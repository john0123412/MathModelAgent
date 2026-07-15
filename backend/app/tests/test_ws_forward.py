"""WS 转发循环回归测试：阻塞式 get_message 替代固定 0.1s 轮询。"""

import asyncio
import json
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app.config.setting import settings
from app.services.redis_manager import redis_manager


class _FakePubSub:
    """记录 get_message 调用参数，并按脚本依次返回消息。

    消息耗尽后会真正 sleep timeout 秒：这样当测试关闭 WebSocket 连接时，
    forward loop 等待中的 get_message 协程会收到 CancelledError 并退出，
    而不是无限空转导致 receive_json() 永久阻塞。
    """

    def __init__(self, messages: list[dict]):
        self._messages = list(messages)
        self.get_message_kwargs: list[dict] = []

    async def get_message(self, **kwargs):
        self.get_message_kwargs.append(kwargs)
        if self._messages:
            return self._messages.pop(0)
        # 模拟真实 Redis 阻塞等待：消息耗尽时按 timeout 睡眠，
        # asyncio 取消信号（任务被 cancel）会中断 sleep 并抛出 CancelledError，
        # 使 forward loop 能被 TestClient 关闭连接后正常退出。
        timeout = kwargs.get("timeout") or 0
        if timeout > 0:
            await asyncio.sleep(timeout)
        return None

    async def unsubscribe(self, _channel):
        return None


class _FakeRedisClient:
    async def exists(self, _key):
        return 1


class TestForwardLoopBlockingWait(unittest.TestCase):
    """L4：转发循环应以 get_message(timeout=1.0) 阻塞等待，而非空转轮询。"""

    def _connect_and_receive(self, fake_pubsub: _FakePubSub) -> dict:
        from app.main import app

        with (
            mock.patch.object(settings, "API_AUTH_TOKEN", None),
            mock.patch.object(
                settings, "CORS_ALLOW_ORIGINS", ["http://localhost:5173"]
            ),
            mock.patch.object(
                redis_manager,
                "get_client",
                new=mock.AsyncMock(return_value=_FakeRedisClient()),
            ),
            mock.patch.object(
                redis_manager,
                "subscribe_to_task",
                new=mock.AsyncMock(return_value=fake_pubsub),
            ),
        ):
            with TestClient(app, base_url="http://localhost") as client:
                with client.websocket_connect(
                    "/task/forward-loop-task",
                    headers={
                        "origin": "http://localhost:5173",
                        "host": "localhost",
                    },
                ) as websocket:
                    return websocket.receive_json()

    def test_message_forwarded_and_get_message_blocks_with_timeout(self):
        payload = {"msg_type": "system", "content": "forward-loop-check"}
        fake_pubsub = _FakePubSub([{"data": json.dumps(payload)}])

        received = self._connect_and_receive(fake_pubsub)

        self.assertEqual(received, payload)
        # 回归守卫：必须以有限 timeout 阻塞等待。旧实现不传 timeout
        # （redis-py 默认 0.0 非阻塞）配合 sleep(0.1) 形成每秒 10 次空轮询
        self.assertGreater(len(fake_pubsub.get_message_kwargs), 0)
        for kwargs in fake_pubsub.get_message_kwargs:
            self.assertEqual(kwargs.get("timeout"), 1.0)
            self.assertTrue(kwargs.get("ignore_subscribe_messages"))

    def test_invalid_payload_sends_error_notice_and_keeps_running(self):
        good_payload = {"msg_type": "system", "content": "after-bad-data"}
        fake_pubsub = _FakePubSub(
            [
                {"data": "{not-valid-json"},
                {"data": json.dumps(good_payload)},
            ]
        )

        from app.main import app

        with (
            mock.patch.object(settings, "API_AUTH_TOKEN", None),
            mock.patch.object(
                settings, "CORS_ALLOW_ORIGINS", ["http://localhost:5173"]
            ),
            mock.patch.object(
                redis_manager,
                "get_client",
                new=mock.AsyncMock(return_value=_FakeRedisClient()),
            ),
            mock.patch.object(
                redis_manager,
                "subscribe_to_task",
                new=mock.AsyncMock(return_value=fake_pubsub),
            ),
        ):
            with TestClient(app, base_url="http://localhost") as client:
                with client.websocket_connect(
                    "/task/forward-loop-task",
                    headers={
                        "origin": "http://localhost:5173",
                        "host": "localhost",
                    },
                ) as websocket:
                    first = websocket.receive_json()
                    second = websocket.receive_json()

        # 解析失败先收到 error 提示，随后正常消息仍被转发（循环未中断）
        self.assertEqual(first.get("type"), "error")
        self.assertEqual(second, good_payload)


if __name__ == "__main__":
    unittest.main()
