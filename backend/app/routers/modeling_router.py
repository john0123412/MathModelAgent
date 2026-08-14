"""建模任务路由模块，提供任务创建、API 验证和配置管理等接口。"""

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile
from app.core.checkpoint import CheckpointManager, TaskCheckpoint
from app.core.workflow import MathModelWorkFlow
from app.schemas.enums import CompTemplate, ExportProfile, FormatOutPut
from app.utils.log_util import logger
from app.services.redis_manager import redis_manager
from app.services import user_input_queue
from app.services.task_recovery import load_task_request_snapshot
from app.services.task_status import read_task_status, write_task_status
from app.schemas.request import DEFAULT_MODELING_EXPORT_PROFILE, Problem
from app.schemas.A2A import ModelerToCoder
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
import hashlib
import json
import uuid
from typing import Dict, Literal, Tuple
from fastapi import HTTPException
from icecream import ic  # type: ignore[import-unresolved]
from app.schemas.request import ExampleRequest
from pydantic import BaseModel, Field
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
    work_dir = get_work_dir(task_id)
    manifest_path = os.path.join(work_dir, "candidate_manifest.json")
    # A previous candidate must not survive a failed refresh and masquerade as
    # the current DOCX/audit result. The audit needs a provisional manifest, so
    # remove it again if any later finalization step fails.
    try:
        os.remove(manifest_path)
    except FileNotFoundError:
        pass

    try:
        md_2_docx(task_id, export_profile=export_profile)
        # Final acceptance validates the manifest hashes, so write a current
        # manifest before the submission audit.  The audit then cross-binds that
        # manifest with the template identity used by DOCX/PDF/preflight/visual
        # reports; refresh once more to include report filenames.
        write_candidate_manifest(work_dir, task_id)
        write_submission_audit_report(work_dir)
        report = write_final_acceptance_report(work_dir)
        write_candidate_manifest(work_dir, task_id)
        return report
    except Exception:
        try:
            os.remove(manifest_path)
        except FileNotFoundError:
            pass
        raise


async def _apply_final_acceptance_status(task_id: str, report: dict) -> bool:
    """Persist the only task status that matches the final technical gate.

    A completed workflow is not a completed delivery when final acceptance has
    hard failures.  Keep the persisted status authoritative so the task list
    cannot promote stale output files to a successful task.
    """
    if report.get("technical_status") != "TECHNICAL_PASS":
        message = "最终技术验收未通过，请查看 final_acceptance_report.json"
        await redis_manager.publish_message(
            task_id,
            SystemMessage(content=message, type="error"),
        )
        write_task_status(task_id, "failed", message)
        return False

    await redis_manager.publish_message(
        task_id,
        SystemMessage(content="任务处理完成", type="success"),
    )
    write_task_status(task_id, "completed", "任务处理完成")
    return True



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


class GuidanceRequest(BaseModel):
    """A bounded, role-addressed advisory note for an in-flight task."""

    target: Literal["coordinator", "modeler", "coder", "writer", "all"]
    content: str
    purpose: Literal["modeling", "execution", "review", "recovery"] = "review"
    source: Literal["codex", "operator"] = "operator"


class GuidanceResponse(BaseModel):
    task_id: str
    target: str
    status: str
    audit_file: str


def _require_safe_task_id(task_id: str) -> str:
    """验证 URL 中的任务 ID，非法时返回 400。"""
    try:
        return ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法任务ID") from exc


