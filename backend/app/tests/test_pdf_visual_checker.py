"""PDF visual post-check tests."""

import json
import os
import tempfile
import unittest
from unittest import mock

from app.tools.pdf_visual_checker import (
    CUMCM2026_STRICT_EDITORIAL_QUALITY_POLICY,
    check_pdf_visual,
)


class _FakePage:
    rect = mock.Mock(width=595.0, height=842.0)

    def __init__(self, text="可提取文本", lines=None):
        self.text = text
        self.lines = lines or []

    def get_text(self, option=None):
        if option == "dict":
            return {"blocks": [{"lines": self.lines}] if self.lines else []}
        return self.text

    def get_pixmap(self, matrix=None, alpha=False):
        return mock.Mock(samples=b"\xff" * 64 + b"\x00" * 64)


class _LeadingWhitespacePage(_FakePage):
    def get_pixmap(self, matrix=None, alpha=False):
        return mock.Mock(samples=b"\xff" * 4096 + b"\x00" * 64)


class _OverflowPage(_FakePage):
    def __init__(self):
        super().__init__("附录B 源程序代码")

    def get_text(self, option=None):
        if option == "dict":
            return {
                "blocks": [
                    {
                        "lines": [
                            {
                                "bbox": (88.0, 120.0, 602.0, 132.0),
                                "spans": [{"text": "print('this very long code line reaches the page edge')"}],
                            }
                        ]
                    }
                ]
            }
        return self.text


class _NonA4Page(_FakePage):
    rect = mock.Mock(width=612.0, height=792.0)


class _NarrowMarginPage(_FakePage):
    def __init__(self):
        super().__init__(
            "一、问题重述\n正文",
            [
                {
                    "bbox": (40.0, 120.0, 420.0, 132.0),
                    "spans": [{"text": "正文距离左侧不足 2.5cm"}],
                }
            ],
        )


class _BadFirstPage(_FakePage):
    def __init__(self):
        super().__init__("目录\n一、问题重述\n正文")


class _FakeDocument:
    page_count = 2

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def __getitem__(self, index):
        if index == 0:
            return _FakePage("论文标题\n摘要\n摘要正文\n关键词：优化")
        return _FakePage("一、问题重述\n正文")


class _LeadingWhitespaceDocument(_FakeDocument):
    def __getitem__(self, index):
        page = _LeadingWhitespacePage(
            "论文标题\n摘要\n摘要正文\n关键词：优化"
            if index == 0
            else "一、问题重述\n正文"
        )
        return page


class _OverflowDocument(_FakeDocument):
    page_count = 4

    def __getitem__(self, index):
        if index == 3:
            return _OverflowPage()
        if index == 0:
            return _FakePage("论文标题\n摘要\n摘要正文\n关键词：优化")
        return _FakePage()


class _NarrowMarginDocument(_FakeDocument):
    def __getitem__(self, index):
        if index == 0:
            return _FakePage("论文标题\n摘要\n摘要正文\n关键词：优化")
        return _NarrowMarginPage()


class _BadFirstPageDocument(_FakeDocument):
    def __getitem__(self, index):
        if index == 0:
            return _BadFirstPage()
        return _FakePage("二、问题分析")


class _UntitledAbstractDocument(_FakeDocument):
    def __getitem__(self, index):
        if index == 0:
            return _FakePage("摘要\n摘要正文\n关键词：优化")
        return _FakePage("一、问题重述")


class _LongBodyDocument(_FakeDocument):
    page_count = 33

    def __getitem__(self, index):
        if index == 0:
            return _FakePage("论文标题\n摘要\n摘要正文\n关键词：优化")
        return _FakePage(f"正文第 {index} 页")


class _NonA4LaterPageDocument(_FakeDocument):
    page_count = 4

    def __getitem__(self, index):
        if index == 0:
            return _FakePage("论文标题\n摘要\n摘要正文\n关键词：优化")
        if index == 3:
            return _NonA4Page("附录B 源程序代码")
        return _FakePage("正文")


class _ForbiddenSubmissionTermDocument(_FakeDocument):
    def __getitem__(self, index):
        if index == 0:
            return _FakePage("论文标题\n摘要\n摘要正文\n关键词：优化")
        return _FakePage("承诺书\n参赛队号：12345")


