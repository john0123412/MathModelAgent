"""Submission audit report tests."""

import json
import os
import tempfile
import unittest

from app.tools.submission_audit import audit_submission, write_submission_audit_report


def _write_json(work_dir: str, filename: str, data: dict) -> None:
    with open(os.path.join(work_dir, filename), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _write_required_success_files(work_dir: str, font_resolution: list[dict]) -> None:
    for filename in ["res.md", "res.json", "res.docx", "res.pdf"]:
        with open(os.path.join(work_dir, filename), "w", encoding="utf-8") as f:
            f.write("ok")
    _write_json(work_dir, "paper_preflight_report.json", {"status": "PASS"})
    _write_json(work_dir, "pdf_visual_check.json", {"status": "PASS"})
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
