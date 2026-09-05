"""Tests for the frozen-result Codex/human quality review packet.

Batch-1 contract: review sources come from the execution-evidence manifest
(``execution_validation.json``), never from filename guessing.  PASS /
NEEDS_REVIEW / BLOCKED are strictly separated and the review_id binds the
frozen registry, executed code, problem/plan artifacts and rule version.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path


from app.tools.execution_quality_review import write_execution_quality_review


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_csv(root: Path, name: str, text: str) -> str:
    path = root / name
    path.write_text(text, encoding="utf-8")
    return _sha(path)


def _register(root: Path, subtasks: list[dict]) -> None:
    (root / "execution_validation.json").write_text(
        json.dumps(
            {
                "schema_version": "test",
                "subtasks": subtasks,
                "metrics": [],
                "status": "pass",
                "generated_by": "test",
                "updated_at": "2026-09-05T00:00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _subtask(subtask_id: str, source: dict | None, feasible: bool = True) -> dict:
    constraints = [{"source": source}] if source else []
    return {
        "id": subtask_id,
        "executed": True,
        "feasible": feasible,
        "constraints": constraints,
        "metrics": [],
        "figures": [],
        "recorded_by": "test",
    }


class ExecutionQualityReviewRegistryTest(unittest.TestCase):
    def test_missing_manifest_blocks_instead_of_empty_pass(self):
        with tempfile.TemporaryDirectory() as work_dir:
            # 情形1：没有任何登记来源（清单缺失）——旧实现会 0 来源 PASS。
            Path(work_dir, "ques1_results.csv").write_text(
                "指标,实际值,是否达标\n利润,3600,是\n", encoding="utf-8"
            )
            report = write_execution_quality_review(work_dir)
            self.assertEqual(report["status"], "BLOCKED")
            self.assertIn("registry.missing", [f["id"] for f in report["findings"]])

    def test_nonstandard_filename_registered_is_checked_normally(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            # 情形2：文件名非 quesN_result(s).csv，但清单正确登记——正常检查。
            sha = _write_csv(
                root, "ques1_schedule_result.csv", "指标,实际值,是否达标\n利润,3600,是\n"
            )
            _register(root, [_subtask("ques1", {"path": "ques1_schedule_result.csv", "sha256": sha})])
            report = write_execution_quality_review(work_dir)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual([s["path"] for s in report["sources"]], ["ques1_schedule_result.csv"])

    def test_subtask_without_numeric_source_blocks_and_names_it(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            # 情形3：某一正式子题缺数值来源——阻断并点名。
            sha = _write_csv(root, "ques1_results.csv", "指标,实际值,是否达标\n利润,3600,是\n")
            _register(
                root,
                [
                    _subtask("ques1", {"path": "ques1_results.csv", "sha256": sha}),
                    _subtask("ques2", None),
                ],
            )
            report = write_execution_quality_review(work_dir)
            self.assertEqual(report["status"], "BLOCKED")
            self.assertEqual(report["blocked_subtasks"], ["ques2"])
            self.assertIn("ques2.no_numeric_source", [f["id"] for f in report["findings"]])

    def test_source_drift_blocks_and_changes_review_id(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            # 情形4a：CSV 在登记后被改动——漂移阻断，编号变化。
            sha = _write_csv(root, "ques1_results.csv", "指标,实际值,是否达标\n利润,3600,是\n")
            _register(root, [_subtask("ques1", {"path": "ques1_results.csv", "sha256": sha})])
            first = write_execution_quality_review(work_dir)
            self.assertEqual(first["status"], "PASS")

            (root / "ques1_results.csv").write_text(
                "指标,实际值,是否达标\n利润,9999,是\n", encoding="utf-8"
            )
            second = write_execution_quality_review(work_dir)
            self.assertEqual(second["status"], "BLOCKED")
            self.assertIn("ques1.source_drift", [f["id"] for f in second["findings"]])
            self.assertNotEqual(first["review_id"], second["review_id"])

    def test_frozen_registry_and_notebook_changes_invalidate_approval(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            # 情形4b：冻结登记或执行代码变化——原审批编号失效。
            sha = _write_csv(root, "ques1_results.csv", "指标,实际值,是否达标\n利润,3600,是\n")
            _register(root, [_subtask("ques1", {"path": "ques1_results.csv", "sha256": sha})])
            (root / "frozen_results.json").write_text('{"metrics": []}', encoding="utf-8")
            (root / "notebook.ipynb").write_text('{"cells": []}', encoding="utf-8")
            first = write_execution_quality_review(work_dir)

            (root / "frozen_results.json").write_text('{"metrics": [1]}', encoding="utf-8")
            second = write_execution_quality_review(work_dir)
            self.assertNotEqual(first["review_id"], second["review_id"])

            (root / "frozen_results.json").write_text('{"metrics": []}', encoding="utf-8")
            (root / "notebook.ipynb").write_text('{"cells": [2]}', encoding="utf-8")
            third = write_execution_quality_review(work_dir)
            self.assertNotEqual(first["review_id"], third["review_id"])

    def test_only_generated_at_change_keeps_review_id(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            # 情形5：仅报告生成时间变化——审批依据不变。
            sha = _write_csv(root, "ques1_results.csv", "指标,实际值,是否达标\n利润,3600,是\n")
            _register(root, [_subtask("ques1", {"path": "ques1_results.csv", "sha256": sha})])
            first = write_execution_quality_review(work_dir)
            second = write_execution_quality_review(work_dir)
            self.assertEqual(first["review_id"], second["review_id"])
            self.assertNotEqual(first["generated_at"], second["generated_at"])

    def test_declared_failure_nonfinite_and_infeasible_require_review(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            # 情形6：不可行声明/失败标记/非有限数值——NEEDS_REVIEW（可人工批准）。
            sha = _write_csv(
                root,
                "ques1_results.csv",
                "指标,实际值,是否达标\n质量守恒残差,8.32,否\n温度,nan,是\n",
            )
            _register(
                root,
                [
                    _subtask("ques1", {"path": "ques1_results.csv", "sha256": sha}),
                    _subtask("ques2", {"path": "ques1_results.csv", "sha256": sha}, feasible=False),
                ],
            )
            report = write_execution_quality_review(work_dir)
            self.assertEqual(report["status"], "NEEDS_REVIEW")
            self.assertEqual(report["failed_subtasks"], ["ques1", "ques2"])
            ids = [f["id"] for f in report["findings"]]
            self.assertIn("ques1.declared_failure.2.是否达标", ids)
            self.assertIn("ques1.nonfinite.3.实际值", ids)
            self.assertIn("ques2.declared_infeasible", ids)

    def test_missing_registered_file_blocks(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            # 登记的来源文件被删除——阻断。
            _register(
                root,
                [_subtask("ques1", {"path": "ques1_results.csv", "sha256": "0" * 64})],
            )
            report = write_execution_quality_review(work_dir)
            self.assertEqual(report["status"], "BLOCKED")
            self.assertIn("ques1.source_missing", [f["id"] for f in report["findings"]])

    def test_unsafe_registered_path_blocks(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            # 登记路径逃逸工作区——按缺失阻断，不读外部文件。
            _register(root, [_subtask("ques1", {"path": "../outside.csv", "sha256": "0" * 64})])
            report = write_execution_quality_review(work_dir)
            self.assertEqual(report["status"], "BLOCKED")

    def test_markdown_reports_coverage_and_blocked_actions(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            sha = _write_csv(root, "ques1_results.csv", "指标,实际值,是否达标\n利润,3600,是\n")
            _register(root, [_subtask("ques1", {"path": "ques1_results.csv", "sha256": sha})])
            write_execution_quality_review(work_dir)
            md = Path(work_dir, "execution_quality_review.md").read_text(encoding="utf-8")
            self.assertIn("来源覆盖", md)
            self.assertIn("ques1_results.csv", md)
            self.assertIn("`BLOCKED` 状态禁止 approve", md)


if __name__ == "__main__":
    unittest.main()
