from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "workflow_guard.py"


class WorkflowGuardTests(unittest.TestCase):
    def _run(self, workspace: Path) -> dict:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--workspace", "."],
            cwd=workspace,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_empty_workspace_starts_at_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = self._run(Path(temporary))
            self.assertEqual(report["current_stage"], "analysis-modeling")
            self.assertEqual(report["recommended_skill"], "2analysis-modeling")
            self.assertEqual(report["evidence_chain"], "not_enabled")

    def test_frozen_results_advance_to_drawio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            reports = workspace / "reports"
            reports.mkdir()
            for name in (
                "ANALYSIS_MODELING_REPORT.md",
                "METHOD_VALIDATION.md",
                "METHOD_SELECTION.md",
                "RESULTS_REPORT.md",
                "frozen_numbers.json",
            ):
                (reports / name).write_text("ok", encoding="utf-8")
            report = self._run(workspace)
            self.assertEqual(report["current_stage"], "drawio")
            self.assertEqual(report["recommended_skill"], "4drawio")
            self.assertEqual(report["evidence_chain"], "active")


if __name__ == "__main__":
    unittest.main()
