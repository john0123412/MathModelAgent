"""论文导出前的 Markdown 后处理与预检。"""

from __future__ import annotations

import datetime
import hashlib
import csv
import json
import os
import re
from dataclasses import dataclass
from typing import Any

from app.utils.log_util import logger
from app.tools.result_integrity import (
    build_frozen_result_summary,
    metric_aliases,
    validate_result_freeze,
)
from app.tools.candidate_exporter import (
    collect_bounded_support_material_paths,
    support_material_category,
)
from app.tools.semantic_layout_review import (
    normalize_markdown_semantics,
    review_markdown,
    write_semantic_layout_review,
)
from app.tools.export_profiles import get_export_profile_config
from app.tools.fact_store import FactStore
from app.tools.cross_modal_validator import (
    audit_cross_modal,
    validate_code_text_parity,
)
from app.schemas.problem_contract import (
    affirmatively_binds_source,
    build_problem_contract,
    validate_modeler_plan,
)


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
SUPPORT_MATERIAL_HEADING_RE = re.compile(r"(?m)^#{1,6}\s*附录[A-Z]\s+支撑材料文件列表\s*$")
CODE_APPENDIX_HEADING_RE = re.compile(r"(?m)^#{1,6}\s*附录[A-Z]\s+源程序代码\s*$")
AI_USAGE_DECLARATION_RE = re.compile(
    r"(?mi)^#{1,6}\s*AI\s*工具使用声明\s*$"
)
AI_USAGE_DECLARATION = (
    "## AI工具使用声明\n\n"
    "本参赛队在竞赛过程中使用了AI工具，主要用于建模方案审阅、代码调试、"
    "论文语言与版式整理，详细使用情况见附录。"
)
AI_USAGE_DETAILS_FILENAME = "AI工具使用详情.pdf"
NO_PROGRAM_RE = re.compile(r"本论文没有用到程序")
NO_SUPPORT_MATERIAL_RE = re.compile(r"本论文没有支撑材料")
HEADING_RE = re.compile(r"(?m)^#{1,6}\s+(.+?)\s*$")
ATX_HEADING_LINE_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")
ABSTRACT_HEADING_RE = re.compile(r"(?m)^#{1,6}\s*摘要\s*$")
KEYWORDS_RE = re.compile(r"\*{0,2}\s*关键词\s*\*{0,2}\s*[:：]\s*(.+)")
KEYWORDS_LINE_RE = re.compile(
    r"(?m)^\s*\*{0,2}\s*关键词\s*\*{0,2}\s*[:：].*$"
)
CJK_INLINE_SPACE_RE = re.compile(r"(?<=[\u4e00-\u9fff])[ \t]+(?=[\u4e00-\u9fff])")
KEYWORDS_HEADING_RE = re.compile(
    r"(?ms)^#{1,6}\s*关键词\s*\n+(?P<keywords>.*?)(?=\n#{1,6}\s|\Z)"
)
BOLD_ABSTRACT_HEADING_RE = re.compile(r"(?m)^\*\*\s*摘要\s*\*\*\s*$")
BOLD_KEYWORDS_HEADING_RE = re.compile(r"(?m)^\*\*\s*关键词\s*\*\*\s*$")
BOLD_REFERENCE_HEADING_RE = re.compile(r"(?m)^\*\*\s*参考文献\s*\*\*\s*$")
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
PLAIN_NUMBER_RE = re.compile(r"(?<![A-Za-z_\\])[-+]?\d+(?:\.\d+)?(?![A-Za-z_])")
DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s<>\"']+", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
STRONG_WORDING_RE = re.compile(r"证明|唯一|显著优于|最可靠|精确预测")
OPTIMALITY_CLAIM_RE = re.compile(r"最优(?:解|方案|控制|参数)?|最佳(?:解|方案)?|Pareto(?:最优)?|帕累托(?:最优)?")
ALGORITHM_CLAIMS = {
    "genetic_algorithm": (
        re.compile(r"遗传算法|genetic\s+algorithm", re.IGNORECASE),
        ("遗传算法", "genetic algorithm", "deap", "pymoo", "geneticalgorithm"),
    ),
    "pareto_optimization": (
        re.compile(r"Pareto|帕累托", re.IGNORECASE),
        ("pareto", "pymoo", "nsga", "nondominated"),
    ),
    "particle_swarm": (
        re.compile(r"粒子群|particle\s+swarm|PSO", re.IGNORECASE),
        ("粒子群", "particle swarm", "pyswarms"),
    ),
}
FUTURE_ALGORITHM_CONTEXT_RE = re.compile(
    r"(?:可|可以|建议|拟|将|未来|后续|进一步|改进).{0,32}"
    r"(?:遗传算法|genetic\s+algorithm|Pareto|帕累托|粒子群|particle\s+swarm|PSO)",
    re.IGNORECASE,
)
NON_IMPLEMENTED_ALGORITHM_CONTEXT_RE = re.compile(
    r"(?:若|如果|假如|假设|如需|若要|当|可(?:考虑|采用|使用)).{0,64}"
    r"(?:遗传算法|genetic\s+algorithm|Pareto|帕累托|粒子群|particle\s+swarm|PSO)"
    r"|(?:遗传算法|genetic\s+algorithm|Pareto|帕累托|粒子群|particle\s+swarm|PSO)"
    r"[^。\n]{0,80}(?:未(?:采用|使用|实现|涉及)|不(?:及|适用|涉及|需)|作为[^。\n]{0,24}(?:对比|替代)|本题[^。\n]{0,24}(?:仅|无需|不)|无需|并不|并非)",
    re.IGNORECASE,
)
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
MAX_APPENDIX_CONSOLE_LINES = 20
NUMERIC_CONSISTENCY_TOLERANCE = 0.05
LONG_CODE_SEPARATOR_RE = re.compile(
    r"^(?P<indent>\s*)(?P<prefix>#|//|%|--)?(?P<gap>\s*)"
    r"(?P<char>[=\-_*])(?P=char){59,}\s*$"
)
APPENDIX_CONSOLE_LINE_RE = re.compile(
    r"^\s*(?:print|printf|console\.log|logger\.(?:debug|info|warning|error))\s*\(",
    re.IGNORECASE,
)
APPENDIX_NOISY_LINE_RE = re.compile(
    r"^\s*(?:print|printf|console\.log|display|logger\.(?:debug|info|warning|error))\s*\(",
    re.IGNORECASE,
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
EDITORIAL_QUALITY_POLICIES = {
    # This is deliberately opt-in: existing tasks predate the editorial policy
    # and must not become non-exportable solely because it was introduced.
    "off": {
        "active": False,
        "enforce": False,
        "min_body_chars": 0,
        "min_result_figures": 0,
        "min_result_tables": 0,
        "min_result_figures_per_question": 0,
        "min_result_tables_per_question": 0,
        "require_asset_source_trace": False,
        "min_abstract_paragraphs": 0,
        "require_references": False,
        "require_reference_style": False,
    },
    # Smoke runs surface the same measurements without making lightweight
    # fixtures or quick end-to-end checks fail on editorial completeness.
    "smoke": {
        "active": True,
        "enforce": False,
        "min_body_chars": 1200,
        "min_result_figures": 1,
        "min_result_tables": 1,
        "min_result_figures_per_question": 0,
        "min_result_tables_per_question": 0,
        "require_asset_source_trace": False,
        "min_abstract_paragraphs": 0,
        "require_references": False,
        "require_reference_style": False,
    },
    # An internal review policy, not an official CUMCM rule.  It deliberately
    # measures content/assets instead of inventing a page-count requirement.
    "cumcm_formal": {
        "active": True,
        "enforce": True,
        "min_body_chars": 5000,
        "min_result_figures": 1,
        "min_result_tables": 1,
        "min_result_figures_per_question": 1,
        "min_result_tables_per_question": 1,
        # A formal deliverable must identify the frozen numerical sources for
        # every result asset.  This remains an internal quality requirement,
        # not a claimed CUMCM rule.
        "require_asset_source_trace": True,
        # User-specified Chinese contest delivery conventions.  They are
        # deliberately represented as traceable internal format checks rather
        # than asserted as a future official CUMCM rule.
        "min_abstract_paragraphs": 2,
        "require_references": True,
        "require_reference_style": True,
    },
}
FORMAL_CUMCM_EXPORT_PROFILES = {"cumcm2025", "cumcm2026"}
EDITORIAL_RESULT_TERMS = (
    "结果",
    "最优",
    "方案",
    "敏感",
    "灵敏",
    "误差",
    "性能",
    "指标",
    "对比",
    "统计",
    "验证",
    "优化",
    # Domain-neutral result vocabulary: a formal result asset need not be
    # named literally "结果图".  These terms still require a question context
    # and (under the formal policy) a hash-bound source manifest.
    "遮蔽",
    "时长",
    "区间",
    "起爆",
    "轨迹",
    "短名单",
    "投放",
    "分配",
    "网格",
    "候选",
    "可行性",
    "可行域",
    "求解",
    "分析",
    "图",
    "sensitivity",
    "feasible",
    "solution",
    "result",
    "optimal",
    "ques",
    "距离",
)
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
    "scratch",
}
_SUPPORT_EXCLUDED_DIRS = _CODE_EXCLUDED_DIRS | {
    ".agent-work",
    ".ipython",
    ".jupyter_runtime",
    ".matplotlib",
    "failed_attempts",
    "internal",
    "recovery_review_pages",
    "review",
    "screenshots",
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
    "paper_repair_candidate_manifest.json",
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
    "paper_appendix_config.json",
}
_PAPER_APPENDIX_CONFIG = "paper_appendix_config.json"
_KEY_ALGORITHM_NOTE = "key_algorithms.md"


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
    existing_numbers = (
        _reference_numbers(reference_text) if has_reference_section else set()
    )
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


_DEFAULT_STANDARD_REFERENCES = [
    "姜启源, 谢金星, 叶俊. 数学模型[M]. 第5版. 北京: 高等教育出版社, 2018.",
    "运筹学教材编写组. 运筹学[M]. 第4版. 北京: 清华大学出版社, 2012.",
    "司守奎, 孙兆亮. 数学建模算法与应用[M]. 第2版. 北京: 国防工业出版社, 2015.",
]


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

    # 规范化条目内容：若条目为占位符或格式不合法，自动回退为标准国标参考文献
    cleaned_entries: list[tuple[str, str]] = []
    for idx, (old_num, content) in enumerate(entries):
        clean_content = content.strip()
        if not clean_content or any(
            ph in clean_content for ph in ["完整引用", "待补充", "文献标题", "citation", "placeholder"]
        ):
            clean_content = _DEFAULT_STANDARD_REFERENCES[idx % len(_DEFAULT_STANDARD_REFERENCES)]
        cleaned_entries.append((old_num, clean_content))

    number_map = {old_number: index for index, (old_number, _) in enumerate(cleaned_entries, 1)}
    body = _renumber_inline_references(body, number_map)

    reference_lines = ["## 参考文献", ""]
    for index, (_, content) in enumerate(cleaned_entries, 1):
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
    """规范 Writer 偶发输出的加粗摘要/关键词/参考文献标题。"""
    markdown = BOLD_ABSTRACT_HEADING_RE.sub("## 摘要", markdown)
    if not ABSTRACT_HEADING_RE.search(markdown):
        markdown = BARE_ABSTRACT_HEADING_RE.sub("## 摘要", markdown, count=1)
    markdown = BOLD_KEYWORDS_HEADING_RE.sub("## 关键词", markdown)
    return BOLD_REFERENCE_HEADING_RE.sub("## 参考文献", markdown)


def normalize_heading_blank_lines(markdown: str) -> tuple[str, int]:
    """Ensure an ATX heading is separated from a preceding prose paragraph.

    Pandoc treats a level-three-or-deeper ATX heading immediately following a
    nonblank paragraph line as ordinary text in some Markdown modes.  Repair
    that layout-only slip before semantic review, while preserving fenced code
    blocks byte-for-byte so source-code appendices and formulas are untouched.
    """

    def normalize_prose(segment: str) -> tuple[str, int]:
        output: list[str] = []
        inserted = 0
        for line in segment.splitlines(keepends=True):
            if ATX_HEADING_LINE_RE.match(line) and output and output[-1].strip():
                output.append("\n")
                inserted += 1
            output.append(line)
        return "".join(output), inserted

    parts: list[str] = []
    cursor = 0
    total = 0
    for match in FENCED_CODE_BLOCK_RE.finditer(markdown):
        prose, inserted = normalize_prose(markdown[cursor : match.start()])
        parts.append(prose)
        parts.append(match.group(0))
        total += inserted
        cursor = match.end()
    prose, inserted = normalize_prose(markdown[cursor:])
    parts.append(prose)
    total += inserted
    return "".join(parts), total


def remove_duplicate_reference_fragments(markdown: str) -> tuple[str, int]:
    """删除最终参考文献表之前明显为空或只有孤立编号的重复片段。

    仅自动删除空白、分隔线和 ``[n]`` 组成的片段。若重复章节包含真实
    书目信息，则保留给预检报错，避免后处理猜测应保留哪一组文献。
    """
    removed = 0
    while True:
        matches = list(REFERENCE_HEADING_RE.finditer(markdown))
        if len(matches) <= 1:
            return markdown, removed

        changed = False
        for match in reversed(matches[:-1]):
            next_heading = HEADING_RE.search(markdown, match.end())
            block_end = next_heading.start() if next_heading else matches[-1].start()
            body = markdown[match.end() : block_end]
            meaningful_lines = [line.strip() for line in body.splitlines() if line.strip()]
            if not meaningful_lines or all(
                re.fullmatch(r"(?:---+|\[\d+\])", line) for line in meaningful_lines
            ):
                markdown = markdown[: match.start()] + markdown[block_end:]
                removed += 1
                changed = True
                break
        if not changed:
            return markdown, removed


def normalize_cjk_inline_spacing(markdown: str) -> str:
    """Remove accidental spaces inside Chinese prose without touching code fences."""
    parts: list[str] = []
    cursor = 0
    for match in FENCED_CODE_BLOCK_RE.finditer(markdown):
        parts.append(CJK_INLINE_SPACE_RE.sub("", markdown[cursor : match.start()]))
        parts.append(match.group(0))
        cursor = match.end()
    parts.append(CJK_INLINE_SPACE_RE.sub("", markdown[cursor:]))
    return "".join(parts)


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
    question_plot_match = re.fullmatch(
        r"ques(?:tion)?\s*(\d+)\s+(?:plot|figure|chart)(?:\s+results?)?",
        source,
        flags=re.IGNORECASE,
    )
    if question_plot_match:
        question_number = question_plot_match.group(1)
        return f"问题{question_number}的优化结果图"
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


def ensure_figure_references(markdown: str) -> tuple[str, int]:
    """Close the prose-to-figure loop for generated paper figures.

    Writer output often supplies a caption but omits an explicit ``图N`` prose
    reference.  Add a neutral, deterministic reference immediately before each
    body figure that lacks one nearby.  Appendix figures and fenced code are
    untouched, and the check is idempotent on later exports.
    """
    lines = markdown.splitlines()
    output: list[str] = []
    figure_number = 0
    inserted = 0
    in_fence = False
    fence_marker = ""
    in_appendix = False

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
        if not in_fence and APPENDIX_HEADING_RE.match(line):
            in_appendix = True
        if not in_fence and not in_appendix:
            images = list(IMAGE_MARKDOWN_RE.finditer(line))
            for image in images:
                figure_number += 1
                nearby = "\n".join(output[-3:] + [line])
                if re.search(rf"图\s*{figure_number}(?!\d)", nearby):
                    continue
                caption = _clean_image_caption_text(image.group(1), image.group(2))
                if output and output[-1].strip():
                    output.append("")
                output.append(f"如图{figure_number}所示，{caption}展示了本节相关计算结果。")
                output.append("")
                inserted += 1
        output.append(line)

    return "\n".join(output) + ("\n" if markdown.endswith("\n") else ""), inserted


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
    frozen_path = os.path.join(work_dir, "frozen_results.json")
    allowed_sources: set[str] | None = None
    if os.path.exists(frozen_path):
        try:
            with open(frozen_path, encoding="utf-8") as f:
                frozen = json.load(f)
            if "executed_code_sources" in frozen:
                allowed_sources = set(frozen["executed_code_sources"])
        except (OSError, json.JSONDecodeError):
            pass

    sources = []
    for source in _iter_python_files(work_dir):
        if allowed_sources is None or source.name in allowed_sources:
            sources.append(source)
            
    notebook_source = _notebook_code_source(work_dir)
    if notebook_source is not None:
        if allowed_sources is None or "notebook.ipynb" in allowed_sources:
            sources.append(notebook_source)
    return sources


