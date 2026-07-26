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
    REPRODUCIBILITY_NAME,
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
    def test_recorded_infeasible_evidence_returns_failed_constraint_details(self):
        with tempfile.TemporaryDirectory() as work_dir:
            source_path = os.path.join(work_dir, "ques2_constraint_check.csv")
            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write("id,actual,target\\nmax_pressure,177.99,150.0\\n")

            recorded = record_execution_evidence(
                work_dir,
                subtask_id="ques2",
                constraints=[
                    {
                        "id": "max_pressure",
                        "actual": 177.99,
                        "comparison": "lte",
                        "target": 150.0,
                        "unit": "MPa",
                        "source_path": "ques2_constraint_check.csv",
                    }
                ],
                metrics=[
                    {
                        "id": "pipe_pressure_peak",
                        "label": "油管压力最大值",
                        "value": 177.99,
                        "unit": "MPa",
                        "explanation": "由已执行的压力时序数组取得最大值。",
                        "source_path": "ques2_constraint_check.csv",
                    }
                ],
            )

            self.assertTrue(recorded["ok"])
            self.assertFalse(recorded["feasible"])
            self.assertEqual(
                recorded["failed_constraints"],
                [{
                    "id": "max_pressure",
                    "actual": 177.99,
                    "comparison": "lte",
                    "target": 150.0,
                    "tolerance": None,
                    "lower": None,
                    "upper": None,
                }],
            )

    def test_explicit_incident_angles_must_survive_parameter_audit(self):
        problem = (
            "附件1和附件2是入射角分别为10°和15°时针对同一块晶圆片的测试结果。"
        )
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            with open(
                os.path.join(work_dir, "task_request.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump({"ques_all": problem}, handle, ensure_ascii=False)
            audit_path = os.path.join(work_dir, "input_parameter_audit.csv")
            with open(audit_path, "w", encoding="utf-8-sig") as handle:
                handle.write("参数,值,单位,来源\n入射角 θ,0,度,题面假设垂直入射\n")

            wrong = validate_execution_artifacts(
                work_dir, required_subtasks=["ques3"]
            )
            angle_check = next(
                item
                for item in wrong["checks"]
                if item["id"] == "problem_parameter.incident_angles"
            )
            self.assertFalse(angle_check["passed"])
            self.assertEqual(angle_check["evidence"]["missing_angles_deg"], [10.0, 15.0])

            with open(audit_path, "w", encoding="utf-8-sig") as handle:
                handle.write(
                    "参数,值,单位,来源\n"
                    "附件1入射角,10,度,题面附件说明\n"
                    "附件2入射角,15,度,题面附件说明\n"
                )
            correct = validate_execution_artifacts(
                work_dir, required_subtasks=["ques3"]
            )
            angle_check = next(
                item
                for item in correct["checks"]
                if item["id"] == "problem_parameter.incident_angles"
            )
            self.assertTrue(angle_check["passed"], angle_check)

    def test_per_question_parameter_audits_are_aggregated_for_angle_check(self):
        """每题写各自的审计文件时，角度核对应聚合所有文件而非只认单一文件。"""
        problem = (
            "附件1和附件2是入射角分别为10°和15°时针对同一块晶圆片的测试结果。"
        )
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            with open(
                os.path.join(work_dir, "task_request.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump({"ques_all": problem}, handle, ensure_ascii=False)
            # 没有任何 per-question 审计文件时应判缺失。
            missing = validate_execution_artifacts(
                work_dir, required_subtasks=["ques3"]
            )
            angle_check = next(
                item
                for item in missing["checks"]
                if item["id"] == "problem_parameter.incident_angles"
            )
            self.assertFalse(angle_check["passed"])
            # 两题各写自己的审计文件，各覆盖一个角度；聚合后应通过。
            with open(
                os.path.join(work_dir, "ques2_input_parameter_audit.csv"),
                "w",
                encoding="utf-8-sig",
            ) as handle:
                handle.write("参数,值,单位,来源\n附件1入射角,10,度,题面附件说明\n")
            with open(
                os.path.join(work_dir, "ques3_input_parameter_audit.csv"),
                "w",
                encoding="utf-8-sig",
            ) as handle:
                handle.write("参数,值,单位,来源\n附件2入射角,15,度,题面附件说明\n")
            correct = validate_execution_artifacts(
                work_dir, required_subtasks=["ques3"]
            )
            angle_check = next(
                item
                for item in correct["checks"]
                if item["id"] == "problem_parameter.incident_angles"
            )
            self.assertTrue(angle_check["passed"], angle_check)

    def test_trusted_evidence_recorder_hashes_files_and_derives_feasibility(self):
        with tempfile.TemporaryDirectory() as work_dir:
            result_path = os.path.join(work_dir, "ques1_results.json")
            with open(result_path, "w", encoding="utf-8") as handle:
                json.dump({"value": 100.0, "balance_residual": 0.0}, handle)
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
                        "source_path": "ques1_results.json",
                    },
                    {
                        "id": "balance_residual",
                        "label": "约束残差",
                        "value": 0.0,
                        "unit": "小时",
                        "explanation": "由实际解代入资源约束计算。",
                        "source_path": "ques1_results.json",
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
                        "source_path": "../outside.json",
                    }
                ],
                figures=[],
            )

            self.assertFalse(recorded["ok"])
            self.assertFalse(os.path.exists(os.path.join(work_dir, MANIFEST_NAME)))

    def test_recorder_rejects_flipped_model_plan_comparison(self):
        with tempfile.TemporaryDirectory() as work_dir:
            result_path = os.path.join(work_dir, "ques2_fit_results.json")
            with open(result_path, "w", encoding="utf-8") as handle:
                json.dump({"fit_r_squared": 0.1543}, handle)
            with open(
                os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(
                    {
                        "model_plan": {
                            "subtasks": {
                                "ques2": {
                                    "acceptance_metrics": [
                                        {
                                            "key": "fit_r_squared",
                                            "comparator": "gt",
                                            "target": 0.95,
                                        }
                                    ]
                                }
                            }
                        }
                    },
                    handle,
                )

            recorded = record_execution_evidence(
                work_dir,
                subtask_id="ques2",
                constraints=[
                    {
                        "id": "fit_r_squared",
                        "actual": 0.1543,
                        "comparison": "lte",
                        "target": 0.95,
                        "source_path": "ques2_fit_results.json",
                    }
                ],
                metrics=[
                    {
                        "id": "fit_r_squared",
                        "label": "拟合优度",
                        "value": 0.1543,
                        "unit": "无量纲",
                        "explanation": "由拟合残差计算。",
                        "source_path": "ques2_fit_results.json",
                    }
                ],
                figures=[],
            )

            self.assertFalse(recorded["ok"])
            self.assertIn("不得改为 lte", " ".join(recorded["errors"]))
            self.assertFalse(os.path.exists(os.path.join(work_dir, MANIFEST_NAME)))

            with open(result_path, "w", encoding="utf-8") as handle:
                json.dump({"fit_r_squared": 0.96}, handle)
            corrected = record_execution_evidence(
                work_dir,
                subtask_id="ques2",
                constraints=[
                    {
                        "id": "fit_r_squared",
                        "actual": 0.96,
                        "comparison": "gt",
                        "target": 0.95,
                        "source_path": "ques2_fit_results.json",
                    }
                ],
                metrics=[
                    {
                        "id": "fit_r_squared",
                        "label": "拟合优度",
                        "value": 0.96,
                        "unit": "无量纲",
                        "explanation": "由拟合残差计算。",
                        "source_path": "ques2_fit_results.json",
                    }
                ],
                figures=[],
            )
            self.assertTrue(corrected["ok"], corrected)
            self.assertTrue(corrected["feasible"])
            with open(os.path.join(work_dir, MANIFEST_NAME), encoding="utf-8") as handle:
                manifest = json.load(handle)
            self.assertEqual(
                manifest["schema_version"], "mathmodel.execution-validation.v2"
            )
            self.assertEqual(
                manifest["subtasks"][0]["metrics"][0]["source"]["path"],
                "ques2_fit_results.json",
            )

    def test_recorder_binds_plan_constraints_to_exact_acceptance_table_values(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "ques1_results.json"), "w", encoding="utf-8") as handle:
                json.dump({"objective": 10.0}, handle)
            with open(os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {"model_plan": {"subtasks": {"ques1": {"acceptance_metrics": [
                        {"key": "pressure_deviation_rms", "comparator": "le", "target": 3.0}
                    ]}}}},
                    handle,
                )
            with open(
                os.path.join(work_dir, "ques1_acceptance_metrics.csv"),
                "w", encoding="utf-8-sig",
            ) as handle:
                handle.write(
                    "指标ID,指标名称,数值,单位,目标值,是否达标\n"
                    "pressure_deviation_rms,稳态压力均方根误差,2.586323599964039,MPa,≤3.0,是\n"
                )

            recorded = record_execution_evidence(
                work_dir,
                subtask_id="ques1",
                constraints=[
                    {
                        "id": "physical_bound",
                        "actual": 10.0,
                        "comparison": "lte",
                        "target": 10.0,
                        "source_path": "ques1_results.json",
                    }
                ],
                metrics=[
                    {
                        "id": "objective",
                        "label": "目标值",
                        "value": 10.0,
                        "unit": "无量纲",
                        "explanation": "由本次实际计算结果读取。",
                        "source_path": "ques1_results.json",
                    }
                ],
                figures=[],
            )

            self.assertTrue(recorded["ok"], recorded)
            self.assertTrue(recorded["feasible"])
            with open(os.path.join(work_dir, MANIFEST_NAME), encoding="utf-8") as handle:
                manifest = json.load(handle)
            bound = next(
                item for item in manifest["subtasks"][0]["constraints"]
                if item["id"] == "pressure_deviation_rms"
            )
            self.assertEqual(bound["actual"], 2.586323599964039)
            self.assertEqual(bound["source"]["path"], "ques1_acceptance_metrics.csv")

    def test_recorder_rejects_internally_inconsistent_acceptance_tables(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "ques1_results.json"), "w", encoding="utf-8") as handle:
                json.dump({"objective": 10.0}, handle)
            with open(os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {"model_plan": {"subtasks": {"ques1": {"acceptance_metrics": [
                        {"key": "pressure_deviation_rms", "comparator": "le", "target": 1.0}
                    ]}}}},
                    handle,
                )
            with open(
                os.path.join(work_dir, "ques1_acceptance_metrics.csv"),
                "w", encoding="utf-8-sig",
            ) as handle:
                handle.write(
                    "指标ID,指标名称,数值,单位,目标值,是否达标\n"
                    "pressure_deviation_rms,稳态压力均方根误差,2.586323599964039,MPa,≤1.0,是\n"
                )
            with open(
                os.path.join(work_dir, "ques1_constraint_check.csv"),
                "w", encoding="utf-8-sig",
            ) as handle:
                handle.write(
                    "约束ID,约束名称,左端值,比较,右端值,状态\n"
                    "C6,pressure_deviation_rms约束,2.586323599964039,≤,1.0,满足\n"
                )

            recorded = record_execution_evidence(
                work_dir,
                subtask_id="ques1",
                constraints=[
                    {
                        "id": "physical_bound",
                        "actual": 10.0,
                        "comparison": "lte",
                        "target": 10.0,
                        "source_path": "ques1_results.json",
                    }
                ],
                metrics=[
                    {
                        "id": "objective",
                        "label": "目标值",
                        "value": 10.0,
                        "unit": "无量纲",
                        "explanation": "由本次实际计算结果读取。",
                        "source_path": "ques1_results.json",
                    }
                ],
                figures=[],
            )

            self.assertFalse(recorded["ok"])
            errors = " ".join(recorded["errors"])
            self.assertIn("acceptance_metrics.csv", errors)
            self.assertIn("constraint_check.csv", errors)
            self.assertIn("却标为", errors)
            self.assertFalse(os.path.exists(os.path.join(work_dir, MANIFEST_NAME)))

    def test_recorder_binds_scenario_rows_using_the_worst_plan_value(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "ques1_results.json"), "w", encoding="utf-8") as handle:
                json.dump({"objective": 10.0}, handle)
            with open(os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {"model_plan": {"subtasks": {"ques1": {"acceptance_metrics": [
                        {"key": "pressure_stability_index", "comparator": "le", "target": 5.0}
                    ]}}}},
                    handle,
                )
            with open(
                os.path.join(work_dir, "ques1_acceptance_metrics.csv"),
                "w", encoding="utf-8-sig",
            ) as handle:
                handle.write(
                    "指标ID,指标名称,数值,单位,目标值,是否达标\n"
                    "pressure_stability_100MPa,压力稳定度,2.4,MPa,5.0,True\n"
                    "pressure_stability_150MPa,压力稳定度,10.5,MPa,5.0,False\n"
                )

            recorded = record_execution_evidence(
                work_dir,
                subtask_id="ques1",
                constraints=[
                    {
                        "id": "physical_bound",
                        "actual": 10.0,
                        "comparison": "lte",
                        "target": 10.0,
                        "source_path": "ques1_results.json",
                    }
                ],
                metrics=[
                    {
                        "id": "objective",
                        "label": "目标值",
                        "value": 10.0,
                        "unit": "无量纲",
                        "explanation": "由本次实际计算结果读取。",
                        "source_path": "ques1_results.json",
                    },
                    {
                        "id": "pressure_stability_150MPa",
                        "label": "150MPa 压力稳定度",
                        "value": 999.0,
                        "unit": "MPa",
                        "explanation": "由情景仿真表读取。",
                        "source_path": "ques1_results.json",
                    }
                ],
                figures=[],
            )

            self.assertTrue(recorded["ok"], recorded)
            self.assertFalse(recorded["feasible"])
            self.assertEqual(recorded["constraint_passed"], [True, False])
            with open(os.path.join(work_dir, MANIFEST_NAME), encoding="utf-8") as handle:
                manifest = json.load(handle)
            scenario_metric = next(
                item for item in manifest["subtasks"][0]["metrics"]
                if item["id"] == "pressure_stability_150MPa"
            )
            self.assertEqual(scenario_metric["value"], 10.5)
            self.assertEqual(scenario_metric["source"]["path"], "ques1_acceptance_metrics.csv")

    def test_recorder_requires_metric_and_constraint_values_in_bound_source(self):
        with tempfile.TemporaryDirectory() as work_dir:
            result_path = os.path.join(work_dir, "ques2_fit_results.json")
            with open(result_path, "w", encoding="utf-8") as handle:
                json.dump({"thickness_nm": 2731.8, "fit_r_squared": 0.154328}, handle)

            recorded = record_execution_evidence(
                work_dir,
                subtask_id="ques2",
                constraints=[
                    {
                        "id": "fit_r_squared",
                        "actual": 0.9,
                        "comparison": "gte",
                        "target": 0.8,
                        "source_path": "ques2_fit_results.json",
                    }
                ],
                metrics=[
                    {
                        "id": "thickness_nm",
                        "label": "外延层厚度",
                        "value": 10562.36,
                        "unit": "nm",
                        "explanation": "联合拟合结果。",
                        "source_path": "ques2_fit_results.json",
                    }
                ],
                figures=[],
            )

            self.assertFalse(recorded["ok"])
            errors = " ".join(recorded["errors"])
            self.assertIn("actual=0.9 无法在 source_path 中复查", errors)
            self.assertIn("value=10562.36 无法在 source_path 中复查", errors)

    def test_final_validator_rechecks_model_plan_comparison_for_v1_manifest(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            result_path = os.path.join(work_dir, "ques2_fit_results.json")
            with open(result_path, "w", encoding="utf-8") as handle:
                json.dump({"fit_r_squared": 0.1543}, handle)
            with open(
                os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(
                    {
                        "model_plan": {
                            "subtasks": {
                                "ques2": {
                                    "acceptance_metrics": [
                                        {
                                            "key": "fit_r_squared",
                                            "comparator": "gt",
                                            "target": 0.95,
                                        }
                                    ]
                                }
                            }
                        }
                    },
                    handle,
                )
            with open(
                os.path.join(work_dir, MANIFEST_NAME), "w", encoding="utf-8"
            ) as handle:
                json.dump(
                    {
                        "schema_version": "mathmodel.execution-validation.v1",
                        "status": "PASS",
                        "metrics": [
                            {
                                "id": "fit_r_squared",
                                "label": "拟合优度",
                                "value": 0.1543,
                                "unit": "无量纲",
                                "explanation": "由拟合残差计算。",
                            }
                        ],
                        "subtasks": [
                            {
                                "id": "ques2",
                                "executed": True,
                                "feasible": True,
                                "constraints": [
                                    {
                                        "id": "fit_r_squared",
                                        "actual": 0.1543,
                                        "comparison": "lte",
                                        "target": 0.95,
                                        "source": {
                                            "path": "ques2_fit_results.json",
                                            "sha256": _sha256(result_path),
                                        },
                                    }
                                ],
                                "metrics": [],
                                "figures": [],
                            }
                        ],
                    },
                    handle,
                )

            report = validate_execution_artifacts(work_dir, required_subtasks=["ques2"])
            contract_check = next(
                item
                for item in report["checks"]
                if item["id"] == "ques2.plan_acceptance_contract"
            )
            self.assertFalse(contract_check["passed"])
            self.assertEqual(report["status"], "FAIL")

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
            self.assertTrue(
                os.path.exists(os.path.join(work_dir, REPRODUCIBILITY_NAME))
            )
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
                            "source_path": source_name,
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

    def test_optical_fitting_contract_does_not_require_mass_or_flow_balance(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            manifest_path = os.path.join(work_dir, "execution_validation.json")
            with open(manifest_path, encoding="utf-8") as handle:
                manifest = json.load(handle)
            result_path = os.path.join(work_dir, "results.json")
            with open(result_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {"mean_pressure_mpa": 100.0, "fitting_residual_rmse": 0.001},
                    handle,
                )
            manifest["subtasks"][0]["constraints"] = [
                {
                    "id": "fitting_residual_rmse",
                    "actual": 0.001,
                    "comparison": "lte",
                    "target": 0.01,
                    "source": {
                        "path": "results.json",
                        "sha256": _sha256(result_path),
                    },
                }
            ]
            manifest["subtasks"][0]["metrics"] = [
                {
                    "id": "fitting_residual_rmse",
                    "label": "拟合残差均方根误差",
                    "value": 0.001,
                    "unit": "无量纲",
                    "explanation": "由光谱拟合数组和实测数组计算。",
                }
            ]
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle, ensure_ascii=False)
            with open(os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "model_plan": {
                            "subtasks": {
                                "ques3": {
                                    "acceptance_metrics": [
                                        {
                                            "key": "fitting_residual_rmse",
                                            "label": "拟合残差均方根误差",
                                            "comparator": "le",
                                            "target": 0.01,
                                            "description": "检查多光束光学模型的拟合误差。",
                                        }
                                    ]
                                }
                            }
                        }
                    },
                    handle,
                    ensure_ascii=False,
                )

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

    def test_formal_subtask_without_manifest_writes_fail_report(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)

            report = write_execution_validation_report(
                work_dir, required_subtasks=["ques1"]
            )

            self.assertEqual(report["status"], "FAIL")
            self.assertFalse(
                next(item for item in report["checks"] if item["id"] == "execution_manifest")["passed"]
            )

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
            with open(os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "model_plan": {
                            "subtasks": {
                                "ques3": {
                                    "acceptance_metrics": [
                                        {
                                            "key": "mass_balance_residual",
                                            "label": "质量守恒残差",
                                            "description": "由供回油流量平衡计算。",
                                        }
                                    ]
                                }
                            }
                        }
                    },
                    handle,
                    ensure_ascii=False,
                )

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

    def test_gt_constraint_is_checked_without_inventing_pressure_fluctuation_limit(self):
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
            self.assertFalse(
                any(item["id"].startswith("pressure_stability.") for item in report["checks"])
            )

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

    def test_model_plan_expected_artifact_must_exist_and_be_nonempty(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            with open(os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "model_plan": {
                            "subtasks": {
                                "ques3": {
                                    "expected_artifacts": [
                                        {
                                            "path": "ques3_model_comparison.csv",
                                            "kind": "result_table",
                                            "description": "两种模型的同口径结果表",
                                        }
                                    ]
                                }
                            }
                        }
                    },
                    handle,
                    ensure_ascii=False,
                )

            report = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])

            self.assertEqual(report["status"], "FAIL")
            check = next(item for item in report["checks"] if item["id"] == "ques3.expected_artifact.0")
            self.assertFalse(check["passed"])

    def test_planned_response_scan_rejects_a_flat_model_curve(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            with open(os.path.join(work_dir, "ques3_thickness_scan.csv"), "w", encoding="utf-8-sig") as handle:
                # The overall response range is nonzero because the two
                # angles have different baselines, but each displayed scan is
                # flat and therefore cannot identify thickness.
                handle.write(
                    "angle_deg,thickness_um,R_model_mid\n"
                    "10,1.0,0.2\n10,2.0,0.2\n10,3.0,0.2\n"
                    "15,1.0,0.3\n15,2.0,0.3\n15,3.0,0.3\n"
                )
            with open(os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "model_plan": {
                            "subtasks": {
                                "ques3": {
                                    "expected_artifacts": [
                                        {
                                            "path": "ques3_thickness_scan.csv",
                                            "kind": "figure_data",
                                            "description": "候选厚度扫描下的模型反射率响应",
                                        }
                                    ]
                                }
                            }
                        }
                    },
                    handle,
                    ensure_ascii=False,
                )

            report = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])

            self.assertEqual(report["status"], "FAIL")
            check = next(
                item for item in report["checks"]
                if item["id"] == "ques3.expected_artifact.0.response_variation"
            )
            self.assertFalse(check["passed"])
            self.assertEqual(check["evidence"]["degenerate_groups"], ["10", "15"])

    def test_planned_numeric_csv_cannot_be_a_text_only_placeholder(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            with open(os.path.join(work_dir, "ques3_results.csv"), "w", encoding="utf-8-sig") as handle:
                handle.write("status,comment\npassed,waiting for calculation\n")
            with open(os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "model_plan": {
                            "subtasks": {
                                "ques3": {
                                    "expected_artifacts": [
                                        {
                                            "path": "ques3_results.csv",
                                            "kind": "result_table",
                                            "description": "需要由实际计算写入的结果表",
                                        }
                                    ]
                                }
                            }
                        }
                    },
                    handle,
                    ensure_ascii=False,
                )

            report = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])

            check = next(item for item in report["checks"] if item["id"] == "ques3.expected_artifact.0.csv")
            self.assertFalse(check["passed"])
            self.assertIn("没有有限数值列", check["message"])

    def test_identifiability_plan_needs_a_diagnostic_beyond_finite_records(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            with open(os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "model_plan": {
                            "subtasks": {
                                "ques3": {
                                    "method": "使用多组初值和 Bootstrap 判断参数可辨识性与局部解分支。",
                                    "constraints": [],
                                    "visualization": "展示不同初值的拟合结果。",
                                    "expected_artifacts": [],
                                }
                            }
                        }
                    },
                    handle,
                    ensure_ascii=False,
                )

            missing = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])
            check = next(item for item in missing["checks"] if item["id"] == "ques3.identifiability_evidence")
            self.assertFalse(check["passed"])

            manifest_path = os.path.join(work_dir, MANIFEST_NAME)
            with open(manifest_path, encoding="utf-8") as handle:
                manifest = json.load(handle)
            manifest["subtasks"][0]["metrics"].append(
                {
                    "id": "parameter_identifiability_status",
                    "label": "参数可辨识性状态",
                    "value": 1.0,
                    "unit": "1=稳定识别",
                    "explanation": "多初值均收敛到同一分支，Bootstrap 区间与边界状态已记录。",
                }
            )
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle, ensure_ascii=False)

            recorded = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])
            check = next(item for item in recorded["checks"] if item["id"] == "ques3.identifiability_evidence")
            self.assertTrue(check["passed"], check)

    def test_declared_diagnostic_profile_needs_matching_execution_metric(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            with open(os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "model_plan": {
                            "subtasks": {
                                "ques3": {
                                    "diagnostic_profile": "optimization",
                                    "diagnostic_requirements": ["记录求解器状态和可行性。"],
                                }
                            }
                        }
                    },
                    handle,
                    ensure_ascii=False,
                )

            missing = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])
            check = next(item for item in missing["checks"] if item["id"] == "ques3.diagnostic_profile")
            self.assertFalse(check["passed"])

            manifest_path = os.path.join(work_dir, MANIFEST_NAME)
            with open(manifest_path, encoding="utf-8") as handle:
                manifest = json.load(handle)
            manifest["subtasks"][0]["metrics"].extend(
                [
                    {
                        "id": "solver_status",
                        "label": "求解器状态",
                        "value": 1.0,
                        "unit": "1=optimal",
                        "explanation": "线性规划求解器返回 optimal。",
                    },
                    {
                        "id": "feasibility_check",
                        "label": "约束可行性",
                        "value": 1.0,
                        "unit": "1=可行",
                        "explanation": "求解器返回 optimal 后独立检查约束可行性。",
                    },
                ]
            )
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle, ensure_ascii=False)

            recorded = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])
            check = next(item for item in recorded["checks"] if item["id"] == "ques3.diagnostic_profile")
            self.assertTrue(check["passed"], check)

    def test_recording_simulation_evidence_requires_each_explicit_diagnostic(self):
        with tempfile.TemporaryDirectory() as work_dir:
            source_path = os.path.join(work_dir, "ques3_results.csv")
            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "id,value\nmean_pressure,100.0\nrelief_valve_activity,1.0\n"
                    "mass_balance_residual,0.001\n"
                )
            with open(os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "model_plan": {
                            "subtasks": {
                                "ques3": {
                                    "diagnostic_profile": "simulation",
                                    "diagnostic_requirements": [
                                        "验证减压阀仅在阈值上方开启。",
                                        "验证系统总质量守恒并记录残差。",
                                    ],
                                }
                            }
                        }
                    },
                    handle,
                    ensure_ascii=False,
                )

            missing = record_execution_evidence(
                work_dir,
                subtask_id="ques3",
                constraints=[{
                    "id": "pressure_recorded",
                    "actual": 100.0,
                    "comparison": "abs_diff_lte",
                    "target": 100.0,
                    "tolerance": 0.0,
                    "source_path": "ques3_results.csv",
                }],
                metrics=[{
                    "id": "mean_pressure",
                    "label": "油管平均压力",
                    "value": 100.0,
                    "unit": "MPa",
                    "explanation": "由压力时序数组计算。",
                    "source_path": "ques3_results.csv",
                }],
            )
            self.assertFalse(missing["ok"])
            self.assertTrue(any("质量守恒" in error for error in missing["errors"]))
            self.assertTrue(any("减压阀" in error for error in missing["errors"]))

            recorded = record_execution_evidence(
                work_dir,
                subtask_id="ques3",
                constraints=[{
                    "id": "pressure_recorded",
                    "actual": 100.0,
                    "comparison": "abs_diff_lte",
                    "target": 100.0,
                    "tolerance": 0.0,
                    "source_path": "ques3_results.csv",
                }],
                metrics=[
                    {
                        "id": "relief_valve_activity",
                        "label": "减压阀开启核验",
                        "value": 1.0,
                        "unit": "1=已核验",
                        "explanation": "减压阀仅在压力超过阈值时开启。",
                        "source_path": "ques3_results.csv",
                    },
                    {
                        "id": "mass_balance_residual",
                        "label": "质量守恒残差",
                        "value": 0.001,
                        "unit": "mm³",
                        "explanation": "由真实时序数组积分得到的单周期质量守恒残差。",
                        "source_path": "ques3_results.csv",
                    },
                ],
            )
            self.assertTrue(recorded["ok"], recorded)


