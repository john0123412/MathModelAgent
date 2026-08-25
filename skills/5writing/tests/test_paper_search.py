"""paper_search.py 离线单元测试：规范化、双引擎融合、BibTeX 键替换与 CLI 自检。

在线行为（search/verify/bib 访问真实 API）不在此覆盖，由验收流程对真实 /
编造 DOI 人工实测；本文件保证重构时核心纯函数语义不变。

运行：backend/.venv/Scripts/python.exe skills/5writing/tests/test_paper_search.py
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "paper_search.py"

_spec = importlib.util.spec_from_file_location("paper_search_under_test", SCRIPT)
assert _spec is not None and _spec.loader is not None
paper_search = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(paper_search)


def _paper(title: str, doi: str | None, source: str, year: int | None = 2020) -> dict:
    """构造 merge_papers / coverage_filter 所需的最小文献结构。"""
    return {
        "title": title,
        "authors": ["A. Author"],
        "year": year,
        "venue": "Journal of Testing",
        "doi": doi,
        "citations": 5,
        "type": "journal-article",
        "sources": [source],
    }


class NormFunctionsTest(unittest.TestCase):
    def test_norm_doi_variants(self):
        self.assertEqual(paper_search.norm_doi(" HTTPS://DOI.ORG/10.1234/AbC "), "10.1234/abc")
        self.assertEqual(paper_search.norm_doi("https://dx.doi.org/10.1234/x"), "10.1234/x")
        self.assertIsNone(paper_search.norm_doi(""))
        self.assertIsNone(paper_search.norm_doi(None))

    def test_norm_title_keeps_cjk(self):
        self.assertEqual(paper_search.norm_title("Robust Optimization: Theory!"), "robustoptimizationtheory")
        self.assertEqual(paper_search.norm_title("板凳龙运动"), "板凳龙运动")

    def test_query_terms_drop_stopwords(self):
        self.assertEqual(
            paper_search.query_terms("LSTM time series forecasting with the LSTM model"),
            ["lstm", "time", "series", "forecasting", "lstm", "model"],
        )


class MergePapersTest(unittest.TestCase):
    def test_same_doi_cross_validated(self):
        a = _paper("Spiral Motion Analysis", "10.1234/spiral", "openalex")
        b = _paper("Spiral Motion Analysis", "10.1234/SPIRAL", "crossref")
        merged = paper_search.merge_papers([a], [b])
        self.assertEqual(len(merged), 1)
        self.assertTrue(merged[0]["cross_validated"])
        self.assertEqual(sorted(merged[0]["sources"]), ["crossref", "openalex"])

    def test_single_source_not_cross_validated(self):
        merged = paper_search.merge_papers([_paper("Only One", None, "openalex")], [])
        self.assertFalse(merged[0]["cross_validated"])

    def test_no_doi_merged_by_title_and_year(self):
        a = _paper("Collision Detection", None, "openalex", year=2019)
        b = _paper("Collision   Detection", None, "crossref", year=2019)
        merged = paper_search.merge_papers([a], [b])
        self.assertEqual(len(merged), 1)
        self.assertTrue(merged[0]["cross_validated"])

    def test_different_years_not_merged(self):
        a = _paper("Curve Fitting", None, "openalex", year=2018)
        b = _paper("Curve Fitting", None, "crossref", year=2021)
        merged = paper_search.merge_papers([a], [b])
        self.assertEqual(len(merged), 2)

    def test_merge_fills_missing_fields(self):
        a = _paper("Field Fill", "10.1234/fill", "openalex")
        a["venue"] = ""
        b = _paper("Field Fill", "10.1234/fill", "crossref")
        b["authors"] = ["A. Author", "B. Author"]
        merged = paper_search.merge_papers([a], [b])
        self.assertEqual(merged[0]["venue"], "Journal of Testing")
        self.assertEqual(len(merged[0]["authors"]), 2)


class CoverageFilterTest(unittest.TestCase):
    def test_requires_two_term_hits_for_multi_term_query(self):
        query = "machine learning scheduling"
        keep = _paper("Machine learning for nurse scheduling", None, "openalex")
        drop = _paper("Deep neural networks for vision", None, "openalex")
        filtered = paper_search.coverage_filter([keep, drop], query)
        self.assertEqual(filtered, [keep])

    def test_single_term_query_needs_one_hit(self):
        keep = _paper("TOPSIS extensions", None, "openalex")
        drop = _paper("Unrelated study", None, "openalex")
        filtered = paper_search.coverage_filter([keep, drop], "topsis")
        self.assertEqual(filtered, [keep])


class ApplyBibKeyTest(unittest.TestCase):
    def test_replaces_first_key(self):
        entry = "@article{Doe_2020,\n  title = {A Study},\n}"
        self.assertTrue(paper_search.apply_bib_key(entry, "ref01").startswith("@article{ref01,"))

    def test_none_key_returns_original(self):
        entry = "@book{X,\n title = {T},\n}"
        self.assertEqual(paper_search.apply_bib_key(entry, None), entry)


class CliSmokeTest(unittest.TestCase):
    def test_help_exits_zero(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
