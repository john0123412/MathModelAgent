"""写作手 Agent 模块，负责基于建模结果撰写学术论文。"""

import asyncio
from collections import Counter
import json
import re
from typing import Callable
from urllib.parse import unquote

import markdown_it

from app.config.setting import ApiType
from app.core.agents.agent import Agent
from app.core.functions import writer_tools, writer_tools_anthropic
from app.core.llm.llm import LLM
from app.core.llm.types import StandardResponse, ToolCall
from app.core.prompts import get_writer_prompt
from app.schemas.A2A import WriterResponse
from app.schemas.enums import CompTemplate, FormatOutPut
from app.schemas.response import SystemMessage, WriterMessage
from app.services.redis_manager import redis_manager
from app.tools.openalex_scholar import OpenAlexScholar
from app.utils.common_utils import split_footnotes
from app.utils.log_util import logger

MAX_TOOL_ROUNDS = 3

PSEUDO_SEARCH_TOOL_RE = re.compile(
    r"<tool_call>\s*<function=search_papers>(?P<body>.*?)</function>\s*</tool_call>",
    re.DOTALL,
)
PSEUDO_TOOL_PARAM_RE = re.compile(
    r"<parameter=(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)>(?P<value>.*?)</parameter>",
    re.DOTALL,
)


def _has_pseudo_tool_call(content: str) -> bool:
    return bool(PSEUDO_SEARCH_TOOL_RE.search(content or ""))


def _parse_pseudo_search_tool_call(content: str) -> dict | None:
    """Parse XML-like tool text emitted by some OpenAI-compatible models."""
    match = PSEUDO_SEARCH_TOOL_RE.search(content or "")
    if not match:
        return None

    params: dict = {}
    for param in PSEUDO_TOOL_PARAM_RE.finditer(match.group("body")):
        name = param.group("name")
        value = param.group("value").strip()
        if name in {"limit", "year_from", "year_to", "min_citations"}:
            params[name] = int(value) if value and value.lower() != "none" else None
        elif name == "include_web":
            lowered = value.lower()
            params[name] = None if lowered == "none" else lowered == "true"
        elif name == "source_types":
            try:
                params[name] = json.loads(value)
            except json.JSONDecodeError:
                params[name] = [value] if value else None
        else:
            params[name] = value
    return params if params.get("query") else None


def _is_valid_sub_title(sub_title: str | None) -> bool:
    """验证 sub_title 是否属于工作流合法的章节标识符。"""
    if not sub_title:
        return False
    st = sub_title.strip().lower()
    valid_fixed = {
        "firstpage",
        "abstract",
        "repeatques",
        "analysisques",
        "modelassumption",
        "symbol",
        "eda",
        "sensitivity_analysis",
        "judge",
    }
    if st in valid_fixed:
        return True
    if re.fullmatch(r"ques[1-9][0-9]*(_preflight_repair)?", st):
        return True
    return False


def _get_footnote_ranges(lines: list[str]) -> list[tuple[int, int]]:
    """识别正文中所有合法脚注定义的行范围 [start_line, end_line) (0-indexed)。"""
    ranges: list[tuple[int, int]] = []
    n = len(lines)
    i = 0
    while i < n:
        line = lines[i]
        if re.match(r"^\[\^([a-zA-Z0-9_-]+)\]:\s*", line):
            start = i
            i += 1
            while i < n:
                cur = lines[i]
                if cur.startswith("    ") or cur.startswith("\t"):
                    i += 1
                elif cur.strip() == "":
                    if i + 1 < n and (lines[i + 1].startswith("    ") or lines[i + 1].startswith("\t")):
                        i += 1
                    else:
                        break
                else:
                    break
            ranges.append((start, i))
        else:
            i += 1
    return ranges


def _extract_full_footnotes(text: str) -> Counter[tuple[str, str]]:
    """提取完整 Markdown 脚注定义（支持首行、4空格/Tab缩进续行及空行后续段）。

    返回 Counter[tuple[str, str]]：(footnote_idx, normalized_full_definition)。
    """
    footnotes: Counter[tuple[str, str]] = Counter()
    if not text:
        return footnotes

    lines = text.splitlines(True)
    ranges = _get_footnote_ranges(lines)
    for start, end in ranges:
        first_line = lines[start]
        m = re.match(r"^\[\^([a-zA-Z0-9_-]+)\]:\s*(.*)", first_line)
        if m:
            fn_idx = m.group(1)
            def_lines = [m.group(2).strip()]
            for cur_line in lines[start + 1 : end]:
                def_lines.append(cur_line.strip())
            full_def = "\n".join(def_lines).strip()
            normalized_def = re.sub(r"\s+", " ", full_def)
            footnotes[(fn_idx, normalized_def)] += 1

    return footnotes


def _strip_footnote_definitions(text: str) -> str:
    """剥离正文中所有的脚注定义块（含多行缩进续行），避免数值与文本干扰正文比对。"""
    if not text:
        return ""
    lines = text.splitlines(True)
    ranges = _get_footnote_ranges(lines)
    skip_indices: set[int] = set()
    for start, end in ranges:
        for k in range(start, end):
            skip_indices.add(k)

    output_lines = [line for idx, line in enumerate(lines) if idx not in skip_indices]
    return "".join(output_lines)


