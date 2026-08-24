"""Focused regression tests for the pre-release hardening fixes."""

import asyncio
import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.config.setting import settings
from app.core.checkpoint import CheckpointManager, TaskCheckpoint
from app.main import RequestBodyLimitMiddleware
from app.routers import modeling_router
from app.routers.modeling_router import SaveApiConfigRequest
from app.services import task_status as task_status_service
from app.services import user_input_queue
from app.services.task_status import recover_stale_task_statuses, write_task_status
from app.tools.local_interpreter import LocalCodeInterpreter
from app.tools.notebook_serializer import NotebookSerializer


class TestChunkedBodyLimit(unittest.IsolatedAsyncioTestCase):
    async def _run_asgi(
        self,
        chunks: list[bytes],
        limit: int,
        headers: list[tuple[bytes, bytes]] | None = None,
    ):
        received = []
        sent = []
        messages = [
            {
                "type": "http.request",
                "body": chunk,
                "more_body": index < len(chunks) - 1,
            }
            for index, chunk in enumerate(chunks)
        ]

        async def receive():
            message = messages.pop(0)
            return message

        async def send(message):
            sent.append(message)

        async def app_under_test(scope, receive_callback, send_callback):
            while True:
                message = await receive_callback()
                if message["type"] != "http.request":
                    break
                received.append(message["body"])
                if not message.get("more_body"):
                    break
            body = b"".join(received)
            await send_callback(
                {"type": "http.response.start", "status": 200, "headers": []}
            )
            await send_callback(
                {"type": "http.response.body", "body": body}
            )

        middleware = RequestBodyLimitMiddleware(app_under_test, max_body_bytes=limit)
        await middleware(
            {
                "type": "http",
                "method": "POST",
                "headers": headers
                if headers is not None
                else [(b"transfer-encoding", b"chunked")],
            },
            receive,
            send,
        )
        return received, sent

    async def test_chunked_multi_chunk_body_is_preserved(self):
        received, sent = await self._run_asgi([b"{\"a\":", b"1}"], limit=32)
        self.assertEqual(received, [b"{\"a\":", b"1}"])
        self.assertEqual(sent[0]["status"], 200)

    async def test_chunked_body_over_limit_returns_413(self):
        received, sent = await self._run_asgi([b"1234", b"5678"], limit=7)
        self.assertEqual(received, [b"1234"])
        self.assertEqual(sent[0]["status"], 413)

    async def test_declared_length_cannot_hide_extra_stream_bytes(self):
        received, sent = await self._run_asgi(
            [b"12", b"3"],
            limit=10,
            headers=[(b"content-length", b"2")],
        )
        self.assertEqual(received, [b"12"])
        self.assertEqual(sent[0]["status"], 413)

    def test_httpx_generator_has_no_content_length_and_is_limited(self):
        captured_scope = {}

        async def capture_app(scope, receive, send):
            if scope["type"] == "lifespan":
                while True:
                    message = await receive()
                    if message["type"] == "lifespan.startup":
                        await send({"type": "lifespan.startup.complete"})
                    elif message["type"] == "lifespan.shutdown":
                        await send({"type": "lifespan.shutdown.complete"})
                        return
            captured_scope.update(scope)
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] != "http.request":
                    break
                body.extend(message.get("body", b""))
                if not message.get("more_body"):
                    break
            await send(
                {"type": "http.response.start", "status": 200, "headers": []}
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": str(len(body)).encode("ascii"),
                }
            )

        limited_app = RequestBodyLimitMiddleware(capture_app, max_body_bytes=128)
        with TestClient(limited_app, base_url="http://localhost") as client:
            response = client.post(
                "/",
                content=(chunk for chunk in [b"{}" * 100]),
                headers={"content-type": "application/json"},
            )
        scope_headers = dict(captured_scope["headers"])
        self.assertNotIn(b"content-length", scope_headers)
        self.assertEqual(response.status_code, 413)


class TestBroadcastQueueBounded(unittest.TestCase):
    def setUp(self):
        self.task_id = "pre-release-broadcast"
        user_input_queue.clear(self.task_id)
        self.addCleanup(user_input_queue.clear, self.task_id)

    def test_near_full_broadcast_reaches_each_role_once(self):
        expected = [f"broadcast-{index}" for index in range(user_input_queue.MAX_QUEUE_SIZE)]
        for item in expected:
            self.assertTrue(user_input_queue.push(self.task_id, item, "all"))

        for role in ("coordinator", "modeler", "coder", "writer"):
            self.assertEqual(user_input_queue.pop_for(self.task_id, role), expected)
            self.assertEqual(user_input_queue.pop_for(self.task_id, role), [])


