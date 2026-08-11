"""语义排版审查：检查 Markdown 标题语义与模板层级，不参与数学硬门禁。"""

from __future__ import annotations

import datetime
import json
import os
import re
from typing import Any


_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_HEADING_RE = re.compile(r"^(?P<marks>#{1,6})\s+(?P<title>\S.*?)(?:\s+#+)?\s*$")
_MAIN_RE = re.compile(r"^(?P<number>[一二三四五六七八九十]+)、(?P<body>.+)$")
_DECIMAL_SUB_RE = re.compile(r"^\d+\.\d+\s+.+$")
_DECIMAL_SUBSUB_RE = re.compile(r"^\d+\.\d+\.\d+\s+.+$")
_ASSUMPTION_RE = re.compile(r"^假设\s*\d+\s*[:：].+$")
_APPENDIX_SUB_RE = re.compile(r"^附录[AB](?:\s|$).+")
_APPENDIX_CODE_RE = re.compile(r"^B\.\d+\s+.+$")
_PAGE_BREAK_RE = re.compile(
    r"(?:<!--\s*pagebreak\s*-->|\\(?:clearpage|newpage|pagebreak)\b|\f)",
    re.IGNORECASE,
)
# Empty braces are emitted by some providers when an intended citation has no
# usable entry.  Do not treat escaped LaTeX braces as a reference marker.
_EMPTY_REFERENCE_RE = re.compile(r"(?<![A-Za-z0-9\\])(?:\{\s*\})+(?![A-Za-z0-9])")
_IMAGE_RE = re.compile(r"!\[(?P<caption>[^\]]*)\]\((?P<path>[^)]+)\)")
_FILENAME_LIKE_CAPTION_RE = re.compile(r"^(?:fig(?:ure)?[\s_-]*\d*|image[\s_-]*\d*|图[\s_-]*\d*)$", re.I)


def _without_fenced_code(markdown: str) -> list[tuple[int, str]]:
    """Return source lines outside fenced code blocks with original line numbers."""
    visible: list[tuple[int, str]] = []
    in_fence = False
    fence: str | None = None
    for line_number, line in enumerate(markdown.splitlines(), start=1):
        marker = _FENCE_RE.match(line)
        if marker:
            token = marker.group(1)[0]
            if not in_fence:
                in_fence = True
                fence = token
            elif fence == token:
                in_fence = False
                fence = None
            continue
        if not in_fence:
            visible.append((line_number, line))
    return visible


def _expected_level(title: str) -> tuple[int | None, str]:
    if _MAIN_RE.match(title) or title == "附录":
        return 1, "top_level_section"
    if title == "摘要":
        return 2, "abstract"
    if _DECIMAL_SUBSUB_RE.match(title) or _APPENDIX_CODE_RE.match(title):
        return 3, "subsubsection"
    if (
        _DECIMAL_SUB_RE.match(title)
        or _ASSUMPTION_RE.match(title)
        or _APPENDIX_SUB_RE.match(title)
    ):
        return 2, "subsection"
    return None, "other"


