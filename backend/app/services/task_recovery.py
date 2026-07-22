"""Durable inputs used to restart a task that failed before checkpoint creation."""

import json
import os
from typing import Any

from app.utils.log_util import logger


REQUEST_SNAPSHOT_FILENAME = "task_request.json"
_REQUEST_FIELDS = (
    "task_id",
    "ques_all",
    "comp_template",
    "format_output",
    "export_profile",
)
_OPTIONAL_BOOLEAN_FIELDS = ("require_model_review",)


def write_task_request_snapshot(work_dir: str, payload: dict[str, Any]) -> str:
    """Atomically persist the non-secret task request before LLM planning starts."""
    snapshot = {key: payload.get(key) for key in _REQUEST_FIELDS}
    if not all(isinstance(snapshot.get(key), str) and snapshot[key] for key in _REQUEST_FIELDS):
        raise ValueError("任务请求快照缺少必要字段")
    for key in _OPTIONAL_BOOLEAN_FIELDS:
        if key not in payload:
            continue
        value = payload[key]
        if not isinstance(value, bool):
            raise ValueError(f"任务请求快照字段类型错误: {key}")
        snapshot[key] = value

    path = os.path.join(work_dir, REQUEST_SNAPSHOT_FILENAME)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
    return path


def load_task_request_snapshot(work_dir: str) -> dict[str, Any] | None:
    """Return a validated restart request, or None for absent/invalid legacy tasks."""
    path = os.path.join(work_dir, REQUEST_SNAPSHOT_FILENAME)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            return None
        snapshot = {key: payload.get(key) for key in _REQUEST_FIELDS}
        if not all(isinstance(snapshot.get(key), str) and snapshot[key] for key in _REQUEST_FIELDS):
            logger.warning("任务请求快照字段不完整: {}", path)
            return None
        for key in _OPTIONAL_BOOLEAN_FIELDS:
            if key not in payload:
                continue
            value = payload[key]
            if not isinstance(value, bool):
                logger.warning("任务请求快照字段类型错误: {}, {}", path, key)
                return None
            snapshot[key] = value
        return snapshot
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取任务请求快照失败: {}, {}", path, type(exc).__name__)
        return None
