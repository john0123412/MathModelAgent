"""Submission audit report tests."""

import hashlib
import json
import os
import tempfile
import unittest

from app.tools.submission_audit import audit_submission, write_submission_audit_report


def _write_json(work_dir: str, filename: str, data: dict) -> None:
    with open(os.path.join(work_dir, filename), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _write_preflight(work_dir: str, status: str) -> None:
    _write_json(
        work_dir,
        "paper_preflight_report.json",
        {
            "status": status,
            "source_sha256": _sha256(os.path.join(work_dir, "res.md")),
        },
    )


def _write_required_success_files(work_dir: str, font_resolution: list[dict]) -> None:
    for filename in ["res.md", "res.json", "res.docx", "res.pdf"]:
        with open(os.path.join(work_dir, filename), "w", encoding="utf-8") as f:
            f.write("ok")
    _write_preflight(work_dir, "PASS")
    _write_json(work_dir, "execution_validation_report.json", {"status": "PASS"})
    _write_json(
        work_dir,
        "pdf_visual_check.json",
        {
            "status": "PASS",
            "pdf_sha256": _sha256(os.path.join(work_dir, "res.pdf")),
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
                "font_resolution": font_resolution,
            }
        },
    )


class TestSubmissionAudit(unittest.TestCase):
    def test_fallback_fonts_warn_for_preview_mode(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [
                    {
                        "variable": "mainfont",
                        "preferred": "Times New Roman",
                        "actual": "Liberation Serif",
                        "fallback": "Liberation Serif",
                        "source": "fallback",
                    }
                ],
            )

            report = audit_submission(work_dir)

        self.assertEqual(report["status"], "WARN")
        font_check = next(item for item in report["checks"] if item["id"] == "pdf_fonts")
        self.assertEqual(font_check["severity"], "warning")
        self.assertIn("MMA_OFFICIAL_FONTS_DIR", font_check["evidence"]["remediation"][0])

    def test_fallback_fonts_fail_when_official_fonts_are_required(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [
                    {
                        "variable": "CJKmainfont",
                        "preferred": "SimSun",
                        "actual": "Noto Serif CJK SC",
                        "fallback": "Noto Serif CJK SC",
                        "source": "fallback",
                    }
                ],
            )

            report = audit_submission(work_dir, require_official_fonts=True)

        self.assertEqual(report["status"], "FAIL")
        font_check = next(item for item in report["checks"] if item["id"] == "pdf_fonts")
        self.assertEqual(font_check["severity"], "error")

    def test_conditional_preflight_warns_instead_of_failing_submission_audit(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [
                    {
                        "variable": "mainfont",
                        "preferred": "Times New Roman",
                        "actual": "Times New Roman",
                        "fallback": "Liberation Serif",
                        "source": "profile",
                    }
                ],
            )
            _write_preflight(work_dir, "CONDITIONAL_PASS")

            report = audit_submission(work_dir)

        self.assertEqual(report["status"], "WARN")
        preflight_check = next(item for item in report["checks"] if item["id"] == "paper_preflight")
        self.assertFalse(preflight_check["passed"])
        self.assertEqual(preflight_check["severity"], "warning")

    def test_failed_preflight_still_fails_submission_audit(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [
                    {
                        "variable": "mainfont",
                        "preferred": "Times New Roman",
                        "actual": "Times New Roman",
                        "fallback": "Liberation Serif",
                        "source": "profile",
                    }
                ],
            )
            _write_preflight(work_dir, "FAIL")

            report = audit_submission(work_dir)

        self.assertEqual(report["status"], "FAIL")
        preflight_check = next(item for item in report["checks"] if item["id"] == "paper_preflight")
        self.assertFalse(preflight_check["passed"])
        self.assertEqual(preflight_check["severity"], "error")

    def test_failed_execution_validation_fails_submission_audit(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [
                    {
                        "variable": "mainfont",
                        "preferred": "Times New Roman",
                        "actual": "Times New Roman",
                        "fallback": "Liberation Serif",
                        "source": "profile",
                    }
                ],
            )
            _write_json(work_dir, "execution_validation_report.json", {"status": "FAIL"})

            report = audit_submission(work_dir)

        self.assertEqual(report["status"], "FAIL")
        check = next(item for item in report["checks"] if item["id"] == "execution_validation")
        self.assertFalse(check["passed"])


    def test_stale_preflight_hash_fails_submission_audit(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            with open(os.path.join(work_dir, "res.md"), "a", encoding="utf-8") as handle:
                handle.write(" changed")

            report = audit_submission(work_dir)

        check = next(item for item in report["checks"] if item["id"] == "paper_preflight")
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(check["passed"])

    def test_partial_or_stale_pdf_visual_report_fails_submission_audit(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            visual_path = os.path.join(work_dir, "pdf_visual_check.json")
            with open(visual_path, encoding="utf-8") as handle:
                visual = json.load(handle)
            visual["scan_scope"] = "partial_pages"
            _write_json(work_dir, "pdf_visual_check.json", visual)

            report = audit_submission(work_dir)

        check = next(item for item in report["checks"] if item["id"] == "pdf_visual_check")
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(check["passed"])

    def test_official_fonts_pass_and_report_files_are_written(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [
                    {
                        "variable": "mainfont",
                        "preferred": "Times New Roman",
                        "actual": "Times New Roman",
                        "fallback": "Liberation Serif",
                        "source": "profile",
                    }
                ],
            )

            report = write_submission_audit_report(work_dir, require_official_fonts=True)

            self.assertEqual(report["status"], "PASS")
            self.assertTrue(os.path.exists(os.path.join(work_dir, "submission_audit_report.json")))
            self.assertTrue(os.path.exists(os.path.join(work_dir, "submission_audit_report.md")))


if __name__ == "__main__":
    unittest.main()
