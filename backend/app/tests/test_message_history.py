"""任务消息历史读取测试。"""

import json
import os
import tempfile
import unittest
from unittest import mock

from app.routers.common_router import _load_task_messages_from_file
from app.schemas.response import SystemMessage
from app.services.redis_manager import RedisManager
from app.utils.RichPrinter import RichPrinter


class TestMessageHistoryFallback(unittest.TestCase):
    """验证 JSON 损坏或缺失时可从 JSONL 恢复历史消息。"""

    def test_loads_from_jsonl_when_json_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            messages_dir = os.path.join(temp_dir, "logs", "messages")
            os.makedirs(messages_dir, exist_ok=True)
            with open(
                os.path.join(messages_dir, "task-1.jsonl"), "w", encoding="utf-8"
            ) as f:
                f.write(json.dumps({"id": "1", "msg_type": "system"}) + "\n")

            with mock.patch("app.routers.common_router.Path") as path_mock:
                from pathlib import Path

                path_mock.side_effect = lambda value: Path(temp_dir) / value
                messages = self._run_async(_load_task_messages_from_file("task-1"))

            self.assertEqual(messages, [{"id": "1", "msg_type": "system"}])

    @staticmethod
    def _run_async(coro):
        import asyncio

        return asyncio.run(coro)


class TestMessageLogging(unittest.IsolatedAsyncioTestCase):
    async def test_publish_log_omits_message_payload(self):
        manager = RedisManager()
        marker = "sensitive-message-marker"
        client = mock.AsyncMock()

        with mock.patch.object(
            manager, "get_client", new=mock.AsyncMock(return_value=client)
        ), mock.patch.object(
            manager, "_save_message_to_file", new=mock.AsyncMock()
        ), mock.patch("app.services.redis_manager.logger.debug") as log_debug:
            await manager.publish_message("task-1", SystemMessage(content=marker))

        logged_text = " ".join(
            str(call.args[0]) for call in log_debug.call_args_list if call.args
        )
        self.assertNotIn(marker, logged_text)
        self.assertIn("task_id=task-1", logged_text)
        self.assertIn("bytes=", logged_text)


class TestConsoleLogging(unittest.TestCase):
    def test_agent_console_output_omits_payload(self):
        marker = "sensitive-agent-message-marker"
        with mock.patch("app.utils.RichPrinter.logger.info") as log_info, mock.patch(
            "app.utils.RichPrinter.rprint"
        ) as rich_print:
            RichPrinter.print_agent_msg(marker, "WriterAgent")

        logged_text = " ".join(
            str(call.args[0]) for call in log_info.call_args_list if call.args
        )
        printed_text = " ".join(
            str(call.args[0]) for call in rich_print.call_args_list if call.args
        )
        self.assertNotIn(marker, logged_text)
        self.assertNotIn(marker, printed_text)
        self.assertIn("agent_message_chars=", logged_text)


if __name__ == "__main__":
    unittest.main()
