"""Token usage 统计与 /track 路由测试。"""

import asyncio
import json
import os
import tempfile
import unittest
from unittest import mock

from fastapi import HTTPException

from app.core.llm.llm import LLM, simple_chat
from app.core.llm.types import StandardResponse, Usage
from app.routers import common_router
from app.schemas.enums import AgentType
from app.services import token_usage
from app.utils import common_utils


class FakeProvider:
    def __init__(self):
        self.call_count = 0

    async def call(self, **_kwargs):
        self.call_count += 1
        return StandardResponse(
            content="ok",
            usage=Usage(prompt_tokens=11, completion_tokens=7),
        )


class TestTokenUsageRecorder(unittest.TestCase):
    def test_record_usage_accumulates_by_agent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            task_dir = os.path.join(temp_dir, "task-1")
            os.makedirs(task_dir, exist_ok=True)
            with mock.patch.object(common_utils, "WORK_DIR_ROOT", temp_dir):
                token_usage.record_token_usage("task-1", "WriterAgent", "model-a", Usage(3, 2))
                token_usage.record_token_usage("task-1", "WriterAgent", "model-a", Usage(5, 4))
                token_usage.record_token_usage("task-1", "CoderAgent", "model-b", Usage(7, 6))
                report = token_usage.read_token_usage("task-1")

        self.assertTrue(report["usage_available"])
        self.assertEqual(report["agents"]["WriterAgent"]["chat_count"], 2)
        self.assertEqual(report["agents"]["WriterAgent"]["prompt_tokens"], 8)
        self.assertEqual(report["agents"]["WriterAgent"]["completion_tokens"], 6)
        self.assertEqual(report["agents"]["WriterAgent"]["total_tokens"], 14)
        self.assertEqual(report["agents"]["CoderAgent"]["total_tokens"], 13)
        self.assertEqual(report["totals"]["chat_count"], 3)
        self.assertEqual(report["totals"]["total_tokens"], 27)

    def test_record_usage_does_not_write_prompt_or_secrets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            task_dir = os.path.join(temp_dir, "task-1")
            os.makedirs(task_dir, exist_ok=True)
            with mock.patch.object(common_utils, "WORK_DIR_ROOT", temp_dir):
                token_usage.record_token_usage(
                    "task-1",
                    "WriterAgent",
                    "model-a",
                    Usage(prompt_tokens=1, completion_tokens=1),
                )
                with open(os.path.join(task_dir, "token_usage.json"), encoding="utf-8") as f:
                    content = f.read()

        self.assertNotIn("api_key", content)
        self.assertNotIn("base_url", content)
        self.assertNotIn("messages", content)
        self.assertNotIn("content", content)


class TestTrackEndpoint(unittest.TestCase):
    def test_track_returns_empty_usage_for_task_without_usage_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.makedirs(os.path.join(temp_dir, "task-1"), exist_ok=True)
            with mock.patch.object(common_utils, "WORK_DIR_ROOT", temp_dir):
                result = asyncio.run(common_router.track("task-1"))

        self.assertFalse(result["usage_available"])
        self.assertEqual(result["totals"]["total_tokens"], 0)
        self.assertEqual(result["agents"], {})

    def test_track_rejects_unsafe_task_id(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(common_router.track("../outside"))

        self.assertEqual(ctx.exception.status_code, 400)

    def test_track_returns_404_for_missing_task(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(common_utils, "WORK_DIR_ROOT", temp_dir):
                with self.assertRaises(HTTPException) as ctx:
                    asyncio.run(common_router.track("missing-task"))

        self.assertEqual(ctx.exception.status_code, 404)

    def test_track_rejects_malformed_usage_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            task_dir = os.path.join(temp_dir, "task-1")
            os.makedirs(task_dir, exist_ok=True)
            with open(os.path.join(task_dir, "token_usage.json"), "w", encoding="utf-8") as f:
                f.write("{bad json")

            with mock.patch.object(common_utils, "WORK_DIR_ROOT", temp_dir):
                with self.assertRaises(HTTPException) as ctx:
                    asyncio.run(common_router.track("task-1"))

        self.assertEqual(ctx.exception.status_code, 500)


class TestLLMUsageRecording(unittest.IsolatedAsyncioTestCase):
    async def test_chat_records_usage_without_sensitive_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            task_dir = os.path.join(temp_dir, "task-1")
            os.makedirs(task_dir, exist_ok=True)
            model = LLM(
                api_key="secret-key",
                model="test-model",
                base_url="https://example.test/v1",
                task_id="task-1",
            )
            model.provider = FakeProvider()

            with (
                mock.patch.object(common_utils, "WORK_DIR_ROOT", temp_dir),
                mock.patch.object(model, "send_message", new=mock.AsyncMock()),
            ):
                await model.chat(
                    history=[{"role": "user", "content": "do not persist me"}],
                    agent_name=AgentType.WRITER,
                )

            usage_path = os.path.join(task_dir, "token_usage.json")
            with open(usage_path, encoding="utf-8") as f:
                report = json.load(f)
            raw = json.dumps(report, ensure_ascii=False)

        self.assertEqual(report["agents"]["WriterAgent"]["total_tokens"], 18)
        self.assertNotIn("secret-key", raw)
        self.assertNotIn("do not persist me", raw)
        self.assertNotIn("https://example.test/v1", raw)

    async def test_chat_returns_response_when_usage_recording_fails(self):
        model = LLM(api_key="secret-key", model="test-model", task_id="task-1")
        provider = FakeProvider()
        model.provider = provider

        with (
            mock.patch.object(model, "send_message", new=mock.AsyncMock()),
            mock.patch(
                "app.core.llm.llm.record_token_usage",
                side_effect=RuntimeError("disk full"),
            ),
        ):
            response = await model.chat(
                history=[{"role": "user", "content": "hello"}],
                agent_name=AgentType.WRITER,
            )

        self.assertEqual(response.content, "ok")
        self.assertEqual(provider.call_count, 1)

    async def test_simple_chat_records_usage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            task_dir = os.path.join(temp_dir, "task-1")
            os.makedirs(task_dir, exist_ok=True)
            model = LLM(api_key="secret-key", model="test-model", task_id="task-1")
            model.provider = FakeProvider()

            with mock.patch.object(common_utils, "WORK_DIR_ROOT", temp_dir):
                result = await simple_chat(model, [{"role": "user", "content": "hello"}])

            with open(os.path.join(task_dir, "token_usage.json"), encoding="utf-8") as f:
                report = json.load(f)

        self.assertEqual(result, "ok")
        self.assertEqual(report["agents"]["simple_chat"]["total_tokens"], 18)

    async def test_simple_chat_returns_content_when_usage_recording_fails(self):
        model = LLM(api_key="secret-key", model="test-model", task_id="task-1")
        provider = FakeProvider()
        model.provider = provider

        with mock.patch(
            "app.core.llm.llm.record_token_usage",
            side_effect=RuntimeError("disk full"),
        ):
            result = await simple_chat(model, [{"role": "user", "content": "hello"}])

        self.assertEqual(result, "ok")
        self.assertEqual(provider.call_count, 1)


if __name__ == "__main__":
    unittest.main()
