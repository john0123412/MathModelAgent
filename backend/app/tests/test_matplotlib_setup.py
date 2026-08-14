"""Shared matplotlib kernel bootstrap tests."""

import tempfile
import unittest

from app.tools.matplotlib_setup import build_matplotlib_init_code


class MatplotlibSetupTest(unittest.TestCase):
    def test_e2b_posix_paths_are_not_rewritten_by_windows_host(self):
        code = build_matplotlib_init_code(
            "/home/user",
            font_dir="/home/user",
        )

        self.assertIn("work_dir = '/home/user'", code)
        self.assertIn("_font_dir = '/home/user'", code)
        compile(code, "<matplotlib-init>", "exec")

    def test_local_bootstrap_injects_shared_plot_constants(self):
        with tempfile.TemporaryDirectory() as work_dir:
            code = build_matplotlib_init_code(work_dir)

        self.assertIn("COLORS =", code)
        self.assertIn("FIG_SINGLE =", code)
        self.assertIn("FIG_DOUBLE =", code)
        self.assertIn("FIG_WIDE =", code)
        self.assertIn("FIG_SQUARE =", code)
        compile(code, "<matplotlib-init>", "exec")


if __name__ == "__main__":
    unittest.main()