def _extract_markdown_images_with_spans(
    text: str,
) -> tuple[Counter[tuple[str, str]], list[tuple[int, int]]]:
    """严格使用 MarkdownIt AST 提取真实渲染的图片 (alt, normalized_url) 及其 spans。"""
    images: Counter[tuple[str, str]] = Counter()
    spans: list[tuple[int, int]] = []
    if not text:
        return images, spans

    md = markdown_it.MarkdownIt()
    try:
        tokens = md.parse(text)
    except Exception:
        tokens = []

    def _collect_images(token_list):
        for tok in token_list:
            if tok.type == "image":
                alt = tok.content or ""
                attrs = dict(tok.attrs) if tok.attrs else {}
                src = attrs.get("src", "")
                norm_src = unquote(src.strip())
                images[(alt.strip(), norm_src)] += 1
            if tok.children:
                _collect_images(tok.children)

    _collect_images(tokens)

    # 提取 span 坐标
    pos = 0
    n = len(text)
    while pos < n:
        idx = text.find("![", pos)
        if idx == -1:
            break

        close_bracket = -1
        depth = 0
        i = idx + 2
        while i < n:
            if text[i] == "\\" and i + 1 < n:
                i += 2
                continue
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                if depth == 0:
                    close_bracket = i
                    break
                depth -= 1
            i += 1

        if close_bracket == -1 or close_bracket + 1 >= n or text[close_bracket + 1] != "(":
            pos = idx + 2
            continue

        paren_start = close_bracket + 1
        paren_end = -1
        paren_depth = 0
        in_quote = None
        j = paren_start + 1
        while j < n:
            ch = text[j]
            if ch == "\\" and j + 1 < n:
                j += 2
                continue
            if in_quote:
                if ch == in_quote:
                    in_quote = None
            else:
                if ch in ('"', "'"):
                    in_quote = ch
                elif ch == "(":
                    paren_depth += 1
                elif ch == ")":
                    if paren_depth == 0:
                        paren_end = j
                        break
                    paren_depth -= 1
            j += 1

        if paren_end == -1:
            pos = idx + 2
            continue

        spans.append((idx, paren_end + 1))
        pos = paren_end + 1

    return images, spans


def _detect_pseudo_images_in_non_image_context(
    text: str, image_spans: list[tuple[int, int]]
) -> list[str]:
    """检测在非合法图片上下文中残留的未经转义的伪图片语法 ![...](...)。"""
    disallowed: list[str] = []
    if not text:
        return disallowed

    masked_chars = list(text)
    for start, end in image_spans:
        for k in range(start, min(end, len(masked_chars))):
            masked_chars[k] = " "
    masked_text = "".join(masked_chars)

    for m in re.finditer(r"!\[(.*?)\]", masked_text):
        after_pos = m.end()
        if after_pos < len(masked_text) and masked_text[after_pos] == "(":
            disallowed.append(m.group(0))
        elif "[hidden" in text or "http" in text or "[![" in text or "]:" in text:
            disallowed.append(m.group(0))

    return disallowed


def _detect_disallowed_pandoc_attributes(text: str) -> list[str]:
    """检测并拒绝 Pandoc 属性列表（如 {style="display:none"}、{width=0} 等）及 Fenced div (:::)."""
    disallowed: list[str] = []
    if not text:
        return disallowed

    for m in re.finditer(r"^:::.*", text, re.MULTILINE):
        disallowed.append(m.group(0).strip())

    cleaned = re.sub(r"\$\$.*?\$\$", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"\$.*?\$", "", cleaned)
    cleaned = re.sub(r"\{\[\^\d+\]\s*.*?\}", "", cleaned)

    pat = re.compile(r"\{(?:\s*style\s*=|#|\.|\w+\s*=)[^}]*\}", re.IGNORECASE)
    for match in pat.finditer(cleaned):
        attr_text = match.group(0)
        if any(
            k in attr_text.lower()
            for k in ("display", "visibility", "none", "hidden", "width=0", "height=0", "style=")
        ) or re.search(r"\{[#.][a-zA-Z0-9_-]+\}", attr_text):
            disallowed.append(attr_text)

    return disallowed


def _detect_disallowed_raw_html(text: str) -> list[str]:
    """基于 MarkdownIt AST 识别所有非注释的原始 HTML 标签与容器。"""
    disallowed: list[str] = []
    if not text:
        return disallowed

    md = markdown_it.MarkdownIt()
    try:
        tokens = md.parse(text)
    except Exception:
        return disallowed

    for token in tokens:
        if token.type == "html_block":
            content = token.content.strip()
            if not (content.startswith("<!--") and content.endswith("-->")):
                disallowed.append(content)
        elif token.type == "inline" and token.children:
            for child in token.children:
                if child.type == "html_inline":
                    tag = child.content.strip()
                    if not (tag.startswith("<!--") and tag.endswith("-->")):
                        disallowed.append(tag)

    return disallowed


