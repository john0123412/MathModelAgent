"""候选方案导出协议模块，生成可被 math-modeling-skills 导入的 candidate_manifest.json。"""

import os
import json
import datetime
import hashlib
import re
import zipfile
from app.utils.log_util import logger

SCHEMA_VERSION = "1.2"
SOURCE_NAME = "MathModelAgent"
SUPPORT_MANIFEST = "support_materials_manifest.json"
SUPPORT_ARCHIVE = "support_materials.zip"
SUPPORT_MAX_BYTES = 20 * 1024 * 1024

# 图片扩展名（大小写不敏感）
_IMAGE_EXTS = (".png", ".jpg", ".jpeg")

# 递归扫描图片时需要跳过的明显缓存/临时目录
_EXCLUDED_DIR_NAMES = {
    "__pycache__",
    ".ipynb_checkpoints",
    "node_modules",
    ".git",
    ".cache",
    ".agent-work",
    ".ipython",
    ".jupyter_runtime",
    ".matplotlib",
    "failed_attempts",
    "internal",
    "latex_project",
    "recovery_review_pages",
    "review",
    "screenshots",
}

# Files which may contain credentials, runtime state or internal review data are
# never support material, even when their extension otherwise looks useful.
_SUPPORT_EXCLUDED_FILENAMES = {
    "candidate_manifest.json", SUPPORT_MANIFEST, SUPPORT_ARCHIVE,
    "checkpoint.json", "variable_snapshot.pkl", "variable_snapshot_meta.json",
    "task_status.json", "export_status.json", "docx_export_status.json",
    "modeler_plan.json", "modeler_plan.md", "modeling_decision.json",
    "modeling_decision.md", "paper_preflight_report.json", "paper_preflight_report.md",
    "paper_outline.json", "figure_usage.json", "claim_trace.json", "claim_trace.md",
    "pdf_visual_check.json", "submission_audit_report.json", "submission_audit_report.md",
    "final_acceptance_report.json", "final_acceptance_report.md", "tex_export_status.json",
    "res.md", "res.json", "res.docx", "res.pdf", "paper_appendix_config.json",
    "test_save.png",
}
_SUPPORT_EXCLUDED_DIR_NAMES = _EXCLUDED_DIR_NAMES | {
    "internal", "review", "screenshots", "recovery_review_pages", "latex_project",
}
_SECRET_NAME_RE = re.compile(
    r"(?:^|[_\-.])(secret|secrets|token|password|passwd|credential|credentials|api[_-]?key|apikey|key|keys|cookie|private|id[_-]?rsa)(?:$|[_\-.])",
    re.IGNORECASE,
)
_SUPPORT_EXT_CATEGORY = {
    ".py": "源程序代码", ".m": "源程序代码", ".r": "源程序代码",
    ".jl": "源程序代码", ".sql": "源程序代码", ".do": "源程序代码",
    ".ipynb": "源程序代码", ".png": "图片文件", ".jpg": "图片文件",
    ".jpeg": "图片文件", ".gif": "图片文件", ".bmp": "图片文件",
    ".webp": "图片文件", ".csv": "数据/结果文件", ".tsv": "数据/结果文件",
    ".xlsx": "数据/结果文件", ".xls": "数据/结果文件", ".txt": "数据/结果文件",
    ".json": "数据/结果文件",
}


def support_material_category(filename: str) -> str | None:
    """Return the controlled Appendix-A category for a relative file name."""
    base = os.path.basename(filename).lower()
    if base in _SUPPORT_EXCLUDED_FILENAMES or _SECRET_NAME_RE.search(base):
        return None
    return _SUPPORT_EXT_CATEGORY.get(os.path.splitext(base)[1])


