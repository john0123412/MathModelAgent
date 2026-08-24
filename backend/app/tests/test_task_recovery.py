"""Regression tests for durable task recovery boundaries."""

import json
import os
import tempfile
import unittest
from unittest import mock

from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient

from app import main
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

    def test_testclient_lifespan_does_not_recover_shared_live_tasks(self):
        """Unit tests must not mutate a Docker task through app startup."""
        with mock.patch.object(main, "recover_stale_task_statuses") as recovery:
            with TestClient(main.app):
                pass

        recovery.assert_not_called()


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
    async def asyncSetUp(self):
        modeling_router._active_tasks.clear()
        self._schedule_patcher = mock.patch.object(
            modeling_router, "_schedule_reserved_runner"
        )
        self.schedule_runner = self._schedule_patcher.start()

    async def asyncTearDown(self):
        self._schedule_patcher.stop()
        modeling_router._active_tasks.clear()

    @staticmethod
    def _write_checkpoint(work_dir: str, workflow_state: str = "solving") -> None:
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
                workflow_state=workflow_state,
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
        self.schedule_runner.assert_called_once()
        self.assertIs(
            self.schedule_runner.call_args.args[2],
            modeling_router.run_resume_task_async,
        )

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
        self.schedule_runner.assert_called_once()
        call = self.schedule_runner.call_args
        self.assertIs(call.args[2], modeling_router.run_modeling_task_async)
        self.assertEqual(call.args[3], "task-1")
        self.assertEqual(call.args[4], snapshot["ques_all"])

    async def test_completed_task_cannot_be_resumed(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "completed", "message": "done"}, handle)
            with mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir):
                with self.assertRaises(HTTPException) as caught:
                    await modeling_router.resume_task("task-1", BackgroundTasks())

        self.assertEqual(caught.exception.status_code, 409)

    async def test_completed_task_with_editorial_export_only_checkpoint_can_resume(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._write_checkpoint(
                work_dir,
                workflow_state="editorial_repair_pending_export",
            )
            with open(
                os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump({"status": "completed", "message": "old export done"}, handle)
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(
                    modeling_router.redis_manager, "set", new_callable=mock.AsyncMock
                ),
                mock.patch.object(modeling_router, "write_task_status") as status_mock,
            ):
                background = BackgroundTasks()
                response = await modeling_router.resume_task("task-1", background)

        self.assertEqual(response.status, "resuming")
        self.schedule_runner.assert_called_once()
        self.assertIs(
            self.schedule_runner.call_args.args[2],
            modeling_router.run_resume_task_async,
        )
        status_mock.assert_called_once_with("task-1", "resuming", "从检查点受控续传中")

    async def test_completed_task_with_presentation_reflow_checkpoint_can_resume(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._write_checkpoint(work_dir, "presentation_reflow_pending_export")
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(modeling_router, "read_task_status", return_value={"status": "completed"}),
                mock.patch.object(modeling_router.redis_manager, "set", new_callable=mock.AsyncMock),
                mock.patch.object(modeling_router, "write_task_status") as status_mock,
            ):
                background = BackgroundTasks()
                response = await modeling_router.resume_task("task-1", background)

        self.assertEqual(response.status, "resuming")
        self.schedule_runner.assert_called_once()
        self.assertIs(
            self.schedule_runner.call_args.args[2],
            modeling_router.run_resume_task_async,
        )
        status_mock.assert_called_once_with("task-1", "resuming", "从检查点受控续传中")

    async def test_remodelled_resume_waiting_review_does_not_finalize(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(modeling_router, "write_task_status") as status_mock,
                mock.patch.object(
                    modeling_router.redis_manager,
                    "publish_message",
                    new_callable=mock.AsyncMock,
                ),
                mock.patch("app.routers.modeling_router.asyncio.sleep", new_callable=mock.AsyncMock),
                mock.patch.object(modeling_router, "MathModelWorkFlow") as workflow_cls,
                mock.patch.object(modeling_router, "_finalize_docx_and_manifest") as finalize,
            ):
                workflow_cls.return_value.resume = mock.AsyncMock(
                    return_value="waiting_review"
                )
                await modeling_router.run_resume_task_async("unit-task")

        status_mock.assert_any_call(
            "unit-task", "waiting_review", "任务等待人工确认建模方案"
        )
        finalize.assert_not_called()
