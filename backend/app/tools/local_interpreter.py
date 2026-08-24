"""本地代码解释器模块，通过本地 Jupyter 内核执行 Python 代码。"""

from app.tools.base_interpreter import BaseCodeInterpreter
from app.tools.matplotlib_setup import build_matplotlib_init_code
from app.tools.notebook_serializer import NotebookSerializer
import asyncio
import ctypes
from concurrent.futures import ThreadPoolExecutor
import jupyter_client
from app.utils.log_util import logger
import os
import stat
import subprocess
import tempfile
import threading
import time
from app.services.redis_manager import redis_manager
from app.schemas.response import (
    OutputItem,
    ResultModel,
    StdErrModel,
    SystemMessage,
)


_KERNEL_ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "TZ")
_SENSITIVE_ENV_SUFFIXES = (
    "_API_KEY",
    "_AUTH_TOKEN",
    "_SECRET",
    "_TOKEN",
    "_PASSWORD",
)
_PR_SET_DUMPABLE = 4
# Must match the dedicated account created in backend/Dockerfile.
_LOCAL_KERNEL_UID = 10001
_LOCAL_KERNEL_GID = 10001
_KERNEL_CONNECTION_ROOT = "/tmp/mathmodelagent-kernel-connections"


def _is_sensitive_environment_variable(name: str) -> bool:
    """Identify credentials that model-generated local code must not inherit."""
    return name.upper().endswith(_SENSITIVE_ENV_SUFFIXES)