def collect_support_material_paths(work_dir: str) -> list[tuple[str, str]]:
    """Collect the exact paths eligible for Appendix A and support archive."""
    if not os.path.isdir(work_dir):
        return []
    result: list[tuple[str, str]] = []
    for root, dirs, files in os.walk(work_dir):
        dirs[:] = [d for d in dirs if d not in _SUPPORT_EXCLUDED_DIR_NAMES]
        for filename in sorted(files):
            rel = os.path.relpath(os.path.join(root, filename), work_dir).replace(os.sep, "/")
            category = support_material_category(rel)
            if category:
                result.append((rel, category))
    return sorted(result, key=lambda item: (item[1], item[0]))


def collect_bounded_support_material_paths(work_dir: str) -> list[tuple[str, str]]:
    """Return the same <=20MB selection used by the support archive."""
    selected: list[tuple[str, str]] = []
    total = 0
    for rel, category in collect_support_material_paths(work_dir):
        try:
            size = os.path.getsize(os.path.join(work_dir, rel.replace("/", os.sep)))
        except OSError:
            continue
        if total + size > SUPPORT_MAX_BYTES:
            continue
        selected.append((rel, category))
        total += size
    return selected


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


def _artifact_hashes(work_dir: str) -> tuple[str | None, dict[str, str]]:
    names = (
        "res.md",
        "res.json",
        "res.docx",
        "res.pdf",
        "frozen_results.json",
    )
    hashes = {
        name: value
        for name in names
        if (value := _file_sha256(os.path.join(work_dir, name))) is not None
    }
    if not hashes:
        return None, {}
    canonical = "\n".join(f"{name}:{hashes[name]}" for name in sorted(hashes))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), hashes


def _existing_or_none(work_dir: str, filename: str) -> str | None:
    """检查 work_dir 下文件是否存在，存在返回文件名，否则返回 None。

    Args:
        work_dir: 工作目录路径。
        filename: 待检查的文件名（相对 work_dir）。

    Returns:
        文件存在时返回 filename，否则返回 None。
    """
    if os.path.exists(os.path.join(work_dir, filename)):
        return filename
    return None


def _scan_figures(work_dir: str) -> list[str]:
    """递归扫描 work_dir 下的图片文件（png/jpg/jpeg），排除明显缓存目录。

    Args:
        work_dir: 工作目录路径。

    Returns:
        图片文件相对路径列表（相对 work_dir，使用 "/" 分隔，按路径排序）。
    """
    if not os.path.isdir(work_dir):
        return []

    figures = []
    for root, dirs, files in os.walk(work_dir):
        dirs[:] = [d for d in dirs if d not in _EXCLUDED_DIR_NAMES]
        for f in files:
            if f.lower().endswith(_IMAGE_EXTS):
                rel_path = os.path.relpath(os.path.join(root, f), work_dir)
                figures.append(rel_path.replace(os.sep, "/"))
    return sorted(figures)


def _load_claims(work_dir: str) -> list[dict]:
    claim_trace_path = os.path.join(work_dir, "claim_trace.json")
    if not os.path.exists(claim_trace_path):
        return []
    try:
        with open(claim_trace_path, encoding="utf-8") as f:
            claim_trace = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"claim_trace.json 读取失败，manifest claims 留空: {exc}")
        return []
    claims = claim_trace.get("claims", [])
    if not isinstance(claims, list):
        return []
    result = []
    for item in claims:
        if not isinstance(item, dict) or not item.get("claim"):
            continue
        evidence = item.get("evidence_id_file", [])
        if isinstance(evidence, str):
            evidence = [evidence]
        evidence = evidence if isinstance(evidence, list) else []
        source_records = []
        for source in evidence:
            if not isinstance(source, str) or ":" in source and not os.path.exists(os.path.join(work_dir, source)):
                source_records.append({"source": source, "verifiable": False, "status": "manual_review_required"})
                continue
            path = os.path.join(work_dir, source)
            exists = os.path.isfile(path)
            source_records.append({
                "source": source,
                "verifiable": exists,
                "status": "verified_local" if exists else "manual_review_required",
                "sha256": _file_sha256(path) if exists else None,
            })
        result.append({
            "claim": item.get("claim", ""),
            "paper_section": item.get("paper_section", ""),
            "evidence_type": item.get("evidence_type", ""),
            "evidence_id_file": item.get("evidence_id_file", []),
            "strength": item.get("strength", ""),
            "paper_wording_check": item.get("paper_wording_check", ""),
            "source_records": source_records,
            "source_verification": item.get("source_verification", "manual_review_required"),
        })
    return result


