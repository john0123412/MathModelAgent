"""建模任务路由模块，提供任务创建、API 验证和配置管理等接口。"""

from fastapi import APIRouter, BackgroundTasks, File, Form, Header, UploadFile
from app.core.checkpoint import CheckpointManager, TaskCheckpoint
from app.core.workflow import MathModelWorkFlow
from app.schemas.enums import CompTemplate, ExportProfile, FormatOutPut
from app.utils.log_util import logger
from app.services.redis_manager import redis_manager
from app.services import user_input_queue
from app.services import task_status as task_status_service
from app.services.task_recovery import load_task_request_snapshot
from app.services.task_status import (
    read_task_status,
    write_task_status,
    write_task_status_to_dir,
)
from app.services.token_usage import USAGE_REPORT_FILENAME
from app.services.idempotency import (
    check_idempotency,
    compute_file_hashes,
    compute_guidance_hash,
    record_idempotency,
)
from app.services.agent_operations import get_single_task_status
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
from app.tools.execution_quality_review import build_execution_quality_review
import os
import re
import asyncio
import shutil
import datetime
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Dict, Literal, Tuple
from fastapi import HTTPException
from icecream import ic  # type: ignore[import-unresolved]
from app.schemas.request import ExampleRequest
from pydantic import BaseModel, ConfigDict, Field, field_validator
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
_active_tasks: Dict[str, Tuple[asyncio.Task | None, asyncio.Event]] = {}
_task_locks: Dict[str, asyncio.Lock] = {}

# Runtime API configuration updates are serialized so concurrent requests can
# never leave an endpoint and its key from different requests interleaved.
_api_config_lock = asyncio.Lock()

# Roadmap P1-2: per-idempotency-key async lock to make check+record atomic
_idempotency_locks: Dict[str, asyncio.Lock] = {}


def _get_idempotency_lock(key: str | None) -> asyncio.Lock:
    if not key:
        # No key -> use a dummy lock that never contends (create ephemeral)
        return asyncio.Lock()
    # Normalize key for lock dict
    k = key.strip()
    if k not in _idempotency_locks:
        _idempotency_locks[k] = asyncio.Lock()
    return _idempotency_locks[k]

_AGENT_CONFIG_BLOCKS: Tuple[Tuple[str, str], ...] = (
    ("coordinator", "COORDINATOR"),
    ("modeler", "MODELER"),
    ("coder", "CODER"),
    ("writer", "WRITER"),
)


def _get_task_lock(task_id: str) -> asyncio.Lock:
    if task_id not in _task_locks:
        _task_locks[task_id] = asyncio.Lock()
    return _task_locks[task_id]


_NON_DISPATCHABLE_STATES = frozenset(
    {"running", "resuming", "revising", "finalizing"}
)


def _reserve_active_task(task_id: str) -> asyncio.Event | None:
    """Atomically reserve a task ID before scheduling a background runner.

    The event is also the reservation token.  Cleanup always compares it by
    identity, so a stale runner or a failed prelude can never remove a newer
    reservation for the same task.
    """
    if task_id in _active_tasks:
        return None
    cancel_event = asyncio.Event()
    _active_tasks[task_id] = (None, cancel_event)
    return cancel_event


def _claim_active_task(task_id: str, cancel_event: asyncio.Event) -> None:
    """Bind a scheduled runner (or direct runner call) to its token."""
    current_task = asyncio.current_task()
    entry = _active_tasks.get(task_id)
    if entry is None:
        raise RuntimeError("任务活动占位令牌已失效")
    if entry[1] is not cancel_event:
        raise RuntimeError("任务活动占位令牌已失效")
    _active_tasks[task_id] = (current_task, cancel_event)


def _bind_workflow_task(
    task_id: str,
    cancel_event: asyncio.Event,
    workflow_task: asyncio.Task,
) -> None:
    """Replace the runner placeholder with the cancellable workflow task."""
    entry = _active_tasks.get(task_id)
    if entry is None or entry[1] is not cancel_event:
        raise RuntimeError("任务活动占位令牌已失效")
    _active_tasks[task_id] = (workflow_task, cancel_event)


def _release_active_task(task_id: str, cancel_event: asyncio.Event) -> None:
    """Release only the reservation owned by ``cancel_event``."""
    entry = _active_tasks.get(task_id)
    if entry is not None and entry[1] is cancel_event:
        _active_tasks.pop(task_id, None)


def _schedule_reserved_runner(
    task_id: str,
    cancel_event: asyncio.Event,
    runner,
    *args,
    **kwargs,
) -> asyncio.Task:
    """Create and register a runner before returning the HTTP response.

    FastAPI ``BackgroundTasks`` are executed only after response delivery.  A
    disconnected client can therefore leave the placeholder in ``_active_tasks``
    forever.  The reservation is already held when this helper runs, so direct
    task creation makes cancellation and duplicate-dispatch checks independent
    of response delivery.  The runner still owns the same token and releases it
    in its ``finally`` block.
    """
    coroutine = runner(*args, cancel_event=cancel_event, **kwargs)
    try:
        task = asyncio.create_task(coroutine)
    except BaseException:
        coroutine.close()
        raise
    try:
        _bind_workflow_task(task_id, cancel_event, task)
    except BaseException:
        task.cancel()
        raise
    return task


def _snapshot_files(paths: tuple[str, ...]) -> dict[str, bytes | None]:
    """Capture small durable control files before a dispatch transaction."""
    snapshot: dict[str, bytes | None] = {}
    for path in paths:
        try:
            with open(path, "rb") as handle:
                snapshot[path] = handle.read()
        except FileNotFoundError:
            snapshot[path] = None
    return snapshot


def _restore_files(snapshot: dict[str, bytes | None]) -> None:
    """Restore a dispatch transaction's control files atomically."""
    for path, content in snapshot.items():
        if content is None:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            continue
        tmp_path = path + ".rollback.tmp"
        with open(tmp_path, "wb") as handle:
            handle.write(content)
        os.replace(tmp_path, path)


async def _rollback_dispatch(
    scheduled_task: asyncio.Task | None,
    state_snapshot: dict[str, bytes | None] | None,
) -> None:
    """Best-effort rollback that never hides the dispatching exception.

    A runner can be created before a later queue/audit operation fails.  It
    must be cancelled and fully drained *before* restoring the control files,
    otherwise its ``finally``/status writes can race the rollback.  Cleanup is
    deliberately defensive: callers own the original exception and release
    the reservation in their own ``finally`` block.
    """
    if scheduled_task is not None:
        try:
            scheduled_task.cancel()
            try:
                await scheduled_task
            except asyncio.CancelledError:
                pass
        except BaseException as exc:
            logger.warning(
                "调度任务回滚收束失败，继续释放占位: error_type={}",
                type(exc).__name__,
            )
    if state_snapshot is not None:
        try:
            _restore_files(state_snapshot)
        except BaseException as exc:
            logger.warning(
                "调度文件回滚失败，继续释放占位: error_type={}",
                type(exc).__name__,
            )


_PRESERVE_STATUS_ON_CANCELLATION = frozenset(
    {
        "completed",
        "failed",
        "cancelled",
        "waiting_review",
        "waiting_quality_review",
        "interrupted",
    }
)