def _mask_non_semantic_markdown(text: str) -> str:
    """使用 MarkdownIt 语法树将代码块、HTML 注释与多行链接参考定义遮罩为等长空白。"""
    if not text:
        return ""

    lines = text.splitlines(True)
    md = markdown_it.MarkdownIt()
    env: dict = {}
    try:
        tokens = md.parse(text, env)
    except Exception:
        return text

    line_mask = [False] * len(lines)

    # 1. 严格无条件遮罩 fence 与 html_block
    for token in tokens:
        if token.type in ("fence", "html_block"):
            if token.map:
                start, end = token.map
                for line_idx in range(start, min(end, len(line_mask))):
                    line_mask[line_idx] = True

    # 2. 识别真实合法脚注行
    valid_footnote_ranges = _get_footnote_ranges(lines)
    valid_footnote_lines: set[int] = set()
    for start, end in valid_footnote_ranges:
        # 必须确保首行不在已遮罩的 fence/html_block 内
        if not line_mask[start]:
            for k in range(start, end):
                valid_footnote_lines.add(k)

    # 3. 遮罩普通 code_block（排除合法脚注续行）
    for token in tokens:
        if token.type == "code_block":
            if token.map:
                start, end = token.map
                for line_idx in range(start, min(end, len(line_mask))):
                    if line_idx not in valid_footnote_lines:
                        line_mask[line_idx] = True

    # 4. 遮罩非脚注链接参考定义
    references = env.get("references", {})
    for label, ref in references.items():
        if re.fullmatch(r"\^\d+", str(label)):
            continue
        if "map" in ref and ref["map"]:
            start, end = ref["map"]
            for line_idx in range(start, min(end, len(line_mask))):
                line_mask[line_idx] = True

    # 5. 补充扫描器
    in_html_comment = False
    for idx, line in enumerate(lines):
        line_str = line.strip()
        if "<!--" in line_str:
            in_html_comment = True
        if in_html_comment:
            line_mask[idx] = True
            if "-->" in line_str:
                in_html_comment = False
            continue

        if re.match(r"^\[(?![\^]\d+\]).+\]:\s*", line_str):
            line_mask[idx] = True
        elif line_mask[idx - 1] if idx > 0 else False:
            if line.startswith("  ") or line.startswith("\t") or line_str.startswith('"') or line_str.startswith("'"):
                if idx not in valid_footnote_lines:
                    line_mask[idx] = True

    output_lines: list[str] = []
    for idx, line in enumerate(lines):
        if line_mask[idx]:
            output_lines.append(" " * (len(line) - 1) + "\n" if line.endswith("\n") else " " * len(line))
        else:
            output_lines.append(line)

    return "".join(output_lines)


def _extract_protected_compression_tokens(text: str) -> dict:
    """提取受保护要素：标题、公式、引用、脚注定义、图片及数值 Counter。"""
    tokens: dict = {
        "headings": Counter(),
        "block_math": Counter(),
        "inline_math": Counter(),
        "citations": Counter(),
        "inline_citation_bodies": Counter(),
        "footnotes": Counter(),
        "images": Counter(),
        "numbers": Counter(),
    }
    if not text:
        return tokens

    masked_text = _mask_non_semantic_markdown(text)

    # 1. 标题
    for m in re.finditer(r"^(#+)\s*(.*)", masked_text, re.MULTILINE):
        tokens["headings"][(len(m.group(1)), m.group(2).strip())] += 1

    # 2. 独立公式 $$...$$
    for m in re.finditer(r"\$\$(.*?)\$\$", masked_text, re.DOTALL):
        tokens["block_math"][re.sub(r"\s+", " ", m.group(1).strip())] += 1

    # 3. 剥离独立公式后提取行内公式 $...$
    no_block_math = re.sub(r"\$\$.*?\$\$", " ", masked_text, flags=re.DOTALL)
    for m in re.finditer(r"(?<!\$)\$(?!\$)(.*?)(?<!\$)\$(?!\$)", no_block_math):
        tokens["inline_math"][re.sub(r"\s+", " ", m.group(1).strip())] += 1

    # 4. 文献引用标记与正文内容
    for m in re.finditer(r"\{\[\^(\d+)\]\s*(.*?)\}", masked_text):
        idx, body = m.group(1), m.group(2).strip()
        tokens["citations"][idx] += 1
        tokens["inline_citation_bodies"][(idx, re.sub(r"\s+", " ", body))] += 1

    for m in re.finditer(r"\[\^(\d+)\](?!:)", masked_text):
        idx = m.group(1)
        tokens["citations"][idx] += 1

    # 5. 脚注定义
    tokens["footnotes"] = _extract_full_footnotes(masked_text)

    # 6. Markdown 图片（严格使用 AST）
    images_counter, _ = _extract_markdown_images_with_spans(masked_text)
    tokens["images"] = images_counter

    # 7. 全量数值 Counter（剥离公式、引用、脚注定义与图片）
    clean_for_nums = re.sub(r"\$\$.*?\$\$", " ", masked_text, flags=re.DOTALL)
    clean_for_nums = re.sub(r"\$.*?\$", " ", clean_for_nums)
    clean_for_nums = re.sub(r"\{\[\^\d+\]\s*.*?\}", " ", clean_for_nums)
    clean_for_nums = re.sub(r"!\[.*?\]\(.*?\)", " ", clean_for_nums)
    clean_for_nums = _strip_footnote_definitions(clean_for_nums)

    num_pattern = re.compile(r"(?<![a-zA-Z0-9_\u4e00-\u9fa5])-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?(?![a-zA-Z0-9_\u4e00-\u9fa5])")
    for m in num_pattern.finditer(clean_for_nums):
        val_str = m.group(0).strip()
        tokens["numbers"][val_str] += 1

    return tokens


