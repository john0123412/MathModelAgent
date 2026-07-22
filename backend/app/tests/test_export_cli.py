import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from app.tools import export_cli


class TestExportCliCheck(unittest.TestCase):
    def test_check_prints_fallback_conclusion_when_fonts_are_missing(self):
        stdout = io.StringIO()
        with (
            mock.patch("app.tools.export_cli.shutil.which", return_value="tool"),
            mock.patch("app.tools.export_cli.check_font_installed", return_value=False),
            redirect_stdout(stdout),
        ):
            exit_code = export_cli.cmd_check(mock.Mock())

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("=== 环境结论 ===", output)
        self.assertIn("可以导出但会 fallback", output)

    def test_check_prints_blocking_conclusion_when_tools_are_missing(self):
        stdout = io.StringIO()
        with (
            mock.patch("app.tools.export_cli.shutil.which", return_value=None),
            mock.patch("app.tools.export_cli.check_font_installed", return_value=True),
            redirect_stdout(stdout),
        ):
            exit_code = export_cli.cmd_check(mock.Mock())

        self.assertEqual(exit_code, 1)
        output = stdout.getvalue()
        self.assertIn("=== 环境结论 ===", output)
        self.assertIn("缺 pandoc/xelatex，不能导出", output)


class TestExportCliPdf(unittest.TestCase):
    def test_pdf_update_status_refreshes_reports(self):
        with tempfile.TemporaryDirectory() as work_dir:
            output_path = os.path.join(work_dir, "res.pdf")
            with open(os.path.join(work_dir, "candidate_manifest.json"), "w", encoding="utf-8") as f:
                json.dump({"task_id": "task-1"}, f)
            args = mock.Mock(
                input=os.path.join(work_dir, "res.md"),
                output=output_path,
                work_dir=work_dir,
                profile="cumcm2026",
                local=False,
                update_status=True,
                font_config=None,
                mainfont=None,
                monofont=None,
                sansfont=None,
                cjk_mainfont=None,
                cjk_sansfont=None,
                cjk_monofont=None,
            )

            pdf_result = {"success": True, "pdf_path": output_path, "font_resolution": []}
            with (
                mock.patch("app.tools.export_cli.shutil.which", return_value="tool"),
                mock.patch("app.tools.export_cli.export_markdown_to_pdf", return_value=pdf_result),
                mock.patch("app.tools.export_cli.check_pdf_visual", return_value={"status": "PASS"}),
                mock.patch("app.tools.export_cli.write_submission_audit_report") as audit_mock,
                mock.patch("app.tools.export_cli.write_candidate_manifest") as manifest_mock,
                mock.patch(
                    "app.tools.export_cli.write_final_acceptance_report",
                    return_value={"technical_status": "TECHNICAL_PASS"},
                ) as final_mock,
                mock.patch("app.tools.export_cli.write_task_status_to_dir") as status_mock,
            ):
                exit_code = export_cli.cmd_pdf(args)

            self.assertEqual(exit_code, 0)
            with open(os.path.join(work_dir, "export_status.json"), encoding="utf-8") as f:
                status = json.load(f)
            self.assertEqual(status["export_profile"], "cumcm2026")
            self.assertEqual(status["pdf"], pdf_result)
            self.assertEqual(status["pdf_visual_check"], {"status": "PASS"})
            audit_mock.assert_called_once_with(work_dir)
            manifest_mock.assert_called_once_with(work_dir, "task-1")
            final_mock.assert_called_once_with(work_dir)
            status_mock.assert_called_once_with(
                work_dir, "task-1", "completed", "任务处理完成"
            )


class TestExportCliLatex(unittest.TestCase):
    def test_manual_latex_instructions_disable_shell_escape(self):
        stdout = io.StringIO()
        args = mock.Mock(input="res.md", work_dir="work", profile="cumcm2026")
        result = {
            "success": True,
            "latex_project_dir": "latex_project",
            "main_tex": "latex_project/main.tex",
            "compile_attempted": False,
            "compile_success": False,
            "compile_reason": "未检测到编译器",
        }
        with (
            mock.patch("app.tools.export_cli.shutil.which", return_value="pandoc"),
            mock.patch(
                "app.tools.export_cli.export_markdown_to_latex_project",
                return_value=result,
            ),
            redirect_stdout(stdout),
        ):
            exit_code = export_cli.cmd_latex(args)

        self.assertEqual(exit_code, 0)
        self.assertIn("xelatex -no-shell-escape", stdout.getvalue())