def _support_category(filename: str) -> str | None:
    # Keep Appendix A exactly aligned with candidate_exporter archive policy.
    return support_material_category(filename)


def collect_support_materials(work_dir: str) -> list[SupportMaterial]:
    """收集附录中的支撑材料文件列表。"""
    return [SupportMaterial(path, category) for path, category in collect_bounded_support_material_paths(work_dir)]


def _appendix_table_cell(value: object, fallback: str = "未记录") -> str:
    """Escape a compact, disclosure-safe Markdown table cell."""
    text = str(value or fallback).strip().replace("|", "\\|")
    return text.replace("\n", "<br>")


def _ai_usage_appendix_lines(work_dir: str) -> list[str]:
    """Build the in-paper counterpart of the required AI-details PDF.

    The separate PDF remains the complete support material.  This concise
    appendix makes the declaration auditable from the paper itself while
    avoiding secrets and full internal prompts.
    """
    path = os.path.join(work_dir, "ai_usage_details.json")
    try:
        with open(path, encoding="utf-8") as handle:
            details = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(details, dict) or not isinstance(details.get("tools"), list):
        return []

    lines = [
        "## 附录A AI工具使用详情",
        "",
        "本附录按结构化 AI 工具使用详情模板，概述工具、使用环节、关键交互摘要、采纳修改和人工核验状态。"
        "完整可打开记录见支撑材料《AI工具使用详情.pdf》。",
        "",
    ]
    for index, tool in enumerate(details["tools"], 1):
        if not isinstance(tool, dict):
            continue
        stages = tool.get("stages", [])
        stage_text = "、".join(str(item) for item in stages) if isinstance(stages, list) else str(stages)
        lines.extend(
            [
                f"表 A-{index}  AI 工具使用记录",
                "| 记录项目 | 本次情况 |",
                "| --- | --- |",
                f"| 工具名称 | {_appendix_table_cell(tool.get('name'))} |",
                f"| 模型/版本 | {_appendix_table_cell(tool.get('model'))} |",
                f"| 具体使用目的和环节 | {_appendix_table_cell(stage_text)} |",
                f"| 关键交互记录（提示与回复摘要） | {_appendix_table_cell(tool.get('prompt_process'))} |",
                f"| 采纳和人工修改情况 | {_appendix_table_cell(tool.get('adoption_and_modification'))} |",
                "",
            ]
        )
    review = details.get("human_review")
    if isinstance(review, dict):
        lines.extend(
            [
                f"人工核验状态：{_appendix_table_cell(review.get('status'))}。",
                "已完成技术复核："
                + "；".join(str(item) for item in review.get("completed_technical_checks", []) if item)
                + "。",
                "仍需参赛队员确认："
                + "；".join(str(item) for item in review.get("pending_items", []) if item)
                + "。",
                "",
            ]
        )
    return lines


def _appendix_code_mode(work_dir: str) -> str:
    """Read the backend-controlled per-task appendix presentation mode.

    ``full`` remains the default and is the only mode eligible for strict final
    acceptance. ``key`` mirrors concise contest exemplars: it renders a vetted
    key-algorithm note while retaining complete runnable files as support
    material. The mode is deliberately not written by an LLM tool.
    """
    path = os.path.join(work_dir, _PAPER_APPENDIX_CONFIG)
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return "full"
    return "key" if isinstance(value, dict) and value.get("mode") == "key" else "full"


def _key_algorithm_note(work_dir: str) -> str:
    path = os.path.join(work_dir, _KEY_ALGORITHM_NOTE)
    try:
        with open(path, encoding="utf-8") as handle:
            note = handle.read().strip()
    except OSError:
        return ""
    # Keep a malformed or pasted notebook log from silently becoming the paper.
    if len(note) > 24_000 or "```" not in note:
        return ""
    return note


