from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "freeze_results.py"


class FreezeResultsTests(unittest.TestCase):
    def _create_workspace(self) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / "reports").mkdir()
        (root / "results").mkdir()
        metrics = {
            "metrics": [
                {
                    "id": "objective_value",
                    "value": 2200,
                    "unit": "yuan",
                    "explanation": "optimal production profit",
                }
            ]
        }
        (root / "reports" / "key_metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False),
            encoding="utf-8",
        )
        source = root / "results" / "summary.csv"
        source.write_text("product,amount\nA,40\nB,20\n", encoding="utf-8")
        return temporary, root, source

    def _run(self, root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            cwd=root,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

    def test_freeze_records_metrics_and_relative_source_hashes(self) -> None:
        temporary, root, _ = self._create_workspace()
        with temporary:
            completed = self._run(
                root,
                "--workspace",
                ".",
                "--metrics",
                "reports/key_metrics.json",
                "--source",
                "results/summary.csv",
                "--output",
                "reports/frozen_numbers.json",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["status"], "PASS")
            frozen = json.loads((root / "reports" / "frozen_numbers.json").read_text(encoding="utf-8"))
            self.assertEqual(frozen["schema"], "mathmodel.result-freeze")
            self.assertEqual(frozen["version"], 1)
            self.assertEqual(frozen["metrics"][0]["value"], 2200)
            self.assertEqual(
                [source["relative_path"] for source in frozen["sources"]],
                ["reports/key_metrics.json", "results/summary.csv"],
            )
            self.assertTrue(all(len(source["sha256"]) == 64 for source in frozen["sources"]))

    def test_verify_fails_after_source_changes(self) -> None:
        temporary, root, source = self._create_workspace()
        with temporary:
            frozen = self._run(
                root,
                "--workspace",
                ".",
                "--metrics",
                "reports/key_metrics.json",
                "--source",
                "results/summary.csv",
                "--output",
                "reports/frozen_numbers.json",
            )
            self.assertEqual(frozen.returncode, 0, frozen.stderr)
            source.write_text("product,amount\nA,41\nB,20\n", encoding="utf-8")

            verified = self._run(
                root,
                "--workspace",
                ".",
                "--verify",
                "--output",
                "reports/frozen_numbers.json",
            )

            self.assertNotEqual(verified.returncode, 0)
            result = json.loads(verified.stdout)
            self.assertEqual(result["status"], "FAIL")
            self.assertIn(
                "source_hash_changed",
                [check["code"] for check in result["checks"]],
            )


if __name__ == "__main__":
    unittest.main()