class _EditorialQualityDocument(_FakeDocument):
    page_count = 12

    def __getitem__(self, index):
        if index == 0:
            return _FakePage("论文标题\n摘要\n过短摘要\n关键词：优化")
        if index == 11:
            return _FakePage("附录A")
        return _FakePage(f"正文第 {index} 页")


class _LowCoverageAbstractDocument(_EditorialQualityDocument):
    def __getitem__(self, index):
        if index == 0:
            abstract = "A" * 500
            return _FakePage(
                f"论文标题\n摘要\n{abstract}\n关键词：优化",
                [
                    {
                        "bbox": (100.0, 100.0, 200.0, 110.0),
                        "spans": [{"text": abstract}],
                    }
                ],
            )
        return super().__getitem__(index)


class _HighDensityAbstractDocument(_EditorialQualityDocument):
    def __getitem__(self, index):
        if index == 0:
            abstract = "A" * 500
            return _FakePage(
                f"论文标题\n摘要\n{abstract}\n关键词：优化",
                [
                    {
                        "bbox": (80.0, 80.0, 510.0, 500.0),
                        "spans": [{"text": abstract}],
                    }
                ],
            )
        return super().__getitem__(index)


class _LiteralMarkdownHeadingDocument(_FakeDocument):
    def __getitem__(self, index):
        if index == 0:
            return _FakePage("论文标题\n摘要\n摘要正文\n关键词：优化")
        return _FakePage("上一段正文\n### 6.1.2 未渲染标题\n后续正文")


class _OfficialLimitBodyDocument(_FakeDocument):
    """Abstract page plus a configurable number of body pages.

    The abstract mirrors ``_HighDensityAbstractDocument`` so the strict
    editorial policy does not mask the body-page-limit signal under test.
    """

    def __init__(self, body_pages):
        self.page_count = body_pages + 1

    def __getitem__(self, index):
        if index == 0:
            abstract = "A" * 500
            return _FakePage(
                f"论文标题\n摘要\n{abstract}\n关键词：优化",
                [
                    {
                        "bbox": (80.0, 80.0, 510.0, 500.0),
                        "spans": [{"text": abstract}],
                    }
                ],
            )
        return _FakePage(f"正文第 {index} 页")


