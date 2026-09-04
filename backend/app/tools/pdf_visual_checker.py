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
MAX_CUMCM_BODY_PAGES = 20
# 华数杯部署放宽（仅 huashubei profile 生效；cumcm2025/2026 与 default 维持原基线）：
HUASHUBEI_MIN_CONTENT_MARGIN_PT = 0.6 / 2.54 * 72  # 页边距允许至 0.6cm（公式略超右边距放行）
HUASHUBEI_MAX_BODY_PAGES = 30  # 原则上正文<=20页；华数杯部署严格按新规正文<=30页（摘要不计入）。
HUASHUBEI_RIGHT_MARGIN_SLACK_PT = 20.0  # 允许公式/图略超右边距至页面边缘的额外余量
HUASHUBEI_KEYWORDS_ANY_PAGE = True  # 关键词允许出现在摘要页之后的页面，不强制首页
MAX_ABSTRACT_PAGES = 1  # 新规：摘要强制控制在首页单页内。
MAX_CONTENT_MARGIN_ISSUES = 20
DEFAULT_EDITORIAL_QUALITY_POLICY = "internal_editorial_warn"
CUMCM2026_STRICT_EDITORIAL_QUALITY_POLICY = "cumcm2026_strict"
EDITORIAL_QUALITY_POLICY_SCOPE = "internal_editorial_non_official"
MIN_ABSTRACT_CHARACTERS = 450
MIN_ABSTRACT_TEXT_COVERAGE_RATIO = 0.12
MIN_EDITORIAL_BODY_PAGES = 10
MAX_EDITORIAL_BODY_PAGES = 20
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

EDITORIAL_QUALITY_POLICIES = {
    DEFAULT_EDITORIAL_QUALITY_POLICY: {
        "blocking": False,
        "description": "仅记录内部编辑质量风险，不阻断历史或轻量任务导出。",
    },
    CUMCM2026_STRICT_EDITORIAL_QUALITY_POLICY: {
        "blocking": True,
        "description": "将内部编辑质量风险作为正式 CUMCM 候选的阻断条件。",
    },
}


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
    right_slack_pt: float = 0.0,
) -> list[dict]:
    """Find body text outside the CUMCM 2.5cm minimum content margin."""
    width = float(page.rect.width)
    height = float(page.rect.height)
    left_limit = min_margin - tolerance
    right_limit = width - min_margin + tolerance + right_slack_pt
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


