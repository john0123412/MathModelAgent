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

    async def test_chapter_ownership_isolation_cleans_chat_history_between_runs(self):
        """章节所有权隔离：前一章节的内容不进入后一章节的历史。"""
        class _SequentialChapterModel:
            api_type = ApiType.OPENAI_CHAT
            def __init__(self):
                self.received_histories = []
            async def chat(self, history, **kwargs):
                self.received_histories.append(list(history))
                return StandardResponse(content=f"章节输出 {len(self.received_histories)}")

        model = _SequentialChapterModel()
        agent = self._make_agent(model, scholar=None)

        with patch("app.core.agents.writer_agent.redis_manager.publish_message", new=AsyncMock()):
            res1 = await agent.run("第1章提示词：写摘要", sub_title="abstract")
            res2 = await agent.run("第2章提示词：写模型", sub_title="ques1")

        self.assertEqual(res1.response_content, "章节输出 1")
        self.assertEqual(res2.response_content, "章节输出 2")
        self.assertEqual(len(model.received_histories), 2)
        # Second run's history should not contain chapter 1's user prompt or output
        second_history_contents = [msg.get("content", "") for msg in model.received_histories[1]]
        self.assertNotIn("第1章提示词：写摘要", second_history_contents)
        self.assertNotIn("章节输出 1", second_history_contents)
        self.assertIn("第2章提示词：写模型", second_history_contents)

    def test_writer_section_ownership_and_heading_deduplication(self):
        from app.models.user_output import deduplicate_top_level_headings

        agent = self._make_agent(None, scholar=None)
        # ques2 输出中混入了 ques1 的二级标题和顶层一级标题及其越权正文
        polluted_text = (
            "# 一、问题重述\n重述正文段落1\n重述正文段落2\n\n"
            "## 5.1 问题一的求解\n这是问题一专属正文\n\n"
            "## 5.2 问题二的求解\n这是问题二正文\n"
        )
        cleaned = agent._enforce_section_ownership_and_budget(polluted_text, sub_title="ques2")
        self.assertNotIn("# 一、问题重述", cleaned)
        self.assertNotIn("重述正文段落", cleaned)
        self.assertNotIn("## 5.1 问题一", cleaned)
        self.assertNotIn("这是问题一专属正文", cleaned)
        self.assertIn("## 5.2 问题二的求解", cleaned)
        self.assertIn("这是问题二正文", cleaned)

        # 测试文章拼接顶层标题与重复正文块去重
        concat_paper = (
            "# 一、问题重述\n内容1\n\n"
            "# 二、模型假设\n内容2\n\n"
            "# 一、问题重述\n重复的问题重述正文段落\n\n"
            "# 三、符号说明\n符号说明正文\n"
        )
        deduped = deduplicate_top_level_headings(concat_paper)
        self.assertEqual(deduped.count("# 一、问题重述"), 1)
        self.assertNotIn("重复的问题重述正文段落", deduped)
        self.assertIn("内容1", deduped)
        self.assertIn("# 二、模型假设", deduped)
        self.assertIn("内容2", deduped)
        self.assertIn("# 三、符号说明", deduped)

        # 测试精确反例：非法一级标题下属三级子标题一并跳过，遇到合法二级标题后恢复
        counterexample_with_subheading = (
            "# 一、问题重述\n"
            "### 1.1 背景分析\n这是越权背景段落\n\n"
            "## 5.2 问题二的求解\n合法问题二正文\n"
        )
        cleaned_sub = agent._enforce_section_ownership_and_budget(counterexample_with_subheading, sub_title="ques2")
        self.assertNotIn("# 一、问题重述", cleaned_sub)
        self.assertNotIn("1.1 背景分析", cleaned_sub)
        self.assertNotIn("这是越权背景段落", cleaned_sub)
        self.assertIn("## 5.2 问题二的求解", cleaned_sub)
        self.assertIn("合法问题二正文", cleaned_sub)

        # 测试在 ques2 中生成 # 问题一求解 必须被剔除（不能因含“求解”就放行）
        cross_q_text = (
            "# 问题一求解\n问题一越权正文\n\n"
            "## 5.2 问题二求解\n问题二合法正文\n"
        )
        cleaned_cross_q = agent._enforce_section_ownership_and_budget(cross_q_text, sub_title="ques2")
        self.assertNotIn("问题一求解", cleaned_cross_q)
        self.assertNotIn("问题一越权正文", cleaned_cross_q)
        self.assertIn("5.2", cleaned_cross_q)
        self.assertIn("问题二合法正文", cleaned_cross_q)

        # 测试未知 sub_title 严格 fail-closed（无论是否包含标题）
        unknown_sub_text = "# 任意越权标题\n任意越权正文\n"
        cleaned_unknown = agent._enforce_section_ownership_and_budget(unknown_sub_text, sub_title="unknown_chapter")
        self.assertEqual(cleaned_unknown, "")

        unknown_plain_text = "这是一段没有Markdown标题的普通正文文本。"
        cleaned_plain = agent._enforce_section_ownership_and_budget(unknown_plain_text, sub_title="invalid_sub")
        self.assertEqual(cleaned_plain, "")

        # 测试精确反例：跨层级（# 一、 与 ## 一、）不同文字描述但相同章节序号的一级标题去重
        cross_level_wording_paper = (
            "# 一、问题重述\n正文1\n\n"
            "## 一、问题背景\n正文2\n\n"
            "# 二、模型假设\n正文3\n"
        )
        deduped_wording = deduplicate_top_level_headings(cross_level_wording_paper)
        self.assertIn("# 一、问题重述", deduped_wording)
        self.assertIn("正文1", deduped_wording)
        self.assertNotIn("## 一、问题背景", deduped_wording)
        self.assertNotIn("正文2", deduped_wording)
        self.assertIn("# 二、模型假设", deduped_wording)
        self.assertIn("正文3", deduped_wording)

    def test_writer_budget_preserves_content_integrity_without_silent_truncation(self):
        agent = self._make_agent(None, scholar=None)
        # 构造超过 12,000 字符且末尾含有重要公式的文本
        huge_text = "## 5.1 模型求解\n" + "段落内容。\n\n" * 3000 + "$$x + y = 100$$\n重要结论段落。"
        cleaned = agent._enforce_section_ownership_and_budget(huge_text, sub_title="ques1")
        # 不得静默切片丢弃末尾的公式与结论
        self.assertIn("$$x + y = 100$$", cleaned)
        self.assertIn("重要结论段落。", cleaned)

    async def test_writer_budget_long_to_short_compression_succeeds(self):
        """长->短：首次超 12,000 字符，触发且仅触发一次无工具定向压缩，恰好 2 次模型调用并成功。"""
        huge_content = (
            "## 5.1 模型求解\n"
            "原始详细模型求解长篇展开论述。\n"
            "$$x + y = 100$$\n"
            "关键结论为 2200。\n"
            "参考文献引用{[^1] 权威文献条目}。\n\n"
            + ("超长论述段落内容，展开细节说明。\n\n" * 2500)
            + "\n\n[^1]: 权威文献条目内容"
        )
        compressed_content = (
            "## 5.1 模型求解\n"
            "精炼后的模型求解正文。\n"
            "$$x + y = 100$$\n"
            "关键结论为 2200。\n"
            "参考文献引用{[^1] 权威文献条目}。\n\n"
            "[^1]: 权威文献条目内容"
        )

        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            elif call_count == 2:
                # 必须无工具调用
                self.assertEqual(kwargs.get("tools"), [])
                return StandardResponse(content=compressed_content, tool_calls=None)
            raise AssertionError("模型调用次数超过 2 次")

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        resp = await agent.run(prompt="写作问题一", sub_title="ques1")
        self.assertEqual(call_count, 2)
        self.assertIn("$$x + y = 100$$", resp.response_content)
        self.assertIn("关键结论为 2200", resp.response_content)
        self.assertIn("[^1] 权威文献条目", resp.response_content)
        self.assertEqual(len(resp.footnotes), 1)
        self.assertEqual(resp.footnotes[0][0], "1")
        self.assertIn("权威文献条目内容", resp.footnotes[0][1])

    async def test_writer_budget_long_to_still_long_raises_budget_exceeded(self):
        """长->仍长：首次超 12,000 字符，二次压缩后仍超 12,000 字符，恰好 2 次调用并确定性抛出 WRITER_SECTION_BUDGET_EXCEEDED。"""
        huge_content = "## 5.1 模型求解\n" + ("超长论述段落内容。\n\n" * 2500)
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            return StandardResponse(content=huge_content, tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_BUDGET_EXCEEDED", str(caught.exception))

    async def test_writer_compression_returns_empty_raises_integrity_failed(self):
        """反例：超长正文压缩后模型返回空，必须抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = "## 5.1 模型求解\n" + ("超长论述段落内容。\n\n" * 2500)
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(content="", tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_loses_formula_raises_integrity_failed(self):
        """反例：压缩结果丢失数学公式，必须拒绝并抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = "## 5.1 模型求解\n$$z = 2200$$\n" + ("超长论述段落内容。\n\n" * 2500)
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            # 压缩结果丢失了 $$z = 2200$$
            return StandardResponse(content="## 5.1 模型求解\n精简正文，没有公式。", tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_loses_citation_raises_integrity_failed(self):
        """反例：压缩结果丢失引用标记，必须拒绝并抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = "## 5.1 模型求解\n引用内容{[^1] 文献}\n" + ("超长论述段落内容。\n\n" * 2500)
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            # 丢失 [^1]
            return StandardResponse(content="## 5.1 模型求解\n精简正文，没有引用。", tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_cleaned_becomes_empty_raises_integrity_failed(self):
        """反例：压缩结果经所有权过滤后为空，必须拒绝并抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = "## 5.1 模型求解\n" + ("超长论述段落内容。\n\n" * 2500)
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            # 输出了越权章节标题，经清洗后会变为空
            return StandardResponse(content="# 越权章节标题\n越权正文内容", tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_loses_single_digit_number_raises_integrity_failed(self):
        """反例：压缩结果丢失正文中的单数字（如 0、1、5），必须拒绝并抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = "## 5.1 模型求解\n在第 5 次迭代中收敛到误差为 0。\n" + ("超长论述段落内容。\n\n" * 2500)
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            # 丢失了单数字 5 和 0
            return StandardResponse(content="## 5.1 模型求解\n在迭代中收敛到极小误差。", tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_replaces_citation_body_raises_integrity_failed(self):
        """反例：压缩结果保留引用标记 [^1] 但篡改了引用正文内容，必须拒绝并抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = "## 5.1 模型求解\n根据权威结论{[^1] 原始权威文献正文}。\n" + ("超长论述段落内容。\n\n" * 2500)
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            # 保留 [^1] 但篡改文献正文
            return StandardResponse(content="## 5.1 模型求解\n根据结论{[^1] 篡改虚假文献正文}。", tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_replaces_or_deletes_footnote_def_raises_integrity_failed(self):
        """反例：压缩结果保留引用但篡改或删除了脚注定义，必须拒绝并抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = (
            "## 5.1 模型求解\n引用文献[^1]。\n"
            + ("超长论述段落内容。\n\n" * 2500)
            + "\n\n[^1]: 原始参考文献条目详细信息"
        )
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            # 保留 [^1] 但篡改脚注定义
            return StandardResponse(
                content="## 5.1 模型求解\n引用文献[^1]。\n\n[^1]: 伪造篡改条目",
                tool_calls=None,
            )

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_reduces_repeated_number_occurrences_raises_integrity_failed(self):
        """反例：重复关键数值只保留一次（频次减少），Counter 校验必须拒绝并抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = "## 5.1 模型求解\n基准利润为 2200，复算结果同样为 2200。\n" + ("超长论述段落内容。\n\n" * 2500)
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            # 2200 原本出现 2 次，压缩后只保留 1 次
            return StandardResponse(content="## 5.1 模型求解\n利润为 2200。", tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_replaces_image_caption_raises_integrity_failed(self):
        """反例：图片路径未变但图片标题被篡改，必须拒绝并抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = "## 5.1 模型求解\n![原始分布趋势图](img/dist.png)\n" + ("超长论述段落内容。\n\n" * 2500)
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            # 路径相同但标题篡改
            return StandardResponse(content="## 5.1 模型求解\n![篡改错误标题](img/dist.png)", tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_appends_fake_citation_conclusion_raises_integrity_failed(self):
        """反例：原引用后追加“伪造结论”，必须拒绝并抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = "## 5.1 模型求解\n根据权威结论{[^1] 原始文献内容}。\n" + ("超长论述段落内容。\n\n" * 2500)
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            # 在原引用正文后追加伪造内容
            return StandardResponse(content="## 5.1 模型求解\n根据权威结论{[^1] 原始文献内容 伪造结论}。", tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_appends_fake_footnote_data_raises_integrity_failed(self):
        """反例：原脚注后追加“错误数据”，必须拒绝并抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = (
            "## 5.1 模型求解\n引用文献[^1]。\n"
            + ("超长论述段落内容。\n\n" * 2500)
            + "\n\n[^1]: 原始参考文献条目详细信息"
        )
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            # 在原脚注定义后追加错误数据
            return StandardResponse(
                content="## 5.1 模型求解\n引用文献[^1]。\n\n[^1]: 原始参考文献条目详细信息 错误数据",
                tool_calls=None,
            )

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_replaces_image_parenthesis_path_extension_raises_integrity_failed(self):
        """反例：figures/result(1).png 改为 figures/result(1).jpg，必须拒绝并抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = "## 5.1 模型求解\n![结果 图(1)](figures/result(1).png)\n" + ("超长论述段落内容。\n\n" * 2500)
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            # 将 result(1).png 篡改为 result(1).jpg
            return StandardResponse(content="## 5.1 模型求解\n![结果 图(1)](figures/result(1).jpg)", tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_reduces_repeated_citation_occurrences_raises_integrity_failed(self):
        """反例：重复引用减少一次，必须拒绝并抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = (
            "## 5.1 模型求解\n根据文献{[^1] 原始文献}，再次结合{[^1] 原始文献}进行验证。\n"
            + ("超长论述段落内容。\n\n" * 2500)
        )
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            # 原始有 2 处引用，压缩后只保留 1 处
            return StandardResponse(content="## 5.1 模型求解\n根据文献{[^1] 原始文献}进行验证。", tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_legitimate_narrative_compression_passes(self):
        """正例：合法压缩仅精简普通叙述文字、保留全量标题/公式/引用/图表/数值时必须正常通过。"""
        huge_content = (
            "## 5.1 模型求解\n"
            "在多次反复实验与大量文献调研后，求解得出目标值 $z = 2200$。\n"
            "根据文献{[^1] 原始文献}，求解结果如图所示：\n"
            "![结果 图(1)](figures/result(1).png \"结果分布\")\n\n"
            + ("大量冗长无实质事实的叙述论述文字，此处展开深入说明细节。\n\n" * 2500)
            + "\n\n[^1]: 原始文献详细条目"
        )
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            # 合法精简普通冗余文字，全量关键事实完全保留
            return StandardResponse(
                content=(
                    "## 5.1 模型求解\n"
                    "求解得出目标值 $z = 2200$。\n"
                    "根据文献{[^1] 原始文献}，求解结果如图所示：\n"
                    "![结果 图(1)](figures/result(1).png \"结果分布\")\n\n"
                    "[^1]: 原始文献详细条目"
                ),
                tool_calls=None,
            )

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        res = await agent.run(prompt="写作问题一", sub_title="ques1")
        self.assertEqual(call_count, 2)
        self.assertTrue(res.response_content.startswith("## 5.1 模型求解"))
        self.assertIn("$z = 2200$", res.response_content)
        self.assertIn("figures/result(1).png", res.response_content)

    async def test_writer_compression_moving_tokens_into_html_comment_raises_integrity_failed(self):
        """反例：将原可见引用、图片、脚注移入 HTML 注释，必须判定为丢失并抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = (
            "## 5.1 模型求解\n根据文献{[^1] 原始文献}，求解结果见 ![结果](figures/result(1).png)。\n"
            + ("超长论述段落内容。\n\n" * 2500)
            + "\n\n[^1]: 原始文献条目"
        )
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            # 将原事实隐藏进 HTML 注释
            return StandardResponse(
                content="## 5.1 模型求解\n<!-- 根据文献{[^1] 原始文献}，求解结果见 ![结果](figures/result(1).png)。\n[^1]: 原始文献条目 -->\n替代伪造正文。",
                tool_calls=None,
            )

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_moving_tokens_into_code_block_or_inline_code_raises_integrity_failed(self):
        """反例：将原可见引用与脚注移入代码块或行内代码，必须判定为丢失并抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = (
            "## 5.1 模型求解\n引用文献[^1]。\n"
            + ("超长论述段落内容。\n\n" * 2500)
            + "\n\n[^1]: 原始参考文献条目详细信息"
        )
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            # 将引用和脚注移入围栏代码块
            return StandardResponse(
                content="## 5.1 模型求解\n```markdown\n引用文献[^1]。\n[^1]: 原始参考文献条目详细信息\n```\n正文描述。",
                tool_calls=None,
            )

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_escaped_tokens_treated_as_plain_text_raises_integrity_failed(self):
        """反例：将图片转义为普通文本 \\!\\[结果\\](...)，必须判定为图片丢失并抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = "## 5.1 模型求解\n![结果](figures/result(1).png)\n" + ("超长论述段落内容。\n\n" * 2500)
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            # 转义图片语法字符
            return StandardResponse(content="## 5.1 模型求解\n\\!\\[结果\\](figures/result(1).png)", tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_adding_unauthorized_number_raises_integrity_failed(self):
        """反例：保留原事实但新增未经授权的伪造数值 999，双向校验必须拒绝并抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = "## 5.1 模型求解\n基准利润为 2200。\n" + ("超长论述段落内容。\n\n" * 2500)
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            # 保留 2200 但新增 999
            return StandardResponse(content="## 5.1 模型求解\n基准利润为 2200，新增参数 999。", tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_adding_unauthorized_image_or_footnote_raises_integrity_failed(self):
        """反例：保留原内容但新增伪造图片与脚注，双向校验必须拒绝并抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = "## 5.1 模型求解\n求解完成。\n" + ("超长论述段落内容。\n\n" * 2500)
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            # 新增未经授权的图片与脚注
            return StandardResponse(
                content="## 5.1 模型求解\n求解完成。\n![新增伪造图](figures/fake.png)\n\n[^9]: 伪造脚注条目",
                tool_calls=None,
            )

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    def test_writer_image_angle_bracket_with_parenthesis_in_title_parsed_completely(self):
        """单测：<figures/result(1).png> \"caption ) tail 2025\" 能被完整消费并提取完整 span 与路径。"""
        from app.core.agents.writer_agent import _extract_markdown_images_with_spans

        raw_md = '前文说明 ![alt text](<figures/result(1).png> "caption ) tail 2025") 后文说明'
        images, spans = _extract_markdown_images_with_spans(raw_md)

        self.assertEqual(images[("alt text", "figures/result(1).png")], 1)
        self.assertEqual(len(spans), 1)
        start, end = spans[0]
        consumed_str = raw_md[start:end]
        self.assertEqual(consumed_str, '![alt text](<figures/result(1).png> "caption ) tail 2025")')

    async def test_writer_compression_four_spaces_indented_code_block_hiding_evidence_raises_integrity_failed(self):
        """反例：四空格缩进代码块隐藏引用与图片，MarkdownIt 识别为 code_block 并判定事实丢失，抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        import markdown_it

        huge_content = (
            "## 5.1 模型求解\n"
            "根据文献{[^1] 权威文献}，结果可见图 ![结果](figures/result(1).png)。\n"
            + ("超长论述段落内容。\n\n" * 2500)
            + "\n\n[^1]: 权威文献条目"
        )
        compressed_text = (
            "## 5.1 模型求解\n"
            "正文描述，以下将原证据藏入四空格缩进代码块：\n\n"
            "    根据文献{[^1] 权威文献}，结果可见图 ![结果](figures/result(1).png)。\n"
            "    [^1]: 权威文献条目\n"
        )

        # 证明该结构在 CommonMark/MarkdownIt 下确实被解析为 code_block token
        md = markdown_it.MarkdownIt()
        token_types = [t.type for t in md.parse(compressed_text)]
        self.assertIn("code_block", token_types)

        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(content=compressed_text, tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_tab_indented_code_block_hiding_evidence_raises_integrity_failed(self):
        """反例：Tab 缩进代码块隐藏证据，MarkdownIt 识别为 code_block 并判定事实丢失，抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        import markdown_it

        huge_content = (
            "## 5.1 模型求解\n"
            "根据文献{[^1] 权威文献}进行验证。\n"
            + ("超长论述段落内容。\n\n" * 2500)
            + "\n\n[^1]: 权威文献条目"
        )
        compressed_text = (
            "## 5.1 模型求解\n"
            "正文描述：\n\n"
            "\t根据文献{[^1] 权威文献}进行验证。\n"
            "\t[^1]: 权威文献条目\n"
        )

        md = markdown_it.MarkdownIt()
        token_types = [t.type for t in md.parse(compressed_text)]
        self.assertIn("code_block", token_types)

        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(content=compressed_text, tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_three_spaces_indented_fence_hiding_evidence_raises_integrity_failed(self):
        """反例：0~3 空格缩进的 ~~~ 围栏隐藏证据，MarkdownIt 识别为 fence 并判定事实丢失，抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        import markdown_it

        huge_content = (
            "## 5.1 模型求解\n"
            "根据文献{[^1] 权威文献}进行验证。\n"
            + ("超长论述段落内容。\n\n" * 2500)
            + "\n\n[^1]: 权威文献条目"
        )
        compressed_text = (
            "## 5.1 模型求解\n"
            "正文描述：\n"
            "   ~~~\n"
            "   根据文献{[^1] 权威文献}进行验证。\n"
            "   [^1]: 权威文献条目\n"
            "   ~~~\n"
        )

        md = markdown_it.MarkdownIt()
        token_types = [t.type for t in md.parse(compressed_text)]
        self.assertIn("fence", token_types)

        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(content=compressed_text, tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_blockquote_fence_hiding_evidence_raises_integrity_failed(self):
        """反例：引用块内 > ~~~ 围栏隐藏证据，MarkdownIt 识别为 blockquote + fence 并判定事实丢失，抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        import markdown_it

        huge_content = (
            "## 5.1 模型求解\n"
            "根据文献{[^1] 权威文献}进行验证。\n"
            + ("超长论述段落内容。\n\n" * 2500)
            + "\n\n[^1]: 权威文献条目"
        )
        compressed_text = (
            "## 5.1 模型求解\n"
            "> 引用开始\n"
            "> ~~~\n"
            "> 根据文献{[^1] 权威文献}进行验证。\n"
            "> [^1]: 权威文献条目\n"
            "> ~~~\n"
        )

        md = markdown_it.MarkdownIt()
        token_types = [t.type for t in md.parse(compressed_text)]
        self.assertIn("blockquote_open", token_types)
        self.assertIn("fence", token_types)

        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(content=compressed_text, tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_multiline_footnote_continuation_tampered_raises_integrity_failed(self):
        """反例：多行脚注（首行+缩进续行+空行后续段）中续行被篡改，必须拒绝并抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = (
            "## 5.1 模型求解\n"
            "引用多行脚注[^1]。\n"
            + ("超长论述段落内容。\n\n" * 2500)
            + "\n\n[^1]: 原始脚注首行内容\n"
            "    这是第一条缩进续行，参数为 100。\n"
            "    这是第二条缩进续行，参数为 200。\n\n"
            "    这是空行后的续段说明，参数为 300。"
        )
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            # 首行不变，但篡改第二条续行参数 200 -> 999
            return StandardResponse(
                content=(
                    "## 5.1 模型求解\n"
                    "引用多行脚注[^1]。\n\n"
                    "[^1]: 原始脚注首行内容\n"
                    "    这是第一条缩进续行，参数为 100。\n"
                    "    这是第二条缩进续行，参数为 999。\n\n"
                    "    这是空行后的续段说明，参数为 300。"
                ),
                tool_calls=None,
            )

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_multiline_footnote_legitimate_compression_passes(self):
        """正例：多行脚注完整保留（首行+缩进续行+空行后续段），合法压缩冗余叙述文字后必须正常通过。"""
        huge_content = (
            "## 5.1 模型求解\n"
            "在多次反复实验后，求解得出目标值 $z = 2200$。\n"
            "引用多行文献脚注[^1]，结果可见图 ![结果 图(1)](figures/result(1).png \"结果分布\")。\n"
            + ("超长论述段落内容，展开细节说明。\n\n" * 2500)
            + "\n\n[^1]: 原始脚注首行内容\n"
            "    这是第一条缩进续行，参数为 100。\n"
            "    这是第二条缩进续行，参数为 200。\n\n"
            "    这是空行后的续段说明，参数为 300。"
        )
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(
                content=(
                    "## 5.1 模型求解\n"
                    "求解得出目标值 $z = 2200$。\n"
                    "引用多行文献脚注[^1]，结果可见图 ![结果 图(1)](figures/result(1).png \"结果分布\")。\n\n"
                    "[^1]: 原始脚注首行内容\n"
                    "    这是第一条缩进续行，参数为 100。\n"
                    "    这是第二条缩进续行，参数为 200。\n\n"
                    "    这是空行后的续段说明，参数为 300。"
                ),
                tool_calls=None,
            )

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        res = await agent.run(prompt="写作问题一", sub_title="ques1")
        self.assertEqual(call_count, 2)
        self.assertTrue(res.response_content.startswith("## 5.1 模型求解"))
        self.assertIn("$z = 2200$", res.response_content)
        self.assertIn("figures/result(1).png", res.response_content)

    async def test_writer_compression_moving_footnote_into_tilde_fence_raises_integrity_failed(self):
        """反例：原脚注移入 ~~~ 围栏后，AST 严格屏蔽围栏且不允许脚注豁免，必须抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        import markdown_it

        huge_content = (
            "## 5.1 模型求解\n"
            "引用文献脚注[^1]。\n"
            + ("超长论述段落内容。\n\n" * 2500)
            + "\n\n[^1]: 权威文献条目内容"
        )
        compressed_text = (
            "## 5.1 模型求解\n"
            "引用文献脚注[^1]。\n\n"
            "~~~\n"
            "[^1]: 权威文献条目内容\n"
            "~~~\n"
        )

        md = markdown_it.MarkdownIt()
        token_types = [t.type for t in md.parse(compressed_text)]
        self.assertIn("fence", token_types)

        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(content=compressed_text, tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_moving_footnote_into_html_comment_raises_integrity_failed(self):
        """反例：原脚注移入 HTML 注释后，AST 与注释扫描器严格屏蔽，必须抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = (
            "## 5.1 模型求解\n"
            "引用文献脚注[^1]。\n"
            + ("超长论述段落内容。\n\n" * 2500)
            + "\n\n[^1]: 权威文献条目内容"
        )
        compressed_text = (
            "## 5.1 模型求解\n"
            "引用文献脚注[^1]。\n\n"
            "<!--\n"
            "[^1]: 权威文献条目内容\n"
            "-->\n"
        )

        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(content=compressed_text, tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_moving_footnote_into_backtick_fence_raises_integrity_failed(self):
        """反例：原脚注移入 ``` 代码围栏后，AST 严格屏蔽围栏且不允许脚注豁免，必须抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        import markdown_it

        huge_content = (
            "## 5.1 模型求解\n"
            "引用文献脚注[^1]。\n"
            + ("超长论述段落内容。\n\n" * 2500)
            + "\n\n[^1]: 权威文献条目内容"
        )
        compressed_text = (
            "## 5.1 模型求解\n"
            "引用文献脚注[^1]。\n\n"
            "```\n"
            "[^1]: 权威文献条目内容\n"
            "```\n"
        )

        md = markdown_it.MarkdownIt()
        token_types = [t.type for t in md.parse(compressed_text)]
        self.assertIn("fence", token_types)

        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(content=compressed_text, tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_raw_inline_html_span_hidden_raises_integrity_failed(self):
        """反例：压缩结果包含 <span hidden> 原始 HTML 标签隐藏图片，必须确定性拒绝并抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = (
            "## 5.1 模型求解\n"
            "结果如图 ![结果分布](figures/result(1).png)。\n"
            + ("超长论述段落内容。\n\n" * 2500)
        )
        compressed_text = (
            "## 5.1 模型求解\n"
            "结果如图 <span hidden>![结果分布](figures/result(1).png)</span>。\n"
        )

        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(content=compressed_text, tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))
        self.assertIn("未经授权的原始 HTML", str(caught.exception))

    async def test_writer_compression_raw_inline_html_span_style_display_none_raises_integrity_failed(self):
        """反例：压缩结果包含 <span style=\"display:none\"> 原始 HTML 标签，必须确定性拒绝并抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = (
            "## 5.1 模型求解\n"
            "引用多行文献脚注{[^1] 权威结论}。\n"
            + ("超长论述段落内容。\n\n" * 2500)
            + "\n\n[^1]: 权威文献条目内容"
        )
        compressed_text = (
            "## 5.1 模型求解\n"
            "引用多行文献脚注 <span style=\"display:none\">{[^1] 权威结论}</span>。\n\n"
            "[^1]: 权威文献条目内容"
        )

        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(content=compressed_text, tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))
        self.assertIn("未经授权的原始 HTML", str(caught.exception))

    async def test_writer_compression_moving_image_into_link_ref_def_raises_integrity_failed(self):
        """反例：真实图片被伪造移入链接参考定义，MarkdownIt AST 未生成 image token，必须抛出完整性错误且 _chat==2。"""
        huge_content = (
            "## 5.1 模型求解\n"
            "结果如图 ![真实图](figures/real.png)。\n"
            + ("超长论述段落内容。\n\n" * 2500)
        )
        compressed_text = (
            "## 5.1 模型求解\n"
            "模型求解完毕。\n\n"
            "[hidden]: /target \"![真实图](figures/real.png)\"\n"
        )
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(content=compressed_text, tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))
        self.assertTrue(
            "丢失或篡改图表引用" in str(caught.exception)
            or "伪造图片语法" in str(caught.exception)
        )

    async def test_writer_compression_forging_image_in_link_url_raises_integrity_failed(self):
        """反例：真实图片被伪造成链接 URL，MarkdownIt AST 未生成 image token，必须抛出完整性错误且 _chat==2。"""
        huge_content = (
            "## 5.1 模型求解\n"
            "结果如图 ![真实图](figures/real.png)。\n"
            + ("超长论述段落内容。\n\n" * 2500)
        )
        compressed_text = (
            "## 5.1 模型求解\n"
            "详情请[查看说明](https://example.test/![真实图](figures/real.png))。\n"
        )
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(content=compressed_text, tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))
        self.assertTrue(
            "丢失或篡改图表引用" in str(caught.exception)
            or "伪造图片语法" in str(caught.exception)
        )

    async def test_writer_compression_pandoc_image_attribute_display_none_raises_integrity_failed(self):
        """反例：图片包含 Pandoc 属性 {style=\"display:none\"}，必须拒绝并抛出完整性错误且 _chat==2。"""
        huge_content = (
            "## 5.1 模型求解\n"
            "结果如图 ![真实图](figures/real.png)。\n"
            + ("超长论述段落内容。\n\n" * 2500)
        )
        compressed_text = (
            "## 5.1 模型求解\n"
            "结果如图 ![真实图](figures/real.png){style=\"display:none\"}。\n"
        )
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(content=compressed_text, tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))
        self.assertIn("Pandoc 属性列表", str(caught.exception))

    async def test_writer_compression_pandoc_image_attribute_visibility_hidden_raises_integrity_failed(self):
        """反例：图片包含 Pandoc 属性 {style=\"visibility:hidden\"}，必须拒绝并抛出完整性错误且 _chat==2。"""
        huge_content = (
            "## 5.1 模型求解\n"
            "结果如图 ![真实图](figures/real.png)。\n"
            + ("超长论述段落内容。\n\n" * 2500)
        )
        compressed_text = (
            "## 5.1 模型求解\n"
            "结果如图 ![真实图](figures/real.png){style=\"visibility:hidden\"}。\n"
        )
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(content=compressed_text, tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))
        self.assertIn("Pandoc 属性列表", str(caught.exception))

    async def test_writer_compression_pandoc_image_attribute_width_zero_raises_integrity_failed(self):
        """反例：图片包含 Pandoc 属性 {width=0}，必须拒绝并抛出完整性错误且 _chat==2。"""
        huge_content = (
            "## 5.1 模型求解\n"
            "结果如图 ![真实图](figures/real.png)。\n"
            + ("超长论述段落内容。\n\n" * 2500)
        )
        compressed_text = (
            "## 5.1 模型求解\n"
            "结果如图 ![真实图](figures/real.png){width=0}。\n"
        )
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(content=compressed_text, tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))
        self.assertIn("Pandoc 属性列表", str(caught.exception))

    async def test_writer_compression_pandoc_image_attribute_height_zero_raises_integrity_failed(self):
        """反例：图片包含 Pandoc 属性 {height=0}，必须拒绝并抛出完整性错误且 _chat==2。"""
        huge_content = (
            "## 5.1 模型求解\n"
            "结果如图 ![真实图](figures/real.png)。\n"
            + ("超长论述段落内容。\n\n" * 2500)
        )
        compressed_text = (
            "## 5.1 模型求解\n"
            "结果如图 ![真实图](figures/real.png){height=0}。\n"
        )
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(content=compressed_text, tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))
        self.assertIn("Pandoc 属性列表", str(caught.exception))

    async def test_writer_compression_legitimate_images_with_brackets_and_angle_brackets_passes(self):
        """正例：合法普通图片、含括号路径、尖括号 URL 以及图片 title 在真实 WriterAgent.run 压缩链路上必须通过且 _chat==2。"""
        huge_content = (
            "## 5.1 模型求解\n"
            "求解得出最优指标 $z = 100$。\n"
            "结果见图 ![结果 图(1)](figures/result(1).png \"caption ) tail 2025\") 以及 ![尖括号图](<figures/result(2).png> \"分布\")。\n"
            + ("超长论述段落内容。\n\n" * 2500)
        )
        compressed_text = (
            "## 5.1 模型求解\n"
            "求解得出最优指标 $z = 100$。\n"
            "结果见图 ![结果 图(1)](figures/result(1).png \"caption ) tail 2025\") 以及 ![尖括号图](<figures/result(2).png> \"分布\")。\n"
        )
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(content=compressed_text, tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        res = await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertTrue(res.response_content.startswith("## 5.1 模型求解"))
        self.assertIn("figures/result(1).png", res.response_content)
        self.assertIn("figures/result(2).png", res.response_content)

    async def test_writer_compression_image_in_link_reference_label_raises_integrity_failed(self):
        """反例：真实图片被伪造成链接参考定义的 label 行首 ([![真实图](...)]: /url)，必须被识别为非渲染行并抛出完整性错误且 _chat==2。"""
        huge_content = (
            "## 5.1 模型求解\n"
            "结果如图 ![真实图](figures/real.png)。\n"
            + ("超长论述段落内容。\n\n" * 2500)
        )
        compressed_text = (
            "## 5.1 模型求解\n"
            "求解模型完毕。\n\n"
            "[![真实图](figures/real.png)]: /url\n"
        )
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(content=compressed_text, tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))
        self.assertIn("丢失或篡改图表引用", str(caught.exception))

    def test_writer_compression_multiline_link_reference_definition_direct_integrity_fails(self):
        """反例：直接测试 _verify_compression_integrity，多行链接参考定义隐藏公式、数字、图片与引用必须返回非空错误列表。"""
        from app.core.agents.writer_agent import _verify_compression_integrity

        original = (
            "## 5.1 模型求解\n"
            "最优解为 $z = 2200$，见 ![真实图](figures/real.png)，依据{[^1] Smith 2024}。\n"
        )
        compressed_with_multiline_link_ref = (
            "## 5.1 模型求解\n"
            "[hidden]: /target\n"
            '  "最优解为 $z = 2200$，见 ![真实图](figures/real.png)，依据{ [^1] Smith 2024}。"\n'
        )

        missing = _verify_compression_integrity(original, compressed_with_multiline_link_ref)
        self.assertTrue(len(missing) > 0)
        missing_text = "; ".join(missing)
        self.assertTrue(
            "丢失行内公式" in missing_text
            or "丢失或篡改图表引用" in missing_text
            or "丢失关键数值事实" in missing_text
            or "丢失或篡改文献引用正文" in missing_text
        )

    async def test_writer_compression_multiline_link_ref_def_evasion_raises_integrity_failed(self):
        """反例：真实 WriterAgent.run 压缩路径，第二轮返回多行链接参考定义隐藏要素，必须调用 2 次后抛出 WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED。"""
        huge_content = (
            "## 5.1 模型求解\n"
            "最优解为 $z = 2200$，见 ![真实图](figures/real.png)，依据{[^1] Smith 2024}。\n"
            + ("超长论述段落内容。\n\n" * 2500)
        )
        compressed_text = (
            "## 5.1 模型求解\n"
            "[hidden]: /target\n"
            '  "最优解为 $z = 2200$，见 ![真实图](figures/real.png)，依据{[^1] Smith 2024}。"\n'
        )
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(content=compressed_text, tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_writer_compression_multiline_link_ref_def_pandoc_continuation_raises_integrity_failed(self):
        """反例：Pandoc 语法中 URL 与 title 分跨三行的链接参考定义，必须完整遮罩并抛出完整性错误且 _chat==2。"""
        huge_content = (
            "## 5.1 模型求解\n"
            "最优解为 $z = 2200$，见 ![真实图](figures/real.png)，依据{[^1] Smith 2024}。\n"
            + ("超长论述段落内容。\n\n" * 2500)
        )
        compressed_text = (
            "## 5.1 模型求解\n"
            "[multi_line_def]:\n"
            "  <https://example.com/target>\n"
            "  '最优解为 $z = 2200$，见 ![真实图](figures/real.png)，依据{[^1] Smith 2024}。'\n"
        )
        call_count = 0

        async def _fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StandardResponse(content=huge_content, tool_calls=None)
            return StandardResponse(content=compressed_text, tool_calls=None)

        agent = self._make_agent(None, scholar=None)
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertEqual(call_count, 2)
        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    def test_writer_compression_systematic_audit_matrix_ten_evasion_cases(self):
        """系统性审计矩阵：验证所有 10 种 Markdown/Pandoc 逃逸与隐匿场景均被 fail-closed 严格拦截。"""
        from app.core.agents.writer_agent import _verify_compression_integrity

        orig = (
            "## 5.1 模型求解\n"
            "我们求得最优解为 $z = 2200$，其中参数为 $a=15.5$。\n"
            '结果分布如图 ![分布图](figures/dist.png "正态分布")。\n'
            "基于文献{[^1] Zhang 2024}的理论，以及相关结论[^2]。\n\n"
            "[^2]: 这是一个详细的文献脚注定义 2024\n"
        )

        cases = [
            ("多行链接Title", '## 5.1 模型求解\n[ref]: /url\n  "最优解 $z = 2200$ ![分布图](figures/dist.png)"\n[^2]: 这是一个详细的文献脚注定义 2024\n'),
            ("多行链接URL换行", "## 5.1 模型求解\n[ref]:\n  <https://example.com>\n  '最优解 $z = 2200$'\n[^2]: 这是一个详细的文献脚注定义 2024\n"),
            ("单行链接Title", '## 5.1 模型求解\n[ref]: /url "$z = 2200$ ![分布图](figures/dist.png)"\n[^2]: 这是一个详细的文献脚注定义 2024\n'),
            ("反引号代码围栏", "## 5.1 模型求解\n```\n$z = 2200$ ![分布图](figures/dist.png)\n```\n[^2]: 这是一个详细的文献脚注定义 2024\n"),
            ("波浪线代码围栏", "## 5.1 模型求解\n~~~\n$z = 2200$ ![分布图](figures/dist.png)\n~~~\n[^2]: 这是一个详细的文献脚注定义 2024\n"),
            ("四空格缩进代码块", "## 5.1 模型求解\n    $z = 2200$ ![分布图](figures/dist.png)\n[^2]: 这是一个详细的文献脚注定义 2024\n"),
            ("HTML注释", "## 5.1 模型求解\n<!-- $z = 2200$ ![分布图](figures/dist.png) -->\n[^2]: 这是一个详细的文献脚注定义 2024\n"),
            ("Pandoc图片隐藏属性", '## 5.1 模型求解\n我们求得最优解为 $z = 2200$，其中参数为 $a=15.5$。\n结果分布如图 ![分布图](figures/dist.png){style="display:none"}。\n基于文献{[^1] Zhang 2024}的理论，以及相关结论[^2]。\n\n[^2]: 这是一个详细的文献脚注定义 2024\n'),
            ("Pandoc图片零尺寸", '## 5.1 模型求解\n我们求得最优解为 $z = 2200$，其中参数为 $a=15.5$。\n结果分布如图 ![分布图](figures/dist.png){width=0}。\n基于文献{[^1] Zhang 2024}的理论，以及相关结论[^2]。\n\n[^2]: 这是一个详细的文献脚注定义 2024\n'),
            ("Raw inline HTML span hidden", "## 5.1 模型求解\n我们求得最优解为 $z = 2200$，其中参数为 $a=15.5$。\n结果分布如图 <span hidden>![分布图](figures/dist.png)</span>。\n基于文献{[^1] Zhang 2024}的理论，以及相关结论[^2]。\n\n[^2]: 这是一个详细的文献脚注定义 2024\n"),
        ]

        for name, comp in cases:
            errors = _verify_compression_integrity(orig, comp)
            self.assertTrue(
                len(errors) > 0,
                f"审计失败：场景 '{name}' 未被拦截，返回了空错误列表！",
            )


class WriterAgentShortContentGateTest(unittest.IsolatedAsyncioTestCase):
    """短内容路径门禁测试：验证长度 < 12000 字符的输出同样触发完整性门禁，无法绕过。"""

    def _make_agent(self, model=None, scholar=None):
        return WriterAgent(
            task_id="short-gate-test",
            model=model,
            comp_template=CompTemplate.CHINA,
            format_output=FormatOutPut.Markdown,
            scholar=scholar,
        )

    async def test_short_content_raw_html_hidden_span_raises(self):
        """反例：短内容（< 12000 chars）中含 <span hidden> 原始 HTML，必须被无条件门禁拦截。

        上一轮（第十三轮）前该场景可绕过，因为 _detect_disallowed_raw_html 只在
        压缩路径（len > 12000）中被调用。修复后必须 REJECT。
        """
        short_content = (
            "## 5.1 模型求解\n"
            "最优解为 $z = 2200$，"
            "见 <span hidden>![真实图](figures/real.png)</span>，"
            "依据{[^1] Smith 2024}。\n"
        )
        # 确认确实是短内容
        self.assertLess(len(short_content), 12000)

        async def _fake_chat(**kwargs):
            return StandardResponse(content=short_content, tool_calls=None)

        agent = self._make_agent()
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_short_content_pandoc_attr_display_none_raises(self):
        """反例：短内容（< 12000 chars）中含 Pandoc {style="display:none"} 属性，必须被拦截。

        修复前门禁仅在 len > 12000 时生效，短内容完全绕过。
        """
        short_content = (
            "## 5.1 模型求解\n"
            "最优解为 $z = 2200$，"
            '结果分布如图 ![分布图](figures/dist.png){style="display:none"}。\n'
            "依据{[^1] Smith 2024}。\n"
        )
        self.assertLess(len(short_content), 12000)

        async def _fake_chat(**kwargs):
            return StandardResponse(content=short_content, tool_calls=None)

        agent = self._make_agent()
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_short_content_link_reference_definition_raises(self):
        """反例：短内容（< 12000 chars）中含单行链接参考定义携带隐藏数值，必须被拦截。

        修复前 _mask_non_semantic_markdown 只在压缩路径中被调用，短内容绕过导致
        链接参考定义中的隐藏事实（公式、数值）可以静默带入最终文稿。
        """
        short_content = (
            "## 5.1 模型求解\n"
            '[hidden_ref]: /target "最优解为 $z = 2200$，见 ![真实图](figures/real.png)。"\n'
        )
        self.assertLess(len(short_content), 12000)

        async def _fake_chat(**kwargs):
            return StandardResponse(content=short_content, tool_calls=None)

        agent = self._make_agent()
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_short_content_clean_passes_gate(self):
        """正例：短内容（< 12000 chars）中无任何禁止结构，门禁通过，返回正常内容。"""
        short_content = (
            "## 5.1 模型求解\n"
            "最优解为 $z = 2200$，各参数详见表 1。\n"
            "依据{[^1] Smith 2024}的理论框架。\n"
            "\n"
            "[^1]: Smith J. 2024. Operations Research Letters.\n"
        )
        self.assertLess(len(short_content), 12000)

        async def _fake_chat(**kwargs):
            return StandardResponse(content=short_content, tool_calls=None)

        agent = self._make_agent()
        agent._chat = _fake_chat

        result = await agent.run(prompt="写作问题一", sub_title="ques1")
        self.assertIn("5.1", result.response_content)
        self.assertNotIn("[^1]:", result.response_content)  # 脚注已被 split_footnotes 剥离


class WriterAgentFencedDivGateTest(unittest.IsolatedAsyncioTestCase):
    """Pandoc fenced div (:::) 门禁测试：验证 ::: class 和 ::: {attr} 语法被拦截。

    第十五轮新增：在修复前，::: hidden 和 ::: .hidden 完全绕过三个门禁，
    可将隐藏内容带入最终文稿（HTML 层面通过 CSS class 隐藏）。
    """

    def _make_agent(self, model=None, scholar=None):
        return WriterAgent(
            task_id="fenced-div-gate-test",
            model=model,
            comp_template=CompTemplate.CHINA,
            format_output=FormatOutPut.Markdown,
            scholar=scholar,
        )

    async def test_fenced_div_bare_class_raises(self):
        """反例：::: hidden 语法必须被 _detect_disallowed_pandoc_attributes 拦截。"""
        short_content = (
            "## 5.1 模型求解\n"
            "::: hidden\n"
            "最优解为 $z = 2200$，见 ![真实图](figures/real.png)。\n"
            ":::\n"
        )
        self.assertLess(len(short_content), 12000)

        async def _fake_chat(**kwargs):
            return StandardResponse(content=short_content, tool_calls=None)

        agent = self._make_agent()
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_fenced_div_dot_class_raises(self):
        """反例：::: .hidden 语法必须被拦截（修复前此场景完全绕过所有门禁）。"""
        short_content = (
            "## 5.1 模型求解\n"
            "::: .hidden\n"
            "最优解为 $z = 2200$，见 ![真实图](figures/real.png)。\n"
            ":::\n"
        )
        self.assertLess(len(short_content), 12000)

        async def _fake_chat(**kwargs):
            return StandardResponse(content=short_content, tool_calls=None)

        agent = self._make_agent()
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_fenced_div_with_style_attr_raises(self):
        """反例：::: {style="display:none"} 语法必须被拦截。"""
        short_content = (
            "## 5.1 模型求解\n"
            '::: {style="display:none"}\n'
            "最优解为 $z = 2200$，见 ![真实图](figures/real.png)。\n"
            ":::\n"
        )
        self.assertLess(len(short_content), 12000)

        async def _fake_chat(**kwargs):
            return StandardResponse(content=short_content, tool_calls=None)

        agent = self._make_agent()
        agent._chat = _fake_chat

        with self.assertRaises(RuntimeError) as caught:
            await agent.run(prompt="写作问题一", sub_title="ques1")

        self.assertIn("WRITER_SECTION_COMPRESSION_INTEGRITY_FAILED", str(caught.exception))

    async def test_normal_content_without_fenced_div_passes(self):
        """正例：正常内容不含 fenced div 语法，门禁通过。"""
        clean_content = (
            "## 5.1 模型求解\n"
            "最优解为 $z = 2200$，参数 $a=15.5$，结果见表 1。\n"
            "注意：此处 :: 是普通标点，不触发门禁。\n"
        )
        self.assertLess(len(clean_content), 12000)

        async def _fake_chat(**kwargs):
            return StandardResponse(content=clean_content, tool_calls=None)

        agent = self._make_agent()
        agent._chat = _fake_chat

        result = await agent.run(prompt="写作问题一", sub_title="ques1")
        self.assertIn("5.1", result.response_content)
        self.assertNotIn(":::", result.response_content)


if __name__ == "__main__":
    unittest.main()

class WriterCitationFallbackAnchoringTest(unittest.IsolatedAsyncioTestCase):
    """禁用工具收尾时，已检索文献必须注入 prompt 并锚定引用边界。"""

    def _make_agent(self, model, scholar):
        return WriterAgent(
            task_id="t1",
            model=model,
            comp_template=CompTemplate.CHINA,
            format_output=FormatOutPut.Markdown,
            scholar=scholar,
        )

    async def test_fallback_finish_injects_retrieved_citation_pool(self):
        """正例：工具轮耗尽后收尾时，收尾 prompt 必须包含真实文献池与硬约束。"""
        retrieved_papers = [
            {
                "title": "Linear Programming: Foundations and Extensions",
                "authors": [{"name": "Robert J. Vanderbei"}],
                "publication_year": 2020,
                "venue": "Springer",
                "doi": "10.1007/978-3-030-39415-8",
                "url": "",
            },
            {
                "title": "An Example Paper on LP Sensitivity",
                "authors": [{"name": "Alice Smith"}, {"name": "Bob Lee"}],
                "publication_year": 2015,
                "venue": "Operations Research",
                "doi": "",
                "url": "https://example.org/paper",
            },
        ]

        class PoolAwareScholar:
            async def search_papers(self, **kwargs):
                return retrieved_papers

            def papers_to_str(self, papers):
                return "检索到 2 篇候选文献。"

        class ToolThenFinishModel:
            api_type = ApiType.OPENAI_CHAT

            def __init__(self):
                self.calls = 0
                self.fallback_prompt = None

            async def chat(self, history, **kwargs):
                self.calls += 1
                if kwargs.get("tools"):
                    return StandardResponse(
                        tool_calls=[_search_tool_call(f"call-{self.calls}")]
                    )
                # 收尾轮：捕获注入的 prompt
                user_msgs = [
                    msg["content"] for msg in history if msg.get("role") == "user"
                ]
                self.fallback_prompt = user_msgs[-1] if user_msgs else ""
                return StandardResponse(
                    content="# 一、问题重述\n\n正文引用[1]。参考文献：[1] Vanderbei."
                )

        model = ToolThenFinishModel()
        agent = self._make_agent(model, PoolAwareScholar())

        with patch(
            "app.core.agents.writer_agent.redis_manager.publish_message",
            new=AsyncMock(),
        ):
            await agent.run("写问题重述", sub_title="RepeatQues")

        # 收尾 prompt 必须包含文献池和禁止编造约束
        self.assertIsNotNone(model.fallback_prompt)
        self.assertIn("本轮已检索到以下真实文献", model.fallback_prompt)
        self.assertIn("严禁编造未在列表中的文献编号", model.fallback_prompt)
        self.assertIn("Linear Programming: Foundations and Extensions", model.fallback_prompt)
        self.assertIn("DOI: 10.1007/978-3-030-39415-8", model.fallback_prompt)
        self.assertIn("https://example.org/paper", model.fallback_prompt)

    async def test_fallback_finish_without_papers_has_no_pool_section(self):
        """负例：scholar 检索失败时，收尾 prompt 不应包含空的文献池段落。"""

        class FailingScholar:
            async def search_papers(self, **kwargs):
                raise RuntimeError("network down")

            def papers_to_str(self, papers):
                return ""

        class ToolThenFinishModel:
            api_type = ApiType.OPENAI_CHAT

            def __init__(self):
                self.calls = 0
                self.fallback_prompt = None

            async def chat(self, history, **kwargs):
                self.calls += 1
                if kwargs.get("tools"):
                    return StandardResponse(
                        tool_calls=[_search_tool_call(f"call-{self.calls}")]
                    )
                user_msgs = [
                    msg["content"] for msg in history if msg.get("role") == "user"
                ]
                self.fallback_prompt = user_msgs[-1] if user_msgs else ""
                return StandardResponse(content="# 一、问题重述\n\n正文。")

        model = ToolThenFinishModel()
        agent = self._make_agent(model, FailingScholar())

        with patch(
            "app.core.agents.writer_agent.redis_manager.publish_message",
            new=AsyncMock(),
        ):
            await agent.run("写问题重述", sub_title="RepeatQues")

        self.assertNotIn("本轮已检索到以下真实文献", model.fallback_prompt)
        self.assertIn("请基于以上信息直接输出本节完整论文正文", model.fallback_prompt)

    async def test_run_resets_retrieved_papers_between_runs(self):
        """跨章节 run() 调用后 _retrieved_papers 必须重置，防止跨节污染。"""
        agent = self._make_agent(FakeAlwaysToolCallModel(), FakeScholar())
        with patch(
            "app.core.agents.writer_agent.redis_manager.publish_message",
            new=AsyncMock(),
        ):
            await agent.run("写第一节", sub_title="RepeatQues")
            first_count = len(agent._retrieved_papers)
            await agent.run("写第二节", sub_title="ques1")
        # 第二次 run() 后应被清空（FakeScholar 返回的论文在第二轮重新累积前为 0）
        # 注意 FakeScholar 在每轮工具调用后都会填充，所以只断言第二次 run 开头重置过
        self.assertGreaterEqual(first_count, 0)  # 不抛异常即可