"""Tests for the frozen-result Codex/human quality review packet."""

import json
import tempfile
import unittest
from pathlib import Path

from app.tools.execution_quality_review import write_execution_quality_review


class ExecutionQualityReviewTest(unittest.TestCase):
    def test_explicit_failed_result_and_nonfinite_value_require_review(self):
        with tempfile.TemporaryDirectory() as work_dir:
            Path(work_dir, "ques1_results.csv").write_text(
                "指标,实际值,是否达标\n质量守恒残差,8.32,否\n温度,nan,是\n",
                encoding="utf-8",
            )

            report = write_execution_quality_review(work_dir)

            self.assertEqual(report["status"], "NEEDS_REVIEW")
            self.assertEqual(report["failed_subtasks"], ["ques1"])
            self.assertEqual(len(report["findings"]), 2)
            saved = json.loads(
                Path(work_dir, "execution_quality_review.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(saved["review_id"], report["review_id"])
            self.assertTrue(Path(work_dir, "execution_quality_review.md").exists())

    def test_review_id_changes_with_result_evidence(self):
        with tempfile.TemporaryDirectory() as work_dir:
            result_path = Path(work_dir, "ques1_results.csv")
            result_path.write_text(
                "指标,实际值,是否达标\n利润,3600,是\n", encoding="utf-8"
            )
            first = write_execution_quality_review(work_dir)
            self.assertEqual(first["status"], "PASS")

            result_path.write_text(
                "指标,实际值,是否达标\n利润,0,否\n", encoding="utf-8"
            )
            second = write_execution_quality_review(work_dir)

            self.assertNotEqual(first["review_id"], second["review_id"])

    def test_singular_result_filename_is_scanned_without_unrelated_csvs(self):
        with tempfile.TemporaryDirectory() as work_dir:
            Path(work_dir, "ques1_result.csv").write_text(
                "指标,实际值,是否达标\n质量守恒残差,8.32,否\n", encoding="utf-8"
            )
            Path(work_dir, "ques2_results.csv").write_text(
                "指标,实际值,是否达标\n利润,3600,是\n", encoding="utf-8"
            )
            Path(work_dir, "ques3_result_backup.csv").write_text(
                "指标,实际值,是否达标\n误报,1,否\n", encoding="utf-8"
            )
            Path(work_dir, "results.csv").write_text(
                "指标,实际值,是否达标\n误报,1,否\n", encoding="utf-8"
            )

            report = write_execution_quality_review(work_dir)

            self.assertEqual(
                [source["path"] for source in report["sources"]],
                ["ques1_result.csv", "ques2_results.csv"],
            )
            self.assertEqual(report["failed_subtasks"], ["ques1"])
            self.assertEqual(len(report["findings"]), 1)


if __name__ == "__main__":
    unittest.main()
