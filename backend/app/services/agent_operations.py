"""Agent operations service: single source for roadmap B-2 contracts.

Provides shared helpers for:
- single task status (GET /tasks/{id})
- message cursor (GET /tasks/{id}/events)
- artifact manifest (GET /tasks/{id}/artifacts)
- guidance receipt (accepted/consumed)

Used by both HTTP routers and the thin task_client, so logic is not duplicated.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.checkpoint import CheckpointManager
from app.services.task_status import read_task_status
from app.utils.common_utils import WORK_DIR_ROOT, get_work_dir
from app.utils.log_util import logger

# ---------------------------------------------------------------------------
# Allowed actions derived from persisted status
# ---------------------------------------------------------------------------

_STATUS_ALLOWED_ACTIONS: dict[str, list[str]] = {
    "pending": ["cancel"],
    "running": ["cancel", "guide"],
    "waiting_review": ["approve-model", "revise-model", "guide", "cancel"],
    "waiting_quality_review": ["review-results", "guide", "cancel"],
    "revising": ["cancel", "guide"],
    "resuming": ["cancel"],
    "finalizing": ["cancel"],
    "interrupted": ["resume", "cancel"],
    "failed": ["resume", "cancel"],
    "completed": ["artifacts"],
    "cancelled": ["artifacts"],
}

_STATUS_BLOCK_REASON: dict[str, str] = {
    "running": "任务执行中",
    "waiting_review": "等待建模方案审批",
    "waiting_quality_review": "等待冻结结果复核",
    "revising": "建模方案修订中",
    "resuming": "任务恢复中",
    "finalizing": "产物收尾中",
    "interrupted": "任务已中断，可续传",
    "failed": "任务失败，可续传或取消",
    "completed": "任务已完成",
    "cancelled": "任务已取消",
}


def _allowed_actions(status: str) -> list[str]:
    return _STATUS_ALLOWED_ACTIONS.get(status, [])


def _read_checkpoint_state(work_dir: str) -> dict[str, Any]:
    try:
        cp = CheckpointManager(work_dir).load()
        if cp is None:
            return {"workflow_state": None, "revision": None, "quality_review_id": None}
        return {
            "workflow_state": cp.workflow_state,
            "revision": cp.modeling_review_revisions,
            "quality_review_id": cp.quality_review_id,
            "quality_review_status": cp.quality_review_status,
            "targeted_repair_attempts": cp.targeted_repair_attempts,
            "paper_repair_attempts": cp.paper_repair_attempts,
            "updated_at": cp.updated_at,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"读取检查点失败: {type(exc).__name__}")
        return {"workflow_state": None, "error": str(exc)}


def _read_token_summary(task_id: str) -> dict[str, Any]:
    try:
        from app.services.token_usage import read_token_usage

        usage = read_token_usage(task_id)
        return {
            "usage_available": usage.get("usage_available", False),
            "totals": usage.get("totals", {}),
            "updated_at": usage.get("updated_at"),
        }
    except Exception:
        return {"usage_available": False, "totals": {}, "updated_at": None}


def _file_info(work_dir: str, filename: str) -> dict[str, Any] | None:
    p = Path(work_dir) / filename
    if not p.is_file():
        return None
    try:
        size = p.stat().st_size
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return {"filename": filename, "size": size, "sha256": h.hexdigest(), "exists": True}
    except OSError:
        return {"filename": filename, "exists": False}


def get_single_task_status(task_id: str) -> dict[str, Any]:
    """Build the roadmap B-2 single-task contract without scanning all tasks."""
    work_dir = get_work_dir(task_id)
    status_payload = read_task_status(work_dir)
    if status_payload is None:
        raise FileNotFoundError(f"任务不存在: {task_id}")

    status = status_payload.get("status", "unknown")
    checkpoint_state = _read_checkpoint_state(work_dir)

    # Determine current phase / subtask from checkpoint
    current_phase = None
    subtask = None
    if checkpoint_state.get("workflow_state") in {"solving", "repairing", "quality_repair"}:
        # Heuristic: last completed phase or first pending
        try:
            cp = CheckpointManager(work_dir).load()
            if cp is not None:
                completed = set(cp.completed_phases.keys()) | set(cp.solution_coder_responses.keys())
                # From questions dict, find first not completed
                questions = cp.questions if isinstance(cp.questions, dict) else {}
                for k in sorted(questions.keys()):
                    if k not in completed:
                        current_phase = k
                        subtask = k
                        break
                if current_phase is None and questions:
                    current_phase = sorted(questions.keys())[-1]
        except Exception:
            pass

    # Budget summary
    token_summary = _read_token_summary(task_id)

    # Artifact version (candidate_manifest artifact_set_id or file mtimes)
    artifact_version = None
    artifact_set_id = None
    try:
        manifest_path = Path(work_dir) / "candidate_manifest.json"
        if manifest_path.is_file():
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
            artifact_set_id = manifest.get("artifact_set_id") or manifest.get("id")
            artifact_version = manifest.get("generated_at") or manifest.get("created_at")
    except Exception:
        pass

    # Last activity from status updated_at or work_dir mtime
    last_activity = status_payload.get("updated_at")
    if not last_activity:
        try:
            last_activity = datetime.fromtimestamp(Path(work_dir).stat().st_mtime).isoformat()
        except OSError:
            last_activity = None

    review_id = checkpoint_state.get("quality_review_id") or ""

    return {
        "task_id": task_id,
        "task_status": status,
        "message": status_payload.get("message", ""),
        "workflow_state": checkpoint_state.get("workflow_state"),
        "revision": checkpoint_state.get("revision"),
        "current_phase": current_phase,
        "subtask": subtask,
        "last_activity": last_activity,
        "review_id": review_id,
        "quality_review_status": checkpoint_state.get("quality_review_status"),
        "allowed_actions": _allowed_actions(status),
        "block_reason": _STATUS_BLOCK_REASON.get(status, ""),
        "budget": token_summary,
        "artifact_version": artifact_version,
        "artifact_set_id": artifact_set_id,
        "checkpoint": checkpoint_state,
        "updated_at": status_payload.get("updated_at"),
    }


def get_task_events(task_id: str, after: str | None = None, limit: int = 50) -> dict[str, Any]:
    """Stable cursor over logs/messages/{task_id}.json{,l}."""
    work_dir = get_work_dir(task_id)  # ensure exists, raises if not
    _ = work_dir  # unused but validates

    # Prefer .json, fallback to .jsonl
    json_path = Path("logs/messages") / f"{task_id}.json"
    jsonl_path = Path("logs/messages") / f"{task_id}.jsonl"

    messages: list[dict[str, Any]] = []
    if json_path.exists():
        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                messages = [m for m in data if isinstance(m, dict)]
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"读取消息失败: {type(exc).__name__}")
    elif jsonl_path.exists():
        try:
            with open(jsonl_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        m = json.loads(line)
                        if isinstance(m, dict):
                            messages.append(m)
                    except json.JSONDecodeError:
                        continue
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"读取 JSONL 消息失败: {type(exc).__name__}")

    # Assign stable seq (0-based index)
    for idx, m in enumerate(messages):
        m.setdefault("_seq", idx)

    # Parse after cursor
    start = 0
    if after is not None and after != "":
        try:
            # after is last seen seq, next is after+1
            start = int(after) + 1
        except ValueError:
            # Try as message id
            for idx, m in enumerate(messages):
                if str(m.get("id")) == str(after):
                    start = idx + 1
                    break

    limit = max(1, min(int(limit), 200))
    sliced = messages[start : start + limit]
    next_after = sliced[-1]["_seq"] if sliced else after
    has_more = (start + limit) < len(messages)

    # Strip internal _seq before returning, but keep seq field for client
    events = []
    for m in sliced:
        e = dict(m)
        seq = e.pop("_seq", None)
        e["seq"] = seq
        events.append(e)

    return {
        "task_id": task_id,
        "total": len(messages),
        "after": after,
        "next_after": str(next_after) if next_after is not None else None,
        "has_more": has_more,
        "events": events,
        "expired": False,
    }


def get_task_artifacts(task_id: str) -> dict[str, Any]:
    """Reuse candidate manifest + file hashes."""
    work_dir = get_work_dir(task_id)
    manifest: dict[str, Any] | None = None
    manifest_path = Path(work_dir) / "candidate_manifest.json"
    if manifest_path.is_file():
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = None

    # Collect known deliverables
    deliverables = []
    for fname in ["res.md", "res.json", "res.docx", "res.pdf", "frozen_results.json", "execution_validation.json", "candidate_manifest.json"]:
        info = _file_info(work_dir, fname)
        if info is not None:
            # Freshness: compare file mtime vs manifest generated_at
            deliverables.append(info)

    # Paper assets manifest
    assets_manifest = None
    for candidate in ["paper_assets_manifest.json", "support_manifest.json"]:
        p = Path(work_dir) / candidate
        if p.is_file():
            try:
                with open(p, encoding="utf-8") as f:
                    assets_manifest = json.load(f)
                break
            except Exception:
                pass

    return {
        "task_id": task_id,
        "manifest": manifest,
        "deliverables": deliverables,
        "paper_assets_manifest": assets_manifest,
        "generated_at": manifest.get("generated_at") if isinstance(manifest, dict) else None,
        "artifact_set_id": manifest.get("artifact_set_id") if isinstance(manifest, dict) else None,
    }
