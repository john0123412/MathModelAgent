"""Submission audit report for generated modeling artifacts."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Any

from app.utils.log_util import logger
from app.tools.candidate_exporter import SUPPORT_ARCHIVE, SUPPORT_MANIFEST
from app.tools.export_template_override import (
    MANIFEST_FILENAME as TEMPLATE_OVERRIDE_MANIFEST,
    TemplateOverrideError,
    load_export_template_override,
    template_override_audit_matches,
)
from app.tools.paper_postprocessor import scan_similarity_ai_risk
from app.tools.result_integrity import _safe_path

REPORT_JSON = "submission_audit_report.json"
REPORT_MD = "submission_audit_report.md"

_REQUIRED_FILES = ["res.md", "res.json", "res.docx", "res.pdf"]
_REPORT_FILES = [
    "execution_validation_report.json",
    "paper_preflight_report.json",
    "pdf_visual_check.json",
    "export_status.json",
]
_SUBMISSION_NAME_RE = re.compile(r"^[^/\\]+\.(?:pdf|docx)$", re.IGNORECASE)
_DOCX_CODE_APPENDIX_RE = re.compile(r"附录\s*[A-Z]\s*源程序代码", re.IGNORECASE)

HIGH_CONF_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
HIGH_CONF_PHONE_RE = re.compile(
    r"(?<!\d)(?:1[3-9]\d{9}|\+?86[- ]?1[3-9]\d{9})(?!\d)|(?:电话|手机|Tel|Mobile|Contact)[:：\s]*\+?\d[\d\s-]{6,}"
)
HIGH_CONF_ID_RE = re.compile(
    r"(?<![a-zA-Z0-9])(?:学号|身份证(?:号)?|报名号|参赛编号|队号|参赛队号|准考证号|Student\s*ID)[:：\s]*([0-9a-zA-Z]{4,})"
)
HIGH_CONF_IDENTITY_RE = re.compile(
    r"(?<![a-zA-Z0-9])(?:作者|参赛队员|队员姓名|指导教师|指导老师|导师|学校名称|所属学校|所在学校|院系|班级|Author|Advisor|Supervisor|Instructor)"
    r"((?:\s*[:：]\s*|[\s_—\-]+))"
    r"([^\s,;，；\n\"'<>#_]{2,30})"
)
HIGH_CONF_WECHAT_QQ_RE = re.compile(
    r"(?<![a-zA-Z0-9])(?:微信|WeChat|QQ)[:：\s]*([0-9a-zA-Z_-]{5,})"
)

LOW_CONFIDENCE_KEYWORDS = [
    "学校", "学院", "大学", "University", "College", "School",
    "致谢", "承诺书", "编号专用页",
]

PLACEHOLDER_WORDS = {
    "xxx", "xxxx", "0000", "none", "null", "tbd", "todo", "待补充", "占位符",
    "unknown", "author", "user", "admin", "n/a", "anonymous", "organization", "company",
}

_COMMON_VERB_PREFIXES = (
    "提出", "认为", "建议", "建立", "分析", "采用", "发现", "证明",
    "指出", "总结", "假设", "推导", "给出", "说明", "结合", "基于",
    "研究", "针对", "考虑", "通过", "对", "在", "将", "从", "由",
    "使用", "设计", "引入", "构建", "讨论", "计算",
)

CONTEST_PHRASES = [
    "全国大学生数学建模竞赛",
    "全国研究生数学建模竞赛",
    "中国大学生数学建模竞赛",
    "美国大学生数学建模竞赛",
    "华数杯全国大学生数学建模竞赛",
    "大学生数学建模",
    "数学建模竞赛",
]


def _mask_sensitive_text(category: str, raw: str) -> str:
    """对报告中回显的疑似敏感词执行不可逆脱敏掩码。"""
    raw = raw.strip()
    if not raw:
        return "***"
    if category == "email":
        parts = raw.split("@")
        if len(parts) == 2:
            name, domain = parts
            masked_name = name[:2] + "***" if len(name) > 2 else "***"
            return f"{masked_name}@{domain}"
        return "***@***.***"
    if category in ("phone", "telephone"):
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= 7:
            return f"{digits[:3]}****{digits[-4:]}"
        return "*******"
    if category in ("student_id", "id_card", "team_number", "registration_number", "student_id_or_number"):
        val = raw.split(":")[-1].split("：")[-1].strip()
        if len(val) >= 4:
            return f"{val[:2]}****{val[-2:]}"
        return "****"
    if category in ("author", "advisor", "school_name", "author_or_school", "wechat", "qq", "wechat_or_qq"):
        for sep in ("：", ":", "_", "—", "-"):
            if sep in raw:
                prefix, val = raw.split(sep, 1)
                val = val.strip()
                masked_val = val[0] + "*" * (len(val) - 1) if len(val) > 1 else "**"
                return f"{prefix}{sep}{masked_val}"
        val = raw.split(":")[-1].split("：")[-1].strip()
        if len(val) >= 2:
            return f"{val[0]}" + "*" * (len(val) - 1)
        return "**"
    return "***"


def _extract_docx_paragraphs(xml_bytes: bytes) -> list[str]:
    """从 DOCX XML 数据中提取并合并同一段落内被拆分的 <w:t> 文本运行。

    遇到 XML 语法损坏时直接抛出异常，由外层捕获记录 high_confidence 阻断项。
    """
    root = ET.fromstring(xml_bytes)
    paragraphs: list[str] = []
    for elem in root.iter():
        if elem.tag.endswith("}p"):
            runs = []
            for t in elem.iter():
                if t.tag.endswith("}t") and t.text:
                    runs.append(t.text)
            if runs:
                paragraphs.append("".join(runs))
    return paragraphs


def _normalize_mojibake_candidates(s: str) -> list[str]:
    """生成文本候选列表，包含原始字符串以及严格 latin-1 -> utf-8 恢复的候选（修复 PyMuPDF 对中文 ufilename 的误解码）。"""
    if not s:
        return []
    candidates = [s]
    try:
        # 仅当 latin-1 编码后可以严格按 utf-8 解码时增加修复候选
        repaired = s.encode("latin-1").decode("utf-8")
        if repaired and repaired != s:
            candidates.append(repaired)
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return list(dict.fromkeys(candidates))


def _audit_docx_metadata(archive: zipfile.ZipFile) -> list[dict[str, Any]]:
    """扫描 DOCX 元数据文件 (core.xml, app.xml, custom.xml) 中残留的作者与机构信息。"""
    findings: list[dict[str, Any]] = []
    # 1. 扫描 docProps/core.xml（仅检测作者与修改人身份字段，严禁将 title/subject 误判为作者）
    try:
        if "docProps/core.xml" in archive.namelist():
            core_xml = archive.read("docProps/core.xml")
            root = ET.fromstring(core_xml)
            for child in root.iter():
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag in ("creator", "lastModifiedBy"):
                    val = (child.text or "").strip()
                    val_lower = val.lower()
                    if (
                        val
                        and val_lower not in PLACEHOLDER_WORDS
                        and not any(t in val_lower for t in ("pandoc", "microsoft word", "latex", "tex", "wps", "libreoffice"))
                    ):
                        findings.append({
                            "category": "docx_metadata_author",
                            "part": f"docProps/core.xml:{tag}",
                            "masked": _mask_sensitive_text("author", val),
                            "high_confidence": True,
                        })
    except Exception as exc:
        findings.append({
            "category": "docx_metadata_error",
            "part": "docProps/core.xml",
            "masked": f"[core.xml解析失败: {type(exc).__name__}]",
            "high_confidence": True,
        })

    # 2. 扫描 docProps/app.xml
    try:
        if "docProps/app.xml" in archive.namelist():
            app_xml = archive.read("docProps/app.xml")
            root = ET.fromstring(app_xml)
            for child in root.iter():
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag in ("Company", "Manager"):
                    val = (child.text or "").strip()
                    val_lower = val.lower()
                    if (
                        val
                        and val_lower not in PLACEHOLDER_WORDS
                        and not any(t in val_lower for t in ("microsoft", "libreoffice", "wps"))
                    ):
                        findings.append({
                            "category": "docx_metadata_company",
                            "part": f"docProps/app.xml:{tag}",
                            "masked": _mask_sensitive_text("school_name", val),
                            "high_confidence": True,
                        })
    except Exception as exc:
        findings.append({
            "category": "docx_metadata_error",
            "part": "docProps/app.xml",
            "masked": f"[app.xml解析失败: {type(exc).__name__}]",
            "high_confidence": True,
        })

    # 3. 扫描 docProps/custom.xml
    try:
        if "docProps/custom.xml" in archive.namelist():
            custom_xml = archive.read("docProps/custom.xml")
            root = ET.fromstring(custom_xml)
            for prop in root.iter():
                name = prop.attrib.get("name", "")
                prop_val = ""
                for c in prop.iter():
                    if c.text and c.text.strip():
                        prop_val = c.text.strip()
                if prop_val:
                    val_lower = prop_val.lower()
                    if any(kw in name.lower() for kw in ("author", "creator", "owner", "user", "manager", "company", "school", "team", "member")):
                        if val_lower not in PLACEHOLDER_WORDS:
                            findings.append({
                                "category": "docx_metadata_custom",
                                "part": f"docProps/custom.xml:{name}",
                                "masked": _mask_sensitive_text("author", prop_val),
                                "high_confidence": True,
                            })
                    else:
                        _scan_text_for_anonymity(prop_val, f"docx:custom.xml:{name}", findings)
    except Exception as exc:
        findings.append({
            "category": "docx_metadata_error",
            "part": "docProps/custom.xml",
            "masked": f"[custom.xml解析失败: {type(exc).__name__}]",
            "high_confidence": True,
        })

    return findings


def _audit_pdf_metadata(pdf_path: str) -> list[dict[str, Any]]:
    """扫描 PDF 文档属性 metadata、注释与附件中残留的作者或团队信息。"""
    findings: list[dict[str, Any]] = []
    try:
        import fitz

        doc = fitz.open(pdf_path)
        meta = doc.metadata or {}
        # 仅扫描 author/creator（排除软件生成器，严禁将 title/subject 误判为作者）
        for k in ("author", "creator"):
            val = str(meta.get(k) or "").strip()
            if not val:
                continue
            val_lower = val.lower()
            if any(
                tool in val_lower
                for tool in (
                    "pandoc", "latex", "tex live", "xelatex", "pdftex", "microsoft",
                    "wps", "libreoffice", "acrobat", "matplotlib", "python", "reportlab",
                    "cairo", "ghostscript"
                )
            ):
                continue
            if val_lower in PLACEHOLDER_WORDS:
                continue
            findings.append({
                "category": "pdf_metadata_author",
                "part": f"pdf:metadata:{k}",
                "masked": _mask_sensitive_text("author", val),
                "high_confidence": True,
            })

        # 扫描 PDF 页面批注/注释
        for page_idx, page in enumerate(doc, start=1):
            for annot in page.annots():
                info = annot.info or {}
                for ak in ("title", "author", "content"):
                    aval = str(info.get(ak) or "").strip()
                    if aval:
                        for cand in _normalize_mojibake_candidates(aval):
                            _scan_text_for_anonymity(cand, f"pdf:page{page_idx}:annot:{ak}", findings)

        # 扫描 PDF 内嵌附件元数据 (key, filename, ufilename, desc)
        if hasattr(doc, "embfile_names"):
            try:
                emb_names = doc.embfile_names() or []
            except Exception as exc:
                findings.append({
                    "category": "pdf_attachment_error",
                    "part": "pdf:attachment",
                    "masked": f"[PDF附件清单读取失败: {type(exc).__name__}]",
                    "high_confidence": True,
                })
                emb_names = []

            for emb_idx, emb_key in enumerate(emb_names, start=1):
                # 1. 扫描附件键 (key)
                if emb_key:
                    for cand in _normalize_mojibake_candidates(str(emb_key)):
                        _scan_text_for_anonymity(cand, f"pdf:attachment:{emb_idx}:key", findings)

                # 2. 扫描附件详细信息 (filename, ufilename, desc/description)
                if hasattr(doc, "embfile_info"):
                    try:
                        info = doc.embfile_info(emb_key) or {}
                    except Exception as exc:
                        findings.append({
                            "category": "pdf_attachment_error",
                            "part": f"pdf:attachment:{emb_idx}",
                            "masked": f"[PDF附件信息读取失败: {type(exc).__name__}]",
                            "high_confidence": True,
                        })
                        info = {}

                    field_map = [
                        ("filename", "filename"),
                        ("ufilename", "ufilename"),
                        ("desc", "description"),
                        ("description", "description"),
                    ]
                    for info_key, part_suffix in field_map:
                        raw_val = info.get(info_key)
                        if raw_val:
                            val_str = str(raw_val).strip()
                            if val_str:
                                for cand in _normalize_mojibake_candidates(val_str):
                                    _scan_text_for_anonymity(cand, f"pdf:attachment:{emb_idx}:{part_suffix}", findings)

    except Exception as exc:
        findings.append({
            "category": "pdf_metadata_error",
            "part": "pdf:metadata",
            "masked": f"[PDF元数据读取异常: {type(exc).__name__}]",
            "high_confidence": True,
        })
    return findings


def _extract_pdf_text(pdf_path: str) -> str:
    chunks: list[str] = []
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        for page in doc:
            chunks.append(page.get_text() or "")
        text = "\n".join(chunks).strip()
        if text:
            return text
    except Exception:
        chunks.clear()

    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = __import__(module_name)
            reader = module.PdfReader(pdf_path)
            for page in reader.pages:
                chunks.append(page.extract_text() or "")
            text = "\n".join(chunks).strip()
            if text:
                return text
        except Exception:
            chunks.clear()

    try:
        with open(pdf_path, "rb") as f:
            data = f.read(2_000_000)
            return data.decode("utf-8", errors="ignore") + "\n" + data.decode("latin-1", errors="ignore")
    except OSError:
        return ""



def _read_json(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


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


def _issue(
    check_id: str,
    passed: bool,
    severity: str,
    message: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "passed": passed,
        "severity": severity,
        "message": message,
        "evidence": evidence or {},
    }


def _status_from_issues(issues: list[dict[str, Any]]) -> str:
    if any(not item["passed"] and item["severity"] == "error" for item in issues):
        return "FAIL"
    if any(not item["passed"] for item in issues):
        return "WARN"
    return "PASS"


def _audit_required_files(work_dir: str) -> list[dict[str, Any]]:
    missing = [
        filename
        for filename in _REQUIRED_FILES
        if not os.path.isfile(os.path.join(work_dir, filename))
    ]
    return [
        _issue(
            "required_files",
            not missing,
            "error",
            "主交付文件齐全。" if not missing else f"缺少主交付文件: {', '.join(missing)}",
            {"missing": missing},
        )
    ]


def _audit_reports(work_dir: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    missing_reports = [
        filename
        for filename in _REPORT_FILES
        if not os.path.isfile(os.path.join(work_dir, filename))
    ]
    issues.append(
        _issue(
            "required_reports",
            not missing_reports,
            "error",
            "自动审核报告齐全。"
            if not missing_reports
            else f"缺少自动审核报告: {', '.join(missing_reports)}",
            {"missing": missing_reports},
        )
    )

    execution = _read_json(os.path.join(work_dir, "execution_validation_report.json"))
    if execution is None:
        issues.append(
            _issue(
                "execution_validation",
                False,
                "error",
                "无法读取 execution_validation_report.json。",
            )
        )
    else:
        passed = execution.get("status") == "PASS"
        issues.append(
            _issue(
                "execution_validation",
                passed,
                "error",
                "代码执行、数值可行性和结果来源验证通过。"
                if passed
                else "代码执行、数值可行性或结果来源验证未通过。",
                {"status": execution.get("status")},
            )
        )

    preflight = _read_json(os.path.join(work_dir, "paper_preflight_report.json"))
    if preflight is None:
        issues.append(
            _issue(
                "paper_preflight",
                False,
                "error",
                "无法读取 paper_preflight_report.json。",
            )
        )
    else:
        preflight_status = preflight.get("status")
        current_md_hash = _file_sha256(os.path.join(work_dir, "res.md"))
        source_hash_matches = preflight.get("source_sha256") == current_md_hash
        conditional = preflight_status == "CONDITIONAL_PASS"
        passed = (
            preflight_status == "PASS" or preflight.get("success") is True
        ) and source_hash_matches and not conditional
        issues.append(
            _issue(
                "paper_preflight",
                passed,
                "warning" if conditional and source_hash_matches else "error" if not passed else "info",
                "paper_preflight_report.json = PASS，且绑定当前 res.md。"
                if preflight_status == "PASS" and source_hash_matches
                else "paper_preflight_report.json = CONDITIONAL_PASS，存在需人工复核的条件项。"
                if conditional and source_hash_matches
                else "paper_preflight_report.json 已过期或未绑定当前 res.md。"
                if not source_hash_matches
                else "paper_preflight_report.json 未通过。",
                {
                    "status": preflight_status,
                    "success": preflight.get("success"),
                    "source_sha256": preflight.get("source_sha256"),
                    "current_res_md_sha256": current_md_hash,
                },
            )
        )

    visual = _read_json(os.path.join(work_dir, "pdf_visual_check.json"))
    if visual is None:
        issues.append(
            _issue("pdf_visual_check", False, "error", "无法读取 pdf_visual_check.json。")
        )
    else:
        current_pdf_hash = _file_sha256(os.path.join(work_dir, "res.pdf"))
        pdf_hash_matches = visual.get("pdf_sha256") == current_pdf_hash
        full_scan = (
            visual.get("scan_scope") == "all_pages"
            and visual.get("pages_checked") == visual.get("page_count")
        )
        passed = (
            visual.get("status") == "PASS" or visual.get("success") is True
        ) and pdf_hash_matches and full_scan
        issues.append(
            _issue(
                "pdf_visual_check",
                passed,
                "error",
                "pdf_visual_check.json = PASS，且已覆盖当前 PDF 全部页面。"
                if passed
                else "pdf_visual_check.json 已过期、未绑定当前 PDF 或未覆盖全部页面。"
                if not pdf_hash_matches or not full_scan
                else "pdf_visual_check.json 未通过。",
                {
                    "status": visual.get("status"),
                    "success": visual.get("success"),
                    "pdf_sha256": visual.get("pdf_sha256"),
                    "current_res_pdf_sha256": current_pdf_hash,
                    "scan_scope": visual.get("scan_scope"),
                    "pages_checked": visual.get("pages_checked"),
                    "page_count": visual.get("page_count"),
                },
            )
        )
    return issues


def _audit_pdf_fonts(
    work_dir: str, require_official_fonts: bool
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    export_status = _read_json(os.path.join(work_dir, "export_status.json"))
    if export_status is None:
        return [
            _issue(
                "pdf_fonts",
                False,
                "error",
                "无法读取 export_status.json，不能审核 PDF 字体来源。",
            )
        ], {}

    pdf_status = export_status.get("pdf") if isinstance(export_status.get("pdf"), dict) else {}
    font_resolution = pdf_status.get("font_resolution")
    if not isinstance(font_resolution, list) or not font_resolution:
        return [
            _issue(
                "pdf_fonts",
                False,
                "warning",
                "export_status.json 未记录 font_resolution，无法确认 PDF 字体是否使用正式字体。",
            )
        ], {"font_resolution": []}

    fallback_items = [
        item
        for item in font_resolution
        if isinstance(item, dict)
        and item.get("preferred")
        and item.get("actual") != item.get("preferred")
    ]
    unknown_items = [
        item
        for item in font_resolution
        if isinstance(item, dict) and item.get("source") == "unknown"
    ]
    passed = not fallback_items and not unknown_items
    severity = "error" if require_official_fonts else "warning"

    if passed:
        message = "PDF 字体均使用 profile 指定的正式字体。"
    elif require_official_fonts:
        message = "正式提交门禁要求官方字体，但 PDF 存在 fallback 或未知字体来源。"
    else:
        message = "PDF 存在 Docker/自动化 fallback 字体，仅适合作为预览；正式提交前应改用官方字体重导。"

    evidence = {
        "require_official_fonts": require_official_fonts,
        "fallback_items": fallback_items,
        "unknown_items": unknown_items,
        "font_resolution": font_resolution,
        "remediation": [
            "Windows Docker: 在仓库根目录 .env 设置 MMA_OFFICIAL_FONTS_DIR=C:\\Windows\\Fonts 后重建/重启 backend。",
            "Windows 本机: cd backend; uv run python -m app.tools.export_cli pdf --input project\\work_dir\\<task_id>\\res.md --output project\\work_dir\\<task_id>\\res.pdf --profile cumcm2026 --local --update-status",
            "重导后再次运行 python -m app.tools.submission_audit --work-dir project\\work_dir\\<task_id> --require-official-fonts。",
        ],
    }
    return [_issue("pdf_fonts", passed, severity, message, evidence)], evidence


def _audit_candidate_manifest(work_dir: str) -> list[dict[str, Any]]:
    path = os.path.join(work_dir, "candidate_manifest.json")
    if not os.path.exists(path):
        return []
    manifest = _read_json(path)
    if manifest is None:
        return [_issue("candidate_manifest", False, "error", "无法读取 candidate_manifest.json。")]
    selected = manifest.get("submission_file")
    valid = isinstance(selected, str) and bool(_SUBMISSION_NAME_RE.fullmatch(selected))
    exists = valid and os.path.isfile(os.path.join(work_dir, selected))
    issues = [_issue(
        "submission_file",
        bool(valid and exists and not (
            isinstance(manifest.get("submission_files"), list)
            and manifest.get("submission_files") != [selected]
        )),
        "error",
        "candidate manifest 声明了唯一且存在的 submission_file。" if valid and exists
        else "candidate manifest 缺少合法 submission_file（应为工作目录内的 PDF/DOCX 文件）。",
        {"submission_file": selected, "exists": bool(exists)},
    )]
    if valid and exists and str(selected).lower().endswith(".docx"):
        issues.append(_audit_docx_identity(work_dir, selected))
    return issues


def _audit_docx_identity(work_dir: str, filename: str) -> dict[str, Any]:
    """Static DOCX text guard for identity/cover/TOC material.

    This is intentionally a narrow text check; it does not claim that a DOCX
    has passed full visual or contest-format review.
    """
    forbidden = re.compile(r"承诺书|编号专用页|参赛队号|队员姓名|指导教师|所在学校|学校名称|目录|TOC", re.IGNORECASE)
    found: list[str] = []
    try:
        with zipfile.ZipFile(os.path.join(work_dir, filename)) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
            found = sorted(set(forbidden.findall(xml)))
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        return _issue("docx_identity", False, "error", "无法读取 DOCX 文本以检查身份/封面字段。", {"error": type(exc).__name__})
    return _issue(
        "docx_identity",
        not found,
        "error",
        "DOCX 未发现受限身份/承诺书/目录文本。" if not found else "DOCX 包含可能违反匿名提交要求的身份、承诺书或目录文本。",
        {"matches": found},
    )


def _audit_docx_markdown_heading_leakage(work_dir: str, filename: str = "res.docx") -> dict[str, Any]:
    """Reject literal Markdown headings in the generated Word deliverable.

    This is intentionally a structural DOCX guard, not a claim of full Word
    visual approval.  It complements the PDF visual check so an ATX heading
    cannot be silently rendered as normal text in either primary deliverable.
    """
    paragraphs: list[str] = []
    try:
        with zipfile.ZipFile(os.path.join(work_dir, filename)) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        for paragraph in root.findall(".//w:p", namespace):
            text = "".join(
                node.text or "" for node in paragraph.findall(".//w:t", namespace)
            ).strip()
            if text:
                # A source-code appendix may legitimately contain literals
                # such as ``# Cell``.  The guard is intentionally confined to
                # rendered manuscript prose, consistent with PDF checking.
                if _DOCX_CODE_APPENDIX_RE.search(text):
                    break
                paragraphs.append(text)
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        return _issue(
            "docx_markdown_heading_leakage",
            False,
            "error",
            "无法读取 DOCX 段落以检查 Markdown 标题泄漏。",
            {"error": type(exc).__name__},
        )

    leaked = [
        text[:200]
        for text in paragraphs
        if re.match(r"^\s*#{1,6}\s+\S", text)
    ]
    return _issue(
        "docx_markdown_heading_leakage",
        not leaked,
        "error",
        "DOCX 未发现字面 Markdown 标题。" if not leaked else "DOCX 出现未渲染的 Markdown 标题。",
        {"paragraphs_checked": len(paragraphs), "issues": leaked},
    )


def _audit_template_override(work_dir: str) -> dict[str, Any]:
    """Cross-bind every formal export report to one checked template identity."""
    docx_status = _read_json(os.path.join(work_dir, "docx_export_status.json")) or {}
    export_status = _read_json(os.path.join(work_dir, "export_status.json")) or {}
    preflight = _read_json(os.path.join(work_dir, "paper_preflight_report.json")) or {}
    visual = _read_json(os.path.join(work_dir, "pdf_visual_check.json")) or {}
    candidate = _read_json(os.path.join(work_dir, "candidate_manifest.json"))
    profile = str(
        docx_status.get("export_profile") or export_status.get("export_profile") or ""
    )
    manifest_path = os.path.join(work_dir, TEMPLATE_OVERRIDE_MANIFEST)
    if not os.path.lexists(manifest_path):
        return _issue(
            "template_override_integrity",
            True,
            "info",
            "当前任务未安装用户提供的模板覆盖。",
            {"active": False, "export_profile": profile},
        )
    if not profile:
        return _issue(
            "template_override_integrity",
            False,
            "error",
            "任务级模板覆盖存在，但当前 DOCX/PDF 导出状态未声明 profile。",
            {"active": True, "export_profile": profile},
        )
    try:
        override = load_export_template_override(work_dir, profile)
    except (TemplateOverrideError, ValueError) as exc:
        return _issue(
            "template_override_integrity",
            False,
            "error",
            "任务级模板覆盖无效或哈希不匹配。",
            {"active": True, "error": str(exc)},
        )
    audit = override["audit"]
    if not override.get("active"):
        return _issue(
            "template_override_integrity",
            True,
            "info",
            "任务保存了其他 profile 的模板覆盖；当前导出 profile 未启用该覆盖。",
            {"active": False, "export_profile": profile, "installed_profiles_ignored": True},
        )

    records: dict[str, object] = {
        "docx_export_status": docx_status.get("template_override"),
        "export_status": export_status.get("template_override"),
        "pdf_export": (
            export_status.get("pdf", {}).get("template_override")
            if isinstance(export_status.get("pdf"), dict)
            else None
        ),
        "paper_preflight": preflight.get("template_override"),
        "pdf_visual_check": visual.get("template_override"),
    }
    if candidate is not None:
        records["candidate_manifest"] = candidate.get("template_override")
    mismatched_records = [
        name
        for name, record in records.items()
        if not template_override_audit_matches(audit, record)
    ]

    profile_records = {
        "docx_export_status": docx_status.get("export_profile"),
        "export_status": export_status.get("export_profile"),
        "paper_preflight": preflight.get("export_profile"),
        "pdf_visual_check": visual.get("export_profile"),
    }
    profile_mismatches = [
        name for name, value in profile_records.items() if value != audit["profile"]
    ]
    rendered_contract = docx_status.get("format_contract")
    expected_docx_contract = override.get("format_contract", {}).get("docx", {})
    contract_bound = bool(
        isinstance(rendered_contract, dict)
        and rendered_contract.get("template_override_format_contract_sha256")
        == audit["format_contract_sha256"]
        and rendered_contract.get("template_override_docx_contract_sha256")
        == audit["docx_contract_sha256"]
        and all(rendered_contract.get(name) == value for name, value in expected_docx_contract.items())
    )
    docx_output_matches = docx_status.get("output_sha256") == _file_sha256(
        os.path.join(work_dir, "res.docx")
    )
    bound = (
        not mismatched_records
        and not profile_mismatches
        and contract_bound
        and docx_output_matches
    )
    return _issue(
        "template_override_integrity",
        bound,
        "error",
        "用户提供的模板覆盖已与 Markdown、DOCX、PDF、视觉检查和候选清单交叉绑定。"
        if bound
        else "模板覆盖与至少一个当前交付物或审核报告不一致，请执行 task-refresh。",
        {
            "active": True,
            "bound": bound,
            "mismatched_records": mismatched_records,
            "profile_mismatches": profile_mismatches,
            "contract_bound": contract_bound,
            "docx_output_matches": docx_output_matches,
            **audit,
        },
    )


def _audit_docx_format_contract(work_dir: str, filename: str = "res.docx") -> dict[str, Any]:
    """Verify the rendered DOCX against its recorded task format contract."""
    status = _read_json(os.path.join(work_dir, "docx_export_status.json")) or {}
    profile = str(status.get("export_profile") or "")
    contract = status.get("format_contract")
    if not isinstance(contract, dict) or not contract.get("active"):
        return _issue(
            "docx_format_contract",
            True,
            "info",
            "当前 DOCX 未记录可机检的正文版式合同。",
            {"active": False, "export_profile": profile},
        )

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

    def qn(name: str) -> str:
        return f"{{{namespace['w']}}}{name}"

    expected_fonts = {
        "eastAsia": str(contract.get("body_font_east_asia", "")),
        "ascii": str(contract.get("body_font_ascii", "")),
        "hAnsi": str(contract.get("body_font_hansi", "")),
        "cs": str(contract.get("body_font_cs", "")),
    }
    expected_size = str(contract.get("body_font_size_half_points", ""))
    expected_line = str(contract.get("body_line_spacing_twips", ""))
    expected_rule = str(contract.get("body_line_rule", ""))
    expect_page_break = bool(contract.get("body_start_page_break"))
    mismatches: list[dict[str, str]] = []
    checked = 0
    body_start_page_break = False
    try:
        with zipfile.ZipFile(os.path.join(work_dir, filename)) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
        body = root.find("w:body", namespace)
        if body is None:
            raise ET.ParseError("missing body")
        code_appendix_started = False
        for paragraph in body.findall("w:p", namespace):
            text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace)).strip()
            if not text:
                continue
            if _DOCX_CODE_APPENDIX_RE.fullmatch(text):
                code_appendix_started = True
                continue
            properties = paragraph.find("w:pPr", namespace)
            style = ""
            if properties is not None:
                style_node = properties.find("w:pStyle", namespace)
                if style_node is not None:
                    style = style_node.get(qn("val"), "")
            if re.fullmatch(r"(?:一、)?问题重述", text):
                body_start_page_break = bool(
                    properties is not None and properties.find("w:pageBreakBefore", namespace) is not None
                )
            if code_appendix_started or style.lower().startswith("heading") or re.match(
                r"^(?:[一二三四五六七八九十]+、|\d+(?:\.\d+){0,3}\s|摘要$|关键词|参考文献$|附录)", text
            ):
                continue
            runs = [run for run in paragraph.findall("w:r", namespace) if run.findall(".//w:t", namespace)]
            if not runs:
                continue
            checked += 1
            spacing = properties.find("w:spacing", namespace) if properties is not None else None
            spacing_ok = bool(
                spacing is not None
                and spacing.get(qn("line")) == expected_line
                and spacing.get(qn("lineRule")) == expected_rule
            )
            font_ok = True
            for run in runs:
                run_properties = run.find("w:rPr", namespace)
                fonts = run_properties.find("w:rFonts", namespace) if run_properties is not None else None
                size = run_properties.find("w:sz", namespace) if run_properties is not None else None
                size_cs = run_properties.find("w:szCs", namespace) if run_properties is not None else None
                if (
                    fonts is None
                    or any(fonts.get(qn(name)) != value for name, value in expected_fonts.items())
                    or size is None
                    or size.get(qn("val")) != expected_size
                    or size_cs is None
                    or size_cs.get(qn("val")) != expected_size
                ):
                    font_ok = False
                    break
            if not spacing_ok or not font_ok:
                mismatches.append(
                    {
                        "text": text[:120],
                        "font_ok": str(font_ok),
                        "single_spacing_ok": str(spacing_ok),
                    }
                )
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        return _issue(
            "docx_format_contract",
            False,
            "error",
            "无法读取 DOCX 以核验宋体小四单倍行距与摘要后正文分页。",
            {"error": type(exc).__name__},
        )

    page_break_ok = body_start_page_break or not expect_page_break
    passed = bool(checked) and page_break_ok and not mismatches
    return _issue(
        "docx_format_contract",
        passed,
        "error",
        "DOCX 已核验为记录的正文版式，且满足摘要后正文分页设置。"
        if passed
        else "DOCX 未满足记录的字体、行距或摘要后正文分页合同。",
        {
            "active": True,
            "export_profile": profile,
            "format_contract": contract,
            "checked_body_paragraphs": checked,
            "body_start_page_break": body_start_page_break,
            "expected_page_break": expect_page_break,
            "mismatches": mismatches[:20],
        },
    )


def _audit_support_materials(work_dir: str) -> list[dict[str, Any]]:
    manifest_path = os.path.join(work_dir, SUPPORT_MANIFEST)
    archive_path = os.path.join(work_dir, SUPPORT_ARCHIVE)
    manifest = _read_json(manifest_path)
    if manifest is None and not os.path.exists(archive_path):
        return []
    if manifest is None or not os.path.isfile(archive_path):
        return [_issue("support_materials", False, "warning", "支撑材料 manifest 或 zip 缺失，无法核验。")]
    files = manifest.get("files", [])
    total = sum(int(item.get("size", 0)) for item in files if isinstance(item, dict))
    errors = []
    if total > 20 * 1024 * 1024:
        errors.append("超过 20MB 总大小限制")
    try:
        if os.path.getsize(archive_path) > 20 * 1024 * 1024:
            errors.append("support_materials.zip 超过 20MB 限制")
    except OSError:
        errors.append("无法读取 support_materials.zip 大小")
    if manifest.get("archive_error"):
        errors.append(str(manifest["archive_error"]))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            for item in files:
                if not isinstance(item, dict):
                    errors.append("manifest files 含非法条目")
                    continue
                name = item.get("path")
                if not isinstance(name, str) or name not in names:
                    errors.append(f"zip 缺少 {name}")
                    continue
                digest = hashlib.sha256(archive.read(name)).hexdigest()
                if digest != item.get("sha256"):
                    errors.append(f"SHA-256 不匹配: {name}")
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        errors.append(f"zip 无法读取: {type(exc).__name__}")
    return [_issue(
        "support_materials",
        not errors,
        "error" if errors else "warning",
        "支撑材料清单、压缩包内容和 SHA-256 已本地核对。" if not errors else "支撑材料清单/压缩包核验失败。",
        {"errors": errors, "file_count": len(files), "total_source_bytes": total},
    )]


def _audit_similarity_ai_risk(work_dir: str) -> dict[str, Any]:
    path = os.path.join(work_dir, "res.md")
    try:
        with open(path, encoding="utf-8") as handle:
            result = scan_similarity_ai_risk(handle.read(), work_dir)
    except OSError:
        result = {"status": "UNAVAILABLE", "risk_count": 0, "risks": [], "disclaimer": "本地扫描不可用，需人工复核。"}
    passed = result.get("risk_count", 0) == 0
    return _issue("similarity_ai_risk", passed, "warning", result.get("disclaimer", ""), result)


def _audit_cross_modal_integrity(work_dir: str) -> dict[str, Any]:
    """核验跨模态质检报告的有效性与时效性（拒绝缺失或哈希过期的 cross_modal 报告）。"""
    cross_modal_path = os.path.join(work_dir, "cross_modal_audit.json")

    if not os.path.isfile(cross_modal_path):
        return _issue(
            "cross_modal_integrity",
            False,
            "error",
            "未生成跨模态审计报告 (cross_modal_audit.json)，无法证明代码与正文跨模态对齐。",
        )

    try:
        with open(cross_modal_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        return _issue(
            "cross_modal_integrity",
            False,
            "error",
            f"无法解析跨模态审计报告: {exc}",
        )

    if not isinstance(data, dict):
        return _issue(
            "cross_modal_integrity",
            False,
            "error",
            "跨模态审计报告格式非法（不是 JSON 对象）。",
        )

    # 检查阻断状态
    if data.get("status") == "FAIL" or not data.get("passed", True):
        return _issue(
            "cross_modal_integrity",
            False,
            "error",
            "跨模态审计未通过（存在求解器私有依赖、最优性证书矛盾或 LaTeX 损坏等阻断项）。",
            data,
        )

    # 时效性校验：核对当前 res.md 哈希与代码源哈希
    md_path = os.path.join(work_dir, "res.md")
    if os.path.isfile(md_path):
        try:
            with open(md_path, "rb") as mf:
                curr_md_bytes = mf.read()
            curr_md_hash = hashlib.sha256(curr_md_bytes).hexdigest()
            curr_norm_hash = hashlib.sha256(curr_md_bytes.replace(b"\r\n", b"\n")).hexdigest()
        except OSError:
            curr_md_hash = ""
            curr_norm_hash = ""
        recorded_md_hash = data.get("markdown_sha256")
        if not recorded_md_hash:
            return _issue(
                "cross_modal_integrity",
                False,
                "error",
                "跨模态审计报告缺少 markdown_sha256 绑定指纹，视为无效/过期报告。",
                data,
            )
        if recorded_md_hash != curr_md_hash and recorded_md_hash != curr_norm_hash:
            return _issue(
                "cross_modal_integrity",
                False,
                "error",
                f"跨模态审计报告已过期（res.md SHA-256 不匹配：当前为 {curr_md_hash[:8]}...，报告为 {recorded_md_hash[:8]}...），必须重新运行跨模态审计！",
                data,
            )

    code_hashes = data.get("code_source_hashes")
    if code_hashes is not None and not isinstance(code_hashes, dict):
        return _issue(
            "cross_modal_integrity",
            False,
            "error",
            "跨模态审计报告中的 code_source_hashes 不是字典格式！",
            data,
        )

    if isinstance(code_hashes, dict):
        for src_rel, recorded_h in code_hashes.items():
            safe_src = _safe_path(work_dir, str(src_rel))
            if safe_src is None:
                return _issue(
                    "cross_modal_integrity",
                    False,
                    "error",
                    f"跨模态审计报告记录了越界或非法代码源路径: {src_rel}",
                    data,
                )
            if not os.path.isfile(safe_src):
                return _issue(
                    "cross_modal_integrity",
                    False,
                    "error",
                    f"跨模态审计报告中已登记的代码源文件缺失或已被删除: {src_rel}，报告已失效！",
                    data,
                )
            try:
                with open(safe_src, "rb") as sf:
                    curr_h = hashlib.sha256(sf.read()).hexdigest()
                if curr_h != recorded_h:
                    return _issue(
                        "cross_modal_integrity",
                        False,
                        "error",
                        f"跨模态审计报告已过期（代码源 {src_rel} 哈希已变更），必须重新运行跨模态审计！",
                        data,
                    )
            except OSError:
                return _issue(
                    "cross_modal_integrity",
                    False,
                    "error",
                    f"读取代码源文件失败: {src_rel}",
                    data,
                )

    # 从 frozen_results.json.executed_code_sources 反向核对
    frozen_path = os.path.join(work_dir, "frozen_results.json")
    if os.path.isfile(frozen_path):
        try:
            with open(frozen_path, encoding="utf-8") as f:
                frozen_doc = json.load(f)
        except Exception as exc:
            return _issue(
                "cross_modal_integrity",
                False,
                "error",
                f"frozen_results.json 解析失败: {type(exc).__name__}，无法通过跨模态审计！",
                data,
            )

        if isinstance(frozen_doc, dict):
            exec_srcs = frozen_doc.get("executed_code_sources")
            if exec_srcs is not None:
                if not isinstance(exec_srcs, list):
                    return _issue(
                        "cross_modal_integrity",
                        False,
                        "error",
                        "frozen_results.json 中的 executed_code_sources 不是列表格式！",
                        data,
                    )
                if exec_srcs:
                    if not isinstance(code_hashes, dict) or not code_hashes:
                        return _issue(
                            "cross_modal_integrity",
                            False,
                            "error",
                            "跨模态审计报告缺少 code_source_hashes 字段，无法证明已执行源码时效性！",
                            data,
                        )
                    for exec_src in exec_srcs:
                        if str(exec_src) not in code_hashes:
                            return _issue(
                                "cross_modal_integrity",
                                False,
                                "error",
                                f"跨模态审计报告遗漏了 frozen_results 中已声明的执行源码: {exec_src}，报告已失效！",
                                data,
                            )
                        safe_p = _safe_path(work_dir, str(exec_src))
                        if safe_p is None:
                            return _issue(
                                "cross_modal_integrity",
                                False,
                                "error",
                                f"frozen_results 中已声明的执行源码路径越界: {exec_src}，门禁阻断！",
                                data,
                            )
                        if not os.path.isfile(safe_p):
                            return _issue(
                                "cross_modal_integrity",
                                False,
                                "error",
                                f"frozen_results 中已声明的执行源码文件不存在或已被删除: {exec_src}，门禁阻断！",
                                data,
                            )

    return _issue(
        "cross_modal_integrity",
        True,
        "info",
        "跨模态对齐审计已通过（代码自包含、最优性证书一致性与版式完整性均正常且报告有效）。",
        data,
    )


def _scan_text_for_anonymity(
    text: str, source_label: str, findings: list[dict[str, Any]]
) -> None:
    """对单段文本执行分层匿名扫描（高置信阻断 vs 低置信预警）。"""
    if not text:
        return

    # 1. 高置信阻断扫描
    # 邮箱
    for m in HIGH_CONF_EMAIL_RE.finditer(text):
        raw = m.group(0)
        domain = raw.split("@")[-1].lower()
        if domain not in ("example.com", "xxx.com", "test.com"):
            findings.append({
                "category": "email",
                "part": source_label,
                "masked": _mask_sensitive_text("email", raw),
                "high_confidence": True,
            })

    # 手机 / 电话
    for m in HIGH_CONF_PHONE_RE.finditer(text):
        raw = m.group(0)
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= 8 and not re.match(r"^0+$|^1{7,}$", digits):
            findings.append({
                "category": "phone",
                "part": source_label,
                "masked": _mask_sensitive_text("phone", raw),
                "high_confidence": True,
            })

    # 学号 / 身份证 / 报名号 / 队号
    for m in HIGH_CONF_ID_RE.finditer(text):
        val = m.group(1).strip()
        if val.lower() not in PLACEHOLDER_WORDS and len(val) >= 4:
            findings.append({
                "category": "student_id_or_number",
                "part": source_label,
                "masked": _mask_sensitive_text("student_id", m.group(0)),
                "high_confidence": True,
            })

    # 作者 / 队员 / 导师 / 学校名称 + 真实值
    for m in HIGH_CONF_IDENTITY_RE.finditer(text):
        sep = m.group(1)
        val = m.group(2).strip()
        val_lower = val.lower()
        if not val or val_lower in PLACEHOLDER_WORDS:
            continue

        # 明确分隔符（冒号/破折号/下划线）属于直接元数据赋值，严禁使用谓词过滤（避免误伤计算机学院、研究院、设计班等）
        is_explicit_delimiter = any(d in sep for d in (":", "：", "_", "—", "-"))
        if not is_explicit_delimiter:
            # 仅在纯空白分隔时过滤自然语言谓词
            if any(val.startswith(verb) for verb in _COMMON_VERB_PREFIXES):
                continue
            if any(kw in val_lower for kw in ("model", "algorithm", "study", "analysis", "paper", "optimization", "method", "solution")):
                continue

        findings.append({
            "category": "author_or_school",
            "part": source_label,
            "masked": _mask_sensitive_text("author", m.group(0)),
            "high_confidence": True,
        })

    # 微信 / QQ
    for m in HIGH_CONF_WECHAT_QQ_RE.finditer(text):
        val = m.group(1).strip()
        if val.lower() not in PLACEHOLDER_WORDS and len(val) >= 5:
            findings.append({
                "category": "wechat_or_qq",
                "part": source_label,
                "masked": _mask_sensitive_text("wechat", m.group(0)),
                "high_confidence": True,
            })

    # 2. 低置信预警扫描（过滤比赛全称与参考文献出版机构）
    cleaned_text = text
    for cp in CONTEST_PHRASES:
        cleaned_text = cleaned_text.replace(cp, "〔数模竞赛〕")

    text_lower = cleaned_text.lower()
    for kw in LOW_CONFIDENCE_KEYWORDS:
        kw_lower = kw.lower()
        matched = False
        if kw == "大学":
            matched = re.search(r"大学(?!生)", cleaned_text) is not None
        elif kw in ("School", "University", "College"):
            matched = bool(re.search(rf"\b{kw_lower}\b", text_lower))
        else:
            matched = kw_lower in text_lower

        if matched:
            is_reference_context = any(
                ref_hint in text_lower
                for ref_hint in ("press", "journal", "proceedings", "trans.", "出版社", "学报", "文献", "[1]", "[2]", "[3]", "[4]", "[5]")
            )
            findings.append({
                "category": "reference_institution_hint" if is_reference_context else "generic_institution_word",
                "part": source_label,
                "keyword": kw,
                "masked": f"[{kw}]",
                "high_confidence": False,
            })


def _audit_submission_anonymity(work_dir: str, strict: bool = True) -> list[dict[str, Any]]:
    """分层审计 PDF 与 DOCX 交付物及候选清单中的作者身份、学校名称、联系方式与元数据泄露（高置信阻断 vs 低置信预警）。"""
    pdf_path = os.path.join(work_dir, "res.pdf")
    docx_path = os.path.join(work_dir, "res.docx")

    findings: list[dict[str, Any]] = []

    # 1. 扫描 PDF 文本与元数据
    pdf_unextractable = False
    if os.path.isfile(pdf_path):
        pdf_text = _extract_pdf_text(pdf_path)
        if os.path.getsize(pdf_path) > 1024 and len(pdf_text.strip()) < 50:
            pdf_unextractable = True
            findings.append({
                "category": "unextractable_pdf_text",
                "part": "res.pdf",
                "masked": "[PDF全文未抽取到有效文本，疑似纯图片扫描件，未执行OCR]",
                "high_confidence": strict,
            })
        else:
            _scan_text_for_anonymity(pdf_text, "res.pdf:text", findings)

        pdf_meta_findings = _audit_pdf_metadata(pdf_path)
        findings.extend(pdf_meta_findings)

    # 2. 扫描 DOCX (document.xml, headers, footers, footnotes, endnotes, comments, docProps)
    if os.path.isfile(docx_path):
        try:
            with zipfile.ZipFile(docx_path) as archive:
                names = archive.namelist()
                for name in names:
                    if (
                        name == "word/document.xml"
                        or name.startswith("word/header")
                        or name.startswith("word/footer")
                        or name.startswith("word/footnotes")
                        or name.startswith("word/endnotes")
                        or name.startswith("word/comments")
                    ):
                        try:
                            xml_bytes = archive.read(name)
                            paragraphs = _extract_docx_paragraphs(xml_bytes)
                            for p_idx, p_text in enumerate(paragraphs, start=1):
                                _scan_text_for_anonymity(p_text, f"docx:{name}:P{p_idx}", findings)
                        except Exception as exc:
                            findings.append({
                                "category": "damaged_docx_part",
                                "part": f"docx:{name}",
                                "masked": f"[DOCX部件解析失败: {type(exc).__name__}]",
                                "high_confidence": True,
                            })

                docx_meta_findings = _audit_docx_metadata(archive)
                findings.extend(docx_meta_findings)
        except Exception as exc:
            findings.append({
                "category": "damaged_docx",
                "part": "res.docx",
                "masked": f"[DOCX损坏或无法解压: {type(exc).__name__}]",
                "high_confidence": True,
            })

    # 3. 扫描候选清单与提交文件名中的敏感信息（完整支持 schema 1.2）
    manifest_path = os.path.join(work_dir, "candidate_manifest.json")
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as mf:
                m_data = json.load(mf)
            if isinstance(m_data, dict):
                # 3.1 顶层 submission_file（主提交文件名）
                sub_file = m_data.get("submission_file")
                if sub_file:
                    _scan_text_for_anonymity(str(sub_file), "candidate_manifest:submission_file", findings)

                # 3.2 顶层支撑材料归档名称
                for sm_key in ("support_materials", "support_materials_archive", "support_materials_manifest"):
                    sm_val = m_data.get(sm_key)
                    if sm_val:
                        _scan_text_for_anonymity(str(sm_val), f"candidate_manifest:{sm_key}", findings)

                # 3.3 字典或列表形式的 files 清单
                files_obj = m_data.get("files")
                if isinstance(files_obj, dict):
                    for file_cat, file_val in files_obj.items():
                        if isinstance(file_val, str):
                            _scan_text_for_anonymity(file_val, f"candidate_manifest:files:{file_cat}", findings)
                        elif isinstance(file_val, dict):
                            for key in ("path", "name", "filename"):
                                if file_val.get(key):
                                    _scan_text_for_anonymity(str(file_val[key]), f"candidate_manifest:files:{file_cat}", findings)
                        elif isinstance(file_val, list):
                            for list_item in file_val:
                                if isinstance(list_item, str):
                                    _scan_text_for_anonymity(list_item, f"candidate_manifest:files:{file_cat}", findings)
                                elif isinstance(list_item, dict):
                                    for key in ("path", "name", "filename"):
                                        if list_item.get(key):
                                            _scan_text_for_anonymity(str(list_item[key]), f"candidate_manifest:files:{file_cat}", findings)
                elif isinstance(files_obj, list):
                    for item in files_obj:
                        fn = str(item.get("path") or item.get("name") or "") if isinstance(item, dict) else str(item)
                        if fn:
                            _scan_text_for_anonymity(fn, "candidate_manifest:files", findings)
        except Exception as exc:
            findings.append({
                "category": "manifest_read_error",
                "part": "candidate_manifest.json",
                "masked": f"[清单解析异常: {type(exc).__name__}]",
                "high_confidence": True,
            })

    high_conf_items = [f for f in findings if f.get("high_confidence")]
    low_conf_items = [f for f in findings if not f.get("high_confidence")]

    # 严格模式下：仅高置信敏感项（或无法提取文本的扫描 PDF/损坏文档）触发阻断 FAIL；
    # 低置信词（如普通大学词、参考文献出版单位）仅报 warning，不阻断主预检 PASS。
    passed = len(high_conf_items) == 0
    severity = "error" if not passed else ("warning" if low_conf_items else "info")

    if pdf_unextractable:
        message = "PDF 全文未抽取到有效文本（疑似纯图片扫描件），已标记 PENDING_HUMAN_REVIEW，需人工复核。"
    elif not passed:
        masked_samples = ", ".join(f"{item['category']}({item['masked']})" for item in high_conf_items[:5])
        message = f"发现高置信身份/联系方式/元数据泄露或损坏敏感项: {masked_samples}。"
    elif low_conf_items:
        message = f"未发现高置信身份泄露；检测到 {len(low_conf_items)} 处低置信机构/参考文献词汇，已转为预警提示。"
    else:
        message = "PDF 与 DOCX 严格匿名检查通过，未发现作者、学校或联系方式泄露。"

    return [
        _issue(
            "submission_anonymity",
            passed,
            severity,
            message,
            {
                "high_confidence_findings": high_conf_items,
                "low_confidence_findings": low_conf_items[:30],
                "high_confidence_count": len(high_conf_items),
                "low_confidence_count": len(low_conf_items),
                "strict_mode": strict,
                "pdf_unextractable": pdf_unextractable,
            },
        )
    ]


def audit_submission(
    work_dir: str,
    *,
    require_official_fonts: bool = False,
    strict_anonymity: bool = True,
) -> dict[str, Any]:
    """Audit generated artifacts and return a structured report."""
    work_dir = os.path.abspath(work_dir)
    issues: list[dict[str, Any]] = []
    issues.extend(_audit_required_files(work_dir))
    issues.extend(_audit_reports(work_dir))
    issues.extend(_audit_candidate_manifest(work_dir))
    if os.path.isfile(os.path.join(work_dir, "res.docx")):
        issues.append(_audit_docx_markdown_heading_leakage(work_dir))
        issues.append(_audit_template_override(work_dir))
        issues.append(_audit_docx_format_contract(work_dir))
    issues.extend(_audit_submission_anonymity(work_dir, strict=strict_anonymity))
    issues.extend(_audit_support_materials(work_dir))
    issues.append(_audit_similarity_ai_risk(work_dir))
    issues.append(_audit_cross_modal_integrity(work_dir))
    font_issues, font_summary = _audit_pdf_fonts(work_dir, require_official_fonts)
    issues.extend(font_issues)

    status = _status_from_issues(issues)
    return {
        "schema_version": "1.1",
        "generated_at": datetime.datetime.now().isoformat(),
        "work_dir": work_dir,
        "status": status,
        "require_official_fonts": require_official_fonts,
        "strict_anonymity": strict_anonymity,
        "inputs": {
            "res_md_sha256": _file_sha256(os.path.join(work_dir, "res.md")),
            "res_docx_sha256": _file_sha256(os.path.join(work_dir, "res.docx")),
            "res_pdf_sha256": _file_sha256(os.path.join(work_dir, "res.pdf")),
        },
        "checks": issues,
        "font_summary": font_summary,
    }



def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Submission Audit Report",
        "",
        f"- Status: `{report['status']}`",
        f"- Work dir: `{report['work_dir']}`",
        f"- Require official fonts: `{report['require_official_fonts']}`",
        "",
        "## Checks",
        "",
    ]
    for item in report["checks"]:
        mark = "PASS" if item["passed"] else item["severity"].upper()
        lines.append(f"- `{mark}` `{item['id']}`: {item['message']}")
    lines.append("")
    return "\n".join(lines)


def write_submission_audit_report(
    work_dir: str,
    *,
    require_official_fonts: bool = False,
    strict_anonymity: bool = True,
) -> dict[str, Any]:
    """Write submission_audit_report.json/md and return the report."""
    report = audit_submission(
        work_dir,
        require_official_fonts=require_official_fonts,
        strict_anonymity=strict_anonymity,
    )
    json_path = os.path.join(work_dir, REPORT_JSON)
    md_path = os.path.join(work_dir, REPORT_MD)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_markdown_report(report))
    logger.info(f"submission_audit_report 生成成功: {json_path}")
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.tools.submission_audit",
        description="审核建模任务产物、PDF 视觉报告、严格匿名状态和正式字体使用状态。",
    )
    parser.add_argument(
        "work_dir_pos",
        nargs="?",
        default=None,
        metavar="WORK_DIR",
        help="任务工作目录（位置参数），例如 project/work_dir/<task_id>",
    )
    parser.add_argument(
        "--work-dir",
        dest="work_dir_opt",
        default=None,
        help="任务工作目录，例如 project/work_dir/<task_id>",
    )
    parser.add_argument(
        "--require-official-fonts",
        action="store_true",
        help="正式提交门禁：如果 PDF 使用 fallback/未知字体则返回 FAIL。",
    )
    parser.add_argument(
        "--allow-anonymity-warnings",
        action="store_true",
        help="关闭 strict 匿名模式，将疑似身份泄露作为 warning 而非阻断 error。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    target_work_dir = args.work_dir_opt or args.work_dir_pos
    if not target_work_dir:
        parser.error("必须指定任务工作目录（通过位置参数或 --work-dir）")
    report = write_submission_audit_report(
        target_work_dir,
        require_official_fonts=args.require_official_fonts,
        strict_anonymity=not args.allow_anonymity_warnings,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
