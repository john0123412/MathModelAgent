"""通用路由模块，提供配置查询、消息获取和健康检查等接口。"""

import json
import os
import subprocess
from pathlib import Path
from datetime import datetime

from aiofile import async_open
from fastapi import APIRouter, HTTPException
from app.config.setting import settings
from app.utils.common_utils import WORK_DIR_ROOT, ensure_safe_task_id, get_config_template
from app.schemas.enums import CompTemplate
from app.services.redis_manager import redis_manager
from app.services.task_status import read_task_status
from app.services.token_usage import read_token_usage
from app.tools.interpreter_factory import get_code_execution_status
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
        logger.error(f"读取任务消息文件失败: {type(e).__name__}")
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
        logger.error(f"读取任务 JSONL 消息失败: {type(e).__name__}")
    return messages


def _file_has_content(path: str) -> bool:
    """判断文件存在且非空。"""
    return os.path.isfile(path) and os.path.getsize(path) > 0


def _feature_guardrail_warnings() -> list[dict[str, str]]:
    """返回配置存在但主工作流尚未接入的功能警告。"""
    warnings: list[dict[str, str]] = []
    if settings.RAG_ENABLED:
        warnings.append(
            {
                "feature": "RAG_ENABLED",
                "status": "config_only",
                "message": "RAG 配置已启用，但 ChromaDB/Rerank 检索尚未接入主工作流。",
            }
        )
    if settings.HIL_ENABLED:
        warnings.append(
            {
                "feature": "HIL_ENABLED",
                "status": "config_only",
                "message": "通用 HIL 配置尚未接入主工作流；当前可用的是 HUMAN_MODEL_GATE_ENABLED 建模方案门禁。",
            }
        )
    if getattr(settings, "FALLBACK_ENABLED", False):
        warnings.append(
            {
                "feature": "FALLBACK_ENABLED",
                "status": "config_only",
                "message": "Fallback Hand Off 尚未接入主工作流；当前只有基础重试和错误反思。",
            }
        )
    if getattr(settings, "EVALUATOR_ENABLED", False):
        warnings.append(
            {
                "feature": "EVALUATOR_ENABLED",
                "status": "config_only",
                "message": "Evaluator/Feedback Rerun 尚未接入主工作流。",
            }
        )
    return warnings


