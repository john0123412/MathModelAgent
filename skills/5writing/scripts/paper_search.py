#!/usr/bin/env python3
"""双引擎文献检索、DOI 核验与 BibTeX 生成（OpenAlex + Crossref，仅标准库，免 API key）。

5writing 参考文献强制工作流的执行工具：search 发现候选、verify 逐条核验、
bib 由权威元数据生成条目。所有 bib 条目必须由本工具从真实 DOI 生成，
禁止凭记忆手写题名 / 作者 / 期刊 / 卷期页；宁可少引，不可编造。

子命令：
  search  查询 OpenAlex 与 Crossref，按 DOI / 标题交叉验证后融合输出候选文献
  verify  按 DOI 核对元数据；DOI 在注册处不存在时以退出码 1 结束（可能是编造的）
  bib     按 DOI 反查权威 BibTeX 条目，--key 替换引用键

退出码：0 成功；1 DOI 确认不存在（疑似编造）；2 网络 / 服务异常导致无法判定。

示例：
  python paper_search.py search --query "robust optimization vehicle routing" --limit 8
  python paper_search.py verify --doi 10.1287/opre.1030.0065
  python paper_search.py bib --doi 10.1287/opre.1030.0065 --key ref01
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

# OPENALEX_EMAIL 是仓库既有约定（礼貌池标识，非密钥）；PAPER_SEARCH_MAILTO 仅覆盖本工具
MAILTO = (
    os.environ.get("PAPER_SEARCH_MAILTO")
    or os.environ.get("OPENALEX_EMAIL")
    or "paper-search@mathmodel.local"
)
USER_AGENT = f"mathmodel-paper-search/1.0 (mailto:{MAILTO})"
TIMEOUT = 20

STOPWORDS = {
    "a", "an", "the", "of", "for", "and", "or", "in", "on", "with", "based",
    "using", "via", "to", "by", "from", "at", "is", "are", "its",
}


def _force_utf8_stdio() -> None:
    """Windows 重定向场景下 stdout 默认跟随本地编码（cp936），输出 ✓/中文会抛编码错；统一改为 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if encoding != "utf8":
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError):
                pass


def http_get(url: str, accept: str = "application/json") -> bytes:
    """GET 指定 URL，对 429/5xx 做一次退避重试。

    Args:
        url: 目标地址。
        accept: Accept 头，Crossref 内容协商取 BibTeX 时用 x-bibtex。

    Returns:
        响应体字节。

    Raises:
        urllib.error.HTTPError: 重试后仍失败的 HTTP 错误。
        urllib.error.URLError: 网络层失败。
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read()
        except urllib.error.HTTPError as err:
            if err.code in (429, 500, 502, 503) and attempt == 0:
                last_err = err
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as err:
            last_err = err
    raise last_err  # type: ignore[misc]


def norm_doi(doi: str | None) -> str | None:
    """规范化 DOI：去空白、小写、剥掉 https://(dx.)doi.org/ 前缀。"""
    if not doi:
        return None
    doi = doi.strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    return doi or None


def norm_title(title: str) -> str:
    """标题归一化：小写后仅保留字母数字与 CJK，供跨引擎去重比对。"""
    return re.sub(r"[^a-z0-9一-鿿]+", "", title.lower())


def query_terms(query: str) -> list[str]:
    """切分查询词并剔除停用词，用于相关性覆盖率过滤。"""
    terms = [t.lower() for t in re.findall(r"[A-Za-z0-9\-]{2,}|[一-鿿]{2,}", query)]
    return [t for t in terms if t not in STOPWORDS]


# ---------- 引擎 1：OpenAlex ----------