class TestRevisingStatusRecovery(unittest.TestCase):
    def test_revising_is_recovered_as_stale(self):
        with tempfile.TemporaryDirectory() as root:
            task_dir = os.path.join(root, "revising-task")
            os.makedirs(task_dir)
            with mock.patch(
                "app.services.task_status.get_work_dir", return_value=task_dir
            ):
                write_task_status("revising-task", "revising", "old revision worker")

            self.assertEqual(recover_stale_task_statuses(root), ["revising-task"])
            with open(
                os.path.join(task_dir, "task_status.json"), encoding="utf-8"
            ) as handle:
                self.assertEqual(json.load(handle)["status"], "interrupted")


class TestApiConfigSchema(unittest.TestCase):
    def test_invalid_nested_provider_and_negative_context_window_are_422(self):
        test_app = FastAPI()
        test_app.include_router(modeling_router.router)
        client = TestClient(test_app)
        base = {"coordinator": {}, "modeler": {}, "coder": {}, "writer": {}, "openalex_email": ""}

        invalid_provider = {**base, "coordinator": {"apiType": "unknown-provider"}}
        negative_window = {**base, "coordinator": {"contextWindow": -1}}
        self.assertEqual(client.post("/save-api-config", json=invalid_provider).status_code, 422)
        self.assertEqual(client.post("/save-api-config", json=negative_window).status_code, 422)

    def test_empty_fields_preserve_settings_and_unknown_fields_reject(self):
        request = SaveApiConfigRequest(
            coordinator={"apiKey": "", "apiType": "", "contextWindow": ""},
            modeler={},
            coder={},
            writer={},
            openalex_email="",
        )
        with mock.patch.object(settings, "COORDINATOR_API_KEY", "existing"):
            asyncio.run(modeling_router.save_api_config(request))
            self.assertEqual(settings.COORDINATOR_API_KEY, "existing")
        with self.assertRaises(Exception):
            SaveApiConfigRequest(
                coordinator={"unexpected": "value"},
                modeler={},
                coder={},
                writer={},
                openalex_email="",
            )


class TestApiConfigAtomicity(unittest.IsolatedAsyncioTestCase):
    async def test_assignment_failure_rolls_back_already_applied_fields(self):
        class FailingSettings:
            COORDINATOR_BASE_URL = None
            MODELER_BASE_URL = None
            CODER_BASE_URL = None
            WRITER_BASE_URL = None
            COORDINATOR_API_KEY = "old-coordinator"
            MODELER_API_KEY = "old-modeler"
            CODER_API_KEY = None
            WRITER_API_KEY = None
            OPENALEX_EMAIL = "old@example.test"

            def __setattr__(self, name, value):
                if name == "MODELER_API_KEY" and value == "new-modeler":
                    raise RuntimeError("simulated settings write failure")
                object.__setattr__(self, name, value)

        fake_settings = FailingSettings()
        request = SaveApiConfigRequest(
            coordinator={"apiKey": "new-coordinator"},
            modeler={"apiKey": "new-modeler"},
            coder={},
            writer={},
            openalex_email="new@example.test",
        )
        with mock.patch.object(modeling_router, "settings", fake_settings):
            with self.assertRaisesRegex(Exception, "保存配置失败"):
                await modeling_router.save_api_config(request)
        self.assertEqual(fake_settings.COORDINATOR_API_KEY, "old-coordinator")
        self.assertEqual(fake_settings.MODELER_API_KEY, "old-modeler")
        self.assertEqual(fake_settings.OPENALEX_EMAIL, "old@example.test")

    async def test_concurrent_saves_leave_a_complete_provider_pair(self):
        request_a = SaveApiConfigRequest(
            coordinator={
                "apiKey": "key-a",
                "baseUrl": "https://8.8.8.8/v1",
                "modelId": "model-a",
            },
            modeler={},
            coder={},
            writer={},
            openalex_email="",
        )
        request_b = SaveApiConfigRequest(
            coordinator={
                "apiKey": "key-b",
                "baseUrl": "https://1.1.1.1/v1",
                "modelId": "model-b",
            },
            modeler={},
            coder={},
            writer={},
            openalex_email="",
        )
        with (
            mock.patch.object(modeling_router.settings, "COORDINATOR_API_KEY", "old"),
            mock.patch.object(modeling_router.settings, "COORDINATOR_BASE_URL", ""),
            mock.patch.object(modeling_router.settings, "COORDINATOR_MODEL", "old-model"),
        ):
            async def save(request):
                return await modeling_router.save_api_config(request)

            results = await asyncio.gather(save(request_a), save(request_b))
            self.assertTrue(all(result["success"] for result in results))
            final_pair = (
                modeling_router.settings.COORDINATOR_API_KEY,
                modeling_router.settings.COORDINATOR_BASE_URL,
                modeling_router.settings.COORDINATOR_MODEL,
            )
        self.assertIn(
            final_pair,
            {
                ("key-a", "https://8.8.8.8/v1", "model-a"),
                ("key-b", "https://1.1.1.1/v1", "model-b"),
            },
        )


