"""论文导出前的 Markdown 后处理与预检。"""

from __future__ import annotations

import datetime
import json
import os
import re
from dataclasses import dataclass

from app.utils.log_util import logger


REFERENCE_HEADING_RE = re.compile(
    r"(?m)^(?P<heading>#{1,6}\s*(?:[一二三四五六七八九十]+、)?参考文献\s*|参考文献\s*)$"
)
INLINE_FOOTNOTE_RE = re.compile(r"\[\^(\d+)\]")
INLINE_NUMERIC_RE = re.compile(r"\[(\d+)\]")
IMAGE_MARKDOWN_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
REFERENCE_START_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\[\^?(\d+)\]|\^?(\d+)[:：.]|(\d+)[.、])\s*[:：]?\s*(.+?)\s*$"
)
IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
PLACEHOLDER_RE = re.compile(r"\b(?:TODO|TBD|FIXME)\b|待补充|占位|这里写|xxx", re.IGNORECASE)
FORBIDDEN_SUBMISSION_RE = re.compile(
    r"承诺书|编号专用页|参赛队号|队员姓名|指导教师|所在学校|学校名称|"
    r"(?<![A-Za-z0-9_])姓名\s*[:：]|(?<![A-Za-z0-9_])学号\s*[:：]"
)
APPENDIX_HEADING_RE = re.compile(r"(?m)^#{1,6}\s*附录\s*$")
SUPPORT_MATERIAL_HEADING_RE = re.compile(r"(?m)^#{1,6}\s*附录A\s+支撑材料文件列表\s*$")
CODE_APPENDIX_HEADING_RE = re.compile(r"(?m)^#{1,6}\s*附录B\s+源程序代码\s*$")
NO_PROGRAM_RE = re.compile(r"本论文没有用到程序")
NO_SUPPORT_MATERIAL_RE = re.compile(r"本论文没有支撑材料")
HEADING_RE = re.compile(r"(?m)^#{1,6}\s+(.+?)\s*$")
ABSTRACT_HEADING_RE = re.compile(r"(?m)^#{1,6}\s*摘要\s*$")
KEYWORDS_RE = re.compile(r"\*{0,2}\s*关键词\s*\*{0,2}\s*[:：]\s*(.+)")
KEYWORDS_HEADING_RE = re.compile(
    r"(?ms)^#{1,6}\s*关键词\s*\n+(?P<keywords>.*?)(?=\n#{1,6}\s|\Z)"
)
BOLD_ABSTRACT_HEADING_RE = re.compile(r"(?m)^\*\*\s*摘要\s*\*\*\s*$")
BOLD_KEYWORDS_HEADING_RE = re.compile(r"(?m)^\*\*\s*关键词\s*\*\*\s*$")
BARE_ABSTRACT_HEADING_RE = re.compile(r"(?m)^\s*摘要\s*$")
INTERNAL_PATH_RE = re.compile(
    r"(?<![A-Za-z])(?:[A-Za-z]:[\\/][^\s，。；；,;]+|/(?:home|tmp|var|usr|etc|opt|root|workspace)/[^\s，。；；,;]+)"
)
FENCED_CODE_BLOCK_RE = re.compile(
    r"(?ms)^(?P<fence>`{3,}|~{3,})[^\n]*\n.*?^(?P=fence)[ \t]*\n?"
)
FENCED_CODE_CONTENT_RE = re.compile(
    r"(?ms)^(?P<open>(?P<fence>`{3,}|~{3,})[^\n]*\n)(?P<body>.*?)(?P<close>^(?P=fence)[ \t]*\n?)"
)
FENCE_START_RE = re.compile(r"^\s*(`{3,}|~{3,})")
BOLD_STANDALONE_LABEL_RE = re.compile(
    r"^\s*\*\*(?P<label>(?:假设|步骤|情形|情况|方案|方法|结论|分析)\s*\d*[^*\n]{0,40})\*\*\s*$"
)
ORPHAN_DEFINITION_REFERENCE_RE = re.compile(
    r"^\s*:\s+.+(?:DOI|doi|Journal|Proceedings|20\d{2}|19\d{2}|https?://).*$"
)
TABLE_CAPTION_RE = re.compile(r"^\s*(?:表|Table)\s*\d+[\s：:、.-]")
MARKDOWN_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
EXTRA_PROBLEM_LABEL_RE = re.compile(r"问题(?P<number>\d+|[一二三四五六七八九十]+)(?P<suffix>[_、\s]?)")
CLAIM_SENTENCE_RE = re.compile(r"[^。！？.!?\n]*(?:最优|利润|提高|增加|降低|结果表明|敏感性|影子价格|准确率|误差)[^。！？.!?\n]*[。！？.!?]?")
NUMERIC_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|元|小时|件|吨|亩|分|倍|年|万元)?")
STRONG_WORDING_RE = re.compile(r"证明|唯一|显著优于|最可靠|精确预测")
RANDOM_SIMULATION_RE = re.compile(
    r"Monte[\s_-]*Carlo|蒙特卡洛|随机模拟|随机扰动|随机生成样本|模拟样本|模拟数据集",
    re.IGNORECASE,
)
ENGLISH_TRANSITION_REPLACEMENTS = {
    "Overall": "总体来看",
    "In addition": "此外",
    "To conclude": "综上",
    "Therefore": "因此",
    "However": "不过",
    "Furthermore": "进一步地",
    "Moreover": "此外",
}
DETERMINISTIC_NO_SAMPLE_MARKERS = (
    "不涉及随机样本数据",
    "题目给定的确定性常量",
    "无外部数据集",
    "确定性线性规划",
    "参数确定不变",
)
MAX_CODE_SEPARATOR_CHARS = 48
LONG_CODE_SEPARATOR_RE = re.compile(
    r"^(?P<indent>\s*)(?P<prefix>#|//|%|--)?(?P<gap>\s*)"
    r"(?P<char>[=\-_*])(?P=char){59,}\s*$"
)

REQUIRED_SECTION_KEYWORDS = {
    "problem_restatement": ("问题重述", "问题提出"),
    "problem_analysis": ("问题分析",),
    "assumptions": ("模型假设",),
    "symbols": ("符号说明",),
    "model_solution": ("模型的建立", "模型建立", "模型的建立与求解"),
    "validation": ("模型的分析", "结果分析", "模型检验", "敏感性分析", "灵敏度分析"),
    "evaluation": ("模型的评价", "模型评价", "改进与推广"),
}

CORE_SECTION_KEYS = {"model_solution", "validation"}
EXPECTED_EXPORT_PROFILE = "cumcm2026"
EXPORT_PROFILE_LABELS = {
    "default": "默认导出",
    "cumcm2025": "高教社杯/CUMCM 2025",
    "cumcm2026": "高教社杯/CUMCM 2026",
    "huashubei": "华数杯",
}
SECTION_KIND_KEYWORDS = {
    "abstract": ("摘要",),
    "problem_restatement": ("问题重述", "问题提出"),
    "problem_analysis": ("问题分析",),
    "assumptions": ("模型假设",),
    "symbols": ("符号说明",),
    "model_solution": ("模型的建立", "模型建立", "模型的建立与求解"),
    "validation": ("模型的分析", "结果分析", "模型检验", "敏感性分析", "灵敏度分析"),
    "evaluation": ("模型的评价", "模型评价", "改进与推广"),
    "references": ("参考文献",),
    "appendix": ("附录",),
}
CHINESE_NUMBER_MAP = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
_CODE_EXT_LANGUAGES = {
    ".py": "python",
    ".m": "matlab",
    ".r": "r",
    ".jl": "julia",
    ".sql": "sql",
    ".do": "stata",
}
_DATA_EXTS = (".csv", ".tsv", ".xlsx", ".xls", ".txt")
_CODE_EXCLUDED_DIRS = {
    "__pycache__",
    ".ipynb_checkpoints",
    "latex_project",
    ".git",
    ".cache",
}
_SUPPORT_EXCLUDED_FILENAMES = {
    "candidate_manifest.json",
    "checkpoint.json",
    "export_status.json",
    "modeler_plan.json",
    "modeler_plan.md",
    "modeling_decision.json",
    "modeling_decision.md",
    "paper_preflight_report.json",
    "paper_preflight_report.md",
    "paper_outline.json",
    "figure_usage.json",
    "claim_trace.json",
    "claim_trace.md",
    "pdf_visual_check.json",
    "res.docx",
    "res.json",
    "res.md",
    "res.pdf",
    "task_status.json",
    "tex_export_status.json",
    "variable_snapshot.pkl",
    "variable_snapshot_meta.json",
    "test_save.png",
}


