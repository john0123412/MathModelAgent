"""任务消息历史读取测试。"""

import json
import os
import tempfile
import unittest
from unittest import mock

from app.routers.common_router import _load_task_messages_from_file


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


if __name__ == "__main__":
    unittest.main()
