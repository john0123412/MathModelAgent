"""Human modeling gate tests."""

import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from app.core.agents.modeler_agent import ModelerAgent
from app.core.workflow import MathModelWorkFlow
from app.core.checkpoint import CheckpointManager, TaskCheckpoint
from app.routers.modeling_router import (
    CodexModelingRequest,
    _mark_modeling_decision_revision_failed,
    approve_modeling,
    submit_codex_modeling,
)
from app.schemas.A2A import (
    AcceptanceMetric,
    CoordinatorToModeler,
    ExpectedArtifact,
    ModelPlan,
    ModelerToCoder,
    SubtaskPlan,
)
from app.schemas.enums import CompTemplate, ExportProfile, FormatOutPut
from app.schemas.request import Problem
from app.schemas.problem_contract import ProblemContract
from app.core.llm.types import StandardResponse, Usage


class _InvalidModelerLLM:
    """Return malformed plans without contacting a provider."""

    def __init__(self):
        self.calls = 0

    async def chat(self, **_kwargs):
        self.calls += 1
        return StandardResponse(content="{}")


class _SequencedModelerLLM:
    """Return deterministic Modeler responses and retain call contracts."""

    def __init__(self, responses: list[StandardResponse]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _valid_codex_plan() -> ModelPlan:
    return ModelPlan(
        eda="核验题面中的目标、变量和资源约束。",
        subtasks={
            "ques1": SubtaskPlan(
                inputs=["题面资源约束"],
                method="定义决策变量和目标函数，求解线性规划并逐项回代核验全部约束。",
                constraints=["决策变量非负并满足题面约束"],
                expected_artifacts=[
                    ExpectedArtifact(
                        path="ques1_results.csv",
                        kind="result_table",
                        description="最优解与目标函数值",
                    )
                ],
                acceptance_metrics=[
                    AcceptanceMetric(
                        key="objective_value",
                        label="目标函数值",
                        comparator="ge",
                        target=0,
                        description="由求解得到的目标函数值",
                    )
                ],
                visualization="绘制可行域和最优点。",
            )
        },
        sensitivity_analysis="改变资源上限并比较最优目标值。",
    )


class TestModelerRepairBudget(unittest.IsolatedAsyncioTestCase):
    async def test_modeler_stops_after_two_invalid_plans_without_third_call(self):
        model = _InvalidModelerLLM()
        agent = ModelerAgent(task_id="unit-modeler", model=model)
        coordinator = CoordinatorToModeler(
            questions={"ques_count": 1, "ques1": "完成建模"},
            ques_count=1,
            problem_contract=ProblemContract(),
        )

        with self.assertRaisesRegex(ValueError, "连续返回不合格"):
            await agent.run(coordinator)

        self.assertEqual(model.calls, 2)
        corrections = [
            message
            for message in agent.chat_history
            if message.get("role") == "user" and "固定协议" in message.get("content", "")
        ]
        self.assertEqual(len(corrections), 1)

    async def test_modeler_recovers_a_blank_response_in_nonthinking_json_mode(self):
        valid_plan = json.dumps(_valid_codex_plan().model_dump(), ensure_ascii=False)
        model = _SequencedModelerLLM(
            [
                StandardResponse(
                    content=None,
                    reasoning_content="partial reasoning is intentionally not replayed",
                    finish_reason="length",
                    usage=Usage(completion_tokens=8192, reasoning_tokens=8192),
                ),
                StandardResponse(content=valid_plan, finish_reason="stop"),
            ]
        )
        agent = ModelerAgent(task_id="unit-modeler", model=model)
        coordinator = CoordinatorToModeler(
            questions={"ques_count": 1, "ques1": "完成建模"},
            ques_count=1,
            problem_contract=ProblemContract(),
        )

        result = await agent.run(coordinator)

        self.assertIn("ques1", result.model_plan.subtasks)
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(
            [call["thinking"] for call in model.calls], [False, False]
        )
        self.assertEqual(
            [call["response_format"] for call in model.calls],
            [{"type": "json_object"}, {"type": "json_object"}],
        )
        self.assertFalse(
            any("reasoning_content" in message for message in agent.chat_history)
        )

    async def test_modeler_applies_targeted_basis_description_patch(self):
        plan = _valid_codex_plan()
        plan.subtasks["ques1"].acceptance_metrics = [
            AcceptanceMetric(
                key="n_consistency",
                label="样本一致性偏差",
                comparator="eq",
                target=1,
                description="两组样本量一致时记为 1。",
            )
        ]
        model = _SequencedModelerLLM(
            [
                StandardResponse(
                    content=json.dumps(plan.model_dump(), ensure_ascii=False),
                    finish_reason="stop",
                ),
                StandardResponse(
                    content=json.dumps(
                        {
                            "description_updates": [
                                {
                                    "subtask": "ques1",
                                    "key": "n_consistency",
                                    "description": (
                                        "n_consistency=1 的目标值依据：题目原文规定样本必须一一对应。"
                                    ),
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                    finish_reason="stop",
                ),
            ]
        )
        agent = ModelerAgent(task_id="unit-modeler", model=model)
        coordinator = CoordinatorToModeler(
            questions={"ques_count": 1, "ques1": "完成建模"},
            ques_count=1,
            problem_contract=ProblemContract(),
        )

        result = await agent.run(coordinator)

        self.assertEqual(len(model.calls), 2)
        self.assertTrue(all(call["thinking"] is False for call in model.calls))
        self.assertEqual(
            result.model_plan.subtasks["ques1"].acceptance_metrics[0].description,
            "n_consistency=1 的目标值依据：题目原文规定样本必须一一对应。",
        )
        repair_prompt = agent.chat_history[-1]["content"]
        self.assertIn("description_updates", repair_prompt)
        self.assertIn("不要重新输出整份 ModelPlan", repair_prompt)

    async def test_modeler_bounds_two_blank_responses_without_a_third_call(self):
        model = _SequencedModelerLLM(
            [
                StandardResponse(content=None, finish_reason="length"),
                StandardResponse(content="", finish_reason="stop"),
            ]
        )
        agent = ModelerAgent(task_id="unit-modeler", model=model)
        coordinator = CoordinatorToModeler(
            questions={"ques_count": 1, "ques1": "完成建模"},
            ques_count=1,
            problem_contract=ProblemContract(),
        )

        with self.assertRaisesRegex(ValueError, "连续返回不合格.*返回内容为空"):
            await agent.run(coordinator)

        self.assertEqual(len(model.calls), 2)
        self.assertTrue(all(call["thinking"] is False for call in model.calls))


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


class TestCodexCancelledTakeover(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _save_checkpoint(work_dir: str, *, require_model_review: bool = True, **kwargs):
        CheckpointManager(work_dir).save(
            TaskCheckpoint(
                task_id="unit-task",
                ques_all="求一个线性规划最优解。",
                comp_template="CHINA",
                format_output="Markdown",
                export_profile="cumcm2026",
                require_model_review=require_model_review,
                questions={"ques_count": 1, "ques1": "求最优生产方案。"},
                ques_count=1,
                modeler_response={},
                updated_at="2026-07-20T00:00:00",
                **kwargs,
            )
        )

    async def test_pristine_cancelled_checkpoint_enters_waiting_review(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._save_checkpoint(work_dir)
            with (
                patch("app.routers.modeling_router.get_work_dir", return_value=work_dir),
                patch(
                    "app.routers.modeling_router.read_task_status",
                    return_value={"status": "cancelled"},
                ),
                patch("app.core.workflow.get_work_dir", return_value=work_dir),
                patch("app.routers.modeling_router.write_task_status") as write_status,
                patch("app.routers.modeling_router.redis_manager.set", new=AsyncMock()),
                patch(
                    "app.routers.modeling_router.redis_manager.publish_message",
                    new=AsyncMock(),
                ),
            ):
                result = await submit_codex_modeling(
                    "unit-task",
                    CodexModelingRequest(modeler_response=ModelerToCoder(model_plan=_valid_codex_plan())),
                )

            self.assertEqual(result.status, "waiting_review")
            write_status.assert_called_once_with(
                "unit-task", "waiting_review", "Codex 建模方案已写入，等待人工确认"
            )
            saved = CheckpointManager(work_dir).load()
            self.assertTrue(saved.modeler_response)
            with open(os.path.join(work_dir, "modeling_decision.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["status"], "waiting_review")

    async def test_cancelled_checkpoint_with_execution_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._save_checkpoint(
                work_dir,
                completed_phases={
                    "ques1": {
                        "key": "ques1",
                        "completed_at": "2026-07-20T00:00:00",
                    }
                },
            )
            with (
                patch("app.routers.modeling_router.get_work_dir", return_value=work_dir),
                patch(
                    "app.routers.modeling_router.read_task_status",
                    return_value={"status": "cancelled"},
                ),
                patch("app.routers.modeling_router.MathModelWorkFlow") as workflow_cls,
            ):
                with self.assertRaises(HTTPException) as caught:
                    await submit_codex_modeling(
                        "unit-task",
                        CodexModelingRequest(modeler_response=ModelerToCoder(model_plan=_valid_codex_plan())),
                    )

            self.assertEqual(caught.exception.status_code, 409)
            self.assertIn("completed_phases", str(caught.exception.detail))
            workflow_cls.assert_not_called()

    async def test_cancelled_checkpoint_without_model_review_gate_is_rejected(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._save_checkpoint(work_dir, require_model_review=False)
            with (
                patch("app.routers.modeling_router.get_work_dir", return_value=work_dir),
                patch(
                    "app.routers.modeling_router.read_task_status",
                    return_value={"status": "cancelled"},
                ),
            ):
                with self.assertRaises(HTTPException) as caught:
                    await submit_codex_modeling(
                        "unit-task",
                        CodexModelingRequest(modeler_response=ModelerToCoder(model_plan=_valid_codex_plan())),
                    )

            self.assertEqual(caught.exception.status_code, 409)
            self.assertIn("未启用", str(caught.exception.detail))


class TestHumanModelingGateResume(unittest.IsolatedAsyncioTestCase):
    async def test_remodeled_resume_reenters_review_before_building_agents(self):
        with tempfile.TemporaryDirectory() as work_dir:
            manager = CheckpointManager(work_dir)
            original = ModelerToCoder(questions_solution={"ques1": "旧方案"})
            rebuilt = ModelerToCoder(questions_solution={"ques1": "重建后的方案"})
            manager.save(
                TaskCheckpoint(
                    task_id="unit-task",
                    ques_all="题面",
                    comp_template="CHINA",
                    format_output="Markdown",
                    export_profile="cumcm2026",
                    require_model_review=True,
                    questions={"ques_count": 1, "ques1": "问题一"},
                    ques_count=1,
                    modeler_response=original.model_dump(),
                    updated_at="2026-08-08T00:00:00",
                )
            )
            workflow = MathModelWorkFlow()
            with (
                patch("app.core.workflow.get_work_dir", return_value=work_dir),
                patch("app.core.workflow.redis_manager.publish_message", AsyncMock()),
                patch("app.core.workflow.LLMFactory") as llm_factory,
                patch.object(
                    workflow,
                    "_validate_plan_with_one_remodel",
                    AsyncMock(return_value=rebuilt),
                ),
                patch.object(workflow, "_build_agents", AsyncMock()) as build_agents,
            ):
                llm_factory.return_value.get_all_llms.return_value = (
                    object(), object(), object(), object()
                )
                result = await workflow.resume("unit-task")

            self.assertEqual(result, "waiting_review")
            build_agents.assert_not_awaited()
            saved = manager.load()
            self.assertEqual(saved.modeler_response, rebuilt.model_dump())
            with open(os.path.join(work_dir, "modeling_decision.json"), encoding="utf-8") as handle:
                decision = json.load(handle)
            self.assertEqual(decision["status"], "waiting_review")
            self.assertFalse(decision["review"]["approved"])
            self.assertEqual(decision["modeler_response"], rebuilt.model_dump())

    async def test_approval_rejects_plan_that_differs_from_checkpoint(self):
        with tempfile.TemporaryDirectory() as work_dir:
            checkpoint_plan = {"questions_solution": {"ques1": "检查点方案"}}
            CheckpointManager(work_dir).save(
                TaskCheckpoint(
                    task_id="unit-task",
                    ques_all="题面",
                    comp_template="CHINA",
                    format_output="Markdown",
                    export_profile="cumcm2026",
                    require_model_review=True,
                    questions={"ques_count": 1, "ques1": "问题一"},
                    ques_count=1,
                    modeler_response=checkpoint_plan,
                    updated_at="2026-08-08T00:00:00",
                )
            )
            with open(os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8") as handle:
                json.dump({"questions_solution": {"ques1": "已替换方案"}}, handle)
            with open(os.path.join(work_dir, "modeling_decision.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "status": "waiting_review",
                        "modeler_response": checkpoint_plan,
                        "review": {"approved": False},
                    },
                    handle,
                )
            with open(os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "waiting_review"}, handle)

            with patch("app.routers.modeling_router.get_work_dir", return_value=work_dir):
                with self.assertRaisesRegex(Exception, "当前建模方案已变化") as caught:
                    await approve_modeling("unit-task", background_tasks=AsyncMock())

        self.assertEqual(caught.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