class PressureTargetEvidenceTest(unittest.TestCase):
    """题面给出压力目标时，必须留下可复核的实际压力偏差证据。

    这些用例替代早期写死的“100 MPa 一律峰峰值 ≤15 MPa”门禁：阈值只能来自
    题面或 ModelPlan，但“是否记录了实际偏差”本身是硬要求，否则删除硬阈值
    会让大幅振荡的控制方案无声通过。
    """

    def _write_pressure_contract(self, work_dir: str, *, target: float = 100.0) -> None:
        key = f"{target:g}".replace(".", "_")
        with open(
            os.path.join(work_dir, "problem_contract.json"), "w", encoding="utf-8"
        ) as handle:
            json.dump(
                {
                    "required_requirements": [
                        {
                            "key": f"target_pressure_{key}_mpa",
                            "label": f"方案须检验压力目标为 {target:g} MPa 的约束是否满足",
                            "evidence_terms": [f"{target:g}MPa"],
                        }
                    ]
                },
                handle,
            )

    def _set_metrics(self, work_dir: str, metrics: list[dict]) -> None:
        manifest_path = os.path.join(work_dir, MANIFEST_NAME)
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        manifest["subtasks"][0]["metrics"] = metrics
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False)

    def test_pressure_target_without_deviation_metric_is_rejected(self):
        """只登记“仿真完成=1”这类标志位，不构成压力目标的验收证据。"""
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            self._write_pressure_contract(work_dir)
            self._set_metrics(
                work_dir,
                [
                    {
                        "id": "ode_solved",
                        "label": "ODE求解完成",
                        "value": 1.0,
                        "unit": "标志",
                        "explanation": "已生成可复核的压力时序与求解器状态。",
                    }
                ],
            )

            report = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])

            self.assertEqual(report["status"], "FAIL")
            check = next(
                item
                for item in report["checks"]
                if item["id"] == "ques3.pressure_target_evidence"
            )
            self.assertFalse(check["passed"])

    def test_recorded_pressure_deviation_satisfies_the_gate(self):
        """记录了实际峰峰值/偏差即可通过；门禁不自行编造合格阈值。"""
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            self._write_pressure_contract(work_dir)
            self._set_metrics(
                work_dir,
                [
                    {
                        "id": "q1_pressure_peak_to_peak",
                        "label": "稳态压力峰峰值",
                        "value": 68.02,
                        "unit": "MPa",
                        "explanation": "由本题压力时序数组直接计算。",
                    }
                ],
            )

            report = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])

            check = next(
                item
                for item in report["checks"]
                if item["id"] == "ques3.pressure_target_evidence"
            )
            self.assertTrue(check["passed"], check)

    def test_plan_declared_pressure_bound_is_enforced_by_its_own_number(self):
        """ModelPlan 自己声明了数值上限时，超限必须判失败。"""
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            self._write_pressure_contract(work_dir)
            self._set_metrics(
                work_dir,
                [
                    {
                        "id": "pressure_peak_to_peak",
                        "label": "稳态压力峰峰值",
                        "value": 68.02,
                        "unit": "MPa",
                        "explanation": "由本题压力时序数组直接计算。",
                    }
                ],
            )
            with open(
                os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(
                    {
                        "model_plan": {
                            "subtasks": {
                                "ques3": {
                                    "acceptance_metrics": [
                                        {
                                            "key": "pressure_peak_to_peak",
                                            "label": "稳态压力峰峰值",
                                            "comparator": "le",
                                            "target": 15.0,
                                            "unit": "MPa",
                                        }
                                    ]
                                }
                            }
                        }
                    },
                    handle,
                )

            report = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])

            check = next(
                item
                for item in report["checks"]
                if item["id"] == "ques3.pressure_target_evidence"
            )
            self.assertFalse(check["passed"], check)
            self.assertEqual(check["evidence"].get("declared_target"), 15.0)

    def test_absolute_pressure_ceiling_is_not_used_as_a_deviation_bound(self):
        """绝对压力上限不是波动上限，不能拿来判峰峰值。

        真实任务里出现过 `最大压力超调 le 150 MPa`、`柱塞腔峰值压力 le 200 MPa`
        这类**绝对压力天花板**。把它们当作波动上限，等于用 150 MPa 的尺子量
        68 MPa 的峰峰值——永远不会失败，门禁被悄悄架空。这类量级不匹配的阈值
        必须落回“已记录、待人工判定”，而不是伪装成已达标。
        """
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            self._write_pressure_contract(work_dir)
            self._set_metrics(
                work_dir,
                [
                    {
                        "id": "pressure_peak_to_peak",
                        "label": "稳态压力峰峰值",
                        "value": 68.02,
                        "unit": "MPa",
                        "explanation": "由本题压力时序数组直接计算。",
                    }
                ],
            )
            with open(
                os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(
                    {
                        "model_plan": {
                            "subtasks": {
                                "ques3": {
                                    "acceptance_metrics": [
                                        {
                                            "key": "max_pressure_violation",
                                            "label": "最大压力超调",
                                            "comparator": "le",
                                            "target": 150.0,
                                            "unit": "MPa",
                                        }
                                    ]
                                }
                            }
                        }
                    },
                    handle,
                )

            report = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])

            check = next(
                item
                for item in report["checks"]
                if item["id"] == "ques3.pressure_target_evidence"
            )
            self.assertIsNone(check["evidence"].get("declared_target"), check)
            self.assertTrue(
                check["evidence"].get("requires_human_review"),
                check,
            )

    def test_task_without_pressure_target_is_not_affected(self):
        """没有压力目标的题（如线性规划）不应被这条门禁波及。"""
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            with open(
                os.path.join(work_dir, "problem_contract.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(
                    {"required_requirements": [{"key": "data_analysis_evidence"}]},
                    handle,
                )

            report = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])

            self.assertFalse(
                any(
                    item["id"] == "ques3.pressure_target_evidence"
                    for item in report["checks"]
                )
            )

    def test_solver_convergence_delta_is_not_accepted_as_pressure_deviation(self):
        """步长收敛差不是解本身的压力波动，不能顶替峰峰值证据。

        真实 2019A 任务里 ques2/ques3 只登记了 ``dt_convergence_pp_delta_MPa``
        （两种步长解之间的峰峰值差，0.05 MPa 量级），而解本身的压力峰峰值曾达到
        68 MPa。把收敛量当作波动证据，等于用数值精度冒充物理达标。
        """
        with tempfile.TemporaryDirectory() as work_dir:
            _write_notebook(work_dir)
            _write_manifest(work_dir)
            self._write_pressure_contract(work_dir)
            self._set_metrics(
                work_dir,
                [
                    {
                        "id": "dt_convergence_pp_delta_MPa",
                        "label": "步长收敛峰峰值差",
                        "value": 0.0455,
                        "unit": "MPa",
                        "explanation": "dt 减半后两解的峰峰值之差，用于确认数值收敛。",
                    }
                ],
            )

            report = validate_execution_artifacts(work_dir, required_subtasks=["ques3"])

            self.assertEqual(report["status"], "FAIL")
            check = next(
                item
                for item in report["checks"]
                if item["id"] == "ques3.pressure_target_evidence"
            )
            self.assertFalse(check["passed"])


if __name__ == "__main__":
    unittest.main()