def _disable_parent_process_dumpability() -> None:
    """Prevent the local kernel from reading the backend's initial environment via /proc.

    The local execution fallback is only supported in trusted Linux Docker deployments.
    Removing variables from ``os.environ`` alone is insufficient because ``/proc/<pid>/environ``
    can retain the process environment inherited at exec time.
    """
    if os.name != "posix":
        raise RuntimeError("本地代码执行仅支持受控 Linux Docker 环境")

    try:
        prctl = ctypes.CDLL(None, use_errno=True).prctl
    except (AttributeError, OSError) as exc:
        raise RuntimeError("无法启用本地代码执行的进程环境保护") from exc

    if prctl(_PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        error_number = ctypes.get_errno()
        raise RuntimeError(
            f"无法启用本地代码执行的进程环境保护（errno={error_number}）"
        )


def _drop_kernel_privileges() -> None:
    """Run the Jupyter kernel under a dedicated unprivileged account.

    ``PR_SET_DUMPABLE`` is defense in depth, but a UID boundary is the primary
    protection against same-container access to the backend process and its initial
    environment. This function runs in the kernel child immediately before exec.
    """
    if os.name != "posix" or not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise RuntimeError("本地代码执行需要受控 Linux Docker root 后端进程")

    try:
        os.setgroups([])
        os.setgid(_LOCAL_KERNEL_GID)
        os.setuid(_LOCAL_KERNEL_UID)
    except OSError as exc:
        raise RuntimeError("无法降权本地 Jupyter 内核") from exc

    if os.geteuid() != _LOCAL_KERNEL_UID or os.getegid() != _LOCAL_KERNEL_GID:
        raise RuntimeError("本地 Jupyter 内核降权校验失败")


class _UnprivilegedKernelManager(jupyter_client.KernelManager):
    """Hand the Jupyter connection file to the unprivileged kernel before exec."""

    def write_connection_file(self, **kwargs) -> None:
        super().write_connection_file(**kwargs)
        # The backend and kernel only need to read these connection details.
        os.chmod(self.connection_file, 0o440)
        os.chown(self.connection_file, _LOCAL_KERNEL_UID, 0)


class LocalCodeInterpreter(BaseCodeInterpreter):
    """基于本地 Jupyter 内核的代码解释器。"""

    def __init__(
        self,
        task_id: str,
        work_dir: str,
        notebook_serializer: NotebookSerializer,
        execution_timeout: int = 300,
    ):
        super().__init__(task_id, work_dir, notebook_serializer)
        self.km, self.kc = None, None
        self._kernel_connection_dir: str | None = None
        self._kernel_connection_file: str | None = None
        self.interrupt_signal = False
        self.execution_timeout = max(0, int(execution_timeout))
        # The Jupyter IOPub receive loop is synchronous.  Keep one executor
        # per interpreter so it never blocks the event loop and can be shut
        # down together with this interpreter's kernel.
        self._code_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=f"mma-code-{task_id[:12]}",
        )
        self._executor_shutdown = False
        self._active_executor_future: asyncio.Future | None = None

    def _strip_sensitive_parent_environment(self) -> None:
        """Remove credentials from the backend process before starting a local kernel.

        Settings retain the values required by the application, while a same-container
        Jupyter kernel can no longer recover them from its parent process environment.
        """
        for name in list(os.environ):
            if _is_sensitive_environment_variable(name):
                os.environ.pop(name, None)

    def _prepare_kernel_work_dir(self) -> None:
        """Assign this task directory to the dedicated kernel account."""
        if os.name != "posix" or not hasattr(os, "geteuid") or os.geteuid() != 0:
            raise RuntimeError("本地代码执行需要受控 Linux Docker root 后端进程")

        task_home = os.path.abspath(self.work_dir)
        os.makedirs(task_home, exist_ok=True)
        for runtime_dir in (".jupyter_runtime", ".ipython", ".matplotlib"):
            os.makedirs(os.path.join(task_home, runtime_dir), exist_ok=True)
        for root, directories, filenames in os.walk(task_home, followlinks=False):
            for name in directories:
                path = os.path.join(root, name)
                if os.path.islink(path):
                    raise RuntimeError("本地代码执行不支持任务目录中的符号链接")
                os.chown(path, _LOCAL_KERNEL_UID, _LOCAL_KERNEL_GID)
            for name in filenames:
                path = os.path.join(root, name)
                if os.path.islink(path):
                    raise RuntimeError("本地代码执行不支持任务目录中的符号链接")
                os.chown(path, _LOCAL_KERNEL_UID, _LOCAL_KERNEL_GID)

        os.chown(task_home, _LOCAL_KERNEL_UID, _LOCAL_KERNEL_GID)

    def _create_kernel_connection_file(self) -> str:
        """Create a root-managed directory for the kernel's immutable connection file.

        The task directory belongs to the unprivileged kernel user, so the root backend
        deliberately cannot write there after dropping ``DAC_OVERRIDE``. Keeping the
        connection file outside that directory also prevents kernel code from replacing
        it while the backend client is connected.
        """
        if os.name != "posix" or not hasattr(os, "geteuid") or os.geteuid() != 0:
            raise RuntimeError("本地代码执行需要受控 Linux Docker root 后端进程")

        try:
            os.makedirs(_KERNEL_CONNECTION_ROOT, mode=0o711, exist_ok=True)
            root_stat = os.lstat(_KERNEL_CONNECTION_ROOT)
            if (
                not stat.S_ISDIR(root_stat.st_mode)
                or root_stat.st_uid != 0
                or root_stat.st_mode & 0o022
            ):
                raise RuntimeError("本地 Jupyter 连接目录不安全")
            os.chmod(_KERNEL_CONNECTION_ROOT, 0o711)
            connection_dir = tempfile.mkdtemp(
                prefix="kernel-", dir=_KERNEL_CONNECTION_ROOT
            )
            os.chown(connection_dir, 0, 0)
            os.chmod(connection_dir, 0o711)
        except OSError as exc:
            raise RuntimeError("无法创建受保护的本地 Jupyter 连接目录") from exc

        self._kernel_connection_dir = connection_dir
        self._kernel_connection_file = os.path.join(connection_dir, "kernel.json")
        return self._kernel_connection_file

    def _cleanup_kernel_connection_file(self) -> None:
        """Remove only the connection file and directory created for this kernel."""
        connection_file = self._kernel_connection_file
        connection_dir = self._kernel_connection_dir
        self._kernel_connection_file = None
        self._kernel_connection_dir = None

        try:
            if connection_file and os.path.lexists(connection_file):
                if os.path.islink(connection_file):
                    raise RuntimeError("本地 Jupyter 连接文件异常")
                os.unlink(connection_file)
            if connection_dir:
                os.rmdir(connection_dir)
        except (OSError, RuntimeError) as exc:
            logger.warning(
                "清理本地 Jupyter 连接文件失败: error_type={}", type(exc).__name__
            )

    def _start_kernel(self) -> None:
        _disable_parent_process_dumpability()
        self._prepare_kernel_work_dir()
        self._strip_sensitive_parent_environment()
        connection_file = self._create_kernel_connection_file()
        self.km = _UnprivilegedKernelManager(
            kernel_name="python3",
            connection_file=connection_file,
        )
        try:
            self.km.start_kernel(
                env=self._build_kernel_env(),
                preexec_fn=_drop_kernel_privileges,
            )
            self.kc = self.km.client()
            self.kc.start_channels()
            self.kc.wait_for_ready(timeout=60)
        except Exception:
            try:
                self.km.shutdown_kernel(now=True)
            except Exception:
                pass
            self.km, self.kc = None, None
            self._cleanup_kernel_connection_file()
            raise

    def _build_kernel_env(self) -> dict[str, str]:
        """Build a minimal per-task environment for model-generated code."""
        kernel_env = {
            name: os.environ[name]
            for name in _KERNEL_ENV_ALLOWLIST
            if name in os.environ
        }
        task_home = os.path.abspath(self.work_dir)
        runtime_dir = os.path.join(task_home, ".jupyter_runtime")
        ipython_dir = os.path.join(task_home, ".ipython")
        matplotlib_dir = os.path.join(task_home, ".matplotlib")

        kernel_env.update(
            {
                "PATH": kernel_env.get("PATH", os.defpath),
                "HOME": task_home,
                "IPYTHONDIR": ipython_dir,
                "JUPYTER_RUNTIME_DIR": runtime_dir,
                "MPLCONFIGDIR": matplotlib_dir,
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
                "PYTHONNOUSERSITE": "1",
            }
        )
        return kernel_env

    async def initialize(self):
        # 本地内核一般不需异步上传文件，直接切换目录即可
        # 初始化 Jupyter 内核管理器和客户端
        logger.info("初始化本地内核")
        self._start_kernel()
        self._pre_execute_code()

    def _pre_execute_code(self):
        init_code = build_matplotlib_init_code(self.work_dir)
        # 保留本地解释器的保存钩子：生成代码即使调用 seaborn.set_theme，
        # 在最终写图前仍会恢复中文字体和统一论文样式。
        init_code += (
            "_MMA_COLORS = ['#2E5B88', '#E85D4C', '#4A9B7F', '#F5A623', '#7F7F7F', '#B8D4E8', '#D4A5A5', '#9B59B6']\n"
            "COLOR_MAP = dict(COLORS)\n"
            "COLORS = list(_MMA_COLORS)\n"
            "import matplotlib.figure as _mma_matplotlib_figure\n"
            "_MMA_CHINESE_FONTS = list(_cjk_fonts) + ['SimHei', 'Microsoft YaHei', 'SimSun', 'Noto Sans CJK SC', 'Noto Sans SC', 'DejaVu Sans']\n"
            "def _mma_apply_chinese_plot_style():\n"
            "    plt.rcParams.update({\n"
            "        'font.sans-serif': _MMA_CHINESE_FONTS,\n"
            "        'font.family': 'sans-serif',\n"
            "        'font.size': 11,\n"
            "        'axes.titlesize': 12,\n"
            "        'axes.titleweight': 'bold',\n"
            "        'axes.labelsize': 11,\n"
            "        'axes.linewidth': 1.2,\n"
            "        'axes.spines.top': False,\n"
            "        'axes.spines.right': False,\n"
            "        'axes.unicode_minus': False,\n"
            "        'xtick.labelsize': 10,\n"
            "        'ytick.labelsize': 10,\n"
            "        'legend.fontsize': 10,\n"
            "        'legend.frameon': False,\n"
            "        'figure.dpi': 150,\n"
            "        'savefig.dpi': 300,\n"
            "        'savefig.bbox': 'tight',\n"
            "        'savefig.pad_inches': 0.1,\n"
            "    })\n"
            "    plt.gca().set_prop_cycle(color=_MMA_COLORS)\n"
            "_mma_apply_chinese_plot_style()\n"
            "if not getattr(plt.savefig, '_mma_wrapped', False):\n"
            "    _mma_original_plt_savefig = plt.savefig\n"
            "    def _mma_savefig_with_style(*args, **kwargs):\n"
            "        _mma_apply_chinese_plot_style()\n"
            "        return _mma_original_plt_savefig(*args, **kwargs)\n"
            "    _mma_savefig_with_style._mma_wrapped = True\n"
            "    plt.savefig = _mma_savefig_with_style\n"
            "if not getattr(matplotlib.figure.Figure.savefig, '_mma_wrapped', False):\n"
            "    _mma_original_figure_savefig = matplotlib.figure.Figure.savefig\n"
            "    def _mma_figure_savefig_with_style(self, *args, **kwargs):\n"
            "        _mma_apply_chinese_plot_style()\n"
            "        return _mma_original_figure_savefig(self, *args, **kwargs)\n"
            "    _mma_figure_savefig_with_style._mma_wrapped = True\n"
            "    matplotlib.figure.Figure.savefig = _mma_figure_savefig_with_style\n"
            "print('学术图表样式已配置')\n"
        )
        self.execute_code_(init_code)

    def _request_kernel_interrupt(self) -> None:
        """Interrupt the current kernel from the event-loop side safely."""
        self.interrupt_signal = True
        kernel_manager = self.km
        if kernel_manager is None:
            return
        try:
            kernel_manager.interrupt_kernel()
        except Exception as exc:
            logger.warning(
                "请求中断本地代码失败: error_type={}", type(exc).__name__
            )

    async def _run_code_in_executor(self, code: str) -> list[tuple[str, str]]:
        """Run one synchronous Jupyter exchange off-loop with safe cancellation.

        ``Future.cancel()`` cannot stop a Python worker thread.  On cancellation
        or timeout we therefore interrupt the kernel first and await the worker
        future to completion before returning, so cleanup/restart cannot race a
        still-running IOPub read loop.
        """
        if self._executor_shutdown:
            raise RuntimeError("本地代码执行线程池已关闭")
        loop = asyncio.get_running_loop()
        worker_future = loop.run_in_executor(
            self._code_executor, self.execute_code_, code
        )
        self._active_executor_future = worker_future

        async def wait_for_worker():
            return await asyncio.shield(worker_future)

        try:
            if self.execution_timeout > 0:
                try:
                    return await asyncio.wait_for(
                        wait_for_worker(), timeout=self.execution_timeout
                    )
                except asyncio.TimeoutError:
                    self._request_kernel_interrupt()
                    try:
                        await wait_for_worker()
                    except Exception:
                        logger.warning("超时后等待本地执行线程结束失败")
                    return [
                        (
                            "error",
                            f"本地代码执行超过 {self.execution_timeout} 秒，已中断",
                        )
                    ]
            return await wait_for_worker()
        except asyncio.CancelledError:
            self._request_kernel_interrupt()
            try:
                await wait_for_worker()
            except Exception:
                logger.warning("取消后等待本地执行线程结束失败")
            raise
        finally:
            # ``_request_kernel_interrupt`` sets a per-execution flag so the
            # synchronous IOPub loop can notice an interrupt delivered through
            # its exception path.  An idle status can finish the loop without
            # visiting that branch; clear the flag only after the worker is
            # known to be drained, never while its thread is still active.
            if worker_future.done():
                self.interrupt_signal = False
            if self._active_executor_future is worker_future:
                self._active_executor_future = None

    async def execute_code(self, code: str) -> tuple[str, bool, str]:
        logger.info(f"执行代码: chars={len(code)}")
        #  添加代码到notebook
        self.notebook_serializer.add_code_cell_to_notebook(code)

        text_to_gpt: list[str] = []
        content_to_display: list[OutputItem] | None = []
        error_occurred: bool = False
        error_message: str = ""

        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="开始执行代码"),
        )
        # 执行 Python 代码
        logger.info("开始在本地执行代码...")
        execution = await self._run_code_in_executor(code)
        logger.info("代码执行完成，开始处理结果...")

        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="代码执行完成"),
        )

        timeout_occurred = False
        for mark, out_str in execution:
            if mark in ("stdout", "execute_result_text", "display_text"):
                text_to_gpt.append(self._truncate_text(f"[{mark}]\n{out_str}"))
                #  添加text到notebook
                content_to_display.append(
                    ResultModel(res_type="result", format="text", msg=out_str)
                )
                self.notebook_serializer.add_code_cell_output_to_notebook(out_str)

            elif mark in (
                "execute_result_png",
                "execute_result_jpeg",
                "display_png",
                "display_jpeg",
            ):
                # TODO: 视觉模型解释图像
                text_to_gpt.append(f"[{mark} 图片已生成，内容为 base64，未展示]")

                #  添加image到notebook
                if "png" in mark:
                    self.notebook_serializer.add_image_to_notebook(out_str, "image/png")
                    content_to_display.append(
                        ResultModel(res_type="result", format="png", msg=out_str)
                    )
                else:
                    self.notebook_serializer.add_image_to_notebook(
                        out_str, "image/jpeg"
                    )
                    content_to_display.append(
                        ResultModel(res_type="result", format="jpeg", msg=out_str)
                    )

            elif mark == "error":
                error_occurred = True
                error_message = self.delete_color_control_char(out_str)
                error_message = self._truncate_text(error_message)
                timeout_occurred = "本地代码执行超过" in error_message
                logger.error(f"本地代码执行失败: error_chars={len(error_message)}")
                text_to_gpt.append(error_message)
                content_to_display.append(StdErrModel(msg=out_str))

        if error_occurred:
            # A failed cell is useful in task logs but must not poison a future
            # clean-kernel source replay after the agent supplies a correction.
            self.notebook_serializer.discard_last_code_cell()

        if timeout_occurred:
            restored = await self._recover_kernel_after_timeout()
            recovery_message = (
                "超时后的本地内核已重启，并恢复了前序代码与变量状态；"
                "请务必大幅降低计算复杂度（如将蒙特卡洛抽样次数 N 降低到 100~500、粗化网格、向量化计算），以低开销方式完成计算。"
                if restored
                else "超时后的本地内核重启或状态恢复失败；本次执行保持失败，不能继续使用旧内核。"
            )
            error_message = f"{error_message}\n{recovery_message}"
            text_to_gpt.append(recovery_message)

        logger.info(
            "本地代码执行结果已整理: "
            f"text_items={len(text_to_gpt)}, chars={sum(len(item) for item in text_to_gpt)}, "
            f"error={error_occurred}"
        )
        combined_text = "\n".join(text_to_gpt)

        await self._push_to_websocket(content_to_display)

        return (
            combined_text,
            error_occurred,
            error_message,
        )

    async def _recover_kernel_after_timeout(self) -> bool:
        """Discard a timed-out kernel and restore only the last durable state.

        A numerical extension may ignore Jupyter's interrupt message.  Continuing in
        that kernel risks turning every reflection retry into the same timeout, so a
        timeout is a process-boundary failure rather than a recoverable cell error.
        """
        previous_kc, previous_km = self.kc, self.km
        self.kc, self.km = None, None
        try:
            if previous_kc is not None:
                try:
                    previous_kc.stop_channels()
                except Exception as exc:
                    logger.warning(
                        "超时后停止本地内核通道失败: error_type={}",
                        type(exc).__name__,
                    )
            if previous_km is not None:
                previous_km.shutdown_kernel(now=True)
        except Exception as exc:
            logger.warning(
                "超时后终止本地内核失败: error_type={}", type(exc).__name__
            )
        finally:
            self._cleanup_kernel_connection_file()

        try:
            self._start_kernel()
            self._pre_execute_code()
            from app.tools.variable_snapshot import VariableSnapshot

            snapshot = VariableSnapshot(self.work_dir)
            restored = bool(
                snapshot.exists() and self.kc is not None and await snapshot.load(self.kc)
            )
            if not restored:
                code_cells = self.notebook_serializer.get_code_cells()
                # 当前超时的单元格在执行前已被加入 notebook，超时恢复时仅重放此前的前序有效单元格
                replayable_cells = code_cells[:-1] if len(code_cells) > 1 else []
                if replayable_cells:
                    logger.info(
                        "无变量快照，正在从 notebook 历史代码重放恢复状态: cells={}",
                        len(replayable_cells),
                    )
                    for cell_code in replayable_cells:
                        await self.replay_code(cell_code)
                    restored = True
            logger.info("超时后本地内核已重建: snapshot_restored={}", restored)
            return restored
        except Exception as exc:
            logger.error(
                "超时后本地内核重建失败: error_type={}", type(exc).__name__
            )
            failed_kc, failed_km = self.kc, self.km
            self.kc, self.km = None, None
            try:
                if failed_kc is not None:
                    failed_kc.stop_channels()
                if failed_km is not None:
                    failed_km.shutdown_kernel(now=True)
            except Exception:
                pass
            self._cleanup_kernel_connection_file()
            return False

    async def replay_code(self, code: str) -> tuple[str, bool, str]:
        """重放历史代码，只恢复内核状态，不修改 notebook 或推送前端消息。"""
        logger.info(f"重放代码: chars={len(code)}")
        execution = await self._run_code_in_executor(code)
        text_to_gpt: list[str] = []
        error_occurred = False
        error_message = ""

        for mark, out_str in execution:
            if mark in ("stdout", "execute_result_text", "display_text"):
                text_to_gpt.append(self._truncate_text(f"[{mark}]\n{out_str}"))
            elif mark in (
                "execute_result_png",
                "execute_result_jpeg",
                "display_png",
                "display_jpeg",
            ):
                text_to_gpt.append(f"[{mark} 图片已生成，内容为 base64，未展示]")
            elif mark == "error":
                error_occurred = True
                error_message = self._truncate_text(
                    self.delete_color_control_char(out_str)
                )
                text_to_gpt.append(error_message)

        return "\n".join(text_to_gpt), error_occurred, error_message

    def execute_code_(self, code) -> list[tuple[str, str]]:
        if self.kc is None or self.km is None:
            raise RuntimeError("本地 Jupyter 内核未初始化")
        self.kc.execute(code)
        logger.info(f"执行代码: chars={len(code)}")
        # Get the output of the code
        msg_list = []
        deadline = time.monotonic() + self.execution_timeout
        timed_out = threading.Event()

        def interrupt_for_timeout() -> None:
            """Interrupt independently of a stalled IOPub receive loop."""
            timed_out.set()
            logger.warning(
                "本地代码执行超时，看门狗请求中断: timeout_seconds={}",
                self.execution_timeout,
            )
            try:
                if self.km is not None:
                    self.km.interrupt_kernel()
            except Exception as exc:
                logger.warning(
                    "本地代码执行超时后中断内核失败: error_type={}",
                    type(exc).__name__,
                )

        if self.execution_timeout <= 0:
            interrupt_for_timeout()
            return [("error", "本地代码执行超过 0 秒，已中断")]

        watchdog: threading.Timer | None = None
        watchdog_process: subprocess.Popen | None = None
        returned_after_timeout = False
        kernel_pid = getattr(getattr(self.km, "provisioner", None), "pid", None)
        if os.name == "posix" and isinstance(kernel_pid, int) and kernel_pid > 0:
            # Do not rely solely on a Python thread here: a numerical extension can
            # retain the GIL and prevent threading.Timer from ever running.  This
            # tiny OS-level watchdog has no model input and can always signal the
            # dedicated unprivileged kernel process.
            # Bind the watchdog to this exact process start time so a reused PID can
            # never be signalled after the interpreter replaces a timed-out kernel.
            script = (
                f"kernel_start=$(awk '{{print $22}}' /proc/{kernel_pid}/stat 2>/dev/null || true); "
                f"sleep {self.execution_timeout}; "
                f"if [ -n \"$kernel_start\" ] && "
                f"[ \"$(awk '{{print $22}}' /proc/{kernel_pid}/stat 2>/dev/null || true)\" = \"$kernel_start\" ]; then "
                f"kill -INT {kernel_pid} 2>/dev/null || true; sleep 5; "
                f"if [ \"$(awk '{{print $22}}' /proc/{kernel_pid}/stat 2>/dev/null || true)\" = \"$kernel_start\" ]; then "
                f"kill -KILL {kernel_pid} 2>/dev/null || true; fi; fi"
            )
            watchdog_process = subprocess.Popen(
                ["/bin/sh", "-c", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        else:
            watchdog = threading.Timer(self.execution_timeout, interrupt_for_timeout)
            watchdog.daemon = True
            watchdog.start()
        try:
            while True:
                if timed_out.is_set() or time.monotonic() >= deadline:
                    if not timed_out.is_set():
                        interrupt_for_timeout()
                    returned_after_timeout = True
                    return [
                        (
                            "error",
                            f"本地代码执行超过 {self.execution_timeout} 秒，已中断",
                        )
                    ]
                remaining = deadline - time.monotonic()
                try:
                    iopub_msg = self.kc.get_iopub_msg(timeout=min(1, remaining))
                    msg_list.append(iopub_msg)
                    if (
                        iopub_msg["msg_type"] == "status"
                        and iopub_msg["content"].get("execution_state") == "idle"
                    ):
                        break
                except Exception:
                    if timed_out.is_set():
                        returned_after_timeout = True
                        return [
                            (
                                "error",
                                f"本地代码执行超过 {self.execution_timeout} 秒，已中断",
                            )
                        ]
                    if self.interrupt_signal:
                        self.km.interrupt_kernel()
                        self.interrupt_signal = False
                        return [("error", "本地代码执行已中断")]
                    continue
        finally:
            if watchdog is not None:
                watchdog.cancel()
            if (
                watchdog_process is not None
                and not returned_after_timeout
            ):
                try:
                    if watchdog_process.poll() is None:
                        if os.name == "posix" and hasattr(os, "getpgid") and hasattr(os, "killpg"):
                            try:
                                pid = getattr(watchdog_process, "pid", None)
                                if isinstance(pid, int):
                                    os.killpg(os.getpgid(pid), 15)
                            except (OSError, TypeError):
                                pass
                        watchdog_process.terminate()
                        try:
                            watchdog_process.wait(timeout=1.0)
                        except (subprocess.TimeoutExpired, OSError):
                            if os.name == "posix" and hasattr(os, "getpgid") and hasattr(os, "killpg"):
                                try:
                                    pid = getattr(watchdog_process, "pid", None)
                                    if isinstance(pid, int):
                                        os.killpg(os.getpgid(pid), 9)
                                except (OSError, TypeError):
                                    pass
                            watchdog_process.kill()
                            try:
                                watchdog_process.wait(timeout=1.0)
                            except (subprocess.TimeoutExpired, OSError):
                                pass
                except Exception:
                    pass

        all_output: list[tuple[str, str]] = []
        for iopub_msg in msg_list:
            if iopub_msg["msg_type"] == "stream":
                if iopub_msg["content"].get("name") == "stdout":
                    output = iopub_msg["content"]["text"]
                    all_output.append(("stdout", output))
            elif iopub_msg["msg_type"] == "execute_result":
                if "data" in iopub_msg["content"]:
                    if "text/plain" in iopub_msg["content"]["data"]:
                        output = iopub_msg["content"]["data"]["text/plain"]
                        all_output.append(("execute_result_text", output))
                    if "text/html" in iopub_msg["content"]["data"]:
                        output = iopub_msg["content"]["data"]["text/html"]
                        all_output.append(("execute_result_html", output))
                    if "image/png" in iopub_msg["content"]["data"]:
                        output = iopub_msg["content"]["data"]["image/png"]
                        all_output.append(("execute_result_png", output))
                    if "image/jpeg" in iopub_msg["content"]["data"]:
                        output = iopub_msg["content"]["data"]["image/jpeg"]
                        all_output.append(("execute_result_jpeg", output))
            elif iopub_msg["msg_type"] == "display_data":
                if "data" in iopub_msg["content"]:
                    if "text/plain" in iopub_msg["content"]["data"]:
                        output = iopub_msg["content"]["data"]["text/plain"]
                        all_output.append(("display_text", output))
                    if "text/html" in iopub_msg["content"]["data"]:
                        output = iopub_msg["content"]["data"]["text/html"]
                        all_output.append(("display_html", output))
                    if "image/png" in iopub_msg["content"]["data"]:
                        output = iopub_msg["content"]["data"]["image/png"]
                        all_output.append(("display_png", output))
                    if "image/jpeg" in iopub_msg["content"]["data"]:
                        output = iopub_msg["content"]["data"]["image/jpeg"]
                        all_output.append(("display_jpeg", output))
            elif iopub_msg["msg_type"] == "error":
                # TODO: 正确返回格式
                if "traceback" in iopub_msg["content"]:
                    output = "\n".join(iopub_msg["content"]["traceback"])
                    cleaned_output = self.delete_color_control_char(output)
                    all_output.append(("error", cleaned_output))
        return all_output

    async def get_created_images(self, section: str) -> list[str]:
        """获取新创建的图片列表"""
        current_images = set()
        files = os.listdir(self.work_dir)
        for file in files:
            if file.endswith((".png", ".jpg", ".jpeg")):
                current_images.add(file)

        # 计算新增的图片
        new_images = current_images - self.last_created_images

        # 更新last_created_images为当前的图片集合
        self.last_created_images = current_images

        logger.info(f"新创建的图片列表: {new_images}")
        return list(new_images)  # 最后转换为list返回

    async def _shutdown_code_executor(self) -> None:
        """Interrupt/drain active code, then close this interpreter's executor."""
        if self._executor_shutdown:
            return
        active_future = self._active_executor_future
        if active_future is not None and not active_future.done():
            self._request_kernel_interrupt()
            try:
                await asyncio.shield(active_future)
            except Exception:
                logger.warning("清理时等待本地执行线程结束失败")
        # The worker is drained above, so wait=True cannot block the event loop
        # on uninterruptible model code and guarantees no cleanup race.
        self._code_executor.shutdown(wait=True, cancel_futures=True)
        self._executor_shutdown = True

    async def cleanup(self):
        # Drain an active synchronous exchange before closing the kernel it is
        # talking to; this ordering avoids a worker/connection cleanup race.
        await self._shutdown_code_executor()
        # 关闭内核
        if self.kc is None or self.km is None:
            logger.warning("本地 Jupyter 内核未初始化，跳过清理")
            self._cleanup_kernel_connection_file()
            return
        try:
            self.kc.shutdown()
            logger.info("关闭内核")
            self.km.shutdown_kernel()
        finally:
            self.km, self.kc = None, None
            self._cleanup_kernel_connection_file()

    async def restart_kernel(self):
        """重置或重启内核以清除状态"""
        self.restart_jupyter_kernel()

    def send_interrupt_signal(self):
        self.interrupt_signal = True

    def restart_jupyter_kernel(self):
        """Restart the Jupyter kernel and recreate the work directory."""
        if self.kc is None or self.km is None:
            raise RuntimeError("本地 Jupyter 内核未初始化")
        try:
            self.kc.shutdown()
            self.km.shutdown_kernel()
        finally:
            self.km, self.kc = None, None
            self._cleanup_kernel_connection_file()
        self._start_kernel()
        self.interrupt_signal = False
        self._create_work_dir()
        self._pre_execute_code()

    def _create_work_dir(self):
        """Ensure the working directory exists after a restart."""
        os.makedirs(self.work_dir, exist_ok=True)
