"""Regression tests for durable task recovery boundaries."""

import json
import os
import tempfile
import unittest
from unittest import mock

from fastapi import BackgroundTasks, HTTPException

from app.core.checkpoint import CheckpointManager, TaskCheckpoint
from app.routers import modeling_router
from app.services.task_recovery import (
    load_task_request_snapshot,
    write_task_request_snapshot,
)
from app.services.task_status import recover_stale_task_statuses, write_task_status


class TestTaskRequestSnapshot(unittest.TestCase):
    def test_snapshot_roundtrip(self):
        payload = {
            "task_id": "task-1",
            "ques_all": "求最优生产方案",
            "comp_template": "CHINA",
            "format_output": "Markdown",
            "export_profile": "cumcm2026",
        }
        with tempfile.TemporaryDirectory() as work_dir:
            write_task_request_snapshot(work_dir, payload)
            loaded = load_task_request_snapshot(work_dir)

        self.assertEqual(loaded, payload)

    def test_snapshot_rejects_missing_required_fields(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with self.assertRaisesRegex(ValueError, "缺少必要字段"):
                write_task_request_snapshot(work_dir, {"task_id": "task-1"})


class TestStaleTaskStatusRecovery(unittest.TestCase):
    def test_only_stale_active_states_become_interrupted(self):
        with tempfile.TemporaryDirectory() as root:
            running_dir = os.path.join(root, "running-task")
            completed_dir = os.path.join(root, "completed-task")
            os.makedirs(running_dir)
            os.makedirs(completed_dir)
            with mock.patch("app.services.task_status.get_work_dir", side_effect=[running_dir, completed_dir]):
                write_task_status("running-task", "running", "old worker")
                write_task_status("completed-task", "completed", "done")

            recovered = recover_stale_task_statuses(root)
            with open(os.path.join(running_dir, "task_status.json"), encoding="utf-8") as handle:
                running = json.load(handle)
            with open(os.path.join(completed_dir, "task_status.json"), encoding="utf-8") as handle:
                completed = json.load(handle)

        self.assertEqual(recovered, ["running-task"])
        self.assertEqual(running["status"], "interrupted")
        self.assertEqual(completed["status"], "completed")


class TestManualExecutionRecovery(unittest.TestCase):
    def _checkpoint(self, work_dir: str) -> CheckpointManager:
        manager = CheckpointManager(work_dir)
        manager.save(
            TaskCheckpoint(
                task_id="task-1",
                ques_all="题目",
                comp_template="CHINA",
                format_output="Markdown",
                export_profile="cumcm2026",
                questions={"ques_count": 1, "ques1": "问题一"},
                ques_count=1,
                modeler_response={},
                updated_at="2026-07-15T00:00:00",
                targeted_repair_attempts=2,
            )
        )
        return manager

    def test_allows_exactly_one_explicit_post_exhaustion_recovery(self):
        with tempfile.TemporaryDirectory() as work_dir:
            manager = self._checkpoint(work_dir)
            manager.load()
            manager.authorize_manual_execution_recovery(
                "low_cost_algorithm", "改用线性规划基线"
            )
            checkpoint = manager.load()
            assert checkpoint is not None
            self.assertEqual(checkpoint.targeted_repair_attempts, 1)
            self.assertEqual(checkpoint.manual_recovery_attempts, 1)
            self.assertEqual(checkpoint.last_manual_recovery["mode"], "low_cost_algorithm")
            with self.assertRaisesRegex(RuntimeError, "已使用过"):
                manager.authorize_manual_execution_recovery("provider_changed")


class TestResumeRoute(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _write_checkpoint(work_dir: str) -> None:
        CheckpointManager(work_dir).save(
            TaskCheckpoint(
                task_id="task-1",
                ques_all="题目",
                comp_template="CHINA",
                format_output="Markdown",
                export_profile="cumcm2026",
                questions={"ques_count": 1, "ques1": "问题一"},
                ques_count=1,
                modeler_response={},
                updated_at="2026-07-15T00:00:00",
            )
        )

    async def test_checkpoint_resume_uses_manager_failure_budget(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._write_checkpoint(work_dir)
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(modeling_router.redis_manager, "set", new_callable=mock.AsyncMock),
                mock.patch.object(modeling_router, "write_task_status"),
            ):
                background = BackgroundTasks()
                response = await modeling_router.resume_task("task-1", background)

        self.assertEqual(response.status, "resuming")
        self.assertEqual(len(background.tasks), 1)
        self.assertIs(background.tasks[0].func, modeling_router.run_resume_task_async)

    async def test_early_failure_restarts_from_durable_request_snapshot(self):
        snapshot = {
            "task_id": "task-1",
            "ques_all": "求最优生产方案",
            "comp_template": "CHINA",
            "format_output": "Markdown",
            "export_profile": "cumcm2026",
        }
        with tempfile.TemporaryDirectory() as work_dir:
            write_task_request_snapshot(work_dir, snapshot)
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(modeling_router.redis_manager, "set", new_callable=mock.AsyncMock),
                mock.patch.object(modeling_router, "write_task_status"),
            ):
                background = BackgroundTasks()
                response = await modeling_router.resume_task("task-1", background)

        self.assertEqual(response.status, "resuming")
        self.assertEqual(len(background.tasks), 1)
        task = background.tasks[0]
        self.assertIs(task.func, modeling_router.run_modeling_task_async)
        self.assertEqual(task.args[0], "task-1")
        self.assertEqual(task.args[1], snapshot["ques_all"])

    async def test_completed_task_cannot_be_resumed(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "completed", "message": "done"}, handle)
            with mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir):
                with self.assertRaises(HTTPException) as caught:
                    await modeling_router.resume_task("task-1", BackgroundTasks())

        self.assertEqual(caught.exception.status_code, 409)