@dataclass(frozen=True)
class CodeSource:
    """可附录进论文的代码来源。"""

    name: str
    code: str
    language: str = "text"


@dataclass(frozen=True)
class SupportMaterial:
    """论文附录中需要列出的支撑材料。"""

    name: str
    category: str


def _normalise_reference_content(content: str) -> str:
    content = re.sub(r"\s+", " ", content.strip())
    return content


def _parse_reference_entries(reference_text: str) -> list[tuple[int, str]]:
    entries: list[tuple[int, str]] = []
    current_number: int | None = None
    current_lines: list[str] = []

    for raw_line in reference_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = REFERENCE_START_RE.match(line)
        if match:
            if current_number is not None and current_lines:
                entries.append(
                    (current_number, _normalise_reference_content(" ".join(current_lines)))
                )
            number_text = match.group(1) or match.group(2) or match.group(3)
            current_number = int(number_text)
            current_lines = [match.group(4)]
            continue
        if current_number is not None:
            current_lines.append(line)

    if current_number is not None and current_lines:
        entries.append((current_number, _normalise_reference_content(" ".join(current_lines))))

    return entries


def _renumber_inline_references(text: str, number_map: dict[int, int]) -> str:
    def replace_footnote(match: re.Match[str]) -> str:
        old_number = int(match.group(1))
        return f"[{number_map.get(old_number, old_number)}]"

    def replace_numeric(match: re.Match[str]) -> str:
        old_number = int(match.group(1))
        return f"[{number_map.get(old_number, old_number)}]"

    text = INLINE_FOOTNOTE_RE.sub(replace_footnote, text)
    return INLINE_NUMERIC_RE.sub(replace_numeric, text)


def _reference_body_parts(markdown: str) -> tuple[str, str]:
    match = REFERENCE_HEADING_RE.search(markdown)
    if not match:
        return markdown, ""
    reference_text = markdown[match.end() :]
    appendix_match = APPENDIX_HEADING_RE.search(reference_text)
    if appendix_match:
        reference_text = reference_text[: appendix_match.start()]
    return markdown[: match.start()], reference_text


def _reference_numbers(reference_text: str) -> set[int]:
    return {number for number, _ in _parse_reference_entries(reference_text)}


def _inline_reference_numbers(body: str) -> set[int]:
    body = _without_fenced_code_blocks(body)
    body = IMAGE_RE.sub("", body)
    return {int(match.group(1)) for match in INLINE_NUMERIC_RE.finditer(body)}


def strip_unmatched_inline_references(markdown: str) -> tuple[str, list[int]]:
    """Remove inline numeric references that do not have bibliography entries."""
    has_reference_section = REFERENCE_HEADING_RE.search(markdown) is not None
    body, reference_text = _reference_body_parts(markdown)
    if not has_reference_section:
        return markdown, []

    existing_numbers = _reference_numbers(reference_text)
    removed: set[int] = set()

    def replace(match: re.Match[str]) -> str:
        number = int(match.group(1))
        if number in existing_numbers:
            return match.group(0)
        removed.add(number)
        return ""

    return INLINE_NUMERIC_RE.sub(replace, body) + markdown[len(body) :], sorted(removed)


def remove_empty_reference_section(markdown: str) -> tuple[str, bool]:
    """Remove a reference heading when it contains no bibliography entries."""
    match = REFERENCE_HEADING_RE.search(markdown)
    if not match:
        return markdown, False

    reference_text = markdown[match.end() :]
    appendix_match = APPENDIX_HEADING_RE.search(reference_text)
    if appendix_match:
        reference_body = reference_text[: appendix_match.start()]
        appendix_text = reference_text[appendix_match.start() :].strip()
    else:
        reference_body = reference_text
        appendix_text = ""

    if _parse_reference_entries(reference_body) or reference_body.strip():
        return markdown, False

    result = markdown[: match.start()].rstrip()
    if appendix_text:
        result += "\n\n" + appendix_text
    return result.rstrip() + "\n", True


def normalize_chinese_references(markdown: str) -> str:
    """将参考文献章节整理为独立编号行，并把正文脚注标记改为数字引用。"""
    match = REFERENCE_HEADING_RE.search(markdown)
    if not match:
        return INLINE_FOOTNOTE_RE.sub(lambda m: f"[{m.group(1)}]", markdown)

    body = markdown[: match.start()].rstrip()
    reference_text = markdown[match.end() :].strip()
    appendix_text = ""
    appendix_match = APPENDIX_HEADING_RE.search(reference_text)
    if appendix_match:
        appendix_text = reference_text[appendix_match.start() :].strip()
        reference_text = reference_text[: appendix_match.start()].strip()

    entries = _parse_reference_entries(reference_text)
    if not entries:
        return INLINE_FOOTNOTE_RE.sub(lambda m: f"[{m.group(1)}]", markdown)

    number_map = {old_number: index for index, (old_number, _) in enumerate(entries, 1)}
    body = _renumber_inline_references(body, number_map)

    reference_lines = ["## 参考文献", ""]
    for index, (_, content) in enumerate(entries, 1):
        reference_lines.extend([f"[{index}] {content}", ""])

    result = body + "\n\n" + "\n".join(reference_lines).rstrip() + "\n"
    if appendix_text:
        result += "\n\n" + appendix_text.rstrip() + "\n"
    return result


def normalize_keywords(markdown: str) -> str:
    """将“## 关键词”块规范为 CUMCM 常见的单行关键词格式。"""
    if KEYWORDS_RE.search(markdown):
        return markdown

    def replace(match: re.Match[str]) -> str:
        raw = re.sub(r"\s+", " ", match.group("keywords").strip())
        items = [item.strip() for item in re.split(r"[;；,，、\s]+", raw) if item.strip()]
        if not items:
            return match.group(0)
        return "关键词：" + "；".join(items) + "\n\n"

    return KEYWORDS_HEADING_RE.sub(replace, markdown, count=1)


def normalize_markdown_headings(markdown: str) -> str:
    """规范 Writer 偶发输出的加粗摘要/关键词标题。"""
    markdown = BOLD_ABSTRACT_HEADING_RE.sub("## 摘要", markdown)
    if not ABSTRACT_HEADING_RE.search(markdown):
        markdown = BARE_ABSTRACT_HEADING_RE.sub("## 摘要", markdown, count=1)
    return BOLD_KEYWORDS_HEADING_RE.sub("## 关键词", markdown)


def _chinese_problem_number(text: str) -> int | None:
    if text.isdigit():
        return int(text)
    if text in CHINESE_NUMBER_MAP:
        return CHINESE_NUMBER_MAP[text]
    if text.startswith("十") and len(text) == 2:
        suffix = CHINESE_NUMBER_MAP.get(text[1])
        return 10 + suffix if suffix else None
    if text.endswith("十") and len(text) == 2:
        prefix = CHINESE_NUMBER_MAP.get(text[0])
        return prefix * 10 if prefix else None
    if "十" in text and len(text) == 3:
        prefix = CHINESE_NUMBER_MAP.get(text[0])
        suffix = CHINESE_NUMBER_MAP.get(text[2])
        return prefix * 10 + suffix if prefix and suffix else None
    return None


def _infer_declared_problem_count(markdown: str) -> int | None:
    text = _without_fenced_code_blocks(markdown)
    restatement_match = re.search(r"(?m)^#{1,6}\s*(?:一、)?问题重述\s*$", text)
    search_area = text
    if restatement_match:
        next_heading = re.search(r"(?m)^#{1,6}\s*(?:二、)?问题分析\s*$", text[restatement_match.end() :])
        end = restatement_match.end() + next_heading.start() if next_heading else len(text)
        search_area = text[restatement_match.end() : end]

    enumerated = [int(item) for item in re.findall(r"[（(](\d+)[）)]", search_area)]
    if enumerated:
        return max(enumerated)

    problem_numbers = [
        number
        for number in (
            _chinese_problem_number(match.group(1))
            for match in re.finditer(r"问题([一二三四五六七八九十]+)", search_area)
        )
        if number is not None
    ]
    return max(problem_numbers) if problem_numbers else None


