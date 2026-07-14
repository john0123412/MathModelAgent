"""候选方案导出协议模块，生成可被 math-modeling-skills 导入的 candidate_manifest.json。"""

import os
import json
import datetime
from app.utils.log_util import logger

SCHEMA_VERSION = "1.0"
SOURCE_NAME = "MathModelAgent"

# 图片扩展名（大小写不敏感）
_IMAGE_EXTS = (".png", ".jpg", ".jpeg")

# 递归扫描图片时需要跳过的明显缓存/临时目录
_EXCLUDED_DIR_NAMES = {
    "__pycache__",
    ".ipynb_checkpoints",
    "node_modules",
    ".git",
    ".cache",
}


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
    return [
        {
            "claim": item.get("claim", ""),
            "paper_section": item.get("paper_section", ""),
            "evidence_type": item.get("evidence_type", ""),
            "evidence_id_file": item.get("evidence_id_file", []),
            "strength": item.get("strength", ""),
            "paper_wording_check": item.get("paper_wording_check", ""),
        }
        for item in claims
        if isinstance(item, dict) and item.get("claim")
    ]


def write_candidate_manifest(work_dir: str, task_id: str) -> str:
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
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "task_id": task_id,
        "generated_at": datetime.datetime.now().isoformat(),
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