def _get_deployment_info() -> dict:
    """返回 Agent 可读的部署信息（不含凭据）。"""
    info: dict = {
        "source_mounted": False,
        "git_commit": None,
        "git_dirty": None,
        "capability_version": "2026-09-03-roadmap-A",
    }
    # 源码是否通过 volume 挂载（开发模式）
    try:
        # backend/app 挂载时，宿主机 .git 往往不在容器内；通过检查 /app/app 是否为挂载点近似判断
        info["source_mounted"] = os.path.ismount("/app/app") or os.path.exists("/app/app/.git") or os.path.exists("/app/.git")
        if not info["source_mounted"] and not os.path.exists("/app/.mma-image-baked"):
            # 宿主机开发挂载时，WORK_DIR 通常也是挂载。稳定部署（代码在镜像里）
            # 会写 /app/.mma-image-baked 标记：此时 work_dir 挂载不代表源码挂载，
            # 只有 /app/app 真被挂载（个别调试场景）才报 true。
            info["source_mounted"] = os.path.ismount("/app/project/work_dir")
    except Exception:
        pass
    # git 信息（尽量不依赖 git 二进制，优先读环境变量）
    env_commit = os.getenv("GIT_COMMIT") or os.getenv("MMA_GIT_COMMIT")
    if env_commit:
        info["git_commit"] = env_commit[:40]
        # dirty 由外部注入 MMA_GIT_DIRTY 显式标记，否则未知
        dirty_env = os.getenv("MMA_GIT_DIRTY")
        if dirty_env is not None:
            info["git_dirty"] = dirty_env.lower() in ("1", "true", "dirty")
        return info
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, timeout=2
        ).decode().strip()
        info["git_commit"] = commit
        try:
            porcelain = subprocess.check_output(
                ["git", "status", "--porcelain"], stderr=subprocess.DEVNULL, timeout=2
            ).decode().strip()
            info["git_dirty"] = bool(porcelain)
        except Exception:
            info["git_dirty"] = None
    except Exception:
        # 容器内无 git 或非 git 目录，保留 None 避免误报可复现
        pass
    # 镜像标识（若构建时注入）
    image_tag = os.getenv("MMA_IMAGE_TAG") or os.getenv("IMAGE_TAG")
    if image_tag:
        info["image_tag"] = image_tag
    return info


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
        "deployment": _get_deployment_info(),
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
    """获取任务的 token 使用聚合统计。"""
    safe_task_id = _require_safe_task_id(task_id)
    try:
        return read_token_usage(safe_task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/status")
async def get_service_status():
    """获取后端、Redis 和代码执行后端的运行状态。"""
    status = {
        "backend": {
            "status": "running",
            "message": "Backend service is running",
            "feature_warnings": _feature_guardrail_warnings(),
        },
        "redis": {"status": "unknown", "message": "Redis connection status unknown"},
        "code_execution": get_code_execution_status(),
        "deployment": _get_deployment_info(),
    }

    # 检查Redis连接状态
    try:
        redis_client = await redis_manager.get_client()
        await redis_client.ping()  # type: ignore[reportGeneralTypeIssues]
        status["redis"] = {"status": "running", "message": "Redis connection is healthy"}
    except Exception as e:
        logger.error(f"Redis connection failed: {type(e).__name__}")
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
        has_persisted_status = bool(
            persisted_status and isinstance(persisted_status.get("status"), str)
        )
        if has_persisted_status:
            # Persisted workflow/finalization state is authoritative. Merely
            # finding an old res.md or res.docx must not turn failed/finalizing
            # tasks back into completed.
            task_info["status"] = persisted_status["status"]

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
                                    except Exception as exc:
                                        logger.debug(
                                            f"任务标题 JSON 解析失败，保留原始标题: {exc}"
                                        )
                                task_info["title"] = title
                                break

                    # 检查是否有"完成"状态，或"失败/停止"标记为对应状态
                    for msg in messages:
                        content = msg.get("content", "")
                        if msg.get("msg_type") != "system":
                            continue
                        # 只检查最终完成消息，避免中间步骤的"完成"误判
                        if (
                            not has_persisted_status
                            and content
                            and "任务处理完成" in content
                        ):
                            task_info["status"] = "completed"
                        elif (
                            not has_persisted_status
                            and ("失败" in content or "停止" in content)
                        ):
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
                        and not has_persisted_status
                        and task_info["status"]
                        not in {
                            "completed",
                            "failed",
                            "cancelled",
                            "running",
                            "resuming",
                            "revising",
                            "waiting_quality_review",
                            "waiting_review",
                            "finalizing",
                        }
                    ):
                        task_info["status"] = (
                            "interrupted" if files_exist["checkpoint"] else "running"
                        )

                    # 获取创建时间（第一条消息的时间）
                    task_info["created_at"] = messages[0].get("id", "")[:19]
            except Exception as e:
                logger.error(f"读取任务消息失败: {task_id}, {type(e).__name__}")

        # 从目录修改时间获取创建时间
        try:
            mtime = os.path.getmtime(task_path)
            dt = datetime.fromtimestamp(mtime)
            task_info["created_at"] = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as exc:
            logger.debug(
                f"读取任务目录修改时间失败: {task_id}, {type(exc).__name__}"
            )

        tasks.append(task_info)

    # 按创建时间倒序排列
    tasks.sort(key=lambda x: x["created_at"], reverse=True)
    return tasks


