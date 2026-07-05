"""PDF visual post-check tests."""

import json
import os
import tempfile
import unittest
from unittest import mock

from app.tools.pdf_visual_checker import check_pdf_visual


class _FakePage:
    rect = mock.Mock(width=595.0, height=842.0)

    def get_text(self, option=None):
        if option == "dict":
            return {"blocks": []}
        return "可提取文本"

    def get_pixmap(self, matrix=None, alpha=False):
        return mock.Mock(samples=b"\xff" * 64 + b"\x00" * 64)


class _LeadingWhitespacePage(_FakePage):
    def get_pixmap(self, matrix=None, alpha=False):
        return mock.Mock(samples=b"\xff" * 4096 + b"\x00" * 64)


class _OverflowPage(_FakePage):
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
        return "可提取文本"


class _FakeDocument:
    page_count = 2

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def __getitem__(self, index):
        return _FakePage()


class _LeadingWhitespaceDocument(_FakeDocument):
    def __getitem__(self, index):
        return _LeadingWhitespacePage()


class _OverflowDocument(_FakeDocument):
    page_count = 4

    def __getitem__(self, index):
        if index == 3:
            return _OverflowPage()
        return _FakePage()


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
            self.assertTrue(report["checks"]["a4_size"]["passed"])
            self.assertTrue(report["checks"]["text_extractable"]["passed"])
            self.assertTrue(report["checks"]["nonblank_pages"]["passed"])

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


if __name__ == "__main__":
    unittest.main()
