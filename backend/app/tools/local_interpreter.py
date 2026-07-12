"""本地代码解释器模块，通过本地 Jupyter 内核执行 Python 代码。"""

from app.tools.base_interpreter import BaseCodeInterpreter
from app.tools.notebook_serializer import NotebookSerializer
import jupyter_client
from app.utils.log_util import logger
import os
from app.services.redis_manager import redis_manager
from app.schemas.response import (
    OutputItem,
    ResultModel,
    StdErrModel,
    SystemMessage,
)


class LocalCodeInterpreter(BaseCodeInterpreter):
    """基于本地 Jupyter 内核的代码解释器。"""

    def __init__(
        self,
        task_id: str,
        work_dir: str,
        notebook_serializer: NotebookSerializer,
    ):
        super().__init__(task_id, work_dir, notebook_serializer)
        self.km, self.kc = None, None
        self.interrupt_signal = False

    async def initialize(self):
        # 本地内核一般不需异步上传文件，直接切换目录即可
        # 初始化 Jupyter 内核管理器和客户端
        logger.info("初始化本地内核")
        # 设置 UTF-8 编码环境，避免 Windows 中文环境下 GBK 编码导致的乱码问题
        kernel_env = os.environ.copy()
        kernel_env["PYTHONIOENCODING"] = "utf-8"
        kernel_env["PYTHONUTF8"] = "1"
        self.km, self.kc = jupyter_client.manager.start_new_kernel(
            kernel_name="python3", env=kernel_env
        )
        self._pre_execute_code()

    def _pre_execute_code(self):
        init_code = (
            f"import os\n"
            f"work_dir = r'{self.work_dir}'\n"
            f"os.makedirs(work_dir, exist_ok=True)\n"
            f"os.chdir(work_dir)\n"
            f"print('当前工作目录:', os.getcwd())\n"
            # 加载中文字体，确保图表中文正常显示（跨平台兼容）
            # 先清除 matplotlib 字体缓存，避免旧缓存导致 addfont 失效
            f"import matplotlib\n"
            f"import matplotlib.pyplot as plt\n"
            f"from matplotlib import font_manager\n"
            f"import glob as _glob, pathlib as _pl\n"
            f"_cache_dir = _pl.Path(matplotlib.get_cachedir())\n"
            f"for _cache_file in _glob.glob(str(_cache_dir / 'fontlist*.json')):\n"
            f"    _pl.Path(_cache_file).unlink(missing_ok=True)\n"
            f"font_manager.fontManager.__init__()\n"
            f"_font_dir = work_dir\n"
            f"_loaded = False\n"
            f"for _f in os.listdir(_font_dir):\n"
            f"    if _f.lower().endswith(('.ttf', '.otf', '.ttc')):\n"
            f"        _fp = os.path.join(_font_dir, _f)\n"
            f"        font_manager.fontManager.addfont(_fp)\n"
            f"        _loaded = True\n"
            f"if _loaded:\n"
            f"    print(f'中文字体已加载，可用字体数: {{len(font_manager.fontManager.ttflist)}}')\n"
            # 学术配色方案
            f"_MMA_COLORS = ['#2E5B88', '#E85D4C', '#4A9B7F', '#F5A623', '#7F7F7F', '#B8D4E8', '#D4A5A5', '#9B59B6']\n"
            f"COLORS = list(_MMA_COLORS)\n"
            # 学术论文图表样式。生成代码可能调用 seaborn.set_theme() 覆盖字体，
            # 因此保存图片前也会通过 savefig hook 重新应用一次。
            f"import matplotlib.figure as _mma_matplotlib_figure\n"
            f"_MMA_CHINESE_FONTS = ['SimHei', 'Microsoft YaHei', 'SimSun', 'Noto Sans CJK SC', 'Noto Sans SC', 'DejaVu Sans']\n"
            f"def _mma_apply_chinese_plot_style():\n"
            f"    plt.rcParams.update({{\n"
            f"        'font.sans-serif': _MMA_CHINESE_FONTS,\n"
            f"        'font.family': 'sans-serif',\n"
            f"        'font.size': 11,\n"
            f"        'axes.titlesize': 12,\n"
            f"        'axes.titleweight': 'bold',\n"
            f"        'axes.labelsize': 11,\n"
            f"        'axes.linewidth': 1.2,\n"
            f"        'axes.spines.top': False,\n"
            f"        'axes.spines.right': False,\n"
            f"        'axes.unicode_minus': False,\n"
            f"        'xtick.labelsize': 10,\n"
            f"        'ytick.labelsize': 10,\n"
            f"        'legend.fontsize': 10,\n"
            f"        'legend.frameon': False,\n"
            f"        'figure.dpi': 150,\n"
            f"        'savefig.dpi': 300,\n"
            f"        'savefig.bbox': 'tight',\n"
            f"        'savefig.pad_inches': 0.1,\n"
            f"    }})\n"
            f"    plt.gca().set_prop_cycle(color=_MMA_COLORS)\n"
            f"_mma_apply_chinese_plot_style()\n"
            f"if not getattr(plt.savefig, '_mma_wrapped', False):\n"
            f"    _mma_original_plt_savefig = plt.savefig\n"
            f"    def _mma_savefig_with_style(*args, **kwargs):\n"
            f"        _mma_apply_chinese_plot_style()\n"
            f"        return _mma_original_plt_savefig(*args, **kwargs)\n"
            f"    _mma_savefig_with_style._mma_wrapped = True\n"
            f"    plt.savefig = _mma_savefig_with_style\n"
            f"if not getattr(matplotlib.figure.Figure.savefig, '_mma_wrapped', False):\n"
            f"    _mma_original_figure_savefig = matplotlib.figure.Figure.savefig\n"
            f"    def _mma_figure_savefig_with_style(self, *args, **kwargs):\n"
            f"        _mma_apply_chinese_plot_style()\n"
            f"        return _mma_original_figure_savefig(self, *args, **kwargs)\n"
            f"    _mma_figure_savefig_with_style._mma_wrapped = True\n"
            f"    matplotlib.figure.Figure.savefig = _mma_figure_savefig_with_style\n"
            f"print('学术图表样式已配置')\n"
        )
        self.execute_code_(init_code)

    async def execute_code(self, code: str) -> tuple[str, bool, str]:
        logger.info(f"执行代码: {code}")
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
        execution = self.execute_code_(code)
        logger.info("代码执行完成，开始处理结果...")

        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="代码执行完成"),
        )

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
                logger.error(f"执行错误: {error_message}")
                text_to_gpt.append(error_message)
                #  添加error到notebook
                self.notebook_serializer.add_code_cell_error_to_notebook(out_str)
                content_to_display.append(StdErrModel(msg=out_str))

        logger.info(f"text_to_gpt: {text_to_gpt}")
        combined_text = "\n".join(text_to_gpt)

        await self._push_to_websocket(content_to_display)

        return (
            combined_text,
            error_occurred,
            error_message,
        )

    async def replay_code(self, code: str) -> tuple[str, bool, str]:
        """重放历史代码，只恢复内核状态，不修改 notebook 或推送前端消息。"""
        logger.info(f"重放代码: {code}")
        execution = self.execute_code_(code)
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
        logger.info(f"执行代码: {code}")
        # Get the output of the code
        msg_list = []
        while True:
            try:
                iopub_msg = self.kc.get_iopub_msg(timeout=1)
                msg_list.append(iopub_msg)
                if (
                    iopub_msg["msg_type"] == "status"
                    and iopub_msg["content"].get("execution_state") == "idle"
                ):
                    break
            except Exception:
                if self.interrupt_signal:
                    self.km.interrupt_kernel()
                    self.interrupt_signal = False
                continue

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

    async def cleanup(self):
        # 关闭内核
        if self.kc is None or self.km is None:
            logger.warning("本地 Jupyter 内核未初始化，跳过清理")
            return
        self.kc.shutdown()
        logger.info("关闭内核")
        self.km.shutdown_kernel()

    def send_interrupt_signal(self):
        self.interrupt_signal = True

    def restart_jupyter_kernel(self):
        """Restart the Jupyter kernel and recreate the work directory."""
        if self.kc is None:
            raise RuntimeError("本地 Jupyter 内核未初始化")
        self.kc.shutdown()
        # 设置 UTF-8 编码环境，避免 Windows 中文环境下 GBK 编码导致的乱码问题
        kernel_env = os.environ.copy()
        kernel_env["PYTHONIOENCODING"] = "utf-8"
        kernel_env["PYTHONUTF8"] = "1"
        self.km, self.kc = jupyter_client.manager.start_new_kernel(
            kernel_name="python3", env=kernel_env
        )
        self.interrupt_signal = False
        self._create_work_dir()
        self._pre_execute_code()

    def _create_work_dir(self):
        """Ensure the working directory exists after a restart."""
        os.makedirs(self.work_dir, exist_ok=True)
