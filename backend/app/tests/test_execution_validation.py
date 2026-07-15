"""Regression tests for the execution/feasibility completion gate."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest

import nbformat
from nbformat import v4 as nbf

from app.tools.execution_validation import (
    MANIFEST_NAME,
    record_execution_evidence,
    validate_execution_artifacts,
    write_frozen_results_from_execution_validation,
    write_execution_validation_report,
)


def _sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _write_notebook(work_dir: str, *, error: bool = False) -> None:
    cell = nbf.new_code_cell("value = 100")
    if error:
        cell["outputs"] = [
            nbf.new_output(
                output_type="error",
                ename="ModuleNotFoundError",
                evalue="No module named 'problem2_simulation'",
                traceback=["ModuleNotFoundError"],
            )
        ]
    notebook = nbf.new_notebook(cells=[cell])
    with open(os.path.join(work_dir, "notebook.ipynb"), "w", encoding="utf-8") as handle:
        nbformat.write(notebook, handle)


def _write_manifest(
    work_dir: str,
    *,
    actual: float = 100.0,
    feasible: bool = True,
) -> None:
    source_path = os.path.join(work_dir, "results.json")
    with open(source_path, "w", encoding="utf-8") as handle:
        json.dump({"mean_pressure_mpa": actual}, handle)
    payload = {
        "schema_version": "mathmodel.execution-validation.v1",
        "status": "PASS" if feasible else "FAIL",
        "metrics": [
            {
                "id": "mean_pressure_mpa",
                "label": "平均压力",
                "value": actual,
                "unit": "MPa",
                "explanation": "稳态窗口内高压油管压力均值",
            }
        ],
        "subtasks": [
            {
                "id": "ques3",
                "executed": True,
                "feasible": feasible,
                "constraints": [
                    {
                        "id": "mean_pressure_target",
                        "actual": actual,
                        "target": 100.0,
                        "tolerance": 1.0,
                        "comparison": "abs_diff_lte",
                        "unit": "MPa",
                        "source": {"path": "results.json", "sha256": _sha256(source_path)},
                    }
                ],
                "metrics": [
                    {
                        "id": "mass_balance_residual",
                        "label": "质量守恒残差",
                        "value": 0.0,
                        "unit": "mg",
                        "explanation": "由已执行时序数组计算的单周期质量守恒残差",
                    }
                ],
                "figures": [],
            }
        ],
    }
    with open(
        os.path.join(work_dir, "execution_validation.json"), "w", encoding="utf-8"
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


class TestExecutionValidation(unittest.TestCase):
    def test_trusted_evidence_recorder_hashes_files_and_derives_feasibility(self):
        with tempfile.TemporaryDirectory() as work_dir:
            result_path = os.path.join(work_dir, "ques1_results.json")
            with open(result_path, "w", encoding="utf-8") as handle:
                json.dump({"value": 100.0}, handle)
            with open(os.path.join(work_dir, MANIFEST_NAME), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "schema_version": "mathmodel.execution-validation.v1",
                        "subtasks": [{"id": "ques2", "executed": True, "feasible": True}],
                        "metrics": [],
                    },
                    handle,
                )

            recorded = record_execution_evidence(
                work_dir,
                subtask_id="ques1",
                constraints=[
                    {
                        "id": "target",
                        "actual": 100.0,
                        "comparison": "abs_diff_lte",
                        "target": 100.0,
                        "tolerance": 0.1,
                        "lower": None,
                        "upper": None,
                        "unit": None,
                        "source_path": "ques1_results.json",
                    }
                ],
                metrics=[
                    {
                        "id": "objective",
                        "label": "目标值",
                        "value": 100.0,
                        "unit": "元",
                        "explanation": "由本次线性规划的实际求解结果读取。",
                    },
                    {
                        "id": "balance_residual",
                        "label": "约束残差",
                        "value": 0.0,
                        "unit": "小时",
                        "explanation": "由实际解代入资源约束计算。",
                    },
                ],
                figures=[],
            )

            self.assertTrue(recorded["ok"])
            self.assertTrue(recorded["feasible"])
            with open(os.path.join(work_dir, MANIFEST_NAME), encoding="utf-8") as handle:
                manifest = json.load(handle)
            entry = next(item for item in manifest["subtasks"] if item["id"] == "ques1")
            self.assertTrue(any(item["id"] == "ques2" for item in manifest["subtasks"]))
            self.assertTrue(entry["executed"])
            self.assertTrue(entry["feasible"])
            self.assertEqual(entry["recorded_by"], "trusted_record_execution_evidence")
            self.assertEqual(entry["constraints"][0]["source"]["path"], "ques1_results.json")
            self.assertEqual(entry["constraints"][0]["source"]["sha256"], _sha256(result_path))
            self.assertEqual(manifest["metrics"][0]["id"], "objective")

    def test_trusted_evidence_recorder_rejects_missing_or_cross_task_sources_without_writing(self):
        with tempfile.TemporaryDirectory() as work_dir:
            recorded = record_execution_evidence(
                work_dir,
                subtask_id="ques1",
                constraints=[
                    {
                        "id": "target",
                        "actual": 1.0,
                        "comparison": "lte",
                        "target": 2.0,
                        "source_path": "../outside.json",
                    }
                ],
                metrics=[
                    {
                        "id": "objective",
                        "label": "目标值",
                        "value": 1.0,
                        "unit": "元",
                        "explanation": "由计算结果读取。",
                    }
                ],
                figures=[],
            )

            self.assertFalse(recorded["ok"])
            self.assertFalse(os.path.exists(os.path.join(work_dir, MANIFEST_NAME)))

    def test_clean_notebook_and_feasible_constraint_pass(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)

            report = write_execution_validation_report(
                work_dir, required_subtasks=["ques3"]
            )

            self.assertEqual(report["status"], "PASS")
            self.assertTrue(
                os.path.exists(os.path.join(work_dir, "execution_validation_report.json"))
            )
            frozen_path = write_frozen_results_from_execution_validation(work_dir)
            with open(frozen_path, encoding="utf-8") as handle:
                frozen = json.load(handle)
            self.assertEqual(frozen["schema"], "mathmodel.result-freeze")
            self.assertEqual(frozen["version"], 1)
            self.assertEqual(frozen["metrics"][0]["label"], "平均压力")
            self.assertIn("notebook.ipynb", frozen["executed_code_sources"])

    def test_freeze_qualifies_duplicate_metric_ids_by_subtask(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            for subtask_id, residual in (("ques1", 0.0), ("ques2", -10.0)):
                source_name = f"{subtask_id}_results.json"
                with open(os.path.join(work_dir, source_name), "w", encoding="utf-8") as handle:
                    json.dump({"residual": residual}, handle)
                recorded = record_execution_evidence(
                    work_dir,
                    subtask_id=subtask_id,
                    constraints=[
                        {
                            "id": "residual_bound",
                            "actual": residual,
                            "comparison": "lte",
                            "target": 0.0,
                            "source_path": source_name,
                        }
                    ],
                    metrics=[
                        {
                            "id": "balance_residual",
                            "label": "资源守恒残差",
                            "value": residual,
                            "unit": "小时",
                            "explanation": "由本子题资源约束代入计算。",
                        }
                    ],
                    figures=[],
                )
                self.assertTrue(recorded["ok"])

            frozen_path = write_frozen_results_from_execution_validation(work_dir)
            with open(frozen_path, encoding="utf-8") as handle:
                frozen = json.load(handle)
            self.assertEqual(
                [metric["id"] for metric in frozen["metrics"]],
                ["ques1.balance_residual", "ques2.balance_residual"],
            )
            self.assertEqual(
                [metric["subtask_id"] for metric in frozen["metrics"]],
                ["ques1", "ques2"],
            )

    def test_linear_programming_contract_requires_decision_metrics(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            with open(os.path.join(work_dir, "problem_contract.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "required_requirements": [
                            {"plugin": "linear_programming", "key": "linear_programming_evidence"}
                        ]
                    },
                    handle,
                )

            report = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])

            self.assertEqual(report["status"], "FAIL")
            check = next(
                item
                for item in report["checks"]
                if item["id"] == "ques3.linear_programming_solution_metrics"
            )
            self.assertFalse(check["passed"])

    def test_linear_programming_contract_does_not_require_physical_balance_residual(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            manifest_path = os.path.join(work_dir, "execution_validation.json")
            with open(manifest_path, encoding="utf-8") as handle:
                manifest = json.load(handle)
            manifest["subtasks"][0]["metrics"] = [
                {
                    "id": "optimal_profit",
                    "label": "最优利润",
                    "value": 2200.0,
                    "unit": "元",
                    "explanation": "由线性规划实际求解结果读取。",
                },
                {
                    "id": "optimal_production_a",
                    "label": "A 产品最优产量",
                    "value": 40.0,
                    "unit": "件",
                    "explanation": "由最优决策变量读取。",
                },
            ]
            with open(os.path.join(work_dir, "problem_contract.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {"required_requirements": [{"plugin": "linear_programming"}]},
                    handle,
                )
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle, ensure_ascii=False)

            report = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])

        self.assertEqual(report["status"], "PASS")
        self.assertFalse(any(item["id"] == "ques3.balance_residual" for item in report["checks"]))

    def test_notebook_error_without_manifest_blocks_completion(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir, error=True)

            report = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])

            self.assertEqual(report["status"], "FAIL")
            check = next(item for item in report["checks"] if item["id"] == "notebook_errors")
            self.assertFalse(check["passed"])

    def test_historical_notebook_error_needs_hashed_manifest_evidence(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir, error=True)
            _write_manifest(work_dir)

            report = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])

            self.assertEqual(report["status"], "PASS")
            check = next(item for item in report["checks"] if item["id"] == "notebook_errors")
            self.assertTrue(check["passed"])
            self.assertTrue(check["evidence"]["reconciled_by_execution_manifest"])

    def test_pressure_mean_66_mpa_cannot_be_marked_feasible_for_100_mpa_target(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir, actual=66.08, feasible=True)

            report = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])

            self.assertEqual(report["status"], "FAIL")
            check = next(
                item
                for item in report["checks"]
                if item["id"] == "ques3.constraint.mean_pressure_target"
            )
            self.assertFalse(check["passed"])

    def test_explicit_infeasibility_blocks_completion(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir, actual=100.0, feasible=False)

            report = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])

            self.assertEqual(report["status"], "FAIL")
            check = next(item for item in report["checks"] if item["id"] == "ques3.feasible")
            self.assertFalse(check["passed"])

    def test_hash_mismatch_blocks_figure_or_result_claim(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            with open(os.path.join(work_dir, "results.json"), "w", encoding="utf-8") as handle:
                json.dump({"mean_pressure_mpa": 99.0}, handle)

            report = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])

            self.assertEqual(report["status"], "FAIL")
            check = next(
                item
                for item in report["checks"]
                if item["id"] == "ques3.constraint.mean_pressure_target"
            )
            self.assertFalse(check["passed"])

    def test_formal_subtask_cannot_pass_with_an_estimate_or_no_balance_residual(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            manifest_path = os.path.join(work_dir, "execution_validation.json")
            with open(manifest_path, encoding="utf-8") as handle:
                manifest = json.load(handle)
            manifest["subtasks"][0]["metrics"] = [
                {
                    "id": "estimated_pressure",
                    "label": "估计平均压力",
                    "value": 100.0,
                    "unit": "MPa",
                    "explanation": "基于上一问结果估计",
                }
            ]
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle, ensure_ascii=False)

            report = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])

            self.assertEqual(report["status"], "FAIL")
            self.assertFalse(next(item for item in report["checks"] if item["id"] == "ques3.computed_evidence")["passed"])
            self.assertFalse(next(item for item in report["checks"] if item["id"] == "ques3.balance_residual")["passed"])

    def test_relief_valve_problem_needs_a_real_disturbance_activation(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            with open(os.path.join(work_dir, "problem_contract.json"), "w", encoding="utf-8") as handle:
                json.dump({"required_requirements": [{"key": "relief_valve_control"}]}, handle)
            report = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])

            self.assertEqual(report["status"], "FAIL")
            check = next(item for item in report["checks"] if item["id"] == "ques3.relief_disturbance_evidence")
            self.assertFalse(check["passed"])

    def test_gt_constraint_is_checked_and_100_mpa_contract_rejects_large_fluctuation(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            manifest_path = os.path.join(work_dir, "execution_validation.json")
            with open(manifest_path, encoding="utf-8") as handle:
                manifest = json.load(handle)
            constraint = manifest["subtasks"][0]["constraints"][0]
            constraint.update({"actual": 2.0, "comparison": "gt", "target": 1.0})
            manifest["metrics"].append(
                {
                    "id": "pressure_fluctuation",
                    "label": "压力波动幅值",
                    "value": 20.0,
                    "unit": "MPa",
                    "explanation": "已执行控制仿真的峰峰值",
                }
            )
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle, ensure_ascii=False)
            with open(os.path.join(work_dir, "problem_contract.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {"required_requirements": [{"key": "target_pressure_100_mpa"}]},
                    handle,
                )

            report = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])

            gt_check = next(
                item
                for item in report["checks"]
                if item["id"] == "ques3.constraint.mean_pressure_target"
            )
            self.assertTrue(gt_check["passed"])
            stability = next(
                item
                for item in report["checks"]
                if item["id"] == "pressure_stability.pressure_fluctuation"
            )
            self.assertFalse(stability["passed"])

    def test_problem_one_contract_requires_all_valve_duration_metrics(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            manifest_path = os.path.join(work_dir, "execution_validation.json")
            with open(manifest_path, encoding="utf-8") as handle:
                manifest = json.load(handle)
            manifest["subtasks"][0]["id"] = "ques1"
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle, ensure_ascii=False)
            with open(os.path.join(work_dir, "problem_contract.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {"required_requirements": [{"key": "problem1_valve_duration_outputs"}]},
                    handle,
                )

            report = validate_execution_artifacts(work_dir, required_subtasks=["ques1"])

            check = next(
                item for item in report["checks"] if item["id"] == "ques1.valve_duration_outputs"
            )
            self.assertFalse(check["passed"])
            self.assertEqual(len(check["evidence"]["missing"]), 5)


if __name__ == "__main__":
    unittest.main()