def _verify_compression_integrity(orig: str, comp: str) -> list[str]:
    """严格校验压缩前后的关键要素完整性，返回缺失或篡改项列表。"""
    errors: list[str] = []
    if not comp or not comp.strip():
        errors.append("压缩结果为空文本")
        return errors

    raw_html = _detect_disallowed_raw_html(comp)
    if raw_html:
        errors.append(f"包含未经授权的原始 HTML 标签: {', '.join(raw_html[:3])}")

    pandoc_attrs = _detect_disallowed_pandoc_attributes(comp)
    if pandoc_attrs:
        errors.append(f"包含未经授权的 Pandoc 属性列表: {', '.join(pandoc_attrs[:3])}")

    _, comp_image_spans = _extract_markdown_images_with_spans(comp)
    pseudo_images = _detect_pseudo_images_in_non_image_context(comp, comp_image_spans)
    if pseudo_images:
        errors.append(f"包含未经授权的伪造图片语法: {', '.join(pseudo_images[:3])}")

    orig_tokens = _extract_protected_compression_tokens(orig)
    comp_tokens = _extract_protected_compression_tokens(comp)

    for heading, count in orig_tokens["headings"].items():
        if comp_tokens["headings"][heading] < count:
            errors.append(f"丢失或篡改标题: {heading[1]}")

    for math, count in orig_tokens["block_math"].items():
        if comp_tokens["block_math"][math] < count:
            errors.append(f"丢失独立数学公式: $${math[:30]}...$$")

    for math, count in orig_tokens["inline_math"].items():
        if comp_tokens["inline_math"][math] < count:
            errors.append(f"丢失行内公式: ${math[:30]}$")

    for cit_idx, count in orig_tokens["citations"].items():
        if comp_tokens["citations"][cit_idx] != count:
            errors.append(f"文献引用 [^{cit_idx}] 频次不匹配 (原: {count}, 现: {comp_tokens['citations'][cit_idx]})")

    for (idx, body), count in orig_tokens["inline_citation_bodies"].items():
        if comp_tokens["inline_citation_bodies"][(idx, body)] != count:
            errors.append(f"丢失或篡改文献引用正文: [^{idx}] {body[:30]}")

    for (idx, def_text), count in orig_tokens["footnotes"].items():
        if comp_tokens["footnotes"][(idx, def_text)] != count:
            errors.append(f"丢失或篡改脚注定义: [^{idx}]: {def_text[:30]}")

    for (idx, def_text), count in comp_tokens["footnotes"].items():
        if orig_tokens["footnotes"][(idx, def_text)] < count:
            errors.append(f"新增未经授权的伪造脚注定义: [^{idx}]: {def_text[:30]}")

    for (alt, url), count in orig_tokens["images"].items():
        if comp_tokens["images"][(alt, url)] != count:
            errors.append(f"丢失或篡改图表引用: ![{alt}]({url})")

    for (alt, url), count in comp_tokens["images"].items():
        if orig_tokens["images"][(alt, url)] < count:
            errors.append(f"新增未经授权的伪造图表引用: ![{alt}]({url})")

    for num_str, count in orig_tokens["numbers"].items():
        if comp_tokens["numbers"][num_str] != count:
            errors.append(f"丢失关键数值事实: {num_str} (原出现 {count} 次, 现出现 {comp_tokens['numbers'][num_str]} 次)")

    for num_str, count in comp_tokens["numbers"].items():
        if orig_tokens["numbers"][num_str] < count:
            errors.append(f"新增未经授权的伪造数值事实: {num_str}")

    return errors


