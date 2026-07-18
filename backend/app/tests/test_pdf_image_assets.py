"""Regression tests for PDF-only image validation and safe asset staging."""

import hashlib
import os
import tempfile
import unittest
from unittest import mock

from PIL import Image

from app.tools.pdf_exporter import export_markdown_to_pdf


def _write_png(path: str) -> None:
    Image.new("RGB", (1, 1), color="white").save(path, format="PNG")


def _sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


class TestPdfImageAssets(unittest.TestCase):
    def test_stages_special_names_without_mutating_sources_or_colliding(self):
        with tempfile.TemporaryDirectory() as work_dir:
            first_dir = os.path.join(work_dir, "甲")
            second_dir = os.path.join(work_dir, "乙")
            os.makedirs(first_dir)
            os.makedirs(second_dir)
            first = os.path.join(first_dir, "图 (最终版).png")
            second = os.path.join(second_dir, "图 (最终版).png")
            _write_png(first)
            _write_png(second)
            source_hashes = [_sha256(first), _sha256(second)]
            md_path = os.path.join(work_dir, "res.md")
            pdf_path = os.path.join(work_dir, "res.pdf")
            original_markdown = (
                "# 图表\n\n"
                "![第一张](甲/图 (最终版).png)\n\n"
                "![第二张](乙/图 (最终版).png)\n"
            )
            with open(md_path, "w", encoding="utf-8") as handle:
                handle.write(original_markdown)

            captured = {}

            def fake_run(command, **_kwargs):
                with open(command[1], encoding="utf-8") as handle:
                    captured["markdown"] = handle.read()
                return mock.Mock(returncode=1, stderr="expected failure")

            with (
                mock.patch("shutil.which", return_value="tool"),
                mock.patch("subprocess.run", side_effect=fake_run),
                mock.patch("app.utils.font_utils.check_font_installed", return_value=True),
            ):
                result = export_markdown_to_pdf(md_path, pdf_path, work_dir)

            self.assertFalse(result["success"])
            self.assertEqual(len(result["staged_assets"]), 2)
            self.assertIn("asset_001.png", captured["markdown"])
            self.assertIn("asset_002.png", captured["markdown"])
            self.assertNotIn("图 (最终版).png", captured["markdown"])
            with open(md_path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), original_markdown)
            self.assertEqual([_sha256(first), _sha256(second)], source_hashes)
            self.assertEqual(
                [],
                [name for name in os.listdir(work_dir) if name.startswith(".mma_pdf_")],
            )

    def test_rejects_zero_byte_image_before_pandoc(self):
        with tempfile.TemporaryDirectory() as work_dir:
            empty_image = os.path.join(work_dir, "空图.png")
            open(empty_image, "wb").close()
            md_path = os.path.join(work_dir, "res.md")
            with open(md_path, "w", encoding="utf-8") as handle:
                handle.write("![空图](空图.png)\n")

            with (
                mock.patch("shutil.which", return_value="tool"),
                mock.patch("subprocess.run") as run_mock,
            ):
                result = export_markdown_to_pdf(
                    md_path, os.path.join(work_dir, "res.pdf"), work_dir
                )

            self.assertFalse(result["enabled"])
            self.assertIn("图片资源校验失败", result["reason"])
            self.assertIn("0 字节", result["reason"])
            run_mock.assert_not_called()

    def test_rejects_missing_image_before_pandoc(self):
        with tempfile.TemporaryDirectory() as work_dir:
            md_path = os.path.join(work_dir, "res.md")
            with open(md_path, "w", encoding="utf-8") as handle:
                handle.write("![缺图](missing chart.png)\n")

            with (
                mock.patch("shutil.which", return_value="tool"),
                mock.patch("subprocess.run") as run_mock,
            ):
                result = export_markdown_to_pdf(
                    md_path, os.path.join(work_dir, "res.pdf"), work_dir
                )

            self.assertFalse(result["enabled"])
            self.assertIn("missing chart.png: 文件不存在", result["reason"])
            run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
