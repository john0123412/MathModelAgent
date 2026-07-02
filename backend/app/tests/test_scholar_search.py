"""文献聚合搜索测试。"""

import asyncio
import unittest
from unittest import mock

from app.tools.openalex_scholar import OpenAlexScholar


class TestScholarSearchAggregation(unittest.TestCase):
    """验证多源聚合、去重和配置开关。"""

    def test_without_openalex_email_still_searches_other_sources(self):
        scholar = OpenAlexScholar(task_id="task-1")

        async def run_test():
            with (
                mock.patch.object(
                    scholar,
                    "_search_semantic_scholar",
                    mock.AsyncMock(return_value=[self._paper("Semantic result", "10/x")]),
                ) as semantic_mock,
                mock.patch.object(
                    scholar,
                    "_search_crossref",
                    mock.AsyncMock(return_value=[]),
                ) as crossref_mock,
                mock.patch.object(
                    scholar,
                    "_search_arxiv",
                    mock.AsyncMock(return_value=[]),
                ) as arxiv_mock,
                mock.patch.object(
                    scholar,
                    "_search_openalex",
                    mock.AsyncMock(return_value=[]),
                ) as openalex_mock,
                mock.patch(
                    "app.tools.openalex_scholar.redis_manager.publish_message",
                    mock.AsyncMock(),
                ),
            ):
                papers = await scholar.search_papers("linear programming")

            self.assertEqual(len(papers), 1)
            semantic_mock.assert_awaited_once()
            crossref_mock.assert_awaited_once()
            arxiv_mock.assert_awaited_once()
            openalex_mock.assert_not_awaited()

        asyncio.run(run_test())

    def test_duplicate_doi_is_merged_and_sources_are_preserved(self):
        scholar = OpenAlexScholar(task_id="task-1", email="user@example.com")
        openalex_paper = self._paper(
            "A robust optimization paper",
            "10.1000/test",
            source="openalex",
            citations=10,
            abstract="short",
        )
        semantic_paper = self._paper(
            "A robust optimization paper",
            "https://doi.org/10.1000/test",
            source="semantic_scholar",
            citations=25,
            abstract="long abstract with more useful context",
        )

        async def run_test():
            with (
                mock.patch.object(
                    scholar,
                    "_search_openalex",
                    mock.AsyncMock(return_value=[openalex_paper]),
                ),
                mock.patch.object(
                    scholar,
                    "_search_semantic_scholar",
                    mock.AsyncMock(return_value=[semantic_paper]),
                ),
                mock.patch.object(
                    scholar,
                    "_search_crossref",
                    mock.AsyncMock(return_value=[]),
                ),
                mock.patch.object(
                    scholar,
                    "_search_arxiv",
                    mock.AsyncMock(return_value=[]),
                ),
                mock.patch(
                    "app.tools.openalex_scholar.redis_manager.publish_message",
                    mock.AsyncMock(),
                ),
            ):
                papers = await scholar.search_papers("robust optimization")

            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0]["doi"], "10.1000/test")
            self.assertEqual(papers[0]["citations_count"], 25)
            self.assertIn("openalex", papers[0]["sources"])
            self.assertIn("semantic_scholar", papers[0]["sources"])
            self.assertIn("long abstract", papers[0]["abstract"])

        asyncio.run(run_test())

    def test_tavily_requires_key_and_enabled_flag(self):
        scholar = OpenAlexScholar(
            task_id="task-1",
            tavily_api_key="test-key",
            web_search_enabled=False,
        )

        async def run_test():
            with (
                mock.patch.object(
                    scholar,
                    "_search_semantic_scholar",
                    mock.AsyncMock(return_value=[]),
                ),
                mock.patch.object(
                    scholar,
                    "_search_crossref",
                    mock.AsyncMock(return_value=[]),
                ),
                mock.patch.object(
                    scholar,
                    "_search_arxiv",
                    mock.AsyncMock(return_value=[]),
                ),
                mock.patch.object(
                    scholar,
                    "_search_tavily",
                    mock.AsyncMock(return_value=[self._paper("web", None, "tavily")]),
                ) as tavily_mock,
                mock.patch(
                    "app.tools.openalex_scholar.redis_manager.publish_message",
                    mock.AsyncMock(),
                ),
            ):
                await scholar.search_papers("factory production")
                tavily_mock.assert_not_awaited()

                await scholar.search_papers("factory production", include_web=True)
                tavily_mock.assert_not_awaited()

                scholar.web_search_enabled = True
                await scholar.search_papers("factory production", include_web=True)
                tavily_mock.assert_awaited_once()

        asyncio.run(run_test())

    def test_web_only_query_skips_scholarly_sources(self):
        scholar = OpenAlexScholar(
            task_id="task-1",
            tavily_api_key="test-key",
            web_search_enabled=True,
        )

        async def run_test():
            with (
                mock.patch.object(
                    scholar,
                    "_search_semantic_scholar",
                    mock.AsyncMock(return_value=[]),
                ) as semantic_mock,
                mock.patch.object(
                    scholar,
                    "_search_crossref",
                    mock.AsyncMock(return_value=[]),
                ) as crossref_mock,
                mock.patch.object(
                    scholar,
                    "_search_arxiv",
                    mock.AsyncMock(return_value=[]),
                ) as arxiv_mock,
                mock.patch.object(
                    scholar,
                    "_search_tavily",
                    mock.AsyncMock(return_value=[self._paper("web", None, "tavily")]),
                ) as tavily_mock,
                mock.patch(
                    "app.tools.openalex_scholar.redis_manager.publish_message",
                    mock.AsyncMock(),
                ),
            ):
                papers = await scholar.search_papers(
                    "official statistics source",
                    source_types=["web"],
                    include_web=True,
                )

            semantic_mock.assert_not_awaited()
            crossref_mock.assert_not_awaited()
            arxiv_mock.assert_not_awaited()
            tavily_mock.assert_awaited_once()
            self.assertEqual(len(papers), 1)

        asyncio.run(run_test())

    def _paper(
        self,
        title,
        doi,
        source="semantic_scholar",
        citations=0,
        abstract="",
    ):
        return {
            "title": title,
            "abstract": abstract,
            "authors": [{"name": "A. Author", "position": "author"}],
            "citations_count": citations,
            "doi": doi,
            "publication_year": 2024,
            "venue": "Test Journal",
            "url": "https://example.com/paper",
            "source": source,
            "sources": [source],
            "publication_type": "journal" if source != "tavily" else "web",
            "citation_info": {
                "volume": None,
                "issue": None,
                "first_page": None,
                "last_page": None,
            },
            "citation_format": "",
        }


if __name__ == "__main__":
    unittest.main()
