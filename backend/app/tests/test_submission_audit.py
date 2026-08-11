"""Submission audit report tests."""

import hashlib
import json
import os
import tempfile
import unittest
import zipfile

from app.tools.submission_audit import audit_submission, write_submission_audit_report
from app.tools.export_template_override import install_export_template_override


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


def _write_minimal_docx(work_dir: str, paragraphs: list[str] | None = None) -> None:
    body = "".join(
        "<w:p><w:r><w:t>" + text + "</w:t></w:r></w:p>"
        for text in (paragraphs or ["正常正文"])
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(os.path.join(work_dir, "res.docx"), "w") as archive:
        archive.writestr("word/document.xml", document)


def _write_required_success_files(work_dir: str, font_resolution: list[dict]) -> None:
    for filename in ["res.md", "res.json", "res.pdf"]:
        with open(os.path.join(work_dir, filename), "w", encoding="utf-8") as f:
            f.write("ok")
    _write_minimal_docx(work_dir)
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


def _write_bound_template_chain(work_dir: str) -> dict:
    source_docx = os.path.join(work_dir, "official.docx")
    with zipfile.ZipFile(source_docx, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml",
            "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'/>",
        )
    contract_path = os.path.join(work_dir, "format.json")
    _write_json(work_dir, "format.json", {"docx": {}})
    installed = install_export_template_override(
        work_dir,
        "cumcm2026",
        docx_template_path=source_docx,
        format_contract_path=contract_path,
    )
    audit = installed["audit"]
    docx_status = {
        "success": True,
        "source_sha256": _sha256(os.path.join(work_dir, "res.md")),
        "output_sha256": _sha256(os.path.join(work_dir, "res.docx")),
        "export_profile": "cumcm2026",
        "template_override": audit,
        "format_contract": {
            "active": True,
            "template_override_format_contract_sha256": audit["format_contract_sha256"],
            "template_override_docx_contract_sha256": audit["docx_contract_sha256"],
        },
    }
    _write_json(work_dir, "docx_export_status.json", docx_status)
    export_status_path = os.path.join(work_dir, "export_status.json")
    with open(export_status_path, encoding="utf-8") as handle:
        export_status = json.load(handle)
    export_status.update(
        {
            "export_profile": "cumcm2026",
            "template_override": audit,
            "pdf": {**export_status["pdf"], "template_override": audit},
        }
    )
    _write_json(work_dir, "export_status.json", export_status)
    preflight_path = os.path.join(work_dir, "paper_preflight_report.json")
    with open(preflight_path, encoding="utf-8") as handle:
        preflight = json.load(handle)
    preflight.update({"export_profile": "cumcm2026", "template_override": audit})
    _write_json(work_dir, "paper_preflight_report.json", preflight)
    visual_path = os.path.join(work_dir, "pdf_visual_check.json")
    with open(visual_path, encoding="utf-8") as handle:
        visual = json.load(handle)
    visual.update({"export_profile": "cumcm2026", "template_override": audit})
    _write_json(work_dir, "pdf_visual_check.json", visual)
    return audit


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

    def test_literal_markdown_heading_in_docx_fails_submission_audit(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            _write_minimal_docx(work_dir, ["正常正文", "### 6.1 未渲染标题"])

            report = audit_submission(work_dir)

        check = next(item for item in report["checks"] if item["id"] == "docx_markdown_heading_leakage")
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(check["passed"])
        self.assertIn("### 6.1", check["evidence"]["issues"][0])

    def test_docx_code_appendix_heading_like_source_is_ignored(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            _write_minimal_docx(
                work_dir,
                ["正常正文", "附录 B 源程序代码", "# Cell 1", "### code literal"],
            )

            report = audit_submission(work_dir)

        check = next(item for item in report["checks"] if item["id"] == "docx_markdown_heading_leakage")
        self.assertTrue(check["passed"])


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

    def test_tampered_task_template_override_fails_submission_audit(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            source_docx = os.path.join(work_dir, "official.docx")
            with zipfile.ZipFile(source_docx, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types/>")
                archive.writestr(
                    "word/document.xml",
                    "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'/>",
                )
            contract_path = os.path.join(work_dir, "format.json")
            _write_json(contract_path.rsplit(os.sep, 1)[0], "format.json", {"docx": {}})
            installed = install_export_template_override(
                work_dir,
                "cumcm2026",
                docx_template_path=source_docx,
                format_contract_path=contract_path,
            )
            _write_json(
                work_dir,
                "docx_export_status.json",
                {"export_profile": "cumcm2026", "template_override": installed["audit"]},
            )
            with open(
                os.path.join(work_dir, "template_overrides", "cumcm2026_reference.docx"),
                "ab",
            ) as handle:
                handle.write(b"tamper")

            report = audit_submission(work_dir)

        check = next(item for item in report["checks"] if item["id"] == "template_override_integrity")
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(check["passed"])
        self.assertEqual(check["severity"], "error")

    def test_template_override_must_bind_all_current_export_reports(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            _write_bound_template_chain(work_dir)

            report = audit_submission(work_dir)

        check = next(item for item in report["checks"] if item["id"] == "template_override_integrity")
        self.assertTrue(check["passed"], check["evidence"])

    def test_template_override_rejects_stale_visual_binding(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            _write_bound_template_chain(work_dir)
            visual_path = os.path.join(work_dir, "pdf_visual_check.json")
            with open(visual_path, encoding="utf-8") as handle:
                visual = json.load(handle)
            visual["template_override"] = {"active": False}
            _write_json(work_dir, "pdf_visual_check.json", visual)

            report = audit_submission(work_dir)

        check = next(item for item in report["checks"] if item["id"] == "template_override_integrity")
        self.assertFalse(check["passed"])
        self.assertIn("pdf_visual_check", check["evidence"]["mismatched_records"])

    def test_docx_audit_checks_all_font_slots_and_complex_size(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            xml = (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:pPr><w:spacing w:line=\"240\" w:lineRule=\"auto\"/>"
                "</w:pPr><w:r><w:rPr><w:rFonts w:eastAsia=\"SimSun\" w:ascii=\"Times New Roman\" "
                "w:hAnsi=\"Wrong Font\" w:cs=\"Times New Roman\"/><w:sz w:val=\"24\"/>"
                "<w:szCs w:val=\"24\"/></w:rPr><w:t>正文段落</w:t></w:r></w:p></w:body></w:document>"
            )
            _write_minimal_docx(work_dir, [])
            with zipfile.ZipFile(os.path.join(work_dir, "res.docx"), "w") as archive:
                archive.writestr("word/document.xml", xml)
            _write_json(
                work_dir,
                "docx_export_status.json",
                {
                    "export_profile": "cumcm2026",
                    "format_contract": {
                        "active": True,
                        "body_font_east_asia": "SimSun",
                        "body_font_ascii": "Times New Roman",
                        "body_font_hansi": "Times New Roman",
                        "body_font_cs": "Times New Roman",
                        "body_font_size_half_points": 24,
                        "body_line_spacing_twips": 240,
                        "body_line_rule": "auto",
                        "body_start_page_break": False,
                    },
                },
            )

            report = audit_submission(work_dir)

        check = next(item for item in report["checks"] if item["id"] == "docx_format_contract")
        self.assertFalse(check["passed"])


if __name__ == "__main__":
    unittest.main()
