"""建模任务路由模块，提供任务创建、API 验证和配置管理等接口。"""

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile
from app.core.checkpoint import CheckpointManager
from app.core.workflow import MathModelWorkFlow
from app.schemas.enums import CompTemplate, ExportProfile, FormatOutPut
from app.utils.log_util import logger
from app.services.redis_manager import redis_manager
from app.services import user_input_queue
from app.services.task_status import write_task_status
from app.schemas.request import DEFAULT_MODELING_EXPORT_PROFILE, Problem
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
from app.tools.submission_audit import write_submission_audit_report
from app.tools.final_acceptance import write_final_acceptance_report
import os
import asyncio
import shutil
import datetime
import json
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
from app.utils.security import validate_llm_base_url
import requests

router = APIRouter()
EXAMPLE_ROOT = os.path.abspath(os.path.join("app", "example", "example"))
UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024

# 任务注册表: task_id -> (asyncio.Task, asyncio.Event)
# WHY 该表是进程内状态；当前 Docker/uvicorn 以单 worker 运行。
# 若改成多 worker，cancel / approve / resume 可能路由到不持有任务的进程而失效，
# 需要先把活动任务注册与取消信号迁移到 Redis 或其他跨进程协调机制。
_active_tasks: Dict[str, Tuple[asyncio.Task, asyncio.Event]] = {}


def _finalize_docx_and_manifest(
    task_id: str,
    export_profile: ExportProfile | str | None = DEFAULT_MODELING_EXPORT_PROFILE,
) -> dict:
    """完成 DOCX、审计、候选清单和最终技术验收。

    任一步失败都会向调用方抛出异常，任务不得提前标记为 completed。
    """
    md_2_docx(task_id, export_profile=export_profile)
    work_dir = get_work_dir(task_id)
    write_submission_audit_report(work_dir)
    # Final acceptance validates the manifest hashes, so write a current
    # manifest before the report, then refresh it once more to include the
    # report filenames without changing the artifact set.
    write_candidate_manifest(work_dir, task_id)
    report = write_final_acceptance_report(work_dir)
    write_candidate_manifest(work_dir, task_id)
    return report



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


class SaveApiConfigResponse(BaseModel):
    success: bool
    message: str
    scope: str
    persisted: bool


def _require_safe_task_id(task_id: str) -> str:
    """验证 URL 中的任务 ID，非法时返回 400。"""
    try:
        return ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法任务ID") from exc


def _validated_llm_base_url(base_url: str | None) -> str | None:
    return validate_llm_base_url(
        base_url,
        allow_private_hosts=settings.ALLOW_PRIVATE_LLM_BASE_URLS,
    )


async def _save_uploaded_file(
    upload: UploadFile,
    destination: str,
    *,
    total_uploaded_bytes: int,
) -> int:
    """Stream an upload to disk while enforcing per-file and aggregate limits."""
    file_size = 0
    try:
        with open(destination, "xb") as output:
            while chunk := await upload.read(UPLOAD_CHUNK_SIZE_BYTES):
                file_size += len(chunk)
                if file_size > settings.MAX_UPLOAD_FILE_SIZE_BYTES:
                    raise HTTPException(status_code=413, detail="单个上传文件超过大小上限")
                if total_uploaded_bytes + file_size > settings.MAX_UPLOAD_TOTAL_SIZE_BYTES:
                    raise HTTPException(status_code=413, detail="上传文件总大小超过上限")
                output.write(chunk)
        return file_size
    except Exception:
        if os.path.exists(destination):
            os.remove(destination)
        raise
    finally:
        await upload.close()


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


def _normalize_base_url_for_comparison(base_url: object) -> str:
    """将 Base URL 归一化用于等价比较（去空白与尾部斜杠）。"""
    if base_url is None:
        return ""
    return str(base_url).strip().rstrip("/")


def _require_api_key_for_new_base_url(
    block: dict, current_base_url: str | None
) -> None:
    """更换 LLM 端点时强制同请求携带 API Key，否则整个请求 422。

    仅换 baseUrl 而保留原有 apiKey 会把现有真实密钥随 Authorization 头
    发往新端点，构成密钥外泄链；SSRF 校验（validate_llm_base_url）防不了
    这条路径，因此在保存前强制"新端点 + 新密钥"成对提交。
    与当前端点等价的重复提交不受影响。

    Args:
        block: 单个 agent 的配置块（来自请求体）。
        current_base_url: 当前 settings 中该 agent 的 BASE_URL。

    Raises:
        HTTPException: 提供了不同的非空 baseUrl 但未携带非空 apiKey 时抛出 422。
    """
    if not block:
        return
    new_base_url = _normalize_base_url_for_comparison(block.get("baseUrl"))
    if not new_base_url:
        return
    if new_base_url == _normalize_base_url_for_comparison(current_base_url):
        return
    if not block.get("apiKey"):
        raise HTTPException(
            status_code=422,
            detail="更换 Base URL 必须同时提供该端点的 API Key，防止现有密钥被发往新端点",
        )


