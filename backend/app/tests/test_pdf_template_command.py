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
        self.assertIn("--listings", command)
        self.assertIn("--pdf-engine=xelatex", command)
        self.assertIn(
            "markdown-raw_tex+tex_math_dollars+tex_math_single_backslash+pipe_tables",
            command,
        )
        self.assertIn("documentclass=ctexart", command)
        self.assertIn("papersize=a4", command)
        self.assertIn("CJKmainfont=SimSun", command)
        self.assertIn("CJKsansfont=SimHei", command)
        self.assertIn("mainfont=Times New Roman", command)
        self.assertIn("pagestyle=plain", command)
        self.assertTrue(
            any("header-includes=" in item and r"\heiti" in item for item in command)
        )
        self.assertTrue(
            any("header-includes=" in item and "breaklines=true" in item for item in command)
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

    def test_pdf_command_cumcm2026_profile_has_no_toc_or_auto_numbering(self):
        """cumcm2026 避免对已手写编号的 Markdown 标题二次自动编号。"""
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
                    md_path, pdf_path, work_dir, export_profile=ExportProfile.CUMCM2026
                )

        command = run_mock.call_args.args[0]
        self.assertNotIn("--number-sections", command)
        self.assertNotIn("--toc", command)
        self.assertIn("documentclass=ctexart", command)
        self.assertIn("geometry:left=3.17cm,right=3.17cm,top=3cm,bottom=2.8cm", command)

    def test_pdf_input_inserts_pagebreak_after_keywords_without_touching_res_md(self):
        with tempfile.TemporaryDirectory() as work_dir:
            md_path = os.path.join(work_dir, "res.md")
            pdf_path = os.path.join(work_dir, "res.pdf")
            original_markdown = (
                "# 题目\n\n"
                "## 摘要\n\n"
                "摘要正文。\n\n"
                "关键词：线性规划；生产优化\n\n"
                "# 一、问题重述\n\n"
                "生产资源分配优化是制造业管理中的经典问题，旨在有限资源约束下确定最优生产方案以实现利润最大化。"
                "随着市场竞争加剧，企业对资源配置效率的要求日益提高。\n\n"
                "```python\n"
                "print('生产资源分配优化是制造业管理中的经典问题')\n"
                "```\n"
            )
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(original_markdown)

            captured = {}

            def fake_run(command, **kwargs):
                with open(command[1], encoding="utf-8") as f:
                    captured["pdf_markdown"] = f.read()
                captured["command"] = command
                return mock.Mock(returncode=1, stderr="expected test failure")

            with (
                mock.patch("shutil.which", return_value="tool"),
                mock.patch("subprocess.run", side_effect=fake_run),
                mock.patch("app.utils.font_utils.check_font_installed", return_value=True),
            ):
                export_markdown_to_pdf(
                    md_path, pdf_path, work_dir, export_profile=ExportProfile.CUMCM2026
                )

            with open(md_path, encoding="utf-8") as f:
                self.assertEqual(f.read(), original_markdown)
            self.assertIn("MMA_PDF_PAGEBREAK", captured["pdf_markdown"])
            self.assertIn("MMA_PDF_CJK_BREAK", captured["pdf_markdown"])
            self.assertIn(
                "print('生产资源分配优化是制造业管理中的经典问题')",
                captured["pdf_markdown"],
            )
            self.assertNotRegex(
                captured["pdf_markdown"],
                r"print\('.*MMA_PDF_CJK_BREAK.*'\)",
            )
            self.assertLess(
                captured["pdf_markdown"].index("MMA_PDF_PAGEBREAK"),
                captured["pdf_markdown"].index("# 一、问题重述"),
            )
            self.assertIn("--lua-filter", captured["command"])

    def test_pdf_input_inserts_pagebreak_after_bold_inline_keywords(self):
        with tempfile.TemporaryDirectory() as work_dir:
            md_path = os.path.join(work_dir, "res.md")
            pdf_path = os.path.join(work_dir, "res.pdf")
            original_markdown = (
                "# 题目\n\n"
                "## 摘要\n\n"
                "摘要正文。\n\n"
                "**关键词**：线性规划；生产优化\n\n"
                "# 一、问题重述\n\n"
                "正文。\n"
            )
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(original_markdown)

            captured = {}

            def fake_run(command, **kwargs):
                with open(command[1], encoding="utf-8") as f:
                    captured["pdf_markdown"] = f.read()
                return mock.Mock(returncode=1, stderr="expected test failure")

            with (
                mock.patch("shutil.which", return_value="tool"),
                mock.patch("subprocess.run", side_effect=fake_run),
                mock.patch("app.utils.font_utils.check_font_installed", return_value=True),
            ):
                export_markdown_to_pdf(
                    md_path, pdf_path, work_dir, export_profile=ExportProfile.CUMCM2026
                )

            self.assertIn("MMA_PDF_PAGEBREAK", captured["pdf_markdown"])
            self.assertLess(
                captured["pdf_markdown"].index("MMA_PDF_PAGEBREAK"),
                captured["pdf_markdown"].index("# 一、问题重述"),
            )

    def test_pdf_command_huashubei_profile_uses_confirmed_margin_baseline(self):
        """huashubei profile 先按国赛基线 2.5cm 接入，等待官方规范发布后复核。"""
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
                    md_path, pdf_path, work_dir, export_profile=ExportProfile.HUASHUBEI
                )

        command = run_mock.call_args.args[0]
        self.assertIn("documentclass=ctexart", command)
        self.assertIn("geometry:left=2.5cm,right=2.5cm,top=2.5cm,bottom=2.5cm", command)
        self.assertIn("fontsize=12pt", command)
        self.assertIn("linestretch=1.6", command)
        self.assertTrue(
            any(r"\fontsize{14pt}{16.8pt}" in item and r"\centering" in item for item in command)
        )
        self.assertNotIn("--toc", command)

    def test_pdf_result_records_font_resolution_fallbacks(self):
        with tempfile.TemporaryDirectory() as work_dir:
            md_path = os.path.join(work_dir, "res.md")
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write("# 测试标题\n\n摘要 测试正文。")

            proc = mock.Mock(returncode=1, stderr="expected test failure")
            with (
                mock.patch("shutil.which", return_value="tool"),
                mock.patch("subprocess.run", return_value=proc),
                mock.patch("app.utils.font_utils.check_font_installed", return_value=False),
            ):
                result = export_markdown_to_pdf(md_path, pdf_path, work_dir)

        resolution = {
            item["variable"]: item for item in result["font_resolution"]
        }
        self.assertEqual(resolution["mainfont"]["preferred"], "Times New Roman")
        self.assertEqual(resolution["mainfont"]["actual"], "Liberation Serif")
        self.assertEqual(resolution["mainfont"]["fallback"], "Liberation Serif")
        self.assertEqual(resolution["mainfont"]["source"], "fallback")
        self.assertEqual(resolution["CJKmainfont"]["actual"], "Noto Serif CJK SC")

    def test_pdf_result_records_font_resolution_overrides(self):
        with tempfile.TemporaryDirectory() as work_dir:
            md_path = os.path.join(work_dir, "res.md")
            pdf_path = os.path.join(work_dir, "res.pdf")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write("# 测试标题\n\n摘要 测试正文。")

            proc = mock.Mock(returncode=1, stderr="expected test failure")
            with (
                mock.patch("shutil.which", return_value="tool"),
                mock.patch("subprocess.run", return_value=proc),
                mock.patch("app.utils.font_utils.check_font_installed", return_value=True),
            ):
                result = export_markdown_to_pdf(
                    md_path,
                    pdf_path,
                    work_dir,
                    font_overrides={"mainfont": "Georgia", "CJKmonofont": "KaiTi"},
                    local_fonts=True,
                )

        resolution = {
            item["variable"]: item for item in result["font_resolution"]
        }
        self.assertEqual(resolution["mainfont"]["preferred"], "Times New Roman")
        self.assertEqual(resolution["mainfont"]["actual"], "Georgia")
        self.assertIsNone(resolution["mainfont"]["fallback"])
        self.assertEqual(resolution["mainfont"]["source"], "override")
        self.assertEqual(resolution["CJKmonofont"]["actual"], "KaiTi")
        self.assertEqual(resolution["CJKmonofont"]["source"], "override")


if __name__ == "__main__":
    unittest.main()
