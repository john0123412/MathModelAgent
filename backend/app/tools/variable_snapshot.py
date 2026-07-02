"""变量快照模块，支持本地 Jupyter 内核变量的保存与恢复。"""

import datetime
import json
import os
import textwrap

from app.utils.log_util import logger


class VariableSnapshot:
    """Jupyter 内核变量快照管理器。"""

    def __init__(self, work_dir: str):
        """初始化快照管理器。

        Args:
            work_dir: 任务工作目录。
        """
        self.work_dir = os.path.abspath(work_dir)
        self.snapshot_path = os.path.join(self.work_dir, "variable_snapshot.pkl")
        self.meta_path = os.path.join(self.work_dir, "variable_snapshot_meta.json")

    async def save(
        self,
        kernel_client,
        notebook_cell_count: int = 0,
        notebook_code_cell_count: int = 0,
    ) -> bool:
        """保存当前内核变量到工作目录。

        Args:
            kernel_client: Jupyter 内核客户端。
            notebook_cell_count: 快照对应的 notebook 总单元格数量。
            notebook_code_cell_count: 快照对应的 notebook 代码单元格数量。

        Returns:
            是否保存成功。
        """
        os.makedirs(self.work_dir, exist_ok=True)
        tmp_snapshot_path = self.snapshot_path + ".tmp"
        tmp_meta_path = self.meta_path + ".tmp"

        code = textwrap.dedent(
            f"""
            import datetime as _snapshot_datetime
            import json as _snapshot_json
            import os as _snapshot_os
            import pickle as _snapshot_pickle
            import types as _snapshot_types

            _snapshot_path = {tmp_snapshot_path!r}
            _snapshot_meta_path = {tmp_meta_path!r}
            _snapshot_skip_names = {{
                "_snapshot_datetime",
                "_snapshot_json",
                "_snapshot_os",
                "_snapshot_pickle",
                "_snapshot_types",
                "_snapshot_path",
                "_snapshot_meta_path",
                "_snapshot_skip_names",
                "_snapshot_vars",
                "_snapshot_name",
                "_snapshot_obj",
                "_snapshot_meta",
            }}
            _snapshot_vars = {{}}

            for _snapshot_name, _snapshot_obj in list(globals().items()):
                if _snapshot_name in _snapshot_skip_names:
                    continue
                if _snapshot_name.startswith("_"):
                    continue
                if isinstance(_snapshot_obj, _snapshot_types.ModuleType):
                    continue
                if isinstance(_snapshot_obj, type):
                    continue
                if callable(_snapshot_obj):
                    continue
                try:
                    _snapshot_pickle.dumps(_snapshot_obj)
                except (
                    _snapshot_pickle.PicklingError,
                    TypeError,
                    AttributeError,
                    RecursionError,
                ):
                    continue
                _snapshot_vars[_snapshot_name] = _snapshot_obj

            with open(_snapshot_path, "wb") as _snapshot_file:
                _snapshot_pickle.dump(_snapshot_vars, _snapshot_file)

            _snapshot_meta = {{
                "created_at": _snapshot_datetime.datetime.now().isoformat(),
                "variable_count": len(_snapshot_vars),
                "notebook_cell_count": {notebook_cell_count},
                "notebook_code_cell_count": {notebook_code_cell_count},
            }}
            with open(_snapshot_meta_path, "w", encoding="utf-8") as _snapshot_file:
                _snapshot_json.dump(_snapshot_meta, _snapshot_file, ensure_ascii=False, indent=2)

            print("SNAPSHOT_SAVED:" + str(len(_snapshot_vars)))
            """
        )

        try:
            marker = self._execute_and_wait(kernel_client, code, "SNAPSHOT_SAVED:")
            count = int(marker.split(":", 1)[1])
            os.replace(tmp_snapshot_path, self.snapshot_path)
            os.replace(tmp_meta_path, self.meta_path)
            logger.info(f"变量快照已保存: {self.snapshot_path}, 变量数: {count}")
            return True
        except Exception as e:
            logger.warning(f"变量快照保存失败: {e}")
            self._remove_if_exists(tmp_snapshot_path)
            self._remove_if_exists(tmp_meta_path)
            return False

    async def load(self, kernel_client) -> bool:
        """从磁盘恢复变量到内核。

        Args:
            kernel_client: Jupyter 内核客户端。

        Returns:
            是否恢复成功。
        """
        if not self.exists():
            logger.info("未找到可用变量快照文件")
            return False

        code = textwrap.dedent(
            f"""
            import pickle as _snapshot_pickle

            _snapshot_path = {self.snapshot_path!r}
            with open(_snapshot_path, "rb") as _snapshot_file:
                _snapshot_variables = _snapshot_pickle.load(_snapshot_file)

            globals().update(_snapshot_variables)
            print("SNAPSHOT_RESTORED:" + str(len(_snapshot_variables)))
            """
        )

        try:
            marker = self._execute_and_wait(kernel_client, code, "SNAPSHOT_RESTORED:")
            count = int(marker.split(":", 1)[1])
            logger.info(f"变量快照已恢复: {count} 个变量")
            return True
        except Exception as e:
            logger.warning(f"变量快照恢复失败: {e}")
            return False

    def exists(self) -> bool:
        """检查快照文件是否存在且非空。"""
        return (
            os.path.exists(self.snapshot_path)
            and os.path.getsize(self.snapshot_path) > 0
        )

    def delete(self) -> bool:
        """删除快照文件和元数据。"""
        try:
            self._remove_if_exists(self.snapshot_path)
            self._remove_if_exists(self.meta_path)
            logger.info("变量快照已删除")
            return True
        except Exception as e:
            logger.error(f"删除快照失败: {e}")
            return False

    def get_size(self) -> int:
        """获取快照文件大小（字节）。"""
        if self.exists():
            return os.path.getsize(self.snapshot_path)
        return 0

    def load_meta(self) -> dict:
        """读取快照元数据，缺失或损坏时返回空字典。"""
        if not os.path.exists(self.meta_path):
            return {}
        try:
            with open(self.meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"读取变量快照元数据失败: {e}")
            return {}

    def write_meta(
        self,
        notebook_cell_count: int,
        variable_count: int = 0,
        notebook_code_cell_count: int = 0,
    ) -> None:
        """写入快照元数据。

        Args:
            notebook_cell_count: 快照对应的 notebook 总单元格数量。
            variable_count: 快照中的变量数量。
            notebook_code_cell_count: 快照对应的 notebook 代码单元格数量。
        """
        meta = {
            "created_at": datetime.datetime.now().isoformat(),
            "variable_count": variable_count,
            "notebook_cell_count": notebook_cell_count,
            "notebook_code_cell_count": notebook_code_cell_count,
        }
        tmp_path = self.meta_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.meta_path)

    def _execute_and_wait(self, kernel_client, code: str, marker_prefix: str) -> str:
        """执行内核代码并等待指定 marker 输出。"""
        msg_id = kernel_client.execute(code)
        marker: str | None = None
        while True:
            msg = kernel_client.get_iopub_msg(timeout=60)
            if msg.get("parent_header", {}).get("msg_id") != msg_id:
                continue

            msg_type = msg.get("msg_type", "")
            content = msg.get("content", {})
            if msg_type == "stream":
                text = content.get("text", "")
                for line in text.splitlines():
                    if line.startswith(marker_prefix):
                        marker = line
            if msg_type == "error":
                traceback = "\n".join(content.get("traceback", []))
                error_name = content.get("ename", "unknown")
                error_value = content.get("evalue", "")
                raise RuntimeError(f"{error_name}: {error_value}\n{traceback}")
            if msg_type == "status" and content.get("execution_state") == "idle":
                if marker is not None:
                    return marker
                raise RuntimeError(f"内核执行结束但未收到 {marker_prefix} 标记")

    @staticmethod
    def _remove_if_exists(path: str) -> None:
        if os.path.exists(path):
            os.remove(path)
