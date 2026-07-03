"""PDF template command tests."""

import os
import tempfile
import unittest
from unittest import mock

from app.tools.pdf_exporter import export_markdown_to_pdf


class TestPdfTemplateCommand(unittest.TestCase):
    """Ensure generated PDFs follow the reference paper layout contract."""

    def test_pdf_command_matches_reference_template_defaults(self):
        with tempfile.TemporaryDirectory() as work_dir:
            md_path = os.path.join(work_dir, "res.md")
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write("# 测试标题\n\n摘要 测试正文。")

            proc = mock.Mock(returncode=1, stderr="expected test failure")
            with (
                mock.patch("shutil.which", return_value="tool"),
                mock.patch("subprocess.run", return_value=proc) as run_mock,
            ):
                export_markdown_to_pdf(md_path, pdf_path, work_dir)

        command = run_mock.call_args.args[0]
        self.assertIn("--standalone", command)
        self.assertIn("--pdf-engine=xelatex", command)
        self.assertIn("documentclass=ctexart", command)
        self.assertIn("papersize=a4", command)
        self.assertIn("CJKmainfont=SimSun", command)
        self.assertIn("CJKsansfont=SimHei", command)
        self.assertIn("mainfont=Times New Roman", command)
        self.assertIn("pagestyle=plain", command)
        self.assertTrue(
            any("header-includes=" in item and r"\heiti" in item for item in command)
        )
        self.assertIn("geometry:left=3.17cm,right=3.17cm,top=2.6cm,bottom=2.6cm", command)
        self.assertNotIn("--toc", command)
        self.assertNotIn("--number-sections", command)


if __name__ == "__main__":
    unittest.main()
