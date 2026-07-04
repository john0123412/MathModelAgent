"""建模任务路由模块，提供任务创建、API 验证和配置管理等接口。"""

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile
from app.core.checkpoint import CheckpointManager
from app.core.workflow import MathModelWorkFlow
from app.schemas.enums import CompTemplate, ExportProfile, FormatOutPut
from app.utils.log_util import logger
from app.services.redis_manager import redis_manager
from app.services import user_input_queue
from app.services.task_status import write_task_status
from app.schemas.request import Problem
from app.schemas.response import SystemMessage
from app.utils.common_utils import (
    create_task_id,
    create_work_dir,
    ensure_safe_filename,
    ensure_safe_task_id,
    get_current_files,
    get_work_dir,
    md_2_docx,
    safe_join_work_dir,
)
from app.tools.candidate_exporter import write_candidate_manifest
import os
import asyncio
import shutil
from typing import Dict, Tuple
from fastapi import HTTPException
from icecream import ic  # type: ignore[import-unresolved]
from app.schemas.request import ExampleRequest
from pydantic import BaseModel
from app.config.setting import settings, ApiType
from app.core.llm.providers.openai_chat import OpenAIChatProvider
from app.core.llm.providers.openai_responses import OpenAIResponsesProvider
from app.core.llm.providers.anthropic import AnthropicProvider
from app.core.llm.providers.base import BaseProvider
import requests

router = APIRouter()
EXAMPLE_ROOT = os.path.abspath(os.path.join("app", "example", "example"))

# 任务注册表: task_id -> (asyncio.Task, asyncio.Event)
_active_tasks: Dict[str, Tuple[asyncio.Task, asyncio.Event]] = {}


def _finalize_docx_and_manifest(
    task_id: str,
    export_profile: ExportProfile | str | None = ExportProfile.DEFAULT,
) -> None:
    """生成 DOCX 后刷新候选清单，确保 manifest 反映最终产物。"""
    md_2_docx(task_id, export_profile=export_profile)
    write_candidate_manifest(get_work_dir(task_id), task_id)


class ValidateApiKeyRequest(BaseModel):
    api_key: str
    base_url: str = "https://api.openai.com/v1"
    model_id: str
    api_type: str = "openai-chat"


class ValidateOpenalexEmailRequest(BaseModel):
    email: str


class ValidateOpenalexEmailResponse(BaseModel):
    valid: bool
    message: str


class ValidateApiKeyResponse(BaseModel):
    valid: bool
    message: str


class SaveApiConfigRequest(BaseModel):
    coordinator: dict
    modeler: dict
    coder: dict
    writer: dict
    openalex_email: str


def _require_safe_task_id(task_id: str) -> str:
    """验证 URL 中的任务 ID，非法时返回 400。"""
    try:
        return ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法任务ID") from exc