@router.post("/save-api-config", response_model=SaveApiConfigResponse)
async def save_api_config(request: SaveApiConfigRequest):
    """
    保存验证成功的 API 配置到当前进程 settings，不写入 .env.dev。
    """
    # 换端点必须同请求携带该端点的 API Key；先校验全部四个块再落任何字段，
    # 保证请求原子性（部分合法块不会先生效）。
    _require_api_key_for_new_base_url(
        request.coordinator, settings.COORDINATOR_BASE_URL
    )
    _require_api_key_for_new_base_url(request.modeler, settings.MODELER_BASE_URL)
    _require_api_key_for_new_base_url(request.coder, settings.CODER_BASE_URL)
    _require_api_key_for_new_base_url(request.writer, settings.WRITER_BASE_URL)

    try:
        # 更新各个模块的设置：仅当字段非空时才覆盖，空字段保留 .env.dev 中
        # 已加载的默认配置，避免前端未填写时把可用的 key 覆盖成空字符串
        if request.coordinator:
            if api_key := request.coordinator.get("apiKey"):
                settings.COORDINATOR_API_KEY = api_key
            if model_id := request.coordinator.get("modelId"):
                settings.COORDINATOR_MODEL = model_id
            if base_url := request.coordinator.get("baseUrl"):
                settings.COORDINATOR_BASE_URL = _validated_llm_base_url(base_url)
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
                settings.MODELER_BASE_URL = _validated_llm_base_url(base_url)
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
                settings.CODER_BASE_URL = _validated_llm_base_url(base_url)
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
                settings.WRITER_BASE_URL = _validated_llm_base_url(base_url)
            if api_type := request.writer.get("apiType"):
                settings.WRITER_API_TYPE = api_type
            if cw := request.writer.get("contextWindow"):
                settings.WRITER_CONTEXT_WINDOW = int(cw)

        if request.openalex_email:
            settings.OPENALEX_EMAIL = request.openalex_email

        return {
            "success": True,
            "message": "配置已保存到当前后端进程，重启后需重新配置或写入 .env.dev",
            "scope": "runtime",
            "persisted": False,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="LLM Base URL 配置不合法") from exc
    except Exception:
        logger.exception("保存配置失败")
        raise HTTPException(status_code=500, detail="保存配置失败")


@router.post("/validate-api-key", response_model=ValidateApiKeyResponse)
async def validate_api_key(request: ValidateApiKeyRequest):
    """
    验证 API Key 的有效性
    """
    try:
        base_url = _validated_llm_base_url(request.base_url)
    except ValueError:
        return ValidateApiKeyResponse(valid=False, message="✗ Base URL 不安全或格式不合法")

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
            base_url=base_url if base_url != "https://api.openai.com/v1" else None,
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
        return ValidateApiKeyResponse(
            valid=False, message="✗ 验证失败，请检查网络、Base URL 和模型配置"
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
        logger.debug(
            "OpenAlex Email 验证响应已接收: "
            f"status_code={response.status_code}"
        )
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
        DEFAULT_MODELING_EXPORT_PROFILE,
    )
    return {"task_id": task_id, "status": "processing"}


@router.post("/modeling")
async def modeling(
    background_tasks: BackgroundTasks,
    ques_all: str = Form(...),  # 从表单获取
    comp_template: CompTemplate = Form(...),  # 从表单获取
    format_output: FormatOutPut = Form(...),  # 从表单获取
    export_profile: ExportProfile = Form(DEFAULT_MODELING_EXPORT_PROFILE),  # 从表单获取
    files: list[UploadFile] = File(default=None),
):
    if len(ques_all) > settings.MAX_PROBLEM_TEXT_CHARS:
        raise HTTPException(status_code=413, detail="题目文本超过大小上限")

    task_id = create_task_id()
    work_dir = create_work_dir(task_id)

    try:
        # 如果有上传文件，流式保存，避免将不受信任内容整体读入进程内存。
        if files:
            logger.info(f"开始处理上传的文件，工作目录: {work_dir}")
            total_uploaded_bytes = 0
            uploaded_filenames: set[str] = set()
            for file in files:
                if not file.filename:
                    logger.warning("跳过空文件名")
                    await file.close()
                    continue
                safe_filename = ensure_safe_filename(file.filename)
                if safe_filename in uploaded_filenames:
                    await file.close()
                    raise HTTPException(status_code=400, detail="不允许重复上传同名文件")
                uploaded_filenames.add(safe_filename)
                data_file_path = safe_join_work_dir(task_id, safe_filename)
                file_size = await _save_uploaded_file(
                    file,
                    data_file_path,
                    total_uploaded_bytes=total_uploaded_bytes,
                )
                total_uploaded_bytes += file_size
                logger.info(f"上传文件已保存: {safe_filename} ({file_size} bytes)")
        else:
            logger.warning("没有上传文件")
    except HTTPException:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        logger.exception("保存上传文件失败")
        raise HTTPException(status_code=400, detail="保存上传文件失败")

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
    export_profile: ExportProfile = DEFAULT_MODELING_EXPORT_PROFILE,
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

    workflow_completed = False
    try:
        # 设置超时时间（5 小时）
        workflow_result = await asyncio.wait_for(task, timeout=3600 * 5)
        if workflow_result == "waiting_review":
            await redis_manager.publish_message(
                task_id,
                SystemMessage(content="任务等待人工确认建模方案", type="warning"),
            )
            write_task_status(task_id, "waiting_review", "任务等待人工确认建模方案")
            return

        workflow_completed = True
        write_task_status(task_id, "finalizing", "工作流完成，正在生成并验收最终产物")
        await redis_manager.publish_message(
            task_id,
            SystemMessage(content="工作流完成，正在生成并验收最终产物"),
        )
        final_report = _finalize_docx_and_manifest(task_id, export_profile)
        if final_report.get("technical_status") != "TECHNICAL_PASS":
            await redis_manager.publish_message(
                task_id,
                SystemMessage(
                    content=(
                        "主交付产物已生成，但正式技术验收仍有待处理项；"
                        "请查看 final_acceptance_report.json"
                    ),
                    type="warning",
                ),
            )

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
        phase = "最终产物收尾失败" if workflow_completed else "任务执行失败"
        logger.error(f"任务 {task_id} {phase}: {type(e).__name__}")
        await redis_manager.publish_message(
            task_id,
            SystemMessage(content=f"{phase}: {str(e)}", type="error"),
        )
        write_task_status(task_id, "failed", f"{phase}: {e}")
    finally:
        _active_tasks.pop(task_id, None)
        user_input_queue.clear(task_id)



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