class TestDispatchReservation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        modeling_router._active_tasks.clear()
        self._real_schedule_runner = modeling_router._schedule_reserved_runner
        self._schedule_patcher = mock.patch.object(
            modeling_router, "_schedule_reserved_runner"
        )
        self.schedule_runner = self._schedule_patcher.start()

    async def asyncTearDown(self):
        self._schedule_patcher.stop()
        modeling_router._active_tasks.clear()

    async def test_reservation_is_identity_safe(self):
        first = modeling_router._reserve_active_task("reservation-task")
        self.assertIsNotNone(first)
        self.assertIsNone(modeling_router._reserve_active_task("reservation-task"))
        second = asyncio.Event()
        modeling_router._release_active_task("reservation-task", second)
        self.assertIn("reservation-task", modeling_router._active_tasks)
        modeling_router._release_active_task("reservation-task", first)
        self.assertNotIn("reservation-task", modeling_router._active_tasks)

    async def test_direct_runner_is_registered_before_response_delivery(self):
        token = modeling_router._reserve_active_task("direct-runner")
        self.assertIsNotNone(token)
        scheduled_task = object()
        runner = mock.Mock(return_value=None)
        with mock.patch.object(
            modeling_router.asyncio, "create_task", return_value=scheduled_task
        ) as create_task:
            self._real_schedule_runner(
                "direct-runner", token, runner, "direct-runner"
            )
        create_task.assert_called_once()
        self.assertIs(
            modeling_router._active_tasks["direct-runner"][0], scheduled_task
        )
        modeling_router._release_active_task("direct-runner", token)

    async def test_direct_runner_executes_without_background_callback(self):
        token = modeling_router._reserve_active_task("direct-runner")
        self.assertIsNotNone(token)
        ran = asyncio.Event()

        async def runner(task_id, *, cancel_event):
            self.assertIs(cancel_event, token)
            ran.set()
            modeling_router._release_active_task(task_id, cancel_event)

        self._real_schedule_runner(
            "direct-runner", token, runner, "direct-runner"
        )
        await asyncio.wait_for(ran.wait(), timeout=1)
        self.assertNotIn("direct-runner", modeling_router._active_tasks)

    async def test_resume_publish_prelude_failure_releases_placeholder(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
                mock.patch.object(
                    modeling_router.redis_manager,
                    "publish_message",
                    new=mock.AsyncMock(side_effect=RuntimeError("publish unavailable")),
                ),
            ):
                await modeling_router.run_resume_task_async("prelude-failure")
            with open(os.path.join(work_dir, "task_status.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["status"], "failed")
        self.assertNotIn("prelude-failure", modeling_router._active_tasks)

    async def test_initial_runner_publish_failure_releases_placeholder(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
                mock.patch.object(
                    modeling_router.redis_manager,
                    "publish_message",
                    new=mock.AsyncMock(side_effect=RuntimeError("publish unavailable")),
                ),
            ):
                await modeling_router.run_modeling_task_async(
                    "initial-prelude-failure",
                    "题面",
                    modeling_router.CompTemplate.CHINA,
                    modeling_router.FormatOutPut.Markdown,
                )
            with open(os.path.join(work_dir, "task_status.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["status"], "failed")
        self.assertNotIn("initial-prelude-failure", modeling_router._active_tasks)

    async def test_revision_workflow_constructor_failure_releases_placeholder(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with (
                mock.patch.object(modeling_router, "MathModelWorkFlow", side_effect=RuntimeError("workflow unavailable")),
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
                mock.patch.object(
                    modeling_router.redis_manager,
                    "publish_message",
                    new=mock.AsyncMock(),
                ),
            ):
                await modeling_router.run_revise_modeling_async(
                    "revision-prelude-failure", "修订意见"
                )
            with open(os.path.join(work_dir, "task_status.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["status"], "failed")
        self.assertNotIn("revision-prelude-failure", modeling_router._active_tasks)

    async def test_second_dispatch_is_rejected_while_first_is_reserved(self):
        event = modeling_router._reserve_active_task("concurrent-task")
        self.assertIsNotNone(event)
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "waiting_review"}, handle)
            self.assertIn("运行中", modeling_router._check_dispatch_guard(work_dir, "concurrent-task"))

    @staticmethod
    def _write_review_checkpoint(work_dir: str, *, quality: bool = False) -> None:
        checkpoint = TaskCheckpoint(
            task_id="dispatch-endpoint",
            ques_all="题面",
            comp_template="CHINA",
            format_output="Markdown",
            export_profile="cumcm2026",
            questions={"ques_count": 1, "ques1": "问题一"},
            ques_count=1,
            modeler_response={},
            workflow_state="waiting_quality_review" if quality else "solving",
            quality_review_status="pending" if quality else "not_run",
            quality_review_id="review-1" if quality else "",
            updated_at="2026-08-23T00:00:00",
        )
        CheckpointManager(work_dir).save(checkpoint)

    async def test_initial_modeling_redis_failure_releases_reservation(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with (
                mock.patch.object(modeling_router, "create_task_id", return_value="dispatch-endpoint"),
                mock.patch.object(modeling_router, "create_work_dir", return_value=work_dir),
                mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
                mock.patch.object(
                    modeling_router.redis_manager,
                    "set",
                    new=mock.AsyncMock(side_effect=RuntimeError("redis unavailable")),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "redis unavailable"):
                    await modeling_router.modeling(
                        BackgroundTasks(),
                        "题面",
                        modeling_router.CompTemplate.CHINA,
                        modeling_router.FormatOutPut.Markdown,
                        modeling_router.DEFAULT_MODELING_EXPORT_PROFILE,
                        False,
                        "all",
                        "",
                        "review",
                        None,
                    )
        self.assertNotIn("dispatch-endpoint", modeling_router._active_tasks)

    async def test_second_initial_dispatch_gets_409_while_placeholder_is_live(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with (
                mock.patch.object(modeling_router, "create_task_id", return_value="dispatch-endpoint"),
                mock.patch.object(modeling_router, "create_work_dir", return_value=work_dir),
                mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
                mock.patch.object(modeling_router.redis_manager, "set", new=mock.AsyncMock()),
            ):
                await modeling_router.modeling(
                    BackgroundTasks(),
                    "题面",
                    modeling_router.CompTemplate.CHINA,
                    modeling_router.FormatOutPut.Markdown,
                    modeling_router.DEFAULT_MODELING_EXPORT_PROFILE,
                    False,
                    "all",
                    "",
                    "review",
                    None,
                )
                with self.assertRaises(HTTPException) as caught:
                    await modeling_router.modeling(
                        BackgroundTasks(),
                        "题面",
                        modeling_router.CompTemplate.CHINA,
                        modeling_router.FormatOutPut.Markdown,
                        modeling_router.DEFAULT_MODELING_EXPORT_PROFILE,
                        False,
                        "all",
                        "",
                        "review",
                        None,
                    )
        self.assertEqual(caught.exception.status_code, 409)
        entry = modeling_router._active_tasks.get("dispatch-endpoint")
        if entry is not None:
            modeling_router._release_active_task("dispatch-endpoint", entry[1])
        self.assertNotIn("dispatch-endpoint", modeling_router._active_tasks)

    async def test_approve_publish_failure_releases_reservation(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._write_review_checkpoint(work_dir)
            with open(os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "waiting_review"}, handle)
            plan_hash = modeling_router._canonical_json_sha256({})
            with open(os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            with open(os.path.join(work_dir, "modeling_decision.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "waiting_review", "modeler_response": {}, "modeler_plan_sha256": plan_hash}, handle)
            checkpoint_before = Path(os.path.join(work_dir, "checkpoint.json")).read_bytes()
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
                mock.patch.object(modeling_router.redis_manager, "set", new=mock.AsyncMock()),
                mock.patch.object(
                    modeling_router.redis_manager,
                    "publish_message",
                    new=mock.AsyncMock(
                        side_effect=[RuntimeError("publish unavailable"), None]
                    ),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "publish unavailable"):
                    await modeling_router.approve_modeling(
                        "dispatch-endpoint", BackgroundTasks()
                    )
                with open(
                    os.path.join(work_dir, "task_status.json"), encoding="utf-8"
                ) as handle:
                    self.assertEqual(json.load(handle)["status"], "waiting_review")
                with open(
                    os.path.join(work_dir, "modeling_decision.json"), encoding="utf-8"
                ) as handle:
                    self.assertEqual(json.load(handle)["status"], "waiting_review")
                self.assertEqual(
                    Path(os.path.join(work_dir, "checkpoint.json")).read_bytes(),
                    checkpoint_before,
                )
                response = await modeling_router.approve_modeling(
                    "dispatch-endpoint", BackgroundTasks()
                )
                self.assertEqual(response.status, "resuming")
                with open(
                    os.path.join(work_dir, "task_status.json"), encoding="utf-8"
                ) as handle:
                    self.assertEqual(json.load(handle)["status"], "resuming")
                with open(
                    os.path.join(work_dir, "modeling_decision.json"), encoding="utf-8"
                ) as handle:
                    self.assertEqual(json.load(handle)["status"], "approved")
                entry = modeling_router._active_tasks.get("dispatch-endpoint")
                self.assertIsNotNone(entry)
                modeling_router._release_active_task("dispatch-endpoint", entry[1])
        self.assertNotIn("dispatch-endpoint", modeling_router._active_tasks)

    async def test_snapshot_failure_releases_reservation(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._write_review_checkpoint(work_dir)
            with open(os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "waiting_review"}, handle)
            plan_hash = modeling_router._canonical_json_sha256({})
            with open(os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            with open(os.path.join(work_dir, "modeling_decision.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "waiting_review", "modeler_response": {}, "modeler_plan_sha256": plan_hash}, handle)
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
                mock.patch.object(
                    modeling_router,
                    "_snapshot_files",
                    side_effect=OSError("snapshot unavailable"),
                ),
            ):
                with self.assertRaisesRegex(OSError, "snapshot unavailable"):
                    await modeling_router.approve_modeling(
                        "dispatch-endpoint", BackgroundTasks()
                    )
        self.assertNotIn("dispatch-endpoint", modeling_router._active_tasks)

    async def test_restore_failure_does_not_hide_original_error_or_reservation(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._write_review_checkpoint(work_dir)
            with open(os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "waiting_review"}, handle)
            plan_hash = modeling_router._canonical_json_sha256({})
            with open(os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            with open(os.path.join(work_dir, "modeling_decision.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "waiting_review", "modeler_response": {}, "modeler_plan_sha256": plan_hash}, handle)
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
                mock.patch.object(modeling_router.redis_manager, "set", new=mock.AsyncMock()),
                mock.patch.object(
                    modeling_router.redis_manager,
                    "publish_message",
                    new=mock.AsyncMock(side_effect=RuntimeError("publish unavailable")),
                ),
                mock.patch.object(
                    modeling_router,
                    "_restore_files",
                    side_effect=OSError("rollback unavailable"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "publish unavailable"):
                    await modeling_router.approve_modeling(
                        "dispatch-endpoint", BackgroundTasks()
                    )
        self.assertNotIn("dispatch-endpoint", modeling_router._active_tasks)

    async def test_revise_rollback_drains_runner_before_restore_failure(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._write_review_checkpoint(work_dir)
            with open(os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "waiting_review"}, handle)
            with open(os.path.join(work_dir, "modeling_decision.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "waiting_review", "review": {"approved": False}}, handle)
            scheduled = asyncio.create_task(asyncio.sleep(60))
            self.schedule_runner.return_value = scheduled
            try:
                with (
                    mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                    mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
                    mock.patch.object(modeling_router.redis_manager, "publish_message", new=mock.AsyncMock()),
                    mock.patch.object(
                        modeling_router,
                        "_restore_files",
                        side_effect=OSError("rollback unavailable"),
                    ),
                    mock.patch.object(
                        user_input_queue,
                        "push",
                        side_effect=RuntimeError("queue unavailable"),
                    ),
                ):
                    with self.assertRaisesRegex(RuntimeError, "queue unavailable"):
                        await modeling_router.revise_modeling(
                            "dispatch-endpoint",
                            BackgroundTasks(),
                            modeling_router.ReviseModelingRequest(comment="请修订"),
                        )
            finally:
                if not scheduled.done():
                    scheduled.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await scheduled
        self.assertTrue(scheduled.done())
        self.assertNotIn("dispatch-endpoint", modeling_router._active_tasks)

    async def test_revise_publish_failure_releases_reservation(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._write_review_checkpoint(work_dir)
            with open(os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "waiting_review"}, handle)
            with open(os.path.join(work_dir, "modeling_decision.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "waiting_review", "review": {"approved": False}}, handle)
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
                mock.patch.object(
                    modeling_router.redis_manager,
                    "publish_message",
                    new=mock.AsyncMock(
                        side_effect=[RuntimeError("publish unavailable"), None]
                    ),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "publish unavailable"):
                    await modeling_router.revise_modeling(
                        "dispatch-endpoint",
                        BackgroundTasks(),
                        modeling_router.ReviseModelingRequest(comment="请修订"),
                    )
                with open(
                    os.path.join(work_dir, "task_status.json"), encoding="utf-8"
                ) as handle:
                    self.assertEqual(json.load(handle)["status"], "waiting_review")
                with open(
                    os.path.join(work_dir, "checkpoint.json"), encoding="utf-8"
                ) as handle:
                    self.assertEqual(json.load(handle)["modeling_review_revisions"], 0)
                with open(
                    os.path.join(work_dir, "modeling_decision.json"), encoding="utf-8"
                ) as handle:
                    self.assertEqual(json.load(handle)["status"], "waiting_review")
                user_input_queue.clear("dispatch-endpoint")
                response = await modeling_router.revise_modeling(
                    "dispatch-endpoint",
                    BackgroundTasks(),
                    modeling_router.ReviseModelingRequest(comment="请修订"),
                )
                self.assertEqual(response.status, "revising")
                with open(
                    os.path.join(work_dir, "task_status.json"), encoding="utf-8"
                ) as handle:
                    self.assertEqual(json.load(handle)["status"], "revising")
                with open(
                    os.path.join(work_dir, "checkpoint.json"), encoding="utf-8"
                ) as handle:
                    self.assertEqual(json.load(handle)["modeling_review_revisions"], 1)
                with open(
                    os.path.join(work_dir, "modeling_decision.json"), encoding="utf-8"
                ) as handle:
                    self.assertEqual(json.load(handle)["status"], "revising")
                entry = modeling_router._active_tasks.get("dispatch-endpoint")
                self.assertIsNotNone(entry)
                modeling_router._release_active_task("dispatch-endpoint", entry[1])
        self.assertNotIn("dispatch-endpoint", modeling_router._active_tasks)
        user_input_queue.clear("dispatch-endpoint")

    async def test_execution_review_repair_publish_failure_releases_reservation(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._write_review_checkpoint(work_dir, quality=True)
            with open(os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "waiting_quality_review"}, handle)
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
                mock.patch.object(modeling_router.redis_manager, "set", new=mock.AsyncMock()),
                mock.patch.object(
                    modeling_router.redis_manager,
                    "publish_message",
                    new=mock.AsyncMock(
                        side_effect=[RuntimeError("publish unavailable"), None]
                    ),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "publish unavailable"):
                    await modeling_router.review_execution_quality(
                        "dispatch-endpoint",
                        BackgroundTasks(),
                        modeling_router.ExecutionReviewRequest(
                            action="repair",
                            review_id="review-1",
                            failed_subtasks=["ques1"],
                            comment="请重算",
                        ),
                    )
                with open(
                    os.path.join(work_dir, "task_status.json"), encoding="utf-8"
                ) as handle:
                    self.assertEqual(
                        json.load(handle)["status"], "waiting_quality_review"
                    )
                with open(
                    os.path.join(work_dir, "checkpoint.json"), encoding="utf-8"
                ) as handle:
                    checkpoint = json.load(handle)
                    self.assertEqual(checkpoint["quality_review_repairs"], 0)
                    self.assertEqual(checkpoint["workflow_state"], "waiting_quality_review")
                response = await modeling_router.review_execution_quality(
                    "dispatch-endpoint",
                    BackgroundTasks(),
                    modeling_router.ExecutionReviewRequest(
                        action="repair",
                        review_id="review-1",
                        failed_subtasks=["ques1"],
                        comment="请重算",
                    ),
                )
                self.assertEqual(response.status, "resuming")
                with open(
                    os.path.join(work_dir, "task_status.json"), encoding="utf-8"
                ) as handle:
                    self.assertEqual(json.load(handle)["status"], "resuming")
                with open(
                    os.path.join(work_dir, "checkpoint.json"), encoding="utf-8"
                ) as handle:
                    checkpoint = json.load(handle)
                    self.assertEqual(checkpoint["quality_review_repairs"], 1)
                    self.assertEqual(checkpoint["workflow_state"], "quality_repair")
                entry = modeling_router._active_tasks.get("dispatch-endpoint")
                self.assertIsNotNone(entry)
                modeling_router._release_active_task("dispatch-endpoint", entry[1])
        self.assertNotIn("dispatch-endpoint", modeling_router._active_tasks)

    async def test_resume_redis_failure_releases_reservation(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._write_review_checkpoint(work_dir)
            with open(os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "failed"}, handle)
            checkpoint_before = Path(os.path.join(work_dir, "checkpoint.json")).read_bytes()
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
                mock.patch.object(
                    modeling_router.redis_manager,
                    "set",
                    new=mock.AsyncMock(
                        side_effect=[RuntimeError("redis unavailable"), None]
                    ),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "redis unavailable"):
                    await modeling_router.resume_task(
                        "dispatch-endpoint", BackgroundTasks()
                    )
                with open(
                    os.path.join(work_dir, "task_status.json"), encoding="utf-8"
                ) as handle:
                    self.assertEqual(json.load(handle)["status"], "failed")
                self.assertEqual(
                    Path(os.path.join(work_dir, "checkpoint.json")).read_bytes(),
                    checkpoint_before,
                )
                response = await modeling_router.resume_task(
                    "dispatch-endpoint", BackgroundTasks()
                )
                self.assertEqual(response.status, "resuming")
                with open(
                    os.path.join(work_dir, "task_status.json"), encoding="utf-8"
                ) as handle:
                    self.assertEqual(json.load(handle)["status"], "resuming")
                entry = modeling_router._active_tasks.get("dispatch-endpoint")
                self.assertIsNotNone(entry)
                modeling_router._release_active_task("dispatch-endpoint", entry[1])
        self.assertNotIn("dispatch-endpoint", modeling_router._active_tasks)


class TestNotificationStateOrdering(unittest.IsolatedAsyncioTestCase):
    async def test_technical_pass_publish_failure_stays_completed(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
                mock.patch.object(
                    modeling_router.redis_manager,
                    "publish_message",
                    new=mock.AsyncMock(side_effect=RuntimeError("redis unavailable")),
                ),
            ):
                self.assertTrue(
                    await modeling_router._apply_final_acceptance_status(
                        "terminal-pass", {"technical_status": "TECHNICAL_PASS"}
                    )
                )
            with open(os.path.join(work_dir, "task_status.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["status"], "completed")

    async def test_waiting_review_publish_failure_stays_waiting_review(self):
        with tempfile.TemporaryDirectory() as work_dir:
            workflow = mock.Mock()
            workflow.resume = mock.AsyncMock(return_value="waiting_review")
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
                mock.patch.object(modeling_router, "MathModelWorkFlow", return_value=workflow),
                mock.patch.object(modeling_router.asyncio, "sleep", new=mock.AsyncMock()),
                mock.patch.object(
                    modeling_router.redis_manager,
                    "publish_message",
                    new=mock.AsyncMock(
                        side_effect=[None, RuntimeError("redis unavailable")]
                    ),
                ),
            ):
                await modeling_router.run_resume_task_async("waiting-notify")
            with open(os.path.join(work_dir, "task_status.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["status"], "waiting_review")
        self.assertNotIn("waiting-notify", modeling_router._active_tasks)

    async def test_initial_waiting_review_publish_failure_stays_waiting_review(self):
        with tempfile.TemporaryDirectory() as work_dir:
            workflow = mock.Mock()
            workflow.execute = mock.AsyncMock(return_value="waiting_review")
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
                mock.patch.object(modeling_router, "MathModelWorkFlow", return_value=workflow),
                mock.patch.object(modeling_router.asyncio, "sleep", new=mock.AsyncMock()),
                mock.patch.object(
                    modeling_router.redis_manager,
                    "publish_message",
                    new=mock.AsyncMock(
                        side_effect=[None, RuntimeError("redis unavailable")]
                    ),
                ),
            ):
                await modeling_router.run_modeling_task_async(
                    "initial-waiting-notify",
                    "题面",
                    modeling_router.CompTemplate.CHINA,
                    modeling_router.FormatOutPut.Markdown,
                )
            with open(os.path.join(work_dir, "task_status.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["status"], "waiting_review")
        self.assertNotIn("initial-waiting-notify", modeling_router._active_tasks)

    async def test_revision_waiting_review_publish_failure_stays_waiting_review(self):
        with tempfile.TemporaryDirectory() as work_dir:
            workflow = mock.Mock()
            workflow.revise_modeling = mock.AsyncMock(return_value="waiting_review")
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
                mock.patch.object(modeling_router, "MathModelWorkFlow", return_value=workflow),
                mock.patch.object(
                    modeling_router.redis_manager,
                    "publish_message",
                    new=mock.AsyncMock(side_effect=RuntimeError("redis unavailable")),
                ),
            ):
                await modeling_router.run_revise_modeling_async(
                    "revision-waiting-notify", "请修订"
                )
            with open(os.path.join(work_dir, "task_status.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["status"], "waiting_review")
        self.assertNotIn("revision-waiting-notify", modeling_router._active_tasks)

    async def test_cancellation_persists_before_notification_failure(self):
        with tempfile.TemporaryDirectory() as work_dir:
            sleep_started = asyncio.Event()
            blocked = asyncio.Event()

            async def block_sleep(_delay):
                sleep_started.set()
                await blocked.wait()

            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
                mock.patch.object(modeling_router.asyncio, "sleep", new=block_sleep),
                mock.patch.object(
                    modeling_router.redis_manager,
                    "publish_message",
                    new=mock.AsyncMock(
                        side_effect=[None, RuntimeError("redis unavailable")]
                    ),
                ),
            ):
                runner = asyncio.create_task(
                    modeling_router.run_resume_task_async("cancel-before-notify")
                )
                await asyncio.wait_for(sleep_started.wait(), timeout=1)
                runner.cancel()
                await runner
            with open(os.path.join(work_dir, "task_status.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["status"], "cancelled")
        self.assertNotIn("cancel-before-notify", modeling_router._active_tasks)

    async def test_safe_publish_does_not_swallow_cancellation_or_system_exit(self):
        for error in (asyncio.CancelledError(), SystemExit("stop")):
            with mock.patch.object(
                modeling_router.redis_manager,
                "publish_message",
                new=mock.AsyncMock(side_effect=error),
            ):
                with self.assertRaises(type(error)):
                    await modeling_router._safe_publish_message(
                        "base-exception", modeling_router.SystemMessage(content="notice")
                    )


class TestLocalInterpreterExecutor(unittest.IsolatedAsyncioTestCase):
    async def test_execute_and_replay_leave_event_loop_responsive(self):
        with tempfile.TemporaryDirectory() as work_dir:
            interpreter = LocalCodeInterpreter(
                "heartbeat-task", work_dir, NotebookSerializer(work_dir), execution_timeout=2
            )
            interpreter.execute_code_ = mock.Mock(
                side_effect=lambda code: (time.sleep(0.08), [("stdout", code)])[1]
            )
            with (
                mock.patch.object(interpreter, "_push_to_websocket", new=mock.AsyncMock()),
                mock.patch.object(
                    interpreter,
                    "_recover_kernel_after_timeout",
                    new=mock.AsyncMock(return_value=False),
                ),
                mock.patch(
                    "app.tools.local_interpreter.redis_manager.publish_message",
                    new=mock.AsyncMock(),
                ),
            ):
                ticks = 0

                async def heartbeat():
                    nonlocal ticks
                    for _ in range(4):
                        await asyncio.sleep(0.02)
                        ticks += 1

                result, _ = await asyncio.gather(
                    interpreter.execute_code("run"),
                    heartbeat(),
                )
                replay_ticks = 0

                async def replay_heartbeat():
                    nonlocal replay_ticks
                    for _ in range(4):
                        await asyncio.sleep(0.02)
                        replay_ticks += 1

                replay_result, _ = await asyncio.gather(
                    interpreter.replay_code("replay"),
                    replay_heartbeat(),
                )
                await interpreter.cleanup()

        self.assertGreaterEqual(ticks, 3)
        self.assertGreaterEqual(replay_ticks, 3)
        self.assertIn("run", result[0])
        self.assertFalse(replay_result[1])
        self.assertIn("replay", replay_result[0])

    async def test_cancel_and_timeout_interrupt_then_drain_worker(self):
        with tempfile.TemporaryDirectory() as work_dir:
            interpreter = LocalCodeInterpreter(
                "cancel-task", work_dir, NotebookSerializer(work_dir), execution_timeout=1
            )
            finished = threading.Event()

            def blocking(_code):
                finished.wait(5)
                return [("stdout", "done")]

            interpreter.execute_code_ = mock.Mock(side_effect=blocking)
            def interrupt_and_release():
                interpreter.interrupt_signal = True
                finished.set()

            interrupt = mock.Mock(side_effect=interrupt_and_release)
            with mock.patch.object(interpreter, "_request_kernel_interrupt", interrupt):
                task = asyncio.create_task(interpreter.replay_code("cancel"))
                await asyncio.sleep(0.03)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertTrue(finished.is_set())
                self.assertTrue(interrupt.called)
                self.assertFalse(interpreter.interrupt_signal)
            await interpreter.cleanup()

    async def test_timeout_interrupts_and_drains_worker(self):
        with tempfile.TemporaryDirectory() as work_dir:
            interpreter = LocalCodeInterpreter(
                "timeout-task", work_dir, NotebookSerializer(work_dir), execution_timeout=1
            )
            interpreter.execution_timeout = 0.03
            finished = threading.Event()

            def blocking(_code):
                finished.wait(5)
                return [("stdout", "done")]

            interpreter.execute_code_ = mock.Mock(side_effect=blocking)
            def interrupt_and_release():
                interpreter.interrupt_signal = True
                finished.set()

            interrupt = mock.Mock(side_effect=interrupt_and_release)
            with mock.patch.object(interpreter, "_request_kernel_interrupt", interrupt):
                result = await interpreter.replay_code("timeout")
            self.assertTrue(finished.is_set())
            self.assertTrue(interrupt.called)
            self.assertFalse(interpreter.interrupt_signal)
            self.assertTrue(result[1])
            await interpreter.cleanup()


class TestFrontendRuntimeStatusContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repo_root = Path(__file__).resolve().parents[3]
        cls.common_api = (repo_root / "frontend/src/apis/commonApi.ts").read_text(
            encoding="utf-8"
        )
        cls.task_store = (repo_root / "frontend/src/stores/task.ts").read_text(
            encoding="utf-8"
        )
        cls.task_page = (repo_root / "frontend/src/pages/task/index.vue").read_text(
            encoding="utf-8"
        )

    def test_backend_status_union_and_active_set_are_explicit(self):
        for status in ("revising", "waiting_quality_review", "finalizing"):
            self.assertIn(status, self.common_api)
        for status in ("pending", "running", "resuming", "revising", "finalizing"):
            self.assertIn(status, self.task_store)

    def test_status_refresh_is_task_scoped_and_websocket_is_not_authoritative(self):
        self.assertIn("statusRequestGeneration", self.task_store)
        self.assertIn("currentTaskId.value !== taskId", self.task_store)
        self.assertIn("listTasks", self.task_store)
        self.assertIn("syncTaskStatus(props.task_id", self.task_page)
        self.assertIn("refreshTaskStatus(taskId)", self.task_store)
        websocket_handler = self.task_store.split("ws = new TaskWebSocket", 1)[1]
        self.assertNotIn("isRunning.value = false", websocket_handler)
