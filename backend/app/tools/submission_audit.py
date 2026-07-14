"""Submission audit report for generated modeling artifacts."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from typing import Any

from app.utils.log_util import logger

REPORT_JSON = "submission_audit_report.json"
REPORT_MD = "submission_audit_report.md"

_REQUIRED_FILES = ["res.md", "res.json", "res.docx", "res.pdf"]
_REPORT_FILES = [
    "execution_validation_report.json",
    "paper_preflight_report.json",
    "pdf_visual_check.json",
    "export_status.json",
]


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
        passed = (
            preflight_status == "PASS" or preflight.get("success") is True
        ) and source_hash_matches
        conditional = preflight_status == "CONDITIONAL_PASS"
        issues.append(
            _issue(
                "paper_preflight",
                passed,
                "warning" if conditional and source_hash_matches else "error",
                "paper_preflight_report.json = PASS，且绑定当前 res.md。"
                if passed
                else "paper_preflight_report.json 已过期或未绑定当前 res.md。"
                if not source_hash_matches
                else "paper_preflight_report.json = CONDITIONAL_PASS，存在需人工复核的条件项。"
                if conditional
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


def audit_submission(
    work_dir: str,
    *,
    require_official_fonts: bool = False,
) -> dict[str, Any]:
    """Audit generated artifacts and return a structured report."""
    work_dir = os.path.abspath(work_dir)
    issues: list[dict[str, Any]] = []
    issues.extend(_audit_required_files(work_dir))
    issues.extend(_audit_reports(work_dir))
    font_issues, font_summary = _audit_pdf_fonts(work_dir, require_official_fonts)
    issues.extend(font_issues)

    status = _status_from_issues(issues)
    return {
        "schema_version": "1.1",
        "generated_at": datetime.datetime.now().isoformat(),
        "work_dir": work_dir,
        "status": status,
        "require_official_fonts": require_official_fonts,
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
) -> dict[str, Any]:
    """Write submission_audit_report.json/md and return the report."""
    report = audit_submission(work_dir, require_official_fonts=require_official_fonts)
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
        description="审核建模任务产物、PDF 视觉报告和正式字体使用状态。",
    )
    parser.add_argument("--work-dir", required=True, help="任务工作目录，例如 project/work_dir/<task_id>")
    parser.add_argument(
        "--require-official-fonts",
        action="store_true",
        help="正式提交门禁：如果 PDF 使用 fallback/未知字体则返回 FAIL。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    report = write_submission_audit_report(
        args.work_dir,
        require_official_fonts=args.require_official_fonts,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
