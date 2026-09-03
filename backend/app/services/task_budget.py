"""Task-level budget contract (roadmap batch C).

Supplements existing token_usage, MAX_TOKENS, retry caps with a durable
per-task budget: provider calls, known tokens, runtime, subtask time, repairs.

- Budget file is work_dir/task_budget.json, persisted atomically.
- Resume inherits the ledger; it never resets on restart.
- Unknown usage is marked unknown, never reported as zero cost.
- Outer Agent vs backend provider costs are separate; this ledger is backend only.
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from app.utils.log_util import logger

BUDGET_FILENAME = "task_budget.json"
DEFAULT_LIMITS: dict[str, Any] = {
    "max_provider_calls": 200,
    "max_known_tokens": 500_000,
    "max_runtime_seconds": 18_000,  # 5h
    "max_subtask_seconds": 900,
    "max_repairs": 2,
}


def _budget_path(work_dir: str) -> Path:
    return Path(work_dir) / BUDGET_FILENAME


def _now_iso() -> str:
    return datetime.datetime.now().isoformat()


def _load_or_init(work_dir: str, task_id: str) -> dict[str, Any]:
    p = _budget_path(work_dir)
    if p.is_file():
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("task_id") == task_id:
                # Ensure required keys
                data.setdefault("limits", dict(DEFAULT_LIMITS))
                data.setdefault("usage", {"provider_calls": 0, "known_tokens": 0, "unknown_calls": 0, "runtime_seconds": 0})
                data.setdefault("created_at", _now_iso())
                return data
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"读取预算失败，将重建: {type(exc).__name__}")
    # Init new
    data: dict[str, Any] = {
        "task_id": task_id,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "limits": dict(DEFAULT_LIMITS),
        "usage": {"provider_calls": 0, "known_tokens": 0, "unknown_calls": 0, "runtime_seconds": 0, "unknown_token_calls": 0},
        "history": [],
        "unknown_usage_events": 0,
    }
    _save_atomic(p, data)
    return data


def _save_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=BUDGET_FILENAME + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def init_budget(work_dir: str, task_id: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Initialize or load budget, applying overrides without resetting usage."""
    data = _load_or_init(work_dir, task_id)
    if overrides:
        for k, v in overrides.items():
            if k in DEFAULT_LIMITS and isinstance(v, int) and v > 0:
                data["limits"][k] = v
        data["updated_at"] = _now_iso()
        _save_atomic(_budget_path(work_dir), data)
    return data


def load_budget(work_dir: str) -> dict[str, Any] | None:
    p = _budget_path(work_dir)
    if not p.is_file():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def check_budget_before_call(work_dir: str, task_id: str) -> tuple[bool, str | None]:
    """Return (allowed, reason). Call before each provider invocation."""
    data = _load_or_init(work_dir, task_id)
    limits = data.get("limits", {})
    usage = data.get("usage", {})
    calls = int(usage.get("provider_calls", 0))
    known = int(usage.get("known_tokens", 0))
    runtime = float(usage.get("runtime_seconds", 0))

    if calls >= int(limits.get("max_provider_calls", 200)):
        return False, f"已达提供商调用上限 {limits.get('max_provider_calls')} 次"
    if known >= int(limits.get("max_known_tokens", 500_000)):
        return False, f"已达累计 token 上限 {limits.get('max_known_tokens')}"
    if runtime >= float(limits.get("max_runtime_seconds", 18_000)):
        return False, f"已达任务运行时间上限 {limits.get('max_runtime_seconds')}s"
    return True, None


def record_provider_call(
    work_dir: str,
    task_id: str,
    known_tokens: int | None,
    duration_seconds: float | None = None,
) -> dict[str, Any]:
    """Record one provider call; known_tokens=None means unknown usage."""
    data = _load_or_init(work_dir, task_id)
    usage = data.setdefault("usage", {"provider_calls": 0, "known_tokens": 0, "unknown_calls": 0, "runtime_seconds": 0})
    usage["provider_calls"] = int(usage.get("provider_calls", 0)) + 1
    if known_tokens is None:
        usage["unknown_calls"] = int(usage.get("unknown_calls", 0)) + 1
        data["unknown_usage_events"] = int(data.get("unknown_usage_events", 0)) + 1
    else:
        usage["known_tokens"] = int(usage.get("known_tokens", 0)) + int(known_tokens)
    if duration_seconds is not None:
        usage["runtime_seconds"] = float(usage.get("runtime_seconds", 0)) + float(duration_seconds)
    # Append history
    history = data.setdefault("history", [])
    history.append(
        {
            "at": _now_iso(),
            "known_tokens": known_tokens,
            "duration_seconds": duration_seconds,
            "unknown": known_tokens is None,
        }
    )
    # Keep last 200
    if len(history) > 200:
        data["history"] = history[-200:]
    data["updated_at"] = _now_iso()
    _save_atomic(_budget_path(work_dir), data)
    return data


def get_budget_summary(work_dir: str, task_id: str) -> dict[str, Any]:
    data = _load_or_init(work_dir, task_id)
    return {
        "limits": data.get("limits", {}),
        "usage": data.get("usage", {}),
        "updated_at": data.get("updated_at"),
        "unknown_usage_events": data.get("unknown_usage_events", 0),
    }
