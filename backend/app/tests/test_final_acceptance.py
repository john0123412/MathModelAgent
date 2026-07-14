"""Regression coverage for the strict technical/final-human acceptance split."""

import hashlib
import json
import os
import tempfile
import unittest

from app.tools.final_acceptance import audit_final_acceptance, write_final_acceptance_report
from app.tools.paper_postprocessor import append_code_appendix


def _write_json(work_dir: str, name: str, value: dict) -> None:
    with open(os.path.join(work_dir, name), "w", encoding="utf-8") as handle:
        json.dump(value, handle)


def _prepare_technical_fixture(work_dir: str) -> None:
    source = "def solve():\n    return 2200\n"
    with open(os.path.join(work_dir, "solve.py"), "w", encoding="utf-8") as handle:
        handle.write(source)
    with open(os.path.join(work_dir, "solve.py"), "rb") as handle:
        source_hash = hashlib.sha256(handle.read()).hexdigest()
    markdown, _ = append_code_appendix("# 论文\n\n正文。", work_dir)
    with open(os.path.join(work_dir, "res.md"), "w", encoding="utf-8") as handle:
        handle.write(markdown)
    for name in ("res.json", "res.docx", "res.pdf", "candidate_manifest.json"):
        with open(os.path.join(work_dir, name), "w", encoding="utf-8") as handle:
            handle.write("ok")
    _write_json(work_dir, "execution_validation_report.json", {"status": "PASS"})
    _write_json(work_dir, "paper_preflight_report.json", {"status": "PASS"})
    _write_json(work_dir, "pdf_visual_check.json", {"status": "PASS"})
    _write_json(
        work_dir,
        "export_status.json",
        {
            "pdf": {
                "font_resolution": [
                    {
                        "preferred": "Times New Roman",
                        "actual": "Times New Roman",
                        "source": "profile",
                    }
                ]
            }
        },
    )
    _write_json(
        work_dir,
        "frozen_results.json",
        {
            "schema": "mathmodel.result-freeze",
            "version": 1,
            "metrics": [
                {
                    "id": "profit",
                    "label": "利润",
                    "value": 2200,
                    "unit": "元",
                    "explanation": "线性规划最优目标值",
                }
            ],
            "sources": [
                {
                    "relative_path": "solve.py",
                    "sha256": source_hash,
                    "role": "executed_code",
                }
            ],
            "subtasks": [{"id": "ques1", "feasible": True}],
        },
    )


class FinalAcceptanceTest(unittest.TestCase):
    def test_all_strict_checks_pass_but_human_review_remains_pending(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _prepare_technical_fixture(work_dir)
            report = write_final_acceptance_report(work_dir)

            self.assertEqual(report["technical_status"], "TECHNICAL_PASS")
            self.assertEqual(report["human_review"]["status"], "PENDING_HUMAN_REVIEW")
            self.assertTrue(os.path.isfile(os.path.join(work_dir, "final_acceptance_report.json")))

    def test_truncated_appendix_is_a_technical_failure(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _prepare_technical_fixture(work_dir)
            res_path = os.path.join(work_dir, "res.md")
            with open(res_path, encoding="utf-8") as handle:
                markdown = handle.read()
            with open(res_path, "w", encoding="utf-8") as handle:
                handle.write(markdown.replace("    return 2200", "    return"))

            report = audit_final_acceptance(work_dir)

            self.assertEqual(report["technical_status"], "TECHNICAL_FAIL")
            source_check = next(item for item in report["checks"] if item["id"] == "complete_source_appendix")
            self.assertFalse(source_check["passed"])

    def test_fallback_font_is_a_strict_technical_failure(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _prepare_technical_fixture(work_dir)
            _write_json(
                work_dir,
                "export_status.json",
                {
                    "pdf": {
                        "font_resolution": [
                            {
                                "preferred": "SimSun",
                                "actual": "Noto Serif CJK SC",
                                "source": "fallback",
                            }
                        ]
                    }
                },
            )

            report = audit_final_acceptance(work_dir)

            self.assertEqual(report["technical_status"], "TECHNICAL_FAIL")
            font_check = next(item for item in report["checks"] if item["id"] == "official_fonts")
            self.assertFalse(font_check["passed"])


if __name__ == "__main__":
    unittest.main()
