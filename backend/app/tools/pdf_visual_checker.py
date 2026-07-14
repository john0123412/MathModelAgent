"""PDF 后验视觉检查。"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re

from app.utils.log_util import logger


REPORT_FILENAME = "pdf_visual_check.json"
A4_WIDTH_PT = 595.28
A4_HEIGHT_PT = 841.89
A4_TOLERANCE_PT = 12
TEXT_EDGE_MARGIN_PT = 6
MAX_TEXT_MARGIN_OVERFLOWS = 20
CUMCM_MIN_CONTENT_MARGIN_PT = 2.5 / 2.54 * 72
CUMCM_CONTENT_MARGIN_TOLERANCE_PT = 3.0
MAX_CUMCM_PDF_SIZE_BYTES = 20 * 1024 * 1024
MAX_CUMCM_BODY_PAGES = 30
MAX_CONTENT_MARGIN_ISSUES = 20
BODY_START_TERMS = ("问题重述", "问题分析", "模型假设", "符号说明", "模型的建立")
FORBIDDEN_SUBMISSION_TERMS = (
    "承诺书",
    "编号专用页",
    "参赛队号",
    "队员姓名",
    "指导教师",
    "所在学校",
    "学校名称",
)


def _file_sha256(path: str) -> str | None:
    if not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _write_report(work_dir: str, report: dict) -> None:
    report_path = os.path.join(work_dir, REPORT_FILENAME)
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        logger.error(f"pdf_visual_check.json 写入失败: {exc}")


def _is_a4_size(width: float, height: float) -> bool:
    return (
        abs(width - A4_WIDTH_PT) <= A4_TOLERANCE_PT
        and abs(height - A4_HEIGHT_PT) <= A4_TOLERANCE_PT
    )


def _page_has_nonblank_pixels(page) -> bool:
    pixmap = page.get_pixmap(matrix=None, alpha=False)
    samples = bytes(pixmap.samples)
    if not samples:
        return False
    stride = max(1, len(samples) // 8192)
    return len(set(samples[::stride])) > 1


def _iter_text_lines(page) -> list[dict]:
    try:
        page_text = page.get_text("dict")
    except Exception:
        return []

    lines: list[dict] = []
    for block in page_text.get("blocks", []):
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            if not text:
                continue
            lines.append({"bbox": line.get("bbox", (0, 0, 0, 0)), "text": text})
    return lines


def _is_page_number_line(text: str) -> bool:
    return bool(re.fullmatch(r"[-—–]?\s*\d+\s*[-—–]?", text.strip()))


def _find_text_margin_overflows(
    page,
    page_number: int,
    edge_margin: float = TEXT_EDGE_MARGIN_PT,
) -> list[dict]:
    """Find text lines that touch or exceed the physical page edge."""
    width = float(page.rect.width)
    left_limit = edge_margin
    right_limit = width - edge_margin
    offenders: list[dict] = []
    for line in _iter_text_lines(page):
        x0, y0, x1, y1 = [float(value) for value in line["bbox"]]
        if x0 >= left_limit and x1 <= right_limit:
            continue
        offenders.append(
            {
                "page": page_number,
                "bbox": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
                "text": line["text"][:160],
            }
        )
    return offenders


def _find_content_margin_issues(
    page,
    page_number: int,
    min_margin: float = CUMCM_MIN_CONTENT_MARGIN_PT,
    tolerance: float = CUMCM_CONTENT_MARGIN_TOLERANCE_PT,
) -> list[dict]:
    """Find body text outside the CUMCM 2.5cm minimum content margin."""
    width = float(page.rect.width)
    height = float(page.rect.height)
    left_limit = min_margin - tolerance
    right_limit = width - min_margin + tolerance
    top_limit = min_margin - tolerance
    bottom_limit = height - min_margin + tolerance
    issues: list[dict] = []

    for line in _iter_text_lines(page):
        text = line["text"]
        if _is_page_number_line(text):
            continue
        x0, y0, x1, y1 = [float(value) for value in line["bbox"]]
        sides = []
        if x0 < left_limit:
            sides.append("left")
        if x1 > right_limit:
            sides.append("right")
        if y0 < top_limit:
            sides.append("top")
        if y1 > bottom_limit:
            sides.append("bottom")
        if not sides:
            continue
        issues.append(
            {
                "page": page_number,
                "sides": sides,
                "bbox": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
                "text": text[:160],
            }
        )
    return issues


def _check_first_page_is_abstract(page_texts: list[str]) -> dict:
    first_page_text = page_texts[0] if page_texts else ""
    forbidden_terms = [term for term in BODY_START_TERMS if term in first_page_text]
    has_keywords = "关键词" in first_page_text or "关键字" in first_page_text
    return {
        "passed": bool(page_texts)
        and "摘要" in first_page_text
        and has_keywords
        and "目录" not in first_page_text
        and not forbidden_terms,
        "has_abstract": "摘要" in first_page_text,
        "has_keywords": has_keywords,
        "forbidden_terms": forbidden_terms,
    }


def _check_no_table_of_contents(page_texts: list[str]) -> dict:
    toc_pages = [
        index + 1
        for index, text in enumerate(page_texts[:3])
        if re.search(r"(?m)^\s*目录\s*$", text)
    ]
    return {"passed": not toc_pages, "toc_pages": toc_pages}


def _check_forbidden_submission_terms(page_texts: list[str]) -> dict:
    occurrences: list[dict] = []
    for index, text in enumerate(page_texts, 1):
        terms = [term for term in FORBIDDEN_SUBMISSION_TERMS if term in text]
        terms.extend(
            term
            for term in re.findall(r"(?<![A-Za-z0-9_])(?:姓名|学号)\s*[:：]", text)
        )
        if terms:
            occurrences.append({"page": index, "terms": sorted(set(terms))})
    return {"passed": not occurrences, "occurrences": occurrences}


def _check_body_page_limit(page_texts: list[str]) -> dict:
    appendix_start_page = None
    for index, text in enumerate(page_texts, 1):
        if "附录" in text:
            appendix_start_page = index
            break
    body_end_page = appendix_start_page - 1 if appendix_start_page else len(page_texts)
    body_pages_after_abstract = max(0, body_end_page - 1)
    return {
        "passed": body_pages_after_abstract <= MAX_CUMCM_BODY_PAGES,
        "body_pages_after_abstract": body_pages_after_abstract,
        "max_body_pages": MAX_CUMCM_BODY_PAGES,
        "appendix_start_page": appendix_start_page,
    }


def _check_markdown_table_leakage(page_texts: list[str]) -> dict:
    """Detect pipe-table source that leaked into rendered body pages."""
    issues: list[dict] = []
    for index, text in enumerate(page_texts):
        # Code appendices may legitimately contain Markdown strings. Stop at
        # the source-code appendix and keep the rule focused on paper prose.
        if "附录B 源程序代码" in text:
            break
        compact = re.sub(r"\s+", " ", text)
        for match in re.finditer(r"表\s*\d+[^\n]{0,1200}", compact):
            sample = match.group(0)
            if sample.count("|") < 6:
                continue
            if not re.search(r"(?:-{3,}|—{2,}|–{2,})", sample):
                continue
            issues.append({"page": index + 1, "text": sample[:300]})
            break
    return {"passed": not issues, "issues": issues}


def check_pdf_visual(pdf_path: str, work_dir: str, max_pages: int | None = None) -> dict:
    """检查 PDF 是否基本可交付，并写入 pdf_visual_check.json。

    该检查逐页验证非空、A4 尺寸和文本边界，并检测正文中的 Markdown
    表格源码泄漏。调用方仍决定失败是否阻断主导出流程。
    由调用方决定是否只报警。
    """
    report = {
        "enabled": False,
        "success": False,
        "status": "SKIPPED",
        "generated_at": datetime.datetime.now().isoformat(),
        "pdf_path": os.path.basename(pdf_path),
        "pdf_sha256": None,
        "scan_scope": "none",
        "page_count": 0,
        "pages_checked": 0,
        "reason": "",
        "checks": {},
    }

    if not os.path.exists(pdf_path):
        report["reason"] = f"PDF 文件不存在: {pdf_path}"
        _write_report(work_dir, report)
        return report

    try:
        import fitz  # PyMuPDF
    except ImportError:
        report["reason"] = "未安装 PyMuPDF，跳过 PDF 后验视觉检查"
        _write_report(work_dir, report)
        return report

    report["enabled"] = True
    report["pdf_sha256"] = _file_sha256(pdf_path)
    file_size_bytes = os.path.getsize(pdf_path)
    try:
        with fitz.open(pdf_path) as doc:
            page_count = int(doc.page_count)
            pages_checked = (
                page_count
                if max_pages is None or max_pages <= 0
                else min(max_pages, page_count)
            )
            page_sizes: list[dict] = []
            nonblank_pages: list[int] = []
            extracted_text_chars = 0
            text_margin_overflows: list[dict] = []
            content_margin_issues: list[dict] = []
            page_texts: list[str] = []

            for index in range(pages_checked):
                page = doc[index]
                if _page_has_nonblank_pixels(page):
                    nonblank_pages.append(index + 1)
                extracted_text_chars += len((page.get_text() or "").strip())

            for index in range(page_count):
                page = doc[index]
                width = float(page.rect.width)
                height = float(page.rect.height)
                page_sizes.append(
                    {
                        "page": index + 1,
                        "width": width,
                        "height": height,
                        "a4": _is_a4_size(width, height),
                    }
                )
                page_texts.append(page.get_text() or "")
                if len(text_margin_overflows) < MAX_TEXT_MARGIN_OVERFLOWS:
                    page_overflows = _find_text_margin_overflows(page, index + 1)
                    remaining = MAX_TEXT_MARGIN_OVERFLOWS - len(text_margin_overflows)
                    text_margin_overflows.extend(page_overflows[:remaining])
                if len(content_margin_issues) < MAX_CONTENT_MARGIN_ISSUES:
                    page_margin_issues = _find_content_margin_issues(page, index + 1)
                    remaining = MAX_CONTENT_MARGIN_ISSUES - len(content_margin_issues)
                    content_margin_issues.extend(page_margin_issues[:remaining])
    except Exception as exc:
        report["reason"] = f"PDF 后验视觉检查异常: {exc}"
        report["status"] = "FAIL"
        _write_report(work_dir, report)
        return report

    checks = {
        "file_size": {
            "passed": file_size_bytes <= MAX_CUMCM_PDF_SIZE_BYTES,
            "bytes": file_size_bytes,
            "max_bytes": MAX_CUMCM_PDF_SIZE_BYTES,
        },
        "page_count": {"passed": page_count > 0},
        "body_page_limit": _check_body_page_limit(page_texts),
        "a4_size": {
            "passed": bool(page_sizes) and all(item["a4"] for item in page_sizes),
            "pages": page_sizes,
        },
        "abstract_first_page": _check_first_page_is_abstract(page_texts),
        "no_table_of_contents": _check_no_table_of_contents(page_texts),
        "submission_anonymity": _check_forbidden_submission_terms(page_texts),
        "markdown_table_leakage": _check_markdown_table_leakage(page_texts),
        "nonblank_pages": {
            "passed": pages_checked > 0 and len(nonblank_pages) == pages_checked,
            "pages": nonblank_pages,
        },
        "text_extractable": {"passed": extracted_text_chars > 0},
        "text_margin": {
            "passed": not text_margin_overflows,
            "edge_margin_pt": TEXT_EDGE_MARGIN_PT,
            "overflows": text_margin_overflows,
        },
        "content_margin": {
            "passed": not content_margin_issues,
            "min_margin_pt": round(CUMCM_MIN_CONTENT_MARGIN_PT, 2),
            "tolerance_pt": CUMCM_CONTENT_MARGIN_TOLERANCE_PT,
            "issues": content_margin_issues,
        },
    }
    report.update(
        {
            "page_count": page_count,
            "pages_checked": pages_checked,
            "scan_scope": (
                "all_pages" if pages_checked == page_count else "partial_pages"
            ),
            "checks": checks,
            "success": all(check["passed"] for check in checks.values()),
        }
    )
    report["status"] = "PASS" if report["success"] else "FAIL"
    _write_report(work_dir, report)
    return report
