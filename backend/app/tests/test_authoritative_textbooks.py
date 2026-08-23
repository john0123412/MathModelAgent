"""权威教材候选池与文献引用增强专项单元测试。"""

import json
import unittest
from unittest.mock import AsyncMock, patch

from app.config.setting import ApiType
from app.core.agents.writer_agent import WriterAgent
from app.core.llm.types import StandardResponse, ToolCall
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


class _EmptyPoolToolThenFinishModel:
    """先发一次真工具调用、再在禁用工具收尾轮输出正文的模型。"""

    api_type = ApiType.OPENAI_CHAT

    def __init__(self):
        self.calls = 0
        self.fallback_prompt: str | None = None

    async def chat(self, history, **kwargs):
        self.calls += 1
        if kwargs.get("tools"):
            return StandardResponse(
                tool_calls=[
                    ToolCall(
                        id=f"call-{self.calls}",
                        name="search_papers",
                        arguments=json.dumps({"query": "linear programming"}),
                    )
                ]
            )
        user_msgs = [msg["content"] for msg in history if msg.get("role") == "user"]
        self.fallback_prompt = user_msgs[-1] if user_msgs else ""
        return StandardResponse(content="# 一、问题重述\n\n正文。")


class _NoResultScholar:
    """模拟检索服务正常返回但结果为空列表（非异常路径）。"""

    async def search_papers(self, **kwargs):
        return []

    def papers_to_str(self, papers):
        return "未检索到可用文献。"


class TestWriterAgentTextbookFallback(unittest.IsolatedAsyncioTestCase):
    """通过完整 run() 链路验证空检索池收尾时注入教材候选池。"""

    def _make_agent(self, model, scholar):
        return WriterAgent(
            task_id="t1",
            model=model,
            comp_template=CompTemplate.CHINA,
            format_output=FormatOutPut.Markdown,
            scholar=scholar,
        )

    async def test_empty_pool_fallback_injects_textbooks_via_run(self):
        """真工具轮返回空列表后进入收尾，收尾 prompt 必须包含教材池与硬约束。"""
        model = _EmptyPoolToolThenFinishModel()
        agent = self._make_agent(model, _NoResultScholar())

        with patch(
            "app.core.agents.writer_agent.redis_manager.publish_message",
            new=AsyncMock(),
        ):
            result = await agent.run("写问题重述", sub_title="RepeatQues")

        self.assertIn("# 一、问题重述", result.response_content)
        self.assertIsNotNone(model.fallback_prompt)
        # 教材池建议必须注入收尾 prompt
        self.assertIn("本轮未检索到特定前沿论文", model.fallback_prompt or "")
        self.assertIn("经典权威教材候选池", model.fallback_prompt or "")
        self.assertIn("数学模型", model.fallback_prompt or "")
        self.assertIn("严禁编造未在列表中的文献编号", model.fallback_prompt or "")

    async def test_nonempty_pool_fallback_skips_textbook_section(self):
        """已有真实检索结果时，收尾 prompt 使用检索池而非教材兜底段。"""
        retrieved = [
            {
                "title": "Real Retrieved Paper on LP",
                "authors": [{"name": "Alice Smith"}],
                "publication_year": 2022,
                "venue": "Operations Research",
                "doi": "10.1287/example",
                "url": "",
            }
        ]

        class OneResultScholar:
            async def search_papers(self, **kwargs):
                return retrieved

            def papers_to_str(self, papers):
                return "检索到 1 篇候选文献。"

        model = _EmptyPoolToolThenFinishModel()
        agent = self._make_agent(model, OneResultScholar())

        with patch(
            "app.core.agents.writer_agent.redis_manager.publish_message",
            new=AsyncMock(),
        ):
            await agent.run("写问题重述", sub_title="RepeatQues")

        fp = model.fallback_prompt or ""
        self.assertNotIn("本轮未检索到特定前沿论文", fp)
        self.assertIn("本轮已检索到以下真实文献", fp)
        self.assertIn("Real Retrieved Paper on LP", fp)


if __name__ == "__main__":
    unittest.main()