def _write_cancelled_status_if_active(task_id: str, message: str) -> None:
    """Persist cancellation without downgrading an already durable outcome."""
    try:
        current = read_task_status(get_work_dir(task_id))
    except Exception:
        current = None
    if (
        isinstance(current, dict)
        and current.get("status") in _PRESERVE_STATUS_ON_CANCELLATION
    ):
        return
    write_task_status(task_id, "cancelled", message)


def _write_task_status_checked(
    work_dir: str, task_id: str, status: str, message: str
) -> None:
    """Write a status and verify it landed in the intended task directory.

    ``write_task_status`` intentionally logs-and-continues for unrelated
    callers.  Dispatch transitions are different: silently writing elsewhere
    would leave a reservation released but a durable state that cannot be
    retried.  Keep the existing call (and its test seam), then fall back to the
    explicit directory writer when that seam or a stale work-dir lookup did not
    persist the requested state.
    """
    write_task_status(task_id, status, message)
    persisted = task_status_service.read_task_status(work_dir)
    if not isinstance(persisted, dict) or persisted.get("status") != status:
        write_task_status_to_dir(work_dir, task_id, status, message)
        persisted = task_status_service.read_task_status(work_dir)
    if not isinstance(persisted, dict) or persisted.get("status") != status:
        raise RuntimeError(f"任务状态未能持久化: {task_id} -> {status}")


async def _safe_publish_message(task_id: str, message: SystemMessage) -> None:
    """Publish a notification without masking durable terminal-state writes."""
    try:
        await redis_manager.publish_message(task_id, message)
    except Exception as exc:
        logger.warning(
            "任务通知发送失败，继续持久化终态: task_id={}, error_type={}",
            task_id,
            type(exc).__name__,
        )


def _check_dispatch_guard(work_dir: str, task_id: str) -> str | None:
    """Return a conflict reason when a task is already being dispatched."""
    if task_id in _active_tasks:
        return "任务仍在运行中"
    prior_state = (read_task_status(work_dir) or {}).get("status")
    if prior_state in _NON_DISPATCHABLE_STATES:
        return f"任务处于 {prior_state} 状态，不可重复调度"
    return None



def _finalize_docx_and_manifest(
    task_id: str,
    export_profile: ExportProfile | str | None = DEFAULT_MODELING_EXPORT_PROFILE,
) -> dict:
    """完成 DOCX、审计、候选清单和最终技术验收。

    任一步失败都会向调用方抛出异常，任务不得提前标记为 completed。
    Roadmap C & P1-5: 失败保留上一版完整产物，新导出在校验后才发布（不混入临时文件）。
    """
    work_dir = get_work_dir(task_id)
    manifest_path = os.path.join(work_dir, "candidate_manifest.json")
    docx_path = os.path.join(work_dir, "res.docx")
    # Backup existing valid deliverables before attempting new export
    backups: dict[str, str] = {}
    for p in [manifest_path, docx_path]:
        if os.path.isfile(p):
            bak = p + ".bak"
            try:
                import shutil

                shutil.copy2(p, bak)
                backups[p] = bak
            except OSError:
                pass
            # Remove manifest proactively to avoid stale candidate masquerading, but keep docx backup
            if p == manifest_path:
                try:
                    os.remove(p)
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
        # Success: remove backups
        for bak in backups.values():
            try:
                os.remove(bak)
            except OSError:
                pass
        return report
    except Exception:
        # Failure: restore previous valid deliverables
        for orig, bak in backups.items():
            if os.path.isfile(bak):
                try:
                    os.replace(bak, orig)
                except OSError:
                    pass
            else:
                # If no backup (first success), ensure no partial new file remains
                if orig == manifest_path:
                    try:
                        os.remove(orig)
                    except FileNotFoundError:
                        pass
                # For docx, if we had no backup, remove the newly generated partial docx
                # to avoid hash mismatch with restored manifest
                if orig == docx_path and os.path.isfile(orig):
                    # Only remove if we had a backup (meaning we overwrote a valid docx)
                    # If no backup, the docx was newly created and should be removed on failure
                    # to keep work_dir consistent (no valid deliverable yet)
                    try:
                        # Check if manifest was restored (has_backup); if not, remove docx as well
                        if manifest_path in backups:
                            os.remove(orig)
                    except OSError:
                        pass
        # 首轮运行没有旧备份可回滚时，循环不会覆盖新写出的清单；
        # 审计失败后必须移除这份从未通过校验的 candidate_manifest，避免假发布。
        if manifest_path not in backups and os.path.isfile(manifest_path):
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
        write_task_status(task_id, "failed", message)
        await _safe_publish_message(
            task_id,
            SystemMessage(content=message, type="error"),
        )
        return False

    # 纵深防御：completed 必须同时满足技术验收通过和主产物集在盘齐全。
    try:
        acceptance_work_dir = get_work_dir(task_id)
    except FileNotFoundError:
        acceptance_work_dir = None
    if acceptance_work_dir is not None:
        from app.tools.task_state_diagnosis import MAIN_ARTIFACTS

        missing_artifacts = [
            name
            for name in MAIN_ARTIFACTS
            if not os.path.isfile(os.path.join(acceptance_work_dir, name))
        ]
        if missing_artifacts:
            message = f"技术验收通过但主产物缺失：{missing_artifacts}，不能登记完成。"
            write_task_status(task_id, "failed", message)
            await _safe_publish_message(
                task_id,
                SystemMessage(content=message, type="error"),
            )
            return False

    write_task_status(task_id, "completed", "任务处理完成")
    await _safe_publish_message(
        task_id,
        SystemMessage(content="任务处理完成", type="success"),
    )
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


