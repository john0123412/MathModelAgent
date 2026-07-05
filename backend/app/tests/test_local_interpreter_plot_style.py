"""Local interpreter plot style tests."""

import tempfile
import unittest
from unittest import mock

from app.tools.local_interpreter import LocalCodeInterpreter


class TestLocalInterpreterPlotStyle(unittest.TestCase):
    """Ensure generated matplotlib images keep Chinese fonts readable."""

    def test_pre_execute_installs_savefig_font_hook(self):
        with tempfile.TemporaryDirectory() as work_dir:
            interpreter = LocalCodeInterpreter(
                task_id="unit-test",
                work_dir=work_dir,
                notebook_serializer=mock.Mock(),
            )

            with mock.patch.object(
                interpreter, "execute_code_", return_value=[]
            ) as execute_mock:
                interpreter._pre_execute_code()

        init_code = execute_mock.call_args.args[0]
        self.assertIn("def _mma_apply_chinese_plot_style()", init_code)
        self.assertIn("_mma_original_plt_savefig", init_code)
        self.assertIn("_mma_savefig_with_style", init_code)
        self.assertIn("plt.savefig = _mma_savefig_with_style", init_code)
        self.assertIn("matplotlib.figure.Figure.savefig = _mma_figure_savefig_with_style", init_code)


if __name__ == "__main__":
    unittest.main()
