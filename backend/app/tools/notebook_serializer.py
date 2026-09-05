"""Jupyter Notebook 序列化模块，管理 notebook 的创建和内容追加。"""

import nbformat
from nbformat import v4 as nbf
import ansi2html  # type: ignore[import-unresolved]
import os


class NotebookSerializer:
    """Jupyter Notebook 序列化器，负责创建和维护 .ipynb 文件。"""
    def __init__(self, work_dir=None, notebook_name="notebook.ipynb"):
        self.nb = nbf.new_notebook()
        self.notebook_path = None
        self.initialized = True
        self.segmentation_output_content = {}  # 保存coder_agent 在 jupyter 中执行的 output 结果内容
        # {
        #     "eda": {
        #     }
        # }
        self.current_segmentation: str = ""

        self.init_notebook(work_dir, notebook_name)

    def init_notebook(self, work_dir=None, notebook_name="notebook.ipynb"):
        """初始化notebook路径

        Args:
            work_dir (str): jupyter工作目录路径
            notebook_name (str): notebook文件名,默认为notebook.ipynb
        """
        if work_dir:
            # 确保使用jupyter工作目录
            base, ext = os.path.splitext(notebook_name)
            if ext.lower() != ".ipynb":
                notebook_name += ".ipynb"

            # 在jupyter工作目录下创建notebook文件
            self.notebook_path = os.path.join(work_dir, notebook_name)
            if os.path.exists(self.notebook_path):
                self.nb = nbformat.read(self.notebook_path, as_version=4)

            # if os.path.exists(self.notebook_path):
            #     raise FileExistsError(
            #         f"文件 {self.notebook_path} 已存在。请选择其他文件名。"
            #     )

    def ansi_to_html(self, ansi_text):
        converter = ansi2html.Ansi2HTMLConverter()
        html_text = converter.convert(ansi_text)
        return html_text

    def write_to_notebook(self):
        if self.notebook_path:
            with open(self.notebook_path, "w", encoding="utf-8") as f:
                f.write(nbformat.writes(self.nb))

    def add_code_cell_to_notebook(self, code):
        code_cell = nbf.new_code_cell(source=code)
        self.nb["cells"].append(code_cell)
        self.write_to_notebook()

    def _stamp_execution(self):
        """真内核执行过的单元必须有 execution_count：手工拼装贴不出来。

        PR #50 的伪执行门禁假设"执行过必有计数"，但本序列化器历史上从不
        写计数，导致管道自身产物被系统性误判。凡序列化器附加过输出的单元
        都是真实执行过的，这里补打递增计数。
        """
        cells = self.nb["cells"]
        if not cells or cells[-1].get("cell_type") != "code":
            return
        if cells[-1].get("execution_count") is None:
            used = [
                c.get("execution_count")
                for c in cells
                if c.get("cell_type") == "code"
                and isinstance(c.get("execution_count"), int)
            ]
            cells[-1]["execution_count"] = max(used, default=0) + 1

    def add_code_cell_output_to_notebook(self, output):
        """添加代码单元格输出

        Args:
            output: 代码输出内容
        """
        html_content = self.ansi_to_html(output)
        if self.current_segmentation:
            # 确保键存在
            if self.current_segmentation not in self.segmentation_output_content:
                self.segmentation_output_content[self.current_segmentation] = ""
            self.segmentation_output_content[self.current_segmentation] += html_content

        self._stamp_execution()
        # stdout 原文以 stream 形式保留（真内核行为），display_data 继续承载
        # 渲染用 HTML；伪执行门禁的 print_without_stream 依赖 stream 存在。
        stream_output = nbf.new_output(
            output_type="stream", name="stdout", text=output
        )
        self.nb["cells"][-1]["outputs"].append(stream_output)
        cell_output = nbf.new_output(
            output_type="display_data", data={"text/html": html_content}
        )
        self.nb["cells"][-1]["outputs"].append(cell_output)
        self.write_to_notebook()

    def add_code_cell_error_to_notebook(self, error):
        self._stamp_execution()
        nbf_error_output = nbf.new_output(
            output_type="error",
            ename="Error",
            evalue="Error message",
            traceback=[error],
        )
        self.nb["cells"][-1]["outputs"].append(nbf_error_output)
        self.write_to_notebook()

    def discard_last_code_cell(self) -> bool:
        """Remove the currently executing failed cell from the replayable notebook.

        The notebook is the reproducible source record, not a transcript of failed
        agent attempts.  Keeping a cell that raised makes every clean-kernel replay
        fail even after a later correction succeeds.  Runtime errors remain visible
        in task messages and structured logs.
        """
        if not self.nb["cells"] or self.nb["cells"][-1].cell_type != "code":
            return False
        self.nb["cells"].pop()
        self.write_to_notebook()
        return True

    def get_code_cells(self) -> list[str]:
        """返回当前 notebook 中所有有效的代码单元格源码列表。"""
        return [
            cell.source
            for cell in self.nb.get("cells", [])
            if cell.get("cell_type") == "code" and cell.get("source")
        ]

    def add_image_to_notebook(self, image, mime_type):
        self._stamp_execution()
        image_output = nbf.new_output(
            output_type="display_data", data={mime_type: image}
        )
        self.nb["cells"][-1]["outputs"].append(image_output)
        self.write_to_notebook()

    def add_markdown_to_notebook(self, content, title=None):
        if title:
            content = "##### " + title + ":\n" + content
        markdown_cell = nbf.new_markdown_cell(content)
        self.nb["cells"].append(markdown_cell)
        self.write_to_notebook()

    def add_markdown_segmentation_to_notebook(self, content, segmentation):
        """添加markdown分段并初始化对应的output内容存储

        Args:
            content: markdown内容
            segmentation: 分段名称
        """
        self.current_segmentation = segmentation
        # 初始化该分段的output内容
        self.segmentation_output_content[segmentation] = ""
        self.add_markdown_to_notebook(content, segmentation)

    def get_notebook_output_content(self, segmentation):
        return self.segmentation_output_content[segmentation]
