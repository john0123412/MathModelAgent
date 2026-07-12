import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.core.workflow import MathModelWorkFlow


class WorkflowInterpreterCleanupTest(unittest.IsolatedAsyncioTestCase):
    async def test_managed_interpreter_cleans_up_after_workflow_failure(self):
        interpreter = SimpleNamespace(cleanup=AsyncMock())
        workflow = MathModelWorkFlow()

        with self.assertRaisesRegex(RuntimeError, "workflow failure"):
            async with workflow._managed_interpreter(interpreter):
                raise RuntimeError("workflow failure")

        interpreter.cleanup.assert_awaited_once()

    async def test_managed_interpreter_does_not_mask_workflow_failure(self):
        interpreter = SimpleNamespace(cleanup=AsyncMock(side_effect=RuntimeError("stop")))
        workflow = MathModelWorkFlow()

        with self.assertRaisesRegex(ValueError, "original failure"):
            async with workflow._managed_interpreter(interpreter):
                raise ValueError("original failure")

        interpreter.cleanup.assert_awaited_once()
