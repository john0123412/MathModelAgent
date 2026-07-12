"""代码解释器工厂模块，根据配置创建本地或远程解释器。"""

from typing import Literal
from app.tools.base_interpreter import BaseCodeInterpreter
from app.tools.e2b_interpreter import E2BCodeInterpreter
from app.tools.local_interpreter import LocalCodeInterpreter
from app.tools.notebook_serializer import NotebookSerializer
from app.config.setting import settings
from app.utils.log_util import logger


async def create_interpreter(
    kind: Literal["remote", "local", "auto"] | None = None,
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
    selected_kind = kind or settings.CODE_INTERPRETER_KIND

    if selected_kind == "auto":
        if settings.E2B_API_KEY:
            selected_kind = "remote"
            logger.info("自动代码执行模式选择远程 E2B 沙箱")
        elif settings.ALLOW_LOCAL_CODE_EXECUTION:
            selected_kind = "local"
            logger.warning(
                "E2B 不可用，自动代码执行模式已显式降级到本地受信任开发环境"
            )
        else:
            raise RuntimeError(
                "自动代码执行模式未配置 E2B_API_KEY；本地降级仍需显式设置 "
                "ALLOW_LOCAL_CODE_EXECUTION=true"
            )

    interp: BaseCodeInterpreter
    if selected_kind == "remote":
        if not settings.E2B_API_KEY:
            raise RuntimeError(
                "远程代码沙箱未配置 E2B_API_KEY；为避免执行不可信代码，"
                "不会自动降级到本地解释器"
            )
        logger.info("使用远程代码沙箱")
        interp = await E2BCodeInterpreter.create(
            task_id=task_id,
            work_dir=work_dir,
            notebook_serializer=notebook_serializer,
        )
        await interp.initialize(timeout=timeout)  # type: ignore[reportCallIssue]
        return interp
    elif selected_kind == "local":
        if not settings.ALLOW_LOCAL_CODE_EXECUTION:
            raise RuntimeError(
                "本地代码执行默认禁用；仅在受信任的隔离开发环境中显式设置 "
                "ALLOW_LOCAL_CODE_EXECUTION=true 后才能启用"
            )
        logger.warning("已显式启用本地代码执行；仅限受信任的隔离开发环境")
        interp = LocalCodeInterpreter(
            task_id=task_id,
            work_dir=work_dir,
            notebook_serializer=notebook_serializer,
            execution_timeout=settings.LOCAL_CODE_EXECUTION_TIMEOUT_SECONDS,
        )
        await interp.initialize()
        return interp
    else:
        raise ValueError(f"未知 interpreter 类型：{selected_kind}")