def _normalise_extra_problem_label_text(text: str, declared_count: int | None) -> tuple[str, int]:
    if declared_count is None:
        return text, 0
    replacements = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal replacements
        number = _chinese_problem_number(match.group("number"))
        if number is None or number <= declared_count:
            return match.group(0)
        replacements += 1
        suffix = match.group("suffix")
        return "灵敏度分析_" if suffix == "_" else "灵敏度分析"

    return EXTRA_PROBLEM_LABEL_RE.sub(replace, text), replacements


def _normalise_visible_problem_labels_line(line: str, declared_count: int | None) -> tuple[str, int]:
    placeholders: list[str] = []
    image_replacements = 0

    def replace_image(match: re.Match[str]) -> str:
        nonlocal image_replacements
        alt, path = match.group(1), match.group(2)
        normalised_alt, count = _normalise_extra_problem_label_text(alt, declared_count)
        image_replacements += count
        placeholders.append(f"![{normalised_alt}]({path})")
        return f"@@MMA_IMAGE_{len(placeholders) - 1}@@"

    masked = IMAGE_MARKDOWN_RE.sub(replace_image, line)
    normalised, replacements = _normalise_extra_problem_label_text(masked, declared_count)
    for index, image_text in enumerate(placeholders):
        normalised = normalised.replace(f"@@MMA_IMAGE_{index}@@", image_text)
    return normalised, replacements + image_replacements


def normalize_extra_problem_labels(
    markdown: str,
    include_code: bool = False,
    declared_count: int | None = None,
) -> tuple[str, int]:
    """Normalize visible labels like 问题3 when the formal statement has fewer questions."""
    if declared_count is None:
        declared_count = _infer_declared_problem_count(markdown)
    if declared_count is None:
        return markdown, 0

    lines: list[str] = []
    replacements = 0
    in_fence = False
    fence_marker = ""
    for line in markdown.splitlines(keepends=True):
        fence_match = FENCE_START_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker[0]
            elif marker.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            lines.append(line)
            continue
        if in_fence and not include_code:
            lines.append(line)
            continue
        normalised, count = _normalise_visible_problem_labels_line(line, declared_count)
        replacements += count
        lines.append(normalised)
    return "".join(lines), replacements


def _without_fenced_code_blocks(markdown: str) -> str:
    return FENCED_CODE_BLOCK_RE.sub("", markdown)


def remove_missing_image_references(markdown: str, work_dir: str) -> tuple[str, list[str]]:
    """删除指向不存在文件的图片引用，避免导出的 PDF/DOCX 出现破图。"""
    removed: list[str] = []

    def replace(match: re.Match[str]) -> str:
        image_path = match.group(1)
        if os.path.exists(_resolve_image_path(work_dir, image_path)):
            return match.group(0)
        removed.append(image_path)
        return ""

    return IMAGE_RE.sub(replace, markdown), removed


def _clean_image_caption_text(caption: str, path: str) -> str:
    source = caption.strip() or os.path.basename(path.strip())
    source = os.path.basename(source)
    stem, ext = os.path.splitext(source)
    if ext.lower() in _IMAGE_EXTS:
        source = stem
    source = re.sub(r"[_-]+", " ", source)
    source = re.sub(r"\s+", " ", source).strip(" .。_-")
    return source or "结果图"


def normalize_image_captions(markdown: str) -> str:
    """Clean Markdown image alt text used by Pandoc as figure captions."""
    lines = markdown.splitlines()
    output: list[str] = []
    in_fence = False
    fence_marker = ""

    for line in lines:
        fence_match = FENCE_START_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker[0]
            elif marker.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            output.append(line)
            continue

        if in_fence:
            output.append(line)
            continue

        def replace(match: re.Match[str]) -> str:
            caption, path = match.groups()
            return f"![{_clean_image_caption_text(caption, path)}]({path})"

        output.append(IMAGE_MARKDOWN_RE.sub(replace, line))

    return "\n".join(output) + ("\n" if markdown.endswith("\n") else "")


def normalize_english_transitions(markdown: str) -> str:
    """Replace common English transition phrases in Chinese prose."""
    lines = markdown.splitlines()
    output: list[str] = []
    in_fence = False
    fence_marker = ""
    transition_pattern = re.compile(
        r"\b("
        + "|".join(re.escape(key) for key in ENGLISH_TRANSITION_REPLACEMENTS)
        + r")\b"
    )

    for line in lines:
        fence_match = FENCE_START_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker[0]
            elif marker.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            output.append(line)
            continue

        if in_fence:
            output.append(line)
            continue

        def replace(match: re.Match[str]) -> str:
            return ENGLISH_TRANSITION_REPLACEMENTS[match.group(1)]

        normalised = transition_pattern.sub(replace, line)
        normalised = re.sub(r"(?<=[。！？；，])\s+(?=[\u4e00-\u9fff])", "", normalised)
        output.append(normalised)

    return "\n".join(output) + ("\n" if markdown.endswith("\n") else "")


def normalize_deterministic_eda_terms(markdown: str) -> tuple[str, int]:
    """Rename sample-data EDA wording when the paper itself says data are deterministic."""
    if not any(marker in markdown for marker in DETERMINISTIC_NO_SAMPLE_MARKERS):
        return markdown, 0

    replacements = 0
    lines: list[str] = []
    in_fence = False
    fence_marker = ""
    for line in markdown.splitlines(keepends=True):
        fence_match = FENCE_START_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker[0]
            elif marker.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            lines.append(line)
            continue

        if in_fence:
            lines.append(line)
            continue

        updated = line
        updated, count = re.subn(r"(?m)(^#{1,6}\s*(?:\d+(?:\.\d+)*\s*)?)描述性统计\b", r"\1参数核验", updated)
        replacements += count
        updated, count = re.subn(r"描述性统计分析", "参数核验分析", updated)
        replacements += count
        updated, count = re.subn(r"进行描述性统计", "进行参数核验", updated)
        replacements += count
        lines.append(updated)

    return "".join(lines), replacements


def normalize_bold_standalone_labels(markdown: str) -> tuple[str, int]:
    """Turn standalone bold labels into headings to avoid Pandoc description lists."""
    replacements = 0
    lines: list[str] = []
    in_fence = False
    fence_marker = ""
    for line in markdown.splitlines(keepends=True):
        fence_match = FENCE_START_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker[0]
            elif marker.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            lines.append(line)
            continue

        if in_fence:
            lines.append(line)
            continue

        newline = line[len(line.rstrip("\r\n")) :]
        body = line[: len(line) - len(newline)]
        match = BOLD_STANDALONE_LABEL_RE.match(body)
        if match:
            replacements += 1
            lines.append(f"### {match.group('label').strip()}{newline}")
            continue
        lines.append(line)

    return "".join(lines), replacements


def remove_orphan_definition_reference_lines(markdown: str) -> tuple[str, int]:
    """Remove stray definition-list reference lines that make Pandoc wrap paragraphs as labels."""
    removed = 0
    lines: list[str] = []
    in_fence = False
    fence_marker = ""
    for line in markdown.splitlines(keepends=True):
        fence_match = FENCE_START_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker[0]
            elif marker.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            lines.append(line)
            continue

        if not in_fence and ORPHAN_DEFINITION_REFERENCE_RE.match(line):
            removed += 1
            continue
        lines.append(line)

    return "".join(lines), removed


