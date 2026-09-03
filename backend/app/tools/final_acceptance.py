"""Strict, layered final acceptance report for mathematical-modeling deliverables.

This report deliberately separates machine-verifiable technical readiness from
the mathematical and editorial decisions that must remain with the team.
``TECHNICAL_PASS`` never means that a paper is mathematically correct or ready
to upload without human review.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
from typing import Any

from app.tools.paper_postprocessor import _listings_safe_code, collect_code_sources
from app.tools.result_integrity import validate_result_freeze
from app.tools.submission_audit import audit_submission


REPORT_JSON = "final_acceptance_report.json"
REPORT_MD = "final_acceptance_report.md"
_REQUIRED_FILES = (
    "res.md",
    "res.json",
    "res.docx",
    "res.pdf",
    "candidate_manifest.json",
)
_REQUIRED_REPORTS = (
    "execution_validation_report.json",
    "paper_preflight_report.json",
    "pdf_visual_check.json",
    "submission_audit_report.json",
    "docx_export_status.json",
    "export_status.json",
)
_SOURCE_HEADING_RE = re.compile(r"(?m)^###\s+[A-Z]\.\d+\s+(?P<name>.+?)\s*$")
_LEGACY_SOURCE_HEADING_RE = re.compile(
    r"(?m)^###\s+[A-Z]\.\d+\s+(?P<name>.+?)（SHA-256:\s*(?P<sha>[0-9a-f]{64})）\s*$"
)
_SOURCE_HASH_RE = re.compile(r"(?m)^SHA-256:\s*\n(?P<sha>(?:[0-9a-f]{16}\s*){4})$")
_FORMAL_EDITORIAL_EXPORT_PROFILES = {"cumcm2025", "cumcm2026"}
_STRICT_PDF_EDITORIAL_POLICY = "cumcm2026_strict"
_STRICT_PREFLIGHT_EDITORIAL_POLICY = "cumcm_formal"


def _read_json(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _check(check_id: str, passed: bool, message: str, **evidence: Any) -> dict[str, Any]:
    return {
        "id": check_id,
        "passed": passed,
        "severity": "error" if not passed else "info",
        "message": message,
        "evidence": evidence,
    }


def _status_check(
    work_dir: str, filename: str, expected: str | tuple[str, ...]
) -> dict[str, Any]:
    report = _read_json(os.path.join(work_dir, filename))
    accepted = (expected,) if isinstance(expected, str) else expected
    actual = report.get("status") if report else None
    passed = actual in accepted
    conditional = passed and actual != "PASS"
    check = _check(
        filename.removesuffix(".json"),
        passed,
        (f"{filename} = {actual}；条件项仍需复核。" if conditional else f"{filename} = {actual}。")
        if passed else f"{filename} 必须为 {' / '.join(accepted)}，实际为 {actual}。",
        actual=actual,
        accepted_statuses=list(accepted),
    )
    if conditional:
        check["severity"] = "warning"
    return check


def _sha256_file(path: str) -> str | None:
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


def _check_artifact_freshness(work_dir: str) -> dict[str, Any]:
    current = {
        name: _sha256_file(os.path.join(work_dir, name))
        for name in ("res.md", "res.json", "res.docx", "res.pdf", "frozen_results.json")
    }
    export_status = _read_json(os.path.join(work_dir, "export_status.json")) or {}
    pdf_status = export_status.get("pdf") if isinstance(export_status.get("pdf"), dict) else {}
    docx_status = _read_json(os.path.join(work_dir, "docx_export_status.json")) or {}
    manifest = _read_json(os.path.join(work_dir, "candidate_manifest.json")) or {}
    manifest_hashes = manifest.get("artifact_hashes")
    if not isinstance(manifest_hashes, dict):
        manifest_hashes = {}

    mismatches: list[str] = []
    if not pdf_status.get("success"):
        mismatches.append("PDF 导出状态不是 success")
    if pdf_status.get("source_sha256") != current["res.md"]:
        mismatches.append("PDF 来源 res.md 哈希不匹配")
    if pdf_status.get("output_sha256") != current["res.pdf"]:
        mismatches.append("PDF 输出哈希不匹配")
    if not docx_status.get("success"):
        mismatches.append("DOCX 导出状态不是 success")
    if docx_status.get("source_sha256") != current["res.md"]:
        mismatches.append("DOCX 来源 res.md 哈希不匹配")
    if docx_status.get("output_sha256") != current["res.docx"]:
        mismatches.append("DOCX 输出哈希不匹配")
    for name, digest in current.items():
        if digest is not None and manifest_hashes.get(name) != digest:
            mismatches.append(f"candidate_manifest 中 {name} 哈希不匹配")

    return _check(
        "artifact_freshness",
        not mismatches,
        "PDF、DOCX、候选清单均绑定当前交付文件哈希。"
        if not mismatches
        else "导出产物或候选清单与当前源文件不是同一批次。",
        mismatches=mismatches,
        artifact_set_id=manifest.get("artifact_set_id"),
    )


def _check_editorial_quality_gate(work_dir: str) -> dict[str, Any]:
    """Require explicit strict editorial checks for formal CUMCM artifacts.

    A bare ``PASS`` status is intentionally insufficient here.  Older reports
    were able to pass before the paper-quality policy existed, which is the
    exact false-positive this gate prevents.  The thresholds remain internal
    review criteria and are not represented as official competition rules.
    """
    export_status = _read_json(os.path.join(work_dir, "export_status.json")) or {}
    profile = str(export_status.get("export_profile", ""))
    if profile not in _FORMAL_EDITORIAL_EXPORT_PROFILES:
        return _check(
            "editorial_quality_gate",
            True,
            "非正式 CUMCM profile 不启用内部编辑质量硬门禁。",
            active=False,
            export_profile=profile,
            official_rule=False,
        )

    preflight = _read_json(os.path.join(work_dir, "paper_preflight_report.json")) or {}
    visual = _read_json(os.path.join(work_dir, "pdf_visual_check.json")) or {}
    preflight_check = (
        preflight.get("checks", {}).get("editorial_quality")
        if isinstance(preflight.get("checks"), dict)
        else None
    )
    visual_check = (
        visual.get("checks", {}).get("editorial_quality")
        if isinstance(visual.get("checks"), dict)
        else None
    )
    preflight_ok = isinstance(preflight_check, dict) and all(
        (
            preflight_check.get("passed") is True,
            preflight_check.get("quality_passed") is True,
            preflight_check.get("enforced") is True,
            preflight_check.get("policy") == _STRICT_PREFLIGHT_EDITORIAL_POLICY,
            preflight_check.get("official_rule") is False,
        )
    )
    visual_ok = isinstance(visual_check, dict) and all(
        (
            visual_check.get("passed") is True,
            visual_check.get("blocking") is True,
            visual_check.get("policy") == _STRICT_PDF_EDITORIAL_POLICY,
            visual_check.get("official_rule") is False,
        )
    )
    passed = preflight_ok and visual_ok
    return _check(
        "editorial_quality_gate",
        passed,
        "内部编辑质量预检与 PDF 严格复核均已通过。"
        if passed
        else "正式 CUMCM 候选缺少或未通过内部编辑质量硬门禁。",
        active=True,
        export_profile=profile,
        official_rule=False,
        preflight_editorial=preflight_check,
        pdf_editorial=visual_check,
    )


def _check_complete_source_appendix(work_dir: str) -> dict[str, Any]:
    markdown_path = os.path.join(work_dir, "res.md")
    try:
        with open(markdown_path, encoding="utf-8") as handle:
            markdown = handle.read()
    except OSError:
        return _check("complete_source_appendix", False, "无法读取 res.md，不能核验源码附录。")

    headings = {
        match.group("name"): match.group("sha")
        for match in _LEGACY_SOURCE_HEADING_RE.finditer(markdown)
    }
    appendix_headings = list(_SOURCE_HEADING_RE.finditer(markdown))
    for index, match in enumerate(appendix_headings):
        name = match.group("name")
        if "（SHA-256:" in name:
            continue
        block_end = (
            appendix_headings[index + 1].start()
            if index + 1 < len(appendix_headings)
            else len(markdown)
        )
        hash_match = _SOURCE_HASH_RE.search(markdown, match.end(), block_end)
        if hash_match:
            headings[name] = re.sub(r"\s+", "", hash_match.group("sha"))
    sources = collect_code_sources(work_dir)
    missing: list[str] = []
    hash_mismatches: list[str] = []
    content_mismatches: list[str] = []
    for source in sources:
        expected_hash = _sha256_text(source.code)
        if source.name not in headings:
            missing.append(source.name)
            continue
        if headings[source.name] != expected_hash:
            hash_mismatches.append(source.name)
        # A source heading alone is not enough: the exact runnable text must be
        # present in the paper, rather than a support-material filename or an
        # abbreviated snippet.
        # ``_listings_safe_code`` is a reversible TeX-safety encoding for an
        # otherwise literal ``\\end{lstlisting}`` token and decorative source
        # separators.  The original hash above remains authoritative.
        if source.code not in markdown and _listings_safe_code(source.code) not in markdown:
            content_mismatches.append(source.name)
    passed = bool(sources) and not missing and not hash_mismatches and not content_mismatches
    if not sources:
        message = "未发现可运行源程序，不能证明论文附录包含完整源码。"
    elif passed:
        message = "论文附录已包含所有发现的完整源程序，并记录了对应 SHA-256。"
    else:
        message = "论文附录缺少、截断或改写了部分可运行源程序。"
    return _check(
        "complete_source_appendix",
        passed,
        message,
        source_count=len(sources),
        missing=missing,
        hash_mismatches=hash_mismatches,
        content_mismatches=content_mismatches,
        remediation="重新运行论文后处理以完整写入附录；若源码包含导出不安全内容，先将其模块化/清理后再导出，不得用摘要替代。",
    )


def audit_final_acceptance(work_dir: str) -> dict[str, Any]:
    """Return the strict final-acceptance result without changing task files."""
    work_dir = os.path.abspath(work_dir)
    checks: list[dict[str, Any]] = []
    missing_files = [name for name in _REQUIRED_FILES if not os.path.isfile(os.path.join(work_dir, name))]
    checks.append(
        _check(
            "primary_deliverables",
            not missing_files,
            "主交付文件与候选清单齐全。" if not missing_files else "缺少主交付文件或候选清单。",
            missing=missing_files,
        )
    )
    missing_reports = [name for name in _REQUIRED_REPORTS if not os.path.isfile(os.path.join(work_dir, name))]
    checks.append(
        _check(
            "required_reports",
            not missing_reports,
            "关键技术报告齐全。" if not missing_reports else "缺少关键技术报告。",
            missing=missing_reports,
        )
    )
    checks.append(_status_check(work_dir, "execution_validation_report.json", "PASS"))
    # Only the explicit generic profile accepts reviewable conditions. Missing,
    # unknown and competition profiles retain their existing strict policy.
    export_status = _read_json(os.path.join(work_dir, "export_status.json")) or {}
    is_default = export_status.get("export_profile") == "default"
    checks.append(_status_check(
        work_dir, "paper_preflight_report.json",
        ("PASS", "CONDITIONAL_PASS") if is_default else "PASS",
    ))
    checks.append(_status_check(work_dir, "pdf_visual_check.json", "PASS"))
    checks.append(_status_check(
        work_dir, "submission_audit_report.json",
        ("PASS", "WARN", "CONDITIONAL_PASS") if is_default else "PASS",
    ))
    checks.append(_check_editorial_quality_gate(work_dir))
    checks.append(_check_artifact_freshness(work_dir))

    freeze = validate_result_freeze(work_dir)
    checks.append(
        _check(
            "frozen_results_integrity",
            bool(freeze.get("active")) and bool(freeze.get("passed")),
            "冻结结果及来源哈希有效。"
            if freeze.get("active") and freeze.get("passed")
            else "冻结结果缺失、格式无效或来源哈希已变化。",
            errors=freeze.get("errors", []),
            path=freeze.get("path"),
        )
    )

    strict_audit = audit_submission(work_dir, require_official_fonts=True)
    template_check = next(
        (
            item
            for item in strict_audit.get("checks", [])
            if item.get("id") == "template_override_integrity"
        ),
        None,
    )
    checks.append(
        _check(
            "template_override_chain",
            bool(template_check and template_check.get("passed")),
            "任务级模板覆盖与所有当前导出报告一致。"
            if template_check and template_check.get("passed")
            else "任务级模板覆盖链缺失、已过期或未完成全量刷新。",
            submission_audit_status=strict_audit.get("status"),
            template_evidence=(template_check or {}).get("evidence", {}),
        )
    )
    font_check = next(
        (item for item in strict_audit.get("checks", []) if item.get("id") == "pdf_fonts"),
        None,
    )
    checks.append(
        _check(
            "official_fonts",
            bool(font_check and font_check.get("passed")),
            "PDF 使用 profile 指定的正式字体。"
            if font_check and font_check.get("passed")
            else "严格字体门禁未通过；Docker fallback 仅可用于预览。",
            submission_audit_status=strict_audit.get("status"),
            font_evidence=(font_check or {}).get("evidence", {}),
        )
    )
    checks.append(_check_complete_source_appendix(work_dir))

    technical_pass = all(item["passed"] for item in checks)
    return {
        "schema_version": "mathmodel.final-acceptance.v2",
        "generated_at": datetime.datetime.now().isoformat(),
        "work_dir": work_dir,
        "technical_status": "TECHNICAL_PASS" if technical_pass else "TECHNICAL_FAIL",
        "checks": checks,
        "human_review": {
            "status": "PENDING_HUMAN_REVIEW",
            "required_items": [
                "模型假设、推导、数值收敛与结论的数学正确性",
                "引用真实性、相关性与可追溯性",
                "PDF/DOCX 人工翻阅、匿名与竞赛规则适配",
                "提交平台文件命名、大小和最终上传要求",
            ],
            "message": "技术门禁不替代人工复核；未完成上述项目不得标记为可正式提交。",
        },
    }


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Final Acceptance Report",
        "",
        f"- Technical status: `{report['technical_status']}`",
        "- Human review: `PENDING_HUMAN_REVIEW`",
        "",
        "## Technical checks",
        "",
    ]
    for item in report["checks"]:
        lines.append(f"- `{'PASS' if item['passed'] else 'FAIL'}` `{item['id']}`: {item['message']}")
    lines.extend(["", "## Required human review", ""])
    lines.extend(f"- {item}" for item in report["human_review"]["required_items"])
    lines.extend(["", report["human_review"]["message"], ""])
    return "\n".join(lines)


def write_final_acceptance_report(work_dir: str) -> dict[str, Any]:
    """Write ``final_acceptance_report.json/md`` and return the report."""
    report = audit_final_acceptance(work_dir)
    with open(os.path.join(work_dir, REPORT_JSON), "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    with open(os.path.join(work_dir, REPORT_MD), "w", encoding="utf-8") as handle:
        handle.write(_markdown_report(report))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成严格技术验收与人工复核分层报告。")
    parser.add_argument("--work-dir", required=True)
    args = parser.parse_args(argv)
    report = write_final_acceptance_report(args.work_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["technical_status"] == "TECHNICAL_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
