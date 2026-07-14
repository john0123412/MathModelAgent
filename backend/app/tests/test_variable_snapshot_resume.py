"""变量快照续传逻辑测试。"""

import asyncio
import os
import tempfile
import unittest
from unittest import mock

import nbformat
from nbformat import v4 as nbf

from app.core.workflow import MathModelWorkFlow
from app.tools.notebook_serializer import NotebookSerializer
from app.tools.variable_snapshot import VariableSnapshot


class FakeInterpreter:
    """用于验证 replay 选择逻辑的轻量解释器。"""

    kc = object()

    def __init__(self):
        self.replayed: list[str] = []

    async def replay_code(self, code: str):
        self.replayed.append(code)
        return "", False, ""


class FakeSnapshot:
    """用于替换 VariableSnapshot 的 fake。"""

    exists_result = False
    load_result = False
    meta: dict = {}

    def __init__(self, work_dir: str):
        self.work_dir = work_dir

    def exists(self) -> bool:
        return self.exists_result

    async def load(self, kernel_client) -> bool:
        return self.load_result

    def load_meta(self) -> dict:
        return self.meta


class TestVariableSnapshotMetadata(unittest.TestCase):
    """验证快照元数据写入和读取。"""

    def test_write_meta_roundtrip(self):
        with tempfile.TemporaryDirectory() as work_dir:
            snapshot = VariableSnapshot(work_dir)
            snapshot.write_meta(
                notebook_cell_count=5,
                notebook_code_cell_count=3,
                variable_count=7,
            )

            meta = snapshot.load_meta()

            self.assertEqual(meta["notebook_cell_count"], 5)
            self.assertEqual(meta["notebook_code_cell_count"], 3)
            self.assertEqual(meta["variable_count"], 7)


class TestReplayNotebookSelection(unittest.TestCase):
    """验证 resume 只恢复已持久化的快照边界。"""

    def _write_notebook(self, work_dir: str) -> None:
        nb = nbf.new_notebook()
        nb["cells"] = [
            nbf.new_code_cell("a = 1"),
            nbf.new_markdown_cell("markdown separator"),
            nbf.new_code_cell("b = 2"),
            nbf.new_code_cell("c = 3"),
        ]
        with open(os.path.join(work_dir, "notebook.ipynb"), "w", encoding="utf-8") as f:
            nbformat.write(nb, f)

    def _run_replay(self, work_dir: str, snapshot_meta: dict, snapshot_load: bool):
        workflow = MathModelWorkFlow()
        workflow.task_id = "unit-test"
        workflow.work_dir = work_dir
        interpreter = FakeInterpreter()

        FakeSnapshot.exists_result = True
        FakeSnapshot.load_result = snapshot_load
        FakeSnapshot.meta = snapshot_meta

        async def noop_publish(*args, **kwargs):
            return None

        with (
            mock.patch(
                "app.tools.variable_snapshot.VariableSnapshot",
                FakeSnapshot,
            ),
            mock.patch(
                "app.core.workflow.redis_manager.publish_message",
                side_effect=noop_publish,
            ),
        ):
            asyncio.run(workflow._replay_notebook(interpreter))

        return interpreter.replayed

    def test_snapshot_restore_does_not_replay_unfinished_cells(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._write_notebook(work_dir)

            replayed = self._run_replay(
                work_dir,
                snapshot_meta={
                    "notebook_cell_count": 2,
                    "notebook_code_cell_count": 1,
                },
                snapshot_load=True,
            )

            self.assertEqual(replayed, [])

    def test_snapshot_restore_ignores_legacy_cell_metadata(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._write_notebook(work_dir)

            replayed = self._run_replay(
                work_dir,
                snapshot_meta={"notebook_code_cell_count": 1},
                snapshot_load=True,
            )

            self.assertEqual(replayed, [])

    def test_snapshot_restore_does_not_depend_on_metadata(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._write_notebook(work_dir)

            replayed = self._run_replay(
                work_dir,
                snapshot_meta={
                    "notebook_cell_count": "bad",
                    "notebook_code_cell_count": "bad",
                },
                snapshot_load=True,
            )

            self.assertEqual(replayed, [])

    def test_missing_notebook_after_snapshot_load_is_allowed(self):
        with tempfile.TemporaryDirectory() as work_dir:
            replayed = self._run_replay(
                work_dir,
                snapshot_meta={
                    "notebook_cell_count": 2,
                    "notebook_code_cell_count": 1,
                },
                snapshot_load=True,
            )

            self.assertEqual(replayed, [])

    def test_snapshot_load_failure_falls_back_to_full_replay(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._write_notebook(work_dir)

            replayed = self._run_replay(
                work_dir,
                snapshot_meta={"notebook_cell_count": 2},
                snapshot_load=False,
            )

            self.assertEqual(replayed, ["a = 1", "b = 2", "c = 3"])


class TestVariableSnapshotMetaFile(unittest.TestCase):
    """验证损坏 metadata 的降级行为。"""

    def test_broken_meta_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as work_dir:
            snapshot = VariableSnapshot(work_dir)
            with open(snapshot.meta_path, "w", encoding="utf-8") as f:
                f.write("{bad json")

            self.assertEqual(snapshot.load_meta(), {})


class TestNotebookSerializerResume(unittest.TestCase):
    """验证 resume 初始化不会覆盖已有 notebook。"""

    def test_existing_notebook_is_loaded_before_append(self):
        with tempfile.TemporaryDirectory() as work_dir:
            nb = nbf.new_notebook()
            nb["cells"] = [nbf.new_code_cell("a = 1")]
            notebook_path = os.path.join(work_dir, "notebook.ipynb")
            with open(notebook_path, "w", encoding="utf-8") as f:
                nbformat.write(nb, f)

            serializer = NotebookSerializer(work_dir=work_dir)
            serializer.add_code_cell_to_notebook("b = 2")

            loaded = nbformat.read(notebook_path, as_version=4)
            self.assertEqual([cell.source for cell in loaded.cells], ["a = 1", "b = 2"])


if __name__ == "__main__":
    unittest.main()