def normalize_markdown_semantics(markdown: str) -> tuple[str, dict[str, int]]:
    """Repair unambiguous CUMCM semantic-layout slips outside code fences.

    Writer prompts ask for the required hierarchy, but a provider can still
    emit a top-level Chinese section as H2 or leave an empty citation marker.
    These two forms have deterministic, low-risk repairs.  Keep source code,
    inline/Display math and all other wording untouched so this does not turn
    the postprocessor into an unchecked prose rewriter.
    """
    output: list[str] = []
    in_fence = False
    fence: str | None = None
    normalised_main_section_headings = 0
    removed_empty_reference_markers = 0

    for line in markdown.splitlines(keepends=True):
        marker = _FENCE_RE.match(line)
        if marker:
            token = marker.group(1)[0]
            if not in_fence:
                in_fence = True
                fence = token
            elif fence == token:
                in_fence = False
                fence = None
            output.append(line)
            continue

        updated = line
        if not in_fence:
            raw_line = line.rstrip("\r\n")
            heading = _HEADING_RE.match(raw_line)
            if heading:
                title = heading.group("title").strip()
                expected_level, kind = _expected_level(title)
                if kind == "top_level_section" and expected_level == 1:
                    level = len(heading.group("marks"))
                    if level != expected_level:
                        leading = raw_line[: len(raw_line) - len(raw_line.lstrip())]
                        line_ending = line[len(raw_line) :]
                        updated = f"{leading}# {title}{line_ending}"
                        normalised_main_section_headings += 1

            # A plain ``{}`` in Chinese prose is an empty citation marker in
            # the Writer protocol.  Skip math lines, whose brace syntax must
            # be preserved for Pandoc/LaTeX.
            if "$" not in updated and re.search(r"[\u4e00-\u9fff]", updated):
                updated, removed = _EMPTY_REFERENCE_RE.subn("", updated)
                removed_empty_reference_markers += removed

        output.append(updated)

    return "".join(output), {
        "normalised_main_section_headings": normalised_main_section_headings,
        "removed_empty_reference_markers": removed_empty_reference_markers,
    }


def review_markdown(
    markdown: str,
    *,
    appendix_pagebreak_in_pdf: bool = False,
) -> dict[str, Any]:
    """Review semantic layout conventions and return non-blocking findings."""
    lines = _without_fenced_code(markdown)
    headings: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    seen_titles: dict[str, int] = {}

    for index, (line_number, line) in enumerate(lines):
        match = _HEADING_RE.match(line)
        if not match:
            continue
        level = len(match.group("marks"))
        title = match.group("title").strip()
        expected, kind = _expected_level(title)
        entry = {
            "line": line_number,
            "level": level,
            "title": title,
            "expected_level": expected,
            "kind": kind,
        }
        headings.append(entry)
        seen_titles[title] = seen_titles.get(title, 0) + 1

        if expected is not None and level != expected:
            code = (
                "main_section_level_mismatch"
                if kind == "top_level_section"
                else "subsection_level_mismatch"
            )
            issues.append(
                {
                    "code": code,
                    "line": line_number,
                    "title": title,
                    "severity": "warning",
                    "blocking": False,
                    "message": f"标题当前为 H{level}，按 CUMCM 语义应为 H{expected}。",
                    "suggestion": f"将 Markdown 标题改为 {'#' * expected} {title}。",
                }
            )

        if kind == "top_level_section":
            previous_nonempty = next(
                (value for _, value in reversed(lines[:index]) if value.strip()),
                "",
            )
            if not _PAGE_BREAK_RE.search(previous_nonempty):
                if title == "附录" and not appendix_pagebreak_in_pdf:
                    issues.append(
                        {
                            "code": "appendix_page_break_hint",
                            "line": line_number,
                            "title": title,
                            "severity": "warning",
                            "blocking": False,
                            "message": "附录在 Markdown 中紧接正文，Pandoc/article 不一定自动换页。",
                            "suggestion": "按所选模板决定是否在附录前加入受支持的分页标记，并人工检查 PDF。",
                        }
                    )

    for title, count in seen_titles.items():
        if count > 1 and title not in {"摘要"}:
            issues.append(
                {
                    "code": "duplicate_heading_title",
                    "line": next(item["line"] for item in headings if item["title"] == title),
                    "title": title,
                    "severity": "warning",
                    "blocking": False,
                    "message": f"同名标题出现 {count} 次，可能造成 PDF 书签定位歧义。",
                    "suggestion": "确认重复标题是否有必要；必要时补充问题编号或场景名称。",
                }
            )

    empty_reference_matches = [
        {"line": line_number, "text": line.strip()}
        for line_number, line in lines
        if _EMPTY_REFERENCE_RE.search(line)
    ]
    if empty_reference_matches:
        issues.append(
            {
                "code": "empty_reference_marker",
                "line": empty_reference_matches[0]["line"],
                "title": "引用标记",
                "severity": "warning",
                "blocking": False,
                "message": f"发现 {len(empty_reference_matches)} 个空引用标记 {{}}。",
                "suggestion": "删除空标记，或补充经过核验的完整引用；不得留下孤立花括号。",
                "matches": empty_reference_matches[:20],
            }
        )

    for line_number, line in lines:
        for image in _IMAGE_RE.finditer(line):
            caption = image.group("caption").strip()
            path_stem = os.path.splitext(os.path.basename(image.group("path").strip()))[0]
            normalized_caption = re.sub(r"[\s_-]+", "", caption).lower()
            normalized_stem = re.sub(r"[\s_-]+", "", path_stem).lower()
            is_ascii_machine_name = bool(re.search(r"[A-Za-z]", path_stem)) and (
                "_" in path_stem
                or "-" in path_stem
                or bool(_FILENAME_LIKE_CAPTION_RE.match(path_stem))
            )
            if (
                not caption
                or _FILENAME_LIKE_CAPTION_RE.match(caption)
                or (normalized_caption == normalized_stem and is_ascii_machine_name)
            ):
                issues.append(
                    {
                        "code": "filename_like_figure_caption",
                        "line": line_number,
                        "title": "图题",
                        "severity": "warning",
                        "blocking": False,
                        "message": "图题看起来是原始文件名或无信息编号，人工应改为说明图意的自然语言标题。",
                        "suggestion": "将图片替代文本改为能说明变量、场景或比较对象的中文图题。",
                    }
                )

    return {
        "status": "WARN" if issues else "PASS",
        "passed": not issues,
        "blocking": False,
        "scope": "Markdown semantic layout only; warnings do not replace PDF visual or human review.",
        "pdf_layout_policy": {
            "appendix_pagebreak_in_pdf": appendix_pagebreak_in_pdf,
        },
        "generated_at": datetime.datetime.now().isoformat(),
        "heading_count": len(headings),
        "headings": headings,
        "issue_count": len(issues),
        "issues": issues,
        "recommendations": [issue["suggestion"] for issue in issues],
    }


