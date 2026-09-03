"""Regression coverage for the strict technical/final-human acceptance split."""

import hashlib
import json
import os
import tempfile
import unittest

from app.tools.candidate_exporter import write_candidate_manifest
from app.tools.final_acceptance import audit_final_acceptance, write_final_acceptance_report
from app.tools.paper_postprocessor import append_code_appendix


def _write_json(work_dir: str, name: str, value: dict) -> None:
    with open(os.path.join(work_dir, name), "w", encoding="utf-8") as handle:
        json.dump(value, handle)


def _read_json(work_dir: str, name: str) -> dict:
    with open(os.path.join(work_dir, name), encoding="utf-8") as handle:
        return json.load(handle)


def _prepare_technical_fixture(work_dir: str) -> None:
    source = "def solve():\n    return 2200\n"
    with open(os.path.join(work_dir, "solve.py"), "w", encoding="utf-8") as handle:
        handle.write(source)
    with open(os.path.join(work_dir, "solve.py"), "rb") as handle:
        source_hash = hashlib.sha256(handle.read()).hexdigest()
    markdown, _ = append_code_appendix("# 论文\n\n正文。", work_dir)
    with open(os.path.join(work_dir, "res.md"), "w", encoding="utf-8") as handle:
        handle.write(markdown)
    for name in ("res.json", "res.docx", "res.pdf"):
        with open(os.path.join(work_dir, name), "w", encoding="utf-8") as handle:
            handle.write("ok")
    with open(os.path.join(work_dir, "res.md"), "rb") as handle:
        md_hash = hashlib.sha256(handle.read()).hexdigest()
    with open(os.path.join(work_dir, "res.docx"), "rb") as handle:
        docx_hash = hashlib.sha256(handle.read()).hexdigest()
    with open(os.path.join(work_dir, "res.pdf"), "rb") as handle:
        pdf_hash = hashlib.sha256(handle.read()).hexdigest()
    _write_json(work_dir, "execution_validation_report.json", {"status": "PASS"})
    _write_json(
        work_dir,
        "paper_preflight_report.json",
        {"status": "PASS", "source_sha256": md_hash},
    )
    _write_json(
        work_dir,
        "pdf_visual_check.json",
        {
            "status": "PASS",
            "pdf_sha256": pdf_hash,
            "scan_scope": "all_pages",
            "pages_checked": 1,
            "page_count": 1,
        },
    )
    _write_json(
        work_dir,
        "export_status.json",
        {
            "pdf": {
                "success": True,
                "source_sha256": md_hash,
                "output_sha256": pdf_hash,
                "font_resolution": [
                    {
                        "preferred": "Times New Roman",
                        "actual": "Times New Roman",
                        "source": "profile",
                    }
                ],
            }
        },
    )
    _write_json(
        work_dir,
        "docx_export_status.json",
        {
            "success": True,
            "source_sha256": md_hash,
            "output_sha256": docx_hash,
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
    _write_json(work_dir, "submission_audit_report.json", {"status": "PASS"})
    write_candidate_manifest(work_dir, "task-fixture")


class FinalAcceptanceTest(unittest.TestCase):
    def test_only_explicit_default_accepts_conditions_and_keeps_warnings(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _prepare_technical_fixture(work_dir)
            for profile in ("default", "cumcm2025", "cumcm2026", "huashubei", "unknown", ""):
                with self.subTest(profile=profile):
                    export = _read_json(work_dir, "export_status.json")
                    export["export_profile"] = profile
                    _write_json(work_dir, "export_status.json", export)
                    _write_json(work_dir, "paper_preflight_report.json", {"status": "CONDITIONAL_PASS"})
                    _write_json(work_dir, "submission_audit_report.json", {"status": "WARN"})
                    report = audit_final_acceptance(work_dir)
                    checks = {item["id"]: item for item in report["checks"]}
                    for key in ("paper_preflight_report", "submission_audit_report"):
                        self.assertEqual(checks[key]["passed"], profile == "default")
                        if profile == "default":
                            self.assertEqual(checks[key]["severity"], "warning")
                    self.assertEqual(report["human_review"]["status"], "PENDING_HUMAN_REVIEW")

    def test_default_never_accepts_hard_failure_or_missing_reports(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _prepare_technical_fixture(work_dir)
            export = _read_json(work_dir, "export_status.json")
            export["export_profile"] = "default"
            _write_json(work_dir, "export_status.json", export)
            for name in ("paper_preflight_report.json", "submission_audit_report.json"):
                for status in ("FAIL", "unknown", None):
                    with self.subTest(name=name, status=status):
                        if status is None:
                            os.remove(os.path.join(work_dir, name))
                        else:
                            _write_json(work_dir, name, {"status": status})
                        report = audit_final_acceptance(work_dir)
                        check = next(c for c in report["checks"] if c["id"] == name[:-5])
                        self.assertFalse(check["passed"])
                        self.assertNotIn("已通过", check["message"])
                        self.assertEqual(report["technical_status"], "TECHNICAL_FAIL")

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

    def test_formal_profile_rejects_legacy_pass_reports_without_editorial_gate(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _prepare_technical_fixture(work_dir)
            export_status = _read_json(work_dir, "export_status.json")
            export_status["export_profile"] = "cumcm2026"
            _write_json(work_dir, "export_status.json", export_status)

            report = audit_final_acceptance(work_dir)

            self.assertEqual(report["technical_status"], "TECHNICAL_FAIL")
            editorial = next(
                item for item in report["checks"] if item["id"] == "editorial_quality_gate"
            )
            self.assertFalse(editorial["passed"])

    def test_formal_profile_accepts_explicit_strict_editorial_reports(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _prepare_technical_fixture(work_dir)
            preflight = _read_json(work_dir, "paper_preflight_report.json")
            preflight["checks"] = {
                "editorial_quality": {
                    "passed": True,
                    "quality_passed": True,
                    "enforced": True,
                    "policy": "cumcm_formal",
                    "official_rule": False,
                }
            }
            _write_json(work_dir, "paper_preflight_report.json", preflight)
            visual = _read_json(work_dir, "pdf_visual_check.json")
            visual["checks"] = {
                "editorial_quality": {
                    "passed": True,
                    "blocking": True,
                    "policy": "cumcm2026_strict",
                    "official_rule": False,
                }
            }
            _write_json(work_dir, "pdf_visual_check.json", visual)
            export_status = _read_json(work_dir, "export_status.json")
            export_status["export_profile"] = "cumcm2026"
            _write_json(work_dir, "export_status.json", export_status)

            report = audit_final_acceptance(work_dir)

            self.assertEqual(report["technical_status"], "TECHNICAL_PASS")
            editorial = next(
                item for item in report["checks"] if item["id"] == "editorial_quality_gate"
            )
            self.assertTrue(editorial["passed"])


if __name__ == "__main__":
    unittest.main()
