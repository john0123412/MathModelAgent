import io
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