def _resolve_example_dir(source: str) -> str:
    """根据示例目录名解析示例路径，拒绝路径遍历。"""
    try:
        safe_source = ensure_safe_filename(source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法示例名称") from exc

    example_dir = os.path.abspath(os.path.join(EXAMPLE_ROOT, safe_source))
    if os.path.commonpath([EXAMPLE_ROOT, example_dir]) != EXAMPLE_ROOT:
        raise HTTPException(status_code=400, detail="非法示例名称")
    if not os.path.isdir(example_dir):
        raise HTTPException(status_code=404, detail="示例不存在")
    return example_dir


@router.post("/save-api-config")
async def save_api_config(request: SaveApiConfigRequest):
    """
    保存验证成功的 API 配置到 settings
    """
    try:
        # 更新各个模块的设置：仅当字段非空时才覆盖，空字段保留 .env.dev 中
        # 已加载的默认配置，避免前端未填写时把可用的 key 覆盖成空字符串
        if request.coordinator:
            if api_key := request.coordinator.get("apiKey"):
                settings.COORDINATOR_API_KEY = api_key
            if model_id := request.coordinator.get("modelId"):
                settings.COORDINATOR_MODEL = model_id
            if base_url := request.coordinator.get("baseUrl"):
                settings.COORDINATOR_BASE_URL = base_url
            if api_type := request.coordinator.get("apiType"):
                settings.COORDINATOR_API_TYPE = api_type
            if cw := request.coordinator.get("contextWindow"):
                settings.COORDINATOR_CONTEXT_WINDOW = int(cw)

        if request.modeler:
            if api_key := request.modeler.get("apiKey"):
                settings.MODELER_API_KEY = api_key
            if model_id := request.modeler.get("modelId"):
                settings.MODELER_MODEL = model_id
            if base_url := request.modeler.get("baseUrl"):
                settings.MODELER_BASE_URL = base_url
            if api_type := request.modeler.get("apiType"):
                settings.MODELER_API_TYPE = api_type
            if cw := request.modeler.get("contextWindow"):
                settings.MODELER_CONTEXT_WINDOW = int(cw)

        if request.coder:
            if api_key := request.coder.get("apiKey"):
                settings.CODER_API_KEY = api_key
            if model_id := request.coder.get("modelId"):
                settings.CODER_MODEL = model_id
            if base_url := request.coder.get("baseUrl"):
                settings.CODER_BASE_URL = base_url
            if api_type := request.coder.get("apiType"):
                settings.CODER_API_TYPE = api_type
            if cw := request.coder.get("contextWindow"):
                settings.CODER_CONTEXT_WINDOW = int(cw)

        if request.writer:
            if api_key := request.writer.get("apiKey"):
                settings.WRITER_API_KEY = api_key
            if model_id := request.writer.get("modelId"):
                settings.WRITER_MODEL = model_id
            if base_url := request.writer.get("baseUrl"):
                settings.WRITER_BASE_URL = base_url
            if api_type := request.writer.get("apiType"):
                settings.WRITER_API_TYPE = api_type
            if cw := request.writer.get("contextWindow"):
                settings.WRITER_CONTEXT_WINDOW = int(cw)

        if request.openalex_email:
            settings.OPENALEX_EMAIL = request.openalex_email

        return {"success": True, "message": "配置保存成功"}
    except Exception as e:
        logger.error(f"保存配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"保存配置失败: {str(e)}")


@router.post("/validate-api-key", response_model=ValidateApiKeyResponse)
async def validate_api_key(request: ValidateApiKeyRequest):
    """
    验证 API Key 的有效性
    """
    try:
        provider: BaseProvider
        match request.api_type:
            case ApiType.OPENAI_RESPONSES:
                provider = OpenAIResponsesProvider()
            case ApiType.ANTHROPIC:
                provider = AnthropicProvider()
            case _:
                provider = OpenAIChatProvider()

        await provider.call(
            messages=[{"role": "user", "content": "Hi"}],
            model=request.model_id,
            api_key=request.api_key,
            base_url=request.base_url
            if request.base_url != "https://api.openai.com/v1"
            else None,
            max_tokens=1,
        )

        return ValidateApiKeyResponse(valid=True, message="✓ 模型 API 验证成功")
    except Exception as e:
        error_msg = str(e)

        # 解析不同类型的错误
        if "401" in error_msg or "Unauthorized" in error_msg:
            return ValidateApiKeyResponse(valid=False, message="✗ API Key 无效或已过期")
        elif "404" in error_msg or "Not Found" in error_msg:
            return ValidateApiKeyResponse(
                valid=False, message="✗ 模型 ID 不存在或 Base URL 错误"
            )
        elif "429" in error_msg or "rate limit" in error_msg.lower():
            return ValidateApiKeyResponse(
                valid=False, message="✗ 请求过于频繁，请稍后再试"
            )
        elif "403" in error_msg or "Forbidden" in error_msg:
            return ValidateApiKeyResponse(
                valid=False, message="✗ API 权限不足或账户余额不足"
            )
        else:
            return ValidateApiKeyResponse(
                valid=False, message=f"✗ 验证失败: {error_msg[:50]}..."
            )


@router.post("/validate-openalex-email", response_model=ValidateOpenalexEmailResponse)
async def validate_openalex_email(request: ValidateOpenalexEmailRequest):
    """
    验证 OpenAlex Email 的有效性
    """
    try:
        params = {"mailto": request.email}
        if settings.OPENALEX_API_KEY:
            params["api_key"] = settings.OPENALEX_API_KEY

        response = requests.get(
            "https://api.openalex.org/works", params=params, timeout=10
        )
        logger.debug(f"OpenAlex Email 验证响应: {response}")
        response.raise_for_status()
        return ValidateOpenalexEmailResponse(
            valid=True, message="✓ OpenAlex Email 验证成功"
        )
    except Exception as e:
        return ValidateOpenalexEmailResponse(
            valid=False, message=f"✗ OpenAlex Email 验证失败: {str(e)}"
        )


@router.post("/example")
async def exampleModeling(
    example_request: ExampleRequest,
    background_tasks: BackgroundTasks,
):
    task_id = create_task_id()
    work_dir = create_work_dir(task_id)
    example_dir = _resolve_example_dir(example_request.source)
    ic(example_dir)
    with open(os.path.join(example_dir, "questions.txt"), "r", encoding="utf-8") as f:
        ques_all = f.read()

    current_files = get_current_files(example_dir, "data")
    for file in current_files:
        safe_filename = ensure_safe_filename(file)
        src_file = os.path.join(example_dir, file)
        dst_file = os.path.join(work_dir, safe_filename)
        shutil.copy2(src_file, dst_file)
    # 存储任务ID
    await redis_manager.set(f"task_id:{task_id}", task_id)

    logger.info(f"Adding background task for task_id: {task_id}")
    # 将任务添加到后台执行
    background_tasks.add_task(
        run_modeling_task_async,
        task_id,
        ques_all,
        CompTemplate.CHINA,
        FormatOutPut.Markdown,
        ExportProfile.DEFAULT,
    )
    return {"task_id": task_id, "status": "processing"}


@router.post("/modeling")
async def modeling(
    background_tasks: BackgroundTasks,
    ques_all: str = Form(...),  # 从表单获取
    comp_template: CompTemplate = Form(...),  # 从表单获取
    format_output: FormatOutPut = Form(...),  # 从表单获取
    export_profile: ExportProfile = Form(ExportProfile.DEFAULT),  # 从表单获取
    files: list[UploadFile] = File(default=None),
):
    task_id = create_task_id()
    work_dir = create_work_dir(task_id)

    # 如果有上传文件，保存文件
    if files:
        logger.info(f"开始处理上传的文件，工作目录: {work_dir}")
        for file in files:
            try:
                if not file.filename:
                    logger.warning("跳过空文件名")
                    continue
                safe_filename = ensure_safe_filename(file.filename)
                data_file_path = safe_join_work_dir(task_id, safe_filename)
                logger.info(f"保存文件: {safe_filename} -> {data_file_path}")

                content = await file.read()
                if not content:
                    logger.warning(f"文件 {safe_filename} 内容为空")
                    continue

                with open(data_file_path, "wb") as f:
                    f.write(content)
                logger.info(f"成功保存文件: {data_file_path}")

            except Exception as e:
                logger.error(f"保存文件 {file.filename} 失败: {str(e)}")
                raise HTTPException(
                    status_code=400, detail=f"保存文件 {file.filename} 失败: {str(e)}"
                )
    else:
        logger.warning("没有上传文件")

    # 存储任务ID
    await redis_manager.set(f"task_id:{task_id}", task_id)

    logger.info(f"Adding background task for task_id: {task_id}")
    # 将任务添加到后台执行
    background_tasks.add_task(
        run_modeling_task_async,
        task_id,
        ques_all,
        comp_template,
        format_output,
        export_profile,
    )
    return {"task_id": task_id, "status": "processing"}


async def run_modeling_task_async(
    task_id: str,
    ques_all: str,
    comp_template: CompTemplate,
    format_output: FormatOutPut,
    export_profile: ExportProfile = ExportProfile.DEFAULT,
):
    """异步执行建模任务。

    Args:
        task_id: 任务 ID。
        ques_all: 完整题目信息。
        comp_template: 竞赛模板类型。
        format_output: 输出格式。
    """
    logger.info(f"run modeling task for task_id: {task_id}")
    write_task_status(task_id, "running", "任务开始处理")

    problem = Problem(
        task_id=task_id,
        ques_all=ques_all,
        comp_template=comp_template,
        format_output=format_output,
        export_profile=export_profile,
    )

    # 创建取消信号
    cancel_event = asyncio.Event()

    # 发送任务开始状态
    await redis_manager.publish_message(
        task_id,
        SystemMessage(content="任务开始处理"),
    )

    # 给一个短暂的延迟，确保 WebSocket 有机会连接
    await asyncio.sleep(1)

    # 创建工作流并传入取消事件
    workflow = MathModelWorkFlow()
    workflow.cancel_event = cancel_event

    # 创建任务并注册到全局表
    task = asyncio.create_task(workflow.execute(problem))
    _active_tasks[task_id] = (task, cancel_event)

    task_completed = False
    try:
        # 设置超时时间（5 小时）
        await asyncio.wait_for(task, timeout=3600 * 5)
        task_completed = True

        # 发送任务完成状态
        await redis_manager.publish_message(
            task_id,
            SystemMessage(content="任务处理完成", type="success"),
        )
        write_task_status(task_id, "completed", "任务处理完成")
    except asyncio.CancelledError:
        logger.info(f"任务 {task_id} 被取消")
        await redis_manager.publish_message(
            task_id,
            SystemMessage(content="任务已停止", type="warning"),
        )
        write_task_status(task_id, "cancelled", "任务已停止")
    except Exception as e:
        logger.error(f"任务 {task_id} 执行失败: {e}")
        await redis_manager.publish_message(
            task_id,
            SystemMessage(content=f"任务执行失败: {str(e)}", type="error"),
        )
        write_task_status(task_id, "failed", str(e))
    finally:
        # 从注册表中清理
        _active_tasks.pop(task_id, None)
        user_input_queue.clear(task_id)
        # 仅在正常完成时转换 md 为 docx
        if task_completed:
            try:
                _finalize_docx_and_manifest(task_id, export_profile)
            except Exception as e:
                logger.error(f"任务 {task_id} DOCX 转换失败: {e}")
                await redis_manager.publish_message(
                    task_id,
                    SystemMessage(
                        content=f"DOCX 转换失败: {str(e)}，Markdown/PDF 结果不受影响",
                        type="warning",
                    ),
                )


class CancelTaskResponse(BaseModel):
    success: bool
    message: str


@router.post("/modeling/{task_id}/cancel", response_model=CancelTaskResponse)
async def cancel_task(task_id: str):
    """取消正在运行的任务。"""
    safe_task_id = _require_safe_task_id(task_id)
    if safe_task_id not in _active_tasks:
        return CancelTaskResponse(
            success=False,
            message="任务不存在或已完成",
        )

    _, cancel_event = _active_tasks[safe_task_id]
    cancel_event.set()
    logger.info(f"已发送取消信号给任务 {safe_task_id}")

    return CancelTaskResponse(
        success=True,
        message="停止指令已发送",
    )


class ResumeTaskResponse(BaseModel):
    task_id: str
    status: str


@router.post("/modeling/{task_id}/resume", response_model=ResumeTaskResponse)
async def resume_task(task_id: str, background_tasks: BackgroundTasks):
    """从检查点续传一个中断的建模任务。"""
    safe_task_id = _require_safe_task_id(task_id)
    try:
        work_dir = get_work_dir(safe_task_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在")

    checkpoint = CheckpointManager(work_dir).load()
    if checkpoint is None:
        raise HTTPException(status_code=404, detail="未找到可续传的检查点")

    if safe_task_id in _active_tasks:
        raise HTTPException(status_code=409, detail="任务仍在运行中")

    # 存储任务ID，续期供 ws 鉴权使用
    await redis_manager.set(f"task_id:{safe_task_id}", safe_task_id)

    logger.info(f"Adding resume background task for task_id: {safe_task_id}")
    background_tasks.add_task(run_resume_task_async, safe_task_id)
    return ResumeTaskResponse(task_id=safe_task_id, status="resuming")


async def run_resume_task_async(task_id: str):
    """异步执行任务续传。

    Args:
        task_id: 待续传的任务 ID。
    """
    logger.info(f"resume modeling task for task_id: {task_id}")
    write_task_status(task_id, "resuming", "任务续传中")

    # 创建取消信号
    cancel_event = asyncio.Event()

    await redis_manager.publish_message(
        task_id,
        SystemMessage(content="任务续传中..."),
    )

    # 给一个短暂的延迟，确保 WebSocket 有机会连接
    await asyncio.sleep(1)

    workflow = MathModelWorkFlow()
    workflow.cancel_event = cancel_event

    task = asyncio.create_task(workflow.resume(task_id))
    _active_tasks[task_id] = (task, cancel_event)

    task_completed = False
    try:
        # 设置超时时间（5 小时）
        await asyncio.wait_for(task, timeout=3600 * 5)
        task_completed = True

        await redis_manager.publish_message(
            task_id,
            SystemMessage(content="任务处理完成", type="success"),
        )
        write_task_status(task_id, "completed", "任务处理完成")
    except asyncio.CancelledError:
        logger.info(f"任务 {task_id} 被取消")
        await redis_manager.publish_message(
            task_id,
            SystemMessage(content="任务已停止", type="warning"),
        )
        write_task_status(task_id, "cancelled", "任务已停止")
    except Exception as e:
        logger.error(f"任务 {task_id} 续传失败: {e}")
        await redis_manager.publish_message(
            task_id,
            SystemMessage(content=f"任务续传失败: {str(e)}", type="error"),
        )
        write_task_status(task_id, "failed", str(e))
    finally:
        _active_tasks.pop(task_id, None)
        user_input_queue.clear(task_id)
        if task_completed:
            try:
                checkpoint = CheckpointManager(get_work_dir(task_id)).load()
                export_profile = (
                    checkpoint.export_profile if checkpoint is not None else "default"
                )
                _finalize_docx_and_manifest(task_id, export_profile)
            except Exception as e:
                logger.error(f"任务 {task_id} DOCX 转换失败: {e}")
                await redis_manager.publish_message(
                    task_id,
                    SystemMessage(
                        content=f"DOCX 转换失败: {str(e)}，Markdown/PDF 结果不受影响",
                        type="warning",
                    ),
                )
