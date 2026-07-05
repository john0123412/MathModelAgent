"""WriterAgent tool-call compatibility tests."""

import unittest
from unittest.mock import AsyncMock, patch

from app.config.setting import ApiType
from app.core.agents.writer_agent import WriterAgent
from app.core.llm.types import StandardResponse
from app.schemas.enums import CompTemplate, FormatOutPut


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


if __name__ == "__main__":
    unittest.main()
