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
REFERENCE_START_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\[\^?(\d+)\]|\^?(\d+)[:：.]|(\d+)[.、])\s*[:：]?\s*(.+?)\s*$"
)
IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
PLACEHOLDER_RE = re.compile(r"\b(?:TODO|TBD|FIXME)\b|待补充|占位|这里写|xxx", re.IGNORECASE)
APPENDIX_HEADING_RE = re.compile(r"(?m)^#{1,6}\s*附录\s*$")
SUPPORT_MATERIAL_HEADING_RE = re.compile(r"(?m)^#{1,6}\s*附录A\s+支撑材料文件列表\s*$")
CODE_APPENDIX_HEADING_RE = re.compile(r"(?m)^#{1,6}\s*附录B\s+源程序代码\s*$")
NO_PROGRAM_RE = re.compile(r"本论文没有用到程序")
NO_SUPPORT_MATERIAL_RE = re.compile(r"本论文没有支撑材料")
HEADING_RE = re.compile(r"(?m)^#{1,6}\s+(.+?)\s*$")
ABSTRACT_HEADING_RE = re.compile(r"(?m)^#{1,6}\s*摘要\s*$")
KEYWORDS_RE = re.compile(r"关键词\s*[:：]\s*(.+)")
KEYWORDS_HEADING_RE = re.compile(
    r"(?ms)^#{1,6}\s*关键词\s*\n+(?P<keywords>.*?)(?=\n#{1,6}\s|\Z)"
)
BOLD_ABSTRACT_HEADING_RE = re.compile(r"(?m)^\*\*\s*摘要\s*\*\*\s*$")
BOLD_KEYWORDS_HEADING_RE = re.compile(r"(?m)^\*\*\s*关键词\s*\*\*\s*$")
INTERNAL_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s，。；；,;]+|/(?:home|tmp|var|usr|etc|opt|root|workspace)/[^\s，。；；,;]+)"
)
FENCED_CODE_BLOCK_RE = re.compile(r"(?ms)^```.*?^```\s*")
CLAIM_SENTENCE_RE = re.compile(r"[^。！？.!?\n]*(?:最优|利润|提高|增加|降低|结果表明|敏感性|影子价格|准确率|误差)[^。！？.!?\n]*[。！？.!?]?")
NUMERIC_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|元|小时|件|吨|亩|分|倍|年|万元)?")
STRONG_WORDING_RE = re.compile(r"证明|必然|唯一|完全|显著优于|最可靠|精确预测")

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


def normalize_chinese_references(markdown: str) -> str:
    """将参考文献章节整理为独立编号行，并把正文脚注标记改为数字引用。"""
    match = REFERENCE_HEADING_RE.search(markdown)
    if not match:
        return INLINE_FOOTNOTE_RE.sub(lambda m: f"[{m.group(1)}]", markdown)

    body = markdown[: match.start()].rstrip()
    reference_text = markdown[match.end() :].strip()
    entries = _parse_reference_entries(reference_text)
    if not entries:
        return INLINE_FOOTNOTE_RE.sub(lambda m: f"[{m.group(1)}]", markdown)

    number_map = {old_number: index for index, (old_number, _) in enumerate(entries, 1)}
    body = _renumber_inline_references(body, number_map)

    reference_lines = ["## 参考文献", ""]
    for index, (_, content) in enumerate(entries, 1):
        reference_lines.append(f"[{index}] {content}")

    return body + "\n\n" + "\n".join(reference_lines).rstrip() + "\n"


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
    return BOLD_KEYWORDS_HEADING_RE.sub("## 关键词", markdown)


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
            lines.extend(
                [
                    f"### B.{index} {source.name}",
                    "",
                    f"```{source.language}",
                    source.code.rstrip(),
                    "```",
                    "",
                ]
            )
    else:
        lines.extend(["本论文没有用到程序。", ""])
    return "\n".join(lines).rstrip() + "\n", [source.name for source in sources]


def _resolve_image_path(work_dir: str, image_path: str) -> str:
    clean_path = image_path.split("#", 1)[0].split("?", 1)[0].strip()
    clean_path = clean_path.replace("/", os.sep)
    return os.path.normpath(os.path.join(work_dir, clean_path))


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
    matches = sorted(set(INTERNAL_PATH_RE.findall(markdown)))
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


def _check_tables(markdown: str) -> dict:
    wide_tables: list[dict] = []
    for index, table in enumerate(_find_markdown_tables(markdown), 1):
        header = table[0]
        column_count = max(0, header.count("|") - 1)
        max_line_length = max(len(line) for line in table)
        if column_count >= 7 or max_line_length >= 120:
            wide_tables.append(
                {
                    "table_index": index,
                    "column_count": column_count,
                    "max_line_length": max_line_length,
                }
            )
    return {"passed": not wide_tables, "wide_tables": wide_tables}


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
            strength = "acceptable"
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

    image_paths = IMAGE_RE.findall(markdown)
    missing_images = [
        path
        for path in image_paths
        if not os.path.exists(_resolve_image_path(work_dir, path))
    ]
    generated_images = _scan_generated_images(work_dir)
    used_image_set = {path.replace("\\", "/") for path in image_paths}
    unused_generated_images = [
        image for image in generated_images if image not in used_image_set
    ]
    placeholders = sorted(set(PLACEHOLDER_RE.findall(markdown)))

    references_check = {
        "passed": bool(reference_lines) and not bad_reference_lines,
        "count": len(reference_lines),
        "bad_lines": bad_reference_lines,
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
        "tables": _with_severity(_check_tables(markdown), "conditional"),
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
        return f"count={check['count']}; bad_lines={len(check['bad_lines'])}"
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
        return f"wide_tables={len(check['wide_tables'])}"
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
    markdown = normalize_chinese_references(markdown)
    markdown = normalize_keywords(markdown)
    markdown, removed_missing_images = remove_missing_image_references(markdown, work_dir)
    markdown, code_sources = append_code_appendix(markdown, work_dir)
    outline = build_paper_outline(markdown)
    figure_usage = build_figure_usage(work_dir, markdown)
    claim_trace = build_claim_trace(markdown, code_sources)
    report = build_preflight_report(
        work_dir,
        markdown,
        code_sources,
        export_profile=export_profile,
        claim_trace=claim_trace,
    )
    if removed_missing_images:
        report["fixups"] = {"removed_missing_images": removed_missing_images}

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
