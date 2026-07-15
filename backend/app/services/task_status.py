"""任务状态持久化模块。"""

import datetime
import json
import os
from typing import Literal

from app.utils.common_utils import WORK_DIR_ROOT, get_work_dir
from app.utils.log_util import logger

TaskStatus = Literal[
    "pending",
    "running",
    "waiting_review",
    "resuming",
    "finalizing",
    "interrupted",
    "failed",
    "completed",
    "cancelled",
]

STATUS_FILENAME = "task_status.json"
STALE_ACTIVE_STATUSES = {"running", "resuming", "finalizing"}


def _write_task_status_to_dir(
    work_dir: str,
    task_id: str,
    status: TaskStatus,
    message: str,
) -> None:
    status_path = os.path.join(work_dir, STATUS_FILENAME)
    tmp_path = status_path + ".tmp"
    payload = {
        "task_id": task_id,
        "status": status,
        "message": message,
        "updated_at": datetime.datetime.now().isoformat(),
    }
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, status_path)


def write_task_status(
    task_id: str,
    status: TaskStatus,
    message: str = "",
) -> None:
    """写入任务状态文件，失败时只记录日志不影响主流程。"""
    try:
        work_dir = get_work_dir(task_id)
        _write_task_status_to_dir(work_dir, task_id, status, message)
    except Exception as e:
        logger.warning(f"写入任务状态失败: {task_id}, {type(e).__name__}")


def read_task_status(work_dir: str) -> dict | None:
    """读取任务状态文件。"""
    status_path = os.path.join(work_dir, STATUS_FILENAME)
    if not os.path.exists(status_path):
        return None
    try:
        with open(status_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning(f"读取任务状态失败: {status_path}, {type(e).__name__}")
        return None


def recover_stale_task_statuses(work_dir_root: str | None = None) -> list[str]:
    """Mark tasks left active by a previous backend process as resumable.

    Background asyncio tasks cannot survive a backend restart.  Leaving their
    old `running` state in place blocks the resume UI indefinitely, so the
    next process records an explicit interruption while preserving checkpoints.
    """
    root = os.path.abspath(work_dir_root or WORK_DIR_ROOT)
    if not os.path.isdir(root):
        return []
    recovered: list[str] = []
    for task_id in sorted(os.listdir(root)):
        work_dir = os.path.join(root, task_id)
        if not os.path.isdir(work_dir):
            continue
        payload = read_task_status(work_dir)
        if not isinstance(payload, dict) or payload.get("status") not in STALE_ACTIVE_STATUSES:
            continue
        try:
            _write_task_status_to_dir(
                work_dir,
                task_id,
                "interrupted",
                "后端进程重启，原运行任务已中断；可从检查点继续。",
            )
            recovered.append(task_id)
        except OSError as exc:
            logger.warning("恢复遗留任务状态失败: {}, {}", task_id, type(exc).__name__)
    return recovered
