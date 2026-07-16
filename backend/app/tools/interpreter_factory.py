"""代码解释器工厂模块，根据配置创建本地或远程解释器。"""

from typing import Literal, TypedDict
from app.tools.base_interpreter import BaseCodeInterpreter
from app.tools.e2b_interpreter import E2BCodeInterpreter
from app.tools.local_interpreter import LocalCodeInterpreter
from app.tools.notebook_serializer import NotebookSerializer
from app.config.setting import settings
from app.utils.log_util import logger


InterpreterKind = Literal["remote", "local", "auto"]
SelectedInterpreterKind = Literal["remote", "local"]


class CodeExecutionStatus(TypedDict):
    """不含凭据正文的代码执行后端就绪状态。"""

    status: Literal["ready", "blocked"]
    configured_kind: InterpreterKind
    selected_kind: SelectedInterpreterKind | None
    e2b_configured: bool
    local_execution_allowed: bool
    local_execution_timeout_seconds: int
    message: str


def get_code_execution_status(
    kind: InterpreterKind | None = None,
) -> CodeExecutionStatus:
    """解析实际执行后端，并返回可安全公开的就绪状态。"""
    configured_kind = kind or settings.CODE_INTERPRETER_KIND
    e2b_configured = bool(settings.E2B_API_KEY)
    local_allowed = settings.ALLOW_LOCAL_CODE_EXECUTION

    selected_kind: SelectedInterpreterKind | None = None
    message: str
    if configured_kind == "remote":
        selected_kind = "remote" if e2b_configured else None
        message = (
            "远程 E2B 代码沙箱已就绪"
            if e2b_configured
            else "远程代码沙箱未配置 E2B_API_KEY；不会自动降级到本地解释器"
        )
    elif configured_kind == "local":
        selected_kind = "local" if local_allowed else None
        message = (
            "可信本地 Docker 代码执行已显式启用"
            if local_allowed
            else "本地代码执行默认禁用；需要显式设置 ALLOW_LOCAL_CODE_EXECUTION=true"
        )
    elif configured_kind == "auto":
        if e2b_configured:
            selected_kind = "remote"
            message = "自动模式已选择远程 E2B 代码沙箱"
        elif local_allowed:
            selected_kind = "local"
            message = "自动模式已选择显式授权的可信本地 Docker 代码执行"
        else:
            message = (
                "自动代码执行模式未配置 E2B_API_KEY；本地降级仍需显式设置 "
                "ALLOW_LOCAL_CODE_EXECUTION=true"
            )
    else:
        raise ValueError(f"未知 interpreter 类型：{configured_kind}")

    return CodeExecutionStatus(
        status="ready" if selected_kind is not None else "blocked",
        configured_kind=configured_kind,
        selected_kind=selected_kind,
        e2b_configured=e2b_configured,
        local_execution_allowed=local_allowed,
        local_execution_timeout_seconds=settings.LOCAL_CODE_EXECUTION_TIMEOUT_SECONDS,
        message=message,
    )


def _resolve_interpreter_kind(
    kind: InterpreterKind | None = None,
) -> SelectedInterpreterKind:
    runtime_status = get_code_execution_status(kind)
    selected_kind = runtime_status["selected_kind"]
    if selected_kind is None:
        raise RuntimeError(runtime_status["message"])
    return selected_kind


async def create_interpreter(
    kind: InterpreterKind | None = None,
    *,
    task_id: str,
    work_dir: str,
    notebook_serializer: NotebookSerializer,
    timeout=3000,
):
    """创建代码解释器实例。

    Args:
        kind: 解释器类型，"remote" 使用 E2B 沙箱，"local" 使用本地 Jupyter，
            "auto" 会优先 E2B，并只在显式信任本地执行时降级。
        task_id: 任务 ID。
        work_dir: 工作目录。
        notebook_serializer: Notebook 序列化器。
        timeout: 超时时间（秒）。

    Returns:
        初始化完成的代码解释器实例。

    Raises:
        ValueError: 未知的解释器类型时抛出。
    """
    configured_kind = kind or settings.CODE_INTERPRETER_KIND
    selected_kind = _resolve_interpreter_kind(kind)
    if configured_kind == "auto":
        if selected_kind == "remote":
            logger.info("自动代码执行模式选择远程 E2B 沙箱")
        else:
            logger.warning(
                "E2B 不可用，自动代码执行模式已显式降级到本地受信任开发环境"
            )

    interp: BaseCodeInterpreter
    if selected_kind == "remote":
        logger.info("使用远程代码沙箱")
        interp = await E2BCodeInterpreter.create(
            task_id=task_id,
            work_dir=work_dir,
            notebook_serializer=notebook_serializer,
        )
        await interp.initialize(timeout=timeout)  # type: ignore[reportCallIssue]
        return interp
    elif selected_kind == "local":
        logger.warning("已显式启用本地代码执行；仅限受信任的隔离开发环境")
        interp = LocalCodeInterpreter(
            task_id=task_id,
            work_dir=work_dir,
            notebook_serializer=notebook_serializer,
            execution_timeout=settings.LOCAL_CODE_EXECUTION_TIMEOUT_SECONDS,
        )
        await interp.initialize()
        return interp
