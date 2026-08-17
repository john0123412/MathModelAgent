"""Unit tests for Phase 2 architectural hardening."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path
import unittest

from app.schemas.problem_contract import (
    BoundaryCondition,
    ProblemContract,
    validate_modeler_plan,
)
from app.tools.execution_validation import (
    _anti_pseudo_crosscheck_issues,
    _dimensional_parameter_sanity_issues,
)


class TestPhase2Hardening(unittest.TestCase):
    """Test boundary conditions, diagnostic group expansions, parameter sanity and crosscheck gates."""

    def test_boundary_condition_prompt_generation(self) -> None:
        """Test BoundaryCondition schema and to_prompt rendering."""
        contract = ProblemContract(
            boundary_conditions=[
                BoundaryCondition(
                    axis="x",
                    boundary_type="clamped_electrode",
                    is_periodic=False,
                    description="左右两面为带电表面，不可跨极板周期连通",
                ),
                BoundaryCondition(
                    axis="y",
                    boundary_type="periodic",
                    is_periodic=True,
                    description="Y轴方向采用27镜像周期边界",
                ),
            ]
        )
        prompt = contract.to_prompt()
        self.assertIn("【边界与拓扑契约】", prompt)
        self.assertIn("坐标轴 x: clamped_electrode (非周期/独立边界)", prompt)
        self.assertIn("坐标轴 y: periodic (周期边界)", prompt)

    def test_expanded_diagnostic_requirement_matching(self) -> None:
        """Test that expanded diagnostic requirements (Monte Carlo, Geometry, Convergence) match."""
        contract = ProblemContract()
        plan = {
            "model_plan": {
                "eda": "核验题面与数据",
                "subtasks": {
                    "ques1": {
                        "inputs": ["题面数据"],
                        "method": "几何相交与27镜像周期计算",
                        "constraints": ["微构体空间界限"],
                        "diagnostic_profile": "simulation",
                        "diagnostic_requirements": [
                            "蒙特卡洛方差与收敛性分析",
                            "有限圆柱几何碰撞距离",
                        ],
                        "expected_artifacts": [
                            {"path": "ques1_results.csv", "kind": "result_table", "description": "结果表"}
                        ],
                        "acceptance_metrics": [
                            {
                                "key": "q1_mc_variance",
                                "label": "蒙特卡洛方差统计",
                                "comparator": "lt",
                                "target": 0.05,
                                "description": "由结果表计算MC方差",
                            },
                            {
                                "key": "q1_geometric_distance_audit",
                                "label": "几何距离碰撞审计",
                                "comparator": "ge",
                                "target": 0.0,
                                "description": "由参数表记录空间几何距离",
                            },
                        ],
                        "visualization": "绘制分布图",
                    }
                },
                "sensitivity_analysis": "敏感性分析",
            }
        }
        res = validate_modeler_plan(contract, plan)
        self.assertTrue(res.valid, f"Expected valid, got violations: {res.violations}, missing: {res.missing_requirements}")

    def test_boolean_conduction_outcome_metric_rejection(self) -> None:
        """Test that forcing uncalculated boolean conduction outcome is rejected."""
        contract = ProblemContract()
        plan = {
            "model_plan": {
                "eda": "核验题面与数据",
                "subtasks": {
                    "ques1": {
                        "inputs": ["附件1数据"],
                        "method": "分析微构体是否导通",
                        "constraints": ["空间界限"],
                        "expected_artifacts": [
                            {"path": "ques1_results.csv", "kind": "result_table", "description": "结果表"}
                        ],
                        "acceptance_metrics": [
                            {
                                "key": "q1_is_conductive",
                                "label": "组1是否导通标志",
                                "comparator": "eq",
                                "target": 0.0,
                                "description": "预置组1不导通结论",
                            }
                        ],
                        "visualization": "图表",
                    }
                },
                "sensitivity_analysis": "敏感性分析",
            }
        }
        res = validate_modeler_plan(
            contract,
            plan,
            questions={"ques1": "问题1：试分析三个微构体是否导通，分别给出导通情况。"},
        )
        self.assertFalse(res.valid)
        self.assertTrue(any("强制开放性判定结论" in v for v in res.violations))

    def test_dimensional_parameter_sanity_error_detection(self) -> None:
        """Test detection of 10000^3 = 1e15 arithmetic error in input_parameter_audit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            audit_file = work_dir / "ques1_input_parameter_audit.csv"
            with audit_file.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["parameter", "symbol", "value", "unit", "notes"])
                writer.writerow(["微构体体积", "V", "1e15", "nm^3", "10000^3=1e15 严重笔误"])

            issues = _dimensional_parameter_sanity_issues(work_dir)
            self.assertTrue(any(not issue["passed"] for issue in issues))
            self.assertTrue(any("数量级严重笔误" in issue["message"] for issue in issues))

    def test_dimensional_parameter_sanity_pass(self) -> None:
        """Test passing valid dimensional parameters (10000^3 = 1e12)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            audit_file = work_dir / "ques1_input_parameter_audit.csv"
            with audit_file.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["parameter", "symbol", "value", "unit", "notes"])
                writer.writerow(["微构体体积", "V", "1e12", "nm^3", "10000^3=1e12 nm^3 (1000 um^3)"])

            issues = _dimensional_parameter_sanity_issues(work_dir)
            self.assertTrue(all(issue["passed"] for issue in issues))

    def test_anti_pseudo_crosscheck_detection(self) -> None:
        """Test detection of identical pseudo-crosscheck with swapped parameters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            crosscheck_file = work_dir / "ques1_crosscheck.csv"
            with crosscheck_file.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["pair_id", "algo1_dist", "algo2_dist", "diff"])
                for i in range(30):
                    # Identical values across all rows without independent method tag
                    writer.writerow([i, f"{10.0 + i:.6f}", f"{10.0 + i:.6f}", "0.000000"])

            issues = _anti_pseudo_crosscheck_issues(work_dir)
            self.assertTrue(any(not issue["passed"] for issue in issues))
            self.assertTrue(any("疑似伪复算" in issue["message"] for issue in issues))

    def test_anti_pseudo_crosscheck_pass_with_distinct_methods(self) -> None:
        """Test passing valid independent crosscheck with distinct method tags and realistic differences."""
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            crosscheck_file = work_dir / "ques1_crosscheck.csv"
            with crosscheck_file.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["pair_id", "analytical_dist", "numerical_optimization_dist", "diff"])
                for i in range(30):
                    v1 = 10.0 + i * 0.5
                    v2 = v1 + 1e-6 * (i % 3)
                    writer.writerow([i, f"{v1:.6f}", f"{v2:.6f}", f"{abs(v1 - v2):.6f}"])

            issues = _anti_pseudo_crosscheck_issues(work_dir)
            self.assertTrue(all(issue["passed"] for issue in issues))


if __name__ == "__main__":
    unittest.main()
