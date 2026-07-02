"""学术文献与网页资料聚合搜索模块。"""

from __future__ import annotations

import asyncio
import math
import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from app.schemas.response import ScholarMessage
from app.services.redis_manager import redis_manager
from app.utils.log_util import logger


_DEFAULT_TIMEOUT = 20.0
_DEFAULT_LIMIT = 8
_MAX_SOURCE_LIMIT = 20
_TOKEN_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]+")


class OpenAlexScholar:
    """多源文献搜索客户端。

    类名保留为 OpenAlexScholar，以兼容现有 workflow / writer 注入代码。
    内部已从单一 OpenAlex fallback 升级为多源聚合：
    OpenAlex、Semantic Scholar、Crossref、arXiv，以及可选 Tavily 网页资料。
    """

    def __init__(
        self,
        task_id: str,
        email: str | None = None,
        api_key: str | None = None,
        tavily_api_key: str | None = None,
        web_search_enabled: bool = False,
    ):
        """初始化搜索客户端。

        Args:
            task_id: 任务 ID。
            email: 可选的 OpenAlex 邮箱。未配置时跳过 OpenAlex，不禁用其他源。
            api_key: 可选的 OpenAlex API Key。
            tavily_api_key: 可选的 Tavily API Key。
            web_search_enabled: 是否启用 Tavily 网页资料搜索。
        """
        self.base_url = "https://api.openalex.org"
        self.email = email
        self.api_key = api_key
        self.tavily_api_key = tavily_api_key
        self.web_search_enabled = web_search_enabled
        self.task_id = task_id

    def _get_request_url(self, endpoint: str) -> str:
        """构建 OpenAlex 请求 URL。"""
        if endpoint.startswith("/"):
            endpoint = endpoint[1:]
        return f"{self.base_url}/{endpoint}"

    def _get_abstract_from_index(self, abstract_inverted_index: dict) -> str:
        """从 OpenAlex abstract_inverted_index 中重建摘要文本。"""
        if not abstract_inverted_index:
            return ""

        max_position = 0
        for positions in abstract_inverted_index.values():
            if positions and max(positions) > max_position:
                max_position = max(positions)

        words = [""] * (max_position + 1)
        for word, positions in abstract_inverted_index.items():
            for position in positions:
                words[position] = word

        return " ".join(words).strip()

    async def search_papers(
        self,
        query: str,
        limit: int = _DEFAULT_LIMIT,
        year_from: int | None = None,
        year_to: int | None = None,
        min_citations: int | None = None,
        source_types: list[str] | None = None,
        include_web: bool | None = None,
    ) -> list[dict[str, Any]]:
        """聚合搜索学术论文和可选网页资料。

        Args:
            query: 搜索关键词。
            limit: 最大返回结果数。
            year_from: 起始发表年份。
            year_to: 截止发表年份。
            min_citations: 最小引用次数。网页资料不参与该过滤。
            source_types: 允许的类型，如 journal/conference/preprint/web。
            include_web: 是否包含 Tavily 网页资料；None 时跟随 SEARCH_ENABLED。

        Returns:
            统一结构的候选文献列表。
        """
        normalized_query = query.strip()
        if not normalized_query:
            return []

        safe_limit = self._normalize_limit(limit)
        include_tavily = (
            self.web_search_enabled
            and bool(self.tavily_api_key)
            and (include_web is not False)
        )
        requested_types = {item.lower() for item in source_types or []}
        allow_web = not requested_types or "web" in requested_types
        allow_scholarly = not requested_types or bool(requested_types - {"web"})
        include_tavily = include_tavily and allow_web

        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            tasks = []
            task_names = []
            if allow_scholarly:
                tasks.extend(
                    [
                        self._search_semantic_scholar(
                            client, normalized_query, safe_limit
                        ),
                        self._search_crossref(
                            client, normalized_query, safe_limit, year_from, year_to
                        ),
                        self._search_arxiv(client, normalized_query, safe_limit),
                    ]
                )
                task_names.extend(["Semantic Scholar", "Crossref", "arXiv"])

            if allow_scholarly and self.email:
                tasks.insert(
                    0,
                    self._search_openalex(
                        client,
                        normalized_query,
                        safe_limit,
                        year_from,
                        year_to,
                        requested_types,
                    ),
                )
                task_names.insert(0, "OpenAlex")
            elif allow_scholarly:
                logger.info("OPENALEX_EMAIL 未配置，跳过 OpenAlex，继续使用其他文献源")

            if include_tavily:
                tasks.append(self._search_tavily(client, normalized_query, safe_limit))
                task_names.append("Tavily")

            results = await asyncio.gather(*tasks, return_exceptions=True)

        papers: list[dict[str, Any]] = []
        for source_name, result in zip(task_names, results):
            if isinstance(result, Exception):
                logger.warning(f"{source_name} 搜索失败（query={query!r}）: {result}")
                continue
            papers.extend(result)

        ranked = self._dedupe_and_rank(
            papers=papers,
            query=normalized_query,
            limit=safe_limit,
            min_citations=min_citations,
            source_types=requested_types,
        )

        await redis_manager.publish_message(
            self.task_id,
            ScholarMessage(
                input={
                    "query": normalized_query,
                    "sources": task_names,
                    "include_web": include_tavily,
                },
                output=[paper["title"] for paper in ranked],
            ),
        )

        if not ranked:
            logger.warning(f"所有文献源均未返回可用结果（query={query!r}）")
        return ranked

    async def _search_openalex(
        self,
        client: httpx.AsyncClient,
        query: str,
        limit: int,
        year_from: int | None,
        year_to: int | None,
        source_types: set[str],
    ) -> list[dict[str, Any]]:
        """OpenAlex 搜索实现。"""
        params: dict[str, Any] = {
            "search": query,
            "per_page": limit,
            "select": (
                "id,title,display_name,authorships,cited_by_count,doi,"
                "publication_year,biblio,abstract_inverted_index,primary_location,type"
            ),
            "sort": "relevance_score:desc",
            "mailto": self.email,
        }
        filters = []
        if year_from:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if year_to:
            filters.append(f"to_publication_date:{year_to}-12-31")
        openalex_types = self._to_openalex_types(source_types)
        if openalex_types:
            filters.append(f"type:{'|'.join(openalex_types)}")
        if filters:
            params["filter"] = ",".join(filters)
        if self.api_key:
            params["api_key"] = self.api_key

        headers = {"User-Agent": f"OpenAlexScholar/1.0 (mailto:{self.email})"}
        response = await self._get_json(
            client,
            self._get_request_url("works"),
            params=params,
            headers=headers,
        )

        papers = []
        for work in response.get("results", []):
            abstract = self._get_abstract_from_index(
                work.get("abstract_inverted_index", {})
            )
            authors = []
            for authorship in work.get("authorships", []):
                author = authorship.get("author", {})
                institutions = authorship.get("institutions") or []
                if author:
                    authors.append(
                        {
                            "name": author.get("display_name") or "",
                            "position": authorship.get("author_position"),
                            "institution": institutions[0].get("display_name")
                            if institutions
                            else None,
                        }
                    )
            primary_location = work.get("primary_location") or {}
            source = primary_location.get("source") or {}
            biblio = work.get("biblio", {})
            publication_type = self._map_publication_type(work.get("type"))
            paper = {
                "title": work.get("display_name") or work.get("title", ""),
                "abstract": abstract,
                "authors": authors,
                "citations_count": work.get("cited_by_count") or 0,
                "doi": self._normalize_doi(work.get("doi")),
                "publication_year": work.get("publication_year"),
                "venue": source.get("display_name", ""),
                "url": primary_location.get("landing_page_url") or work.get("id"),
                "source": "openalex",
                "sources": ["openalex"],
                "publication_type": publication_type,
                "citation_info": {
                    "volume": biblio.get("volume"),
                    "issue": biblio.get("issue"),
                    "first_page": biblio.get("first_page"),
                    "last_page": biblio.get("last_page"),
                },
                "citation_format": self._format_citation(
                    authors=[author["name"] for author in authors],
                    title=work.get("display_name") or work.get("title", ""),
                    year=work.get("publication_year"),
                    venue=source.get("display_name", ""),
                    doi=self._normalize_doi(work.get("doi")),
                    publication_type=publication_type,
                    volume=biblio.get("volume"),
                    issue=biblio.get("issue"),
                    first_page=biblio.get("first_page"),
                    last_page=biblio.get("last_page"),
                    url=primary_location.get("landing_page_url") or work.get("id"),
                ),
            }
            papers.append(paper)
        return papers

    async def _search_semantic_scholar(
        self,
        client: httpx.AsyncClient,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Semantic Scholar API 搜索。"""
        params = {
            "query": query,
            "limit": limit,
            "fields": (
                "title,abstract,authors,year,venue,citationCount,externalIds,url,"
                "publicationTypes,journal"
            ),
        }
        response = await self._get_json(
            client,
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params=params,
        )

        papers = []
        for item in response.get("data", []):
            authors = [
                {"name": author.get("name", ""), "position": "author"}
                for author in item.get("authors", [])
            ]
            external_ids = item.get("externalIds") or {}
            journal = item.get("journal") or {}
            publication_type = self._map_s2_publication_type(
                item.get("publicationTypes") or []
            )
            venue = item.get("venue") or journal.get("name") or ""
            doi = self._normalize_doi(external_ids.get("DOI"))
            paper = {
                "title": item.get("title", ""),
                "abstract": item.get("abstract", "") or "",
                "authors": authors,
                "citations_count": item.get("citationCount") or 0,
                "doi": doi,
                "publication_year": item.get("year"),
                "venue": venue,
                "url": item.get("url"),
                "source": "semantic_scholar",
                "sources": ["semantic_scholar"],
                "publication_type": publication_type,
                "citation_info": {
                    "volume": journal.get("volume"),
                    "issue": journal.get("issue"),
                    "first_page": journal.get("pages"),
                    "last_page": None,
                },
                "citation_format": self._format_citation(
                    authors=[author["name"] for author in authors],
                    title=item.get("title", ""),
                    year=item.get("year"),
                    venue=venue,
                    doi=doi,
                    publication_type=publication_type,
                    url=item.get("url"),
                ),
            }
            papers.append(paper)
        return papers

    async def _search_crossref(
        self,
        client: httpx.AsyncClient,
        query: str,
        limit: int,
        year_from: int | None,
        year_to: int | None,
    ) -> list[dict[str, Any]]:
        """Crossref 搜索，用于补充 DOI 与出版信息。"""
        params: dict[str, Any] = {
            "query.bibliographic": query,
            "rows": limit,
            "sort": "relevance",
            "order": "desc",
        }
        filters = []
        if year_from:
            filters.append(f"from-pub-date:{year_from}-01-01")
        if year_to:
            filters.append(f"until-pub-date:{year_to}-12-31")
        if filters:
            params["filter"] = ",".join(filters)
        if self.email:
            params["mailto"] = self.email

        response = await self._get_json(
            client,
            "https://api.crossref.org/works",
            params=params,
        )

        papers = []
        for item in response.get("message", {}).get("items", []):
            title = self._first(item.get("title"))
            if not title:
                continue
            authors = [
                {
                    "name": " ".join(
                        part
                        for part in [author.get("given", ""), author.get("family", "")]
                        if part
                    ),
                    "position": "author",
                }
                for author in item.get("author", [])
            ]
            year = self._crossref_year(item)
            publication_type = self._map_crossref_type(item.get("type"))
            venue = self._first(item.get("container-title"))
            doi = self._normalize_doi(item.get("DOI"))
            url = item.get("URL") or (f"https://doi.org/{doi}" if doi else None)
            page = item.get("page") or ""
            first_page, last_page = self._split_pages(page)
            paper = {
                "title": title,
                "abstract": self._strip_html(item.get("abstract", "")),
                "authors": authors,
                "citations_count": item.get("is-referenced-by-count") or 0,
                "doi": doi,
                "publication_year": year,
                "venue": venue,
                "url": url,
                "source": "crossref",
                "sources": ["crossref"],
                "publication_type": publication_type,
                "citation_info": {
                    "volume": item.get("volume"),
                    "issue": item.get("issue"),
                    "first_page": first_page,
                    "last_page": last_page,
                },
                "citation_format": self._format_citation(
                    authors=[author["name"] for author in authors],
                    title=title,
                    year=year,
                    venue=venue,
                    doi=doi,
                    publication_type=publication_type,
                    volume=item.get("volume"),
                    issue=item.get("issue"),
                    first_page=first_page,
                    last_page=last_page,
                    url=url,
                ),
            }
            papers.append(paper)
        return papers

    async def _search_arxiv(
        self,
        client: httpx.AsyncClient,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """arXiv 搜索，用于补充数学、统计、优化与计算机方向预印本。"""
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        response = await client.get("https://export.arxiv.org/api/query", params=params)
        response.raise_for_status()

        root = ET.fromstring(response.text)
        namespace = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }
        papers = []
        for entry in root.findall("atom:entry", namespace):
            title = self._compact_ws(entry.findtext("atom:title", "", namespace))
            abstract = self._compact_ws(entry.findtext("atom:summary", "", namespace))
            year = self._year_from_date(entry.findtext("atom:published", "", namespace))
            url = entry.findtext("atom:id", "", namespace)
            authors = [
                {
                    "name": author.findtext("atom:name", "", namespace),
                    "position": "author",
                }
                for author in entry.findall("atom:author", namespace)
            ]
            doi = self._normalize_doi(
                entry.findtext("arxiv:doi", "", namespace)
            )
            paper = {
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "citations_count": 0,
                "doi": doi,
                "publication_year": year,
                "venue": "arXiv",
                "url": url,
                "source": "arxiv",
                "sources": ["arxiv"],
                "publication_type": "preprint",
                "citation_info": {
                    "volume": None,
                    "issue": None,
                    "first_page": None,
                    "last_page": None,
                },
                "citation_format": self._format_citation(
                    authors=[author["name"] for author in authors],
                    title=title,
                    year=year,
                    venue="arXiv",
                    doi=doi,
                    publication_type="preprint",
                    url=url,
                ),
            }
            papers.append(paper)
        return papers

    async def _search_tavily(
        self,
        client: httpx.AsyncClient,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Tavily 网页搜索，用于补充官方报告、数据来源和背景资料。"""
        if not self.tavily_api_key:
            return []

        response = await client.post(
            "https://api.tavily.com/search",
            headers={
                "Authorization": f"Bearer {self.tavily_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "search_depth": "basic",
                "max_results": min(limit, 5),
                "include_answer": False,
                "include_raw_content": False,
            },
        )
        response.raise_for_status()
        data = response.json()

        papers = []
        for item in data.get("results", []):
            title = item.get("title", "")
            url = item.get("url", "")
            if not title or not url:
                continue
            paper = {
                "title": title,
                "abstract": item.get("content", "") or "",
                "authors": [],
                "citations_count": 0,
                "doi": None,
                "publication_year": None,
                "venue": self._domain_from_url(url),
                "url": url,
                "source": "tavily",
                "sources": ["tavily"],
                "publication_type": "web",
                "web_score": item.get("score") or 0,
                "citation_info": {
                    "volume": None,
                    "issue": None,
                    "first_page": None,
                    "last_page": None,
                },
                "citation_format": self._format_citation(
                    authors=[],
                    title=title,
                    year=None,
                    venue=self._domain_from_url(url),
                    doi=None,
                    publication_type="web",
                    url=url,
                ),
            }
            papers.append(paper)
        return papers

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, Any],
        headers: dict[str, str] | None = None,
        retries: int = 2,
    ) -> dict[str, Any]:
        """GET JSON，带轻量重试。"""
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_error = exc
                if attempt < retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def _dedupe_and_rank(
        self,
        papers: list[dict[str, Any]],
        query: str,
        limit: int,
        min_citations: int | None,
        source_types: set[str],
    ) -> list[dict[str, Any]]:
        """按 DOI/title 去重，并按相关性、引用量、年份和完整度重排。"""
        deduped: dict[str, dict[str, Any]] = {}
        for paper in papers:
            if not paper.get("title"):
                continue
            publication_type = (paper.get("publication_type") or "").lower()
            if source_types and publication_type not in source_types:
                continue
            if (
                min_citations is not None
                and publication_type != "web"
                and (paper.get("citations_count") or 0) < min_citations
            ):
                continue

            key = self._dedupe_key(paper)
            if key in deduped:
                deduped[key] = self._merge_paper(deduped[key], paper)
            else:
                deduped[key] = paper

        candidates = list(deduped.values())
        max_citations = max(
            [paper.get("citations_count") or 0 for paper in candidates] or [0]
        )
        for paper in candidates:
            paper["relevance_score"] = self._score_paper(
                paper=paper,
                query=query,
                max_citations=max_citations,
            )
            paper["citation_format"] = self._format_citation(
                authors=[author.get("name", "") for author in paper.get("authors", [])],
                title=paper.get("title", ""),
                year=paper.get("publication_year"),
                venue=paper.get("venue", ""),
                doi=paper.get("doi"),
                publication_type=paper.get("publication_type", "journal"),
                volume=paper.get("citation_info", {}).get("volume"),
                issue=paper.get("citation_info", {}).get("issue"),
                first_page=paper.get("citation_info", {}).get("first_page"),
                last_page=paper.get("citation_info", {}).get("last_page"),
                url=paper.get("url"),
            )

        candidates.sort(
            key=lambda paper: (
                paper.get("relevance_score") or 0,
                paper.get("citations_count") or 0,
                paper.get("publication_year") or 0,
            ),
            reverse=True,
        )
        return candidates[:limit]

    def _merge_paper(
        self,
        current: dict[str, Any],
        incoming: dict[str, Any],
    ) -> dict[str, Any]:
        """合并重复文献，保留更完整的信息。"""
        merged = dict(current)
        merged_sources = set(current.get("sources") or [current.get("source")])
        merged_sources.update(incoming.get("sources") or [incoming.get("source")])
        merged["sources"] = sorted(source for source in merged_sources if source)

        if len(incoming.get("abstract", "")) > len(current.get("abstract", "")):
            merged["abstract"] = incoming.get("abstract", "")
        if (incoming.get("citations_count") or 0) > (current.get("citations_count") or 0):
            merged["citations_count"] = incoming.get("citations_count") or 0
        for field in ["doi", "publication_year", "venue", "url", "publication_type"]:
            if not merged.get(field) and incoming.get(field):
                merged[field] = incoming[field]
        if len(incoming.get("authors", [])) > len(current.get("authors", [])):
            merged["authors"] = incoming.get("authors", [])
        for key, value in incoming.get("citation_info", {}).items():
            if not merged.setdefault("citation_info", {}).get(key) and value:
                merged["citation_info"][key] = value
        return merged

    def _score_paper(
        self,
        paper: dict[str, Any],
        query: str,
        max_citations: int,
    ) -> float:
        """计算候选文献排序分。"""
        query_terms = set(self._tokens(query))
        text = " ".join(
            [
                paper.get("title", ""),
                paper.get("abstract", ""),
                paper.get("venue", ""),
            ]
        )
        text_terms = set(self._tokens(text))
        term_score = (
            len(query_terms & text_terms) / len(query_terms) if query_terms else 0.0
        )
        citations = paper.get("citations_count") or 0
        citation_score = (
            math.log1p(citations) / math.log1p(max_citations)
            if max_citations > 0
            else 0.0
        )
        year = paper.get("publication_year")
        year_score = 0.0
        if isinstance(year, int):
            year_score = max(0.0, min(1.0, (year - 1990) / 40))
        abstract_score = 1.0 if paper.get("abstract") else 0.0
        doi_score = 1.0 if paper.get("doi") else 0.0
        source_bonus = 0.08 * len(paper.get("sources") or [])
        web_score = min(1.0, float(paper.get("web_score") or 0))

        if paper.get("publication_type") == "web":
            return 0.55 * term_score + 0.25 * web_score + 0.20 * abstract_score
        return (
            0.45 * term_score
            + 0.25 * citation_score
            + 0.15 * year_score
            + 0.10 * abstract_score
            + 0.05 * doi_score
            + source_bonus
        )

    def papers_to_str(self, papers: list[dict[str, Any]]) -> str:
        """将文献列表转换为 Writer 可读字符串。"""
        if not papers:
            return "未检索到可用文献。请基于已有建模结果写作，并避免编造参考文献。"

        result = ""
        for index, paper in enumerate(papers, start=1):
            result += "\n" + "=" * 80
            result += f"\n候选文献 {index}"
            result += f"\n标题: {paper.get('title', '')}"
            result += f"\n类型: {paper.get('publication_type', '')}"
            result += f"\n来源: {', '.join(paper.get('sources') or [])}"
            if paper.get("venue"):
                result += f"\n期刊/会议/站点: {paper['venue']}"
            if paper.get("url"):
                result += f"\nURL: {paper['url']}"
            if paper.get("doi"):
                result += f"\nDOI: {paper['doi']}"
            abstract = paper.get("abstract", "")
            result += f"\n摘要: {abstract[:1000]}"
            result += "\n作者:"
            for author in paper.get("authors", []):
                if author.get("name"):
                    result += f"\n- {author['name']}"
            result += f"\n引用次数: {paper.get('citations_count') or 0}"
            result += f"\n发表年份: {paper.get('publication_year') or ''}"
            result += f"\n推荐分: {paper.get('relevance_score', 0):.3f}"
            result += f"\n引用格式:\n{paper.get('citation_format', '')}"
            result += "\n" + "=" * 80
        return result

    def _format_citation(
        self,
        authors: list[str],
        title: str,
        year: int | str | None,
        venue: str,
        doi: str | None,
        publication_type: str,
        volume: str | None = None,
        issue: str | None = None,
        first_page: str | None = None,
        last_page: str | None = None,
        url: str | None = None,
    ) -> str:
        """格式化为接近 GB/T 7714-2015 的引用字符串。"""
        authors_str = self._format_authors(authors)
        year_str = str(year) if year else "n.d."
        mark = self._citation_mark(publication_type)
        citation = f"{authors_str}. {title}[{mark}]. "

        if publication_type == "web":
            if venue:
                citation += f"{venue}, "
            citation += f"{year_str}."
            if url:
                citation += f" Available: {url}."
            return citation

        if publication_type == "preprint":
            citation += f"{venue or 'Preprint'}, {year_str}."
            if doi:
                citation += f" DOI: {doi}."
            elif url:
                citation += f" Available: {url}."
            return citation

        if venue:
            citation += f"{venue}, {year_str}"
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
            citation += f"{year_str}."

        if doi:
            citation += f" DOI: {doi}."
        elif url:
            citation += f" Available: {url}."
        return citation

    def _citation_mark(self, publication_type: str) -> str:
        """返回 GB/T 类型标识。"""
        return {
            "journal": "J",
            "conference": "C",
            "preprint": "EB/OL",
            "book": "M",
            "web": "EB/OL",
        }.get(publication_type, "J")

    def _format_authors(self, authors: list[str]) -> str:
        """格式化作者列表。"""
        cleaned = [author for author in authors if author]
        if not cleaned:
            return "Unknown"
        if len(cleaned) <= 3:
            return ", ".join(cleaned)
        return ", ".join(cleaned[:3]) + ", et al."

    def _dedupe_key(self, paper: dict[str, Any]) -> str:
        """生成去重 key。"""
        doi = self._normalize_doi(paper.get("doi"))
        if doi:
            return f"doi:{doi.lower()}"
        title = self._normalize_title(paper.get("title", ""))
        return f"title:{title}"

    def _normalize_limit(self, limit: int | None) -> int:
        """规范化搜索结果数量。"""
        if limit is None:
            return _DEFAULT_LIMIT
        return max(1, min(int(limit), _MAX_SOURCE_LIMIT))

    def _normalize_doi(self, doi: Any) -> str | None:
        """规范化 DOI。"""
        if not doi:
            return None
        doi_str = str(doi).strip()
        doi_str = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi_str, flags=re.I)
        doi_str = doi_str.removeprefix("doi:")
        return doi_str.strip().lower() or None

    def _normalize_title(self, title: str) -> str:
        """规范化标题用于去重。"""
        return " ".join(self._tokens(title))

    def _tokens(self, text: str) -> list[str]:
        """简单分词，支持英文和中文连续片段。"""
        return [token.lower() for token in _TOKEN_RE.findall(text or "") if len(token) > 1]

    def _to_openalex_types(self, source_types: set[str]) -> list[str]:
        """将通用类型映射到 OpenAlex type。"""
        mapping = {
            "journal": "article",
            "conference": "proceedings-article",
            "book": "book",
            "preprint": "preprint",
        }
        return [mapping[item] for item in source_types if item in mapping]

    def _map_publication_type(self, raw_type: str | None) -> str:
        """映射 OpenAlex 类型。"""
        if raw_type in {"proceedings-article", "conference-paper"}:
            return "conference"
        if raw_type == "preprint":
            return "preprint"
        if raw_type == "book":
            return "book"
        return "journal"

    def _map_s2_publication_type(self, publication_types: list[str]) -> str:
        """映射 Semantic Scholar 类型。"""
        lowered = {item.lower() for item in publication_types}
        if any("conference" in item for item in lowered):
            return "conference"
        if any("review" in item or "journal" in item for item in lowered):
            return "journal"
        return "journal"

    def _map_crossref_type(self, raw_type: str | None) -> str:
        """映射 Crossref 类型。"""
        if raw_type in {"proceedings-article", "proceedings"}:
            return "conference"
        if raw_type in {"posted-content", "preprint"}:
            return "preprint"
        if raw_type in {"book", "book-chapter", "monograph"}:
            return "book"
        return "journal"

    def _crossref_year(self, item: dict[str, Any]) -> int | None:
        """从 Crossref date-parts 提取年份。"""
        for key in ["published-print", "published-online", "published", "created"]:
            parts = item.get(key, {}).get("date-parts")
            if parts and parts[0]:
                year = parts[0][0]
                if isinstance(year, int):
                    return year
        return None

    def _split_pages(self, pages: str) -> tuple[str | None, str | None]:
        """拆分页码。"""
        if not pages:
            return None, None
        if "-" in pages:
            first, last = pages.split("-", 1)
            return first.strip() or None, last.strip() or None
        return pages.strip(), None

    def _first(self, value: Any) -> str:
        """返回列表首项或字符串。"""
        if isinstance(value, list):
            return str(value[0]) if value else ""
        return str(value or "")

    def _strip_html(self, text: str) -> str:
        """去掉 Crossref 摘要中的简单 HTML 标签。"""
        return self._compact_ws(re.sub(r"<[^>]+>", " ", text or ""))

    def _compact_ws(self, text: str) -> str:
        """压缩空白。"""
        return re.sub(r"\s+", " ", text or "").strip()

    def _year_from_date(self, value: str) -> int | None:
        """从 ISO 日期提取年份。"""
        match = re.match(r"(\d{4})", value or "")
        return int(match.group(1)) if match else None

    def _domain_from_url(self, url: str) -> str:
        """从 URL 粗略提取域名。"""
        match = re.match(r"https?://([^/]+)", url or "")
        return match.group(1) if match else ""
