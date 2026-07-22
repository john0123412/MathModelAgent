"""Human modeling gate tests."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from app.core.workflow import MathModelWorkFlow
from app.core.checkpoint import CheckpointManager, TaskCheckpoint
from app.routers.modeling_router import _mark_modeling_decision_revision_failed
from app.schemas.A2A import (
    AcceptanceMetric,
    ExpectedArtifact,
    ModelPlan,
    ModelerToCoder,
    SubtaskPlan,
)
from app.schemas.enums import CompTemplate, ExportProfile, FormatOutPut
from app.schemas.request import Problem


class TestHumanModelingGateArtifacts(unittest.TestCase):
    def test_quality_review_approval_is_hash_bound_and_repair_is_single_use(self):
        with tempfile.TemporaryDirectory() as work_dir:
            manager = CheckpointManager(work_dir)
            manager.save(
                TaskCheckpoint(
                    task_id="unit-task",
                    ques_all="题面",
                    comp_template="CHINA",
                    format_output="Markdown",
                    require_model_review=True,
                    questions={"ques1": "问题一", "ques2": "问题二"},
                    ques_count=2,
                    modeler_response={"questions_solution": {}},
                    solution_coder_responses={"ques1": {}, "ques2": {}},
                    updated_at="2026-07-20T00:00:00",
                )
            )
            manager.record_quality_review_pending({"review_id": "hash-a"})
            with self.assertRaisesRegex(RuntimeError, "结果文件已变化"):
                manager.approve_quality_review("hash-b", "已逐题复核")

            manager.request_quality_repair("hash-a", ["ques2"], "修正质量守恒和量纲")
            saved = manager.load()
            self.assertIn("ques1", saved.solution_coder_responses)
            self.assertNotIn("ques2", saved.solution_coder_responses)
            self.assertEqual(saved.workflow_state, "quality_repair")

            manager.record_quality_review_pending({"review_id": "hash-a"})
            with self.assertRaisesRegex(RuntimeError, "一次质量复核定向返修"):
                manager.request_quality_repair("hash-a", ["ques2"], "再次返修")

    def test_write_modeling_decision_files(self):
        with tempfile.TemporaryDirectory() as work_dir:
            workflow = MathModelWorkFlow()
            workflow.task_id = "unit-task"
            workflow.work_dir = work_dir
            workflow.questions = {"ques1": "求最优生产方案"}
            workflow.ques_count = 1
            problem = Problem(
                task_id="unit-task",
                ques_all="题面",
                comp_template=CompTemplate.CHINA,
                format_output=FormatOutPut.Markdown,
                export_profile=ExportProfile.CUMCM2026,
                require_model_review=True,
            )
            modeler_response = ModelerToCoder(
                questions_solution={"ques1": "建立线性规划模型并做敏感性分析。"}
            )

            workflow._write_modeling_decision(problem, modeler_response)

            decision_json_path = os.path.join(work_dir, "modeling_decision.json")
            decision_md_path = os.path.join(work_dir, "modeling_decision.md")
            self.assertTrue(os.path.exists(decision_json_path))
            self.assertTrue(os.path.exists(decision_md_path))
            with open(decision_json_path, encoding="utf-8") as f:
                decision = json.load(f)
            self.assertEqual(decision["status"], "waiting_review")
            self.assertEqual(decision["export_profile"], "cumcm2026")
            self.assertTrue(decision["gate_enabled"])
            self.assertFalse(decision["review"]["approved"])
            with open(decision_md_path, encoding="utf-8") as f:
                decision_md = f.read()
            self.assertIn("建模方案人工确认", decision_md)
            self.assertIn("/modeling/unit-task/approve-modeling", decision_md)

    def test_modeling_revision_budget_is_single_use(self):
        with tempfile.TemporaryDirectory() as work_dir:
            manager = CheckpointManager(work_dir)
            manager.save(
                TaskCheckpoint(
                    task_id="unit-task",
                    ques_all="题面",
                    comp_template="China",
                    format_output="Markdown",
                    questions={"ques1": "测试问题"},
                    ques_count=1,
                    modeler_response={"questions_solution": {"ques1": "方案"}},
                    updated_at="2026-07-20T00:00:00",
                )
            )

            self.assertEqual(manager.record_modeling_revision_request(), 1)
            self.assertEqual(manager.load().workflow_state, "modeling_revision")
            with self.assertRaisesRegex(RuntimeError, "一次建模方案退回修订"):
                manager.record_modeling_revision_request()

    def test_revision_failure_updates_decision_state(self):
        with tempfile.TemporaryDirectory() as work_dir:
            decision_path = os.path.join(work_dir, "modeling_decision.json")
            with open(decision_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "status": "revising",
                        "review_history": [
                            {"action": "revision_requested", "comment": "修订意见"}
                        ],
                    },
                    f,
                )

            _mark_modeling_decision_revision_failed(work_dir, "provider unavailable")

            with open(decision_path, encoding="utf-8") as f:
                decision = json.load(f)
            self.assertEqual(decision["status"], "revision_failed")
            self.assertEqual(decision["review_history"][-1]["action"], "revision_failed")

    def test_codex_can_replace_failed_modeler_with_contract_validated_plan(self):
        with tempfile.TemporaryDirectory() as work_dir:
            manager = CheckpointManager(work_dir)
            manager.save(TaskCheckpoint(
                task_id="unit-task", ques_all="求一个线性规划最优解。",
                comp_template="CHINA", format_output="Markdown", export_profile="cumcm2026",
                require_model_review=True, questions={"ques1": "求最优生产方案。"},
                ques_count=1, modeler_response={}, updated_at="2026-07-20T00:00:00",
            ))
            plan = ModelPlan(
                eda="核验题面中的目标、变量和资源约束。",
                subtasks={"ques1": SubtaskPlan(
                    inputs=["题面资源约束"], method="定义决策变量和目标函数，求解线性规划并逐项回代核验全部约束。",
                    constraints=["决策变量非负并满足题面约束"],
                    expected_artifacts=[ExpectedArtifact(path="ques1_results.csv", kind="result_table", description="最优解与目标函数值")],
                    acceptance_metrics=[AcceptanceMetric(key="objective_value", label="目标函数值", comparator="ge", target=0, description="由求解得到的目标函数值")],
                    visualization="绘制可行域和最优点。",
                )}, sensitivity_analysis="改变资源上限并比较最优目标值。",
            )
            workflow = MathModelWorkFlow()
            with patch("app.core.workflow.get_work_dir", return_value=work_dir):
                workflow.accept_codex_modeling("unit-task", ModelerToCoder(model_plan=plan))
            saved = manager.load()
            self.assertEqual(saved.modeler_response["model_plan"]["schema_version"], "mathmodel.model-plan.v1")
            self.assertTrue(os.path.exists(os.path.join(work_dir, "modeling_decision.json")))


if __name__ == "__main__":
    unittest.main()
