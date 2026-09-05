"""Task state diagnosis and audited reconciliation (batch 3).

External ``task_status`` and internal ``workflow_state``/``quality_review_status``
must obey a legal correspondence.  Historical manual deliveries left records
like ``completed + quality_repair`` (08-23) or ``completed + not_run`` with a
PASS report (08-17).  This module is the read-only diagnostic for such states
plus the single audited entry that may converge them; it never fabricates
approvals and never reruns computation.

CLI (read-only diagnosis):

    python -m app.tools.task_state_diagnosis --work-dir <dir>

CLI (audited reconciliation, explicit operator + reason required):

    python -m app.tools.task_state_diagnosis --work-dir <dir> \
        --reconcile converge_completed --operator <name> --reason <text>
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
from typing import Any

RECONCILIATION_FILENAME = "state_reconciliation.json"
_SCHEMA_VERSION = "mathmodel.task-state-diagnosis.v1"

MAIN_ARTIFACTS = (
    "res.md",
    "res.json",
    "res.docx",
    "res.pdf",
    "frozen_results.json",
)

# Internal states that legitimately coexist with an external ``completed``.
_COMPLETED_TERMINAL = {
    "paper_preflight_passed",
    "paper_repair_pending_export",
    "editorial_repair_pending_export",
    "presentation_reflow_pending_export",
    "format_compliance_pending_export",
}
_EXPORT_TRANSITIONAL = {s for s in _COMPLETED_TERMINAL if s.endswith("_pending_export")}
# Internal states that mean work is still owed; never legal under completed.
INFLIGHT_STATES = {
    "frozen",
    "quality_repair",
    "repairing",
    "paper_repairing",
    "modeling_revision",
    "manual_recovery",
    "waiting_quality_review",
}
_RECONCILE_ACTIONS = {"converge_completed", "downgrade_to_failed"}


def _read_json(path: Path) -> dict | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _load_checkpoint_state(work_dir: Path) -> dict[str, Any]:
    checkpoint = _read_json(work_dir / "checkpoint.json") or {}
    return {
        "workflow_state": checkpoint.get("workflow_state") or "",
        "quality_review_status": checkpoint.get("quality_review_status") or "not_run",
        "quality_review_id": checkpoint.get("quality_review_id") or "",
    }


def diagnose_task_state(work_dir: str | os.PathLike[str]) -> dict[str, Any]:
    """Read-only verdict on the external/internal state correspondence."""
    root = Path(work_dir)
    status_doc = _read_json(root / "task_status.json") or {}
    external = str(status_doc.get("status") or "")
    internal = _load_checkpoint_state(root)
    artifacts = {name: (root / name).is_file() for name in MAIN_ARTIFACTS}
    missing = [name for name, present in artifacts.items() if not present]
    acceptance = _read_json(root / "final_acceptance_report.json") or {}
    technical = str(acceptance.get("technical_status") or "")

    issues: list[str] = []
    verdict = "CONSISTENT"
    workflow_state = internal["workflow_state"]
    quality_status = internal["quality_review_status"]

    if external == "completed":
        if workflow_state in INFLIGHT_STATES:
            verdict = "CONTRADICTION"
            issues.append(
                f"对外 completed 但内部 workflow_state={workflow_state!r}，仍有未收敛的返修/复核。"
            )
        elif workflow_state and workflow_state not in _COMPLETED_TERMINAL:
            verdict = "CONTRADICTION"
            issues.append(f"对外 completed 但内部状态 {workflow_state!r} 不在合法终态集合。")
        if quality_status in {"pending", "repair_requested"}:
            verdict = "CONTRADICTION"
            issues.append(f"对外 completed 但质量复核状态为 {quality_status!r}。")
        if missing:
            verdict = "CONTRADICTION"
            issues.append(f"主产物缺失：{missing}。")
        elif technical and technical != "TECHNICAL_PASS":
            verdict = "CONTRADICTION"
            issues.append(f"主产物齐全但 final_acceptance={technical!r}，completed 不成立。")
        elif workflow_state in _EXPORT_TRANSITIONAL:
            verdict = "TRANSITIONAL_EXPORT"
            issues.append(
                "内部状态为候选返修后的待导出态：允许仅导出续传，属设计内过渡，不是缺陷。"
            )
    elif external in {"running", "resuming", "revising"}:
        if not workflow_state:
            issues.append("执行中但缺少 checkpoint 内部状态。")
    elif external == "waiting_quality_review":
        if workflow_state != "waiting_quality_review":
            verdict = "CONTRADICTION"
            issues.append(
                f"对外等待质量复核但内部 workflow_state={workflow_state!r}。"
            )
    elif external == "waiting_review":
        pass
    elif external in {"failed", "cancelled", ""}:
        pass  # 失败/取消/无状态记录保留准确阶段即可。
    else:
        issues.append(f"未知对外状态 {external!r}。")

    return {
        "schema_version": _SCHEMA_VERSION,
        "work_dir": str(root),
        "generated_at": datetime.datetime.now().isoformat(),
        "external_status": external,
        "internal": internal,
        "artifacts": artifacts,
        "final_acceptance": technical,
        "verdict": verdict,
        "issues": issues,
        "reconcile_allowed": sorted(_RECONCILE_ACTIONS) if verdict == "CONTRADICTION" else [],
    }


def reconcile_task_state(
    work_dir: str | os.PathLike[str],
    *,
    action: str,
    operator: str,
    reason: str,
) -> dict[str, Any]:
    """Audited explicit fix for a diagnosed contradiction. No silent JSON edits.

    ``converge_completed``  - only when artifacts are complete and final
        acceptance is TECHNICAL_PASS: move the stale internal state to the
        legal terminal ``paper_preflight_passed``.  Never touches approvals.
    ``downgrade_to_failed`` - when completed is unsupported: persist external
        status ``failed`` so the task list stops presenting a false delivery.
    """
    if action not in _RECONCILE_ACTIONS:
        raise ValueError(f"未知修复动作：{action}")
    operator = operator.strip()
    reason = reason.strip()
    if not operator or not reason:
        raise ValueError("修复必须提供操作人与理由（写入审计记录）")
    root = Path(work_dir)
    diagnosis = diagnose_task_state(root)
    if diagnosis["verdict"] != "CONTRADICTION":
        raise RuntimeError(f"当前状态为 {diagnosis['verdict']}，无需/不允许修复：{diagnosis['issues']}")

    artifacts_complete = all(diagnosis["artifacts"].values())
    technical_pass = diagnosis["final_acceptance"] == "TECHNICAL_PASS"
    before = {
        "external_status": diagnosis["external_status"],
        **diagnosis["internal"],
    }

    if action == "converge_completed":
        if not (artifacts_complete and technical_pass):
            raise RuntimeError(
                "产物集或技术验收不支撑 completed，不能收敛为完成；请改用 downgrade_to_failed。"
            )
        if diagnosis["internal"].get("quality_review_status") in {"pending", "repair_requested"}:
            raise RuntimeError(
                "质量复核仍有未执行的待审/返修请求，收敛完成等于吞掉返修；"
                "请先执行返修或显式批准，再考虑收敛。"
            )
        checkpoint_path = root / "checkpoint.json"
        checkpoint = _read_json(checkpoint_path)
        if checkpoint is None:
            raise RuntimeError("缺少 checkpoint.json，无法收敛内部状态")
        checkpoint["workflow_state"] = "paper_preflight_passed"
        checkpoint["updated_at"] = datetime.datetime.now().isoformat()
        tmp = checkpoint_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, checkpoint_path)
        after = {**before, "workflow_state": "paper_preflight_passed"}
    else:
        status_path = root / "task_status.json"
        status_doc = _read_json(status_path) or {}
        status_doc["status"] = "failed"
        status_doc["message"] = f"状态核对降级：{reason}"
        status_doc["updated_at"] = datetime.datetime.now().isoformat()
        tmp = status_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(status_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, status_path)
        after = {**before, "external_status": "failed"}

    record = {
        "action": action,
        "operator": operator,
        "reason": reason[:2000],
        "before": before,
        "after": after,
        "diagnosis_issues": diagnosis["issues"],
        "recorded_at": datetime.datetime.now().isoformat(),
    }
    audit_path = root / RECONCILIATION_FILENAME
    history = _read_json(audit_path) or {"schema_version": _SCHEMA_VERSION, "history": []}
    history.setdefault("history", []).append(record)
    tmp = audit_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, audit_path)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="任务状态诊断与有审计记录的显式修复")
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--reconcile", choices=sorted(_RECONCILE_ACTIONS))
    parser.add_argument("--operator", default="")
    parser.add_argument("--reason", default="")
    args = parser.parse_args(argv)
    if args.reconcile:
        try:
            record = reconcile_task_state(
                args.work_dir,
                action=args.reconcile,
                operator=args.operator,
                reason=args.reason,
            )
        except (ValueError, RuntimeError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 2
        print(json.dumps({"ok": True, "record": record}, ensure_ascii=False, indent=2))
        return 0
    diagnosis = diagnose_task_state(args.work_dir)
    print(json.dumps(diagnosis, ensure_ascii=False, indent=2))
    return 0 if diagnosis["verdict"] in {"CONSISTENT", "TRANSITIONAL_EXPORT"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