class ApproveModelingRequest(BaseModel):
    comment: str = ""


def _mark_modeling_decision_approved(work_dir: str, comment: str = "") -> None:
    decision_path = os.path.join(work_dir, "modeling_decision.json")
    if not os.path.exists(decision_path):
        raise HTTPException(status_code=404, detail="未找到建模确认文件")
    try:
        with open(decision_path, encoding="utf-8") as f:
            decision = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="建模确认文件读取失败") from exc

    decision["status"] = "approved"
    decision.setdefault("review", {})
    decision["review"].update(
        {
            "approved": True,
            "approved_at": datetime.datetime.now().isoformat(),
            "comment": comment,
        }
    )
    tmp_path = decision_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(decision, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, decision_path)


@router.post("/modeling/{task_id}/approve-modeling", response_model=ResumeTaskResponse)
async def approve_modeling(
    task_id: str,
    background_tasks: BackgroundTasks,
    request: ApproveModelingRequest | None = None,
):
    """确认建模手方案并从 Coder 阶段继续执行。"""
    safe_task_id = _require_safe_task_id(task_id)
    try:
        work_dir = get_work_dir(safe_task_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在")

    if safe_task_id in _active_tasks:
        raise HTTPException(status_code=409, detail="任务仍在运行中")

    checkpoint = CheckpointManager(work_dir).load()
    if checkpoint is None:
        raise HTTPException(status_code=404, detail="未找到可继续执行的检查点")

    _mark_modeling_decision_approved(
        work_dir,
        "" if request is None else request.comment,
    )
    write_task_status(safe_task_id, "resuming", "建模方案已确认，任务续传中")
    await redis_manager.set(f"task_id:{safe_task_id}", safe_task_id)
    await redis_manager.publish_message(
        safe_task_id,
        SystemMessage(content="建模方案已确认，继续代码求解与论文写作"),
    )
    background_tasks.add_task(run_resume_task_async, safe_task_id)
    return ResumeTaskResponse(task_id=safe_task_id, status="resuming")


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

    workflow_completed = False
    try:
        await asyncio.wait_for(task, timeout=3600 * 5)
        workflow_completed = True
        checkpoint = CheckpointManager(get_work_dir(task_id)).load()
        export_profile = (
            checkpoint.export_profile
            if checkpoint is not None
            else DEFAULT_MODELING_EXPORT_PROFILE
        )
        write_task_status(task_id, "finalizing", "续传完成，正在生成并验收最终产物")
        await redis_manager.publish_message(
            task_id,
            SystemMessage(content="续传完成，正在生成并验收最终产物"),
        )
        final_report = _finalize_docx_and_manifest(task_id, export_profile)
        if final_report.get("technical_status") != "TECHNICAL_PASS":
            await redis_manager.publish_message(
                task_id,
                SystemMessage(
                    content=(
                        "主交付产物已生成，但正式技术验收仍有待处理项；"
                        "请查看 final_acceptance_report.json"
                    ),
                    type="warning",
                ),
            )

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
        phase = "最终产物收尾失败" if workflow_completed else "任务续传失败"
        logger.error(f"任务 {task_id} {phase}: {type(e).__name__}")
        await redis_manager.publish_message(
            task_id,
            SystemMessage(content=f"{phase}: {str(e)}", type="error"),
        )
        write_task_status(task_id, "failed", f"{phase}: {e}")
    finally:
        _active_tasks.pop(task_id, None)
        user_input_queue.clear(task_id)