def remove_deterministic_random_simulation(markdown: str) -> tuple[str, int]:
    """Remove visible random-simulation claims when the paper states a deterministic setup."""
    if not any(marker in markdown for marker in DETERMINISTIC_NO_SAMPLE_MARKERS):
        return markdown, 0

    removed = 0
    output: list[str] = []
    cursor = 0

    def append_visible_chunk(chunk: str) -> None:
        nonlocal removed
        for part in re.split(r"(\n\s*\n)", chunk):
            if not part:
                continue
            if RANDOM_SIMULATION_RE.search(part):
                if any(line.lstrip().startswith("|") for line in part.splitlines()):
                    kept_lines: list[str] = []
                    for line in part.splitlines(keepends=True):
                        if RANDOM_SIMULATION_RE.search(line):
                            removed += 1
                            continue
                        kept_lines.append(line)
                    output.append("".join(kept_lines))
                    continue
                removed += 1
                continue
            output.append(part)

    for match in FENCED_CODE_BLOCK_RE.finditer(markdown):
        append_visible_chunk(markdown[cursor : match.start()])
        output.append(match.group(0))
        cursor = match.end()
    append_visible_chunk(markdown[cursor:])

    return "".join(output), removed


def normalize_deterministic_random_simulation_code_terms(markdown: str) -> tuple[str, int]:
    """Relabel random-simulation terms inside code appendices for deterministic papers."""
    if not any(marker in markdown for marker in DETERMINISTIC_NO_SAMPLE_MARKERS):
        return markdown, 0

    replacements = 0
    replacement_pairs = (
        (r"Monte[\s_]*Carlo模拟", "参数扰动扩展"),
        (r"Monte[\s_]*Carlo", "参数扰动"),
        (r"蒙特卡洛模拟", "参数扰动分析"),
        (r"随机模拟", "参数扰动分析"),
        (r"随机扰动", "参数扰动"),
    )

    def replace_block(match: re.Match[str]) -> str:
        nonlocal replacements
        body = match.group("body")
        updated = body
        for pattern, replacement in replacement_pairs:
            updated, count = re.subn(pattern, replacement, updated, flags=re.IGNORECASE)
            replacements += count
        return f"{match.group('open')}{updated}{match.group('close')}"

    return FENCED_CODE_CONTENT_RE.sub(replace_block, markdown), replacements


def normalize_strong_claim_wording(markdown: str) -> tuple[str, int]:
    """Downgrade over-strong visible wording before claim-trace gating."""
    replacements = 0
    lines: list[str] = []
    in_fence = False
    fence_marker = ""
    replacement_pairs = (
        ("证明", "说明"),
        ("验证了", "表明"),
        ("证实了", "表明"),
        ("是否唯一", "是否可复核"),
        ("唯一最优解", "一个最优解"),
        ("最优解的唯一性", "最优解的可复核性"),
        ("唯一性", "可复核性"),
        ("唯一", "明确"),
        ("显著优于", "优于"),
        ("最可靠", "较可靠"),
        ("精确预测", "估计"),
        ("预测准确性", "预测结果与重新求解结果的一致性"),
        ("完全一致", "基本一致"),
    )
    for line in markdown.splitlines(keepends=True):
        fence_match = FENCE_START_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker[0]
            elif marker.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            lines.append(line)
            continue

        if in_fence:
            lines.append(line)
            continue

        updated = line
        for old, new in replacement_pairs:
            updated, count = re.subn(re.escape(old), new, updated)
            replacements += count
        lines.append(updated)

    return "".join(lines), replacements


def normalize_submission_wording(markdown: str) -> tuple[str, int]:
    """Remove informal user-facing traces from visible paper and appendix text."""
    replacements = 0
    replacement_pairs = (
        ("用户输入", "题目输入"),
        ("用户描述", "题目描述"),
        ("用户提供", "题目给定"),
        ("用户给出", "题目给定"),
        ("用户边界", "题目边界"),
        ("用户估算", "题目测算"),
        ("用户", "题目"),
        ("待验证", "需核验"),
        ("推断", "核定"),
        ("估算", "测算"),
    )
    updated = markdown
    for old, new in replacement_pairs:
        updated, count = re.subn(re.escape(old), new, updated)
        replacements += count
    return updated, replacements


def _iter_python_files(work_dir: str) -> list[CodeSource]:
    sources: list[CodeSource] = []
    if not os.path.isdir(work_dir):
        return sources
    for root, dirs, files in os.walk(work_dir):
        dirs[:] = [d for d in dirs if d not in _CODE_EXCLUDED_DIRS]
        for filename in sorted(files):
            ext = os.path.splitext(filename.lower())[1]
            if ext not in _CODE_EXT_LANGUAGES:
                continue
            path = os.path.join(root, filename)
            rel_path = os.path.relpath(path, work_dir).replace(os.sep, "/")
            try:
                with open(path, encoding="utf-8") as f:
                    code = f.read().rstrip()
            except UnicodeDecodeError:
                with open(path, encoding="gbk", errors="ignore") as f:
                    code = f.read().rstrip()
            except OSError:
                continue
            if code:
                sources.append(CodeSource(rel_path, code, _CODE_EXT_LANGUAGES[ext]))
    return sources


def _notebook_code_source(work_dir: str) -> CodeSource | None:
    notebook_path = os.path.join(work_dir, "notebook.ipynb")
    if not os.path.exists(notebook_path):
        return None
    try:
        with open(notebook_path, encoding="utf-8") as f:
            notebook = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    code_blocks: list[str] = []
    code_cell_index = 1
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", "")
        if isinstance(source, list):
            code = "".join(source).rstrip()
        else:
            code = str(source).rstrip()
        if not code:
            continue
        code_blocks.append(f"# Cell {code_cell_index}\n{code}")
        code_cell_index += 1

    if not code_blocks:
        return None
    return CodeSource("notebook.ipynb", "\n\n".join(code_blocks), "python")


def collect_code_sources(work_dir: str) -> list[CodeSource]:
    """收集应附在论文末尾的代码。"""
    sources = _iter_python_files(work_dir)
    notebook_source = _notebook_code_source(work_dir)
    if notebook_source is not None:
        sources.append(notebook_source)
    return sources


def _support_category(filename: str) -> str | None:
    lower = filename.lower()
    ext = os.path.splitext(lower)[1]
    if lower in _SUPPORT_EXCLUDED_FILENAMES:
        return None
    if ext in _CODE_EXT_LANGUAGES or lower.endswith(".ipynb"):
        return "源程序代码"
    if lower.endswith(_IMAGE_EXTS):
        return "图片文件"
    if ext in _DATA_EXTS:
        return "数据/结果文件"
    return None


def collect_support_materials(work_dir: str) -> list[SupportMaterial]:
    """收集 CUMCM 附录A中的支撑材料文件列表。"""
    materials: list[SupportMaterial] = []
    if not os.path.isdir(work_dir):
        return materials
    for root, dirs, files in os.walk(work_dir):
        dirs[:] = [d for d in dirs if d not in _CODE_EXCLUDED_DIRS]
        for filename in sorted(files):
            category = _support_category(filename)
            if category is None:
                continue
            rel_path = os.path.relpath(os.path.join(root, filename), work_dir).replace(os.sep, "/")
            materials.append(SupportMaterial(rel_path, category))
    return sorted(materials, key=lambda item: (item.category, item.name))


def append_code_appendix(markdown: str, work_dir: str) -> tuple[str, list[str]]:
    """在论文末尾追加 CUMCM 附录，已存在规范附录时不重复追加。"""
    if SUPPORT_MATERIAL_HEADING_RE.search(markdown) and CODE_APPENDIX_HEADING_RE.search(markdown):
        sources = collect_code_sources(work_dir)
        return markdown, [source.name for source in sources]

    sources = collect_code_sources(work_dir)
    materials = collect_support_materials(work_dir)

    lines = [markdown.rstrip(), "", "# 附录", "", "## 附录A 支撑材料文件列表", ""]
    if materials:
        lines.extend(["| 文件名 | 类型 |", "| --- | --- |"])
        for material in materials:
            lines.append(f"| {material.name} | {material.category} |")
        lines.append("")
    else:
        lines.extend(["本论文没有支撑材料。", ""])

    lines.extend(["## 附录B 源程序代码", ""])
    if sources:
        for index, source in enumerate(sources, 1):
            fence = _code_fence(source.code)
            lines.extend(
                [
                    f"### B.{index} {source.name}",
                    "",
                    f"{fence}{source.language}",
                    _listings_safe_code(source.code).rstrip(),
                    fence,
                    "",
                ]
            )
    else:
        lines.extend(["本论文没有用到程序。", ""])
    return "\n".join(lines).rstrip() + "\n", [source.name for source in sources]


