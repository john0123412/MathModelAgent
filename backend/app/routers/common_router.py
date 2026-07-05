"""通用路由模块，提供配置查询、消息获取和健康检查等接口。"""

import json
import os
from pathlib import Path
from datetime import datetime

from aiofile import async_open
from fastapi import APIRouter, HTTPException
from app.config.setting import settings
from app.utils.common_utils import WORK_DIR_ROOT, ensure_safe_task_id, get_config_template
from app.schemas.enums import CompTemplate
from app.services.redis_manager import redis_manager
from app.services.task_status import read_task_status
from app.utils.log_util import logger

router = APIRouter()


def _require_safe_task_id(task_id: str) -> str:
    """验证并返回安全的任务 ID。

    Args:
        task_id: 待验证的任务 ID。

    Returns:
        验证通过的任务 ID。

    Raises:
        HTTPException: 任务 ID 非法时返回 400。
    """
    try:
        return ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法任务ID") from exc


async def _load_task_messages_from_file(task_id: str) -> list[dict]:
    """从文件加载指定任务的历史消息。

    Args:
        task_id: 任务 ID。

    Returns:
        消息列表，文件不存在时返回空列表。
    """
    safe_task_id = _require_safe_task_id(task_id)
    message_file = Path("logs/messages") / f"{safe_task_id}.json"
    jsonl_file = Path("logs/messages") / f"{safe_task_id}.jsonl"
    if not message_file.exists():
        return _load_task_messages_from_jsonl(jsonl_file)

    try:
        async with async_open(message_file, "r", encoding="utf-8") as f:
            content = await f.read()
            data = json.loads(content)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.error(f"读取任务消息文件失败: {str(e)}")
        return _load_task_messages_from_jsonl(jsonl_file)


