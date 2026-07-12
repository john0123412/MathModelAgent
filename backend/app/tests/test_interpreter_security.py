"""Fail-closed tests for model-generated code execution."""

import tempfile
import unittest
from unittest import mock

from app.config.setting import settings
from app.tools.interpreter_factory import create_interpreter
from app.tools.notebook_serializer import NotebookSerializer


class TestInterpreterSecurity(unittest.IsolatedAsyncioTestCase):
    async def test_remote_mode_does_not_fall_back_to_local_without_e2b(self):
        with tempfile.TemporaryDirectory() as work_dir, mock.patch.object(
            settings, "CODE_INTERPRETER_KIND", "remote"
        ), mock.patch.object(settings, "E2B_API_KEY", None):
            with self.assertRaisesRegex(RuntimeError, "不会自动降级"):
                await create_interpreter(
                    task_id="task-1",
                    work_dir=work_dir,
                    notebook_serializer=NotebookSerializer(work_dir=work_dir),
                )

    async def test_local_mode_requires_explicit_trust_opt_in(self):
        with tempfile.TemporaryDirectory() as work_dir, mock.patch.object(
            settings, "CODE_INTERPRETER_KIND", "local"
        ), mock.patch.object(settings, "ALLOW_LOCAL_CODE_EXECUTION", False):
            with self.assertRaisesRegex(RuntimeError, "本地代码执行默认禁用"):
                await create_interpreter(
                    task_id="task-1",
                    work_dir=work_dir,
                    notebook_serializer=NotebookSerializer(work_dir=work_dir),
                )