def _write_support_materials(work_dir: str) -> dict:
    """Create a bounded, deterministic support archive and its manifest."""
    entries = []
    excluded = []
    total = 0
    for rel, category in collect_support_material_paths(work_dir):
        path = os.path.join(work_dir, rel.replace("/", os.sep))
        try:
            size = os.path.getsize(path)
        except OSError:
            excluded.append({"path": rel, "reason": "unreadable"})
            continue
        if total + size > SUPPORT_MAX_BYTES:
            excluded.append({"path": rel, "reason": "20MB total limit"})
            continue
        digest = _file_sha256(path)
        if digest is None:
            excluded.append({"path": rel, "reason": "unreadable"})
            continue
        entries.append({"path": rel, "category": category, "size": size, "sha256": digest})
        total += size

    archive_path = os.path.join(work_dir, SUPPORT_ARCHIVE)
    archive_error = None
    try:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in entries:
                archive.write(os.path.join(work_dir, item["path"].replace("/", os.sep)), item["path"])
    except (OSError, zipfile.BadZipFile) as exc:
        archive_error = f"archive_failed:{type(exc).__name__}"
    archive_size = os.path.getsize(archive_path) if os.path.isfile(archive_path) else None
    archive_hash = _file_sha256(archive_path)
    if archive_size is not None and archive_size > SUPPORT_MAX_BYTES:
        archive_error = archive_error or "archive_exceeds_20MB"
        try:
            os.remove(archive_path)
            archive_size = None
            archive_hash = None
        except OSError:
            pass
    manifest = {
        "schema_version": "1.0",
        "generated_at": datetime.datetime.now().isoformat(),
        "max_bytes": SUPPORT_MAX_BYTES,
        "total_source_bytes": total,
        "files": entries,
        "excluded": excluded,
        "archive": {"path": SUPPORT_ARCHIVE, "size": archive_size, "sha256": archive_hash},
        "archive_error": archive_error,
        "verification_note": "仅表示本地文件清单、大小和 SHA-256 可复核；不表示内容安全、原创性或正式查重通过。",
    }
    with open(os.path.join(work_dir, SUPPORT_MANIFEST), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    return manifest


def write_support_materials_manifest(work_dir: str) -> str:
    """Public helper for export-only callers; also refreshes the ZIP archive."""
    _write_support_materials(work_dir)
    return os.path.join(work_dir, SUPPORT_MANIFEST)


def write_candidate_manifest(
    work_dir: str, task_id: str, *, submission_file: str = "res.pdf"
) -> str:
    """生成候选方案导出协议文件 candidate_manifest.json。

    扫描 work_dir 下已产出的文件（res.md/res.json/res.docx/res.pdf/notebook.ipynb/
    export_status.json/modeling_decision.json/modeling_decision.md/
    paper_preflight_report.json/paper_preflight_report.md/
    paper_outline.json/figure_usage.json/claim_trace.json/claim_trace.md/
    pdf_visual_check.json/execution_validation.json/execution_validation_report.json/
    submission_audit_report.json/图片），不存在的文件字段为 None，图片列表为空数组。
    claims 字段来自 claim_trace.json，不存在或不可读时保持空数组；本函数只记录
    已生成的可追踪结论，不自行从正文猜造额外内容。

    Args:
        work_dir: 任务工作目录路径。
        task_id: 任务 ID。

    Returns:
        生成的 candidate_manifest.json 文件的绝对/相对路径（与传入 work_dir 一致的路径风格）。
    """
    support_manifest = _write_support_materials(work_dir)
    artifact_set_id, artifact_hashes = _artifact_hashes(work_dir)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "task_id": task_id,
        "generated_at": datetime.datetime.now().isoformat(),
        "artifact_set_id": artifact_set_id,
        "artifact_hashes": artifact_hashes,
        # Exactly one primary file is exported for external submission.  Keep
        # this explicit even when the file is absent so an auditor can reject
        # an incomplete candidate instead of guessing from directory contents.
        "submission_file": submission_file,
        "submission_file_sha256": _file_sha256(os.path.join(work_dir, submission_file))
        if isinstance(submission_file, str) else None,
        "support_materials_manifest": SUPPORT_MANIFEST,
        "support_materials_archive": SUPPORT_ARCHIVE,
        "support_materials": support_manifest,
        "files": {
            "res_md": _existing_or_none(work_dir, "res.md"),
            "res_json": _existing_or_none(work_dir, "res.json"),
            "res_docx": _existing_or_none(work_dir, "res.docx"),
            "res_pdf": _existing_or_none(work_dir, "res.pdf"),
            "modeler_plan_md": _existing_or_none(work_dir, "modeler_plan.md"),
            "modeler_plan_json": _existing_or_none(work_dir, "modeler_plan.json"),
            "modeling_decision": _existing_or_none(
                work_dir, "modeling_decision.json"
            ),
            "modeling_decision_md": _existing_or_none(
                work_dir, "modeling_decision.md"
            ),
            "notebook": _existing_or_none(work_dir, "notebook.ipynb"),
            "problem_contract": _existing_or_none(work_dir, "problem_contract.json"),
            "execution_validation": _existing_or_none(
                work_dir, "execution_validation.json"
            ),
            "execution_validation_report": _existing_or_none(
                work_dir, "execution_validation_report.json"
            ),
            "export_status": _existing_or_none(work_dir, "export_status.json"),
            "docx_export_status": _existing_or_none(
                work_dir, "docx_export_status.json"
            ),
            "paper_preflight_report": _existing_or_none(
                work_dir, "paper_preflight_report.json"
            ),
            "paper_preflight_report_md": _existing_or_none(
                work_dir, "paper_preflight_report.md"
            ),
            "paper_outline": _existing_or_none(work_dir, "paper_outline.json"),
            "figure_usage": _existing_or_none(work_dir, "figure_usage.json"),
            "claim_trace": _existing_or_none(work_dir, "claim_trace.json"),
            "claim_trace_md": _existing_or_none(work_dir, "claim_trace.md"),
            "pdf_visual_check": _existing_or_none(work_dir, "pdf_visual_check.json"),
            "submission_audit_report": _existing_or_none(
                work_dir, "submission_audit_report.json"
            ),
            "submission_audit_report_md": _existing_or_none(
                work_dir, "submission_audit_report.md"
            ),
            "final_acceptance_report": _existing_or_none(
                work_dir, "final_acceptance_report.json"
            ),
            "final_acceptance_report_md": _existing_or_none(
                work_dir, "final_acceptance_report.md"
            ),
            "support_materials_manifest": _existing_or_none(work_dir, SUPPORT_MANIFEST),
            "support_materials_archive": _existing_or_none(work_dir, SUPPORT_ARCHIVE),
            "latex_main": _existing_or_none(work_dir, "latex_project/main.tex"),
            "latex_project": _existing_or_none(work_dir, "latex_project"),
            "tex_export_status": _existing_or_none(work_dir, "tex_export_status.json"),
            "figures": _scan_figures(work_dir),
        },
        "claims": _load_claims(work_dir),
        "known_risks": [
            "External candidate output must be revalidated before final submission.",
            "execution_validation_report.json must be PASS before a task is treated as completed.",
            "submission_audit_report.json is an automated gate; WARN/FAIL items must be resolved or accepted before final submission.",
            "LaTeX project is a candidate sidecar export and must be verified before final submission.",
        ],
    }

    manifest_path = os.path.join(work_dir, "candidate_manifest.json")
    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        logger.info(f"candidate_manifest.json 生成成功: {manifest_path}")
    except Exception as e:
        logger.error(f"candidate_manifest.json 生成失败: {e}")
        raise

    return manifest_path