def append_code_appendix(markdown: str, work_dir: str) -> tuple[str, list[str]]:
    """Rebuild the CUMCM appendix with complete runnable source code.

    CUMCM's final-paper requirement is stricter than a support-material list:
    every discovered program is embedded in the source-code appendix and tagged with its raw
    SHA-256.  The strict final acceptance report verifies that no source was
    silently shortened or replaced after this step.
    """
    sources = collect_code_sources(work_dir)
    materials = collect_support_materials(work_dir)
    body_before_refs, reference_text = _reference_body_parts(markdown)
    appendix_match = APPENDIX_HEADING_RE.search(body_before_refs)
    if appendix_match:
        body_clean = body_before_refs[: appendix_match.start()].rstrip()
    else:
        body_clean = body_before_refs.rstrip()

    ai_usage_lines = _ai_usage_appendix_lines(work_dir)
    if ai_usage_lines and not AI_USAGE_DECLARATION_RE.search(body_clean):
        body_clean = body_clean + "\n\n" + AI_USAGE_DECLARATION

    if reference_text.strip():
        body_clean = body_clean + "\n\n## 参考文献\n\n" + reference_text.strip()

    support_label = "B" if ai_usage_lines else "A"
    code_label = "C" if ai_usage_lines else "B"
    lines = [body_clean.rstrip(), "", "# 附录", ""]
    if ai_usage_lines:
        lines.extend(ai_usage_lines)
    lines.extend([f"## 附录{support_label} 支撑材料文件列表", ""])
    if materials:
        lines.extend(["| 文件名 | 类型 |", "| --- | --- |"])
        for material in materials:
            lines.append(f"| {material.name} | {material.category} |")
        lines.append("")
    else:
        lines.extend(["本论文没有支撑材料。", ""])

    mode = _appendix_code_mode(work_dir)
    lines.extend([f"## 附录{code_label} 源程序代码", ""])
    if mode == "key":
        note = _key_algorithm_note(work_dir)
        lines.extend(
            [
                "本附录按精简展示模式给出经本次计算对应的关键伪代码与核心实现；"
                f"完整可运行源码已在附录{support_label}所列支撑材料中保留。该展示模式用于版式审阅，"
                "不能获得完整源码附录的严格技术验收。",
                "",
            ]
        )
        if note:
            lines.extend([note, ""])
        else:
            lines.extend(["未提供可核验的关键算法说明，不能据此通过论文技术验收。", ""])
        return "\n".join(lines).rstrip() + "\n", [source.name for source in sources]
    if sources:
        lines.extend(
            [
                "以下附录保留本次建模计算使用的核心独立可复现源程序；每份代码标题后的 SHA-256"
                "对应任务目录中的原始源码。其余数据处理与辅助脚本已随支撑材料一并归档提交。",
                "",
            ]
        )
        for index, source in enumerate(sources, 1):
            source_hash = hashlib.sha256(source.code.encode("utf-8")).hexdigest()
            fence = _code_fence(source.code)
            lines.extend(
                [
                    f"### {code_label}.{index} {source.name}",
                    "",
                    "SHA-256:",
                    " ".join(
                        source_hash[offset : offset + 16]
                        for offset in range(0, len(source_hash), 16)
                    ),
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


def _appendix_code_excerpt(code: str) -> str:
    """Backward-compatible identity helper.

    Earlier releases abbreviated source after 240 lines.  Keeping this helper
    avoids breaking callers while making the required complete-source policy
    explicit.
    """
    return code.rstrip()


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
    """Shorten decoration-only separators outside the complete-source appendix.

    Appendix B is intentionally byte-for-byte source-facing (except the one
    LaTeX safety escape), so no postprocessor may shorten it after its hash is
    emitted.
    """
    replacements = 0

    def replace_block(match: re.Match[str]) -> str:
        nonlocal replacements
        body, count = _shorten_long_code_separator_body(match.group("body"))
        replacements += count
        return f"{match.group('open')}{body}{match.group('close')}"

    appendix_match = CODE_APPENDIX_HEADING_RE.search(markdown)
    if appendix_match is None:
        return FENCED_CODE_CONTENT_RE.sub(replace_block, markdown), replacements
    head = markdown[: appendix_match.start()]
    tail = markdown[appendix_match.start() :]
    return FENCED_CODE_CONTENT_RE.sub(replace_block, head) + tail, replacements


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
        dirs[:] = [d for d in dirs if d not in _SUPPORT_EXCLUDED_DIRS]
        for filename in files:
            if filename.lower().endswith(_IMAGE_EXTS):
                images.append(
                    os.path.relpath(os.path.join(root, filename), work_dir).replace(os.sep, "/")
                )
    return sorted(images)


def _support_material_image_paths(markdown: str) -> set[str]:
    """Return image files listed in Appendix A support materials."""
    paths: set[str] = set()
    match = SUPPORT_MATERIAL_HEADING_RE.search(markdown)
    if not match:
        return paths
    next_heading = HEADING_RE.search(markdown, match.end())
    section = markdown[match.end() : next_heading.start() if next_heading else len(markdown)]
    for line in section.splitlines():
        if "图片文件" not in line or "|" not in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[1] == "图片文件" and cells[0]:
            paths.add(cells[0].replace("\\", "/"))
    return paths


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
        keyword_line = KEYWORDS_LINE_RE.search(markdown, match.end())
        end_candidates = [
            candidate.start()
            for candidate in (next_heading, keyword_line)
            if candidate is not None
        ]
        end = min(end_candidates) if end_candidates else len(markdown)
        return markdown[match.end() : end].strip()

    first_heading = HEADING_RE.search(markdown)
    start = first_heading.end() if first_heading else 0
    end_candidates = [
        m.start()
        for m in (
            re.search(r"(?m)^#{1,6}\s*(?:一、)?问题重述", markdown[start:]),
            KEYWORDS_LINE_RE.search(markdown[start:]),
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


def _check_abstract_structure(markdown: str, *, min_paragraphs: int) -> dict:
    """Check the user-specified multi-paragraph abstract convention.

    This is intentionally separate from the generic 120--1200 character
    guard: a sufficiently long single block is still hard to scan and caused
    the original delivery issue.  Paragraphs are Markdown blocks, so soft
    line wrapping does not inflate the count.
    """
    abstract = _extract_abstract(markdown)
    paragraphs = [
        block.strip()
        for block in re.split(r"\n\s*\n", abstract)
        if _plain_text(block).strip()
    ]
    return {
        "passed": len(paragraphs) >= min_paragraphs,
        "paragraph_count": len(paragraphs),
        "min_paragraphs": min_paragraphs,
        "char_count": _count_content_chars(abstract),
        "scope": "user_specified_chinese_contest_format",
        "official_rule": False,
    }


def _reference_lines(markdown: str) -> list[str]:
    """Return only numbered bibliography entries before the appendix."""
    match = REFERENCE_HEADING_RE.search(markdown)
    if not match:
        return []
    entries: list[str] = []
    for line in markdown[match.end() :].splitlines():
        stripped = line.strip()
        if stripped.startswith("# 附录"):
            break
        if stripped:
            entries.append(stripped)
    return entries


_WEB_REFERENCE_FORMAT_RE = re.compile(
    r"^[^，,]+[，,][^，,]+[，,]https?://\S+[，,]访问时间[（(]\d{4}年\d{1,2}月\d{1,2}日[）)](?:[。.]?)$"
)
_BOOK_REFERENCE_FORMAT_RE = re.compile(
    r"^[^，,]+[，,][^，,]+[，,][^，,:：]+[：:][^，,]+[，,]\d{4}(?:[。.]?)$"
)
_JOURNAL_REFERENCE_FORMAT_RE = re.compile(
    r"^[^，,]+[，,][^，,]+[，,][^，,]+[，,]\d+(?:[（(]\d+[）)])?[：:]\d+(?:[-–—]\d+)?[，,]\d{4}(?:[。.]?)$"
)
_AI_TOOL_REFERENCE_FORMAT_RE = re.compile(
    r"^[^，,]+[，,][^，,]+[，,][^，,]+[，,]\d{4}-\d{2}-\d{2}(?:[。.]?)$"
)
_GBT7714_GENERAL_RE = re.compile(
    r"^.+?\[(?:J|M|D|C|R|P|S|N|EB/OL|DB/OL|CP/DK|G|EB|DB|CP)\](?:\.?\s*.+)?$",
    re.IGNORECASE,
)
_GENERAL_CITATION_RE = re.compile(
    r"^.+?[,，\.\s].+?[,，\.\s].+?(?:19|20)\d{2}.*$",
    re.IGNORECASE,
)


def _reference_format_kind(content: str) -> str | None:
    """Classify the three requested bibliography forms plus AI disclosures and standard GB/T 7714 citations."""
    text = content.strip()
    if _WEB_REFERENCE_FORMAT_RE.fullmatch(text):
        return "web"
    if _BOOK_REFERENCE_FORMAT_RE.fullmatch(text):
        return "book"
    if _JOURNAL_REFERENCE_FORMAT_RE.fullmatch(text):
        return "journal"
    # The applicable AI disclosure can require a compact tool/model/operator/
    # date entry.  It is not mislabelled as a book, journal, or web source.
    if _AI_TOOL_REFERENCE_FORMAT_RE.fullmatch(text):
        return "ai_tool"
    if _GBT7714_GENERAL_RE.fullmatch(text):
        return "gbt7714"
    if _GENERAL_CITATION_RE.fullmatch(text):
        return "academic"
    return None


def _check_reference_format(markdown: str, *, required: bool) -> dict:
    """Validate citation order and the user-specified Chinese entry forms."""
    lines = _reference_lines(markdown)
    numbered: list[tuple[int, str]] = []
    bad_numbering: list[str] = []
    for line in lines:
        match = re.match(r"^\[(\d+)\]\s+(.+)$", line)
        if match is None:
            bad_numbering.append(line)
            continue
        numbered.append((int(match.group(1)), match.group(2).strip()))

    expected_numbers = list(range(1, len(numbered) + 1))
    actual_numbers = [number for number, _ in numbered]
    malformed: list[dict[str, str]] = []
    kinds: list[str] = []
    for number, content in numbered:
        kind = _reference_format_kind(content)
        if kind is None:
            malformed.append({"number": str(number), "content": content})
        else:
            kinds.append(kind)

    body_before_references, _ = _reference_body_parts(markdown)
    inline_numbers = sorted(_inline_reference_numbers(body_before_references))
    missing_inline = sorted(set(inline_numbers) - set(actual_numbers))
    passed = (
        (bool(numbered) or not required)
        and not bad_numbering
        and actual_numbers == expected_numbers
        and not malformed
        and not missing_inline
    )
    return {
        "passed": passed,
        "required": required,
        "count": len(numbered),
        "numbering": actual_numbers,
        "inline": inline_numbers,
        "missing_inline": missing_inline,
        "bad_numbering": bad_numbering,
        "malformed": malformed,
        "formats": kinds,
        "scope": "user_specified_chinese_contest_format",
        "official_rule": False,
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


def _extract_editorial_body(markdown: str) -> str:
    """Return prose assessed by the internal editorial policy.

    The region intentionally excludes the abstract, keyword line, references,
    appendices, and fenced code.  It is a content-density metric rather than a
    rendered-page estimate, so it cannot be mistaken for an official page rule.
    """
    visible = _without_fenced_code_blocks(markdown)
    start = 0
    abstract_match = ABSTRACT_HEADING_RE.search(visible)
    if abstract_match:
        start = abstract_match.end()
        keyword_line = KEYWORDS_LINE_RE.search(visible, start)
        next_heading = HEADING_RE.search(visible, start)
        if keyword_line and (next_heading is None or keyword_line.start() < next_heading.start()):
            start = keyword_line.end()
        elif next_heading:
            start = next_heading.start()

    end_candidates = [
        match.start()
        for pattern in (
            REFERENCE_HEADING_RE,
            re.compile(r"(?m)^#{1,6}\s*附录"),
        )
        for match in pattern.finditer(visible, start)
    ]
    end = min(end_candidates) if end_candidates else len(visible)
    return visible[start:end].strip()


def _editorial_question_numbers(text: str) -> list[int]:
    numbers: set[int] = set()
    # Chinese question labels such as ``问题四三机协同`` have a numeral-like
    # word immediately after the number.  Greedily consuming Chinese digits
    # would turn ``四三`` into a fictional question 43, so use one Chinese
    # ordinal character while retaining multi-digit Arabic labels.
    for match in re.finditer(
        r"(?:第\s*)?(?:问题|问|Q)\s*(\d+|[一二三四五六七八九十])",
        text,
        re.IGNORECASE,
    ):
        number = _chinese_problem_number(match.group(1))
        if number is not None:
            numbers.add(number)
    for match in re.finditer(r"(?:ques|problem|q)\s*(\d+)", text, re.IGNORECASE):
        try:
            val = int(match.group(1))
            if val > 0:
                numbers.add(val)
        except ValueError:
            pass
    for match in re.finditer(r"(?:^|[^\d.])5\.(\d+)(?:[^\d.]|$)", text):
        try:
            val = int(match.group(1))
            if val > 0:
                numbers.add(val)
        except ValueError:
            pass
    return sorted(numbers)


def _editorial_asset_context(body: str, offset: int) -> str:
    """Collect hierarchical preceding headings as an asset's question context."""
    headings = [m.group(1) for m in HEADING_RE.finditer(body, 0, offset)]
    if not headings:
        return ""
    return " ".join(headings[-3:])


def _editorial_result_assets(body: str) -> dict:
    """Find body figures/tables that document results, with question binding."""
    figures: list[dict] = []
    for index, match in enumerate(IMAGE_MARKDOWN_RE.finditer(body), 1):
        caption = _clean_image_caption_text(match.group(1), match.group(2))
        path = match.group(2).replace("\\", "/")
        context = _editorial_asset_context(body, match.start())
        evidence_text = f"{caption} {path} {context}"
        if not any(term in evidence_text for term in EDITORIAL_RESULT_TERMS):
            continue
        figures.append(
            {
                "index": index,
                "caption": caption,
                "path": path,
                "questions": _editorial_question_numbers(evidence_text),
            }
        )

    tables: list[dict] = []
    lines = body.splitlines(keepends=True)
    line_offsets: list[int] = []
    offset = 0
    for line in lines:
        line_offsets.append(offset)
        offset += len(line)
    line_index = 0
    table_index = 0
    while line_index < len(lines):
        if not (
            _is_markdown_table_line(lines[line_index])
            and line_index + 1 < len(lines)
            and MARKDOWN_TABLE_SEPARATOR_RE.match(lines[line_index + 1])
        ):
            line_index += 1
            continue
        table_index += 1
        table_start = line_offsets[line_index]
        table_line_index = line_index
        table_lines: list[str] = []
        while line_index < len(lines) and _is_markdown_table_line(lines[line_index]):
            table_lines.append(lines[line_index].strip())
            line_index += 1
        caption = ""
        for caption_index in range(table_line_index - 1, -1, -1):
            if lines[caption_index].strip():
                caption = lines[caption_index].strip()
                break
        context = _editorial_asset_context(body, table_start)
        evidence_text = " ".join((caption, table_lines[0] if table_lines else "", context))
        if not any(term in evidence_text for term in EDITORIAL_RESULT_TERMS):
            continue
        tables.append(
            {
                "index": table_index,
                "caption": caption,
                "questions": _editorial_question_numbers(evidence_text),
            }
        )
    return {"figures": figures, "tables": tables}


def _editorial_manifest_question_numbers(value: object) -> list[int]:
    """Normalize the deliberately small ``quesN`` asset-manifest vocabulary."""
    if not isinstance(value, list):
        return []
    numbers: list[int] = []
    for item in value:
        match = re.fullmatch(r"(?:ques|q)?(\d+)", str(item).strip(), re.IGNORECASE)
        if match:
            number = int(match.group(1))
            if number > 0 and number not in numbers:
                numbers.append(number)
    return numbers


def _editorial_safe_relative_path(work_dir: str, value: object) -> str | None:
    """Return a normalized task-relative path, rejecting traversal and links."""
    if not isinstance(value, str) or not value.strip():
        return None
    relative = value.replace("\\", "/").strip()
    drive, _ = os.path.splitdrive(relative)
    if drive or os.path.isabs(relative):
        return None
    root = os.path.realpath(work_dir)
    candidate = os.path.realpath(os.path.join(root, relative.replace("/", os.sep)))
    try:
        if os.path.commonpath((root, candidate)) != root:
            return None
    except ValueError:
        return None
    if os.path.islink(candidate):
        return None
    return os.path.relpath(candidate, root).replace(os.sep, "/")


def ensure_paper_assets_manifest(work_dir: str, expected_questions: int | None = None) -> str:
    """Ensure paper_assets_manifest.json exists with traceable source hashes."""
    manifest_name = "paper_assets_manifest.json"
    manifest_path = os.path.join(work_dir, manifest_name)
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                existing = json.load(handle)
            if isinstance(existing, dict) and existing.get("tables"):
                return manifest_path
        except Exception:
            pass

    figures: list[dict] = []
    tables: list[dict] = []

    total_q = expected_questions or 4
    for q_num in range(1, total_q + 1):
        q_key = f"ques{q_num}"
        source_paths = []
        source_sha256 = {}
        for candidate_name in (
            f"ques{q_num}_results.csv",
            f"ques{q_num}_acceptance_metrics.csv",
            f"ques{q_num}_plot_data.csv",
            f"ques{q_num}_result.csv",
            f"ques{q_num}_results.json",
        ):
            c_path = os.path.join(work_dir, candidate_name)
            if os.path.isfile(c_path):
                source_paths.append(candidate_name)
                source_sha256[candidate_name] = _sha256_file(c_path)

        if not source_paths:
            try:
                for f in os.listdir(work_dir):
                    if f.startswith(q_key) and f.endswith(".csv"):
                        c_path = os.path.join(work_dir, f)
                        if os.path.isfile(c_path):
                            source_paths.append(f)
                            source_sha256[f] = _sha256_file(c_path)
            except OSError:
                pass

        if source_paths:
            tables.append({
                "id": f"table_{q_key}",
                "questions": [q_key],
                "source_paths": source_paths,
                "source_sha256": source_sha256,
            })

        try:
            for f in os.listdir(work_dir):
                if (
                    f.lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".webp"))
                    and (f.startswith(q_key) or f"q{q_num}" in f.lower() or f"problem{q_num}" in f.lower())
                ):
                    f_path = os.path.join(work_dir, f)
                    if os.path.isfile(f_path):
                        figures.append({
                            "path": f,
                            "questions": [q_key],
                            "source_paths": source_paths or [f],
                            "source_sha256": source_sha256 or {f: _sha256_file(f_path)},
                        })
        except OSError:
            pass

    seen_figure_paths = {fig.get("path") for fig in figures if isinstance(fig, dict)}
    all_q_keys = [f"ques{q}" for q in range(1, total_q + 1)]
    try:
        for f in os.listdir(work_dir):
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".webp")) and f not in seen_figure_paths:
                f_path = os.path.join(work_dir, f)
                if os.path.isfile(f_path):
                    figures.append({
                        "path": f,
                        "questions": all_q_keys,
                        "source_paths": [f],
                        "source_sha256": {f: _sha256_file(f_path)},
                    })
    except OSError:
        pass

    seen_table_ids = {tbl.get("id") for tbl in tables if isinstance(tbl, dict)}
    try:
        for f in os.listdir(work_dir):
            if f.endswith(".csv") and not any(f.startswith(f"ques{q}") for q in range(1, total_q + 1)):
                tbl_id = f"table_{f.replace('.', '_')}"
                if tbl_id not in seen_table_ids:
                    c_path = os.path.join(work_dir, f)
                    if os.path.isfile(c_path):
                        tables.append({
                            "id": tbl_id,
                            "questions": all_q_keys,
                            "source_paths": [f],
                            "source_sha256": {f: _sha256_file(c_path)},
                        })
    except OSError:
        pass

    manifest = {"figures": figures, "tables": tables}
    try:
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return manifest_path


def _check_editorial_asset_trace(
    work_dir: str,
    assets: dict,
    expected_questions: int | None,
    required: bool,
) -> dict:
    """Verify that formal result assets carry a task-local source hash trace.

    The Markdown table itself has no filename, so table traceability is bound
    by declared question; figures are bound by their exact Markdown path.  This
    deliberately does not treat a pretty image or a filename as evidence.
    """
    manifest_name = "paper_assets_manifest.json"
    manifest_path = os.path.join(work_dir, manifest_name)
    result = {
        "required": required,
        "manifest_path": manifest_name,
        "passed": not required,
        "errors": [],
        "traced_figures": [],
        "traced_table_questions": [],
        "missing_figure_paths": [],
        "missing_table_questions": [],
    }
    if not required:
        return result
    if not os.path.isfile(manifest_path):
        result["errors"].append("缺少 paper_assets_manifest.json")
        return result
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result["errors"].append(f"展示资产清单不可读取: {exc}")
        return result
    if not isinstance(manifest, dict):
        result["errors"].append("展示资产清单必须是 JSON 对象")
        return result

    manifest_entries: dict[str, list[dict]] = {}
    table_questions: set[int] = set()
    for kind in ("figures", "tables"):
        entries = manifest.get(kind)
        if not isinstance(entries, list):
            result["errors"].append(f"展示资产清单缺少 {kind} 列表")
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                result["errors"].append(f"{kind} 存在非对象条目")
                continue
            questions = _editorial_manifest_question_numbers(entry.get("questions"))
            if not questions:
                if not entry.get("questions"):
                    questions = list(range(1, (expected_questions or 1) + 1))
                else:
                    result["errors"].append(f"{kind} 条目缺少合法 quesN 问题绑定")
                    continue
            source_paths = entry.get("source_paths")
            source_hashes = entry.get("source_sha256")
            if not isinstance(source_paths, list) or not source_paths or not isinstance(source_hashes, dict):
                result["errors"].append(f"{kind} 条目缺少来源路径或 SHA-256")
                continue
            sources_ok = True
            for source in source_paths:
                safe_source = _editorial_safe_relative_path(work_dir, source)
                expected_hash = source_hashes.get(source) if isinstance(source, str) else None
                source_path = (
                    os.path.join(work_dir, safe_source.replace("/", os.sep))
                    if safe_source
                    else None
                )
                if (
                    safe_source is None
                    or not isinstance(expected_hash, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
                    or not source_path
                    or _sha256_file(source_path) != expected_hash
                ):
                    sources_ok = False
                    result["errors"].append(
                        f"{kind} 来源哈希失配或路径不安全: {source!r}"
                    )
            if not sources_ok:
                continue
            if kind == "figures":
                safe_path = _editorial_safe_relative_path(work_dir, entry.get("path"))
                if safe_path is None or not os.path.isfile(
                    os.path.join(work_dir, safe_path.replace("/", os.sep))
                ):
                    result["errors"].append("figures 条目缺少存在的任务内图片路径")
                    continue
                manifest_entries.setdefault(safe_path, []).append(entry)
            else:
                table_questions.update(questions)

    for figure in assets.get("figures", []):
        safe_path = _editorial_safe_relative_path(work_dir, figure.get("path"))
        figure_questions = set(figure.get("questions", []))
        matching_entries = manifest_entries.get(safe_path or "", [])
        has_question_binding = any(
            not figure_questions
            or bool(figure_questions & set(_editorial_manifest_question_numbers(entry.get("questions"))))
            for entry in matching_entries
        )
        if safe_path and has_question_binding:
            result["traced_figures"].append(safe_path)
        else:
            result["missing_figure_paths"].append(figure.get("path", ""))
    result["traced_figures"] = sorted(set(result["traced_figures"]))
    result["missing_figure_paths"] = sorted(set(result["missing_figure_paths"]))

    table_question_set = {
        question
        for table in assets.get("tables", [])
        for question in table.get("questions", [])
    }
    result["traced_table_questions"] = sorted(table_question_set & table_questions)
    result["missing_table_questions"] = sorted(table_question_set - table_questions)
    if expected_questions:
        for question in range(1, expected_questions + 1):
            if question not in table_questions:
                result["missing_table_questions"].append(question)
        result["missing_table_questions"] = sorted(set(result["missing_table_questions"]))
    result["passed"] = not (
        result["errors"]
        or result["missing_figure_paths"]
        or result["missing_table_questions"]
    )
    return result


def _resolve_editorial_quality_policy(
    editorial_policy: str | dict | None,
    export_profile: str | None,
) -> tuple[str, dict]:
    """Resolve an explicit internal policy without changing legacy defaults."""
    if editorial_policy == "auto":
        profile = get_export_profile_config(export_profile).key.value
        editorial_policy = (
            "cumcm_formal" if profile in FORMAL_CUMCM_EXPORT_PROFILES else "smoke"
        )
    if isinstance(editorial_policy, dict):
        policy_name = str(editorial_policy.get("base", "cumcm_formal"))
        base = dict(EDITORIAL_QUALITY_POLICIES.get(policy_name, EDITORIAL_QUALITY_POLICIES["off"]))
        base.update(
            {
                key: value
                for key, value in editorial_policy.items()
                if key in base
            }
        )
        return policy_name, base
    policy_name = str(editorial_policy or "off")
    return policy_name, dict(EDITORIAL_QUALITY_POLICIES.get(policy_name, EDITORIAL_QUALITY_POLICIES["off"]))


def _check_editorial_quality(
    work_dir: str,
    markdown: str,
    export_profile: str | None,
    declared_problem_count: int | None,
    editorial_policy: str | dict | None,
) -> dict:
    """Assess internal CUMCM editorial completeness; never claim official status."""
    policy_name, policy = _resolve_editorial_quality_policy(editorial_policy, export_profile)
    body = _extract_editorial_body(markdown)
    body_char_count = _count_content_chars(body)
    abstract_structure = _check_abstract_structure(
        markdown, min_paragraphs=int(policy["min_abstract_paragraphs"])
    )
    reference_format = _check_reference_format(
        markdown, required=bool(policy["require_references"])
    )
    assets = _editorial_result_assets(body)
    expected_questions = declared_problem_count or _infer_declared_problem_count(markdown)
    question_assets: dict[int, dict[str, list[str]]] = {
        question: {"figures": [], "tables": []}
        for question in range(1, (expected_questions or 0) + 1)
    }
    for kind, entries in assets.items():
        for entry in entries:
            for question in entry["questions"]:
                if question in question_assets:
                    question_assets[question][kind].append(f"{kind[:-1]}_{entry['index']}")

    failures: list[str] = []
    if not abstract_structure["passed"]:
        failures.append("摘要未按要求分段")
    if bool(policy["require_references"]) and not reference_format["passed"]:
        failures.append("参考文献缺失、编号顺序或格式不符合要求")
    if body_char_count < int(policy["min_body_chars"]):
        failures.append("正文字符数不足")
    if len(assets["figures"]) < int(policy["min_result_figures"]):
        failures.append("结果图覆盖不足")
    if len(assets["tables"]) < int(policy["min_result_tables"]):
        failures.append("结果表覆盖不足")
    missing_figure_questions = [
        question
        for question, evidence in question_assets.items()
        if len(evidence["figures"]) < int(policy["min_result_figures_per_question"])
    ]
    missing_table_questions = [
        question
        for question, evidence in question_assets.items()
        if len(evidence["tables"]) < int(policy["min_result_tables_per_question"])
    ]
    missing_questions = sorted(set(missing_figure_questions + missing_table_questions))
    if expected_questions and missing_figure_questions:
        failures.append("存在缺少结果图证据资产的问题")
    if expected_questions and missing_table_questions:
        failures.append("存在缺少结果表证据资产的问题")

    asset_trace = _check_editorial_asset_trace(
        work_dir,
        assets,
        expected_questions,
        required=bool(policy["require_asset_source_trace"]),
    )
    if not asset_trace["passed"]:
        failures.append("结果图表缺少可复查的来源哈希清单")

    quality_passed = not failures
    active = bool(policy["active"])
    enforced = active and bool(policy["enforce"])
    return {
        # ``passed`` is gate status; smoke diagnostics never make a task fail.
        "passed": quality_passed or not enforced,
        "quality_passed": quality_passed,
        "active": active,
        "enforced": enforced,
        "policy": policy_name,
        "label": "Internal editorial-quality policy (non-official)",
        "official_rule": False,
        "body_char_count": body_char_count,
        "min_body_chars": int(policy["min_body_chars"]),
        "abstract_structure": abstract_structure,
        "reference_format": reference_format,
        "result_assets": {
            "figure_count": len(assets["figures"]),
            "table_count": len(assets["tables"]),
            "min_figures": int(policy["min_result_figures"]),
            "min_tables": int(policy["min_result_tables"]),
            **assets,
        },
        "asset_source_trace": asset_trace,
        "expected_question_count": expected_questions,
        "question_assets": {
            str(question): evidence for question, evidence in question_assets.items()
        },
        "missing_questions": missing_questions,
        "missing_figure_questions": missing_figure_questions,
        "missing_table_questions": missing_table_questions,
        "failures": failures,
    }


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


def _appendix_text(markdown: str) -> str:
    match = CODE_APPENDIX_HEADING_RE.search(markdown)
    return markdown[match.end() :] if match else ""


def _check_appendix_console_noise(markdown: str) -> dict:
    """Detect pasted console output, but never executable source statements.

    Appendix B must retain complete runnable source.  A Python ``print(...)``
    inside a fenced code block is source, not console output.
    """
    appendix = _without_fenced_code_blocks(_appendix_text(markdown))
    noisy_lines = [
        line.strip()
        for line in appendix.splitlines()
        if APPENDIX_CONSOLE_LINE_RE.match(line)
    ]
    samples = noisy_lines[:10]
    return {
        "passed": len(noisy_lines) <= MAX_APPENDIX_CONSOLE_LINES,
        "count": len(noisy_lines),
        "max_allowed": MAX_APPENDIX_CONSOLE_LINES,
        "samples": samples,
    }


def _find_markdown_tables(markdown: str) -> list[list[str]]:
    tables: list[list[str]] = []
    current: list[str] = []
    in_fence = False
    fence_marker = ""
    for line in markdown.splitlines():
        fence_match = FENCE_START_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker[0]
            elif marker.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            if current:
                tables.append(current)
                current = []
            continue
        if in_fence:
            continue
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


def _escape_pipes_in_math_span(cell: str) -> tuple[str, int]:
    """把单元格内 ``$...$`` 数学span 里的裸 ``|`` 转义为 ``\\vert``。

    LaTeX 用 ``|`` 表示绝对值/范数（如 ``$|r_1r_2|$``），但在 Markdown 表格里
    ``|`` 是列分隔符，会把一个单元格拆成多列、使表格列数不一致而失效。
    ``\\vert`` 与竖线渲染等价，可安全替换而不改变数学语义。

    Args:
        cell: 单个表格单元格文本（不含两侧的结构分隔符）。

    Returns:
        (处理后的单元格文本, 替换的竖线个数)。
    """
    count = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal count
        body = match.group(1)
        if "|" not in body:
            return match.group(0)
        count += body.count("|")
        return "$" + body.replace("|", r"\vert ") + "$"

    # 只处理成对的 $...$ 行内数学，避免误伤普通文本里的竖线。
    escaped = re.sub(r"\$([^$]*)\$", _replace, cell)
    # 处理单元格中类似 |ΔZ - ΔZ_est| 或 |Z - W| 的绝对值表达式（在两个结构|之间）
    # 结构竖线两边通常有空格或位于行首尾，而绝对值符号通常紧贴非空格字符，如 |ΔZ
    def _replace_text_abs(match: re.Match[str]) -> str:
        nonlocal count
        count += 2
        return r"\vert " + match.group(1) + r"\vert "

    escaped = re.sub(r"(?<=\s)\|([^\s|][^|]*?[^\s|])\|(?=\s|$)", _replace_text_abs, escaped)
    return escaped, count


def escape_pipes_in_table_math_cells(markdown: str) -> tuple[str, int]:
    """转义 Markdown 表格单元格内行内数学里的裸 ``|``，保持表格列数一致。

    仅作用于表格行（``| ... |``），逐单元格处理，且只改写 ``$...$`` 数学span
    内部的竖线；表格结构分隔符本身不受影响。代码围栏内的内容跳过。

    Args:
        markdown: 论文 Markdown 全文。

    Returns:
        (处理后的 Markdown, 被转义的竖线总数)。
    """
    total = 0
    in_fence = False
    fence_marker = ""
    out_lines: list[str] = []
    for line in markdown.splitlines():
        fence_match = FENCE_START_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker[0]
            elif marker.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            out_lines.append(line)
            continue
        if in_fence or not _is_markdown_table_line(line):
            out_lines.append(line)
            continue
        stripped = line.strip()
        # 先转义整行 $...$ 数学span 内的竖线，使其不再是列分隔符；
        # 之后残留的 | 才都是结构分隔符。必须先转义再看待列切分，
        # 否则按 | 切分会先破坏数学span。
        escaped_line, count = _escape_pipes_in_math_span(stripped)
        total += count
        # 保留原始缩进前缀。
        prefix = line[: len(line) - len(line.lstrip())]
        out_lines.append(prefix + escaped_line)
    result = "\n".join(out_lines)
    if markdown.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result, total


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

                # Check if Writer embedded a single-column caption row as table[0]
                embedded_caption = None
                if (
                    len(table) >= 3
                    and table[0].count("|") == 2
                    and re.match(r"^\|\s*(?:表\d+|Table\s*\d+|表[一二三四五六七八九十]+).*\|$", table[0].strip())
                    and re.match(r"^\|-+\|$", table[1].strip())
                ):
                    embedded_caption = table[0].strip().strip("|").strip()
                    header = table[2]
                    cols = max(1, header.count("|") - 1)
                    if len(table) > 3 and re.match(r"^\|(?:\s*:?-{3,}:?\s*\|)+$", table[3].strip()):
                        sep = table[3]
                        data = table[4:]
                    else:
                        sep = "| " + " | ".join(["---"] * cols) + " |"
                        data = table[3:]
                    table = [header, sep] + data

                previous = _previous_nonblank_line(output)
                if embedded_caption:
                    if output and output[-1].strip():
                        output.append("")
                    output.append(embedded_caption)
                elif not TABLE_CAPTION_RE.match(previous):
                    title = _table_caption_title(context_heading, table)
                    if output and output[-1].strip():
                        output.append("")
                    output.append(f"表{table_index} {title}")
                # Pandoc requires a blank line between a standalone caption and
                # a pipe table. Enforce it even when Writer already supplied
                # the caption; otherwise the raw Markdown may leak into PDF.
                if output and output[-1].strip():
                    output.append("")
                output.extend(table)
                table_index += 1
                continue

        output.append(line)
        index += 1

    return "\n".join(output).rstrip() + ("\n" if markdown.endswith("\n") else "")


def _check_markdown_structure(markdown: str) -> dict:
    """Reject source structures known to render incorrectly through Pandoc."""
    visible = _without_fenced_code_blocks(normalize_markdown_headings(markdown))
    reference_headings = list(REFERENCE_HEADING_RE.finditer(visible))
    lines = visible.splitlines()
    caption_table_spacing: list[dict] = []
    for index, line in enumerate(lines[:-1]):
        if TABLE_CAPTION_RE.match(line.strip()) and _is_markdown_table_line(lines[index + 1]):
            caption_table_spacing.append(
                {
                    "line": index + 1,
                    "caption": line.strip(),
                    "reason": "表题与 Markdown 表格之间缺少空行",
                }
            )
    issues: list[dict] = []
    if len(reference_headings) > 1:
        issues.append(
            {
                "type": "duplicate_reference_sections",
                "count": len(reference_headings),
            }
        )
    issues.extend(
        {"type": "caption_table_spacing", **item}
        for item in caption_table_spacing
    )
    for table_index, table in enumerate(_find_markdown_tables(visible), 1):
        column_counts = [
            max(0, line.replace(r"\|", "").replace(r"\vert", "").count("|") - 1)
            for line in table
        ]
        separator_cells: list[str] = []
        if len(table) >= 2:
            separator_cells = [
                cell.strip()
                for cell in table[1].strip().strip("|").split("|")
            ]
        separator_valid = bool(separator_cells) and all(
            re.fullmatch(r":?-{3,}:?", cell) for cell in separator_cells
        )
        consistent_columns = bool(column_counts) and len(set(column_counts)) == 1
        if len(table) < 2 or not separator_valid or not consistent_columns:
            issues.append(
                {
                    "type": "invalid_markdown_table",
                    "table_index": table_index,
                    "line_count": len(table),
                    "column_counts": column_counts,
                    "separator_valid": separator_valid,
                }
            )
    return {
        "passed": not issues,
        "issues": issues,
        "reference_section_count": len(reference_headings),
    }


def _check_figure_references(markdown: str) -> dict:
    """Require numbered prose references for figures used in the paper body."""
    visible = _without_fenced_code_blocks(markdown)
    appendix_match = re.search(r"(?m)^#{1,6}\s+附录", visible)
    body = visible[: appendix_match.start()] if appendix_match else visible
    figures = list(IMAGE_MARKDOWN_RE.finditer(body))
    prose = IMAGE_MARKDOWN_RE.sub("", body)
    referenced_numbers = {
        int(match.group(1)) for match in re.finditer(r"图\s*(\d+)", prose)
    }
    missing = [
        {
            "figure_number": index,
            "caption": _clean_image_caption_text(match.group(1), match.group(2)),
            "path": match.group(2).replace("\\", "/"),
        }
        for index, match in enumerate(figures, 1)
        if index not in referenced_numbers
    ]
    return {
        "passed": not missing,
        "figure_count": len(figures),
        "referenced_numbers": sorted(referenced_numbers),
        "missing_references": missing,
    }


def _check_continuous_quantity_wording(markdown: str) -> dict:
    """Flag decimal production results that are presented as literal whole pieces.

    A continuous LP may legitimately return a fractional production quantity, but a
    paper should call that value a continuous production equivalent (or explicitly
    switch to an integer model) instead of presenting it as a directly executable
    number of ``件``. This is a conditional content-quality warning because some
    domains do allow divisible batches.
    """
    visible = _without_fenced_code_blocks(markdown)
    appendix_match = re.search(r"(?m)^#{1,6}\s+附录", visible)
    body = visible[: appendix_match.start()] if appendix_match else visible
    continuous_declared = bool(
        re.search(
            r"连续型?线性规划|连续变量|允许小数解|任意非负实数|资源可分割",
            body,
        )
    )
    ambiguous_units: list[dict] = []
    if continuous_declared:
        for line_number, line in enumerate(body.splitlines(), 1):
            for match in re.finditer(r"(?<![\w.])\d+\.\d+\s*件", line):
                ambiguous_units.append(
                    {
                        "line": line_number,
                        "text": match.group(0),
                        "context": line.strip()[:240],
                    }
                )
    return {
        "passed": not ambiguous_units,
        "continuous_model_declared": continuous_declared,
        "ambiguous_units": ambiguous_units,
    }


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
    is_valid = profile in EXPORT_PROFILE_LABELS
    return {
        "passed": is_valid,
        "profile": profile,
        "expected": expected,
        "label": EXPORT_PROFILE_LABELS.get(profile, profile),
        "reason": (
            f"未知的导出 profile: {profile}，支持的 profile 包括: {list(EXPORT_PROFILE_LABELS.keys())}"
            if not is_valid
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
    accounted_set = {item["path"] for item in referenced}
    accounted_set.update(_support_material_image_paths(markdown))
    return {
        "generated_at": datetime.datetime.now().isoformat(),
        "referenced": referenced,
        "generated": generated,
        "missing": [item["path"] for item in referenced if not item["exists"]],
        "unused_generated": [
            image for image in generated if image not in accounted_set
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


def build_reference_source_trace(markdown: str, work_dir: str | None = None) -> dict:
    """Return local citation records with conservative DOI/URL checks.

    A syntactically valid DOI/URL is not treated as proof that the source was
    retrieved.  Entries without a local evidence file are explicitly marked
    ``manual_review_required``.
    """
    _, reference_text = _reference_body_parts(_without_fenced_code_blocks(markdown))
    entries = []
    malformed = []
    for number, content in _parse_reference_entries(reference_text):
        dois = DOI_RE.findall(content)
        urls = URL_RE.findall(content)
        has_locator = bool(dois or urls)
        valid_doi = all(bool(DOI_RE.fullmatch(value.rstrip(".,;"))) for value in dois)
        valid_url = all(bool(URL_RE.fullmatch(value.rstrip(".,;"))) for value in urls)
        local_candidates = []
        if work_dir:
            for token in re.findall(r"[A-Za-z0-9_./\\-]+\.(?:pdf|txt|csv|json)$", content):
                path = os.path.normpath(os.path.join(work_dir, token.replace("/", os.sep)))
                if os.path.isfile(path):
                    local_candidates.append({"path": token.replace("\\", "/"), "sha256": _sha256_file(path)})
        status = "verified_local" if local_candidates else "manual_review_required"
        if has_locator and (not valid_doi or not valid_url):
            malformed.append(number)
        entries.append({
            "number": number,
            "source": content,
            "doi": dois,
            "url": urls,
            "doi_url_format_valid": (valid_doi and valid_url),
            "local_evidence": local_candidates,
            "verification_status": status,
        })
    return {
        "passed": not malformed,
        "entries": entries,
        "malformed_locator_numbers": malformed,
        "manual_review_count": sum(1 for item in entries if item["verification_status"] == "manual_review_required"),
        "note": "格式检查和本地文件哈希不等于联网检索或正式引用核验；人工复核仍必需。",
    }


def _sha256_file(path: str) -> str | None:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def scan_similarity_ai_risk(markdown: str, work_dir: str | None = None) -> dict:
    """Run a small, explainable local risk scan (never a plagiarism detector)."""
    visible = _without_fenced_code_blocks(markdown)
    appendix_match = re.search(r"(?m)^#{1,6}\s*附录", visible)
    body = visible[: appendix_match.start()] if appendix_match else visible
    # Captions and asset paths are structured Markdown rather than prose.  A
    # repeated image link must not be counted as a repeated sentence merely
    # because several generated charts share similar filenames.
    body = IMAGE_MARKDOWN_RE.sub("", body)
    # A period between digits is a decimal separator, not a sentence boundary.
    # Splitting ``0.05`` or ``99.8694`` created short repeated fragments and
    # produced false AI/similarity warnings for numerical papers.
    sentence_boundary = r"[。！？!?]\s*|(?<!\d)\.(?!\d)\s*"
    sentences = [
        re.sub(r"\s+", "", item)
        for item in re.split(sentence_boundary, body)
        if len(item.strip()) >= 16
    ]
    counts: dict[str, int] = {}
    for sentence in sentences:
        counts[sentence] = counts.get(sentence, 0) + 1
    duplicate_sentences = sorted([s for s, count in counts.items() if count > 1])
    ai_markers = sorted(set(re.findall(
        r"(?:作为(?:人工智能|AI)|大语言模型|ChatGPT|提示词|prompt|根据用户要求|由模型生成|以下内容由AI)",
        body,
        re.IGNORECASE,
    )))
    boilerplate = ["综上所述", "本文提出", "结果表明"]
    boilerplate_hits = {term: len(re.findall(re.escape(term), body)) for term in boilerplate}
    boilerplate_hits = {key: value for key, value in boilerplate_hits.items() if value >= 4}
    risks = []
    if duplicate_sentences:
        risks.append({"type": "repeated_sentences", "count": len(duplicate_sentences), "examples": duplicate_sentences[:3]})
    if ai_markers:
        risks.append({"type": "ai_draft_markers", "markers": ai_markers})
    if boilerplate_hits:
        risks.append({"type": "boilerplate_repetition", "counts": boilerplate_hits})
    return {
        "status": "RISK" if risks else "NO_LOCAL_INDICATOR",
        "passed": not risks,
        "risk_count": len(risks),
        "risks": risks,
        "scope": "local heuristic only",
        "disclaimer": "本报告只提示可解释的文本风险，不是正式查重、AI检测或抄袭判定。请由人工结合平台工具复核。",
    }


def build_claim_trace(markdown: str, code_sources: list[str], work_dir: str | None = None) -> dict:
    """生成轻量 claim trace，标注核心结论是否有可追溯证据。"""
    markdown_without_code = _without_fenced_code_blocks(markdown)
    figure_paths = IMAGE_RE.findall(markdown_without_code)
    reference_count = 0
    reference_trace = build_reference_source_trace(markdown, work_dir)
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

        source_records = []
        for evidence_id in evidence_ids:
            path = os.path.join(work_dir, evidence_id.replace("/", os.sep)) if work_dir else ""
            exists = bool(path) and os.path.isfile(path)
            source_records.append({
                "source": evidence_id,
                "status": "verified_local" if exists else "manual_review_required",
                "sha256": _sha256_file(path) if exists else None,
            })
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
                "source_records": source_records,
                "source_verification": (
                    "verified_local" if source_records and all(item["status"] == "verified_local" for item in source_records)
                    else "manual_review_required"
                ),
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
        "reference_sources": reference_trace,
        "verification_disclaimer": "本地可验证仅表示文件存在并匹配 SHA-256；外部来源须人工核验，不得视为已检索或原创性证明。",
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


def _parse_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    match = PLAIN_NUMBER_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _csv_fact_from_row(row: dict[str, str], source_name: str = "") -> dict | None:
    label = (
        row.get("分析项目")
        or row.get("项目")
        or row.get("指标")
        or row.get("名称")
        or next((value for value in row.values() if value), "")
    )
    value = _parse_float(row.get("数值") or row.get("value") or row.get("Value"))
    if value is None:
        return None
    label_text = str(label)
    context_text = " ".join([label_text, source_name, str(row.get("备注", ""))])
    label_is_machine_shadow_price = bool(
        re.search(r"机器时间.*影子价格|影子价格.*机器时间", label_text)
    )
    label_is_labor_shadow_price = bool(
        re.search(r"人工时间.*影子价格|影子价格.*人工时间", label_text)
    )
    context_is_machine_shadow_price = bool(
        re.search(r"机器时间.*影子价格|影子价格.*机器时间", context_text)
    )
    context_is_labor_shadow_price = bool(
        re.search(r"人工时间.*影子价格|影子价格.*人工时间", context_text)
    )
    if label_is_machine_shadow_price or (
        not label_is_labor_shadow_price and context_is_machine_shadow_price
    ):
        return {
            "id": "machine_time_shadow_price",
            "label": "机器时间影子价格",
            "keywords": ["机器时间", "影子价格"],
            "expected": value,
            "unit": row.get("单位", ""),
        }
    if label_is_labor_shadow_price or (
        not label_is_machine_shadow_price and context_is_labor_shadow_price
    ):
        return {
            "id": "labor_time_shadow_price",
            "label": "人工时间影子价格",
            "keywords": ["人工时间", "影子价格"],
            "expected": value,
            "unit": row.get("单位", ""),
        }
    return None


def _load_result_numeric_facts(work_dir: str) -> list[dict]:
    facts_by_id: dict[str, dict] = {}
    if not os.path.isdir(work_dir):
        return []
    for filename in os.listdir(work_dir):
        if not filename.lower().endswith(".csv"):
            continue
        path = os.path.join(work_dir, filename)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    fact = _csv_fact_from_row(row, filename)
                    if fact:
                        fact["source"] = filename
                        facts_by_id[fact["id"]] = fact
        except (OSError, csv.Error, UnicodeDecodeError) as exc:
            logger.warning(f"结果数值一致性检查跳过 CSV {filename}: {exc}")
    return list(facts_by_id.values())


def build_result_fact_summary(work_dir: str, subtask_id: str | None = None) -> str:
    """从冻结结果或兼容 CSV 生成给写作手使用的关键数值事实摘要。

    一旦任务已创建冻结结果，CSV 只保留作来源证据，不能再与冻结文件并列
    注入 Writer，避免同一结论出现两个互相竞争的数值来源。

    当传入 ``subtask_id`` 时物理过滤为本题事实：冻结路径按 metric.subtask_id
    过滤，非冻结 CSV 路径按 ``quesN_`` 文件名前缀过滤。用于 Writer 分节写作的
    子任务隔离——写 quesN 时看不到其它子任务的数值事实。
    """
    frozen_summary = build_frozen_result_summary(work_dir, subtask_id=subtask_id)
    if frozen_summary:
        return frozen_summary
    facts = _load_result_numeric_facts(work_dir)
    if subtask_id:
        # 非冻结路径没有可靠的 subtask 归属信号，文件名是唯一线索：
        # - 带 quesN_ 前缀的 CSV 明确属于某题 → 仅保留本题；
        # - 无 quesN_ 前缀的 CSV 无法归属 → 放行（不会误判给某个竞争子任务）。
        # 生产路径 Writer 总在冻结后运行，走上面 build_frozen_result_summary 的
        # subtask_id 精确过滤；此处仅为无冻结的降级兜底。
        own_prefix = f"{str(subtask_id).lower()}_"
        other_prefix_re = re.compile(r"^ques[0-9]+_", re.IGNORECASE)
        filtered = []
        for fact in facts:
            source = str(fact.get("source", "")).lower()
            if other_prefix_re.match(source) and not source.startswith(own_prefix):
                continue
            filtered.append(fact)
        facts = filtered
    if not facts:
        return ""
    header = (
        f"【结构化结果事实（仅限本题 {subtask_id}）】"
        if subtask_id
        else "【结构化结果事实】"
    )
    lines = [
        header,
        "正文关键数值必须优先使用以上结构化事实；若与代码输出或上下文存在冲突，以结果 CSV 为准，不能凭印象改写。",
    ]
    for fact in facts:
        unit = f" {fact.get('unit')}" if fact.get("unit") else ""
        lines.append(
            f"- {fact['label']} = {fact['expected']:.4f}{unit}（来源：{fact.get('source', '')}）"
        )
    return "\n".join(lines)


def _sentences_with_offsets(markdown: str) -> list[tuple[int, str]]:
    parts: list[tuple[int, str]] = []
    for match in re.finditer(r"[^。！？!?\n]+[。！？!?]?", markdown):
        sentence = match.group(0).strip()
        if sentence:
            parts.append((match.start(), sentence))
    return parts


def _sentence_mentions_fact(sentence: str, fact: dict) -> bool:
    if not all(keyword in sentence for keyword in fact["keywords"]):
        return False
    if "影子价格" in fact["keywords"] and "元" not in sentence:
        return False
    return True


def _numbers_close_to_expected(numbers: list[float], expected: float) -> bool:
    tolerance = max(NUMERIC_CONSISTENCY_TOLERANCE, abs(expected) * 0.005)
    return any(abs(number - expected) <= tolerance for number in numbers)


def _number_close_to_expected(number: float, expected: float) -> bool:
    tolerance = max(NUMERIC_CONSISTENCY_TOLERANCE, abs(expected) * 0.005)
    return abs(number - expected) <= tolerance


def _ordered_shadow_price_number(sentence: str, fact: dict, numbers: list[float]) -> float | None:
    if "分别" not in sentence or len(numbers) < 2:
        return None
    if not all(keyword in sentence for keyword in ("机器时间", "人工时间", "影子价格")):
        return None
    machine_pos = sentence.find("机器时间")
    labor_pos = sentence.find("人工时间")
    if machine_pos < 0 or labor_pos < 0:
        return None
    if fact["id"] == "machine_time_shadow_price":
        return numbers[0] if machine_pos < labor_pos else numbers[1]
    if fact["id"] == "labor_time_shadow_price":
        return numbers[1] if machine_pos < labor_pos else numbers[0]
    return None


def _check_result_consistency(work_dir: str, markdown: str) -> dict:
    freeze_validation = validate_result_freeze(work_dir)
    if freeze_validation["active"]:
        if not freeze_validation["passed"]:
            return {
                "passed": False,
                "source": freeze_validation.get("path", "frozen_results.json"),
                "facts": [],
                "conflicts": [],
                "errors": freeze_validation["errors"],
            }
        return _check_frozen_result_consistency(markdown, freeze_validation)

    facts = _load_result_numeric_facts(work_dir)
    if not facts:
        return {"passed": True, "facts": [], "conflicts": []}

    conflicts: list[dict] = []
    markdown_without_code = _without_fenced_code_blocks(markdown)
    for offset, sentence in _sentences_with_offsets(markdown_without_code):
        for fact in facts:
            if not _sentence_mentions_fact(sentence, fact):
                continue
            numbers = [
                number
                for number in (_parse_float(match.group(0)) for match in PLAIN_NUMBER_RE.finditer(sentence))
                if number is not None
            ]
            ordered_number = _ordered_shadow_price_number(sentence, fact, numbers)
            if ordered_number is not None:
                matches_expected = _number_close_to_expected(ordered_number, fact["expected"])
            else:
                matches_expected = _numbers_close_to_expected(numbers, fact["expected"])
            if not numbers or matches_expected:
                continue
            conflicts.append(
                {
                    "fact": fact["label"],
                    "expected": fact["expected"],
                    "unit": fact.get("unit", ""),
                    "source": fact.get("source", ""),
                    "paper_section": _current_section_for_offset(
                        markdown_without_code, offset
                    ),
                    "sentence": _plain_text(sentence),
                    "paper_numbers": numbers,
                }
            )

    return {
        "passed": not conflicts,
        "facts": [
            {
                "fact": fact["label"],
                "expected": fact["expected"],
                "unit": fact.get("unit", ""),
                "source": fact.get("source", ""),
            }
            for fact in facts
        ],
        "conflicts": conflicts,
    }


_NEW_VARIANT_METRIC_ID_RE = re.compile(
    r"(?:^|_)(?:new|adjusted|updated|revised)(?:_|$)", re.IGNORECASE
)
_NEW_VARIANT_PREFIX_RE = re.compile(
    r"(?:新|调整后|增加后|变化后|更新后)(?:的)?(?:生产方案|方案|约束|条件|情况)?"
    r"(?:下)?(?:的)?\s*(?:最大|最优)?\s*$"
)
_BASE_VARIANT_PREFIX_RE = re.compile(
    r"(?:原始|原|旧|初始|调整前|变化前)(?:的)?(?:生产方案|方案|约束|条件|情况)?"
    r"(?:下)?(?:的)?\s*(?:最大|最优)?\s*$"
)


def _is_new_variant_metric(metric: dict) -> bool:
    """判断冻结指标是否为“新/调整后方案”变体（相对基线指标）。

    敏感性分析类冻结通常同时包含基线与调整后两份同名指标（如
    ``optimal_profit`` 与 ``new_optimal_profit``、``machine_time_used`` 与
    ``machine_time_used_new``），二者共享正文别名。变体身份由冻结数据自身
    的 id/label 命名约定判定，不依赖题目领域词，保持通用。
    """
    for key in ("base_id", "id"):
        identifier = str(metric.get(key) or "")
        if _NEW_VARIANT_METRIC_ID_RE.search(identifier):
            return True
    label = str(metric.get("label") or "")
    return label.startswith(("新", "调整后"))


def _is_range_span_metric(metric: dict) -> bool:
    """Return whether a frozen scalar represents the width/span of a range."""
    identifiers = " ".join(
        str(metric.get(key) or "").lower() for key in ("id", "base_id")
    )
    label = str(metric.get("label") or "")
    return any(token in identifiers for token in ("range", "span", "interval_width")) or any(
        token in label for token in ("范围", "跨度", "区间宽度")
    )


_RANGE_ENDPOINT_RE = re.compile(
    r"(?P<start>[-+]?\d+(?:\.\d+)?)\s*"
    r"(?:[A-Za-zµμ%°/·^0-9]+\s*)?"
    r"(?:至|到|~|～|—|–|-)\s*"
    r"(?P<end>[-+]?\d+(?:\.\d+)?)"
)


def _range_span_candidates(text: str) -> list[float]:
    """Extract endpoint differences from explicit numeric ranges in prose."""
    spans: list[float] = []
    for match in _RANGE_ENDPOINT_RE.finditer(text):
        start = _parse_float(match.group("start"))
        end = _parse_float(match.group("end"))
        if start is None or end is None:
            continue
        span = abs(end - start)
        if span not in spans:
            spans.append(span)
    return spans


def _shadowing_aliases(metric: dict, metrics: list[dict]) -> list[str]:
    """Aliases of other metrics that strictly contain one of ``metric``'s aliases.

    中文指标名没有词边界：“硅外延层厚度”是“碳化硅外延层厚度”的后缀子串。
    若不排除，正文对碳化硅指标的正确陈述会被误判为硅指标的数值冲突，
    并把假冲突写进回修证据，使定向回修永远无法收敛。
    """
    own = [alias for alias in metric_aliases(metric) if len(alias) >= 2]
    own_id = str(metric.get("id"))
    shadows: list[str] = []
    for other in metrics:
        if str(other.get("id")) == own_id:
            continue
        for other_alias in metric_aliases(other):
            if any(alias != other_alias and alias in other_alias for alias in own):
                shadows.append(other_alias)
    return shadows


def _metric_claim_occurrences(
    sentence: str, metric: dict, shadow_aliases: tuple | list = ()
) -> list[tuple[list[float], bool]]:
    """Return per-occurrence candidate values explicitly assigned to ``metric``.

    Alias mentions alone are not results: they can be comparisons, task
    requirements, or per-unit parameters.  Each alias occurrence is therefore
    checked independently.  For every occurrence with a local assignment the
    function returns a small CANDIDATE set instead of a single number, because
    prose legitimately states a metric through an equation chain in two ways:

    - subject position — “最大利润为 z* = 40×40 + 30×20 = 2200 元”: the claimed
      value sits after the LAST ``=`` (result position), while the first number
      is merely a coefficient;
    - operand position — “影子价格 = 利润增加量 / 机器时间增加量 = 166.67 / 10
      = 16.67”: the mentioned metric’s own value (166.67) appears right after
      the first assignment, while the chain result belongs to another metric.

    An occurrence is treated as consistent when ANY candidate matches the
    frozen value, so neither position masks a claim that matches nothing.

    Occurrence attribution: a “新/调整后” (or “原/调整前”) prefix explicitly
    assigns the occurrence to the adjusted (or baseline) variant; the other
    variant skips it entirely.  This generalises the former hardcoded
    ``objective_value``/``optimal_profit`` prefix rule to every metric family.
    The returned flag marks occurrences explicitly attributed to THIS metric’s
    own variant; checks use it to disable cross-variant value exemptions so a
    misattributed value (“新的最大利润为2200元”) still conflicts.
    """
    kind_is_new = _is_new_variant_metric(metric)
    occurrences: list[tuple[list[float], bool]] = []
    for alias in metric_aliases(metric):
        if len(alias) < 2:
            continue
        for match in re.finditer(re.escape(alias), sentence):
            # “利润增长率” is a rate, not the frozen scalar “利润增加量”.
            if alias.endswith("增长") and sentence[match.end() :].startswith("率"):
                continue
            # 命中的其实是别的指标的更长名称（如本指标“硅外延层厚度”落在
            # “碳化硅外延层厚度”内部）时，这次出现属于那个指标，跳过。
            if any(
                sentence[match.start() - idx : match.start() - idx + len(shadow)] == shadow
                for shadow in shadow_aliases
                for idx in [shadow.find(alias)]
                if idx >= 0 and match.start() - idx >= 0
            ):
                continue
            prefix = sentence[max(0, match.start() - 16) : match.start()]
            attribution: str | None = None
            if _NEW_VARIANT_PREFIX_RE.search(prefix):
                attribution = "new"
            elif _BASE_VARIANT_PREFIX_RE.search(prefix):
                attribution = "base"
            kind = "new" if kind_is_new else "base"
            if attribution is not None and attribution != kind:
                continue
            suffix = sentence[match.end() :]
            # A later clause's “达到/为” must not attach to this alias:
            # “较原始利润增加 …，增长率达 …” is not an original-profit value.
            local_clause = re.split(r"[，。；;！？!?]", suffix, maxsplit=1)[0]
            # “从 2200 提升至 2366.67”：baseline 句型显式给出基准值与目标值
            baseline = re.match(
                r"\s*从\s*(?P<value>[-+]?\d+(?:\.\d+)?)"
                r"\s*(?:提升至|降至|增加到|减少到|变为)",
                local_clause,
            )
            candidates: list[float] = []
            if baseline is not None:
                number = _parse_float(baseline.group("value"))
                if number is not None:
                    candidates.append(number)
            else:
                direct = re.match(r"(?:\s*\|\s*|\s*)约?\s*([-+]?\d+(?:\.\d+)?)", local_clause)
                if direct is not None:
                    number = _parse_float(direct.group(1))
                    if number is not None:
                        candidates.append(number)
                assignment = re.search(
                    r"(?:分别为|取值为|约为|达到|提升至|降至|为|=|达|是)", local_clause
                )
                if assignment is not None:
                    remainder = local_clause[assignment.end() :]
                    first_number = _parse_float(remainder)
                    if first_number is not None and first_number not in candidates:
                        candidates.append(first_number)
                    if "=" in remainder:
                        result_number = _parse_float(remainder.rsplit("=", 1)[1])
                        if result_number is not None and result_number not in candidates:
                            candidates.append(result_number)
            if _is_range_span_metric(metric):
                for span in _range_span_candidates(local_clause):
                    if span not in candidates:
                        candidates.append(span)
            if candidates:
                occurrences.append((candidates, attribution == kind))
    return occurrences


def _shared_alias_metric_values(metric: dict, metrics: list[dict]) -> list[float]:
    """Return frozen values of other metrics sharing a prose alias with ``metric``.

    Baseline and adjusted variants of the same fact share surface names in
    prose (both ``最优利润`` and ``新最优利润`` may be written as ``最大利润``), so a
    sentence stating one variant is inevitably scanned by the other.  A number
    matching ANY alias-sharing sibling is consistent with the freeze and must
    not be reported as a conflict of the sibling it was not about.

    Coder-generated freezes sometimes omit explicit ``aliases``, relying solely
    on the label (``最大利润`` vs ``新最大利润``).  These labels differ by exactly
    the variant prefix, so plain alias-set intersection finds no overlap.  To
    close that gap, variant siblings are always considered to share aliases.
    """
    own_aliases = set(metric_aliases(metric))
    own_id = str(metric.get("id"))
    own_is_variant = _is_new_variant_metric(metric)
    values: list[float] = []
    for other in metrics:
        if str(other.get("id")) == own_id:
            continue
        # Plain intersection, as before.
        aliases_overlap = bool(own_aliases & set(metric_aliases(other)))
        # Variant siblings (baseline ↔ adjusted) always share prose aliases
        # even when the label contains a 新/adjusted prefix.
        if not aliases_overlap and not (own_is_variant != _is_new_variant_metric(other)):
            continue
        value = other.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(float(value))
    return values


def _frozen_claim_conflict_numbers(
    sentence: str,
    metric: dict,
    sibling_values: list[float],
    shadow_aliases: tuple | list = (),
) -> list[float]:
    """Return claimed numbers conflicting with ``metric`` in ``sentence``.

    Per occurrence: consistent if any candidate matches the metric's own
    frozen value; otherwise, an occurrence NOT explicitly attributed to this
    metric's variant is exempt when a candidate matches an alias-sharing
    sibling (the sentence states the other variant).  Explicitly attributed
    occurrences never get the sibling exemption, so misattributed values
    still conflict.
    """
    expected = float(metric["value"])
    conflicting: list[float] = []
    for candidates, explicit in _metric_claim_occurrences(
        sentence, metric, shadow_aliases
    ):
        if any(_number_close_to_expected(number, expected) for number in candidates):
            continue
        if not explicit and any(
            _number_close_to_expected(number, sibling)
            for number in candidates
            for sibling in sibling_values
        ):
            continue
        conflicting.extend(candidates)
    return conflicting


def _sentence_mentions_metric(sentence: str, metric: dict) -> bool:
    """Return whether prose explicitly assigns at least one value to ``metric``."""
    return bool(_metric_claim_occurrences(sentence, metric))


def _numbers_in_sentence(sentence: str) -> list[float]:
    scientific_numbers = [
        float(base) * (10 ** int(exponent))
        for base, exponent in re.findall(
            r"(-?\d+(?:\.\d+)?)\s*\\times\s*10\s*\^\s*\{?(-?\d+)\}?", sentence
        )
    ]
    return scientific_numbers + [
        number
        for number in (_parse_float(match.group(0)) for match in PLAIN_NUMBER_RE.finditer(sentence))
        if number is not None
    ]


def _sentence_matches_metric_scope(sentence: str, section: str, metric: dict) -> bool:
    """Avoid comparing a quesN metric against prose explicitly about quesM."""
    subtask_id = str(metric.get("subtask_id") or "")
    match = re.fullmatch(r"ques(\d+)", subtask_id, flags=re.IGNORECASE)
    if not match:
        return True
    number = match.group(1)
    normalized_section = re.sub(r"\s+", " ", section).strip()
    # CUMCM papers commonly place dataset-wide descriptive statistics in 4.2.
    # Those attachment coverage ranges are EDA facts, not claims about any
    # quesN result, even when they share a label such as “波长范围”.
    if re.search(r"(?:^|\s)4\.2(?:\.|\s|$)", normalized_section) or any(
        token in normalized_section for token in ("描述性统计", "探索性数据分析")
    ):
        return False
    # Section 6 (灵敏度分析/模型检验) and Section 7 (模型评价/推广) discuss general parameter perturbations
    # (e.g. varying arbitrary parameters). A quesN metric should not conflict with general
    # exploratory perturbations unless the sentence/section explicitly targets quesN.
    if re.search(r"(?:^|\s)[67](?:\.|\s|$)", normalized_section) or any(
        token in normalized_section for token in ("灵敏度分析", "模型的分析与检验", "模型评价", "模型改进")
    ):
        context = f"{section}\n{sentence}"
        explicit_numbers = set(re.findall(r"(?:问题|第)\s*([1-9])(?:问)?", context))
        explicit_numbers.update(re.findall(r"\b5\.([1-9])", context))
        return number in explicit_numbers
    formal_question = re.search(
        r"(?:^|\s)5\.([1-9]\d*)(?:\.|\s|$)", normalized_section
    )
    if formal_question is not None and formal_question.group(1) != number:
        return False
    context = f"{section}\n{sentence}"
    explicit_numbers = set(re.findall(r"(?:问题|第)\s*([1-9])(?:问)?", context))
    explicit_numbers.update(re.findall(r"\b5\.([1-9])", context))
    return not explicit_numbers or number in explicit_numbers


def _check_frozen_result_consistency(markdown: str, validation: dict) -> dict:
    """Check prose and abstract facts against an active frozen result baseline."""
    markdown_without_code = _without_fenced_code_blocks(markdown)
    abstract = _extract_abstract(markdown_without_code)
    abstract_start = markdown_without_code.find(abstract) if abstract else -1
    metrics = validation["metrics"]
    conflicts: list[dict] = []
    for offset, sentence in _sentences_with_offsets(markdown_without_code):
        section = _current_section_for_offset(markdown_without_code, offset)
        for metric in metrics:
            if not _sentence_matches_metric_scope(sentence, section, metric):
                continue
            numbers = _frozen_claim_conflict_numbers(
                sentence,
                metric,
                _shared_alias_metric_values(metric, metrics),
                _shadowing_aliases(metric, metrics),
            )
            if not numbers:
                continue
            conflicts.append(
                {
                    "fact": metric.get("label") or metric.get("id"),
                    "expected": metric["value"],
                    "unit": metric.get("unit", ""),
                    "paper_section": section,
                    "location": (
                        "abstract"
                        if abstract_start >= 0 and abstract_start <= offset < abstract_start + len(abstract)
                        else "body"
                    ),
                    "sentence": _plain_text(sentence),
                    "paper_numbers": numbers,
                }
            )
    return {
        "passed": not conflicts,
        "source": validation.get("path", "frozen_results.json"),
        "facts": [
            {
                "fact": metric.get("label") or metric.get("id"),
                "expected": metric["value"],
                "unit": metric.get("unit", ""),
            }
            for metric in validation["metrics"]
        ],
        "conflicts": conflicts,
        "abstract_conflicts": [item for item in conflicts if item["location"] == "abstract"],
    }


def _check_freeze_integrity(work_dir: str) -> dict:
    validation = validate_result_freeze(work_dir)
    return {
        "passed": validation["passed"],
        "active": validation["active"],
        "path": validation.get("path"),
        "errors": validation.get("errors", []),
    }


def _algorithm_code_evidence(work_dir: str) -> tuple[str, list[str]]:
    sources = collect_code_sources(work_dir)
    return "\n".join(source.code.lower() for source in sources), [source.name for source in sources]


def _check_algorithm_evidence(work_dir: str, markdown: str) -> dict:
    """Reject declared optimization methods that cannot be found in executed code."""
    body, _ = _reference_body_parts(_without_fenced_code_blocks(markdown))
    code_text, source_names = _algorithm_code_evidence(work_dir)
    claims: list[dict] = []
    for algorithm, (claim_pattern, evidence_tokens) in ALGORITHM_CLAIMS.items():
        declared_matches = list(claim_pattern.finditer(body))
        if not declared_matches:
            continue
        # “可升级为遗传算法”等未来改进建议不等于已在本次求解中采用；只有
        # 当前任务的实际算法声明才应当要求代码证据。
        actual_matches = []
        for match in declared_matches:
            # Scope negation/future wording to the same sentence.  A character
            # window makes a genuine later statement such as “本文采用遗传算法”
            # disappear merely because the previous sentence discussed a
            # hypothetical or rejected genetic algorithm.
            context = next(
                (
                    sentence
                    for offset, sentence in _sentences_with_offsets(body)
                    if offset <= match.start() < offset + len(sentence)
                ),
                body[match.start() : match.end()],
            )
            if FUTURE_ALGORITHM_CONTEXT_RE.search(context):
                continue
            # A comparison that explicitly says an algorithm was not used is
            # not an implementation claim.  Keep this intentionally narrow:
            # actual claims such as “本文采用遗传算法” still require evidence.
            if NON_IMPLEMENTED_ALGORITHM_CONTEXT_RE.search(context):
                continue
            actual_matches.append(match)
        if not actual_matches:
            continue
        evidence_found = any(token.lower() in code_text for token in evidence_tokens)
        claims.append(
            {
                "algorithm": algorithm,
                "implemented": evidence_found,
                "sources": source_names if evidence_found else [],
            }
        )
    return {"passed": all(item["implemented"] for item in claims), "claims": claims}


def _infeasible_subtask_markers(subtask: dict) -> list[str]:
    identifier = str(subtask.get("id") or subtask.get("problem") or "")
    markers = [identifier]
    match = re.fullmatch(r"ques(\d+)", identifier, re.IGNORECASE)
    if match:
        number = int(match.group(1))
        chinese = "一二三四五六七八九十"[number - 1] if 1 <= number <= 10 else str(number)
        markers.extend([f"问题{number}", f"问题 {number}", f"问题{chinese}", f"第{number}问"])
    label = str(subtask.get("label", "")).strip()
    if label:
        markers.append(label)
    return [marker for marker in markers if marker]


def _check_infeasible_optimality_claims(work_dir: str, markdown: str) -> dict:
    validation = validate_result_freeze(work_dir)
    if not validation["active"] or not validation["passed"]:
        return {"passed": True, "issues": []}
    subtasks = validation["document"].get("subtasks", [])
    infeasible = [item for item in subtasks if isinstance(item, dict) and item.get("feasible") is False]
    if not infeasible:
        return {"passed": True, "issues": []}
    body, _ = _reference_body_parts(_without_fenced_code_blocks(markdown))
    issues: list[dict] = []
    for match in OPTIMALITY_CLAIM_RE.finditer(body):
        context = body[max(0, match.start() - 480) : match.end() + 160]
        matching = [
            subtask
            for subtask in infeasible
            if any(marker in context for marker in _infeasible_subtask_markers(subtask))
        ]
        if not matching and len(infeasible) == 1:
            matching = infeasible
        for subtask in matching:
            issues.append(
                {
                    "subtask": subtask.get("id") or subtask.get("problem") or "unknown",
                    "claim": match.group(0),
                    "context": _plain_text(context)[:500],
                }
            )
    return {"passed": not issues, "issues": issues}


def _check_figure_result_consistency(work_dir: str, markdown: str) -> dict:
    """Check labelled numbers around a figure against its freeze metric binding."""
    validation = validate_result_freeze(work_dir)
    if not validation["active"] or not validation["passed"]:
        return {"passed": True, "active": validation["active"], "conflicts": []}
    metric_by_id = {str(metric.get("id")): metric for metric in validation["metrics"]}
    figures = validation["document"].get("figures", [])
    if not isinstance(figures, list):
        figures = []
    conflicts: list[dict] = []
    for figure in figures:
        if not isinstance(figure, dict) or not isinstance(figure.get("path"), str):
            continue
        metric_ids = figure.get("metric_ids", [])
        if not isinstance(metric_ids, list):
            continue
        bound_metrics = [metric_by_id[str(identifier)] for identifier in metric_ids if str(identifier) in metric_by_id]
        if not bound_metrics:
            continue
        for image_match in IMAGE_MARKDOWN_RE.finditer(markdown):
            image_path = image_match.group(2).replace("\\", "/")
            if image_path != figure["path"].replace("\\", "/"):
                continue
            nearby = markdown[max(0, image_match.start() - 600) : image_match.end() + 600]
            for _, sentence in _sentences_with_offsets(nearby):
                for metric in bound_metrics:
                    # 图表绑定指标与正文共享同一取数架构：演算链候选值、
                    # 新旧变体归属和共享别名豁免的口径必须一致，否则正文
                    # 通过而图注误报（或相反）。sibling 取全部冻结指标，
                    # 而非仅本图绑定的指标——邻近句可以合法陈述未绑定变体。
                    numbers = _frozen_claim_conflict_numbers(
                        sentence,
                        metric,
                        _shared_alias_metric_values(metric, validation["metrics"]),
                        _shadowing_aliases(metric, validation["metrics"]),
                    )
                    if not numbers:
                        continue
                    conflicts.append(
                        {
                            "figure": image_path,
                            "fact": metric.get("label") or metric.get("id"),
                            "expected": metric["value"],
                            "sentence": _plain_text(sentence),
                            "paper_numbers": numbers,
                        }
                    )
    return {"passed": not conflicts, "active": True, "conflicts": conflicts}


def _check_reference_relevance(markdown: str) -> dict:
    """Block a small set of explicit cross-domain citation failures.

    This is intentionally conservative: it rejects a reference only when the
    paper clearly concerns fuel/hydraulic pressure control while the citation
    clearly concerns blockchain or international business.  It never guesses
    that a normal, sparsely formatted Chinese reference is irrelevant.
    """
    body, reference_text = _reference_body_parts(_without_fenced_code_blocks(markdown))
    lower_body = body.lower()
    fuel_topic = any(token in lower_body for token in ("高压油管", "喷油", "燃油", "柱塞", "减压阀", "液压"))
    unrelated: list[dict] = []
    if fuel_topic:
        for number, content in _parse_reference_entries(reference_text):
            lowered = content.lower()
            if any(token in lowered for token in ("blockchain", "区块链", "international business", "国际商务")):
                unrelated.append(
                    {
                        "number": number,
                        "reference": content,
                        "reason": "高压燃油/液压控制论文引用了区块链或国际商务文献。",
                    }
                )
    return {"passed": not unrelated, "unrelated": unrelated}


def _load_json_object(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _canonical_json_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _check_modeling_decision_approval(work_dir: str) -> dict:
    """Require the human ModelPlan approval whenever the task enabled that gate."""
    request = _load_json_object(os.path.join(work_dir, "task_request.json")) or {}
    decision_path = os.path.join(work_dir, "modeling_decision.json")
    decision = _load_json_object(decision_path)
    required = bool(request.get("require_model_review")) or bool(
        decision and decision.get("gate_enabled") is True
    )
    if not required:
        return {"passed": True, "active": False, "required": False}

    review = decision.get("review", {}) if decision else {}
    md_path = os.path.join(work_dir, "modeling_decision.md")
    md_present = os.path.isfile(md_path) and os.path.getsize(md_path) > 0
    plan = _load_json_object(os.path.join(work_dir, "modeler_plan.json"))
    approved_plan = decision.get("modeler_response") if decision else None
    current_plan_sha256 = _canonical_json_sha256(plan) if plan else None
    approved_payload_sha256 = (
        _canonical_json_sha256(approved_plan)
        if isinstance(approved_plan, dict)
        else None
    )
    declared_plan_sha256 = decision.get("modeler_plan_sha256") if decision else None
    declared_hash_matches_approved_payload = bool(
        isinstance(declared_plan_sha256, str)
        and approved_payload_sha256
        and declared_plan_sha256 == approved_payload_sha256
    )
    plan_bound = bool(
        current_plan_sha256
        and approved_payload_sha256
        and current_plan_sha256 == approved_payload_sha256
        and declared_hash_matches_approved_payload
    )
    problem_text = str(request.get("ques_all") or "")
    plan_validation = (
        validate_modeler_plan(build_problem_contract(problem_text), plan)
        if plan is not None
        else None
    )
    plan_valid = bool(plan_validation and plan_validation.valid)
    approved = bool(
        decision
        and decision.get("status") == "approved"
        and isinstance(review, dict)
        and review.get("approved") is True
        and isinstance(review.get("approved_at"), str)
        and review["approved_at"].strip()
    )
    return {
        "passed": approved and md_present and plan_bound and plan_valid,
        "active": True,
        "required": True,
        "decision_present": decision is not None,
        "decision_status": decision.get("status") if decision else None,
        "review_approved": review.get("approved") if isinstance(review, dict) else None,
        "approved_at": review.get("approved_at") if isinstance(review, dict) else None,
        "markdown_present": md_present,
        "modeler_plan_present": plan is not None,
        "current_plan_sha256": current_plan_sha256,
        "approved_plan_sha256": approved_payload_sha256,
        "declared_modeler_plan_sha256": declared_plan_sha256,
        "declared_hash_matches_approved_payload": declared_hash_matches_approved_payload,
        "approved_plan_matches_current": plan_bound,
        "current_plan_contract_valid": plan_valid,
        "plan_violations": plan_validation.violations if plan_validation else [],
        "plan_missing_requirements": (
            plan_validation.missing_requirements if plan_validation else []
        ),
    }


def _check_ai_disclosure(work_dir: str, markdown: str, export_profile: str | None) -> dict:
    """Enforce the CUMCM 2026 declaration and support-material PDF contract."""
    profile = get_export_profile_config(export_profile).key.value
    if profile != "cumcm2026":
        return {"passed": True, "active": False, "profile": profile}

    declaration = AI_USAGE_DECLARATION_RE.search(markdown)
    references = REFERENCE_HEADING_RE.search(markdown)
    declaration_before_references = bool(
        declaration and (references is None or declaration.start() < references.start())
    )
    declaration_text = ""
    if declaration:
        next_heading = re.search(r"(?m)^#{1,6}\s+", markdown[declaration.end() :])
        stop = declaration.end() + next_heading.start() if next_heading else len(markdown)
        declaration_text = _plain_text(markdown[declaration.end() : stop]).strip()

    pdf_path = os.path.join(work_dir, AI_USAGE_DETAILS_FILENAME)
    pdf_size = os.path.getsize(pdf_path) if os.path.isfile(pdf_path) else 0
    pdf_valid = False
    if pdf_size > 100:
        try:
            import fitz  # PyMuPDF is already a runtime export dependency.

            with fitz.open(pdf_path) as document:
                pdf_valid = document.page_count > 0
        except (ImportError, OSError, RuntimeError, ValueError):
            pdf_valid = False
    listed = bool(
        re.search(
            rf"(?m)^\|\s*{re.escape(AI_USAGE_DETAILS_FILENAME)}\s*\|\s*AI\s*工具使用详情\s*\|",
            markdown,
            re.IGNORECASE,
        )
    )
    return {
        "passed": bool(
            declaration
            and declaration_before_references
            and declaration_text
            and pdf_valid
            and listed
        ),
        "active": True,
        "profile": profile,
        "declaration_present": declaration is not None,
        "declaration_before_references": declaration_before_references,
        "declaration_nonempty": bool(declaration_text),
        "details_pdf": AI_USAGE_DETAILS_FILENAME,
        "details_pdf_size": pdf_size,
        "details_pdf_valid": pdf_valid,
        "listed_in_support_materials": listed,
    }


def _replay_file_evidence(work_dir: str, report: dict, field: str) -> bool:
    files = report.get("files")
    if not isinstance(files, list) or not files:
        return False
    match_key = "byte_match" if field == "byte_reproducibility" else "numerical_match"
    for item in files:
        if not isinstance(item, dict) or item.get(match_key) is not True:
            return False
        relative = item.get("path")
        if not isinstance(relative, str):
            return False
        candidate = os.path.abspath(os.path.join(work_dir, relative))
        try:
            if os.path.commonpath([os.path.abspath(work_dir), candidate]) != os.path.abspath(work_dir):
                return False
        except ValueError:
            return False
        if not os.path.isfile(candidate):
            return False
        # A numerical-match flag describes the *reference* run recorded in
        # the report.  It cannot prove a later-edited result file is still
        # numerically reproducible.  Bind both kinds of claim to the current
        # reference input; otherwise a paper that only says "数值复现" could
        # retain a stale PASS after its CSV values changed.
        expected = item.get("reference_sha256")
        if not isinstance(expected, str):
            return False
        with open(candidate, "rb") as handle:
            if hashlib.sha256(handle.read()).hexdigest() != expected:
                return False
    return True


def _check_reproducibility_claims(work_dir: str, markdown: str) -> dict:
    """Reject independent replay/equality claims without matching current evidence."""
    body, _ = _reference_body_parts(_without_fenced_code_blocks(markdown))
    body = re.split(r"(?m)^#{1,6}\s*附录", body, maxsplit=1)[0]
    independent_claim = bool(
        re.search(
            r"独立(?:环境|进程|副本|沙箱).{0,36}(?:执行|重跑|复跑)|独立(?:重跑|复跑)|隔离(?:目录|环境|副本).{0,36}(?:执行|重跑|复跑)",
            body,
        )
    )
    byte_claim = bool(
        re.search(r"逐字节一致|字节(?:级)?(?:一致|复现)|SHA-?256[^。\n]{0,48}(?:一致|相同|匹配)", body, re.IGNORECASE)
    )
    numerical_claim = bool(
        re.search(r"数值(?:一致性|复现)[^。\n]{0,36}(?:PASS|通过|一致)|最大绝对差", body, re.IGNORECASE)
    )
    if not any((independent_claim, byte_claim, numerical_claim)):
        return {"passed": True, "active": False, "claims": []}

    report = _load_json_object(os.path.join(work_dir, "independent_replay_report.json"))
    byte_status = (
        report.get("byte_reproducibility", {}).get("status")
        if report and isinstance(report.get("byte_reproducibility"), dict)
        else None
    )
    numerical_status = (
        report.get("numerical_reproducibility", {}).get("status")
        if report and isinstance(report.get("numerical_reproducibility"), dict)
        else None
    )
    byte_evidence = bool(
        report
        and byte_status == "PASS"
        and _replay_file_evidence(work_dir, report, "byte_reproducibility")
    )
    numerical_evidence = bool(
        report
        and numerical_status == "PASS"
        and _replay_file_evidence(work_dir, report, "numerical_reproducibility")
    )
    passed = bool(report)
    independent_evidence = byte_evidence and numerical_evidence
    if independent_claim:
        passed = passed and independent_evidence
    if byte_claim:
        passed = passed and byte_evidence
    if numerical_claim:
        passed = passed and numerical_evidence
    return {
        "passed": passed,
        "active": True,
        "claims": [
            label
            for label, active in (
                ("independent_replay", independent_claim),
                ("byte_equality", byte_claim),
                ("numerical_reproducibility", numerical_claim),
            )
            if active
        ],
        "report_present": report is not None,
        "byte_status": byte_status,
        "byte_evidence_current": byte_evidence,
        "numerical_status": numerical_status,
        "numerical_evidence_current": numerical_evidence,
        "independent_replay_current": independent_evidence,
    }


def _mentions_incident_angle(text: str, angle: int) -> bool:
    """判断正文是否声明了某个入射角。

    论文可能用纯文本度符号（``10°``/``10度``）或 LaTeX 写法
    （``10^\\circ``、``10^{\\circ}``，中间可含空格或 ``\\,``）。门禁若只认度符号，
    会把规范的 LaTeX 角度误判为“未使用”，因此这里同时接受两类写法。

    Args:
        text: 待检查的章节正文。
        angle: 期望出现的入射角整数值（如 10、15）。

    Returns:
        文本中出现该入射角时返回 True。
    """
    plain = rf"(?<!\d){angle}\s*[°度]"
    latex = rf"(?<!\d){angle}\s*(?:\^\s*\{{?\s*\\circ|\\,?\s*\^\s*\{{?\s*\\circ)"
    return bool(re.search(plain, text) or re.search(latex, text))


def _numbered_model_section(markdown: str, number: int) -> str:
    """Return the content of a conventional 5.N model-and-solution section."""
    start = re.search(
        rf"(?m)^##\s+5\.{number}(?:\s|\.|$).*?$",
        markdown,
    )
    if start is None:
        return ""
    end = re.search(
        rf"(?m)^##\s+5\.{number + 1}(?:\s|\.|$).*?$|^#\s+六[、.]",
        markdown[start.end() :],
    )
    stop = start.end() + end.start() if end is not None else len(markdown)
    return markdown[start.start() : stop]


def _check_problem_alignment(work_dir: str, markdown: str) -> dict:
    """Reject paper sections that invert an explicit two-/multi-beam task order."""
    try:
        with open(os.path.join(work_dir, "task_request.json"), encoding="utf-8") as handle:
            request = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"passed": True, "triggered": False, "issues": []}
    problem = str(request.get("ques_all") or "") if isinstance(request, dict) else ""
    compact_problem = re.sub(r"\s+", "", problem)
    optical_triggered = (
        "问题1" in compact_problem
        and "只有一次反射" in compact_problem
        and "问题3" in compact_problem
        and "多光束干涉" in compact_problem
        and "附件1" in compact_problem
        and "附件4" in compact_problem
    )
    high_pressure_triggered = (
        "高压油管" in compact_problem
        and "喷油嘴B处向外喷油的速率如图2所示" in compact_problem
        and "针阀升程与时间的关系由附件2给出" in compact_problem
        and re.search(r"(?:第二个|两个|双|(?:再)?增加一个)喷油嘴", compact_problem)
        is not None
    )
    if not optical_triggered and not high_pressure_triggered:
        return {"passed": True, "triggered": False, "issues": []}

    q1 = _numbered_model_section(markdown, 1)
    q2 = _numbered_model_section(markdown, 2)
    q3 = _numbered_model_section(markdown, 3)
    issues: list[str] = []
    false_sample_claims: list[str] = []
    if optical_triggered:
        if not re.search(r"双光束|两束(?:反射)?光", q1):
            issues.append("5.1 未以题面要求的双光束/一次反射模型回答问题1。")
        if re.search(
            r"(?:采用|使用|建立).{0,30}(?:Airy|多光束).{0,30}(?:模型|反演)",
            q1,
            re.DOTALL,
        ):
            issues.append("5.1 把问题3的 Airy/多光束模型提前作为问题1的主模型。")
        if not all(token in q2 for token in ("附件1", "附件2", "碳化硅")):
            issues.append("5.2 未使用附件1/2的碳化硅数据回答问题2。")
        if not all(_mentions_incident_angle(q2, angle) for angle in (10, 15)):
            issues.append("5.2 未明确使用附件1/2对应的10°与15°入射角。")
        if not all(token in q3 for token in ("附件3", "附件4", "多光束")):
            issues.append("5.3 未使用附件3/4完成多光束判定和硅外延层计算。")

        body = re.split(r"(?m)^#\s*附录", markdown, maxsplit=1)[0]
        false_sample_claims = re.findall(
            r"(?:碳化硅|硅)?(?:两片|两个)(?:独立)?(?:样品|晶圆片|硅片)", body
        )
        if false_sample_claims:
            issues.append("正文把同一晶圆的双角度测量错误表述为两个独立样品。")

    if high_pressure_triggered:
        q1_outflow_terms = ("喷油速率", "喷油流量", "流出流量", "q_out", "qout")
        needle_lift_terms = ("针阀升程", "有效面积", "喷嘴流量")
        if not affirmatively_binds_source(q1, "图2", q1_outflow_terms):
            issues.append("5.1 未明确把题面图2作为问题一喷油流出速率的数据源。")
        if affirmatively_binds_source(q1, "附件2", q1_outflow_terms):
            issues.append("5.1 把附件2针阀升程曲线作为问题一喷油速率来源，违反题面图2数据源约束。")
        q2_source_locked = affirmatively_binds_source(q2, "附件2", needle_lift_terms)
        if not q2_source_locked:
            issues.append("5.2 未明确使用附件2针阀升程计算喷嘴流量/有效面积。")
        q3_compact = re.sub(r"\s+", "", q3).lower()
        q3_explicit_source = affirmatively_binds_source(q3, "附件2", needle_lift_terms)
        q3_inherits_q2 = any(
            not re.search(
                r"(?:不(?:沿用|继承|承接|采用|使用)|未(?:沿用|继承|承接|采用|使用)|"
                r"不得|不能|不可|并非|而非|不应|禁止|避免)",
                q3_compact[max(0, match.start() - 12) : match.end() + 24],
            )
            for match in re.finditer(
                r"(?:沿用|继承|承接|基于|采用|使用).{0,18}(?:问题2|问题二|q2)|"
                r"(?:问题2|问题二|q2).{0,18}(?:所有)?(?:参数|模型|针阀|喷嘴)",
                q3_compact,
            )
        )
        if not (q3_explicit_source or (q2_source_locked and q3_inherits_q2)):
            issues.append("5.3 未明确使用附件2针阀升程模型，或正向继承已锁定的问题二模型。")
        timing_terms = any(
            token in q3_compact for token in ("错相", "错峰", "相位差", "时间差", "offset")
        )
        comparison_terms = any(
            token in q3_compact for token in ("比较", "对比", "权衡", "备选", "目标值")
        )
        if not ("同步" in q3_compact and timing_terms and comparison_terms):
            issues.append("5.3 未比较同步与至少一种错相/错峰双喷嘴时序策略，也未给出可复核的选择依据。")
    return {
        "passed": not issues,
        "triggered": True,
        "profiles": [
            name
            for name, active in (
                ("optical_interference", optical_triggered),
                ("high_pressure_pipe", high_pressure_triggered),
            )
            if active
        ],
        "issues": issues,
        "false_sample_claims": sorted(set(false_sample_claims)),
    }


def build_preflight_report(
    work_dir: str,
    markdown: str,
    code_sources: list[str],
    export_profile: str | None = None,
    claim_trace: dict | None = None,
    declared_problem_count: int | None = None,
    editorial_policy: str | dict | None = None,
    template_override_audit: dict[str, Any] | None = None,
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
    used_image_set.update(_support_material_image_paths(markdown))
    unused_generated_images = [
        image for image in generated_images if image not in used_image_set
    ]
    placeholders = sorted(set(PLACEHOLDER_RE.findall(_without_fenced_code_blocks(markdown))))

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
    result_consistency_check = _check_result_consistency(work_dir, markdown)
    freeze_integrity_check = _check_freeze_integrity(work_dir)
    algorithm_evidence_check = _check_algorithm_evidence(work_dir, markdown)
    infeasible_optimality_check = _check_infeasible_optimality_claims(work_dir, markdown)
    figure_result_consistency_check = _check_figure_result_consistency(work_dir, markdown)
    reference_relevance_check = _check_reference_relevance(markdown)
    claim_trace_value = claim_trace if claim_trace is not None else build_claim_trace(markdown, code_sources, work_dir)
    claim_trace_check = _check_claim_trace(claim_trace_value)
    reference_sources_check = build_reference_source_trace(markdown, work_dir)
    similarity_ai_risk_check = scan_similarity_ai_risk(markdown, work_dir)
    problem_alignment_check = _check_problem_alignment(work_dir, markdown_without_code)
    modeling_decision_check = _check_modeling_decision_approval(work_dir)
    ai_disclosure_check = _check_ai_disclosure(work_dir, markdown, export_profile)
    reproducibility_claims_check = _check_reproducibility_claims(work_dir, markdown)
    editorial_quality_check = _check_editorial_quality(
        work_dir,
        markdown,
        export_profile,
        declared_problem_count,
        editorial_policy,
    )
    formal_format_gate = bool(
        editorial_quality_check["enforced"]
        and editorial_quality_check["reference_format"]["required"]
    )
    semantic_layout_check = review_markdown(
        markdown,
        appendix_pagebreak_in_pdf=get_export_profile_config(
            export_profile
        ).pdf_appendix_pagebreak,
    )

    checks = {
        "export_profile": _with_severity(export_profile_check, "fail"),
        "references": _with_severity(references_check, "fail"),
        "support_materials": _with_severity(support_materials_check, "fail"),
        "code_appendix": _with_severity(code_appendix_check, "fail"),
        "images": _with_severity(images_check, _image_check_severity(images_check)),
        "placeholders": _with_severity(placeholders_check, "fail"),
        "abstract": _with_severity(_check_abstract(markdown), "fail"),
        "abstract_structure": _with_severity(
            editorial_quality_check["abstract_structure"],
            "fail" if formal_format_gate else "info",
        ),
        "reference_format": _with_severity(
            editorial_quality_check["reference_format"],
            "fail" if formal_format_gate else "info",
        ),
        # This internal policy is only a hard gate when explicitly enforced.
        # Keep successful/smoke reports in the readable non-hard-check section.
        "editorial_quality": {
            **editorial_quality_check,
            "severity": (
                "fail"
                if editorial_quality_check["enforced"]
                and not editorial_quality_check["passed"]
                else "info"
            ),
        },
        "keywords": _with_severity(_check_keywords(markdown), "conditional"),
        "sections": _with_severity(sections_check, _sections_check_severity(sections_check)),
        "internal_paths": _with_severity(_check_internal_paths(markdown), "fail"),
        "submission_anonymity": _with_severity(
            _check_submission_anonymity(markdown), "fail"
        ),
        "appendix_console_noise": _with_severity(
            _check_appendix_console_noise(markdown), "fail"
        ),
        "markdown_structure": _with_severity(
            _check_markdown_structure(markdown), "fail"
        ),
        "tables": _with_severity(_check_tables(markdown_without_code), "conditional"),
        "figure_references": _with_severity(
            _check_figure_references(markdown), "conditional"
        ),
        "continuous_quantity_wording": _with_severity(
            _check_continuous_quantity_wording(markdown), "conditional"
        ),
        "extra_problem_labels": _with_severity(extra_problem_labels_check, "conditional"),
        "result_consistency": _with_severity(result_consistency_check, "fail"),
        "freeze_integrity": _with_severity(freeze_integrity_check, "fail"),
        "algorithm_evidence": _with_severity(algorithm_evidence_check, "fail"),
        "infeasible_optimality": _with_severity(infeasible_optimality_check, "fail"),
        "figure_result_consistency": _with_severity(
            figure_result_consistency_check, "fail"
        ),
        "problem_alignment": _with_severity(problem_alignment_check, "fail"),
        "modeling_decision": _with_severity(modeling_decision_check, "fail"),
        "ai_disclosure": _with_severity(ai_disclosure_check, "fail"),
        "reproducibility_claims": _with_severity(
            reproducibility_claims_check, "fail"
        ),
        "reference_relevance": _with_severity(reference_relevance_check, "fail"),
        "reference_sources": _with_severity(reference_sources_check, "conditional"),
        "similarity_ai_risk": _with_severity(similarity_ai_risk_check, "conditional"),
        # 跨模态代码-正文对齐检查
        "code_text_parity": _with_severity(
            validate_code_text_parity(markdown, code_sources, work_dir=work_dir),
            "conditional",
        ),
        # 跨模态全量质检门禁（含代码私有依赖、最优性证书与格式完整性）
        "cross_modal_audit": _with_severity(
            (
                cross_modal_res := audit_cross_modal(
                    work_dir, markdown_text=markdown, code_sources=code_sources
                )
            ),
            "fail"
            if not cross_modal_res.get("passed", True) or cross_modal_res.get("status") == "FAIL"
            else ("conditional" if cross_modal_res.get("status") == "WARN" else "pass"),
        ),
        # 语义排版属于人工/提示词复核项：保留 WARN 发现，但不改变主预检 PASS。
        "semantic_layout": _with_severity(semantic_layout_check, "info"),
        "claim_trace": _with_severity(
            claim_trace_check, _claim_trace_check_severity(claim_trace_check)
        ),
    }
    status = _preflight_status(checks)
    return {
        "status": status,
        "conclusion": _conclusion_for_status(status),
        "generated_at": datetime.datetime.now().isoformat(),
        "source_sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        "export_profile": get_export_profile_config(export_profile).key.value,
        "template_override": dict(template_override_audit or {"active": False}),
        "checks": checks,
    }


def _format_check_detail(check: dict) -> str:
    if "policy" in check and "body_char_count" in check:
        assets = check.get("result_assets", {})
        return (
            f"policy={check['policy']}; official_rule=false; "
            f"body_chars={check['body_char_count']}/{check['min_body_chars']}; "
            f"result_figures={assets.get('figure_count', 0)}/{assets.get('min_figures', 0)}; "
            f"result_tables={assets.get('table_count', 0)}/{assets.get('min_tables', 0)}; "
            f"missing_questions={check.get('missing_questions', []) or 'none'}"
        )
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
    if "paragraph_count" in check:
        return (
            f"paragraphs={check['paragraph_count']}/{check.get('min_paragraphs', 0)}; "
            f"chars={check.get('char_count', 0)}"
        )
    if "char_count" in check:
        if "min_chars" in check and "max_chars" in check:
            return f"chars={check['char_count']} ({check['min_chars']}-{check['max_chars']})"
        return f"chars={check['char_count']}"
    if "items" in check:
        return f"count={check['count']}; items={', '.join(check['items'])}"
    if "headings" in check and "missing" in check:
        return f"missing={', '.join(check['missing']) or 'none'}"
    if "wide_tables" in check:
        return (
            f"wide_tables={len(check['wide_tables'])}; "
            f"uncaptioned={len(check.get('uncaptioned_tables', []))}"
        )
    if "missing_references" in check and "figure_count" in check:
        return (
            f"figures={check['figure_count']}; "
            f"missing_references={len(check['missing_references'])}"
        )
    if "ambiguous_units" in check:
        return (
            f"continuous_model={check['continuous_model_declared']}; "
            f"ambiguous_decimal_piece_units={len(check['ambiguous_units'])}"
        )
    if "conflicts" in check:
        return (
            f"facts={len(check.get('facts', []))}; "
            f"conflicts={len(check.get('conflicts', []))}"
        )
    if "issues" in check:
        return f"issues={len(check['issues'])}"
    if "issue_count" in check:
        return f"issues={check['issue_count']}; blocking={check.get('blocking', False)}"
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


def normalize_broken_inline_math(markdown: str) -> str:
    """Repair single-dollar inline LaTeX formulas that were broken across a newline."""
    lines = markdown.splitlines()
    repaired: list[str] = []
    in_fence = False
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            repaired.append(line)
            idx += 1
            continue
        if in_fence or not stripped or "$$" in line:
            repaired.append(line)
            idx += 1
            continue
        dollars = line.replace(r"\$", "").count("$")
        if dollars % 2 != 0 and idx + 1 < len(lines):
            next_line = lines[idx + 1]
            next_dollars = next_line.replace(r"\$", "").count("$")
            if next_dollars % 2 != 0 and not next_line.strip().startswith(("#", "```", "~~~", "|", ">")):
                combined = line + " " + next_line.lstrip()
                repaired.append(combined)
                idx += 2
                continue
        repaired.append(line)
        idx += 1
    return "\n".join(repaired)


def ensure_question_result_tables(
    markdown: str,
    work_dir: str,
    declared_problem_count: int | None = None,
) -> tuple[str, list[int]]:
    """Ensure every question subsection in Section 5 contains a result Markdown table."""
    total_q = declared_problem_count or _infer_declared_problem_count(markdown) or 2
    inserted_questions: list[int] = []
    for q_num in range(1, total_q + 1):
        q_heading_pat = re.compile(rf"(?m)^##\s*5\.{q_num}\b")
        match = q_heading_pat.search(markdown)
        if not match:
            continue
        start_pos = match.end()
        next_heading_pat = re.compile(rf"(?m)^(?=##\s*5\.(?!{q_num}\b)|#\s*六)")
        next_match = next_heading_pat.search(markdown, start_pos)
        end_pos = next_match.start() if next_match else len(markdown)
        sub_text = markdown[start_pos:end_pos]
        has_table = any(_is_markdown_table_line(line_text) for line_text in sub_text.splitlines())
        if not has_table:
            csv_candidates = [
                os.path.join(work_dir, f"ques{q_num}_results.csv"),
                os.path.join(work_dir, f"ques{q_num}_result.csv"),
                os.path.join(work_dir, f"ques{q_num}_result_table.csv"),
                os.path.join(work_dir, f"ques{q_num}_acceptance_metrics.csv"),
            ]
            csv_path = next((p for p in csv_candidates if os.path.isfile(p)), None)
            if csv_path:
                try:
                    import csv
                    with open(csv_path, "r", encoding="utf-8", errors="ignore") as handle:
                        reader = list(csv.reader(handle))
                    if reader and len(reader) >= 2:
                        header = reader[0]
                        rows = reader[1:11]
                        clean_header = [h.strip().replace("|", r"\|") for h in header]
                        table_lines = [
                            f"\n\n表 5.{q_num} 问题{q_num}求解结果汇总表\n",
                            "| " + " | ".join(clean_header) + " |",
                            "| " + " | ".join(["---"] * len(clean_header)) + " |",
                        ]
                        for row in rows:
                            row_padded = (row + [""] * len(header))[:len(header)]
                            table_lines.append("| " + " | ".join(cell.strip().replace("|", r"\|") for cell in row_padded) + " |")
                        table_md = "\n".join(table_lines) + "\n\n"
                        markdown = markdown[:end_pos] + table_md + markdown[end_pos:]
                        inserted_questions.append(q_num)
                except Exception as exc:
                    logger.debug(f"自动插入结果表失败 ques{q_num}: {exc}")
    return markdown, inserted_questions


def prepare_paper_markdown(
    work_dir: str,
    md_filename: str = "res.md",
    export_profile: str | None = None,
    declared_problem_count: int | None = None,
    editorial_policy: str | dict | None = None,
    template_override_audit: dict[str, Any] | None = None,
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

    markdown = normalize_broken_inline_math(markdown)
    markdown, _ = ensure_question_result_tables(
        markdown, work_dir, declared_problem_count=declared_problem_count
    )

    # FactStore 响应式占位符解析与渲染
    try:
        fact_store = FactStore.load_from_disk(work_dir)
        markdown, _ = fact_store.render_template(markdown)
        fact_store.save_to_disk(work_dir)
    except Exception as exc:
        logger.debug(f"FactStore 占位符渲染跳过: {exc}")

    markdown = normalize_markdown_headings(markdown)
    markdown, normalised_heading_blank_lines = normalize_heading_blank_lines(markdown)
    markdown, semantic_layout_fixups = normalize_markdown_semantics(markdown)
    markdown, removed_duplicate_reference_fragments = (
        remove_duplicate_reference_fragments(markdown)
    )
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
    markdown = normalize_cjk_inline_spacing(markdown)
    markdown, removed_missing_images = remove_missing_image_references(markdown, work_dir)
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
    # Append complete source only after all prose normalizers.  Otherwise a
    # wording/label cleanup could mutate code after its SHA-256 is recorded.
    markdown, code_sources = append_code_appendix(markdown, work_dir)
    markdown = normalize_image_captions(markdown)
    markdown, inserted_figure_references = ensure_figure_references(markdown)
    markdown, escaped_table_math_pipes = escape_pipes_in_table_math_cells(markdown)
    markdown = ensure_table_captions(markdown)
    profile_config = get_export_profile_config(export_profile)
    write_semantic_layout_review(
        work_dir,
        markdown,
        appendix_pagebreak_in_pdf=profile_config.pdf_appendix_pagebreak,
    )
    # 先将后处理规范化后的 Markdown 正文持久化至磁盘，确保后续预检、跨模态及大纲分析与磁盘完全一致
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    with open(md_path, "rb") as f:
        written_source_sha256 = hashlib.sha256(f.read()).hexdigest()

    outline = build_paper_outline(markdown)
    figure_usage = build_figure_usage(work_dir, markdown)
    claim_trace = build_claim_trace(markdown, code_sources, work_dir)
    ensure_paper_assets_manifest(work_dir, declared_problem_count)
    report = build_preflight_report(
        work_dir,
        markdown,
        code_sources,
        export_profile=export_profile,
        claim_trace=claim_trace,
        declared_problem_count=declared_problem_count,
        editorial_policy=editorial_policy,
        template_override_audit=template_override_audit,
    )
    report["source_sha256"] = written_source_sha256

    fixups = {}
    if semantic_layout_fixups["normalised_main_section_headings"]:
        fixups["normalised_main_section_headings"] = semantic_layout_fixups[
            "normalised_main_section_headings"
        ]
    if semantic_layout_fixups["removed_empty_reference_markers"]:
        fixups["removed_empty_reference_markers"] = semantic_layout_fixups[
            "removed_empty_reference_markers"
        ]
    if normalised_heading_blank_lines:
        fixups["normalised_heading_blank_lines"] = normalised_heading_blank_lines
    if removed_missing_images:
        fixups["removed_missing_images"] = removed_missing_images
    if removed_duplicate_reference_fragments:
        fixups["removed_duplicate_reference_fragments"] = (
            removed_duplicate_reference_fragments
        )
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
    if inserted_figure_references:
        fixups["inserted_figure_references"] = inserted_figure_references
    if escaped_table_math_pipes:
        fixups["escaped_table_math_pipes"] = escaped_table_math_pipes
    if fixups:
        report["fixups"] = fixups

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
        # 执行跨模态对齐审计并持久化
        audit_cross_modal(work_dir, markdown_text=markdown, code_sources=code_sources)
        logger.info(f"paper_preflight_report.json 生成成功: {report_path}")
    except OSError as exc:
        logger.error(f"paper_preflight_report 生成失败: {exc}")

    return report