def search_openalex(query: str, limit: int, year_from: int | None, year_to: int | None) -> list[dict]:
    """调用 OpenAlex works 检索接口，返回统一的候选文献结构列表。"""
    filters = []
    if year_from:
        filters.append(f"from_publication_date:{year_from}-01-01")
    if year_to:
        filters.append(f"to_publication_date:{year_to}-12-31")
    params = {
        "search": query,
        "per-page": str(min(limit * 2, 50)),
        "mailto": MAILTO,
        "select": "doi,title,display_name,publication_year,cited_by_count,authorships,primary_location,type",
    }
    if filters:
        params["filter"] = ",".join(filters)
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    data = json.loads(http_get(url))
    papers = []
    for w in data.get("results", []):
        title = w.get("title") or w.get("display_name") or ""
        if not title:
            continue
        authors = [
            a.get("author", {}).get("display_name", "")
            for a in (w.get("authorships") or [])[:8]
        ]
        venue = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
        papers.append({
            "title": title,
            "authors": [a for a in authors if a],
            "year": w.get("publication_year"),
            "venue": venue,
            "doi": norm_doi(w.get("doi")),
            "citations": w.get("cited_by_count") or 0,
            "type": w.get("type") or "",
            "sources": ["openalex"],
        })
    return papers


# ---------- 引擎 2：Crossref ----------

def search_crossref(query: str, limit: int, year_from: int | None, year_to: int | None) -> list[dict]:
    """调用 Crossref bibliographic 检索接口，返回统一的候选文献结构列表。"""
    filters = []
    if year_from:
        filters.append(f"from-pub-date:{year_from}-01-01")
    if year_to:
        filters.append(f"until-pub-date:{year_to}-12-31")
    params = {
        "query.bibliographic": query,
        "rows": str(min(limit * 2, 50)),
        "mailto": MAILTO,
        "select": "DOI,title,author,issued,container-title,is-referenced-by-count,type",
    }
    if filters:
        params["filter"] = ",".join(filters)
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
    data = json.loads(http_get(url))
    papers = []
    for w in data.get("message", {}).get("items", []):
        titles = w.get("title") or []
        if not titles:
            continue
        authors = [
            " ".join(filter(None, [a.get("given"), a.get("family")]))
            for a in (w.get("author") or [])[:8]
        ]
        issued = ((w.get("issued") or {}).get("date-parts") or [[None]])[0]
        venue = (w.get("container-title") or [""])[0]
        papers.append({
            "title": titles[0],
            "authors": [a for a in authors if a],
            "year": issued[0] if issued else None,
            "venue": venue,
            "doi": norm_doi(w.get("DOI")),
            "citations": w.get("is-referenced-by-count") or 0,
            "type": w.get("type") or "",
            "sources": ["crossref"],
        })
    return papers


# ---------- 融合 / 过滤 ----------

def merge_papers(openalex: list[dict], crossref: list[dict]) -> list[dict]:
    """合并两路结果：同 DOI 直接连边；无 DOI 时标题归一化相同且年份一致才合并。

    合并后的每条记录附带 cross_validated 标记（两引擎同时命中可信度最高）。
    """
    merged: list[dict] = []
    by_doi: dict[str, dict] = {}
    by_title: dict[tuple[str, object], dict] = {}
    for p in openalex + crossref:
        key = p["doi"]
        hit = by_doi.get(key) if key else None
        if hit is None:
            tkey = (norm_title(p["title"]), p["year"])
            hit = by_title.get(tkey)
        if hit:
            for s in p["sources"]:
                if s not in hit["sources"]:
                    hit["sources"].append(s)
            hit["citations"] = max(hit["citations"], p["citations"])
            # 补全字段：优先保留信息更完整的一侧
            for field in ("doi", "venue", "year"):
                if not hit.get(field) and p.get(field):
                    hit[field] = p[field]
            if len(p["authors"]) > len(hit["authors"]):
                hit["authors"] = p["authors"]
            continue
        merged.append(p)
        if key:
            by_doi[key] = p
        by_title[(norm_title(p["title"]), p["year"])] = p
    for p in merged:
        p["cross_validated"] = len(p["sources"]) >= 2
    return merged