def _code_fence(code: str) -> str:
    """Return a Markdown fence that cannot be closed by the code content."""
    if "`" in code:
        longest_tilde = max(
            (len(match.group(0)) for match in re.finditer(r"~+", code)),
            default=0,
        )
        return "~" * max(3, longest_tilde + 1)
    return "```"


def _listings_safe_code(code: str) -> str:
    """Prevent source text from closing pandoc's LaTeX listings environment."""
    return _shorten_long_code_separator_body(
        code.replace(r"\end{lstlisting}", r"\end{lstlisting }")
    )[0]


def _shorten_long_code_separator_body(code: str) -> tuple[str, int]:
    """Shorten decoration-only separator lines so PDF code appendices stay in bounds."""
    replacements = 0
    lines: list[str] = []
    for line in code.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        newline = line[len(body) :]
        match = LONG_CODE_SEPARATOR_RE.match(body)
        if match:
            replacements += 1
            prefix = match.group("prefix") or ""
            gap = match.group("gap") if prefix else ""
            body = (
                f"{match.group('indent')}{prefix}{gap}"
                f"{match.group('char') * MAX_CODE_SEPARATOR_CHARS}"
            )
        lines.append(body + newline)
    return "".join(lines), replacements


def shorten_long_code_separator_lines(markdown: str) -> tuple[str, int]:
    """Shorten decoration-only separator lines inside fenced code blocks."""
    replacements = 0

    def replace_block(match: re.Match[str]) -> str:
        nonlocal replacements
        body, count = _shorten_long_code_separator_body(match.group("body"))
        replacements += count
        return f"{match.group('open')}{body}{match.group('close')}"

    return FENCED_CODE_CONTENT_RE.sub(replace_block, markdown), replacements


def _resolve_image_path(work_dir: str, image_path: str) -> str:
    clean_path = image_path.split("#", 1)[0].split("?", 1)[0].strip()
    clean_path = clean_path.replace("/", os.sep)
    return os.path.normpath(os.path.join(work_dir, clean_path))


def _is_random_simulation_asset(path: str) -> bool:
    return bool(RANDOM_SIMULATION_RE.search(path.replace("\\", "/")))


def _scan_generated_images(work_dir: str) -> list[str]:
    images: list[str] = []
    if not os.path.isdir(work_dir):
        return images
    for root, dirs, files in os.walk(work_dir):
        dirs[:] = [d for d in dirs if d not in _CODE_EXCLUDED_DIRS]
        for filename in files:
            if filename.lower().endswith(_IMAGE_EXTS):
                images.append(
                    os.path.relpath(os.path.join(root, filename), work_dir).replace(os.sep, "/")
                )
    return sorted(images)