class WriterAgent(Agent):
    """写作手 Agent，基于建模和代码执行结果撰写竞赛论文。"""

    def __init__(
        self,
        task_id: str,
        model: LLM,
        comp_template: CompTemplate = CompTemplate.CHINA,
        format_output: FormatOutPut = FormatOutPut.Markdown,
        scholar: OpenAlexScholar | None = None,
        context_window: int = 128000,
        cancel_event: asyncio.Event | None = None,
        user_input_provider: Callable[[], list[str]] | None = None,
    ) -> None:
        super().__init__(
            task_id,
            model,
            context_window,
            cancel_event=cancel_event,
            user_input_provider=user_input_provider,
            guidance_target="writer",
        )
        self.format_out_put = format_output
        self.comp_template = comp_template
        self.scholar = scholar
        self.is_first_run = True
        self.system_prompt = get_writer_prompt(format_output)
        self.available_images: list[str] = []
        # 本轮 run() 中通过 search_papers 成功检索到的真实论文，用于收尾锚定。
        self._retrieved_papers: list[dict] = []

    async def run(  # type: ignore[reportIncompatibleMethodOverride]
        self,
        prompt: str,
        available_images: list[str] | None = None,
        sub_title: str | None = None,
    ) -> WriterResponse:
        """执行写作任务并返回论文内容。"""
        self.chat_history = []
        self._retrieved_papers = []
        if available_images is not None:
            self.available_images = available_images

        system_content = self.system_prompt
        if self.available_images:
            images_list = "\n".join(f"- {img}" for img in self.available_images)
            system_content += f"\n\n可使用的图片列表：\n{images_list}"

        system_msg: dict = {"role": "system", "content": system_content}
        await self.append_chat_history(system_msg)

        user_msg: dict = {"role": "user", "content": prompt}
        await self.append_chat_history(user_msg)

        tools = (
            writer_tools_anthropic
            if (self.model and getattr(self.model, "api_type", None) == ApiType.ANTHROPIC)
            else writer_tools
        )

        response_content = ""
        footnotes: list[tuple[str, str]] = []
        content_response: StandardResponse | None = None
        had_tool_calls = False

        for round_idx in range(MAX_TOOL_ROUNDS):
            response = await self._chat(
                history=self.chat_history,
                tools=tools,
                tool_choice="auto",
                agent_name=self.__class__.__name__,
                sub_title=sub_title,
            )

            if response.tool_calls:
                had_tool_calls = True
                await self._append_assistant_tool_calls_msg(response)
                for tool_call in response.tool_calls:
                    if tool_call.name == "search_papers":
                        tool_result, _papers = await self._execute_search_papers(tool_call)
                        tool_msg: dict = {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_result,
                        }
                        await self.append_chat_history(tool_msg)
                    else:
                        tool_msg = {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": f"工具 {tool_call.name} 不受支持",
                        }
                        await self.append_chat_history(tool_msg)
                continue

            response_content = response.content or ""
            content_response = response
            break

        if had_tool_calls and (content_response is None or not response_content.strip()):
            logger.warning("写作手多轮工具后未产出正文，禁用工具收尾")
            fallback_user_msg = (
                "请基于以上信息直接输出本节完整论文正文，禁止调用任何工具。"
            )
            if self._retrieved_papers:
                pool_lines = []
                for _idx, _p in enumerate(self._retrieved_papers, start=1):
                    _authors = ", ".join(
                        a.get("name", "") for a in (_p.get("authors") or [])[:3] if a.get("name")
                    )
                    _parts = [str(_p.get("title") or "").strip()]
                    if _authors:
                        _parts.append(_authors)
                    if _p.get("publication_year"):
                        _parts.append(str(_p["publication_year"]))
                    if _p.get("venue"):
                        _parts.append(str(_p["venue"]))
                    if _p.get("doi"):
                        _parts.append("DOI: " + str(_p["doi"]))
                    elif _p.get("url"):
                        _parts.append("URL: " + str(_p["url"]))
                    _line = ". ".join(part for part in _parts if part)
                    if _line:
                        pool_lines.append("[" + str(_idx) + "] " + _line)
                citation_pool = "\n".join(pool_lines)
                fallback_user_msg += (
                    "\n\n本轮已检索到以下真实文献，如需引用必须且只能引用这些文献，"
                    "并在文末以规范格式完整列出条目；严禁编造未在列表中的文献编号或使用空头占位符。\n"
                    + citation_pool
                )
            await self.append_chat_history({"role": "user", "content": fallback_user_msg})
            final_response = await self._chat(
                history=self.chat_history,
                tools=[],
                tool_choice=None,
                agent_name=self.__class__.__name__,
                sub_title=sub_title,
            )
            response_content = final_response.content or ""
            content_response = final_response

        if _has_pseudo_tool_call(response_content):
            pseudo_params = _parse_pseudo_search_tool_call(response_content)
            if pseudo_params and self.scholar:
                try:
                    papers = await self.scholar.search_papers(
                        query=pseudo_params["query"],
                        limit=pseudo_params.get("limit", 3),
                        year_from=pseudo_params.get("year_from"),
                        year_to=pseudo_params.get("year_to"),
                        min_citations=pseudo_params.get("min_citations"),
                        source_types=pseudo_params.get("source_types"),
                        include_web=pseudo_params.get("include_web"),
                    )
                    self._retrieved_papers.extend(papers)
                    papers_str = self.scholar.papers_to_str(papers)
                except Exception as exc:
                    papers_str = f"文献检索失败: {type(exc).__name__}"

                await self.append_chat_history(
                    {"role": "assistant", "content": response_content}
                )
                await self.append_chat_history(
                    {
                        "role": "user",
                        "content": (
                            "文献检索结果如下，请基于这些结果直接输出本节论文正文。"
                            "不要输出工具调用标记。若使用文献，必须写成 "
                            "{[^1] 完整引用信息} 格式：\n\n"
                            f"{papers_str}"
                        ),
                    }
                )
                next_response = await self._chat(
                    history=self.chat_history,
                    tools=tools,
                    tool_choice="auto",
                    agent_name=self.__class__.__name__,
                    sub_title=sub_title,
                )
                response_content = next_response.content or ""
                content_response = next_response
                if _has_pseudo_tool_call(response_content):
                    await self.append_chat_history(
                        {"role": "assistant", "content": response_content}
                    )
                    await self.append_chat_history(
                        {
                            "role": "user",
                            "content": (
                                "上一次输出仍然是工具调用标记。现在禁止调用任何工具，"
                                "也不要输出 <tool_call>。请直接按照原写作任务输出完整论文正文；"
                                "如果是模型章节，必须包含“# 五、模型的建立与求解”或对应的 5.x 小节标题。"
                            ),
                        }
                    )
                    final_response = await self._chat(
                        history=self.chat_history,
                        tools=[],
                        tool_choice=None,
                        agent_name=self.__class__.__name__,
                        sub_title=sub_title,
                    )
                    response_content = final_response.content or ""
                    content_response = final_response

        if not response_content.strip():
            logger.warning("写作手输出为空，追加提示并禁用工具重试一次")
            await self.append_chat_history(
                {
                    "role": "user",
                    "content": "上一轮输出为空，请直接输出本章节完整正文。",
                }
            )
            retry_response = await self._chat(
                history=self.chat_history,
                tools=[],
                tool_choice=None,
                agent_name=self.__class__.__name__,
                sub_title=sub_title,
            )
            response_content = retry_response.content or ""
            content_response = retry_response
            if not response_content.strip():
                logger.error("写作手空内容重试后仍为空，原样返回交由上游门禁处理")

        response_content = self._enforce_section_ownership_and_budget(
            response_content, sub_title=sub_title
        )

        max_chars = 12000
        if len(response_content) > max_chars:
            logger.warning(
                f"Writer 章节 {sub_title} 清洗后字数 ({len(response_content)}) 超过预算 ({max_chars})，触发一次性无工具定向压缩"
            )
            compress_prompt = (
                f"【篇幅紧急压缩要求】\n"
                f"当前章节写作内容篇幅达到 {len(response_content)} 字符，超过单章节篇幅预算（{max_chars} 字符）。\n"
                f"请对以下章节内容进行精炼压缩（控制在 10,000 字符以内），要求：\n"
                f"1. 必须 100% 完整保留全部数学公式（包括 $$...$$ 独立公式与 $...$ 行内公式）；\n"
                f"2. 必须 100% 完整保留全部文献引用标记（如 {{[^1] ...}}）；\n"
                f"3. 必须完整保留全部图表引用（如 ![]()）与核心数值结论；\n"
                f"4. 必须保持原有各级标题结构完整；\n"
                f"5. 仅精炼冗长叙述、重复论述与过渡性段落，严禁切除公式、结论或引用。\n\n"
                f"【待压缩正文】\n{response_content}"
            )
            await self.append_chat_history({"role": "user", "content": compress_prompt})
            compress_response = await self._chat(
                history=self.chat_history,
                tools=[],
                tool_choice=None,
                agent_name=self.__class__.__name__,
                sub_title=sub_title,
            )
            compressed_raw = compress_response.content or ""
            compressed_cleaned = self._enforce_section_ownership_and_budget(
                compressed_raw, sub_title=sub_title
            )

            missing_elements = _verify_compression_integrity(
                response_content, compressed_cleaned
            )
            if missing_elements:
                missing_summary = "; ".join(missing_elements)
                logger.error(
                    f"Writer 章节 {sub_title} 压缩结果未通过完整性校验: {missing_summary}"
                )
                raise RuntimeError(
                    f"WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED: 章节 {sub_title} 压缩后丢失关键要素: {missing_summary}"
                )

            if len(compressed_cleaned) > max_chars:
                logger.error(
                    f"Writer 章节 {sub_title} 经一次性压缩后字数仍达到 {len(compressed_cleaned)}（超预算 {max_chars}），触发确定性熔断"
                )
                raise RuntimeError(
                    f"WRITER_SECTION_BUDGET_EXCEEDED: 章节 {sub_title} 长度 ({len(compressed_cleaned)}) 超过 {max_chars} 字符预算，已停止生成"
                )
            response_content = compressed_cleaned
            content_response = compress_response

        # ── 无条件完整性门禁（对所有输出路径生效，含短内容绕过保护）──────────────
        _unconditional_raw_html = _detect_disallowed_raw_html(response_content)
        if _unconditional_raw_html:
            raise RuntimeError(
                f"WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED: 章节 {sub_title} "
                f"包含未经授权的原始 HTML 标签或容器({', '.join(_unconditional_raw_html)})"
            )

        _unconditional_pandoc_attrs = _detect_disallowed_pandoc_attributes(response_content)
        if _unconditional_pandoc_attrs:
            raise RuntimeError(
                f"WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED: 章节 {sub_title} "
                f"包含未经授权的 Pandoc 属性列表({', '.join(_unconditional_pandoc_attrs)})"
            )

        _masked_self = _mask_non_semantic_markdown(response_content)
        if _masked_self != response_content:
            if re.search(r"^\[(?![\^]\d+\])[^\]]+\]:\s*", response_content, re.MULTILINE):
                raise RuntimeError(
                    f"WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED: 章节 {sub_title} "
                    "包含未经授权的非语义链接参考定义"
                )

        response_content, parsed_footnotes = split_footnotes(response_content)
        if parsed_footnotes:
            footnotes = parsed_footnotes

        final_assistant_msg: dict = {"role": "assistant", "content": response_content}
        if content_response and content_response.reasoning_content:
            final_assistant_msg["reasoning_content"] = (
                content_response.reasoning_content
            )
        self.chat_history.append(final_assistant_msg)
        logger.info(f"{self.__class__.__name__}:完成:执行对话")
        return WriterResponse(response_content=response_content, footnotes=footnotes)

    def _enforce_section_ownership_and_budget(
        self, text: str, sub_title: str | None
    ) -> str:
        """限制单章节标题所有权，未知 sub_title 严格 fail-closed 拦截，防止单章生成整篇论文或跨章串标。"""
        if not text:
            return ""
        if not _is_valid_sub_title(sub_title):
            logger.warning(
                f"Writer 收到未授权/未知的章节 sub_title: {sub_title}，fail-closed 拒绝所有内容"
            )
            return ""

        sub_title_clean = sub_title.strip().lower()  # type: ignore[union-attr]
        lines = text.splitlines()
        filtered_lines: list[str] = []

        def _is_explicitly_authorized_heading(line_str: str) -> bool:
            h_match = re.match(r"^(#+)\s*(.*)", line_str)
            if not h_match:
                return False
            level = len(h_match.group(1))
            heading_body = h_match.group(2).strip()

            if sub_title_clean.startswith("ques"):
                match_num = re.search(r"ques(\d+)", sub_title_clean)
                curr_q = int(match_num.group(1)) if match_num else 1
                q_zh = ["一", "二", "三", "四", "五", "六", "七", "八", "九"][curr_q - 1] if 1 <= curr_q <= 9 else str(curr_q)
                other_q_markers = [f"问题{i}" for i in range(1, 10) if i != curr_q] + [
                    f"问题{['一', '二', '三', '四', '五', '六', '七', '八', '九'][i-1]}"
                    for i in range(1, 10)
                    if i != curr_q
                ]
                other_top_chapters = [
                    "一、", "二、", "三、", "四、", "六、", "七、", "八、", "九、",
                    "1、", "2、", "3、", "4、", "6、", "7、", "8、", "9、",
                    "1.", "2.", "3.", "4.", "6.", "7.", "8.", "9.",
                ]

                if level == 1:
                    if any(heading_body.startswith(prefix) for prefix in other_top_chapters):
                        return False
                    if (
                        heading_body.startswith("五、")
                        or heading_body.startswith("5、")
                        or heading_body.startswith("5.")
                        or "模型建立与求解" in heading_body
                        or "模型建立" in heading_body
                        or "模型求解" in heading_body
                        or f"问题{curr_q}" in heading_body
                        or f"问题{q_zh}" in heading_body
                    ):
                        if any(marker in heading_body for marker in other_q_markers):
                            return False
                        return True
                    return False

                if level == 2:
                    m = re.match(r"^5\.(\d+)", heading_body)
                    if m:
                        return int(m.group(1)) == curr_q
                    if f"问题{curr_q}" in heading_body or f"问题{q_zh}" in heading_body:
                        if not any(marker in heading_body for marker in other_q_markers):
                            return True
                    return False

                if level >= 3:
                    m = re.match(r"^5\.(\d+)", heading_body)
                    if m and int(m.group(1)) != curr_q:
                        return False
                    if any(marker in heading_body for marker in other_q_markers):
                        return False
                    return True

            if sub_title_clean == "repeatques":
                other_chapters = ("二、", "三、", "四、", "五、", "六、", "七、", "2、", "3、", "4、", "5、", "6、", "7、", "2.", "3.", "4.", "5.", "6.", "7.")
                if level == 1:
                    if any(heading_body.startswith(p) for p in other_chapters):
                        return False
                    return any(k in heading_body for k in ("一、", "1、", "1.", "问题重述", "问题背景"))
                if level == 2:
                    if any(heading_body.startswith(p) for p in other_chapters):
                        return False
                    return bool(re.match(r"^(1\.\d+|一\.\d+|[（(]?[1-9][)）]?)", heading_body)) or any(k in heading_body for k in ("问题背景", "问题重述", "背景", "重述", "问题"))
                return not any(heading_body.startswith(p) for p in other_chapters)

            if sub_title_clean == "analysisques":
                other_chapters = ("一、", "三、", "四、", "五、", "六、", "七、", "1、", "3、", "4、", "5、", "6、", "7、", "1.", "3.", "4.", "5.", "6.", "7.")
                if level == 1:
                    if any(heading_body.startswith(p) for p in other_chapters):
                        return False
                    return any(k in heading_body for k in ("二、", "2、", "2.", "问题分析"))
                if level == 2:
                    if any(heading_body.startswith(p) for p in other_chapters):
                        return False
                    return bool(re.match(r"^(2\.\d+|二\.\d+|[（(]?[1-9][)）]?)", heading_body)) or any(k in heading_body for k in ("问题", "分析", "思路", "求解思路"))
                return not any(heading_body.startswith(p) for p in other_chapters)

            if sub_title_clean == "modelassumption":
                other_chapters = ("一、", "二、", "四、", "五、", "六、", "七、", "1、", "2、", "4、", "5、", "6、", "7、", "1.", "2.", "4.", "5.", "6.", "7.")
                if level == 1:
                    if any(heading_body.startswith(p) for p in other_chapters):
                        return False
                    return any(k in heading_body for k in ("三、", "3、", "3.", "模型假设", "基本假设", "假设"))
                if level == 2:
                    if any(heading_body.startswith(p) for p in other_chapters):
                        return False
                    return bool(re.match(r"^(3\.\d+|三\.\d+|[（(]?[1-9][)）]?)", heading_body)) or any(k in heading_body for k in ("假设", "基本假设", "符号约定"))
                return not any(heading_body.startswith(p) for p in other_chapters)

            if sub_title_clean == "symbol":
                other_chapters = ("一、", "二、", "三、", "五、", "六、", "七、", "1、", "2、", "3、", "5、", "6、", "7、", "1.", "2.", "3.", "5.", "6.", "7.")
                if level == 1:
                    if any(heading_body.startswith(p) for p in other_chapters):
                        return False
                    return any(k in heading_body for k in ("符号说明", "符号与假设", "四、", "4、", "4."))
                if level == 2:
                    if any(heading_body.startswith(p) for p in other_chapters):
                        return False
                    return bool(re.match(r"^(4\.\d+|四\.\d+|[（(]?[1-9][)）]?)", heading_body)) or any(k in heading_body for k in ("符号说明", "符号", "说明", "变量说明", "参数说明"))
                return not any(heading_body.startswith(p) for p in other_chapters)

            if sub_title_clean == "eda":
                other_chapters = ("一、", "二、", "三、", "五、", "六、", "七、", "1、", "2、", "3、", "5、", "6、", "7、", "1.", "2.", "3.", "5.", "6.", "7.")
                if level == 1:
                    if any(heading_body.startswith(p) for p in other_chapters):
                        return False
                    return any(k in heading_body for k in ("四、", "4、", "4.", "数据探索", "数据预处理", "描述性统计"))
                if level == 2:
                    if any(heading_body.startswith(p) for p in other_chapters):
                        return False
                    return bool(re.match(r"^(4\.\d+|四\.\d+|[（(]?[1-9][)）]?)", heading_body)) or any(k in heading_body for k in ("描述性统计", "数据探索", "数据预处理", "统计分析", "数据清洗", "探索性分析"))
                return not any(heading_body.startswith(p) for p in other_chapters)

            if sub_title_clean == "sensitivity_analysis":
                other_chapters = ("一、", "二、", "三、", "四、", "五、", "1、", "2、", "3、", "4、", "5、", "1.", "2.", "3.", "4.", "5.")
                if level == 1:
                    if any(heading_body.startswith(p) for p in other_chapters):
                        return False
                    return any(k in heading_body for k in ("六、", "6、", "6.", "七、", "7、", "7.", "敏感性", "模型检验", "模型评价", "稳健性", "灵敏度"))
                if level == 2:
                    if any(heading_body.startswith(p) for p in other_chapters):
                        return False
                    return bool(re.match(r"^([67]\.\d+|六\.\d+|七\.\d+|[（(]?[1-9][)）]?)", heading_body)) or any(k in heading_body for k in ("灵敏度", "敏感性", "检验", "稳健性", "误差分析", "稳定性", "扰动分析"))
                return not any(heading_body.startswith(p) for p in other_chapters)

            if sub_title_clean == "judge":
                other_chapters = ("一、", "二、", "三、", "四、", "五、", "六、", "1、", "2、", "3、", "4、", "5、", "6、", "1.", "2.", "3.", "4.", "5.", "6.")
                if level == 1:
                    if any(heading_body.startswith(p) for p in other_chapters):
                        return False
                    return any(k in heading_body for k in ("七、", "7、", "7.", "八、", "8、", "8.", "九、", "9、", "9.", "模型评价", "优缺点", "推广", "结论", "模型的评价"))
                if level == 2:
                    if any(heading_body.startswith(p) for p in other_chapters):
                        return False
                    return bool(re.match(r"^([789]\.\d+|七\.\d+|八\.\d+|九\.\d+|[（(]?[1-9][)）]?)", heading_body)) or any(k in heading_body for k in ("优点", "缺点", "优缺点", "评价", "改进", "推广", "局限性", "总结", "结论"))
                return not any(heading_body.startswith(p) for p in other_chapters)

            if sub_title_clean in ("firstpage", "abstract"):
                numbered_chapter = bool(re.match(r"^([一二三四五六七八九十]+、|[1-9]\d*(?:\.\d+)*\s*|第[一二三四五六七八九十0-9]+章|参考文献|附录)", heading_body))
                if numbered_chapter:
                    return False
                if level == 1:
                    return True
                if level == 2:
                    return any(k in heading_body for k in ("摘要", "关键词", "题目", "论文题目", "Abstract", "Keywords", "Title")) or True
                return True

            return False

        is_skipping = False
        for line in lines:
            line_strip = line.strip()
            h_match = re.match(r"^(#+)\s*(.*)", line_strip)
            if h_match:
                level = len(h_match.group(1))
                if level <= 2:
                    if _is_explicitly_authorized_heading(line_strip):
                        is_skipping = False
                        filtered_lines.append(line)
                    else:
                        is_skipping = True
                    continue
                else:
                    if is_skipping:
                        continue
                    if _is_explicitly_authorized_heading(line_strip):
                        filtered_lines.append(line)
                    else:
                        is_skipping = True
                    continue

            if is_skipping:
                continue

            filtered_lines.append(line)

        cleaned = "\n".join(filtered_lines)
        return cleaned

    async def _append_assistant_tool_calls_msg(
        self, response: StandardResponse
    ) -> None:
        """把带 tool_calls 的 assistant 响应写入对话历史。"""
        assistant_msg: dict = {"role": "assistant", "content": response.content}
        if response.reasoning_content:
            assistant_msg["reasoning_content"] = response.reasoning_content
        assistant_msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for tc in response.tool_calls
        ]
        await self.append_chat_history(assistant_msg)

    async def _execute_search_papers(self, tool_call: ToolCall) -> str:
        """执行 search_papers 工具调用并返回文本结果。"""
        logger.info("调用工具: search_papers")
        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content=f"写作手调用{tool_call.name}工具"),
        )

        arguments = json.loads(tool_call.arguments or "{}")
        query = arguments.get("query", "")

        await redis_manager.publish_message(
            self.task_id,
            WriterMessage(content=query),
        )

        scholar = self.scholar
        try:
            if scholar is None:
                raise RuntimeError("scholar 未初始化")
            papers = await scholar.search_papers(
                query=query,
                limit=arguments.get("limit", 8),
                year_from=arguments.get("year_from"),
                year_to=arguments.get("year_to"),
                min_citations=arguments.get("min_citations"),
                source_types=arguments.get("source_types"),
                include_web=arguments.get("include_web"),
            )
        except Exception as exc:
            error_msg = f"搜索文献失败: {type(exc).__name__}"
            logger.error(error_msg)
            return error_msg, []
        logger.info(f"搜索文献结果已获取: count={len(papers)}")
        self._retrieved_papers.extend(papers)
        return scholar.papers_to_str(papers), papers

    async def summarize(self) -> str:
        """总结对话内容，生成任务执行摘要。"""
        try:
            await self.append_chat_history(
                {"role": "user", "content": "请简单总结以上完成什么任务取得什么结果:"}
            )
            response = await self._chat(
                history=self.chat_history, agent_name=self.__class__.__name__
            )
            response_content = response.content or ""
            summary_msg: dict = {"role": "assistant", "content": response_content}
            if response.reasoning_content:
                summary_msg["reasoning_content"] = response.reasoning_content
            await self.append_chat_history(summary_msg)
            return response_content
        except Exception as exc:
            logger.error(f"总结生成失败: {type(exc).__name__}")
            return "由于网络原因无法生成详细总结，但已完成主要任务处理。"
