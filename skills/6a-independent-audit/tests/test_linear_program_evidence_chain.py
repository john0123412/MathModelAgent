from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parents[2]
GUARD = SKILLS_ROOT / "1start-mathmodel" / "scripts" / "workflow_guard.py"
FREEZE = SKILLS_ROOT / "3a-result-freeze" / "scripts" / "freeze_results.py"
AUDIT = SKILLS_ROOT / "6a-independent-audit" / "scripts" / "independent_audit.py"


class LinearProgramEvidenceChainSmokeTests(unittest.TestCase):
    """Exercise the P2 skills on the repository's documented LP smoke case."""

    def _run(self, workspace: Path, script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), "--workspace", ".", *arguments],
            cwd=workspace,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

    def test_real_linear_program_evidence_chain_recovers_after_stale_source(self) -> None:
        # 2A + B = 100 and A + 2B = 80 give the feasible optimum A=40, B=20.
        a = Fraction(40)
        b = Fraction(20)
        profit = 40 * a + 30 * b
        profit_plus_10_machine = Fraction(7100, 3)
        self.assertEqual(profit, 2200)
        self.assertLessEqual(2 * a + b, 100)
        self.assertLessEqual(a + 2 * b, 80)

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            reports = workspace / "reports"
            results = workspace / "results"
            paper = workspace / "paper"
            reports.mkdir()
            results.mkdir()
            paper.mkdir()

            (reports / "ANALYSIS_MODELING_REPORT.md").write_text(
                "资源分配优化：最大化 40A + 30B，受机器和人工约束。\n",
                encoding="utf-8",
            )
            (reports / "METHOD_VALIDATION.md").write_text(
                "LP PoC：约束可行，交点 A=40、B=20。\n",
                encoding="utf-8",
            )
            (reports / "METHOD_SELECTION.md").write_text(
                "# Method selection\n\nStatus: SELECTED\n\n## Human decision\n"
                "- Selected candidate: linear-programming\n- Reviewer: smoke-test\n"
                "- Date: 2026-07-13\n"
                "- Rationale: 线性目标和约束满足 LP 条件，PoC 的交点满足两个资源约束。\n",
                encoding="utf-8",
            )
            (reports / "RESULTS_REPORT.md").write_text(
                "最优解 A=40，B=20，利润为 2200 元；机器时间增加 10 小时后利润为 2366.6667 元。\n",
                encoding="utf-8",
            )
            summary = results / "linear_program_summary.csv"
            original_summary = (
                "product,quantity\nA,40\nB,20\n"
                "metric,value\nprofit,2200\nprofit_machine_plus_10,2366.6666666667\n"
            )
            summary.write_text(original_summary, encoding="utf-8")
            (reports / "key_metrics.json").write_text(
                json.dumps(
                    {
                        "metrics": [
                            {
                                "id": "optimal_profit",
                                "value": int(profit),
                                "unit": "yuan",
                                "explanation": "A=40、B=20 时的最大利润",
                            },
                            {
                                "id": "profit_machine_plus_10",
                                "value": float(profit_plus_10_machine),
                                "unit": "yuan",
                                "explanation": "机器时间增加 10 小时后的最优利润",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            before_freeze = self._run(workspace, GUARD)
            self.assertEqual(before_freeze.returncode, 0, before_freeze.stderr)
            self.assertEqual(json.loads(before_freeze.stdout)["recommended_skill"], "3a-result-freeze")

            frozen = self._run(
                workspace,
                FREEZE,
                "--metrics",
                "reports/key_metrics.json",
                "--source",
                "reports/RESULTS_REPORT.md",
                "--source",
                "results/linear_program_summary.csv",
                "--output",
                "reports/frozen_numbers.json",
            )
            self.assertEqual(frozen.returncode, 0, frozen.stderr)

            after_freeze = self._run(workspace, GUARD)
            self.assertEqual(after_freeze.returncode, 0, after_freeze.stderr)
            self.assertEqual(json.loads(after_freeze.stdout)["recommended_skill"], "4drawio")

            (reports / "DRAWIO_REPORT.md").write_text("无需额外非数据图。\n", encoding="utf-8")
            (paper / "main.tex").write_text("\\section{结果}\n最优利润为 2200 元。\n", encoding="utf-8")
            audited = self._run(workspace, AUDIT, "--paper", "paper/main.tex")
            self.assertEqual(audited.returncode, 0, audited.stderr)
            self.assertEqual(json.loads(audited.stdout)["status"], "PASS")

            before_verification = self._run(workspace, GUARD)
            self.assertEqual(before_verification.returncode, 0, before_verification.stderr)
            self.assertEqual(json.loads(before_verification.stdout)["recommended_skill"], "6verity")

            summary.write_text(original_summary.replace("2200", "2201", 1), encoding="utf-8")
            stale_freeze = self._run(
                workspace,
                FREEZE,
                "--verify",
                "--output",
                "reports/frozen_numbers.json",
            )
            self.assertNotEqual(stale_freeze.returncode, 0)
            self.assertEqual(json.loads(stale_freeze.stdout)["status"], "FAIL")
            stale_audit = self._run(workspace, AUDIT)
            self.assertNotEqual(stale_audit.returncode, 0)
            self.assertEqual(json.loads(stale_audit.stdout)["status"], "FAIL")

            summary.write_text(original_summary, encoding="utf-8")
            recovered_freeze = self._run(
                workspace,
                FREEZE,
                "--verify",
                "--output",
                "reports/frozen_numbers.json",
            )
            self.assertEqual(recovered_freeze.returncode, 0, recovered_freeze.stderr)
            recovered_audit = self._run(workspace, AUDIT, "--paper", "paper/main.tex")
            self.assertEqual(recovered_audit.returncode, 0, recovered_audit.stderr)
            self.assertEqual(json.loads(recovered_audit.stdout)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
