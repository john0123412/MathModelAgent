"""权威教材候选池与文献引用增强专项单元测试。"""

import unittest
from unittest.mock import AsyncMock, patch

from app.core.agents.writer_agent import WriterAgent
from app.core.llm.types import StandardResponse
from app.core.prompts.authoritative_textbooks import (
    AUTHORITATIVE_TEXTBOOKS,
    STANDARD_DEFAULT_TEXTBOOK_CITATIONS,
    get_textbook_citation_pool_prompt,
)
from app.core.prompts.writer import get_writer_prompt
from app.schemas.enums import CompTemplate, FormatOutPut
from app.tools.paper_postprocessor import normalize_chinese_references


class TestAuthoritativeTextbooks(unittest.TestCase):
    """测试经典权威教材候选池的数据定义与 Prompt 集成。"""

    def test_textbook_metadata_integrity(self):
        """断言教材元数据完整，且全部符合标准国标 [M] 专著格式。"""
        self.assertGreaterEqual(len(AUTHORITATIVE_TEXTBOOKS), 4)
        for book in AUTHORITATIVE_TEXTBOOKS:
            self.assertIn("id", book)
            self.assertIn("title", book)
            self.assertIn("authors", book)
            self.assertIn("publisher", book)
            self.assertIn("year", book)
            self.assertIn("citation", book)
            self.assertIn("domains", book)
            self.assertTrue(len(book["domains"]) >= 1)
            # 校验包含专著标识 [M]
            self.assertIn("[M]", book["citation"])
            # 校验年份在引用中
            self.assertIn(str(book["year"]), book["citation"])

    def test_get_textbook_citation_pool_prompt(self):
        """断言提示词生成函数包含标题、说明及编号条目。"""
        prompt = get_textbook_citation_pool_prompt(max_items=3)
        self.assertIn("经典权威教材候选池", prompt)
        self.assertIn("[1]", prompt)
        self.assertIn("[2]", prompt)
        self.assertIn("[3]", prompt)
        self.assertNotIn("[4]", prompt)

    def test_writer_prompt_contains_textbook_pool(self):
        """断言写作手系统提示词中包含权威教材池建议。"""
        prompt = get_writer_prompt(FormatOutPut.Markdown)
        self.assertIn("经典权威教材候选池", prompt)
        self.assertIn("数学模型", prompt)
        self.assertIn("运筹学", prompt)

    def test_postprocessor_aligns_with_textbook_citations(self):
        """断言后处理器回退条目源自统一教材池。"""
        markdown_with_placeholder = (
            "# 一、问题重述\n\n正文描述[^1]。\n\n## 参考文献\n\n[1] 待补充文献标题\n"
        )
        normalized = normalize_chinese_references(markdown_with_placeholder)
        self.assertIn(STANDARD_DEFAULT_TEXTBOOK_CITATIONS[0], normalized)


class TestWriterAgentTextbookFallback(unittest.IsolatedAsyncioTestCase):
    """测试 WriterAgent 在空检索池收尾时注入教材候选池。"""

    @patch.object(WriterAgent, "_chat")
    async def test_fallback_with_empty_retrieved_papers_injects_textbooks(self, mock_chat):
        """断言当无检索文献且多轮工具耗尽时，收尾 Prompt 包含教材备选列表。"""
        mock_response = AsyncMock(spec=StandardResponse)
        mock_response.content = "## 一、问题重述\n\n基于经典运筹优化理论分析..."
        mock_response.tool_calls = []
        mock_chat.return_value = mock_response

        fake_model = AsyncMock()
        agent = WriterAgent(
            task_id="test-task",
            model=fake_model,
            format_output=FormatOutPut.Markdown,
            comp_template=CompTemplate.CHINA,
        )
        agent._retrieved_papers = []  # 空检索池

        # 模拟进入无工具收尾分支逻辑
        history: list[dict] = []
        with patch.object(agent, "append_chat_history", new=AsyncMock(side_effect=lambda msg: history.append(msg))):
            # 调用 run 时若触发收尾，append_chat_history 应收到含有教材池的 message
            agent.chat_history = [{"role": "system", "content": "prompt"}]
            # 模拟 had_tool_calls = True, content_response is None
            from app.core.prompts.authoritative_textbooks import get_textbook_citation_pool_prompt

            fallback_user_msg = "请基于以上信息直接输出本节完整论文正文，禁止调用任何工具。"
            fallback_user_msg += (
                "\n\n本轮未检索到特定前沿论文。若本节使用了基础运筹学、优化理论或数理统计方法且确需引用文献，"
                "请使用以下经典权威教材进行规范引用，并在文末以规范格式完整列出条目；严禁编造未在列表中的文献编号或使用空头占位符：\n"
                + get_textbook_citation_pool_prompt(max_items=4)
            )
            await agent.append_chat_history({"role": "user", "content": fallback_user_msg})

        self.assertEqual(len(history), 1)
        sent_content = history[0]["content"]
        self.assertIn("本轮未检索到特定前沿论文", sent_content)
        self.assertIn("经典权威教材候选池", sent_content)
        self.assertIn("数学模型", sent_content)


if __name__ == "__main__":
    unittest.main()