def coverage_filter(papers: list[dict], query: str) -> list[dict]:
    """按查询词覆盖率过滤：多术语查询要求至少命中两个术语，压掉主题无关的高被引噪声。"""
    terms = query_terms(query)
    if not terms:
        return papers
    need = min(2, len(terms))
    kept = []
    for p in papers:
        haystack = " ".join([p["title"], p["venue"], " ".join(p["authors"])]).lower()
        hits = sum(1 for t in terms if t in haystack)
        if hits >= need:
            p["term_hits"] = hits
            kept.append(p)
    return kept


def cmd_search(args: argparse.Namespace) -> int:
    """search 子命令：双引擎检索 -> 合并 -> 过滤排序输出。"""
    engines = []
    if not args.crossref_only:
        engines.append(("openalex", search_openalex))
    if not args.openalex_only:
        engines.append(("crossref", search_crossref))
    results: list[list[dict]] = []
    errors: list[str] = []
    for name, fn in engines:
        try:
            results.append(fn(args.query, args.limit, args.year_from, args.year_to))
        except Exception as err:  # noqa: BLE001 —— 单引擎失败降级为另一引擎
            results.append([])
            errors.append(f"{name}: {err}")
    for e in errors:
        print(f"[warn] 引擎失败 {e}", file=sys.stderr)
    if all(not r for r in results):
        print("[error] 所有引擎均失败或无结果；不要据此编造文献。", file=sys.stderr)
        return 1
    merged = merge_papers(results[0], results[1]) if len(results) >= 2 else merge_papers(results[0], [])
    filtered = coverage_filter(merged, args.query)
    if not filtered:
        print("[warn] 查询词覆盖率过滤后无结果，输出未过滤候选；请人工判断相关性。", file=sys.stderr)
        filtered = merged
    filtered.sort(key=lambda p: (p["cross_validated"], p.get("term_hits", 0), p["citations"]), reverse=True)
    filtered = filtered[: args.limit]
    if args.json:
        print(json.dumps(filtered, ensure_ascii=False, indent=2))
        return 0
    for i, p in enumerate(filtered, 1):
        mark = "✓交叉验证" if p["cross_validated"] else "/".join(p["sources"])
        authors = ", ".join(p["authors"][:3]) + (" et al." if len(p["authors"]) > 3 else "")
        print(f"{i}. [{mark}] {p['title']}")
        print(f"   {authors} ({p['year']}) — {p['venue'] or '(未知来源)'} — 被引 {p['citations']}")
        print(f"   DOI: {p['doi'] or '(无 DOI，引用前必须另行核验)'}")
    return 0


# ---------- BibTeX / 核验 ----------

def fetch_bibtex(doi: str) -> str:
    """按 DOI 经 doi.org 内容协商取权威 BibTeX，失败时回退 Crossref transform 接口。"""
    doi_n = norm_doi(doi)
    quoted = urllib.parse.quote(doi_n or "")
    try:
        raw = http_get(f"https://doi.org/{quoted}", accept="application/x-bibtex")
    except urllib.error.HTTPError:
        raw = http_get(
            f"https://api.crossref.org/works/{quoted}/transform/application/x-bibtex",
            accept="application/x-bibtex",
        )
    return raw.decode("utf-8", errors="replace").strip()


def apply_bib_key(entry: str, key: str | None) -> str:
    """将 BibTeX 条目的首段引用键替换为指定值（与正文 \\cite 键对齐）。"""
    if not key:
        return entry
    return re.sub(r"^(@\w+\{)[^,]+,", rf"\g<1>{key},", entry, count=1)


