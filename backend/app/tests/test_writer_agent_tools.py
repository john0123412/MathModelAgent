"""WriterAgent tool-call compatibility tests."""

import json
import unittest
from unittest.mock import AsyncMock, patch

from app.config.setting import ApiType
from app.core.agents.writer_agent import MAX_TOOL_ROUNDS, WriterAgent
from app.core.llm.types import StandardResponse, ToolCall
from app.schemas.enums import CompTemplate, FormatOutPut


def _search_tool_call(call_id: str, query: str = "linear programming") -> ToolCall:
    """构造一个标准 search_papers 工具调用。"""
    return ToolCall(
        id=call_id,
        name="search_papers",
        arguments=json.dumps({"query": query, "limit": 3}),
    )


class FakePseudoToolModel:
    api_type = ApiType.OPENAI_CHAT

    def __init__(self):
        self.calls = 0

    async def chat(self, history, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return StandardResponse(
                content=(
                    "<tool_call>\n"
                    "<function=search_papers>\n"
                    "<parameter=query>linear programming production planning</parameter>\n"
                    "<parameter=limit>3</parameter>\n"
                    "<parameter=year_from>2010</parameter>\n"
                    "<parameter=year_to>2024</parameter>\n"
                    "<parameter=min_citations>10</parameter>\n"
                    "<parameter=source_types>[\"journal\"]</parameter>\n"
                    "<parameter=include_web>False</parameter>\n"
                    "</function>\n"
                    "</tool_call>"
                )
            )
        if not any("文献检索结果" in msg.get("content", "") for msg in history):
            raise AssertionError("pseudo tool result was not fed back to model")
        return StandardResponse(
            content="# 一、问题重述\n\n正文引用{[^1] Dantzig G B. Linear programming[J]. Operations Research, 1955.}"
        )


class FakeRepeatedPseudoToolModel:
    api_type = ApiType.OPENAI_CHAT

    def __init__(self):
        self.calls = 0

    async def chat(self, history, **kwargs):
        self.calls += 1
        if self.calls <= 2:
            return StandardResponse(
                content=(
                    "<tool_call>\n"
                    "<function=search_papers>\n"
                    "<parameter=query>linear programming</parameter>\n"
                    "<parameter=limit>3</parameter>\n"
                    "</function>\n"
                    "</tool_call>"
                )
            )
        if kwargs.get("tools"):
            raise AssertionError("final retry should disable tools")
        return StandardResponse(
            content="# 五、模型的建立与求解\n\n## 5.1 问题一模型的建立与求解\n\n正文。"
        )


class FakeScholar:
    async def search_papers(self, **kwargs):
        return [{"title": "Linear programming", "year": 1955}]

    def papers_to_str(self, papers):
        return "Dantzig G B. Linear programming[J]. Operations Research, 1955."


class FakeToolChainModel:
    """连续两轮真工具调用后输出正文的模型。"""

    api_type = ApiType.OPENAI_CHAT

    def __init__(self):
        self.calls = 0
        self.tools_history = []

    async def chat(self, history, **kwargs):
        self.calls += 1
        self.tools_history.append(kwargs.get("tools"))
        if self.calls <= 2:
            return StandardResponse(
                tool_calls=[_search_tool_call(f"call-{self.calls}")]
            )
        return StandardResponse(content="正文内容")


class FakeAlwaysToolCallModel:
    """只要提供了工具就永远返回真工具调用的模型。"""

    api_type = ApiType.OPENAI_CHAT

    def __init__(self):
        self.calls = 0
        self.tools_history = []

    async def chat(self, history, **kwargs):
        self.calls += 1
        self.tools_history.append(kwargs.get("tools"))
        if kwargs.get("tools"):
            return StandardResponse(
                tool_calls=[_search_tool_call(f"call-{self.calls}")]
            )
        return StandardResponse(content="强制收尾后的章节正文。")


class FakeUnknownToolModel:
    """第一轮返回未知工具调用、第二轮输出正文的模型。"""

    api_type = ApiType.OPENAI_CHAT

    def __init__(self):
        self.calls = 0

    async def chat(self, history, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return StandardResponse(
                tool_calls=[
                    ToolCall(id="call-unknown", name="delete_files", arguments="{}")
                ]
            )
        return StandardResponse(content="章节正文。")


class FakeReasoningAttributionModel:
    """两轮响应各带不同 reasoning_content，用于验证归属。"""

    api_type = ApiType.OPENAI_CHAT

    def __init__(self):
        self.calls = 0

    async def chat(self, history, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return StandardResponse(
                reasoning_content="R1",
                tool_calls=[_search_tool_call("call-r1")],
            )
        return StandardResponse(content="正文内容", reasoning_content="R2")


class FakeEmptyThenTextModel:
    """首轮输出空内容、重试后输出正文的模型。"""

    api_type = ApiType.OPENAI_CHAT

    def __init__(self):
        self.calls = 0
        self.tools_history = []

    async def chat(self, history, **kwargs):
        self.calls += 1
        self.tools_history.append(kwargs.get("tools"))
        if self.calls == 1:
            return StandardResponse(content="")
        return StandardResponse(content="重试后的章节正文。")


class FakeAlwaysEmptyModel:
    """永远输出空内容的模型，用于验证不无限重试。"""

    api_type = ApiType.OPENAI_CHAT

    def __init__(self):
        self.calls = 0

    async def chat(self, history, **kwargs):
        self.calls += 1
        return StandardResponse(content="")


def _paired_tool_ids(history: list[dict]) -> tuple[list[str], list[str]]:
    """收集历史中全部 tool_call id 与 tool 响应 id，用于配对断言。"""
    call_ids = [
        tc["id"] for msg in history for tc in (msg.get("tool_calls") or [])
    ]
    response_ids = [
        msg.get("tool_call_id") for msg in history if msg.get("role") == "tool"
    ]
    return call_ids, response_ids


class WriterAgentToolCompatibilityTest(unittest.IsolatedAsyncioTestCase):
    async def test_pseudo_xml_search_papers_call_is_resolved_before_returning_content(self):
        agent = WriterAgent(
            task_id="t1",
            model=FakePseudoToolModel(),
            comp_template=CompTemplate.CHINA,
            format_output=FormatOutPut.Markdown,
            scholar=FakeScholar(),
        )

        with patch("app.core.agents.writer_agent.redis_manager.publish_message", new=AsyncMock()):
            result = await agent.run("写问题重述", sub_title="RepeatQues")

        self.assertNotIn("<tool_call>", result.response_content)
        self.assertIn("# 一、问题重述", result.response_content)
        self.assertIn("{[^1]", result.response_content)

    async def test_repeated_pseudo_xml_search_call_gets_final_no_tool_retry(self):
        model = FakeRepeatedPseudoToolModel()
        agent = WriterAgent(
            task_id="t1",
            model=model,
            comp_template=CompTemplate.CHINA,
            format_output=FormatOutPut.Markdown,
            scholar=FakeScholar(),
        )

        with patch("app.core.agents.writer_agent.redis_manager.publish_message", new=AsyncMock()):
            result = await agent.run("写模型建立章节", sub_title="ques1")

        self.assertEqual(model.calls, 3)
        self.assertNotIn("<tool_call>", result.response_content)
        self.assertIn("# 五、模型的建立与求解", result.response_content)


class WriterAgentRealToolRoundsTest(unittest.IsolatedAsyncioTestCase):
    """真工具调用多轮往返与收尾防线测试。"""

    def _make_agent(self, model, scholar=FakeScholar()):
        return WriterAgent(
            task_id="t1",
            model=model,
            comp_template=CompTemplate.CHINA,
            format_output=FormatOutPut.Markdown,
            scholar=scholar,
        )

    async def test_consecutive_tool_calls_still_produce_content(self):
        """用例 A：连续两轮真工具调用后返回正文，内容不得为空。"""
        model = FakeToolChainModel()
        agent = self._make_agent(model)

        with patch(
            "app.core.agents.writer_agent.redis_manager.publish_message",
            new=AsyncMock(),
        ):
            result = await agent.run("写模型建立章节", sub_title="ques1")

        self.assertEqual(result.response_content, "正文内容")

        call_ids, response_ids = _paired_tool_ids(agent.chat_history)
        self.assertEqual(sorted(call_ids), sorted(response_ids))
        self.assertEqual(len(call_ids), 2)

    async def test_endless_tool_calls_get_forced_no_tool_finish(self):
        """用例 B：永远返回工具调用时，最终用 tools=[] 强制收尾且调用次数有界。"""
        model = FakeAlwaysToolCallModel()
        agent = self._make_agent(model)

        with patch(
            "app.core.agents.writer_agent.redis_manager.publish_message",
            new=AsyncMock(),
        ):
            result = await agent.run("写模型建立章节", sub_title="ques1")

        self.assertEqual(result.response_content, "强制收尾后的章节正文。")
        # 最后一次调用必须禁用工具
        self.assertEqual(model.tools_history[-1], [])
        # 总调用次数有界：MAX_TOOL_ROUNDS 轮工具往返 + 强制收尾（+ 空内容重试余量）
        self.assertLessEqual(model.calls, MAX_TOOL_ROUNDS + 2)

        call_ids, response_ids = _paired_tool_ids(agent.chat_history)
        self.assertEqual(sorted(call_ids), sorted(response_ids))

    async def test_unknown_tool_call_gets_placeholder_tool_response(self):
        """用例 C：未知工具调用必须有占位 tool 响应，避免孤儿 tool_call。"""
        model = FakeUnknownToolModel()
        agent = self._make_agent(model)

        with patch(
            "app.core.agents.writer_agent.redis_manager.publish_message",
            new=AsyncMock(),
        ):
            result = await agent.run("写模型建立章节", sub_title="ques1")

        self.assertEqual(result.response_content, "章节正文。")
        placeholder = [
            msg
            for msg in agent.chat_history
            if msg.get("role") == "tool" and msg.get("tool_call_id") == "call-unknown"
        ]
        self.assertEqual(len(placeholder), 1)
        self.assertIn("不受支持", placeholder[0]["content"])

    async def test_final_assistant_message_uses_own_reasoning_content(self):
        """用例 D：最终 assistant 历史消息的 reasoning_content 取产生正文那轮的值。"""
        model = FakeReasoningAttributionModel()
        agent = self._make_agent(model)

        with patch(
            "app.core.agents.writer_agent.redis_manager.publish_message",
            new=AsyncMock(),
        ):
            result = await agent.run("写模型建立章节", sub_title="ques1")

        self.assertEqual(result.response_content, "正文内容")
        final_msg = agent.chat_history[-1]
        self.assertEqual(final_msg["role"], "assistant")
        self.assertEqual(final_msg.get("reasoning_content"), "R2")

    async def test_empty_content_triggers_single_retry(self):
        """空内容防线：首轮空输出触发一次 tools=[] 重试。"""
        model = FakeEmptyThenTextModel()
        agent = self._make_agent(model, scholar=None)

        with patch(
            "app.core.agents.writer_agent.redis_manager.publish_message",
            new=AsyncMock(),
        ):
            result = await agent.run("写模型建立章节", sub_title="ques1")

        self.assertEqual(result.response_content, "重试后的章节正文。")
        self.assertEqual(model.calls, 2)
        self.assertEqual(model.tools_history[-1], [])

    async def test_persistent_empty_content_returns_without_infinite_retry(self):
        """空内容防线：重试后仍为空则原样返回，不无限重试。"""
        model = FakeAlwaysEmptyModel()
        agent = self._make_agent(model, scholar=None)

        with patch(
            "app.core.agents.writer_agent.redis_manager.publish_message",
            new=AsyncMock(),
        ):
            result = await agent.run("写模型建立章节", sub_title="ques1")

        self.assertEqual(result.response_content, "")
        self.assertEqual(model.calls, 2)


if __name__ == "__main__":
    unittest.main()