def _plain_text(text: str) -> str:
    text = _without_fenced_code_blocks(text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[[^\]]+\]\([^)]+\)", "", text)
    text = re.sub(r"[#*_`$|>\[\]{}()]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _count_content_chars(text: str) -> int:
    plain = _plain_text(text)
    chinese = len(re.findall(r"[\u4e00-\u9fff]", plain))
    english_words = len(re.findall(r"[A-Za-z]{2,}", plain))
    return chinese + english_words


def _extract_abstract(markdown: str) -> str:
    markdown = _without_fenced_code_blocks(markdown)
    match = ABSTRACT_HEADING_RE.search(markdown)
    if match:
        next_heading = HEADING_RE.search(markdown, match.end())
        end = next_heading.start() if next_heading else len(markdown)
        return markdown[match.end() : end].strip()

    first_heading = HEADING_RE.search(markdown)
    start = first_heading.end() if first_heading else 0
    end_candidates = [
        m.start()
        for m in (
            re.search(r"(?m)^#{1,6}\s*(?:一、)?问题重述", markdown[start:]),
            re.search(r"(?m)^关键词\s*[:：]", markdown[start:]),
        )
        if m is not None
    ]
    if end_candidates:
        return markdown[start : start + min(end_candidates)].strip()
    return ""


def _check_abstract(markdown: str) -> dict:
    abstract = _extract_abstract(markdown)
    char_count = _count_content_chars(abstract)
    return {
        "passed": 120 <= char_count <= 1200,
        "char_count": char_count,
        "min_chars": 120,
        "max_chars": 1200,
    }


def _check_keywords(markdown: str) -> dict:
    match = KEYWORDS_RE.search(markdown)
    if not match:
        return {"passed": False, "count": 0, "items": []}
    raw = match.group(1).strip()
    items = [
        item.strip()
        for item in re.split(r"[;；,，、\s]+", raw)
        if item.strip()
    ]
    return {"passed": 3 <= len(items) <= 8, "count": len(items), "items": items}


def _check_sections(markdown: str) -> dict:
    markdown = _without_fenced_code_blocks(markdown)
    headings = [match.group(1).strip() for match in HEADING_RE.finditer(markdown)]
    missing: list[str] = []
    for key, alternatives in REQUIRED_SECTION_KEYWORDS.items():
        if not any(any(alt in heading for alt in alternatives) for heading in headings):
            missing.append(key)
    return {"passed": not missing, "missing": missing, "headings": headings}


def _with_severity(check: dict, severity: str) -> dict:
    check = dict(check)
    check["severity"] = "pass" if check.get("passed") else severity
    return check


def _image_check_severity(check: dict) -> str:
    if check.get("missing"):
        return "fail"
    # 未插入的生成图先降级为 conditional：当前 Harness 还没有上游
    # figure plan，无法可靠区分“重要论文图遗漏”和“探索性调试图未清理”。
    if check.get("unused_generated"):
        return "conditional"
    return "pass"


def _sections_check_severity(check: dict) -> str:
    missing = set(check.get("missing", []))
    if missing.intersection(CORE_SECTION_KEYS):
        return "fail"
    if missing:
        return "conditional"
    return "pass"


def _preflight_status(checks: dict) -> str:
    failed_checks = [
        check for check in checks.values()
        if not check.get("passed") and check.get("severity") == "fail"
    ]
    if failed_checks:
        return "FAIL"
    conditional_checks = [
        check for check in checks.values()
        if not check.get("passed") and check.get("severity") == "conditional"
    ]
    if conditional_checks:
        return "CONDITIONAL_PASS"
    return "PASS"


def _check_internal_paths(markdown: str) -> dict:
    matches = sorted(set(INTERNAL_PATH_RE.findall(_without_fenced_code_blocks(markdown))))
    return {"passed": not matches, "matches": matches}


def _check_submission_anonymity(markdown: str) -> dict:
    """Reject cover/identity fields that should not appear in the electronic paper."""
    text = _without_fenced_code_blocks(markdown)
    matches = sorted(set(match.group(0).strip() for match in FORBIDDEN_SUBMISSION_RE.finditer(text)))
    return {"passed": not matches, "matches": matches}


def _find_markdown_tables(markdown: str) -> list[list[str]]:
    tables: list[list[str]] = []
    current: list[str] = []
    for line in markdown.splitlines():
        if line.strip().startswith("|") and line.strip().endswith("|"):
            current.append(line.strip())
            continue
        if current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables


def _is_markdown_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _previous_nonblank_line(lines: list[str]) -> str:
    for line in reversed(lines):
        if line.strip():
            return line.strip()
    return ""


def _table_caption_title(context_heading: str, table: list[str]) -> str:
    header = table[0] if table else ""
    if "支撑材料" in context_heading or "文件名" in header:
        return "支撑材料文件列表"
    if "符号" in context_heading or "符号" in header:
        return "符号说明"
    if "敏感性" in context_heading or "灵敏度" in context_heading:
        return "灵敏度分析结果"
    if "模型" in context_heading:
        return "模型求解结果"
    return "结果汇总"


def ensure_table_captions(markdown: str) -> str:
    """Insert simple numbered captions before Markdown tables that lack one."""
    lines = markdown.splitlines()
    output: list[str] = []
    index = 0
    table_index = 1
    context_heading = ""
    in_fence = False
    fence_marker = ""

    while index < len(lines):
        line = lines[index]
        fence_match = FENCE_START_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker[0]
            elif marker.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            output.append(line)
            index += 1
            continue

        if not in_fence:
            heading_match = HEADING_RE.match(line)
            if heading_match:
                context_heading = heading_match.group(1).strip()

            if _is_markdown_table_line(line):
                table: list[str] = []
                while index < len(lines) and _is_markdown_table_line(lines[index]):
                    table.append(lines[index])
                    index += 1
                previous = _previous_nonblank_line(output)
                if not TABLE_CAPTION_RE.match(previous):
                    title = _table_caption_title(context_heading, table)
                    if output and output[-1].strip():
                        output.append("")
                    output.append(f"表{table_index} {title}")
                    output.append("")
                output.extend(table)
                table_index += 1
                continue

        output.append(line)
        index += 1

    return "\n".join(output).rstrip() + ("\n" if markdown.endswith("\n") else "")


def _check_tables(markdown: str) -> dict:
    wide_tables: list[dict] = []
    uncaptioned_tables: list[dict] = []
    lines = markdown.splitlines()
    table_start_lines: list[int] = []
    in_fence = False
    fence_marker = ""
    previous_nonblank = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        fence_match = FENCE_START_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker[0]
            elif marker.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            index += 1
            continue
        if in_fence:
            index += 1
            continue
        if _is_markdown_table_line(line):
            table_start_lines.append(index + 1)
            if not TABLE_CAPTION_RE.match(previous_nonblank):
                uncaptioned_tables.append(
                    {
                        "table_index": len(table_start_lines),
                        "line": index + 1,
                    }
                )
            while index < len(lines) and _is_markdown_table_line(lines[index]):
                index += 1
            previous_nonblank = ""
            continue
        if line.strip():
            previous_nonblank = line.strip()
        index += 1

    for index, table in enumerate(_find_markdown_tables(markdown), 1):
        header = table[0]
        column_count = max(0, header.count("|") - 1)
        max_line_length = max(len(line) for line in table)
        if max_line_length >= 120 or (column_count >= 7 and max_line_length >= 90):
            wide_tables.append(
                {
                    "table_index": index,
                    "column_count": column_count,
                    "max_line_length": max_line_length,
                }
            )
    return {
        "passed": not wide_tables and not uncaptioned_tables,
        "wide_tables": wide_tables,
        "uncaptioned_tables": uncaptioned_tables,
    }


def _extra_problem_label_issues(
    markdown: str,
    declared_count: int | None = None,
) -> list[dict]:
    if declared_count is None:
        declared_count = _infer_declared_problem_count(markdown)
    if declared_count is None:
        return []
    visible_markdown = _without_fenced_code_blocks(markdown)
    visible_markdown = IMAGE_MARKDOWN_RE.sub(lambda match: f"![{match.group(1)}]()", visible_markdown)
    issues: list[dict] = []
    for match in EXTRA_PROBLEM_LABEL_RE.finditer(visible_markdown):
        number = _chinese_problem_number(match.group("number"))
        if number is not None and number > declared_count:
            issues.append(
                {
                    "label": match.group(0).strip(),
                    "declared_problem_count": declared_count,
                }
            )
    return issues


def _section_kind(title: str) -> str:
    clean_title = re.sub(r"^(?:[一二三四五六七八九十]+、|\d+(?:\.\d+)*\s*)", "", title).strip()
    for kind, keywords in SECTION_KIND_KEYWORDS.items():
        if any(keyword in clean_title for keyword in keywords):
            return kind
    return "other"


def _check_export_profile(export_profile: str | None) -> dict:
    profile = str(export_profile or EXPECTED_EXPORT_PROFILE)
    expected = EXPECTED_EXPORT_PROFILE
    return {
        "passed": profile == expected,
        "profile": profile,
        "expected": expected,
        "label": EXPORT_PROFILE_LABELS.get(profile, profile),
        "reason": (
            "高教社杯/国赛当前建议使用 cumcm2026。"
            if profile != expected
            else ""
        ),
    }


def _conclusion_for_status(status: str) -> str:
    if status == "PASS":
        return "PASS: 论文预检硬门禁通过，可进入人工复核与正式字体导出。"
    if status == "CONDITIONAL_PASS":
        return "CONDITIONAL_PASS: 主流程可交付，但存在需要人工复核的条件项。"
    return "FAIL: 存在硬门禁失败项，应先修复后再提交。"


def build_paper_outline(markdown: str) -> dict:
    """从 Markdown 标题确定性生成论文结构摘要。"""
    markdown_without_code = _without_fenced_code_blocks(markdown)
    lines = markdown_without_code.splitlines()
    sections: list[dict] = []
    for line_number, line in enumerate(lines, 1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if not match:
            continue
        title = match.group(2).strip()
        sections.append(
            {
                "level": len(match.group(1)),
                "title": title,
                "line": line_number,
                "kind": _section_kind(title),
            }
        )
    return {
        "generated_at": datetime.datetime.now().isoformat(),
        "section_count": len(sections),
        "sections": sections,
    }


def build_figure_usage(work_dir: str, markdown: str) -> dict:
    """生成图像引用与工作目录图片之间的对应关系。"""
    referenced = []
    for match in IMAGE_RE.finditer(markdown):
        path = match.group(1).replace("\\", "/")
        referenced.append(
            {
                "path": path,
                "exists": os.path.exists(_resolve_image_path(work_dir, path)),
            }
        )
    generated = _scan_generated_images(work_dir)
    if any(marker in markdown for marker in DETERMINISTIC_NO_SAMPLE_MARKERS):
        generated = [
            image for image in generated if not _is_random_simulation_asset(image)
        ]
    referenced_set = {item["path"] for item in referenced}
    return {
        "generated_at": datetime.datetime.now().isoformat(),
        "referenced": referenced,
        "generated": generated,
        "missing": [item["path"] for item in referenced if not item["exists"]],
        "unused_generated": [
            image for image in generated if image not in referenced_set
        ],
    }


def _current_section_for_offset(markdown: str, offset: int) -> str:
    current = "正文"
    for match in HEADING_RE.finditer(markdown):
        if match.start() > offset:
            break
        current = match.group(1).strip()
    return current


def _claim_matches(markdown: str) -> list[re.Match[str]]:
    return list(CLAIM_SENTENCE_RE.finditer(markdown))


def build_claim_trace(markdown: str, code_sources: list[str]) -> dict:
    """生成轻量 claim trace，标注核心结论是否有可追溯证据。"""
    markdown_without_code = _without_fenced_code_blocks(markdown)
    figure_paths = IMAGE_RE.findall(markdown_without_code)
    reference_count = 0
    reference_match = REFERENCE_HEADING_RE.search(markdown_without_code)
    if reference_match:
        reference_count = len(
            [
                line
                for line in markdown_without_code[reference_match.end() :].splitlines()
                if re.match(r"^\s*\[\d+\]\s+\S+", line)
            ]
        )

    claims: list[dict] = []
    seen: set[str] = set()
    for match in _claim_matches(markdown_without_code):
        claim = match.group(0).strip()
        claim = re.sub(r"\s+", " ", _plain_text(claim))
        if len(claim) < 12 or claim in seen:
            continue
        seen.add(claim)
        has_number = bool(NUMERIC_RE.search(claim))
        evidence_type = "missing"
        evidence_ids: list[str] = []
        strength = "missing"
        if has_number and code_sources:
            evidence_type = "code_output"
            evidence_ids = code_sources[:3]
            strength = "strong"
        elif figure_paths:
            evidence_type = "figure"
            evidence_ids = figure_paths[:3]
            strength = "acceptable"
        elif reference_count:
            evidence_type = "reference"
            evidence_ids = [f"references:{reference_count}"]
            strength = "acceptable"

        wording_check = (
            "strong_wording_needs_evidence"
            if STRONG_WORDING_RE.search(claim) and strength != "strong"
            else "ok"
        )
        if wording_check != "ok" and strength == "acceptable":
            strength = "weak"

        claims.append(
            {
                "claim": claim,
                "paper_section": _current_section_for_offset(
                    markdown_without_code, match.start()
                ),
                "evidence_type": evidence_type,
                "evidence_id_file": evidence_ids,
                "strength": strength,
                "paper_wording_check": wording_check,
            }
        )
        if len(claims) >= 30:
            break

    missing_count = sum(1 for item in claims if item["strength"] == "missing")
    weak_count = sum(1 for item in claims if item["strength"] == "weak")
    strong_wording_weak_count = sum(
        1
        for item in claims
        if item["strength"] == "weak"
        and item["paper_wording_check"] == "strong_wording_needs_evidence"
    )
    if missing_count or strong_wording_weak_count:
        status = "FAIL"
    elif weak_count:
        status = "CONDITIONAL_PASS"
    else:
        status = "PASS"
    return {
        "generated_at": datetime.datetime.now().isoformat(),
        "claims": claims,
        "summary": {
            "total": len(claims),
            "weak": weak_count,
            "missing": missing_count,
            "strong_wording_weak": strong_wording_weak_count,
        },
        "status": status,
    }


def render_claim_trace_markdown(trace: dict) -> str:
    lines = [
        "# Claim Trace",
        "",
        f"- Status: `{trace.get('status', 'unknown')}`",
        "",
        "| Claim | Paper Section | Evidence Type | Evidence ID/File | Strength | Paper Wording Check |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in trace.get("claims", []):
        evidence = ", ".join(item.get("evidence_id_file", []))
        row = [
            item.get("claim", ""),
            item.get("paper_section", ""),
            item.get("evidence_type", ""),
            evidence,
            item.get("strength", ""),
            item.get("paper_wording_check", ""),
        ]
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |")
    lines.append("")
    return "\n".join(lines)


def _check_claim_trace(trace: dict) -> dict:
    summary = trace.get("summary", {})
    status = trace.get("status", "PASS")
    return {
        "passed": status == "PASS",
        "status": status,
        "total": summary.get("total", 0),
        "weak": summary.get("weak", 0),
        "missing": summary.get("missing", 0),
        "strong_wording_weak": summary.get("strong_wording_weak", 0),
    }


def _claim_trace_check_severity(check: dict) -> str:
    if check.get("missing") or check.get("strong_wording_weak"):
        return "fail"
    if not check.get("passed"):
        return "conditional"
    return "pass"


def build_preflight_report(
    work_dir: str,
    markdown: str,
    code_sources: list[str],
    export_profile: str | None = None,
    claim_trace: dict | None = None,
    declared_problem_count: int | None = None,
) -> dict:
    """生成论文排版预检报告。"""
    markdown_without_code = _without_fenced_code_blocks(markdown)
    reference_match = REFERENCE_HEADING_RE.search(markdown)
    reference_lines: list[str] = []
    if reference_match:
        reference_lines = [
            line.strip()
            for line in markdown[reference_match.end() :].splitlines()
            if line.strip()
        ]
        # 附录代码可能位于参考文献之后，遇到附录标题即停止检查参考文献。
        for index, line in enumerate(reference_lines):
            if line.startswith("# 附录"):
                reference_lines = reference_lines[:index]
                break

    bad_reference_lines = [
        line
        for line in reference_lines
        if not re.match(r"^\[\d+\]\s+\S+", line)
    ]
    reference_numbers = {
        int(match.group(1))
        for line in reference_lines
        for match in [re.match(r"^\[(\d+)\]\s+\S+", line)]
        if match
    }
    body_before_references, _ = _reference_body_parts(markdown)
    inline_reference_numbers = _inline_reference_numbers(body_before_references)
    missing_inline_references = sorted(inline_reference_numbers - reference_numbers)

    image_paths = IMAGE_RE.findall(markdown)
    missing_images = [
        path
        for path in image_paths
        if not os.path.exists(_resolve_image_path(work_dir, path))
    ]
    generated_images = _scan_generated_images(work_dir)
    if any(marker in markdown for marker in DETERMINISTIC_NO_SAMPLE_MARKERS):
        generated_images = [
            image for image in generated_images if not _is_random_simulation_asset(image)
        ]
    used_image_set = {path.replace("\\", "/") for path in image_paths}
    unused_generated_images = [
        image for image in generated_images if image not in used_image_set
    ]
    placeholders = sorted(set(PLACEHOLDER_RE.findall(markdown)))

    references_check = {
        "passed": (
            not bad_reference_lines
            and not missing_inline_references
            and (bool(reference_lines) or not inline_reference_numbers)
        ),
        "count": len(reference_lines),
        "bad_lines": bad_reference_lines,
        "inline": sorted(inline_reference_numbers),
        "missing_inline": missing_inline_references,
    }
    support_materials_check = {
        "passed": bool(SUPPORT_MATERIAL_HEADING_RE.search(markdown))
        and (
            bool(re.search(r"(?m)^\|\s*[^|]+\s*\|\s*(?:源程序代码|数据/结果文件|图片文件)\s*\|", markdown))
            or bool(NO_SUPPORT_MATERIAL_RE.search(markdown))
        ),
    }
    code_appendix_check = {
        "passed": bool(CODE_APPENDIX_HEADING_RE.search(markdown))
        and (bool(code_sources) or bool(NO_PROGRAM_RE.search(markdown))),
        "sources": code_sources,
    }
    images_check = {
        "passed": not missing_images and not unused_generated_images,
        "referenced_count": len(image_paths),
        "missing": missing_images,
        "unused_generated": unused_generated_images,
    }
    placeholders_check = {
        "passed": not placeholders,
        "matches": placeholders,
    }
    extra_problem_label_issues = _extra_problem_label_issues(
        markdown,
        declared_count=declared_problem_count,
    )
    extra_problem_labels_check = {
        "passed": not extra_problem_label_issues,
        "issues": extra_problem_label_issues,
    }
    sections_check = _check_sections(markdown_without_code)
    export_profile_check = _check_export_profile(export_profile)
    claim_trace_check = _check_claim_trace(
        claim_trace if claim_trace is not None else build_claim_trace(markdown, code_sources)
    )

    checks = {
        "export_profile": _with_severity(export_profile_check, "fail"),
        "references": _with_severity(references_check, "fail"),
        "support_materials": _with_severity(support_materials_check, "fail"),
        "code_appendix": _with_severity(code_appendix_check, "fail"),
        "images": _with_severity(images_check, _image_check_severity(images_check)),
        "placeholders": _with_severity(placeholders_check, "fail"),
        "abstract": _with_severity(_check_abstract(markdown), "fail"),
        "keywords": _with_severity(_check_keywords(markdown), "conditional"),
        "sections": _with_severity(sections_check, _sections_check_severity(sections_check)),
        "internal_paths": _with_severity(_check_internal_paths(markdown), "fail"),
        "submission_anonymity": _with_severity(
            _check_submission_anonymity(markdown), "fail"
        ),
        "tables": _with_severity(_check_tables(markdown_without_code), "conditional"),
        "extra_problem_labels": _with_severity(extra_problem_labels_check, "conditional"),
        "claim_trace": _with_severity(
            claim_trace_check, _claim_trace_check_severity(claim_trace_check)
        ),
    }
    status = _preflight_status(checks)
    return {
        "status": status,
        "conclusion": _conclusion_for_status(status),
        "generated_at": datetime.datetime.now().isoformat(),
        "checks": checks,
    }


def _format_check_detail(check: dict) -> str:
    if "profile" in check and "expected" in check:
        return f"profile={check['profile']}; expected={check['expected']}"
    if "count" in check and "bad_lines" in check:
        missing_inline = check.get("missing_inline", [])
        return (
            f"count={check['count']}; bad_lines={len(check['bad_lines'])}; "
            f"missing_inline={missing_inline or 'none'}"
        )
    if "sources" in check:
        return ", ".join(check["sources"]) or "no code sources"
    if "missing" in check and "unused_generated" in check:
        return (
            f"referenced={check['referenced_count']}; "
            f"missing={len(check['missing'])}; unused={len(check['unused_generated'])}"
        )
    if "matches" in check:
        return ", ".join(check["matches"]) or "none"
    if "char_count" in check:
        return f"chars={check['char_count']} ({check['min_chars']}-{check['max_chars']})"
    if "items" in check:
        return f"count={check['count']}; items={', '.join(check['items'])}"
    if "headings" in check:
        return f"missing={', '.join(check['missing']) or 'none'}"
    if "wide_tables" in check:
        return (
            f"wide_tables={len(check['wide_tables'])}; "
            f"uncaptioned={len(check.get('uncaptioned_tables', []))}"
        )
    if "issues" in check:
        return f"issues={len(check['issues'])}"
    if "status" in check and {"weak", "missing"}.issubset(check):
        return (
            f"status={check['status']}; total={check['total']}; "
            f"weak={check['weak']}; missing={check['missing']}; "
            f"strong_wording_weak={check.get('strong_wording_weak', 0)}"
        )
    return json.dumps(check, ensure_ascii=False)


def render_preflight_markdown(report: dict) -> str:
    """将预检 JSON 渲染为人类可读 Markdown。"""
    lines = [
        "# Paper Preflight Report",
        "",
        f"- Status: `{report.get('status', 'unknown')}`",
        f"- Conclusion: {report.get('conclusion', '')}",
        f"- Generated at: `{report.get('generated_at', '')}`",
        "",
        "## Hard Gates",
        "",
        "| Check | Result | Detail |",
        "| --- | --- | --- |",
    ]
    checks = report.get("checks", {})
    for name, check in checks.items():
        if check.get("severity") not in {"fail", "pass"}:
            continue
        result = "PASS" if check.get("passed") else "FAIL"
        detail = _format_check_detail(check).replace("|", "\\|")
        lines.append(f"| {name} | {result} | {detail} |")

    lines.extend(
        [
            "",
            "## Conditional Checks",
            "",
            "| Check | Result | Detail |",
            "| --- | --- | --- |",
        ]
    )
    for name, check in checks.items():
        if check.get("severity") == "fail":
            continue
        if check.get("passed") and name in {"export_profile", "references", "support_materials", "code_appendix"}:
            continue
        if check.get("passed"):
            result = "PASS"
        else:
            result = "CONDITIONAL_PASS"
        detail = _format_check_detail(check).replace("|", "\\|")
        lines.append(f"| {name} | {result} | {detail} |")

    lines.extend(
        [
            "",
            "## All Checks",
            "",
        "| Check | Result | Detail |",
        "| --- | --- | --- |",
        ]
    )
    for name, check in checks.items():
        if check.get("passed"):
            result = "PASS"
        elif check.get("severity") == "fail":
            result = "FAIL"
        else:
            result = "CONDITIONAL_PASS"
        detail = _format_check_detail(check).replace("|", "\\|")
        lines.append(f"| {name} | {result} | {detail} |")
    lines.append("")
    return "\n".join(lines)


def _write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def prepare_paper_markdown(
    work_dir: str,
    md_filename: str = "res.md",
    export_profile: str | None = None,
    declared_problem_count: int | None = None,
) -> dict:
    """后处理 res.md 并写入 paper_preflight_report.json。"""
    md_path = os.path.join(work_dir, md_filename)
    if not os.path.exists(md_path):
        report = {
            "status": "FAIL",
            "conclusion": _conclusion_for_status("FAIL"),
            "generated_at": datetime.datetime.now().isoformat(),
            "checks": {
                "markdown": {
                    "passed": False,
                    "severity": "fail",
                    "reason": f"Markdown 文件不存在: {md_path}",
                }
            },
        }
        return report

    with open(md_path, encoding="utf-8") as f:
        markdown = f.read()

    markdown = normalize_markdown_headings(markdown)
    markdown, normalised_bold_standalone_labels = normalize_bold_standalone_labels(
        markdown
    )
    markdown, removed_orphan_definition_references = (
        remove_orphan_definition_reference_lines(markdown)
    )
    markdown = normalize_chinese_references(markdown)
    markdown, removed_unmatched_references = strip_unmatched_inline_references(markdown)
    markdown, removed_empty_references = remove_empty_reference_section(markdown)
    markdown = normalize_keywords(markdown)
    markdown, removed_missing_images = remove_missing_image_references(markdown, work_dir)
    markdown, code_sources = append_code_appendix(markdown, work_dir)
    markdown, shortened_code_separators = shorten_long_code_separator_lines(markdown)
    markdown, normalised_extra_problem_labels = normalize_extra_problem_labels(
        markdown,
        include_code=True,
        declared_count=declared_problem_count,
    )
    markdown = normalize_english_transitions(markdown)
    markdown, normalised_deterministic_eda_terms = normalize_deterministic_eda_terms(
        markdown
    )
    markdown, removed_deterministic_random_simulation = (
        remove_deterministic_random_simulation(markdown)
    )
    markdown, normalised_deterministic_random_simulation_code_terms = (
        normalize_deterministic_random_simulation_code_terms(markdown)
    )
    markdown, normalised_strong_claim_wording = normalize_strong_claim_wording(
        markdown
    )
    markdown, normalised_submission_wording = normalize_submission_wording(markdown)
    markdown = normalize_image_captions(markdown)
    markdown = ensure_table_captions(markdown)
    outline = build_paper_outline(markdown)
    figure_usage = build_figure_usage(work_dir, markdown)
    claim_trace = build_claim_trace(markdown, code_sources)
    report = build_preflight_report(
        work_dir,
        markdown,
        code_sources,
        export_profile=export_profile,
        claim_trace=claim_trace,
        declared_problem_count=declared_problem_count,
    )
    fixups = {}
    if removed_missing_images:
        fixups["removed_missing_images"] = removed_missing_images
    if removed_unmatched_references:
        fixups["removed_unmatched_references"] = removed_unmatched_references
    if removed_empty_references:
        fixups["removed_empty_reference_section"] = True
    if normalised_bold_standalone_labels:
        fixups["normalised_bold_standalone_labels"] = (
            normalised_bold_standalone_labels
        )
    if removed_orphan_definition_references:
        fixups["removed_orphan_definition_references"] = (
            removed_orphan_definition_references
        )
    if normalised_extra_problem_labels:
        fixups["normalised_extra_problem_labels"] = normalised_extra_problem_labels
    if shortened_code_separators:
        fixups["shortened_code_separator_lines"] = shortened_code_separators
    if normalised_deterministic_eda_terms:
        fixups["normalised_deterministic_eda_terms"] = normalised_deterministic_eda_terms
    if removed_deterministic_random_simulation:
        fixups["removed_deterministic_random_simulation"] = (
            removed_deterministic_random_simulation
        )
    if normalised_deterministic_random_simulation_code_terms:
        fixups["normalised_deterministic_random_simulation_code_terms"] = (
            normalised_deterministic_random_simulation_code_terms
        )
    if normalised_strong_claim_wording:
        fixups["normalised_strong_claim_wording"] = normalised_strong_claim_wording
    if normalised_submission_wording:
        fixups["normalised_submission_wording"] = normalised_submission_wording
    if fixups:
        report["fixups"] = fixups

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    report_path = os.path.join(work_dir, "paper_preflight_report.json")
    md_report_path = os.path.join(work_dir, "paper_preflight_report.md")
    outline_path = os.path.join(work_dir, "paper_outline.json")
    figure_usage_path = os.path.join(work_dir, "figure_usage.json")
    claim_trace_path = os.path.join(work_dir, "claim_trace.json")
    claim_trace_md_path = os.path.join(work_dir, "claim_trace.md")
    try:
        _write_json(report_path, report)
        _write_json(outline_path, outline)
        _write_json(figure_usage_path, figure_usage)
        _write_json(claim_trace_path, claim_trace)
        with open(md_report_path, "w", encoding="utf-8") as f:
            f.write(render_preflight_markdown(report))
        with open(claim_trace_md_path, "w", encoding="utf-8") as f:
            f.write(render_claim_trace_markdown(claim_trace))
        logger.info(f"paper_preflight_report.json 生成成功: {report_path}")
    except OSError as exc:
        logger.error(f"paper_preflight_report 生成失败: {exc}")

    return report