def _append_guidance_audit(
    work_dir: str,
    *,
    task_id: str,
    target: str,
    purpose: str,
    source: str,
    content: str,
) -> str:
    """Persist non-sensitive guidance metadata without storing prompt text.

    The live queue holds the content only until the receiving Agent calls its
    model.  The task directory keeps a hash, length and routing decision so a
    later review can establish what was injected without copying potentially
    sensitive operator text into candidate/support materials.
    """
    audit_file = "internal_guidance_audit.jsonl"
    record = {
        "id": uuid.uuid4().hex,
        "created_at": datetime.datetime.now().isoformat(),
        "task_id": task_id,
        "target": target,
        "purpose": purpose,
        "source": source,
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content_chars": len(content),
        "delivery": "queued_untrusted_advisory",
    }
    with open(os.path.join(work_dir, audit_file), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return audit_file


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
    require_model_review: bool = Form(False),
    guidance_target: Literal["coordinator", "modeler", "coder", "writer", "all"] = Form(
        "all"
    ),
    guidance_content: str = Form(""),
    guidance_purpose: Literal["modeling", "execution", "review", "recovery"] = Form(
        "review"
    ),
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

    # Optional preloaded guidance removes the race between task creation and
    # the first Modeler call. It follows the same untrusted/advisory path as
    # runtime guidance and therefore cannot override workflow safeguards.
    if guidance_content.strip():
        normalized_guidance = user_input_queue.normalize_content(guidance_content.strip())
        if not user_input_queue.push(task_id, normalized_guidance, guidance_target):
            raise HTTPException(status_code=429, detail="预注入引导队列已满或目标无效")
        _append_guidance_audit(
            work_dir,
            task_id=task_id,
            target=guidance_target,
            purpose=guidance_purpose,
            source="operator",
            content=normalized_guidance,
        )

    logger.info(f"Adding background task for task_id: {task_id}")
    # 将任务添加到后台执行
    background_tasks.add_task(
        run_modeling_task_async,
        task_id,
        ques_all,
        comp_template,
        format_output,
        export_profile,
        require_model_review=require_model_review,
    )
    return {"task_id": task_id, "status": "processing"}


async def run_modeling_task_async(
    task_id: str,
    ques_all: str,
    comp_template: CompTemplate,
    format_output: FormatOutPut,
    export_profile: ExportProfile = DEFAULT_MODELING_EXPORT_PROFILE,
    recovery_context: str = "",
    require_model_review: bool = False,
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
        require_model_review=require_model_review,
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
    task = asyncio.create_task(
        workflow.execute(problem, recovery_context=recovery_context)
    )
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
        if workflow_result == "waiting_quality_review":
            write_task_status(
                task_id,
                "waiting_quality_review",
                "冻结结果等待 Codex/人工质量复核",
            )
            return

        workflow_completed = True
        write_task_status(task_id, "finalizing", "工作流完成，正在生成并验收最终产物")
        await redis_manager.publish_message(
            task_id,
            SystemMessage(content="工作流完成，正在生成并验收最终产物"),
        )
        final_report = _finalize_docx_and_manifest(task_id, export_profile)
        if not await _apply_final_acceptance_status(task_id, final_report):
            return
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


@router.post(
    "/modeling/{task_id}/guidance", response_model=GuidanceResponse, status_code=202
)
async def queue_guidance(task_id: str, request: GuidanceRequest):
    """Queue bounded advisory guidance for one workflow role.

    This is deliberately not a privileged prompt override.  The receiving
    Agent labels it untrusted, and ModelPlan validation, execution validation,
    task boundaries and cancellation rules remain authoritative.
    """
    safe_task_id = _require_safe_task_id(task_id)
    try:
        work_dir = get_work_dir(safe_task_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在") from None

    state = (read_task_status(work_dir) or {}).get("status")
    if state in {"completed", "cancelled"}:
        raise HTTPException(status_code=409, detail="任务已结束，不能再注入引导")

    content = user_input_queue.normalize_content(request.content.strip())
    if not content:
        raise HTTPException(status_code=422, detail="引导内容不能为空")
    if not user_input_queue.push(safe_task_id, content, request.target):
        raise HTTPException(status_code=429, detail="引导队列已满或目标无效")

    audit_file = _append_guidance_audit(
        work_dir,
        task_id=safe_task_id,
        target=request.target,
        purpose=request.purpose,
        source=request.source,
        content=content,
    )
    await redis_manager.publish_message(
        safe_task_id,
        SystemMessage(
            content=f"已接收面向 {request.target} 的外部引导（{request.purpose}）",
            type="info",
        ),
    )
    return GuidanceResponse(
        task_id=safe_task_id,
        target=request.target,
        status="queued",
        audit_file=audit_file,
    )


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


class ResumeTaskRequest(BaseModel):
    """An explicit, bounded authorization for a post-failure recovery."""

    recovery_mode: Literal["provider_changed", "low_cost_algorithm"] | None = None
    note: str = ""


class ApproveModelingRequest(BaseModel):
    comment: str = ""


class ReviseModelingRequest(BaseModel):
    """Bounded reviewer feedback used to rebuild a paused ModelPlan once."""

    comment: str


class CodexModelingRequest(BaseModel):
    """A structured, reviewer-authored ModelPlan for a failed Modeler task."""

    modeler_response: ModelerToCoder
    comment: str = ""


class ExecutionReviewRequest(BaseModel):
    """A reviewer decision bound to the current frozen-result review ID."""

    action: Literal["approve", "repair"]
    review_id: str
    comment: str
    failed_subtasks: list[str] = Field(default_factory=list)


def _build_recovery_context(
    prior_status: dict | None,
    checkpoint,
    request: ResumeTaskRequest | None,
) -> str:
    """Pass concise, factual recovery evidence to agents without leaking it to papers."""
    facts: list[str] = [
        "这是一次受控恢复。保留已验证的结果，只重新解决未完成或未通过验证的阶段。",
        "最终论文只能写经验证的数学结论，不得提及失败、重试或恢复过程。",
    ]
    if prior_status and prior_status.get("message"):
        facts.append("上次任务状态：" + str(prior_status["message"])[:1200])
    if checkpoint and checkpoint.last_validation_failure:
        failed = checkpoint.last_validation_failure.get("failed_subtasks", [])
        if failed:
            facts.append("待重新检查的子题：" + "、".join(map(str, failed)))
    if request and request.recovery_mode:
        labels = {
            "provider_changed": "已由人工确认切换到已验证的 provider 配置。",
            "low_cost_algorithm": "已由人工确认改用低开销、可复核算法。",
        }
        facts.append(labels[request.recovery_mode])
        if request.note.strip():
            facts.append("人工恢复说明：" + request.note.strip()[:1000])
    return "\n".join(facts)


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


def _canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _modeling_approval_binding_issues(
    work_dir: str, checkpoint: TaskCheckpoint
) -> list[str]:
    """Ensure the human approves exactly the plan that resume will execute."""
    paths = {
        "decision": os.path.join(work_dir, "modeling_decision.json"),
        "plan": os.path.join(work_dir, "modeler_plan.json"),
    }
    payloads: dict[str, dict] = {}
    for label, path in paths.items():
        try:
            with open(path, encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return [f"无法读取当前{label}文件"]
        if not isinstance(value, dict):
            return [f"当前{label}文件格式无效"]
        payloads[label] = value

    approved_payload = payloads["decision"].get("modeler_response")
    checkpoint_payload = checkpoint.modeler_response
    if not isinstance(approved_payload, dict):
        return ["建模确认文件缺少待审批方案"]
    if not isinstance(checkpoint_payload, dict):
        return ["检查点缺少待执行建模方案"]

    approved_hash = _canonical_json_sha256(approved_payload)
    declared_hash = payloads["decision"].get("modeler_plan_sha256")
    issues: list[str] = []
    if not isinstance(declared_hash, str):
        issues.append("建模确认文件缺少方案哈希")
    elif declared_hash != approved_hash:
        issues.append("建模确认文件的方案哈希不一致")
    if _canonical_json_sha256(payloads["plan"]) != approved_hash:
        issues.append("当前 modeler_plan.json 已与待审批方案不一致")
    if _canonical_json_sha256(checkpoint_payload) != approved_hash:
        issues.append("检查点待执行方案已与待审批方案不一致")
    return issues


def _has_payload_content(value: object) -> bool:
    """Return whether a persisted payload contains meaningful content."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return any(_has_payload_content(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_payload_content(item) for item in value)
    return True


def _cancelled_codex_modeling_issues(checkpoint: TaskCheckpoint) -> list[str]:
    """Reject cancelled tasks that are not pristine at the pre-execution boundary."""
    issues: list[str] = []
    if _has_payload_content(checkpoint.modeler_response):
        issues.append("已有 modeler_response 内容")
    if checkpoint.completed_phases:
        issues.append("已有 completed_phases")
    if checkpoint.solution_coder_responses:
        issues.append("已有 solution_coder_responses")
    if checkpoint.executed_cell_indices:
        issues.append("已有 executed_cell_indices")
    if checkpoint.has_variable_snapshot:
        issues.append("已有变量快照")
    if checkpoint.workflow_state not in {"", "solving"}:
        issues.append(f"已有执行状态 {checkpoint.workflow_state!r}")
    if checkpoint.targeted_repair_attempts or checkpoint.last_validation_failure:
        issues.append("已有执行验证失败/返修状态")
    if checkpoint.manual_recovery_attempts or checkpoint.last_manual_recovery:
        issues.append("已有人工执行恢复状态")
    if checkpoint.paper_repair_attempts or checkpoint.last_paper_preflight_failure:
        issues.append("已有论文预检返修状态")
    if checkpoint.quality_review_status not in {"", "not_run"}:
        issues.append(f"已有质量复核状态 {checkpoint.quality_review_status!r}")
    if (
        checkpoint.quality_review_id
        or checkpoint.quality_review_history
        or checkpoint.quality_review_repairs
    ):
        issues.append("已有质量复核记录")
    if checkpoint.modeling_review_revisions:
        issues.append("已有建模方案修订状态")
    return issues


def _mark_modeling_decision_revision_requested(work_dir: str, comment: str) -> None:
    """Persist an auditable rejection before a ModelPlan is rebuilt."""
    decision_path = os.path.join(work_dir, "modeling_decision.json")
    if not os.path.exists(decision_path):
        raise HTTPException(status_code=404, detail="未找到建模确认文件")
    try:
        with open(decision_path, encoding="utf-8") as f:
            decision = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="建模确认文件读取失败") from exc

    now = datetime.datetime.now().isoformat()
    decision["status"] = "revising"
    decision.setdefault("review", {})
    decision["review"].update(
        {"approved": False, "approved_at": None, "comment": comment}
    )
    history = decision.setdefault("review_history", [])
    if not isinstance(history, list):
        history = []
        decision["review_history"] = history
    history.append(
        {"action": "revision_requested", "requested_at": now, "comment": comment}
    )
    tmp_path = decision_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(decision, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, decision_path)


def _mark_modeling_decision_revision_failed(work_dir: str, message: str) -> None:
    """Keep the paused-review artifact consistent with a failed rebuild."""
    decision_path = os.path.join(work_dir, "modeling_decision.json")
    if not os.path.exists(decision_path):
        return
    try:
        with open(decision_path, encoding="utf-8") as f:
            decision = json.load(f)
    except (OSError, json.JSONDecodeError):
        logger.warning("建模修订失败后无法更新审查文件状态")
        return
    decision["status"] = "revision_failed"
    history = decision.setdefault("review_history", [])
    if isinstance(history, list):
        history.append(
            {
                "action": "revision_failed",
                "failed_at": datetime.datetime.now().isoformat(),
                "message": message[:1000],
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
    prior_state = (read_task_status(work_dir) or {}).get("status")
    if prior_state != "waiting_review":
        raise HTTPException(status_code=409, detail="仅 waiting_review 状态可确认建模方案")
    binding_issues = _modeling_approval_binding_issues(work_dir, checkpoint)
    if binding_issues:
        raise HTTPException(
            status_code=409,
            detail="当前建模方案已变化，请重新生成并复核：" + "；".join(binding_issues),
        )

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


@router.post("/modeling/{task_id}/revise-modeling", response_model=ResumeTaskResponse)
async def revise_modeling(
    task_id: str,
    background_tasks: BackgroundTasks,
    request: ReviseModelingRequest,
):
    """Return one paused ModelPlan to Modeler with explicit reviewer feedback."""
    safe_task_id = _require_safe_task_id(task_id)
    comment = request.comment.strip()
    if not comment:
        raise HTTPException(status_code=422, detail="退回意见不能为空")
    try:
        work_dir = get_work_dir(safe_task_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在")
    if safe_task_id in _active_tasks:
        raise HTTPException(status_code=409, detail="任务仍在运行中")
    prior_state = (read_task_status(work_dir) or {}).get("status")
    if prior_state != "waiting_review":
        raise HTTPException(status_code=409, detail="仅 waiting_review 状态可退回建模方案")

    checkpoint_manager = CheckpointManager(work_dir)
    checkpoint = checkpoint_manager.load()
    if checkpoint is None:
        raise HTTPException(status_code=404, detail="未找到可修订的检查点")
    try:
        checkpoint_manager.record_modeling_revision_request()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    normalized_comment = user_input_queue.normalize_content(comment)
    if not user_input_queue.push(safe_task_id, normalized_comment, "modeler"):
        raise HTTPException(status_code=429, detail="建模修订引导队列已满")
    _append_guidance_audit(
        work_dir,
        task_id=safe_task_id,
        target="modeler",
        purpose="modeling",
        source="codex",
        content=normalized_comment,
    )
    _mark_modeling_decision_revision_requested(work_dir, normalized_comment)
    write_task_status(safe_task_id, "revising", "建模方案已退回，正在按审查意见修订")
    await redis_manager.publish_message(
        safe_task_id,
        SystemMessage(content="建模方案已退回，正在按审查意见修订", type="warning"),
    )
    background_tasks.add_task(run_revise_modeling_async, safe_task_id, normalized_comment)
    return ResumeTaskResponse(task_id=safe_task_id, status="revising")


@router.post("/modeling/{task_id}/codex-modeling", response_model=ResumeTaskResponse)
async def submit_codex_modeling(task_id: str, request: CodexModelingRequest):
    """Place a Codex-authored, contract-validated plan behind normal approval.

    The endpoint is intentionally limited to a Modeler-failed task, a paused
    reviewer task, or a pristine cancelled task at the pre-execution boundary.
    It is not a route around ModelPlan validation or downstream execution gates.
    """
    safe_task_id = _require_safe_task_id(task_id)
    try:
        work_dir = get_work_dir(safe_task_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在")
    if safe_task_id in _active_tasks:
        raise HTTPException(status_code=409, detail="任务仍在运行中")
    prior_state = (read_task_status(work_dir) or {}).get("status")
    if prior_state not in {"failed", "waiting_review", "cancelled"}:
        raise HTTPException(
            status_code=409,
            detail="仅 Modeler 失败、等待建模审查或满足安全前置条件的取消任务可由 Codex 接管",
        )
    checkpoint = CheckpointManager(work_dir).load()
    if checkpoint is None:
        detail = (
            "取消任务缺少检查点，不能安全接管"
            if prior_state == "cancelled"
            else "该任务未启用可审计的建模人工门禁"
        )
        raise HTTPException(status_code=409, detail=detail)
    if not checkpoint.require_model_review:
        detail = (
            "取消任务未启用可审计的建模人工门禁，不能安全接管"
            if prior_state == "cancelled"
            else "该任务未启用可审计的建模人工门禁"
        )
        raise HTTPException(status_code=409, detail=detail)
    if prior_state == "cancelled":
        cancelled_issues = _cancelled_codex_modeling_issues(checkpoint)
        if cancelled_issues:
            raise HTTPException(
                status_code=409,
                detail=(
                    "取消任务已越过 Codex 安全接管边界，不能接管："
                    + "；".join(cancelled_issues)
                ),
            )
    workflow = MathModelWorkFlow()
    try:
        workflow.accept_codex_modeling(safe_task_id, request.modeler_response)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    note = request.comment.strip()[:1000] or "当前 Codex 在 Modeler 失败或安全取消点提交结构化建模方案。"
    _append_guidance_audit(
        work_dir, task_id=safe_task_id, target="modeler", purpose="review", source="codex", content=note
    )
    write_task_status(safe_task_id, "waiting_review", "Codex 建模方案已写入，等待人工确认")
    await redis_manager.set(f"task_id:{safe_task_id}", safe_task_id)
    await redis_manager.publish_message(
        safe_task_id,
        SystemMessage(content="Codex 建模方案已通过题面契约校验，等待人工确认", type="warning"),
    )
    return ResumeTaskResponse(task_id=safe_task_id, status="waiting_review")


@router.post(
    "/modeling/{task_id}/execution-review", response_model=ResumeTaskResponse
)
async def review_execution_quality(
    task_id: str,
    background_tasks: BackgroundTasks,
    request: ExecutionReviewRequest,
):
    """Approve frozen evidence or send selected formal subtasks back to Coder."""
    safe_task_id = _require_safe_task_id(task_id)
    try:
        work_dir = get_work_dir(safe_task_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在") from None
    if safe_task_id in _active_tasks:
        raise HTTPException(status_code=409, detail="任务仍在运行中")
    prior_state = (read_task_status(work_dir) or {}).get("status")
    if prior_state != "waiting_quality_review":
        raise HTTPException(status_code=409, detail="任务不在执行质量复核状态")

    manager = CheckpointManager(work_dir)
    checkpoint = manager.load()
    if checkpoint is None:
        raise HTTPException(status_code=404, detail="未找到质量复核检查点")
    comment = user_input_queue.normalize_content(request.comment.strip())
    if not comment:
        raise HTTPException(status_code=422, detail="复核理由或返修意见不能为空")

    if request.action == "approve":
        try:
            manager.approve_quality_review(request.review_id.strip(), comment)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        status_message = "执行结果质量复核已放行，继续论文写作"
    else:
        allowed_subtasks = {
            str(key)
            for key in checkpoint.questions
            if str(key).startswith("ques") and str(key) != "ques_count"
        }
        requested = sorted(set(request.failed_subtasks))
        if not requested or any(key not in allowed_subtasks for key in requested):
            raise HTTPException(status_code=422, detail="返修子题必须来自当前任务正式问题")
        try:
            manager.request_quality_repair(
                request.review_id.strip(), requested, comment
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        guidance = (
            "【执行质量复核定向返修】只重新求解以下子题："
            + "、".join(requested)
            + "。必须实际执行、覆盖对应结果文件并重新记录证据。\n审查意见："
            + comment
        )
        _append_guidance_audit(
            work_dir,
            task_id=safe_task_id,
            target="coder",
            purpose="execution",
            source="codex",
            content=guidance,
        )
        status_message = "执行质量复核已退回指定子题，开始定向返修"

    write_task_status(safe_task_id, "resuming", status_message)
    await redis_manager.set(f"task_id:{safe_task_id}", safe_task_id)
    await redis_manager.publish_message(
        safe_task_id, SystemMessage(content=status_message, type="warning")
    )
    background_tasks.add_task(run_resume_task_async, safe_task_id, comment)
    return ResumeTaskResponse(task_id=safe_task_id, status="resuming")


@router.post("/modeling/{task_id}/resume", response_model=ResumeTaskResponse)
async def resume_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    request: ResumeTaskRequest | None = None,
):
    """从检查点续传，或从早期失败前保存的请求快照重新开始。"""
    safe_task_id = _require_safe_task_id(task_id)
    try:
        work_dir = get_work_dir(safe_task_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在")

    if safe_task_id in _active_tasks:
        raise HTTPException(status_code=409, detail="任务仍在运行中")

    prior_status = read_task_status(work_dir)
    prior_state = (prior_status or {}).get("status")
    checkpoint_manager = CheckpointManager(work_dir)
    checkpoint = checkpoint_manager.load()
    export_only_paper_repair = bool(
        checkpoint is not None
        and checkpoint.workflow_state
        in {
            "paper_repair_pending_export",
            "editorial_repair_pending_export",
            "presentation_reflow_pending_export",
            "format_compliance_pending_export",
        }
    )
    # A bounded paper candidate is allowed to be applied after a technically
    # completed task.  Its immutable checkpoint state is the authority here:
    # let the normal resume path perform export only, rather than bypassing the
    # router or waking any provider because ``task_status`` still says completed.
    if prior_state == "completed" and not export_only_paper_repair:
        raise HTTPException(status_code=409, detail="任务已完成，无需续传")
    if prior_state == "waiting_review":
        raise HTTPException(status_code=409, detail="任务等待建模方案确认，请使用 approve-modeling")
    if prior_state == "waiting_quality_review":
        raise HTTPException(status_code=409, detail="任务等待执行质量复核，请使用 execution-review")

    if (
        checkpoint is not None
        and not export_only_paper_repair
        and checkpoint_manager.repair_attempts_exhausted()
    ):
        if request is None or request.recovery_mode is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "执行验证已连续两次失败。请先由指定决策人切换已验证 provider "
                    "或确认低开销算法，再在请求体中声明 recovery_mode。"
                ),
            )
        try:
            checkpoint_manager.authorize_manual_execution_recovery(
                request.recovery_mode, request.note
            )
            checkpoint = checkpoint_manager.load()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    recovery_context = _build_recovery_context(prior_status, checkpoint, request)
    snapshot = None if checkpoint is not None else load_task_request_snapshot(work_dir)
    if checkpoint is None and snapshot is None:
        raise HTTPException(
            status_code=404,
            detail="未找到检查点或任务请求快照；该历史任务无法安全自动重启",
        )
    if snapshot is not None and snapshot["task_id"] != safe_task_id:
        raise HTTPException(status_code=409, detail="任务请求快照与任务 ID 不一致")

    # 存储任务ID，续期供 ws 鉴权使用
    await redis_manager.set(f"task_id:{safe_task_id}", safe_task_id)

    logger.info(f"Adding resume background task for task_id: {safe_task_id}")
    if checkpoint is not None:
        write_task_status(safe_task_id, "resuming", "从检查点受控续传中")
        background_tasks.add_task(run_resume_task_async, safe_task_id, recovery_context)
    else:
        write_task_status(safe_task_id, "resuming", "早期失败后从任务请求快照重新开始")
        background_tasks.add_task(
            run_modeling_task_async,
            safe_task_id,
            snapshot["ques_all"],
            CompTemplate(snapshot["comp_template"]),
            FormatOutPut(snapshot["format_output"]),
            ExportProfile(snapshot["export_profile"]),
            recovery_context=recovery_context,
            require_model_review=bool(snapshot.get("require_model_review", False)),
        )
    return ResumeTaskResponse(task_id=safe_task_id, status="resuming")


async def run_revise_modeling_async(task_id: str, review_comment: str) -> None:
    """Run the bounded ModelPlan revision and return to the review gate."""
    logger.info(f"revise modeling plan for task_id: {task_id}")
    cancel_event = asyncio.Event()
    workflow = MathModelWorkFlow()
    workflow.cancel_event = cancel_event
    task = asyncio.create_task(workflow.revise_modeling(task_id, review_comment))
    _active_tasks[task_id] = (task, cancel_event)

    try:
        result = await asyncio.wait_for(task, timeout=3600)
        if result != "waiting_review":
            raise RuntimeError(f"建模修订返回了意外状态: {result}")
        write_task_status(task_id, "waiting_review", "修订后的建模方案等待人工确认")
        await redis_manager.publish_message(
            task_id,
            SystemMessage(content="修订后的建模方案等待人工确认", type="warning"),
        )
    except asyncio.CancelledError:
        logger.info(f"建模方案修订 {task_id} 被取消")
        write_task_status(task_id, "cancelled", "建模方案修订已停止")
    except Exception as exc:
        logger.error(f"建模方案修订 {task_id} 失败: {type(exc).__name__}")
        _mark_modeling_decision_revision_failed(get_work_dir(task_id), str(exc))
        await redis_manager.publish_message(
            task_id,
            SystemMessage(content=f"建模方案修订失败: {exc}", type="error"),
        )
        write_task_status(task_id, "failed", f"建模方案修订失败: {exc}")
    finally:
        _active_tasks.pop(task_id, None)
        user_input_queue.clear(task_id)


async def run_resume_task_async(task_id: str, recovery_context: str = ""):
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

    task = asyncio.create_task(
        workflow.resume(task_id, recovery_context=recovery_context)
    )
    _active_tasks[task_id] = (task, cancel_event)

    workflow_completed = False
    try:
        workflow_result = await asyncio.wait_for(task, timeout=3600 * 5)
        if workflow_result == "waiting_review":
            write_task_status(task_id, "waiting_review", "任务等待人工确认建模方案")
            await redis_manager.publish_message(
                task_id,
                SystemMessage(content="任务等待人工确认建模方案", type="warning"),
            )
            return
        if workflow_result == "waiting_quality_review":
            write_task_status(
                task_id,
                "waiting_quality_review",
                "冻结结果等待 Codex/人工质量复核",
            )
            return
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
        if not await _apply_final_acceptance_status(task_id, final_report):
            return
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
