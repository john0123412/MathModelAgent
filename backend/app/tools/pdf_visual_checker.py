"""PDF 后验视觉检查。"""

from __future__ import annotations

import datetime
import json
import os

from app.utils.log_util import logger


REPORT_FILENAME = "pdf_visual_check.json"
A4_WIDTH_PT = 595.28
A4_HEIGHT_PT = 841.89
A4_TOLERANCE_PT = 12
TEXT_EDGE_MARGIN_PT = 6
MAX_TEXT_MARGIN_OVERFLOWS = 20


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


def _find_text_margin_overflows(
    page,
    page_number: int,
    edge_margin: float = TEXT_EDGE_MARGIN_PT,
) -> list[dict]:
    """Find text lines that touch or exceed the physical page edge."""
    try:
        page_text = page.get_text("dict")
    except Exception:
        return []

    width = float(page.rect.width)
    left_limit = edge_margin
    right_limit = width - edge_margin
    offenders: list[dict] = []
    for block in page_text.get("blocks", []):
        for line in block.get("lines", []):
            x0, y0, x1, y1 = [float(value) for value in line.get("bbox", (0, 0, 0, 0))]
            if x0 >= left_limit and x1 <= right_limit:
                continue
            text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            if not text:
                continue
            offenders.append(
                {
                    "page": page_number,
                    "bbox": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
                    "text": text[:160],
                }
            )
    return offenders


def check_pdf_visual(pdf_path: str, work_dir: str, max_pages: int = 3) -> dict:
    """检查 PDF 是否基本可交付，并写入 pdf_visual_check.json。

    该检查只做低成本后验：页数、A4 尺寸、前几页非空、文本可提取，
    并扫描全文文本行是否贴近或越过页面物理边界。失败不会阻断主导出流程，
    由调用方决定是否只报警。
    """
    report = {
        "enabled": False,
        "success": False,
        "status": "SKIPPED",
        "generated_at": datetime.datetime.now().isoformat(),
        "pdf_path": os.path.basename(pdf_path),
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
    try:
        with fitz.open(pdf_path) as doc:
            page_count = int(doc.page_count)
            pages_checked = min(max_pages, page_count)
            page_sizes: list[dict] = []
            nonblank_pages: list[int] = []
            extracted_text_chars = 0
            text_margin_overflows: list[dict] = []

            for index in range(pages_checked):
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
                if _page_has_nonblank_pixels(page):
                    nonblank_pages.append(index + 1)
                extracted_text_chars += len((page.get_text() or "").strip())

            for index in range(page_count):
                if len(text_margin_overflows) >= MAX_TEXT_MARGIN_OVERFLOWS:
                    break
                page = doc[index]
                page_overflows = _find_text_margin_overflows(page, index + 1)
                remaining = MAX_TEXT_MARGIN_OVERFLOWS - len(text_margin_overflows)
                text_margin_overflows.extend(page_overflows[:remaining])
    except Exception as exc:
        report["reason"] = f"PDF 后验视觉检查异常: {exc}"
        report["status"] = "FAIL"
        _write_report(work_dir, report)
        return report

    checks = {
        "page_count": {"passed": page_count > 0},
        "a4_size": {
            "passed": bool(page_sizes) and all(item["a4"] for item in page_sizes),
            "pages": page_sizes,
        },
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
    }
    report.update(
        {
            "page_count": page_count,
            "pages_checked": pages_checked,
            "checks": checks,
            "success": all(check["passed"] for check in checks.values()),
        }
    )
    report["status"] = "PASS" if report["success"] else "FAIL"
    _write_report(work_dir, report)
    return report
