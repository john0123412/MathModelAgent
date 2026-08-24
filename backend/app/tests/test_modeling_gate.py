"""Human modeling gate tests."""

import hashlib
import json
import os
from pathlib import Path
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
from app.routers import modeling_router


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
                diagnostic_profile="optimization",
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
                    diagnostic_profile="optimization",
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


class TestCodexTakeover(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _save_checkpoint(work_dir: str, *, require_model_review: bool = True, **kwargs):
        (Path(work_dir) / "input_manifest.json").write_text(
            json.dumps({
                "schema_version": "mathmodel.input-manifest.v1",
                "task_id": kwargs.get("task_id", "unit-task"),
                "files": [],
            }),
            encoding="utf-8",
        )
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

    async def test_failed_checkpoint_enters_waiting_review(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._save_checkpoint(work_dir)
            with (
                patch("app.routers.modeling_router.get_work_dir", return_value=work_dir),
                patch(
                    "app.routers.modeling_router.read_task_status",
                    return_value={"status": "failed"},
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

    async def test_framework_token_usage_file_does_not_block_takeover(self):
        """框架自身写入的 token_usage.json 不得阻断干净 Modeler 失败任务的接管。"""
        with tempfile.TemporaryDirectory() as work_dir:
            self._save_checkpoint(work_dir)
            (Path(work_dir) / "token_usage.json").write_text(
                json.dumps({"total_tokens": 123, "entries": []}),
                encoding="utf-8",
            )
            with (
                patch("app.routers.modeling_router.get_work_dir", return_value=work_dir),
                patch(
                    "app.routers.modeling_router.read_task_status",
                    return_value={"status": "failed"},
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
                    CodexModelingRequest(
                        modeler_response=ModelerToCoder(model_plan=_valid_codex_plan())
                    ),
                )

            self.assertEqual(result.status, "waiting_review")
            write_status.assert_called_once_with(
                "unit-task", "waiting_review", "Codex 建模方案已写入，等待人工确认"
            )
            saved = CheckpointManager(work_dir).load()
            self.assertTrue(saved.modeler_response)
            with open(
                os.path.join(work_dir, "modeling_decision.json"), encoding="utf-8"
            ) as handle:
                self.assertEqual(json.load(handle)["status"], "waiting_review")

    async def test_non_failed_status_is_rejected(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._save_checkpoint(work_dir)
            for non_failed_status in ["cancelled", "waiting_review", "completed", "running"]:
                with (
                    patch("app.routers.modeling_router.get_work_dir", return_value=work_dir),
                    patch(
                        "app.routers.modeling_router.read_task_status",
                        return_value={"status": non_failed_status},
                    ),
                    patch("app.routers.modeling_router.MathModelWorkFlow") as workflow_cls,
                ):
                    with self.assertRaises(HTTPException) as caught:
                        await submit_codex_modeling(
                            "unit-task",
                            CodexModelingRequest(modeler_response=ModelerToCoder(model_plan=_valid_codex_plan())),
                        )

                self.assertEqual(caught.exception.status_code, 409)
                self.assertIn("仅 failed 状态下可触发", str(caught.exception.detail))
                workflow_cls.assert_not_called()

    async def test_failed_checkpoint_with_frozen_results_is_rejected(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._save_checkpoint(work_dir)
            with open(os.path.join(work_dir, "frozen_results.json"), "w", encoding="utf-8") as f:
                json.dump({"ques1": {"objective_value": 2200}}, f)
            with (
                patch("app.routers.modeling_router.get_work_dir", return_value=work_dir),
                patch(
                    "app.routers.modeling_router.read_task_status",
                    return_value={"status": "failed"},
                ),
            ):
                with self.assertRaises(HTTPException) as caught:
                    await submit_codex_modeling(
                        "unit-task",
                        CodexModelingRequest(modeler_response=ModelerToCoder(model_plan=_valid_codex_plan())),
                    )

            self.assertEqual(caught.exception.status_code, 409)
            self.assertIn("冻结", str(caught.exception.detail))


    async def test_failed_checkpoint_without_model_review_gate_is_rejected(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._save_checkpoint(work_dir, require_model_review=False)
            with (
                patch("app.routers.modeling_router.get_work_dir", return_value=work_dir),
                patch(
                    "app.routers.modeling_router.read_task_status",
                    return_value={"status": "failed"},
                ),
            ):
                with self.assertRaises(HTTPException) as caught:
                    await submit_codex_modeling(
                        "unit-task",
                        CodexModelingRequest(
                            modeler_response=ModelerToCoder(
                                questions_solution=_valid_codex_plan().to_questions_solution(),
                                model_plan=_valid_codex_plan(),
                            ),
                        ),
                    )

            self.assertEqual(caught.exception.status_code, 409)
            self.assertIn("未启用", str(caught.exception.detail))

    async def test_rejects_task_with_executed_cells_or_snapshot(self):
        with tempfile.TemporaryDirectory() as work_dir:
            manager = CheckpointManager(work_dir)
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
                    modeler_response={"questions_solution": {"ques1": "方案"}},
                    executed_cell_indices=[0, 1],
                    has_variable_snapshot=True,
                    updated_at="2026-08-08T00:00:00",
                )
            )
            with open(os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "failed"}, handle)

            with patch("app.routers.modeling_router.get_work_dir", return_value=work_dir):
                with self.assertRaises(HTTPException) as caught:
                    await submit_codex_modeling(
                        "unit-task",
                        CodexModelingRequest(modeler_response=ModelerToCoder(model_plan=_valid_codex_plan())),
                    )

            self.assertEqual(caught.exception.status_code, 409)
            self.assertIn("禁止越权重置已有执行状态", str(caught.exception.detail))

    async def test_rejects_task_with_disk_execution_artifacts(self):
        with tempfile.TemporaryDirectory() as work_dir:
            manager = CheckpointManager(work_dir)
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
                    modeler_response={"questions_solution": {"ques1": "方案"}},
                    updated_at="2026-08-08T00:00:00",
                )
            )
            with open(os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "failed"}, handle)
            # 制造磁盘快照产物
            with open(os.path.join(work_dir, "variable_snapshot.pkl"), "w", encoding="utf-8") as handle:
                handle.write("snapshot_data")


            with patch("app.routers.modeling_router.get_work_dir", return_value=work_dir):
                with self.assertRaises(HTTPException) as caught:
                    await submit_codex_modeling(
                        "unit-task",
                        CodexModelingRequest(modeler_response=ModelerToCoder(model_plan=_valid_codex_plan())),
                    )

            self.assertEqual(caught.exception.status_code, 409)
            self.assertIn("任务目录已存在执行产物", str(caught.exception.detail))




class TestHumanModelingGateResume(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        modeling_router._active_tasks.clear()
        self._schedule_patcher = patch.object(
            modeling_router, "_schedule_reserved_runner"
        )
        self.schedule_runner = self._schedule_patcher.start()

    async def asyncTearDown(self):
        self._schedule_patcher.stop()
        modeling_router._active_tasks.clear()

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

    async def test_codex_modeling_rejects_tasks_with_validation_or_quality_review_history(self):
        with tempfile.TemporaryDirectory() as work_dir:
            manager = CheckpointManager(work_dir)
            checkpoint = TaskCheckpoint(
                task_id="unit-task",
                ques_all="题面",
                comp_template="CHINA",
                format_output="Markdown",
                export_profile="cumcm2026",
                require_model_review=True,
                questions={"ques_count": 1, "ques1": "问题一"},
                ques_count=1,
                modeler_response={"questions_solution": {"ques1": "旧方案"}},
                updated_at="2026-08-08T00:00:00",
                last_validation_failure={"checks": [{"passed": False, "id": "ques1"}]},
                quality_review_status="approved",
                quality_review_history=[{"review_id": "r1", "status": "approved"}],
            )
            manager.save(checkpoint)
            plan = _valid_codex_plan()
            with patch("app.routers.modeling_router.get_work_dir", return_value=work_dir):
                req = CodexModelingRequest(
                    modeler_response=ModelerToCoder(
                        questions_solution=plan.to_questions_solution(),
                        model_plan=plan,
                    ),
                    comment="Codex接管",
                )
                with self.assertRaises(HTTPException) as caught:
                    await submit_codex_modeling("unit-task", req)
                self.assertEqual(caught.exception.status_code, 409)


    async def test_codex_modeling_rejects_tasks_with_residual_res_json_or_artifacts(self):
        with tempfile.TemporaryDirectory() as work_dir:
            manager = CheckpointManager(work_dir)
            checkpoint = TaskCheckpoint(
                task_id="unit-task",
                ques_all="题面",
                comp_template="CHINA",
                format_output="Markdown",
                export_profile="cumcm2026",
                require_model_review=True,
                questions={"ques_count": 1, "ques1": "问题一"},
                ques_count=1,
                modeler_response={"questions_solution": {"ques1": "旧方案"}},
                updated_at="2026-08-08T00:00:00",
            )
            manager.save(checkpoint)
            # 状态设为 failed 且 checkpoint 表面 pristine，但磁盘残留 res.json
            with open(os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "failed"}, handle)
            with open(os.path.join(work_dir, "res.json"), "w", encoding="utf-8") as handle:
                json.dump({"result": 1}, handle)

            plan = _valid_codex_plan()
            with patch("app.routers.modeling_router.get_work_dir", return_value=work_dir):
                req = CodexModelingRequest(
                    modeler_response=ModelerToCoder(
                        questions_solution=plan.to_questions_solution(),
                        model_plan=plan,
                    ),
                    comment="Codex接管",
                )
                with self.assertRaises(HTTPException) as caught:
                    await submit_codex_modeling("unit-task", req)
                self.assertEqual(caught.exception.status_code, 409)
                self.assertIn("res.json", caught.exception.detail)

    async def test_codex_modeling_allows_uploaded_input_csv_in_input_manifest(self):
        with tempfile.TemporaryDirectory() as work_dir:
            manager = CheckpointManager(work_dir)
            checkpoint = TaskCheckpoint(
                task_id="unit-task",
                ques_all="题面",
                comp_template="CHINA",
                format_output="Markdown",
                export_profile="cumcm2026",
                require_model_review=True,
                questions={"ques_count": 1, "ques1": "问题一"},
                ques_count=1,
                modeler_response={"questions_solution": {"ques1": "旧方案"}},
                updated_at="2026-08-08T00:00:00",
            )
            manager.save(checkpoint)
            with open(os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "failed"}, handle)
            # 合法上传的数据文件并在 input_manifest.json 中登记
            input_content = "x,y\n1,2\n".encode("utf-8")
            with open(os.path.join(work_dir, "input.csv"), "wb") as handle:
                handle.write(input_content)
            manifest_path = Path(work_dir) / "input_manifest.json"
            manifest_path.write_text(
                json.dumps({
                    "schema_version": "mathmodel.input-manifest.v1",
                    "task_id": "unit-task",
                    "created_at": "2026-08-08T00:00:00",
                    "files": [
                        {
                            "name": "input.csv",
                            "relative_path": "input.csv",
                            "size_bytes": len(input_content),
                            "sha256": hashlib.sha256(input_content).hexdigest(),
                        }
                    ],
                }),
                encoding="utf-8",
            )

            plan = _valid_codex_plan()
            with (
                patch("app.routers.modeling_router.get_work_dir", return_value=work_dir),
                patch("app.core.workflow.get_work_dir", return_value=work_dir),
                patch("app.services.task_status.get_work_dir", return_value=work_dir),
                patch("app.routers.modeling_router.redis_manager.set", AsyncMock()),
                patch("app.routers.modeling_router.redis_manager.publish_message", AsyncMock()),
            ):
                req = CodexModelingRequest(
                    modeler_response=ModelerToCoder(
                        questions_solution=plan.to_questions_solution(),
                        model_plan=plan,
                    ),
                    comment="Codex接管",
                )
                res = await submit_codex_modeling("unit-task", req)
                self.assertEqual(res.status, "waiting_review")

    async def test_codex_modeling_rejects_top_level_results_csv(self):
        with tempfile.TemporaryDirectory() as work_dir:
            manager = CheckpointManager(work_dir)
            checkpoint = TaskCheckpoint(
                task_id="unit-task",
                ques_all="题面",
                comp_template="CHINA",
                format_output="Markdown",
                export_profile="cumcm2026",
                require_model_review=True,
                questions={"ques_count": 1, "ques1": "问题一"},
                ques_count=1,
                modeler_response={"questions_solution": {"ques1": "旧方案"}},
                updated_at="2026-08-08T00:00:00",
            )
            manager.save(checkpoint)
            with open(os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "failed"}, handle)
            (Path(work_dir) / "input_manifest.json").write_text(
                json.dumps({"schema_version": "mathmodel.input-manifest.v1", "task_id": "unit-task", "files": []}),
                encoding="utf-8",
            )
            # 未登记的顶层 results.csv
            with open(os.path.join(work_dir, "results.csv"), "w", encoding="utf-8") as handle:
                handle.write("1,2,3\n")

            plan = _valid_codex_plan()
            with patch("app.routers.modeling_router.get_work_dir", return_value=work_dir):
                req = CodexModelingRequest(
                    modeler_response=ModelerToCoder(
                        questions_solution=plan.to_questions_solution(),
                        model_plan=plan,
                    ),
                    comment="Codex接管",
                )
                with self.assertRaises(HTTPException) as caught:
                    await submit_codex_modeling("unit-task", req)
                self.assertEqual(caught.exception.status_code, 409)
                self.assertIn("results.csv", caught.exception.detail)

    async def test_codex_modeling_rejects_top_level_arbitrary_py(self):
        with tempfile.TemporaryDirectory() as work_dir:
            manager = CheckpointManager(work_dir)
            checkpoint = TaskCheckpoint(
                task_id="unit-task",
                ques_all="题面",
                comp_template="CHINA",
                format_output="Markdown",
                export_profile="cumcm2026",
                require_model_review=True,
                questions={"ques_count": 1, "ques1": "问题一"},
                ques_count=1,
                modeler_response={"questions_solution": {"ques1": "旧方案"}},
                updated_at="2026-08-08T00:00:00",
            )
            manager.save(checkpoint)
            with open(os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "failed"}, handle)
            (Path(work_dir) / "input_manifest.json").write_text(
                json.dumps({"schema_version": "mathmodel.input-manifest.v1", "task_id": "unit-task", "files": []}),
                encoding="utf-8",
            )
            # 未登记的顶层 foo.py
            with open(os.path.join(work_dir, "foo.py"), "w", encoding="utf-8") as handle:
                handle.write("print('hello')\n")

            plan = _valid_codex_plan()
            with patch("app.routers.modeling_router.get_work_dir", return_value=work_dir):
                req = CodexModelingRequest(
                    modeler_response=ModelerToCoder(
                        questions_solution=plan.to_questions_solution(),
                        model_plan=plan,
                    ),
                    comment="Codex接管",
                )
                with self.assertRaises(HTTPException) as caught:
                    await submit_codex_modeling("unit-task", req)
                self.assertEqual(caught.exception.status_code, 409)
                self.assertIn("foo.py", caught.exception.detail)

    async def test_codex_modeling_rejects_nested_subdirectory_artifacts(self):
        with tempfile.TemporaryDirectory() as work_dir:
            manager = CheckpointManager(work_dir)
            checkpoint = TaskCheckpoint(
                task_id="unit-task",
                ques_all="题面",
                comp_template="CHINA",
                format_output="Markdown",
                export_profile="cumcm2026",
                require_model_review=True,
                questions={"ques_count": 1, "ques1": "问题一"},
                ques_count=1,
                modeler_response={"questions_solution": {"ques1": "旧方案"}},
                updated_at="2026-08-08T00:00:00",
            )
            manager.save(checkpoint)
            with open(os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "failed"}, handle)
            (Path(work_dir) / "input_manifest.json").write_text(
                json.dumps({"schema_version": "mathmodel.input-manifest.v1", "task_id": "unit-task", "files": []}),
                encoding="utf-8",
            )
            # 嵌套子目录中的执行产物
            subdir = os.path.join(work_dir, "output")
            os.makedirs(subdir, exist_ok=True)
            with open(os.path.join(subdir, "results.csv"), "w", encoding="utf-8") as handle:
                handle.write("val\n1\n")

            plan = _valid_codex_plan()
            with patch("app.routers.modeling_router.get_work_dir", return_value=work_dir):
                req = CodexModelingRequest(
                    modeler_response=ModelerToCoder(
                        questions_solution=plan.to_questions_solution(),
                        model_plan=plan,
                    ),
                    comment="Codex接管",
                )
                with self.assertRaises(HTTPException) as caught:
                    await submit_codex_modeling("unit-task", req)
                self.assertEqual(caught.exception.status_code, 409)

    async def test_codex_modeling_rejects_tampered_input_file_and_corrupt_manifest(self):
        with tempfile.TemporaryDirectory() as work_dir:
            manager = CheckpointManager(work_dir)
            checkpoint = TaskCheckpoint(
                task_id="unit-task",
                ques_all="题面",
                comp_template="CHINA",
                format_output="Markdown",
                export_profile="cumcm2026",
                require_model_review=True,
                questions={"ques_count": 1, "ques1": "问题一"},
                ques_count=1,
                modeler_response={"questions_solution": {"ques1": "旧方案"}},
                updated_at="2026-08-08T00:00:00",
            )
            manager.save(checkpoint)
            with open(os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8") as handle:
                json.dump({"status": "failed"}, handle)

            # 1. 篡改文件内容（哈希/大小不符）
            (Path(work_dir) / "input.csv").write_text("tampered", encoding="utf-8")
            (Path(work_dir) / "input_manifest.json").write_text(
                json.dumps({
                    "schema_version": "mathmodel.input-manifest.v1",
                    "task_id": "unit-task",
                    "files": [{"name": "input.csv", "relative_path": "input.csv", "size_bytes": 100, "sha256": "0" * 64}],
                }),
                encoding="utf-8",
            )
            plan = _valid_codex_plan()
            with patch("app.routers.modeling_router.get_work_dir", return_value=work_dir):
                req = CodexModelingRequest(
                    modeler_response=ModelerToCoder(
                        questions_solution=plan.to_questions_solution(),
                        model_plan=plan,
                    ),
                    comment="Codex接管",
                )
                with self.assertRaises(HTTPException) as caught:
                    await submit_codex_modeling("unit-task", req)
                self.assertEqual(caught.exception.status_code, 409)
                self.assertIn("篡改", caught.exception.detail)

            # 2. 损坏的清单
            (Path(work_dir) / "input_manifest.json").write_text("{corrupt json", encoding="utf-8")
            with patch("app.routers.modeling_router.get_work_dir", return_value=work_dir):
                with self.assertRaises(HTTPException) as caught:
                    await submit_codex_modeling("unit-task", req)
                self.assertEqual(caught.exception.status_code, 409)

    async def test_real_production_management_files_pass_pristine_takeover(self):
        """证明由真实写函数生成的全套生产管理文件可以通过 pristine 接管检查。"""
        from app.services.task_recovery import write_task_request_snapshot
        from app.routers.modeling_router import is_task_pristine_for_takeover

        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            task_id = "real-prod-task"
            manager = CheckpointManager(work_dir)
            checkpoint = TaskCheckpoint(
                task_id=task_id,
                ques_all="题面文本",
                comp_template="CHINA",
                format_output="Markdown",
                export_profile="cumcm2026",
                require_model_review=True,
                questions={"ques_count": 1, "ques1": "问题一"},
                ques_count=1,
                modeler_response={"questions_solution": {"ques1": "方案"}},
                updated_at="2026-08-08T00:00:00",
            )
            manager.save(checkpoint)

            # 1. 真实写入 task_request.json
            write_task_request_snapshot(
                work_dir,
                {
                    "task_id": task_id,
                    "ques_all": "题面文本",
                    "comp_template": "CHINA",
                    "format_output": "Markdown",
                    "export_profile": "cumcm2026",
                },
            )
            # 2. 真实写入 modeler_plan.json 与 modeler_plan.md
            workflow = MathModelWorkFlow()
            workflow.work_dir = work_dir
            workflow.task_id = task_id
            plan = _valid_codex_plan()
            modeler_resp = ModelerToCoder(questions_solution=plan.to_questions_solution(), model_plan=plan)
            with patch("app.core.workflow.get_work_dir", return_value=work_dir):
                workflow._write_modeler_plan(modeler_resp)
                # 3. 真实写入 modeling_decision.json 与 modeling_decision.md
                problem = Problem(task_id=task_id, ques_all="题面", comp_template=CompTemplate.CHINA, format_output=FormatOutPut.Markdown, export_profile=ExportProfile.CUMCM2026)
                workflow._write_modeling_decision(problem, modeler_resp)

            # 4. 写入其余生产管理文件
            (root / "task_status.json").write_text('{"status": "failed"}', encoding="utf-8")
            (root / "problem_contract.json").write_text('{}', encoding="utf-8")
            (root / "guidance.json").write_text('[]', encoding="utf-8")
            (root / "internal_guidance_audit.jsonl").write_text('', encoding="utf-8")
            (root / "questions.txt").write_text('题面', encoding="utf-8")

            # 5. 登记合法输入文件
            input_bytes = b"header1,header2\n1,2\n"
            (root / "input.csv").write_bytes(input_bytes)
            (root / "input_manifest.json").write_text(
                json.dumps({
                    "schema_version": "mathmodel.input-manifest.v1",
                    "task_id": task_id,
                    "created_at": "2026-08-08T00:00:00",
                    "files": [
                        {
                            "name": "input.csv",
                            "relative_path": "input.csv",
                            "size_bytes": len(input_bytes),
                            "sha256": hashlib.sha256(input_bytes).hexdigest(),
                        }
                    ],
                }),
                encoding="utf-8",
            )

            # 验证生产管理文件全部在白名单中并通过 pristine 检查
            pristine, reason = is_task_pristine_for_takeover(checkpoint, work_dir)
            self.assertTrue(pristine, f"生产管理文件目录未能通过接管检查: {reason}")

            # 若混入未登记的 results.csv 或 foo.py 必须立即被拦截
            (root / "results.csv").write_text("unregistered", encoding="utf-8")
            p_bad, r_bad = is_task_pristine_for_takeover(checkpoint, work_dir)
            self.assertFalse(p_bad)
            self.assertIn("results.csv", r_bad)
            (root / "results.csv").unlink()

            (root / "foo.py").write_text("print(1)", encoding="utf-8")
            p_bad2, r_bad2 = is_task_pristine_for_takeover(checkpoint, work_dir)
            self.assertFalse(p_bad2)
            self.assertIn("foo.py", r_bad2)

    def test_input_manifest_strict_field_validation(self):
        """严格校验 input_manifest.json 字段：schema_version、task_id、sha256、相对路径、重复文件名等。"""
        from app.routers.modeling_router import is_task_pristine_for_takeover

        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            checkpoint = TaskCheckpoint(
                task_id="t1",
                ques_all="题面",
                comp_template="CHINA",
                format_output="Markdown",
                export_profile="cumcm2026",
                require_model_review=True,
                questions={"ques_count": 1, "ques1": "问题一"},
                ques_count=1,
                modeler_response={},
                updated_at="2026-08-08T00:00:00",
            )
            (root / "task_status.json").write_text('{"status": "failed"}', encoding="utf-8")
            input_bytes = b"1,2\n"
            (root / "input.csv").write_bytes(input_bytes)
            valid_sha = hashlib.sha256(input_bytes).hexdigest()
            valid_size = len(input_bytes)

            # 1. 错误 schema_version
            (root / "input_manifest.json").write_text(json.dumps({
                "schema_version": "v2_unknown",
                "task_id": "t1",
                "files": [{"name": "input.csv", "relative_path": "input.csv", "size_bytes": valid_size, "sha256": valid_sha}],
            }), encoding="utf-8")
            ok, err = is_task_pristine_for_takeover(checkpoint, work_dir)
            self.assertFalse(ok)
            self.assertIn("schema_version", err)

            # 2. 缺失 task_id
            (root / "input_manifest.json").write_text(json.dumps({
                "schema_version": "mathmodel.input-manifest.v1",
                "task_id": "",
                "files": [{"name": "input.csv", "relative_path": "input.csv", "size_bytes": valid_size, "sha256": valid_sha}],
            }), encoding="utf-8")
            ok, err = is_task_pristine_for_takeover(checkpoint, work_dir)
            self.assertFalse(ok)
            self.assertIn("task_id", err)

            # 3. 负数 size_bytes
            (root / "input_manifest.json").write_text(json.dumps({
                "schema_version": "mathmodel.input-manifest.v1",
                "task_id": "t1",
                "files": [{"name": "input.csv", "relative_path": "input.csv", "size_bytes": -1, "sha256": valid_sha}],
            }), encoding="utf-8")
            ok, err = is_task_pristine_for_takeover(checkpoint, work_dir)
            self.assertFalse(ok)
            self.assertIn("负数", err)

            # 4. 非 64 位十六进制 SHA-256
            (root / "input_manifest.json").write_text(json.dumps({
                "schema_version": "mathmodel.input-manifest.v1",
                "task_id": "t1",
                "files": [{"name": "input.csv", "relative_path": "input.csv", "size_bytes": valid_size, "sha256": "invalid_hex_123"}],
            }), encoding="utf-8")
            ok, err = is_task_pristine_for_takeover(checkpoint, work_dir)
            self.assertFalse(ok)
            self.assertIn("SHA-256", err)

            # 5. 包含路径遍历
            (root / "input_manifest.json").write_text(json.dumps({
                "schema_version": "mathmodel.input-manifest.v1",
                "task_id": "t1",
                "files": [{"name": "../input.csv", "relative_path": "../input.csv", "size_bytes": valid_size, "sha256": valid_sha}],
            }), encoding="utf-8")
            ok, err = is_task_pristine_for_takeover(checkpoint, work_dir)
            self.assertFalse(ok)
            self.assertIn("路径", err)

            # 6. 重复文件名登记
            (root / "input_manifest.json").write_text(json.dumps({
                "schema_version": "mathmodel.input-manifest.v1",
                "task_id": "t1",
                "files": [
                    {"name": "input.csv", "relative_path": "input.csv", "size_bytes": valid_size, "sha256": valid_sha},
                    {"name": "input.csv", "relative_path": "input.csv", "size_bytes": valid_size, "sha256": valid_sha},
                ],
            }), encoding="utf-8")
            ok, err = is_task_pristine_for_takeover(checkpoint, work_dir)
            self.assertFalse(ok)
            self.assertIn("重复", err)

    def test_input_manifest_counter_examples_for_pristine_takeover(self):
        """反例驱动测试：Manifest 接管门禁严格校验反例。"""
        from app.routers.modeling_router import is_task_pristine_for_takeover

        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            checkpoint = TaskCheckpoint(
                task_id="task_chk_123",
                ques_all="题面",
                comp_template="CHINA",
                format_output="Markdown",
                export_profile="cumcm2026",
                workflow_state="modeling",
                require_model_review=True,
                questions={"ques_count": 1, "ques1": "问题一"},
                ques_count=1,
                modeler_response={},
                updated_at="2026-08-08T00:00:00",
            )
            (root / "task_status.json").write_text('{"status": "failed"}', encoding="utf-8")
            input_bytes = b"header_a,header_b\n1,2\n"
            (root / "data.csv").write_bytes(input_bytes)
            valid_sha = hashlib.sha256(input_bytes).hexdigest()
            valid_size = len(input_bytes)

            # 1. input_manifest.json.task_id != checkpoint.task_id
            (root / "input_manifest.json").write_text(json.dumps({
                "schema_version": "mathmodel.input-manifest.v1",
                "task_id": "different_task_id_999",
                "files": [{"name": "data.csv", "relative_path": "data.csv", "size_bytes": valid_size, "sha256": valid_sha}],
            }), encoding="utf-8")
            ok, err = is_task_pristine_for_takeover(checkpoint, work_dir)
            self.assertFalse(ok)
            self.assertIn("task_id", err)

            # 2. name != relative_path
            (root / "input_manifest.json").write_text(json.dumps({
                "schema_version": "mathmodel.input-manifest.v1",
                "task_id": "task_chk_123",
                "files": [{"name": "data.csv", "relative_path": "subdir/data.csv", "size_bytes": valid_size, "sha256": valid_sha}],
            }), encoding="utf-8")
            ok, err = is_task_pristine_for_takeover(checkpoint, work_dir)
            self.assertFalse(ok)
            self.assertIn("不一致", err)

            # 3. Windows drive absolute path
            (root / "input_manifest.json").write_text(json.dumps({
                "schema_version": "mathmodel.input-manifest.v1",
                "task_id": "task_chk_123",
                "files": [{"name": "C:/Windows/win.ini", "relative_path": "C:/Windows/win.ini", "size_bytes": valid_size, "sha256": valid_sha}],
            }), encoding="utf-8")
            ok, err = is_task_pristine_for_takeover(checkpoint, work_dir)
            self.assertFalse(ok)

            # 4. UNC / POSIX absolute / traversal
            for evil_path in ["\\\\server\\share\\data.csv", "//server/share/data.csv", "/etc/passwd", "../data.csv"]:
                (root / "input_manifest.json").write_text(json.dumps({
                    "schema_version": "mathmodel.input-manifest.v1",
                    "task_id": "task_chk_123",
                    "files": [{"name": evil_path, "relative_path": evil_path, "size_bytes": valid_size, "sha256": valid_sha}],
                }), encoding="utf-8")
                ok, err = is_task_pristine_for_takeover(checkpoint, work_dir)
                self.assertFalse(ok, f"Should reject evil path: {evil_path}")

            # 5. size_bytes=True / False 不能被当作 int 接受
            for bool_val in [True, False]:
                (root / "input_manifest.json").write_text(json.dumps({
                    "schema_version": "mathmodel.input-manifest.v1",
                    "task_id": "task_chk_123",
                    "files": [{"name": "data.csv", "relative_path": "data.csv", "size_bytes": bool_val, "sha256": valid_sha}],
                }), encoding="utf-8")
                ok, err = is_task_pristine_for_takeover(checkpoint, work_dir)
                self.assertFalse(ok, f"Should reject bool size_bytes: {bool_val}")
                self.assertIn("size_bytes", err)

            # 6. 与系统保留管理文件重名
            for reserved in ["checkpoint.json", "task_status.json", "problem_contract.json"]:
                (root / "input_manifest.json").write_text(json.dumps({
                    "schema_version": "mathmodel.input-manifest.v1",
                    "task_id": "task_chk_123",
                    "files": [{"name": reserved, "relative_path": reserved, "size_bytes": valid_size, "sha256": valid_sha}],
                }), encoding="utf-8")
                ok, err = is_task_pristine_for_takeover(checkpoint, work_dir)
                self.assertFalse(ok, f"Should reject reserved name: {reserved}")
                self.assertIn("保留", err)

            # 7. NTFS Alternate Data Streams (ADS)
            for ads_path in ["data.csv:payload", "file.txt::$DATA", "subdir/data.csv:stream"]:
                (root / "input_manifest.json").write_text(json.dumps({
                    "schema_version": "mathmodel.input-manifest.v1",
                    "task_id": "task_chk_123",
                    "files": [{"name": ads_path, "relative_path": ads_path, "size_bytes": valid_size, "sha256": valid_sha}],
                }), encoding="utf-8")
                ok, err = is_task_pristine_for_takeover(checkpoint, work_dir)
                self.assertFalse(ok, f"Should reject ADS path: {ads_path}")
                self.assertIn("冒号或备用数据流", err)

            # 8. Windows 保留设备名 (CON, PRN, AUX, NUL, COM1, LPT1 等)
            for dev_name in ["CON", "con.csv", "PRN", "AUX.txt", "NUL", "COM1.dat", "lpt1.json", "subdir/nul.csv"]:
                (root / "input_manifest.json").write_text(json.dumps({
                    "schema_version": "mathmodel.input-manifest.v1",
                    "task_id": "task_chk_123",
                    "files": [{"name": dev_name, "relative_path": dev_name, "size_bytes": valid_size, "sha256": valid_sha}],
                }), encoding="utf-8")
                ok, err = is_task_pristine_for_takeover(checkpoint, work_dir)
                self.assertFalse(ok, f"Should reject Windows reserved device: {dev_name}")
                self.assertIn("保留设备名", err)

            # 9. 尾随空格或句点
            for trailing_path in ["data.csv ", "file.txt.", "subdir /data.csv", "sub./data.csv"]:
                (root / "input_manifest.json").write_text(json.dumps({
                    "schema_version": "mathmodel.input-manifest.v1",
                    "task_id": "task_chk_123",
                    "files": [{"name": trailing_path, "relative_path": trailing_path, "size_bytes": valid_size, "sha256": valid_sha}],
                }), encoding="utf-8")
                ok, err = is_task_pristine_for_takeover(checkpoint, work_dir)
                self.assertFalse(ok, f"Should reject trailing space or dot: {trailing_path}")
                self.assertIn("尾随空格或句点", err)

            # 10. 合法中文、空格、括号及嵌套相对路径必须正常支持
            valid_chinese_file = "附件 1 赛题数据(正式).csv"
            (root / valid_chinese_file).write_text("x,y\n1,2\n", encoding="utf-8")
            valid_cn_size = (root / valid_chinese_file).stat().st_size
            valid_cn_sha = hashlib.sha256((root / valid_chinese_file).read_bytes()).hexdigest()
            (root / "input_manifest.json").write_text(json.dumps({
                "schema_version": "mathmodel.input-manifest.v1",
                "task_id": "task_chk_123",
                "files": [
                    {"name": "data.csv", "relative_path": "data.csv", "size_bytes": valid_size, "sha256": valid_sha},
                    {"name": valid_chinese_file, "relative_path": valid_chinese_file, "size_bytes": valid_cn_size, "sha256": valid_cn_sha},
                ],
            }), encoding="utf-8")
            ok, err = is_task_pristine_for_takeover(checkpoint, work_dir)
            self.assertTrue(ok, f"Valid Chinese and space file should be accepted, error: {err}")


if __name__ == "__main__":
    unittest.main()
