"""OpenAlex 学术文献搜索模块。"""

import asyncio
import requests
from typing import List, Dict, Any
from app.services.redis_manager import redis_manager
from app.schemas.response import ScholarMessage
from app.utils.log_util import logger


class OpenAlexScholar:
    """OpenAlex 学术文献搜索客户端。"""

    def __init__(self, task_id: str, email: str | None = None, api_key: str | None = None):
        """初始化 OpenAlex 客户端。

        Args:
            task_id: 任务 ID。
            email: 可选的邮箱地址，用于获取更好的 API 服务。
            api_key: 可选的 OpenAlex API Key。
        """
        self.base_url = "https://api.openalex.org"
        self.email = email
        self.api_key = api_key
        self.task_id = task_id

    def _get_request_url(self, endpoint: str) -> str:
        """构建请求 URL。

        Args:
            endpoint: API 端点路径。
        """
        if endpoint.startswith("/"):
            endpoint = endpoint[1:]
        return f"{self.base_url}/{endpoint}"

    def _get_abstract_from_index(self, abstract_inverted_index: Dict) -> str:
        """从abstract_inverted_index中重建摘要文本

        Args:
            abstract_inverted_index: OpenAlex API返回的倒排索引

        Returns:
            重建的摘要文本
        """
        if not abstract_inverted_index:
            return ""

        # 创建一个足够大的空列表来存放所有单词
        max_position = 0
        for positions in abstract_inverted_index.values():
            if positions and max(positions) > max_position:
                max_position = max(positions)

        words = [""] * (max_position + 1)

        # 在正确的位置填入单词
        for word, positions in abstract_inverted_index.items():
            for position in positions:
                words[position] = word

        # 拼接单词形成文本
        return " ".join(words).strip()

    async def search_papers(self, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        """使用 OpenAlex API 搜索学术论文，带重试和 fallback。

        Args:
            query: 搜索关键词。
            limit: 最大返回结果数。

        Returns:
            包含论文详细信息的字典列表。
        """
        # 尝试 OpenAlex（带重试）
        for attempt in range(3):
            try:
                papers = await self._search_openalex(query, limit)
                if papers:
                    return papers
            except Exception as e:
                logger.warning(f"OpenAlex 第{attempt+1}次尝试失败: {e}")
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))

        # Fallback: Semantic Scholar
        logger.info(f"OpenAlex 搜索失败（query={query!r}），fallback 到 Semantic Scholar")
        try:
            papers = await self._search_semantic_scholar(query, limit)
            if papers:
                logger.info(f"Semantic Scholar fallback 成功，返回 {len(papers)} 篇论文")
                return papers
            logger.warning(f"Semantic Scholar fallback 未返回结果（query={query!r}）")
        except Exception as e:
            logger.error(f"Semantic Scholar fallback 失败（query={query!r}）: {e}")

        # 最终 fallback: 返回空列表，避免中断任务
        logger.error(f"所有学术搜索 API 均失败，返回空列表（query={query!r}）")
        return []

    async def _search_openalex(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """OpenAlex 搜索实现。"""
        base_url = self._get_request_url("works")
        params = {
            "search": query,
            "per_page": limit,
            "select": "id,title,display_name,authorships,cited_by_count,doi,publication_year,biblio,abstract_inverted_index,primary_location",
        }
        if self.email:
            params["mailto"] = self.email
        else:
            raise ValueError("配置OpenAlex邮箱获取访问文献权利")
        if self.api_key:
            params["api_key"] = self.api_key

        headers = {
            "User-Agent": f"OpenAlexScholar/1.0 (mailto:{self.email})" if self.email else "OpenAlexScholar/1.0"
        }

        response = requests.get(base_url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        results = response.json()

        papers = []
        for work in results.get("results", []):
            abstract = self._get_abstract_from_index(work.get("abstract_inverted_index", {}))
            authors = []
            for authorship in work.get("authorships", []):
                author = authorship.get("author", {})
                if author:
                    authors.append({
                        "name": author.get("display_name"),
                        "position": authorship.get("author_position"),
                        "institution": authorship.get("institutions", [{}])[0].get("display_name")
                        if authorship.get("institutions") else None,
                    })
            biblio = work.get("biblio", {})
            paper = {
                "title": work.get("display_name") or work.get("title", ""),
                "abstract": abstract,
                "authors": authors,
                "citations_count": work.get("cited_by_count"),
                "doi": work.get("doi"),
                "publication_year": work.get("publication_year"),
                "citation_info": {
                    "volume": biblio.get("volume"),
                    "issue": biblio.get("issue"),
                    "first_page": biblio.get("first_page"),
                    "last_page": biblio.get("last_page"),
                },
                "citation_format": self._format_citation(work),
            }
            papers.append(paper)

        await redis_manager.publish_message(
            self.task_id,
            ScholarMessage(input={"query": query}, output=[p["title"] for p in papers]),
        )
        return papers

    async def _search_semantic_scholar(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Semantic Scholar API fallback 搜索。"""
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {
            "query": query,
            "limit": limit,
            "fields": "title,authors,year,venue,citationCount,externalIds,url",
        }
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        papers = []
        for item in data.get("data", []):
            authors = [
                {"name": a.get("name", ""), "position": "author"}
                for a in item.get("authors", [])
            ]
            ext_ids = item.get("externalIds", {})
            paper = {
                "title": item.get("title", ""),
                "abstract": item.get("abstract", "") or "",
                "authors": authors,
                "citations_count": item.get("citationCount"),
                "doi": ext_ids.get("DOI"),
                "publication_year": item.get("year"),
                "citation_info": {"volume": None, "issue": None, "first_page": None, "last_page": None},
                "citation_format": self._format_s2_citation(item),
            }
            papers.append(paper)

        return papers

    def _format_s2_citation(self, item: Dict[str, Any]) -> str:
        """Semantic Scholar 论文格式化为 GB/T 7714-2015 格式。"""
        authors = [a.get("name", "") for a in item.get("authors", [])]
        if len(authors) == 0:
            authors_str = "Unknown"
        elif len(authors) <= 3:
            authors_str = ", ".join(authors)
        else:
            authors_str = ", ".join(authors[:3]) + ", et al."

        title = item.get("title", "")
        year = item.get("year", "")
        venue = item.get("venue", "")
        doi = (item.get("externalIds") or {}).get("DOI", "")

        citation = f"{authors_str}. {title}[J]. "
        if venue:
            citation += f"{venue}, {year}."
        else:
            citation += f"{year}."
        if doi:
            citation += f" DOI: {doi}."
        return citation

    def papers_to_str(self, papers: List[Dict[str, Any]]) -> str:
        """将文献列表转换为可读字符串。"""
        result = ""
        for paper in papers:
            result += "\n" + "=" * 80
            result += f"\n标题: {paper['title']}"
            result += f"\n摘要: {paper['abstract']}"
            result += "\n作者:"
            for author in paper["authors"]:
                result += f"- {author['name']}"
            result += f"\n引用次数: {paper['citations_count']}"
            result += f"\n发表年份: {paper['publication_year']}"
            result += f"\n引用格式:\n{paper['citation_format']}"
            result += "=" * 80
        return result

    def _format_citation(self, work: Dict[str, Any]) -> str:
        """将论文数据格式化为 GB/T 7714-2015 引用格式。

        格式: 作者. 题名[J]. 刊名, 年, 卷(期): 页码.
        """
        # 获取所有作者
        authors = [
            authorship.get("author", {}).get("display_name")
            for authorship in work.get("authorships", [])
            if authorship.get("author")
        ]

        # 格式化作者列表（GB/T 7714: 前3位用逗号分隔，超过3位加"等"或"et al."）
        if len(authors) == 0:
            authors_str = "Unknown"
        elif len(authors) <= 3:
            authors_str = ", ".join(authors)
        else:
            authors_str = ", ".join(authors[:3]) + ", et al."

        # 获取标题
        title = work.get("display_name") or work.get("title", "")

        # 获取年份
        year = work.get("publication_year", "")

        # 获取期刊/会议信息
        biblio = work.get("biblio", {})
        volume = biblio.get("volume", "")
        issue = biblio.get("issue", "")
        first_page = biblio.get("first_page", "")
        last_page = biblio.get("last_page", "")

        # 获取来源（期刊名或会议名）
        primary_location = work.get("primary_location") or {}
        source = primary_location.get("source") or {}
        source_name = source.get("display_name", "")

        # 获取 DOI
        doi = work.get("doi", "")

        # 构建 GB/T 7714 格式
        # 作者. 题名[J]. 刊名, 年, 卷(期): 页码.
        citation = f"{authors_str}. {title}[J]. "

        if source_name:
            citation += f"{source_name}, {year}"
            if volume:
                citation += f", {volume}"
            if issue:
                citation += f"({issue})"
            if first_page:
                citation += f": {first_page}"
                if last_page and last_page != first_page:
                    citation += f"-{last_page}"
            citation += "."
        else:
            citation += f"{year}."

        if doi:
            citation += f" DOI: {doi}."

        return citation