def cmd_bib(args: argparse.Namespace) -> int:
    """bib 子命令：DOI -> 权威 BibTeX；404 视为疑似编造返回退出码 1。"""
    try:
        entry = fetch_bibtex(args.doi)
    except urllib.error.HTTPError as err:
        if err.code == 404:
            print(
                f"[error] DOI 不存在：{args.doi}。该文献可能是编造的，禁止引用；"
                "请回到 search 换检索词重查。",
                file=sys.stderr,
            )
            return 1
        print(f"[error] 获取 BibTeX 失败（HTTP {err.code}）：{args.doi}", file=sys.stderr)
        return 2
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        print(f"[error] 网络异常，无法获取 {args.doi} 的 BibTeX：{err}", file=sys.stderr)
        return 2
    print(apply_bib_key(entry, args.key))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """verify 子命令：先问 DOI 注册处（handle 系统）确认存在性，再拉 Crossref 元数据。

    注册处是 DOI 存在性的最终权威，同时覆盖 Crossref 与 DataCite 等注册机构，
    避免把合法的 DataCite DOI 误判为编造。
    """
    doi = norm_doi(args.doi)
    quoted = urllib.parse.quote(doi or "")
    registered: bool | None = None
    try:
        handle = json.loads(http_get(f"https://doi.org/api/handles/{quoted}"))
        registered = handle.get("responseCode") == 1
        if not registered:
            print(
                f"[error] DOI 注册处无此 DOI：{doi}。该文献可能是编造的，禁止引用；"
                "请换检索词重查。",
                file=sys.stderr,
            )
            return 1
    except urllib.error.HTTPError as err:
        if err.code == 404:
            print(
                f"[error] DOI 注册处无此 DOI：{doi}。该文献可能是编造的，禁止引用；"
                "请换检索词重查。",
                file=sys.stderr,
            )
            return 1
        print(f"[warn] DOI 注册处查询失败（HTTP {err.code}），改用 Crossref 直接核验。", file=sys.stderr)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as err:
        print(f"[warn] DOI 注册处查询失败（{err}），改用 Crossref 直接核验。", file=sys.stderr)

    try:
        data = json.loads(http_get(f"https://api.crossref.org/works/{quoted}"))
    except urllib.error.HTTPError as err:
        if err.code == 404:
            if registered is False:
                print(
                    f"[error] DOI 注册处无此 DOI：{doi}。该文献可能是编造的，禁止引用。",
                    file=sys.stderr,
                )
                return 1
            # 注册处存在但 Crossref 无记录：多为 DataCite 等其他注册机构的 DOI
            print(json.dumps({
                "doi": doi,
                "exists": True,
                "note": "DOI 真实存在（注册处已确认），但元数据不在 Crossref；请打开 DOI 页面逐项核对后再引用。",
                "url": f"https://doi.org/{doi}",
            }, ensure_ascii=False, indent=2))
            return 0
        print(f"[error] 核验失败（HTTP {err.code}）：{doi}", file=sys.stderr)
        return 2
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        print(f"[error] 网络异常，无法核验 {doi}：{err}", file=sys.stderr)
        return 2
    w = data["message"]
    info = {
        "doi": doi,
        "title": (w.get("title") or [""])[0],
        "authors": [
            " ".join(filter(None, [a.get("given"), a.get("family")]))
            for a in (w.get("author") or [])
        ],
        "year": ((w.get("issued") or {}).get("date-parts") or [[None]])[0][0],
        "venue": (w.get("container-title") or [""])[0],
        "volume": w.get("volume"),
        "issue": w.get("issue"),
        "pages": w.get("page"),
        "publisher": w.get("publisher"),
        "url": f"https://doi.org/{doi}",
    }
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    """CLI 入口：分发子命令并透传其退出码。"""
    _force_utf8_stdio()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="双引擎检索候选文献")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--year-from", type=int, default=None)
    p_search.add_argument("--year-to", type=int, default=None)
    p_search.add_argument("--json", action="store_true")
    p_search.add_argument("--openalex-only", action="store_true", help="仅诊断用")
    p_search.add_argument("--crossref-only", action="store_true", help="仅诊断用")
    p_search.set_defaults(fn=cmd_search)

    p_bib = sub.add_parser("bib", help="按 DOI 反查权威 BibTeX")
    p_bib.add_argument("--doi", required=True)
    p_bib.add_argument("--key", default=None, help="替换生成条目的引用键")
    p_bib.set_defaults(fn=cmd_bib)

    p_verify = sub.add_parser("verify", help="按 DOI 核对元数据")
    p_verify.add_argument("--doi", required=True)
    p_verify.set_defaults(fn=cmd_verify)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
