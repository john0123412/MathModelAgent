"""Token usage 聚合记录服务。"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
import threading
from typing import Any

from app.core.llm.types import Usage
from app.utils import common_utils

USAGE_REPORT_FILENAME = "token_usage.json"
_VERSION = 1
_LOCK = threading.Lock()


def _empty_totals() -> dict[str, int]:
    return {
        "chat_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


def _empty_report(task_id: str, usage_available: bool = False) -> dict[str, Any]:
    return {
        "version": _VERSION,
        "task_id": task_id,
        "usage_available": usage_available,
        "estimated": True,
        "updated_at": None,
        "agents": {},
        "totals": _empty_totals(),
    }


def _usage_path(task_id: str) -> str:
    work_dir = common_utils.get_work_dir(task_id)
    return os.path.join(work_dir, USAGE_REPORT_FILENAME)


def _load_existing(path: str, task_id: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return _empty_report(task_id)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("token_usage.json 格式错误")
    agents = data.get("agents")
    totals = data.get("totals")
    if not isinstance(agents, dict) or not isinstance(totals, dict):
        raise ValueError("token_usage.json 格式错误")
    data.setdefault("version", _VERSION)
    data.setdefault("task_id", task_id)
    data.setdefault("usage_available", True)
    data.setdefault("estimated", True)
    data.setdefault("updated_at", None)
    return data


def _write_atomic(path: str, data: dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    fd, temp_path = tempfile.mkstemp(
        prefix=f"{USAGE_REPORT_FILENAME}.",
        suffix=".tmp",
        dir=directory,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def _normalize_usage_value(value: int | None) -> int:
    if value is None:
        return 0
    return max(0, int(value))


def _normalize_agent_name(agent_name: str) -> str:
    return str(getattr(agent_name, "value", agent_name) or "UnknownAgent")


def record_token_usage(
    task_id: str,
    agent_name: str,
    model: str | None,
    usage: Usage | None,
) -> None:
    """记录一次 LLM 调用的 token usage，只保存聚合数字。"""
    if not task_id or usage is None:
        return
    safe_task_id = common_utils.ensure_safe_task_id(task_id)
    prompt_tokens = _normalize_usage_value(usage.prompt_tokens)
    completion_tokens = _normalize_usage_value(usage.completion_tokens)
    total_tokens = prompt_tokens + completion_tokens
    if total_tokens == 0:
        return

    with _LOCK:
        path = _usage_path(safe_task_id)
        data = _load_existing(path, safe_task_id)
        agents = data.setdefault("agents", {})
        agent_key = _normalize_agent_name(agent_name)
        agent_usage = agents.setdefault(
            agent_key,
            {
                "model": model or "",
                "chat_count": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        )
        agent_usage["model"] = model or agent_usage.get("model", "")
        agent_usage["chat_count"] += 1
        agent_usage["prompt_tokens"] += prompt_tokens
        agent_usage["completion_tokens"] += completion_tokens
        agent_usage["total_tokens"] += total_tokens

        totals = data.setdefault("totals", _empty_totals())
        totals["chat_count"] += 1
        totals["prompt_tokens"] += prompt_tokens
        totals["completion_tokens"] += completion_tokens
        totals["total_tokens"] += total_tokens

        data["usage_available"] = True
        data["estimated"] = True
        data["updated_at"] = datetime.datetime.now().isoformat()
        _write_atomic(path, data)


def read_token_usage(task_id: str) -> dict[str, Any]:
    """读取任务 token usage；无文件时返回空统计。"""
    safe_task_id = common_utils.ensure_safe_task_id(task_id)
    path = _usage_path(safe_task_id)
    try:
        data = _load_existing(path, safe_task_id)
    except json.JSONDecodeError as exc:
        raise ValueError("token_usage.json 格式错误") from exc
    if not os.path.exists(path):
        return _empty_report(safe_task_id)
    data["usage_available"] = True
    data["estimated"] = True
    return data