def render_semantic_layout_review(report: dict[str, Any]) -> str:
    lines = [
        "# Semantic Layout Review",
        "",
        f"- Status: `{report.get('status', 'unknown')}`",
        "- Blocking: `false`",
        f"- Scope: {report.get('scope', '')}",
        "",
        "## Findings",
        "",
        "| Code | Line | Title | Suggestion |",
        "| --- | ---: | --- | --- |",
    ]
    for issue in report.get("issues", []):
        lines.append(
            "| {code} | {line} | {title} | {suggestion} |".format(
                code=issue.get("code", ""),
                line=issue.get("line", ""),
                title=str(issue.get("title", "")).replace("|", "\\|"),
                suggestion=str(issue.get("suggestion", "")).replace("|", "\\|"),
            )
        )
    if not report.get("issues"):
        lines.append("| none |  |  | No semantic layout warning. |")
    lines.append("")
    return "\n".join(lines)


def write_semantic_layout_review(
    work_dir: str,
    markdown: str,
    *,
    appendix_pagebreak_in_pdf: bool = False,
) -> dict[str, Any]:
    """Write JSON/Markdown reports beside paper_preflight_report."""
    report = review_markdown(
        markdown,
        appendix_pagebreak_in_pdf=appendix_pagebreak_in_pdf,
    )
    try:
        with open(os.path.join(work_dir, "semantic_layout_review.json"), "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
        with open(os.path.join(work_dir, "semantic_layout_review.md"), "w", encoding="utf-8") as handle:
            handle.write(render_semantic_layout_review(report))
    except OSError:
        # The preflight report still carries the findings; report writing is best effort.
        pass
    return report
