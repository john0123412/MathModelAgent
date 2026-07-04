"""PDF template command tests."""

import os
import tempfile
import unittest
from unittest import mock

from app.schemas.enums import ExportProfile
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
                # 字体是否已安装依赖运行测试的宿主机状态（Windows 本机可能装了
                # Times New Roman/SimSun，Docker 容器则没有），这里固定为
                # "已安装"，让断言的命令内容与宿主机字体状态无关。
                mock.patch("app.utils.font_utils.check_font_installed", return_value=True),
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

    def test_pdf_command_cumcm2025_profile_adds_toc_and_number_sections(self):
        """cumcm2025 profile 在默认变量基础上追加目录/章节编号，且不影响默认 profile。"""
        with tempfile.TemporaryDirectory() as work_dir:
            md_path = os.path.join(work_dir, "res.md")
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write("# 测试标题\n\n摘要 测试正文。")

            proc = mock.Mock(returncode=1, stderr="expected test failure")
            with (
                mock.patch("shutil.which", return_value="tool"),
                mock.patch("subprocess.run", return_value=proc) as run_mock,
                mock.patch("app.utils.font_utils.check_font_installed", return_value=True),
            ):
                export_markdown_to_pdf(
                    md_path, pdf_path, work_dir, export_profile=ExportProfile.CUMCM2025
                )

        command = run_mock.call_args.args[0]
        self.assertIn("--toc", command)
        self.assertIn("--number-sections", command)
        self.assertIn("documentclass=ctexart", command)
        self.assertIn("geometry:left=3.17cm,right=3.17cm,top=3cm,bottom=2.5cm", command)


if __name__ == "__main__":
    unittest.main()
