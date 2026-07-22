import json
import os
import tempfile
import unittest
import zipfile

from app.tools.candidate_exporter import write_candidate_manifest
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
            write_candidate_manifest(work_dir, "t1")
            with open(os.path.join(work_dir, "support_materials_manifest.json"), encoding="utf-8") as handle:
                manifest = json.load(handle)
            paths = {item["path"] for item in manifest["files"]}
            self.assertEqual(paths, {"solve.py", "result.csv"})
            with zipfile.ZipFile(os.path.join(work_dir, "support_materials.zip")) as archive:
                self.assertEqual(set(archive.namelist()), paths)

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


if __name__ == "__main__":
    unittest.main()