def _load_task_messages_from_jsonl(message_file: Path) -> list[dict]:
    """从 JSONL fallback 文件读取历史消息。"""
    if not message_file.exists():
        return []
    messages: list[dict] = []
    try:
        with open(message_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if isinstance(data, dict):
                    messages.append(data)
    except Exception as e:
        logger.error(f"读取任务 JSONL 消息失败: {str(e)}")
    return messages


def _file_has_content(path: str) -> bool:
    """判断文件存在且非空。"""
    return os.path.isfile(path) and os.path.getsize(path) > 0


@router.get("/")
async def root():
    return {"message": "Hello World"}


@router.get("/config")
async def config():
    return {
        "environment": settings.ENV,
        "deepseek_model": settings.DEEPSEEK_MODEL,
        "deepseek_base_url": settings.DEEPSEEK_BASE_URL,
        "max_chat_turns": settings.MAX_CHAT_TURNS,
        "max_retries": settings.MAX_RETRIES,
        "CORS_ALLOW_ORIGINS": settings.CORS_ALLOW_ORIGINS,
    }


@router.get("/writer_seque")
async def get_writer_seque():
    # 返回论文顺序
    config_template: dict = get_config_template(CompTemplate.CHINA)
    return list(config_template.keys())


@router.get("/messages")
async def get_task_messages(task_id: str):
    return await _load_task_messages_from_file(task_id)


@router.get("/track")
async def track(task_id: str):
    # 获取任务的token使用情况

    pass


@router.get("/status")
async def get_service_status():
    """获取后端和 Redis 的运行状态。"""
    status = {
        "backend": {"status": "running", "message": "Backend service is running"},
        "redis": {"status": "unknown", "message": "Redis connection status unknown"}
    }

    # 检查Redis连接状态
    try:
        redis_client = await redis_manager.get_client()
        await redis_client.ping()  # type: ignore[reportGeneralTypeIssues]
        status["redis"] = {"status": "running", "message": "Redis connection is healthy"}
    except Exception as e:
        logger.error(f"Redis connection failed: {str(e)}")
        status["redis"] = {"status": "error", "message": f"Redis connection failed: {str(e)}"}

    return status


@router.get("/tasks")
async def list_tasks():
    """列出所有历史任务，按时间倒序排列。"""
    work_dir = WORK_DIR_ROOT
    if not os.path.exists(work_dir):
        return []

    tasks = []
    for task_id in os.listdir(work_dir):
        task_path = os.path.join(work_dir, task_id)
        if not os.path.isdir(task_path):
            continue

        # 检查各结果文件是否存在
        files_exist = {
            "res_md": _file_has_content(os.path.join(task_path, "res.md")),
            "res_json": _file_has_content(os.path.join(task_path, "res.json")),
            "res_docx": _file_has_content(os.path.join(task_path, "res.docx")),
            "res_pdf": _file_has_content(os.path.join(task_path, "res.pdf")),
            "candidate_manifest": _file_has_content(
                os.path.join(task_path, "candidate_manifest.json")
            ),
            "checkpoint": os.path.exists(os.path.join(task_path, "checkpoint.json")),
            "task_status": os.path.exists(os.path.join(task_path, "task_status.json")),
        }

        # 获取任务信息
        task_info = {
            "task_id": task_id,
            "title": task_id,
            "status": "unknown",
            "created_at": "",
            "has_result": files_exist["res_md"] or files_exist["res_docx"],
            "has_pdf": files_exist["res_pdf"],
            "has_manifest": files_exist["candidate_manifest"],
            "has_checkpoint": files_exist["checkpoint"],
            "files": files_exist,
        }
        persisted_status = read_task_status(task_path)
        if persisted_status and isinstance(persisted_status.get("status"), str):
            task_info["status"] = persisted_status["status"]
        if task_info["has_result"] and task_info["status"] not in {
            "failed",
            "cancelled",
        }:
            task_info["status"] = "completed"

        # 从消息文件获取标题和状态
        msg_file = os.path.join("logs", "messages", f"{task_id}.json")
        if os.path.exists(msg_file):
            try:
                with open(msg_file, "r", encoding="utf-8") as f:
                    messages = json.load(f)
                if messages:
                    # 找第一条 agent 消息作为标题
                    for msg in messages:
                        if msg.get("msg_type") == "agent":
                            content = msg.get("content", "")
                            if content:
                                # 提取标题（取前50个字符）
                                title = content[:80].replace("\n", " ").strip()
                                if title.startswith("{"):
                                    try:
                                        data = json.loads(content)
                                        title = data.get("title", title)
                                    except Exception:
                                        pass
                                task_info["title"] = title
                                break

                    # 检查是否有"完成"状态，或"失败/停止"标记为对应状态
                    for msg in messages:
                        content = msg.get("content", "")
                        if msg.get("msg_type") != "system":
                            continue
                        # 只检查最终完成消息，避免中间步骤的"完成"误判
                        if content and "任务处理完成" in content:
                            task_info["status"] = "completed"
                        elif "失败" in content or "停止" in content:
                            if not task_info["has_result"]:
                                task_info["status"] = (
                                    "interrupted"
                                    if files_exist["checkpoint"]
                                    else "failed"
                                )

                    # 未完成且没有结果文件时，视为仍在运行；若存在检查点，
                    # 说明进程曾中断过，标记为可续传的 "interrupted"
                    if (
                        not task_info["has_result"]
                        and task_info["status"]
                        not in {
                            "completed",
                            "failed",
                            "cancelled",
                            "running",
                            "resuming",
                            "waiting_review",
                        }
                    ):
                        task_info["status"] = (
                            "interrupted" if files_exist["checkpoint"] else "running"
                        )

                    # 获取创建时间（第一条消息的时间）
                    task_info["created_at"] = messages[0].get("id", "")[:19]
            except Exception as e:
                logger.error(f"读取任务消息失败: {task_id}, {e}")

        # 从目录修改时间获取创建时间
        try:
            mtime = os.path.getmtime(task_path)
            dt = datetime.fromtimestamp(mtime)
            task_info["created_at"] = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

        tasks.append(task_info)

    # 按创建时间倒序排列
    tasks.sort(key=lambda x: x["created_at"], reverse=True)
    return tasks