class ProviderConfig(BaseModel):
    """One optional runtime provider configuration block.

    The API keeps the frontend's camelCase wire format while validating the
    provider type and context-window bounds before any settings are touched.
    Empty strings are accepted for backwards-compatible forms and mean
    "preserve the current value" at save time.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    api_key: str | None = Field(default=None, alias="apiKey")
    base_url: str | None = Field(default=None, alias="baseUrl")
    model_id: str | None = Field(default=None, alias="modelId")
    api_type: ApiType | None = Field(default=None, alias="apiType")
    context_window: int | None = Field(
        default=None,
        alias="contextWindow",
        ge=1,
        le=1_000_000,
    )

    @field_validator("api_type", "context_window", mode="before")
    @classmethod
    def _empty_form_value_is_unset(cls, value):
        return None if value == "" else value


class SaveApiConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coordinator: ProviderConfig = Field(default_factory=ProviderConfig)
    modeler: ProviderConfig = Field(default_factory=ProviderConfig)
    coder: ProviderConfig = Field(default_factory=ProviderConfig)
    writer: ProviderConfig = Field(default_factory=ProviderConfig)
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
    guidance_id: str | None = None


class GuidanceResponse(BaseModel):
    task_id: str
    target: str
    status: str
    audit_file: str
    guidance_id: str | None = None
    consumed: bool = False


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
    block: ProviderConfig, current_base_url: str | None
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
    new_base_url = _normalize_base_url_for_comparison(block.base_url)
    if not new_base_url:
        return
    if new_base_url == _normalize_base_url_for_comparison(current_base_url):
        return
    if not block.api_key:
        raise HTTPException(
            status_code=422,
            detail="更换 Base URL 必须同时提供该端点的 API Key，防止现有密钥被发往新端点",
        )


def _plan_agent_config_update(
    block: ProviderConfig, prefix: str
) -> Dict[str, Any]:
    """Validate one provider block into a settings update without side effects."""
    planned: Dict[str, Any] = {}
    if block.api_key:
        planned[f"{prefix}_API_KEY"] = block.api_key
    if block.model_id:
        planned[f"{prefix}_MODEL"] = block.model_id
    if block.base_url:
        planned[f"{prefix}_BASE_URL"] = _validated_llm_base_url(block.base_url)
    if block.api_type is not None:
        planned[f"{prefix}_API_TYPE"] = block.api_type
    if block.context_window is not None:
        planned[f"{prefix}_CONTEXT_WINDOW"] = block.context_window
    return planned


@router.post("/save-api-config", response_model=SaveApiConfigResponse)
async def save_api_config(request: SaveApiConfigRequest):
    """
    保存验证成功的 API 配置到当前进程 settings，不写入 .env.dev。
    """
    async with _api_config_lock:
        # Validate endpoint/key pairing while holding the same lock used for
        # the eventual update.  This prevents a concurrent save from changing
        # the comparison baseline between validation and application.
        _require_api_key_for_new_base_url(
            request.coordinator, settings.COORDINATOR_BASE_URL
        )
        _require_api_key_for_new_base_url(request.modeler, settings.MODELER_BASE_URL)
        _require_api_key_for_new_base_url(request.coder, settings.CODER_BASE_URL)
        _require_api_key_for_new_base_url(request.writer, settings.WRITER_BASE_URL)

        # Phase 1: calculate all settings values without mutating global state.
        planned: Dict[str, Any] = {}
        try:
            for field_name, prefix in _AGENT_CONFIG_BLOCKS:
                planned.update(
                    _plan_agent_config_update(getattr(request, field_name), prefix)
                )
            if request.openalex_email:
                planned["OPENALEX_EMAIL"] = request.openalex_email
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="LLM Base URL 配置不合法") from exc
        except Exception:
            logger.exception("保存配置失败")
            raise HTTPException(status_code=500, detail="保存配置失败")

        # Phase 2: apply as one transaction with best-effort rollback if a
        # settings assignment fails midway.
        applied: list[Tuple[str, Any]] = []
        try:
            for attr, value in planned.items():
                applied.append((attr, getattr(settings, attr)))
                setattr(settings, attr, value)
        except Exception:
            for attr, previous in reversed(applied):
                try:
                    setattr(settings, attr, previous)
                except Exception:
                    logger.exception("配置回滚失败: {}", attr)
            logger.exception("保存配置失败")
            raise HTTPException(status_code=500, detail="保存配置失败")

        return {
            "success": True,
            "message": "配置已保存到当前后端进程，重启后需重新配置或写入 .env.dev",
            "scope": "runtime",
            "persisted": False,
        }


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


def _write_input_manifest(
    work_dir: str | Path,
    task_id: str,
    files_info: list[dict[str, Any]],
) -> Path:
    """持久化任务初始输入文件清单（含安全文件名、相对路径、文件大小与 SHA-256 哈希）。"""
    manifest_data = {
        "schema_version": "mathmodel.input-manifest.v1",
        "task_id": task_id,
        "created_at": datetime.datetime.now().isoformat(),
        "files": files_info,
    }
    manifest_path = Path(work_dir) / "input_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_path


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

    example_records: list[dict[str, Any]] = []
    current_files = get_current_files(example_dir, "data")
    for file in current_files:
        safe_filename = ensure_safe_filename(file)
        src_file = os.path.join(example_dir, file)
        dst_file = os.path.join(work_dir, safe_filename)
        shutil.copy2(src_file, dst_file)
        with open(dst_file, "rb") as f_in:
            f_bytes = f_in.read()
            example_records.append({
                "name": safe_filename,
                "relative_path": safe_filename,
                "size_bytes": len(f_bytes),
                "sha256": hashlib.sha256(f_bytes).hexdigest(),
            })
    _write_input_manifest(work_dir, task_id, example_records)
    # 存储任务ID
    reserved_cancel_event = _reserve_active_task(task_id)
    if reserved_cancel_event is None:
        raise HTTPException(status_code=409, detail="任务仍在运行中")
    try:
        await redis_manager.set(f"task_id:{task_id}", task_id)

        logger.info(f"Scheduling runner for task_id: {task_id}")
        _schedule_reserved_runner(
            task_id,
            reserved_cancel_event,
            run_modeling_task_async,
            task_id,
            ques_all,
            CompTemplate.CHINA,
            FormatOutPut.Markdown,
            DEFAULT_MODELING_EXPORT_PROFILE,
        )
    except BaseException:
        _release_active_task(task_id, reserved_cancel_event)
        raise
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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if len(ques_all) > settings.MAX_PROBLEM_TEXT_CHARS:
        raise HTTPException(status_code=413, detail="题目文本超过大小上限")

    # P1-2: atomic idempotency check+record via per-key async lock
    # Hold lock from work_dir creation through record to prevent concurrent same-key double runner
    _idem_lock = _get_idempotency_lock(idempotency_key)
    async with _idem_lock:
        task_id = create_task_id()
        work_dir = create_work_dir(task_id)
        # Roadmap C: init durable budget (resume inherits, never resets)
        try:
            from app.services.task_budget import init_budget

            init_budget(work_dir, task_id)
        except Exception:
            pass

        try:
            # 如果有上传文件，流式保存，避免将不受信任内容整体读入进程内存。
            uploaded_records: list[dict[str, Any]] = []
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
                    with open(data_file_path, "rb") as f_in:
                        f_hash = hashlib.sha256(f_in.read()).hexdigest()
                    uploaded_records.append({
                        "name": safe_filename,
                        "relative_path": safe_filename,
                        "size_bytes": file_size,
                        "sha256": f_hash,
                    })
                    logger.info(f"上传文件已保存: {safe_filename} ({file_size} bytes)")
            else:
                logger.warning("没有上传文件")
            _write_input_manifest(work_dir, task_id, uploaded_records)
        except HTTPException:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise
        except Exception:
            shutil.rmtree(work_dir, ignore_errors=True)
            logger.exception("保存上传文件失败")
            raise HTTPException(status_code=400, detail="保存上传文件失败")

        # Idempotency check (roadmap B-2): same key + same content -> replay, same key + different -> 409
        # Include behavior-affecting params in hash (P1-2 review)
        try:
            file_hashes = compute_file_hashes(uploaded_records)
            guidance_hash = compute_guidance_hash(guidance_content)
            ct_val = comp_template.value if hasattr(comp_template, "value") else str(comp_template)
            fo_val = format_output.value if hasattr(format_output, "value") else str(format_output)
            ep_val = export_profile.value if hasattr(export_profile, "value") else str(export_profile)
            from app.services.idempotency import build_request_hash

            request_hash = build_request_hash(
                ques_all, ct_val, fo_val, ep_val, file_hashes, guidance_hash,
                require_model_review=require_model_review,
                guidance_target=guidance_target,
                guidance_purpose=guidance_purpose,
            )
            existing, conflict = check_idempotency(idempotency_key, request_hash)
            if conflict:
                shutil.rmtree(work_dir, ignore_errors=True)
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error_code": "idempotency_conflict",
                        "message": conflict,
                        "retryable": False,
                        "idempotency_key": idempotency_key,
                    },
                )
            if existing:
                shutil.rmtree(work_dir, ignore_errors=True)
                try:
                    status_payload = get_single_task_status(existing)
                    return {
                        "task_id": existing,
                        "status": status_payload.get("task_status", "processing"),
                        "idempotent_replay": True,
                        "idempotency_key": idempotency_key,
                    }
                except FileNotFoundError:
                    pass
                except Exception:
                    return {"task_id": existing, "status": "processing", "idempotent_replay": True, "idempotency_key": idempotency_key}
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"幂等检查失败，继续创建新任务: {type(exc).__name__}")

        # Reserve before the first scheduling-side effect.
        reserved_cancel_event = _reserve_active_task(task_id)
        if reserved_cancel_event is None:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise HTTPException(status_code=409, detail="任务仍在运行中")
        try:
            await redis_manager.set(f"task_id:{task_id}", task_id)
            if guidance_content.strip():
                normalized_guidance = user_input_queue.normalize_content(
                    guidance_content.strip()
                )
                if not user_input_queue.push(
                    task_id, normalized_guidance, guidance_target
                ):
                    raise HTTPException(status_code=429, detail="预注入引导队列已满或目标无效")
                _append_guidance_audit(
                    work_dir,
                    task_id=task_id,
                    target=guidance_target,
                    purpose=guidance_purpose,
                    source="operator",
                    content=normalized_guidance,
                )
            logger.info(f"Scheduling runner for task_id: {task_id}")
            _schedule_reserved_runner(
                task_id,
                reserved_cancel_event,
                run_modeling_task_async,
                task_id,
                ques_all,
                comp_template,
                format_output,
                export_profile,
                require_model_review=require_model_review,
            )
            # Record idempotency after successful reservation (still inside lock)
            try:
                file_hashes2 = compute_file_hashes(uploaded_records)
                guidance_hash2 = compute_guidance_hash(guidance_content)
                ct_val2 = comp_template.value if hasattr(comp_template, "value") else str(comp_template)
                fo_val2 = format_output.value if hasattr(format_output, "value") else str(format_output)
                ep_val2 = export_profile.value if hasattr(export_profile, "value") else str(export_profile)
                from app.services.idempotency import build_request_hash as _build_hash2

                request_hash2 = _build_hash2(
                    ques_all, ct_val2, fo_val2, ep_val2, file_hashes2, guidance_hash2,
                    require_model_review=require_model_review,
                    guidance_target=guidance_target,
                    guidance_purpose=guidance_purpose,
                )
                record_idempotency(idempotency_key, request_hash2, task_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"记录幂等键失败: {type(exc).__name__}")
        except BaseException:
            _release_active_task(task_id, reserved_cancel_event)
            raise
        return {"task_id": task_id, "status": "processing", "idempotency_key": idempotency_key}


async def run_modeling_task_async(
    task_id: str,
    ques_all: str,
    comp_template: CompTemplate,
    format_output: FormatOutPut,
    export_profile: ExportProfile = DEFAULT_MODELING_EXPORT_PROFILE,
    recovery_context: str = "",
    require_model_review: bool = False,
    cancel_event: asyncio.Event | None = None,
):
    """异步执行建模任务。

    Args:
        task_id: 任务 ID。
        ques_all: 完整题目信息。
        comp_template: 竞赛模板类型。
        format_output: 输出格式。
    """
    if cancel_event is None:
        cancel_event = _reserve_active_task(task_id)
        if cancel_event is None:
            raise RuntimeError("任务已在运行中")

    workflow_completed = False
    task: asyncio.Task | None = None
    try:
        # Claim the placeholder before any publish/sleep/workflow prelude.  If
        # one of those steps fails, the finally block still owns the same token.
        _claim_active_task(task_id, cancel_event)
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

        await redis_manager.publish_message(
            task_id,
            SystemMessage(content="任务开始处理"),
        )

        # 给一个短暂的延迟，确保 WebSocket 有机会连接
        await asyncio.sleep(1)

        workflow = MathModelWorkFlow()
        workflow.cancel_event = cancel_event
        task = asyncio.create_task(
            workflow.execute(problem, recovery_context=recovery_context)
        )
        _bind_workflow_task(task_id, cancel_event, task)

        # 设置超时时间（5 小时）
        workflow_result = await asyncio.wait_for(task, timeout=3600 * 5)
        if workflow_result == "waiting_review":
            write_task_status(task_id, "waiting_review", "任务等待人工确认建模方案")
            await _safe_publish_message(
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
        # P1-4: check cancel before finalizing; export runs in thread but must respect cancel
        if cancel_event.is_set():
            logger.info(f"任务 {task_id} 在导出前检测到取消，终止交付")
            _write_cancelled_status_if_active(task_id, "任务在导出前已取消")
            await _safe_publish_message(task_id, SystemMessage(content="任务在导出前已取消", type="warning"))
            return
        write_task_status(task_id, "finalizing", "工作流完成，正在生成并验收最终产物")
        await _safe_publish_message(
            task_id,
            SystemMessage(content="工作流完成，正在生成并验收最终产物"),
        )
        # Roadmap C: run sync Pandoc/TeX export in thread to keep /status and /cancel responsive
        final_report = await asyncio.to_thread(_finalize_docx_and_manifest, task_id, export_profile)
        # P1-4: re-check cancel after export; do not let completed overwrite cancelled
        if cancel_event.is_set():
            logger.info(f"任务 {task_id} 在导出后检测到取消，终止交付")
            _write_cancelled_status_if_active(task_id, "任务在导出后已取消")
            await _safe_publish_message(task_id, SystemMessage(content="任务在导出后已取消", type="warning"))
            return
        if not await _apply_final_acceptance_status(task_id, final_report):
            return
    except asyncio.CancelledError:
        logger.info(f"任务 {task_id} 被取消")
        _write_cancelled_status_if_active(task_id, "任务已停止")
        await _safe_publish_message(
            task_id,
            SystemMessage(content="任务已停止", type="warning"),
        )
    except Exception as e:
        phase = "最终产物收尾失败" if workflow_completed else "任务执行失败"
        logger.error(f"任务 {task_id} {phase}: {type(e).__name__}")
        write_task_status(task_id, "failed", f"{phase}: {e}")
        await _safe_publish_message(
            task_id,
            SystemMessage(content=f"{phase}: {str(e)}", type="error"),
        )
    finally:
        _release_active_task(task_id, cancel_event)
        user_input_queue.clear(task_id)



class CancelTaskResponse(BaseModel):
    success: bool
    message: str
    detail: str | None = None
    cancelled: bool | None = None


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
    # Idempotent guidance: same guidance_id returns existing receipt without duplicating queue
    if request.guidance_id:
        existing = user_input_queue.get_guidance_receipt(safe_task_id, request.guidance_id)
        if existing is not None:
            status = existing.get("status", "accepted")
            audit_file = "internal_guidance_audit.jsonl"
            # If already consumed, report consumed, else accepted
            return GuidanceResponse(
                task_id=safe_task_id,
                target=request.target,
                status="consumed" if status == "consumed" else "accepted",
                audit_file=audit_file,
                guidance_id=request.guidance_id,
                consumed=(status == "consumed"),
            )
    if not user_input_queue.push(safe_task_id, content, request.target, guidance_id=request.guidance_id):
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
        status="accepted",
        audit_file=audit_file,
        guidance_id=request.guidance_id,
        consumed=False,
    )


@router.post("/modeling/{task_id}/cancel", response_model=CancelTaskResponse)
async def cancel_task(task_id: str):
    """取消正在运行的任务。区分“已接收”与“已停止”，调用方需轮询 /tasks/{id} 确认。"""
    safe_task_id = _require_safe_task_id(task_id)
    if safe_task_id not in _active_tasks:
        # Check persisted status: if already cancelled/completed, report correctly
        try:
            work_dir = get_work_dir(safe_task_id)
            persisted = read_task_status(work_dir)
            if persisted and persisted.get("status") == "cancelled":
                return CancelTaskResponse(success=True, message="任务已停止", detail="already_cancelled", cancelled=True)
            if persisted and persisted.get("status") in {"completed", "failed"}:
                return CancelTaskResponse(success=False, message="任务已结束", detail=persisted.get("status"), cancelled=False)
        except FileNotFoundError:
            pass
        return CancelTaskResponse(
            success=False,
            message="任务不存在或已完成",
            detail="not_active",
            cancelled=False,
        )

    _, cancel_event = _active_tasks[safe_task_id]
    cancel_event.set()
    logger.info(f"已发送取消信号给任务 {safe_task_id}")
    # P1-4: do not claim actually stopped; let finally block mark cancelled and client polls
    # Brief wait to see if task exits quickly (e.g., was in sleep), but do not block long
    await asyncio.sleep(0.3)
    still_active = safe_task_id in _active_tasks
    if still_active:
        return CancelTaskResponse(
            success=True,
            message="停止指令已接收，执行仍在收尾，需轮询 /tasks/{id} 确认已停止",
            detail="accepted",
            cancelled=False,
        )
    return CancelTaskResponse(
        success=True,
        message="任务已停止",
        detail="cancelled",
        cancelled=True,
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

    guard_reason = _check_dispatch_guard(work_dir, safe_task_id)
    if guard_reason is not None:
        raise HTTPException(status_code=409, detail=guard_reason)

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

    reserved_cancel_event = _reserve_active_task(safe_task_id)
    if reserved_cancel_event is None:
        raise HTTPException(status_code=409, detail="任务仍在运行中")
    state_snapshot: dict[str, bytes | None] | None = None
    scheduled_task: asyncio.Task | None = None
    try:
        state_snapshot = _snapshot_files(
            (
                os.path.join(work_dir, "modeling_decision.json"),
                os.path.join(work_dir, "task_status.json"),
            )
        )
        # Redis/publish are prelude operations.  Do them before changing the
        # decision or durable status so a broker outage leaves waiting_review
        # retryable through the same approval endpoint.
        await redis_manager.set(f"task_id:{safe_task_id}", safe_task_id)
        await redis_manager.publish_message(
            safe_task_id,
            SystemMessage(content="建模方案已确认，继续代码求解与论文写作"),
        )
        _mark_modeling_decision_approved(
            work_dir,
            "" if request is None else request.comment,
        )
        _write_task_status_checked(
            work_dir,
            safe_task_id,
            "resuming",
            "建模方案已确认，任务续传中",
        )
        scheduled_task = _schedule_reserved_runner(
            safe_task_id,
            reserved_cancel_event,
            run_resume_task_async,
            safe_task_id,
        )
    except BaseException:
        try:
            await _rollback_dispatch(scheduled_task, state_snapshot)
        finally:
            _release_active_task(safe_task_id, reserved_cancel_event)
        raise
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
    guard_reason = _check_dispatch_guard(work_dir, safe_task_id)
    if guard_reason is not None:
        raise HTTPException(status_code=409, detail=guard_reason)
    prior_state = (read_task_status(work_dir) or {}).get("status")
    if prior_state != "waiting_review":
        raise HTTPException(status_code=409, detail="仅 waiting_review 状态可退回建模方案")

    checkpoint_manager = CheckpointManager(work_dir)
    checkpoint = checkpoint_manager.load()
    if checkpoint is None:
        raise HTTPException(status_code=404, detail="未找到可修订的检查点")
    normalized_comment = user_input_queue.normalize_content(comment)
    reserved_cancel_event = _reserve_active_task(safe_task_id)
    if reserved_cancel_event is None:
        raise HTTPException(status_code=409, detail="任务仍在运行中")
    state_snapshot: dict[str, bytes | None] | None = None
    scheduled_task: asyncio.Task | None = None
    try:
        state_snapshot = _snapshot_files(
            (
                os.path.join(work_dir, "checkpoint.json"),
                os.path.join(work_dir, "modeling_decision.json"),
                os.path.join(work_dir, "task_status.json"),
                os.path.join(work_dir, "internal_guidance_audit.jsonl"),
            )
        )
        # The notification is the only external prelude.  Do it before
        # consuming the one-shot revision budget; a broker outage therefore
        # leaves the checkpoint/decision in waiting_review for a retry.
        await redis_manager.publish_message(
            safe_task_id,
            SystemMessage(content="建模方案已退回，正在按审查意见修订", type="warning"),
        )

        try:
            checkpoint_manager.record_modeling_revision_request()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        _append_guidance_audit(
            work_dir,
            task_id=safe_task_id,
            target="modeler",
            purpose="modeling",
            source="codex",
            content=normalized_comment,
        )
        _mark_modeling_decision_revision_requested(work_dir, normalized_comment)
        _write_task_status_checked(
            work_dir,
            safe_task_id,
            "revising",
            "建模方案已退回，正在按审查意见修订",
        )
        scheduled_task = _schedule_reserved_runner(
            safe_task_id,
            reserved_cancel_event,
            run_revise_modeling_async,
            safe_task_id,
            normalized_comment,
        )
        # Queue the advisory only after all durable mutations and runner
        # registration succeeded.  The runner cannot start until this handler
        # yields, so it still sees the guidance while a failed queue operation
        # can cancel the just-created task and roll back the transaction.
        if not user_input_queue.push(safe_task_id, normalized_comment, "modeler"):
            raise HTTPException(status_code=429, detail="建模修订引导队列已满")
    except BaseException:
        try:
            await _rollback_dispatch(scheduled_task, state_snapshot)
        finally:
            _release_active_task(safe_task_id, reserved_cancel_event)
        raise
    return ResumeTaskResponse(task_id=safe_task_id, status="revising")


_PRISTINE_FRAMEWORK_MANAGEMENT_FILES: frozenset[str] = frozenset({
    "task_status.json",
    "checkpoint.json",
    "task_request.json",
    "problem_contract.json",
    "modeler_plan.json",
    "modeler_plan.md",
    "modeling_decision.json",
    "modeling_decision.md",
    "input_manifest.json",
    "internal_guidance_audit.jsonl",
    "guidance.json",
    "questions.txt",
    USAGE_REPORT_FILENAME,
})


_WINDOWS_RESERVED_DEVICES: frozenset[str] = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})


def is_task_pristine_for_takeover(
    checkpoint: TaskCheckpoint | None,
    work_dir: str | Path,
) -> tuple[bool, str]:
    """严格判定任务是否处于未发生任何代码执行、求解产物生成或返修记录的 Pristine 状态。"""
    if checkpoint is None:
        return False, "该任务未启用可审计的建模人工门禁"
    if not checkpoint.require_model_review:
        return False, "该任务未启用可审计的建模人工门禁"
    if checkpoint.workflow_state in {"frozen", "completed"}:
        return False, "任务处于已冻结或已完成状态，禁止越权重置已冻结任务"
    if (
        checkpoint.completed_phases
        or checkpoint.solution_coder_responses
        or checkpoint.executed_cell_indices
        or checkpoint.has_variable_snapshot
        or checkpoint.targeted_repair_attempts > 0
        or checkpoint.paper_repair_attempts > 0
        or checkpoint.editorial_repair_attempts > 0
        or checkpoint.presentation_reflow_attempts > 0
        or checkpoint.format_compliance_attempts > 0
        or checkpoint.manual_recovery_attempts > 0
        or bool(checkpoint.last_validation_failure)
        or bool(checkpoint.last_paper_preflight_failure)
        or bool(checkpoint.last_editorial_quality_failure)
        or bool(checkpoint.last_presentation_reflow)
        or bool(checkpoint.last_format_compliance)
        or bool(checkpoint.last_manual_recovery)
        or checkpoint.quality_review_status not in {"not_run", ""}
        or bool(checkpoint.quality_review_id)
        or checkpoint.quality_review_repairs > 0
        or bool(checkpoint.quality_review_history)
        or checkpoint.quality_repair_source_prepared
        or checkpoint.workflow_state not in {"solving", "modeling"}
    ):
        return False, "任务已有求解、执行单元、变量快照、质量复核或返修记录，禁止越权重置已有执行状态"

    work_dir_path = Path(work_dir)
    static_artifacts = {
        "res.json",
        "res.md",
        "res.docx",
        "res.pdf",
        "res.tex",
        "frozen_results.json",
        "variable_snapshot.pkl",
        "variable_snapshot_meta.json",
        "checkpoint.ipynb",
        "execution_validation.json",
        "execution_validation_report.json",
        "paper_preflight_report.json",
        "paper_preflight_report.md",
        "pdf_visual_check.json",
        "submission_audit_report.json",
        "submission_audit_report.md",
        "cross_modal_audit.json",
        "final_acceptance_report.json",
        "final_acceptance_report.md",
        "execution_validation_report.json",
        "execution_quality_review.json",
        "execution_quality_review.md",
        "candidate_manifest.json",
        "support_materials.zip",
        "evidence_failure_budget.json",
        "fact_store.json",
    }
    if work_dir_path.exists():
        for item in work_dir_path.rglob("*"):
            if item.is_dir():
                if item.name == "support_materials":
                    return False, "任务目录已存在执行产物（support_materials/），禁止越权重置已有执行状态"
                continue
            rel_name = item.name
            if rel_name == "frozen_results.json":
                return False, "任务已存在冻结结果（frozen_results.json），禁止越权重置已冻结任务"
            if rel_name in static_artifacts:
                return False, f"任务目录已存在执行产物（{rel_name}），禁止越权重置已有执行状态"

    # 读取并严格校验不可歧义的输入清单
    manifest_file = work_dir_path / "input_manifest.json"
    if not manifest_file.is_file():
        return False, "输入清单（input_manifest.json）缺失，拒绝接管"
    try:
        manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    except Exception:
        return False, "输入清单（input_manifest.json）损坏，拒绝接管"
    if not isinstance(manifest_data, dict):
        return False, "输入清单格式非法，拒绝接管"
    if manifest_data.get("schema_version") != "mathmodel.input-manifest.v1":
        return False, "输入清单 schema_version 不受支持，拒绝接管"
    manifest_task_id = manifest_data.get("task_id")
    if not isinstance(manifest_task_id, str) or not manifest_task_id.strip():
        return False, "输入清单 task_id 缺失或非法，拒绝接管"
    if manifest_task_id != checkpoint.task_id:
        return False, f"输入清单 task_id ({manifest_task_id}) 与检查点 task_id ({checkpoint.task_id}) 不一致，拒绝接管"
    files = manifest_data.get("files")
    if not isinstance(files, list):
        return False, "输入清单 files 字段必须为列表，拒绝接管"

    allowed_inputs: set[str] = set()
    seen_names: set[str] = set()
    resolved_work_dir = work_dir_path.resolve()

    for f_entry in files:
        if (
            not isinstance(f_entry, dict)
            or not isinstance(f_entry.get("name"), str)
            or not isinstance(f_entry.get("relative_path"), str)
            or isinstance(f_entry.get("size_bytes"), bool)
            or not isinstance(f_entry.get("size_bytes"), int)
            or not isinstance(f_entry.get("sha256"), str)
        ):
            return False, "输入清单记录字段不完整或类型错误（size_bytes 必须为整数且非布尔值），拒绝接管"
        f_name = f_entry["name"]
        f_rel = f_entry["relative_path"]
        size_bytes = f_entry["size_bytes"]
        sha256 = f_entry["sha256"]

        # name 与 relative_path 一致性校验
        if f_name != f_rel:
            return False, f"输入清单文件名 ({f_name}) 与相对路径 ({f_rel}) 不一致，拒绝接管"

        # 与系统保留生产管理文件重名校验
        if f_name in _PRISTINE_FRAMEWORK_MANAGEMENT_FILES:
            return False, f"输入清单登记的文件与系统保留管理文件重名: {f_name}，拒绝接管"

        # 严格拦截冒号与 NTFS 备用数据流 (ADS)
        if ":" in f_name or ":" in f_rel:
            return False, f"输入清单文件路径包含冒号或备用数据流(ADS): {f_name}，拒绝接管"

        # Windows 盘符、UNC、POSIX 绝对路径与反斜杠校验
        if f_name.startswith(("/", "\\")) or f_rel.startswith(("/", "\\")):
            return False, f"输入清单包含绝对路径或 UNC 路径: {f_name}，拒绝接管"
        if "\\" in f_name or "\\" in f_rel:
            return False, f"输入清单路径不安全（包含反斜杠）: {f_name}，拒绝接管"

        # 校验各级路径片段：路径遍历、保留设备名、尾随空格与尾随句点
        parts = Path(f_name).parts
        if ".." in parts or ".." in Path(f_rel).parts:
            return False, f"输入清单文件路径包含路径遍历: {f_name}，拒绝接管"

        for part in parts:
            if part.endswith(" ") or part.endswith("."):
                return False, f"输入清单文件路径包含尾随空格或句点: {f_name}，拒绝接管"
            part_stem = part.split(".")[0].upper()
            if part_stem in _WINDOWS_RESERVED_DEVICES or part.upper() in _WINDOWS_RESERVED_DEVICES:
                return False, f"输入清单文件路径包含 Windows 保留设备名: {f_name}，拒绝接管"

        # 非法特殊字符校验
        if any(c in f_name for c in '<>"|?*'):
            return False, f"输入清单文件路径包含非法字符: {f_name}，拒绝接管"

        # 解析后路径必须严格位于 work_dir.resolve() 之内
        try:
            f_resolved = (work_dir_path / f_name).resolve()
            f_resolved.relative_to(resolved_work_dir)
            if f_resolved == resolved_work_dir:
                return False, f"输入清单文件指向工作目录本身: {f_name}，拒绝接管"
        except Exception:
            return False, f"输入清单文件解析路径超出工作目录范围: {f_name}，拒绝接管"

        if f_name in seen_names:
            return False, f"输入清单包含重复文件名登记: {f_name}，拒绝接管"
        seen_names.add(f_name)

        # 大小与十六进制 SHA-256 校验
        if size_bytes < 0:
            return False, f"输入文件（{f_name}）size_bytes 为负数，拒绝接管"
        if not re.fullmatch(r"^[0-9a-f]{64}$", sha256):
            return False, f"输入文件（{f_name}）SHA-256 格式非法（必须为64位小写十六进制），拒绝接管"

        f_path = work_dir_path / f_name
        if not f_path.is_file():
            return False, f"输入清单中登记的输入文件（{f_name}）缺失，拒绝接管"
        try:
            if f_path.stat().st_size != size_bytes:
                return False, f"输入文件（{f_name}）大小与登记不一致（被篡改），拒绝接管"
            actual_sha = hashlib.sha256(f_path.read_bytes()).hexdigest()
            if actual_sha != sha256:
                return False, f"输入文件（{f_name}）哈希与登记不一致（被篡改），拒绝接管"
        except Exception as exc:
            return False, f"校验输入文件（{f_name}）异常: {exc}，拒绝接管"
        allowed_inputs.add(f_name)

    if work_dir_path.exists():
        for item in work_dir_path.rglob("*"):
            if item.is_dir():
                continue

            rel_str = str(item.relative_to(work_dir_path)).replace("\\", "/")
            if rel_str not in _PRISTINE_FRAMEWORK_MANAGEMENT_FILES and rel_str not in allowed_inputs:
                return False, f"任务目录存在未登记的非输入文件（{rel_str}），禁止越权重置已有状态"

    return True, ""


@router.post("/modeling/{task_id}/codex-modeling", response_model=ResumeTaskResponse)
async def submit_codex_modeling(task_id: str, request: CodexModelingRequest):
    """Place a Codex-authored, contract-validated plan behind normal approval.

    The endpoint is strictly limited to a Modeler-failed task.
    It is not a route around ModelPlan validation or downstream execution gates,
    and cannot override a frozen or executing task.
    """
    safe_task_id = _require_safe_task_id(task_id)
    try:
        work_dir = get_work_dir(safe_task_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在")

    lock = _get_task_lock(safe_task_id)
    async with lock:
        if safe_task_id in _active_tasks:
            raise HTTPException(status_code=409, detail="任务仍在运行中")

        status_info = read_task_status(work_dir) or {}
        prior_state = status_info.get("status")
        if prior_state != "failed":
            raise HTTPException(
                status_code=409,
                detail="仅 failed 状态下可触发 Codex 建模接管，禁止越权重置其他状态或已冻结任务",
            )

        checkpoint_manager = CheckpointManager(work_dir)
        checkpoint = checkpoint_manager.load()
        pristine_ok, reason = is_task_pristine_for_takeover(checkpoint, work_dir)
        if not pristine_ok:
            raise HTTPException(status_code=409, detail=reason)

        if not (checkpoint.require_model_review or settings.HUMAN_MODEL_GATE_ENABLED):
            raise HTTPException(status_code=409, detail="未启用人工审核门禁的任务不支持接管")

        workflow = MathModelWorkFlow()
        try:
            workflow.accept_codex_modeling(safe_task_id, request.modeler_response)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        note = request.comment.strip()[:1000] or "当前 Codex 在 Modeler 失败状态提交结构化建模方案。"
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
    guard_reason = _check_dispatch_guard(work_dir, safe_task_id)
    if guard_reason is not None:
        raise HTTPException(status_code=409, detail=guard_reason)
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

    # 审批提交时按当前盘上证据重算复核编号：旧报告、旧编号不能批准新结果；
    # BLOCKED（证据缺失/漂移）一律拒绝 approve，只能返修重建。
    current_report = build_execution_quality_review(work_dir)
    current_id = str(current_report.get("review_id", ""))
    if request.review_id.strip() != current_id or checkpoint.quality_review_id != current_id:
        raise HTTPException(
            status_code=409,
            detail="结果、冻结登记或方案版本已变化，旧审批编号不能批准当前结果；请重新读取最新质量复核报告",
        )
    if request.action == "approve" and current_report.get("status") == "BLOCKED":
        raise HTTPException(
            status_code=409,
            detail="质量复核存在阻断项（证据缺失或哈希漂移），不能批准；请使用 action=repair 重建证据",
        )

    requested: list[str] = []
    guidance = ""
    if request.action == "approve":
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
        guidance = (
            "【执行质量复核定向返修】只重新求解以下子题："
            + "、".join(requested)
            + "。必须实际执行、覆盖对应结果文件并重新记录证据。\n审查意见："
            + comment
        )
        status_message = "执行质量复核已退回指定子题，开始定向返修"

    reserved_cancel_event = _reserve_active_task(safe_task_id)
    if reserved_cancel_event is None:
        raise HTTPException(status_code=409, detail="任务仍在运行中")
    state_snapshot: dict[str, bytes | None] | None = None
    scheduled_task: asyncio.Task | None = None
    try:
        state_snapshot = _snapshot_files(
            (
                os.path.join(work_dir, "checkpoint.json"),
                os.path.join(work_dir, "task_status.json"),
                os.path.join(work_dir, "internal_guidance_audit.jsonl"),
            )
        )
        # Do not consume the quality-review approval/repair budget until the
        # external broker prelude succeeds.  This keeps a failed dispatch in
        # waiting_quality_review and allows the exact review entry to retry.
        await redis_manager.set(f"task_id:{safe_task_id}", safe_task_id)
        await redis_manager.publish_message(
            safe_task_id, SystemMessage(content=status_message, type="warning")
        )
        try:
            if request.action == "approve":
                manager.approve_quality_review(request.review_id.strip(), comment)
            else:
                manager.request_quality_repair(
                    request.review_id.strip(), requested, comment
                )
                _append_guidance_audit(
                    work_dir,
                    task_id=safe_task_id,
                    target="coder",
                    purpose="execution",
                    source="codex",
                    content=guidance,
                )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _write_task_status_checked(
            work_dir,
            safe_task_id,
            "resuming",
            status_message,
        )
        scheduled_task = _schedule_reserved_runner(
            safe_task_id,
            reserved_cancel_event,
            run_resume_task_async,
            safe_task_id,
            comment,
        )
    except BaseException:
        try:
            await _rollback_dispatch(scheduled_task, state_snapshot)
        finally:
            _release_active_task(safe_task_id, reserved_cancel_event)
        raise
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

    guard_reason = _check_dispatch_guard(work_dir, safe_task_id)
    if guard_reason is not None:
        raise HTTPException(status_code=409, detail=guard_reason)

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
        from app.tools.task_state_diagnosis import INFLIGHT_STATES

        if checkpoint is not None and (
            (checkpoint.workflow_state or "") in INFLIGHT_STATES
            or (checkpoint.quality_review_status or "") in {"pending", "repair_requested"}
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"任务状态矛盾（completed + {checkpoint.workflow_state}/"
                    f"{checkpoint.quality_review_status}），不能盲目续传；"
                    "请先运行 python -m app.tools.task_state_diagnosis --work-dir <dir> 核对，"
                    "再用带操作人与理由的 --reconcile 显式修复。"
                ),
            )
        raise HTTPException(status_code=409, detail="任务已完成，无需续传")
    if prior_state == "waiting_review":
        raise HTTPException(status_code=409, detail="任务等待建模方案确认，请使用 approve-modeling")
    if prior_state == "waiting_quality_review":
        raise HTTPException(status_code=409, detail="任务等待执行质量复核，请使用 execution-review")

    manual_recovery_requested = False
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
        manual_recovery_requested = True

    recovery_context = _build_recovery_context(prior_status, checkpoint, request)
    snapshot = None if checkpoint is not None else load_task_request_snapshot(work_dir)
    if checkpoint is None and snapshot is None:
        raise HTTPException(
            status_code=404,
            detail="未找到检查点或任务请求快照；该历史任务无法安全自动重启",
        )
    if snapshot is not None and snapshot["task_id"] != safe_task_id:
        raise HTTPException(status_code=409, detail="任务请求快照与任务 ID 不一致")

    reserved_cancel_event = _reserve_active_task(safe_task_id)
    if reserved_cancel_event is None:
        raise HTTPException(status_code=409, detail="任务仍在运行中")
    state_snapshot: dict[str, bytes | None] | None = None
    scheduled_task: asyncio.Task | None = None
    try:
        state_snapshot = _snapshot_files(
            (
                os.path.join(work_dir, "checkpoint.json"),
                os.path.join(work_dir, "task_status.json"),
            )
        )
        # 存储任务ID，续期供 ws 鉴权使用
        await redis_manager.set(f"task_id:{safe_task_id}", safe_task_id)

        logger.info(f"Scheduling resume runner for task_id: {safe_task_id}")
        if manual_recovery_requested:
            try:
                checkpoint_manager.authorize_manual_execution_recovery(
                    request.recovery_mode, request.note
                )
                checkpoint = checkpoint_manager.load()
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            recovery_context = _build_recovery_context(
                prior_status, checkpoint, request
            )
        if checkpoint is not None:
            _write_task_status_checked(
                work_dir,
                safe_task_id,
                "resuming",
                "从检查点受控续传中",
            )
            scheduled_task = _schedule_reserved_runner(
                safe_task_id,
                reserved_cancel_event,
                run_resume_task_async,
                safe_task_id,
                recovery_context,
            )
        else:
            _write_task_status_checked(
                work_dir,
                safe_task_id,
                "resuming",
                "早期失败后从任务请求快照重新开始",
            )
            scheduled_task = _schedule_reserved_runner(
                safe_task_id,
                reserved_cancel_event,
                run_modeling_task_async,
                safe_task_id,
                snapshot["ques_all"],
                CompTemplate(snapshot["comp_template"]),
                FormatOutPut(snapshot["format_output"]),
                ExportProfile(snapshot["export_profile"]),
                recovery_context=recovery_context,
                require_model_review=bool(snapshot.get("require_model_review", False)),
            )
    except BaseException:
        try:
            await _rollback_dispatch(scheduled_task, state_snapshot)
        finally:
            _release_active_task(safe_task_id, reserved_cancel_event)
        raise
    return ResumeTaskResponse(task_id=safe_task_id, status="resuming")


async def run_revise_modeling_async(
    task_id: str,
    review_comment: str,
    cancel_event: asyncio.Event | None = None,
) -> None:
    """Run the bounded ModelPlan revision and return to the review gate."""
    if cancel_event is None:
        cancel_event = _reserve_active_task(task_id)
        if cancel_event is None:
            raise RuntimeError("任务已在运行中")

    task: asyncio.Task | None = None
    try:
        _claim_active_task(task_id, cancel_event)
        logger.info(f"revise modeling plan for task_id: {task_id}")
        workflow = MathModelWorkFlow()
        workflow.cancel_event = cancel_event
        task = asyncio.create_task(workflow.revise_modeling(task_id, review_comment))
        _bind_workflow_task(task_id, cancel_event, task)
        result = await asyncio.wait_for(task, timeout=3600)
        if result != "waiting_review":
            raise RuntimeError(f"建模修订返回了意外状态: {result}")
        write_task_status(task_id, "waiting_review", "修订后的建模方案等待人工确认")
        await _safe_publish_message(
            task_id,
            SystemMessage(content="修订后的建模方案等待人工确认", type="warning"),
        )
    except asyncio.CancelledError:
        logger.info(f"建模方案修订 {task_id} 被取消")
        _write_cancelled_status_if_active(task_id, "建模方案修订已停止")
        await _safe_publish_message(
            task_id,
            SystemMessage(content="建模方案修订已停止", type="warning"),
        )
    except Exception as exc:
        logger.error(f"建模方案修订 {task_id} 失败: {type(exc).__name__}")
        try:
            _mark_modeling_decision_revision_failed(get_work_dir(task_id), str(exc))
        except Exception:
            logger.exception("建模修订失败后更新审查文件异常")
        write_task_status(task_id, "failed", f"建模方案修订失败: {exc}")
        await _safe_publish_message(
            task_id,
            SystemMessage(content=f"建模方案修订失败: {exc}", type="error"),
        )
    finally:
        _release_active_task(task_id, cancel_event)
        user_input_queue.clear(task_id)


async def run_resume_task_async(
    task_id: str,
    recovery_context: str = "",
    cancel_event: asyncio.Event | None = None,
):
    """异步执行任务续传。

    Args:
        task_id: 待续传的任务 ID。
    """
    if cancel_event is None:
        cancel_event = _reserve_active_task(task_id)
        if cancel_event is None:
            raise RuntimeError("任务已在运行中")

    workflow_completed = False
    task: asyncio.Task | None = None
    try:
        _claim_active_task(task_id, cancel_event)
        logger.info(f"resume modeling task for task_id: {task_id}")
        write_task_status(task_id, "resuming", "任务续传中")

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
        _bind_workflow_task(task_id, cancel_event, task)

        workflow_result = await asyncio.wait_for(task, timeout=3600 * 5)
        if workflow_result == "waiting_review":
            write_task_status(task_id, "waiting_review", "任务等待人工确认建模方案")
            await _safe_publish_message(
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
        if cancel_event.is_set():
            logger.info(f"任务 {task_id} 在续传导出前检测到取消，终止交付")
            _write_cancelled_status_if_active(task_id, "任务在导出前已取消")
            await _safe_publish_message(task_id, SystemMessage(content="任务在导出前已取消", type="warning"))
            return
        write_task_status(task_id, "finalizing", "续传完成，正在生成并验收最终产物")
        await _safe_publish_message(
            task_id,
            SystemMessage(content="续传完成，正在生成并验收最终产物"),
        )
        final_report = await asyncio.to_thread(_finalize_docx_and_manifest, task_id, export_profile)
        if cancel_event.is_set():
            logger.info(f"任务 {task_id} 在续传导出后检测到取消，终止交付")
            _write_cancelled_status_if_active(task_id, "任务在导出后已取消")
            await _safe_publish_message(task_id, SystemMessage(content="任务在导出后已取消", type="warning"))
            return
        if not await _apply_final_acceptance_status(task_id, final_report):
            return
    except asyncio.CancelledError:
        logger.info(f"任务 {task_id} 被取消")
        _write_cancelled_status_if_active(task_id, "任务已停止")
        await _safe_publish_message(
            task_id,
            SystemMessage(content="任务已停止", type="warning"),
        )
    except Exception as e:
        import traceback as _tb
        logger.error("RESUME_TRACEBACK:\n" + _tb.format_exc())
        phase = "最终产物收尾失败" if workflow_completed else "任务续传失败"
        logger.error(f"任务 {task_id} {phase}: {type(e).__name__}")
        write_task_status(task_id, "failed", f"{phase}: {e}")
        await _safe_publish_message(
            task_id,
            SystemMessage(content=f"{phase}: {str(e)}", type="error"),
        )
    finally:
        _release_active_task(task_id, cancel_event)
        user_input_queue.clear(task_id)
