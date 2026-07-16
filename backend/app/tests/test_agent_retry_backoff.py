"""CoderAgent 重试退避与 Agent 基类异常传播的回归测试。

覆盖三个熔断相关行为：

- LLM 持续故障（欠费/断网，内层 llm.py 已重试后抛出）时，CoderAgent 必须按
  恢复规程在连续两次外层异常后返回失败的 CoderToWriter，且首次失败后退避，
  不得继续打满通用代码错误重试额度；
- Agent 基类 run() 不得把异常吞成普通字符串返回（调用方会把错误文本当成
  正常响应造成静默失败），必须向上抛出；
- 配置默认值必须是有限熔断边界，不能回归为 None（无限制）。
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.config.setting import ApiType, Settings
from app.core.agents.agent import Agent
from app.core.agents.coder_agent import CoderAgent
from app.schemas.A2A import CoderToWriter


class FakeAlwaysFailModel:
    """chat() 永远抛异常的 LLM 桩，模拟欠费/断网等持续性故障。"""

    api_type = ApiType.ANTHROPIC

    def __init__(self):
        self.calls = 0

    async def chat(self, **_kwargs):
        self.calls += 1
        raise RuntimeError("simulated permanent LLM failure")


class FakeInterpreter:
    """无副作用的代码解释器桩，仅满足 CoderAgent 的构造依赖。"""

    def add_section(self, _title):
        pass

    async def get_created_images(self, _subtask_title):
        return []


class CoderAgentRetryBackoffTest(unittest.IsolatedAsyncioTestCase):
    """LLM 持续故障时 CoderAgent 必须有限次退避重试，不得紧循环。"""

    async def test_persistent_llm_failure_fails_finitely_with_backoff(self):
        model = FakeAlwaysFailModel()
        agent = CoderAgent(
            task_id="t1",
            model=model,
            work_dir=".",
            max_chat_turns=50,
            max_retries=3,
            code_interpreter=FakeInterpreter(),
        )

        # patch 目标是 coder_agent 模块命名空间中的 asyncio.sleep，
        # 断言外层兜底重试真的插入了退避等待。
        with patch(
            "app.core.agents.coder_agent.redis_manager.publish_message",
            new=AsyncMock(),
        ):
            with patch(
                "app.core.agents.coder_agent.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep:
                result = await agent.run("solve", "ques1")

        self.assertIsInstance(result, CoderToWriter)
        self.assertIn("连续 2 次 provider 或协议异常", result.code_response or "")
        self.assertFalse(result.execution_succeeded)
        self.assertTrue(result.execution_error_occurred)
        # provider/协议异常使用独立的两次上限，不打满通用 max_retries。
        self.assertEqual(model.calls, 2)
        # 首次失败后指数退避；第二次失败直接受控终止。
        delays = [call.args[0] for call in mock_sleep.await_args_list]
        self.assertEqual(delays, [2])

    async def test_backoff_is_skipped_and_cancelled_when_cancel_event_set(self):
        cancel_event = asyncio.Event()
        cancel_event.set()
        agent = CoderAgent(
            task_id="t1",
            model=FakeAlwaysFailModel(),
            work_dir=".",
            max_chat_turns=50,
            max_retries=3,
            code_interpreter=FakeInterpreter(),
            cancel_event=cancel_event,
        )

        # 直接 patch _chat 抛普通异常，绕过 _chat 内部的取消竞争，
        # 精准命中兜底 except：取消事件已置位时应立即向上取消，而非傻等退避。
        with patch.object(
            agent, "_chat", new=AsyncMock(side_effect=RuntimeError("boom"))
        ):
            with patch(
                "app.core.agents.coder_agent.redis_manager.publish_message",
                new=AsyncMock(),
            ):
                with patch(
                    "app.core.agents.coder_agent.asyncio.sleep",
                    new_callable=AsyncMock,
                ) as mock_sleep:
                    with self.assertRaises(asyncio.CancelledError):
                        await agent.run("solve", "ques1")

        mock_sleep.assert_not_awaited()


class AgentBaseRunPropagatesErrorTest(unittest.IsolatedAsyncioTestCase):
    """Agent 基类 run() 不得把异常吞成普通字符串返回。"""

    async def test_base_run_reraises_model_failure(self):
        class FailingModel:
            async def chat(self, **_kwargs):
                raise RuntimeError("provider down")

        agent = Agent(task_id="t1", model=FailingModel())

        with self.assertRaises(RuntimeError):
            await agent.run("prompt", "system prompt", "sub")


class SettingsCircuitBreakerDefaultsTest(unittest.TestCase):
    """熔断边界默认值必须有限，防止回归为 None（无限制）。"""

    def test_defaults_are_finite(self):
        # 断言类字段默认值而非 settings 实例，避免受本机 .env 文件覆盖影响
        self.assertEqual(Settings.model_fields["MAX_CHAT_TURNS"].default, 200)
        self.assertEqual(Settings.model_fields["MAX_RETRIES"].default, 20)


if __name__ == "__main__":
    unittest.main()
