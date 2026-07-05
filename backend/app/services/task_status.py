"""任务状态持久化模块。"""

import datetime
import json
import os
from typing import Literal

from app.utils.common_utils import get_work_dir
from app.utils.log_util import logger

TaskStatus = Literal[
    "pending",
    "running",
    "waiting_review",
    "resuming",
    "interrupted",
    "failed",
    "completed",
    "cancelled",
]

STATUS_FILENAME = "task_status.json"


def write_task_status(
    task_id: str,
    status: TaskStatus,
    message: str = "",
) -> None:
    """写入任务状态文件，失败时只记录日志不影响主流程。"""
    try:
        work_dir = get_work_dir(task_id)
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
    except Exception as e:
        logger.warning(f"写入任务状态失败: {task_id}, {e}")


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
        logger.warning(f"读取任务状态失败: {status_path}, {e}")
        return None