def _check_first_page_is_abstract(
    page_texts: list[str], *, keywords_anywhere: bool = False
) -> dict:
    first_page_text = page_texts[0] if page_texts else ""
    keyword_match = re.search(r"(?:关键词|关键字)\s*[:：]?", first_page_text)
    after_keywords = first_page_text[keyword_match.end() :] if keyword_match else ""
    body_heading_pattern = re.compile(
        r"(?:[一二三四五六七八九十]、|[1-5]\.(?:[1-9]\.)?)\s*(?:问题重述|问题分析|模型假设|符号说明|模型建立|模型的建立)"
    )
    forbidden_terms: list[str] = [
        m.group(0).strip() for m in body_heading_pattern.finditer(first_page_text)
    ]
    if after_keywords:
        for term in BODY_START_TERMS:
            if term in after_keywords and term not in forbidden_terms:
                forbidden_terms.append(term)
    elif not keyword_match:
        for term in BODY_START_TERMS:
            if term in first_page_text and term not in forbidden_terms:
                forbidden_terms.append(term)

    has_keywords = bool(keyword_match)
    # 华数杯部署放宽：关键词允许出现在摘要页（含次页）；cumcm/default 仍要求首页含关键词
    if keywords_anywhere:
        has_keywords_ok = bool(
            re.search(r"(?:关键词|关键字)\s*[:：]?", "\n".join(page_texts))
        )
    else:
        has_keywords_ok = has_keywords
    abstract_offset = first_page_text.find("摘要")
    title_prefix = first_page_text[:abstract_offset].strip() if abstract_offset >= 0 else ""
    has_title = bool(title_prefix)
    return {
        "passed": bool(page_texts)
        and "摘要" in first_page_text
        and has_title
        and has_keywords_ok
        and "目录" not in first_page_text
        and not forbidden_terms,
        "has_abstract": "摘要" in first_page_text,
        "has_keywords": has_keywords,
        "has_title_before_abstract": has_title,
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


_MISSING_GLYPH_MARKERS = ("\ufffd", "\u25a1", "\x00", "\uffff", "\ufffe")


def _check_missing_glyphs(page_texts: list[str]) -> dict:
    """拦截 PDF 渲染后出现的缺字形/乱码占位字符。

    开界 ``$ `` 把后续中文吞进数学字体、或 listings 缺字形（如 λ/≤）时，
    PDF 文本层会留下 U+FFFD/U+25A1/NUL/U+FFFF 等占位；MuPDF 对无映射字形
    恰恰输出 U+FFFF，故它必须在扫描集内。Markdown 源级检查看不到渲染这一
    步，必须在文本层门禁。
    """
    offenders: list[dict] = []
    for index, text in enumerate(page_texts, 1):
        counts = {marker: text.count(marker) for marker in _MISSING_GLYPH_MARKERS}
        counts = {marker: n for marker, n in counts.items() if n}
        if not counts:
            continue
        offenders.append(
            {
                "page": index,
                "counts": {marker.encode("unicode_escape").decode(): n for marker, n in counts.items()},
                "samples": [_missing_glyph_sample(text, marker) for marker in counts],
            }
        )
    return {"passed": not offenders, "offenders": offenders}


def _missing_glyph_sample(text: str, marker: str) -> str:
    """取缺字形字符前后一小段文本作为证据，供人工快速定位。"""
    at = text.find(marker)
    if at < 0:
        return ""
    start = max(0, at - 40)
    end = min(len(text), at + len(marker) + 40)
    return text[start:end].replace("\n", " ")


def _check_body_page_limit(
    page_texts: list[str], *, max_body_pages: int = MAX_CUMCM_BODY_PAGES
) -> dict:
    appendix_start_page = None
    for index, text in enumerate(page_texts, 1):
        if "附录" in text:
            appendix_start_page = index
            break
    body_end_page = appendix_start_page - 1 if appendix_start_page else len(page_texts)
    body_pages_after_abstract = max(0, body_end_page - 1)
    return {
        "passed": body_pages_after_abstract <= max_body_pages,
        "body_pages_after_abstract": body_pages_after_abstract,
        "max_body_pages": max_body_pages,
        "appendix_start_page": appendix_start_page,
    }


def _extract_abstract_text(first_page_text: str) -> str:
    """Return text between the abstract label and the keyword label."""
    abstract_match = re.search(r"摘要\s*[:：]?", first_page_text)
    if not abstract_match:
        return ""
    keyword_match = re.search(
        r"(?:关键词|关键字)\s*[:：]?", first_page_text[abstract_match.end() :]
    )
    abstract_end = (
        abstract_match.end() + keyword_match.start()
        if keyword_match
        else len(first_page_text)
    )
    return re.sub(r"\s+", "", first_page_text[abstract_match.end() : abstract_end])


def _check_abstract_on_single_page(page_texts: list[str], max_abstract_pages: int = 1) -> dict:
    """Return passed=True iff the abstract label and keywords are both on page 1
    and no body-section heading appears on page 1, guaranteeing the abstract
    fits on one page per the new rule (正文≤30页, 摘要≤1页).
    """
    if not page_texts:
        return {"passed": False, "has_abstract_label": False, "keywords_on_first": False,
                "body_leak": True, "max_abstract_pages": max_abstract_pages}

    p1 = page_texts[0]
    has_abstract_label = bool(re.search(r"摘要\s*[:：]?", p1))
    has_keywords = bool(re.search(r"(?:关键词|关键字)\s*[:：]?", p1))

    keyword_match = re.search(r"(?:关键词|关键字)\s*[:：]?", p1)
    rest = p1[keyword_match.end():] if keyword_match else p1
    body_leak = bool(re.search(
        r"(?:[一二三四五六七八九十]、|[1-5]\.(?:[1-9]\.)?)\s*(?:问题重述|问题分析|模型假设|符号说明|模型建立|模型的建立)",
        rest,
    ))

    passed = has_abstract_label and has_keywords and not body_leak
    return {
        "passed": passed,
        "max_abstract_pages": max_abstract_pages,
        "has_abstract_label": has_abstract_label,
        "keywords_on_first": has_keywords,
        "body_leak_on_first_page": body_leak,
    }


def _text_coverage_ratio(page, lines: list[dict]) -> float | None:
    """Estimate text bounding-box coverage; ``None`` means geometry unavailable."""
    boxes: list[tuple[float, float, float, float]] = []
    for line in lines:
        if _is_page_number_line(line["text"]):
            continue
        try:
            x0, y0, x1, y1 = (float(value) for value in line["bbox"])
        except (TypeError, ValueError):
            continue
        if x1 > x0 and y1 > y0:
            boxes.append((x0, y0, x1, y1))
    if not boxes:
        return None

    page_area = float(page.rect.width) * float(page.rect.height)
    if page_area <= 0:
        return None
    min_x = min(box[0] for box in boxes)
    min_y = min(box[1] for box in boxes)
    max_x = max(box[2] for box in boxes)
    max_y = max(box[3] for box in boxes)
    return (max_x - min_x) * (max_y - min_y) / page_area


def _check_editorial_quality(
    page_texts: list[str],
    first_page_coverage_ratio: float | None,
    quality_policy: str,
    *,
    body_min_pages: int | None = None,
    body_max_pages: int | None = None,
) -> dict:
    """Check explicitly non-official content-density and body-length targets."""
    policy = EDITORIAL_QUALITY_POLICIES.get(quality_policy)
    if policy is None:
        return {
            "passed": False,
            "policy": quality_policy,
            "scope": EDITORIAL_QUALITY_POLICY_SCOPE,
            "official_rule": False,
            "blocking": True,
            "error": f"未知 PDF 内容质量策略: {quality_policy}",
            "warnings": [],
            "checkpoints": {},
        }

    abstract_text = _extract_abstract_text(page_texts[0] if page_texts else "")
    abstract_characters = len(abstract_text)
    coverage_ratio = first_page_coverage_ratio
    abstract_density_passed = abstract_characters >= MIN_ABSTRACT_CHARACTERS
    if coverage_ratio is not None:
        abstract_density_passed = (
            abstract_density_passed
            and coverage_ratio >= MIN_ABSTRACT_TEXT_COVERAGE_RATIO
        )

    minimum_pages = MIN_EDITORIAL_BODY_PAGES if body_min_pages is None else body_min_pages
    maximum_pages = MAX_EDITORIAL_BODY_PAGES if body_max_pages is None else body_max_pages
    body_page_limit = _check_body_page_limit(page_texts, max_body_pages=maximum_pages)
    body_pages = body_page_limit["body_pages_after_abstract"]
    body_range_passed = minimum_pages <= body_pages <= maximum_pages
    abstract_single_page = _check_abstract_on_single_page(page_texts, max_abstract_pages=MAX_ABSTRACT_PAGES)
    abstract_single_page_checkpoint = {
        "passed": abstract_single_page["passed"],
        "max_abstract_pages": abstract_single_page["max_abstract_pages"],
        "has_abstract_label": abstract_single_page["has_abstract_label"],
        "keywords_on_first": abstract_single_page["keywords_on_first"],
        "body_leak_on_first_page": abstract_single_page["body_leak_on_first_page"],
    }
    abstract_checkpoint = {
        "passed": abstract_density_passed,
        "abstract_characters": abstract_characters,
        "min_abstract_characters": MIN_ABSTRACT_CHARACTERS,
        "text_coverage_ratio": (
            round(coverage_ratio, 4) if coverage_ratio is not None else None
        ),
        "min_text_coverage_ratio": MIN_ABSTRACT_TEXT_COVERAGE_RATIO,
        "geometry_assessed": coverage_ratio is not None,
    }
    body_checkpoint = {
        "passed": body_range_passed,
        "body_pages_after_abstract": body_pages,
        "recommended_range_pages": [minimum_pages, maximum_pages],
        "appendix_start_page": body_page_limit["appendix_start_page"],
    }
    warnings = []
    if not abstract_density_passed:
        warnings.append("摘要页内容密度偏低或存在较大空白风险。")
    if not body_range_passed:
        warnings.append("正文页数未落在内部编辑建议范围内。")
    if not abstract_single_page_checkpoint["passed"]:
        warnings.append(f"摘要未控制在首页单页内（新规：摘要≤{MAX_ABSTRACT_PAGES}页）。")
    raw_passed = not warnings
    return {
        "passed": raw_passed or not policy["blocking"],
        "policy": quality_policy,
        "scope": EDITORIAL_QUALITY_POLICY_SCOPE,
        "official_rule": False,
        "blocking": policy["blocking"],
        "description": policy["description"],
        "warnings": warnings,
        "checkpoints": {
            "abstract_page_density": abstract_checkpoint,
            "body_page_range": body_checkpoint,
            "abstract_on_single_page": abstract_single_page_checkpoint,
        },
    }


def _check_markdown_table_leakage(page_texts: list[str]) -> dict:
    """Detect pipe-table source that leaked into rendered body pages."""
    issues: list[dict] = []
    for index, text in enumerate(page_texts):
        # Code appendices may legitimately contain Markdown strings. Stop at
        # the source-code appendix and keep the rule focused on paper prose.
        if re.search(r"附录\s*[A-Z]\s*源程序代码", text):
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


def _check_literal_markdown_headings(page_texts: list[str]) -> dict:
    """Reject Markdown heading source visibly leaked into rendered prose.

    The source-code appendix is intentionally excluded: it may legitimately
    contain Markdown examples.  In the paper body a literal ``### 标题`` is a
    formatting failure even when the PDF remains technically readable.
    """
    issues: list[dict] = []
    for index, text in enumerate(page_texts, 1):
        if re.search(r"附录\s*[A-Z]\s*源程序代码", text):
            break
        for match in re.finditer(r"(?m)^\s*#{1,6}\s+\S[^\n]{0,160}", text):
            issues.append({"page": index, "text": match.group(0).strip()})
    return {"passed": not issues, "issues": issues}


def check_pdf_visual(
    pdf_path: str,
    work_dir: str,
    max_pages: int | None = None,
    quality_policy: str = DEFAULT_EDITORIAL_QUALITY_POLICY,
    body_min_pages: int | None = None,
    body_max_pages: int | None = None,
    min_content_margin_cm: float | None = None,
    export_profile: str | None = None,
    template_override_audit: dict | None = None,
) -> dict:
    """检查 PDF 是否基本可交付，并写入 pdf_visual_check.json。

    该检查逐页验证非空、A4 尺寸和文本边界，并检测正文中的 Markdown
    表格源码泄漏。``quality_policy`` 还可启用内部编辑质量检查：默认
    ``internal_editorial_warn`` 只写警告，``cumcm2026_strict`` 会阻断低密度
    摘要页或正文页数不在建议范围内的候选。任务级模板覆盖可安全调整正文
    页数和内容边距阈值；该策略本身不是官方竞赛规则。
    """
    if body_min_pages is not None and (
        isinstance(body_min_pages, bool)
        or not isinstance(body_min_pages, int)
        or body_min_pages < 0
    ):
        raise ValueError("body_min_pages 必须为非负整数")
    if body_max_pages is not None and (
        isinstance(body_max_pages, bool)
        or not isinstance(body_max_pages, int)
        or body_max_pages <= 0
    ):
        raise ValueError("body_max_pages 必须为正整数")
    if body_min_pages is not None and body_max_pages is not None and body_min_pages > body_max_pages:
        raise ValueError("body_min_pages 不能大于 body_max_pages")
    if min_content_margin_cm is not None:
        if isinstance(min_content_margin_cm, bool) or not isinstance(
            min_content_margin_cm, (int, float)
        ) or not 1.0 <= float(min_content_margin_cm) <= 5.0:
            raise ValueError("min_content_margin_cm 必须在 1.0 至 5.0 之间")
    if body_max_pages is None:
        effective_body_max = (
            HUASHUBEI_MAX_BODY_PAGES
            if export_profile == "huashubei"
            else MAX_CUMCM_BODY_PAGES
        )
    else:
        effective_body_max = body_max_pages
    if min_content_margin_cm is None:
        if export_profile == "huashubei":
            # 华数杯部署放宽：正文页边距允许至 0.6cm（公式略超右边距放行）
            effective_margin = HUASHUBEI_MIN_CONTENT_MARGIN_PT
        elif export_profile in ("cumcm2025", "cumcm2026"):
            effective_margin = CUMCM_MIN_CONTENT_MARGIN_PT
        else:
            effective_margin = 2.0 / 2.54 * 72
    else:
        effective_margin = float(min_content_margin_cm) / 2.54 * 72
    report = {
        "enabled": False,
        "success": False,
        "status": "SKIPPED",
        "generated_at": datetime.datetime.now().isoformat(),
        "pdf_path": os.path.basename(pdf_path),
        "pdf_sha256": None,
        "export_profile": export_profile,
        "template_override": dict(template_override_audit or {"active": False}),
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
            first_page_coverage_ratio: float | None = None

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
                if index == 0:
                    first_page_coverage_ratio = _text_coverage_ratio(
                        page, _iter_text_lines(page)
                    )
                if len(text_margin_overflows) < MAX_TEXT_MARGIN_OVERFLOWS:
                    page_overflows = _find_text_margin_overflows(page, index + 1)
                    remaining = MAX_TEXT_MARGIN_OVERFLOWS - len(text_margin_overflows)
                    text_margin_overflows.extend(page_overflows[:remaining])
                if len(content_margin_issues) < MAX_CONTENT_MARGIN_ISSUES:
                    page_margin_issues = _find_content_margin_issues(
                        page,
                        index + 1,
                        min_margin=effective_margin,
                        right_slack_pt=(
                            HUASHUBEI_RIGHT_MARGIN_SLACK_PT
                            if export_profile == "huashubei"
                            else 0.0
                        ),
                    )
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
        "body_page_limit": _check_body_page_limit(
            page_texts, max_body_pages=effective_body_max
        ),
        "abstract_on_single_page": _check_abstract_on_single_page(
            page_texts, max_abstract_pages=MAX_ABSTRACT_PAGES,
        ),
        "editorial_quality": _check_editorial_quality(
            page_texts,
            first_page_coverage_ratio,
            quality_policy,
            body_min_pages=body_min_pages,
            body_max_pages=body_max_pages,
        ),
        "a4_size": {
            "passed": bool(page_sizes) and all(item["a4"] for item in page_sizes),
            "pages": page_sizes,
        },
        "abstract_first_page": _check_first_page_is_abstract(
            page_texts,
            keywords_anywhere=(
                HUASHUBEI_KEYWORDS_ANY_PAGE and export_profile == "huashubei"
            ),
        ),
        "no_table_of_contents": _check_no_table_of_contents(page_texts),
        "submission_anonymity": _check_forbidden_submission_terms(page_texts),
        "markdown_table_leakage": _check_markdown_table_leakage(page_texts),
        "literal_markdown_headings": _check_literal_markdown_headings(page_texts),
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
            "min_margin_pt": round(effective_margin, 2),
            "tolerance_pt": CUMCM_CONTENT_MARGIN_TOLERANCE_PT,
            "issues": content_margin_issues,
        },
        "missing_glyphs": _check_missing_glyphs(page_texts),
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