class TestPdfVisualChecker(unittest.TestCase):
    """Verify PDF visual check writes structured status without blocking exports."""

    def test_missing_pdf_writes_skipped_report(self):
        with tempfile.TemporaryDirectory() as work_dir:
            report = check_pdf_visual(os.path.join(work_dir, "res.pdf"), work_dir)

            self.assertFalse(report["success"])
            self.assertFalse(report["enabled"])
            self.assertEqual(report["status"], "SKIPPED")

            with open(os.path.join(work_dir, "pdf_visual_check.json"), encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["status"], "SKIPPED")

    def test_valid_pdf_writes_pass_report(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")

            with mock.patch("fitz.open", return_value=_FakeDocument()):
                report = check_pdf_visual(pdf_path, work_dir)

            self.assertTrue(report["enabled"])
            self.assertTrue(report["success"])
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["page_count"], 2)
            self.assertEqual(report["pages_checked"], 2)
            self.assertEqual(report["scan_scope"], "all_pages")
            self.assertIsNotNone(report["pdf_sha256"])
            self.assertTrue(report["checks"]["a4_size"]["passed"])
            self.assertTrue(report["checks"]["text_extractable"]["passed"])
            self.assertTrue(report["checks"]["nonblank_pages"]["passed"])
            self.assertTrue(report["checks"]["file_size"]["passed"])
            self.assertTrue(report["checks"]["abstract_first_page"]["passed"])
            self.assertTrue(report["checks"]["no_table_of_contents"]["passed"])
            self.assertTrue(report["checks"]["body_page_limit"]["passed"])
            self.assertTrue(report["checks"]["content_margin"]["passed"])

    def test_pages_with_top_margin_whitespace_are_not_marked_blank(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")

            with mock.patch("fitz.open", return_value=_LeadingWhitespaceDocument()):
                report = check_pdf_visual(pdf_path, work_dir)

            self.assertEqual(report["status"], "PASS")
            self.assertTrue(report["checks"]["nonblank_pages"]["passed"])

    def test_text_line_near_page_edge_fails_report(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")

            with mock.patch("fitz.open", return_value=_OverflowDocument()):
                report = check_pdf_visual(pdf_path, work_dir)

        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"]["text_margin"]["passed"])
        self.assertEqual(report["checks"]["text_margin"]["overflows"][0]["page"], 4)

    def test_content_inside_physical_edge_but_outside_cumcm_margin_fails(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")

            with mock.patch("fitz.open", return_value=_NarrowMarginDocument()):
                report = check_pdf_visual(pdf_path, work_dir)

        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(report["checks"]["text_margin"]["passed"])
        self.assertFalse(report["checks"]["content_margin"]["passed"])
        self.assertEqual(report["checks"]["content_margin"]["issues"][0]["sides"], ["left"])

    def test_first_page_must_be_abstract_not_toc_or_body(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")

            with mock.patch("fitz.open", return_value=_BadFirstPageDocument()):
                report = check_pdf_visual(pdf_path, work_dir)

        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"]["abstract_first_page"]["passed"])
        self.assertFalse(report["checks"]["no_table_of_contents"]["passed"])

    def test_first_page_requires_title_before_abstract(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")

            with mock.patch("fitz.open", return_value=_UntitledAbstractDocument()):
                report = check_pdf_visual(pdf_path, work_dir)

        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"]["abstract_first_page"]["has_title_before_abstract"])

    def test_body_pages_after_abstract_are_limited_by_the_project_baseline(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")

            with mock.patch("fitz.open", return_value=_LongBodyDocument()):
                report = check_pdf_visual(pdf_path, work_dir)

        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"]["body_page_limit"]["passed"])
        self.assertEqual(
            report["checks"]["body_page_limit"]["body_pages_after_abstract"], 32
        )

    def test_cumcm2026_accepts_body_up_to_official_30_page_rule(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")

            with mock.patch(
                "fitz.open", return_value=_OfficialLimitBodyDocument(body_pages=30)
            ):
                report = check_pdf_visual(pdf_path, work_dir, export_profile="cumcm2026")

        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["checks"]["body_page_limit"]["passed"])
        self.assertEqual(report["checks"]["body_page_limit"]["max_body_pages"], 30)
        self.assertEqual(
            report["checks"]["editorial_quality"]["checkpoints"]["body_page_range"]
            ["recommended_range_pages"],
            [15, 30],
        )

    def test_cumcm2026_rejects_body_beyond_official_30_page_rule(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")

            with mock.patch(
                "fitz.open", return_value=_OfficialLimitBodyDocument(body_pages=31)
            ):
                report = check_pdf_visual(pdf_path, work_dir, export_profile="cumcm2026")

        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"]["body_page_limit"]["passed"])
        self.assertEqual(
            report["checks"]["body_page_limit"]["body_pages_after_abstract"], 31
        )

    def test_cumcm2026_rejects_body_below_strict_15_page_floor(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")

            with mock.patch(
                "fitz.open", return_value=_OfficialLimitBodyDocument(body_pages=14)
            ):
                report = check_pdf_visual(pdf_path, work_dir, export_profile="cumcm2026")

        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"]["body_page_limit"]["passed"])
        self.assertEqual(report["checks"]["body_page_limit"]["min_body_pages"], 15)
        self.assertEqual(
            report["checks"]["body_page_limit"]["body_pages_after_abstract"], 14
        )

    def test_cumcm2026_accepts_body_at_strict_15_page_floor(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")

            with mock.patch(
                "fitz.open", return_value=_OfficialLimitBodyDocument(body_pages=15)
            ):
                report = check_pdf_visual(pdf_path, work_dir, export_profile="cumcm2026")

        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["checks"]["body_page_limit"]["passed"])
        self.assertEqual(
            report["checks"]["body_page_limit"]["body_pages_after_abstract"], 15
        )

    def test_task_contract_can_tighten_body_page_range(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")

            with mock.patch("fitz.open", return_value=_HighDensityAbstractDocument()):
                report = check_pdf_visual(
                    pdf_path,
                    work_dir,
                    quality_policy=CUMCM2026_STRICT_EDITORIAL_QUALITY_POLICY,
                    body_min_pages=8,
                    body_max_pages=9,
                    min_content_margin_cm=2.0,
                )

        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["checks"]["body_page_limit"]["max_body_pages"], 9)
        self.assertEqual(
            report["checks"]["editorial_quality"]["checkpoints"]["body_page_range"]
            ["recommended_range_pages"],
            [8, 9],
        )
        self.assertAlmostEqual(report["checks"]["content_margin"]["min_margin_pt"], 56.69, places=2)

    def test_a4_size_is_checked_for_all_pages(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")

            with mock.patch("fitz.open", return_value=_NonA4LaterPageDocument()):
                report = check_pdf_visual(pdf_path, work_dir)

        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"]["a4_size"]["passed"])
        self.assertEqual(report["checks"]["a4_size"]["pages"][-1]["page"], 4)
        self.assertFalse(report["checks"]["a4_size"]["pages"][-1]["a4"])

    def test_forbidden_submission_terms_fail_report(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")

            with mock.patch("fitz.open", return_value=_ForbiddenSubmissionTermDocument()):
                report = check_pdf_visual(pdf_path, work_dir)

        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"]["submission_anonymity"]["passed"])
        self.assertEqual(
            report["checks"]["submission_anonymity"]["occurrences"][0]["page"], 2
        )

    def test_default_editorial_policy_warns_without_breaking_legacy_export(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")

            with mock.patch("fitz.open", return_value=_EditorialQualityDocument()):
                report = check_pdf_visual(pdf_path, work_dir)

        quality = report["checks"]["editorial_quality"]
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(quality["blocking"])
        self.assertFalse(quality["official_rule"])
        self.assertEqual(quality["scope"], "internal_editorial_non_official")
        self.assertTrue(quality["warnings"])
        self.assertFalse(quality["checkpoints"]["abstract_page_density"]["passed"])
        self.assertTrue(quality["checkpoints"]["body_page_range"]["passed"])

    def test_strict_editorial_policy_blocks_content_quality_risks(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")

            with mock.patch("fitz.open", return_value=_EditorialQualityDocument()):
                report = check_pdf_visual(
                    pdf_path,
                    work_dir,
                    quality_policy=CUMCM2026_STRICT_EDITORIAL_QUALITY_POLICY,
                )

        quality = report["checks"]["editorial_quality"]
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(quality["blocking"])
        self.assertFalse(quality["passed"])
        self.assertFalse(quality["official_rule"])

    def test_strict_editorial_policy_detects_sparse_abstract_page_geometry(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")

            with mock.patch("fitz.open", return_value=_LowCoverageAbstractDocument()):
                report = check_pdf_visual(
                    pdf_path,
                    work_dir,
                    quality_policy=CUMCM2026_STRICT_EDITORIAL_QUALITY_POLICY,
                )

        density = report["checks"]["editorial_quality"]["checkpoints"][
            "abstract_page_density"
        ]
        self.assertEqual(report["status"], "FAIL")
        self.assertGreaterEqual(density["abstract_characters"], 450)
        self.assertTrue(density["geometry_assessed"])
        self.assertLess(density["text_coverage_ratio"], density["min_text_coverage_ratio"])

    def test_strict_editorial_policy_allows_dense_abstract_and_ten_body_pages(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")

            with mock.patch("fitz.open", return_value=_HighDensityAbstractDocument()):
                report = check_pdf_visual(
                    pdf_path,
                    work_dir,
                    quality_policy=CUMCM2026_STRICT_EDITORIAL_QUALITY_POLICY,
                )

        quality = report["checks"]["editorial_quality"]
        density = quality["checkpoints"]["abstract_page_density"]
        body_range = quality["checkpoints"]["body_page_range"]
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(quality["passed"])
        self.assertTrue(density["passed"])
        self.assertTrue(body_range["passed"])
        self.assertEqual(body_range["body_pages_after_abstract"], 10)

    def test_unknown_editorial_policy_fails_instead_of_claiming_pass(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")

            with mock.patch("fitz.open", return_value=_FakeDocument()):
                report = check_pdf_visual(
                    pdf_path, work_dir, quality_policy="not-a-policy"
                )

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("未知", report["checks"]["editorial_quality"]["error"])

    def test_literal_markdown_heading_in_body_fails_visual_check(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 fake")

            with mock.patch("fitz.open", return_value=_LiteralMarkdownHeadingDocument()):
                report = check_pdf_visual(pdf_path, work_dir)

        self.assertEqual(report["status"], "FAIL")
        leakage = report["checks"]["literal_markdown_headings"]
        self.assertFalse(leakage["passed"])
        self.assertEqual(leakage["issues"][0]["page"], 2)


if __name__ == "__main__":
    unittest.main()
