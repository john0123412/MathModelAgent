from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "independent_audit.py"
FREEZE_SCRIPT = SCRIPT.parents[2] / "3a-result-freeze" / "scripts" / "freeze_results.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class IndependentAuditTests(unittest.TestCase):
    def _workspace(self) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / "reports").mkdir()
        (root / "results").mkdir()
        source = root / "results" / "summary.csv"
        source.write_text("solution,profit\nA40B20,2200\n", encoding="utf-8")
        frozen = {
            "schema": "mathmodel.result-freeze",
            "version": 1,
            "metrics": [
                {
                    "id": "objective_value",
                    "value": 2200,
                    "unit": "yuan",
                    "explanation": "objective value from the solved model",
                }
            ],
            "sources": [
                {"relative_path": "results/summary.csv", "sha256": sha256(source), "role": "evidence"}
            ],
        }
        (root / "reports" / "frozen_numbers.json").write_text(json.dumps(frozen), encoding="utf-8")
        return temporary, root, source

    def _run(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--workspace", "."],
            cwd=root,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

    def test_audit_passes_valid_freeze(self) -> None:
        temporary, root, _ = self._workspace()
        with temporary:
            completed = self._run(root)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertEqual(report["status"], "PASS")
            self.assertTrue((root / "reports" / "independent_audit_report.md").is_file())

    def test_audit_fails_when_source_changes(self) -> None:
        temporary, root, source = self._workspace()
        with temporary:
            source.write_text("solution,profit\nA40B20,2300\n", encoding="utf-8")
            completed = self._run(root)
            self.assertNotEqual(completed.returncode, 0)
            report = json.loads(completed.stdout)
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("source_hash_changed", [check["code"] for check in report["checks"]])

    def test_audit_fails_incomplete_metric(self) -> None:
        temporary, root, _ = self._workspace()
        with temporary:
            path = root / "reports" / "frozen_numbers.json"
            frozen = json.loads(path.read_text(encoding="utf-8"))
            frozen["metrics"][0].pop("unit")
            path.write_text(json.dumps(frozen), encoding="utf-8")
            completed = self._run(root)
            self.assertNotEqual(completed.returncode, 0)
            report = json.loads(completed.stdout)
            self.assertIn("metric_semantics_incomplete", [check["code"] for check in report["checks"]])

    def test_audit_accepts_the_actual_result_freeze_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "reports").mkdir()
            (root / "results").mkdir()
            (root / "reports" / "key_metrics.json").write_text(
                json.dumps(
                    {
                        "metrics": [
                            {
                                "id": "objective_value",
                                "value": 2200,
                                "unit": "yuan",
                                "explanation": "objective value from the solved model",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (root / "results" / "summary.csv").write_text("profit\n2200\n", encoding="utf-8")
            frozen = subprocess.run(
                [
                    sys.executable,
                    str(FREEZE_SCRIPT),
                    "--workspace",
                    ".",
                    "--metrics",
                    "reports/key_metrics.json",
                    "--source",
                    "results/summary.csv",
                    "--output",
                    "reports/frozen_numbers.json",
                ],
                cwd=root,
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            self.assertEqual(frozen.returncode, 0, frozen.stderr)
            audited = self._run(root)
            self.assertEqual(audited.returncode, 0, audited.stderr)
            self.assertEqual(json.loads(audited.stdout)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