@router.get("/tasks/{task_id}")
async def get_single_task(task_id: str):
    """Roadmap B-2: 单任务状态（不扫描全部历史目录）。"""
    from app.services.agent_operations import get_single_task_status

    safe_task_id = _require_safe_task_id(task_id)
    try:
        return get_single_task_status(safe_task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tasks/{task_id}/events")
async def get_task_events(task_id: str, after: str | None = None, limit: int = 50):
    """Roadmap B-2: 消息游标（稳定序号，仅增量）。"""
    from app.services.agent_operations import get_task_events as _get_events

    safe_task_id = _require_safe_task_id(task_id)
    try:
        return _get_events(safe_task_id, after=after, limit=limit)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tasks/{task_id}/artifacts")
async def get_task_artifacts(task_id: str):
    """Roadmap B-2: 产物清单（复用 manifest + 哈希）。"""
    from app.services.agent_operations import get_task_artifacts as _get_artifacts

    safe_task_id = _require_safe_task_id(task_id)
    try:
        return _get_artifacts(safe_task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tasks/{task_id}/review/packet")
async def get_review_packet(task_id: str):
    """Roadmap D: 组装六维评审材料包（外层 Agent 审阅用）。"""
    from app.services.paper_review import assemble_review_packet

    safe_task_id = _require_safe_task_id(task_id)
    try:
        return assemble_review_packet(safe_task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tasks/{task_id}/review")
async def get_review(task_id: str):
    """Roadmap D: 读取已保存的六维评审（含过期判定）。"""
    from app.services.paper_review import load_review

    safe_task_id = _require_safe_task_id(task_id)
    data = load_review(safe_task_id)
    if data is None:
        raise HTTPException(status_code=404, detail="未找到评审")
    return data


@router.post("/tasks/{task_id}/review")
async def post_review(task_id: str, payload: dict):
    """Roadmap D: 保存外层 Agent 的六维评审（结构化校验+版本绑定）。"""
    from app.services.paper_review import save_review

    safe_task_id = _require_safe_task_id(task_id)
    try:
        # Ensure work_dir exists
        from app.utils.common_utils import get_work_dir

        get_work_dir(safe_task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        save_review(safe_task_id, payload)
        return {"task_id": safe_task_id, "status": "saved", "review": payload}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/doctor")
async def get_doctor():
    """Roadmap E: 容器能力体检（与宿主机 doctor 分离）。"""
    from app.services.doctor import container_doctor, template_capabilities

    return {"container": container_doctor(), "templates": template_capabilities()}


@router.get("/templates/capabilities")
async def get_template_capabilities():
    """Roadmap E: 模板能力表（后端 profile vs skill 模板）。"""
    from app.services.doctor import template_capabilities

    return template_capabilities()


@router.post("/tasks/{task_id}/figure-plan")
async def post_figure_plan(task_id: str, payload: dict):
    """Roadmap E: 创建/更新配图计划（路由+追溯）。"""
    from app.services.figure_plan import create_figure_plan

    safe_task_id = _require_safe_task_id(task_id)
    try:
        from app.utils.common_utils import get_work_dir

        get_work_dir(safe_task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    figures = payload.get("figures")
    if not isinstance(figures, list):
        raise HTTPException(status_code=422, detail="figures 必须为数组")
    try:
        plan = create_figure_plan(safe_task_id, figures)
        return plan
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/tasks/{task_id}/figure-plan")
async def get_figure_plan(task_id: str):
    """Roadmap E: 读取配图计划。"""
    from app.services.figure_plan import load_figure_plan

    safe_task_id = _require_safe_task_id(task_id)
    try:
        from app.utils.common_utils import get_work_dir

        get_work_dir(safe_task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    plan = load_figure_plan(safe_task_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="未找到 figure plan")
    return plan


@router.get("/tasks/{task_id}/figure-plan/validate")
async def validate_figure_plan(task_id: str):
    """Roadmap E: 校验配图产物与数据追溯。"""
    from app.services.figure_plan import validate_figure_artifacts

    safe_task_id = _require_safe_task_id(task_id)
    try:
        from app.utils.common_utils import get_work_dir

        get_work_dir(safe_task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return validate_figure_artifacts(safe_task_id)
