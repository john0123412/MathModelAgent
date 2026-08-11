import json
import os
import tempfile
import unittest
import zipfile

from app.tools.candidate_exporter import collect_support_material_paths, write_candidate_manifest
from app.tools.paper_postprocessor import build_reference_source_trace, scan_similarity_ai_risk
from app.tools.submission_audit import audit_submission


class TestP0SubmissionIntegrity(unittest.TestCase):
    def test_support_archive_is_bounded_and_excludes_secrets(self):
        with tempfile.TemporaryDirectory() as work_dir:
            for name, data in {
                "solve.py": b"print(1)",
                "result.csv": b"x,y\n1,2\n",
                "api_key.txt": b"secret",
                "checkpoint.json": b"internal",
            }.items():
                with open(os.path.join(work_dir, name), "wb") as handle:
                    handle.write(data)
            os.makedirs(os.path.join(work_dir, "template_overrides"), exist_ok=True)
            with open(
                os.path.join(work_dir, "template_overrides", "cumcm2026_reference.docx"),
                "wb",
            ) as handle:
                handle.write(b"template")
            write_candidate_manifest(work_dir, "t1")
            with open(os.path.join(work_dir, "support_materials_manifest.json"), encoding="utf-8") as handle:
                manifest = json.load(handle)
            paths = {item["path"] for item in manifest["files"]}
            self.assertEqual(paths, {"solve.py", "result.csv"})
            with zipfile.ZipFile(os.path.join(work_dir, "support_materials.zip")) as archive:
                self.assertEqual(set(archive.namelist()), paths)

    def test_template_override_files_are_not_support_material(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(
                os.path.join(work_dir, "export_template_override.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write('{"profiles":{}}')
            os.makedirs(os.path.join(work_dir, "template_overrides"), exist_ok=True)
            with open(
                os.path.join(work_dir, "template_overrides", "reference.docx"),
                "wb",
            ) as handle:
                handle.write(b"template")

            self.assertEqual(collect_support_material_paths(work_dir), [])

    def test_ai_usage_details_pdf_is_included_in_support_archive(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pdf_name = "AI工具使用详情.pdf"
            with open(os.path.join(work_dir, pdf_name), "wb") as handle:
                handle.write(b"%PDF-1.4\nAI usage details")

            write_candidate_manifest(work_dir, "t1")

            with open(
                os.path.join(work_dir, "support_materials_manifest.json"),
                encoding="utf-8",
            ) as handle:
                manifest = json.load(handle)
            entry = next(item for item in manifest["files"] if item["path"] == pdf_name)
            self.assertEqual(entry["category"], "AI工具使用详情")
            with zipfile.ZipFile(os.path.join(work_dir, "support_materials.zip")) as archive:
                self.assertIn(pdf_name, archive.namelist())

    def test_audit_rejects_missing_or_invalid_submission_file(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "candidate_manifest.json"), "w", encoding="utf-8") as handle:
                json.dump({"submission_file": "evil.txt"}, handle)
            report = audit_submission(work_dir)
            check = next(item for item in report["checks"] if item["id"] == "submission_file")
            self.assertFalse(check["passed"])

    def test_reference_trace_and_risk_scan_are_explicit(self):
        markdown = "## 参考文献\n\n[1] Example DOI 10.1000/xyz.\n\n结果表明结果表明结果表明结果表明。"
        trace = build_reference_source_trace(markdown)
        self.assertTrue(trace["passed"])
        self.assertEqual(trace["entries"][0]["verification_status"], "manual_review_required")
        risk = scan_similarity_ai_risk(markdown)
        self.assertIn("disclaimer", risk)
        self.assertIn("不是正式查重", risk["disclaimer"])

    def test_risk_scan_ignores_repeated_image_markdown(self):
        markdown = (
            "正文结论不同。\n\n"
            "![重复图题](shared_plot.png)\n\n"
            "![重复图题](shared_plot.png)\n\n"
            "![重复图题](shared_plot.png)\n"
        )

        risk = scan_similarity_ai_risk(markdown)

        self.assertTrue(risk["passed"])
        self.assertEqual(risk["status"], "NO_LOCAL_INDICATOR")


if __name__ == "__main__":
    unittest.main()
