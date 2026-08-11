"""Regression tests for the code-validation-freeze-writer ordering."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.core.checkpoint import CheckpointManager, TaskCheckpoint
from app.core.workflow import MathModelWorkFlow
from app.schemas.A2A import (
    CoderToWriter,
    CoordinatorToModeler,
    ModelerToCoder,
    WriterResponse,
)
from app.schemas.problem_contract import ContractRequirement, ProblemContract
from app.schemas.request import Problem


class _Flows:
    def get_solution_flows(self, _questions, _modeler_response):
        return {
            "ques1": {"coder_prompt": "solve q1"},
            "ques2": {"coder_prompt": "solve q2"},
        }

    def get_writer_prompt(self, key, _response, _interpreter, _template):
        return f"write {key}"


class _EdaOnlyFlows:
    def get_solution_flows(self, _questions, _modeler_response):
        return {"eda": {"coder_prompt": "verify input constants"}}

    def get_writer_prompt(self, key, _response, _interpreter, _template):
        return f"write {key}"


class _Coder:
    def __init__(self, events):
        self.events = events

    async def run(self, prompt, subtask_title):
        self.events.append(("code", subtask_title, prompt))
        return CoderToWriter(
            code_response=f"response {subtask_title}",
            created_images=[],
            execution_attempted=True,
            execution_succeeded=True,
        )


class _QualityRepairCoder(_Coder):
    def __init__(self, events):
        super().__init__(events)
        self.quality_repair_flags = []

    async def run(self, prompt, subtask_title, **kwargs):
        self.quality_repair_flags.append(kwargs.get("quality_repair", False))
        self.events.append(("code", subtask_title, prompt))
        return CoderToWriter(
            code_response=f"response {subtask_title}",
            created_images=[],
            execution_attempted=True,
            execution_succeeded=True,
        )


class _FailedCoder:
    async def run(self, prompt, subtask_title):
        return CoderToWriter(
            code_response=f"failed {subtask_title}",
            created_images=[],
            execution_attempted=True,
            execution_succeeded=False,
        )


class _Writer:
    def __init__(self, events):
        self.events = events

    async def run(self, prompt, available_images=None, sub_title=None):
        self.events.append(("writer", sub_title, prompt))
        return WriterResponse(response_content=f"paper {sub_title}")


class _Interpreter:
    def __init__(self, work_dir):
        self.work_dir = work_dir
        self.kc = None


class _Output:
    def __init__(self):
        self.results = {}

    def set_res(self, key, value):
        self.results[key] = value


class _RepairOutput:
    def __init__(self):
        self.results = {
            "ques1": {"response_content": "paper q1", "footnotes": []},
            "ques2": {"response_content": "incorrect paper q2", "footnotes": []},
        }
        self.save_count = 0

    def get_res(self):
        return self.results

    def set_res(self, key, value):
        self.results[key] = {
            "response_content": value.response_content,
            "footnotes": value.footnotes,
        }

    def save_result(self):
        self.save_count += 1


class WorkflowExecutionGateTest(unittest.IsolatedAsyncioTestCase):
    async def test_quality_review_pauses_before_writer_and_binds_checkpoint(self):
        with tempfile.TemporaryDirectory() as raw_work_dir:
            work_dir = Path(raw_work_dir)
            checkpoint_manager = CheckpointManager(str(work_dir))
            checkpoint_manager.save(
                TaskCheckpoint(
                    task_id="task",
                    ques_all="test",
                    comp_template="cumcm",
                    format_output="markdown",
                    questions={"ques_count": 2, "ques1": "q1", "ques2": "q2"},
                    ques_count=2,
                    modeler_response={"questions_solution": {}},
                    updated_at="now",
                )
            )
            events = []
            workflow = MathModelWorkFlow()
            workflow.task_id = "task"
            workflow.work_dir = str(work_dir)

            def freeze(directory):
                Path(directory, "frozen_results.json").write_text("{}", encoding="utf-8")

            review = {
                "status": "NEEDS_REVIEW",
                "review_id": "review-1",
                "failed_subtasks": ["ques2"],
            }
            with (
                patch("app.core.workflow.redis_manager.publish_message", AsyncMock()),
                patch("app.core.workflow.write_execution_validation_report", return_value={"status": "PASS"}),
                patch("app.core.workflow.write_frozen_results_from_execution_validation", side_effect=freeze),
                patch("app.core.workflow.write_execution_quality_review", return_value=review),
            ):
                result = await workflow._run_solution_flows(
                    _Flows(),
                    ModelerToCoder(questions_solution={}),
                    _Coder(events),
                    _Writer(events),
                    _Interpreter(str(work_dir)),
                    _Output(),
                    checkpoint_manager,
                    {},
                )

            self.assertEqual(result, "waiting_quality_review")
            self.assertEqual([event for event in events if event[0] == "writer"], [])
            saved = checkpoint_manager.load()
            self.assertEqual(saved.workflow_state, "waiting_quality_review")
            self.assertEqual(saved.quality_review_id, "review-1")

    async def test_quality_repair_flag_is_sent_only_to_fresh_coder_turns(self):
        with tempfile.TemporaryDirectory() as raw_work_dir:
            work_dir = Path(raw_work_dir)
            checkpoint_manager = CheckpointManager(str(work_dir))
            checkpoint_manager.save(
                TaskCheckpoint(
                    task_id="task",
                    ques_all="test",
                    comp_template="cumcm",
                    format_output="markdown",
                    questions={"ques_count": 2, "ques1": "q1", "ques2": "q2"},
                    ques_count=2,
                    modeler_response={"questions_solution": {}},
                    updated_at="now",
                )
            )
            saved_response = CoderToWriter(
                code_response="existing q1",
                created_images=[],
                execution_attempted=True,
                execution_succeeded=True,
            )
            checkpoint_manager.mark_solution_coder_completed(
                "ques1", saved_response.model_dump()
            )
            events = []
            workflow = MathModelWorkFlow()
            workflow.task_id = "task"
            workflow.work_dir = str(work_dir)
            coder = _QualityRepairCoder(events)

            def freeze(directory):
                Path(directory, "frozen_results.json").write_text(
                    "{}", encoding="utf-8"
                )

            with (
                patch("app.core.workflow.redis_manager.publish_message", AsyncMock()),
                patch(
                    "app.core.workflow.write_execution_validation_report",
                    return_value={"status": "PASS"},
                ),
                patch(
                    "app.core.workflow.write_frozen_results_from_execution_validation",
                    side_effect=freeze,
                ),
                patch(
                    "app.core.workflow.write_execution_quality_review",
                    return_value={"status": "PASS"},
                ),
            ):
                await workflow._run_solution_flows(
                    _Flows(),
                    ModelerToCoder(questions_solution={}),
                    coder,
                    _Writer(events),
                    _Interpreter(str(work_dir)),
                    _Output(),
                    checkpoint_manager,
                    {},
                    quality_repair=True,
                )

            self.assertEqual(coder.quality_repair_flags, [True])
            self.assertEqual(
                [event[1] for event in events if event[0] == "code"], ["ques2"]
            )

    async def test_early_coder_failure_does_not_label_diagnostic_pass_as_validation(self):
        with tempfile.TemporaryDirectory() as raw_work_dir:
            work_dir = Path(raw_work_dir)
            checkpoint_manager = CheckpointManager(str(work_dir))
            checkpoint_manager.save(
                TaskCheckpoint(
                    task_id="task",
                    ques_all="test",
                    comp_template="cumcm",
                    format_output="markdown",
                    questions={"ques_count": 2, "ques1": "q1", "ques2": "q2"},
                    ques_count=2,
                    modeler_response={"questions_solution": {}},
                    updated_at="now",
                )
            )
            workflow = MathModelWorkFlow()
            workflow.task_id = "task"
            workflow.work_dir = str(work_dir)

            with (
                patch("app.core.workflow.redis_manager.publish_message", AsyncMock()),
                patch(
                    "app.core.workflow.write_execution_validation_report",
                    return_value={"status": "PASS"},
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "尚未执行正式逐题验证"
                ) as raised:
                    await workflow._run_solution_flows(
                        _Flows(),
                        ModelerToCoder(questions_solution={}),
                        _FailedCoder(),
                        _Writer([]),
                        _Interpreter(str(work_dir)),
                        _Output(),
                        checkpoint_manager,
                        {},
                    )

            self.assertNotIn("诊断报告状态: PASS", str(raised.exception))

    async def test_eda_failure_does_not_create_formal_validation_report(self):
        with tempfile.TemporaryDirectory() as raw_work_dir:
            work_dir = Path(raw_work_dir)
            checkpoint_manager = CheckpointManager(str(work_dir))
            checkpoint_manager.save(
                TaskCheckpoint(
                    task_id="task",
                    ques_all="test",
                    comp_template="cumcm",
                    format_output="markdown",
                    questions={"ques_count": 1, "ques1": "q1"},
                    ques_count=1,
                    modeler_response={"questions_solution": {}},
                    updated_at="now",
                )
            )
            workflow = MathModelWorkFlow()
            workflow.task_id = "task"
            workflow.work_dir = str(work_dir)

            with (
                patch("app.core.workflow.redis_manager.publish_message", AsyncMock()),
                patch("app.core.workflow.write_execution_validation_report") as report_writer,
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "非正式代码阶段 eda 未成功执行"
                ):
                    await workflow._run_solution_flows(
                        _EdaOnlyFlows(),
                        ModelerToCoder(questions_solution={}),
                        _FailedCoder(),
                        _Writer([]),
                        _Interpreter(str(work_dir)),
                        _Output(),
                        checkpoint_manager,
                        {},
                    )

            report_writer.assert_not_called()

    async def test_all_code_and_freeze_finish_before_any_solution_writer_runs(self):
        with tempfile.TemporaryDirectory() as raw_work_dir:
            work_dir = Path(raw_work_dir)
            checkpoint_manager = CheckpointManager(str(work_dir))
            checkpoint_manager.save(
                TaskCheckpoint(
                    task_id="task",
                    ques_all="test",
                    comp_template="cumcm",
                    format_output="markdown",
                    questions={"ques_count": 2, "ques1": "q1", "ques2": "q2"},
                    ques_count=2,
                    modeler_response={"questions_solution": {}},
                    updated_at="now",
                )
            )
            events = []
            workflow = MathModelWorkFlow()
            workflow.task_id = "task"
            workflow.work_dir = str(work_dir)
            coder = _Coder(events)
            writer = _Writer(events)
            output = _Output()

            def freeze(directory):
                events.append(("freeze",))
                Path(directory, "frozen_results.json").write_text("{}", encoding="utf-8")
                return Path(directory, "frozen_results.json")

            with (
                patch("app.core.workflow.redis_manager.publish_message", AsyncMock()),
                patch("app.core.workflow.write_execution_validation_report", return_value={"status": "PASS"}),
                patch("app.core.workflow.write_frozen_results_from_execution_validation", side_effect=freeze),
            ):
                await workflow._run_solution_flows(
                    _Flows(),
                    ModelerToCoder(questions_solution={}),
                    coder,
                    writer,
                    _Interpreter(str(work_dir)),
                    output,
                    checkpoint_manager,
                    {},
                )

            self.assertEqual([event[1] for event in events if event[0] == "code"], ["ques1", "ques2"])
            self.assertEqual(events[2], ("freeze",))
            self.assertEqual([event[1] for event in events if event[0] == "writer"], ["ques1", "ques2"])
            self.assertEqual(set(output.results), {"ques1", "ques2"})
            self.assertIsNotNone(checkpoint_manager.get_solution_coder_response("ques1"))

    async def test_second_failed_validation_keeps_passed_checkpoint_and_clears_repair_boundary(self):
        with tempfile.TemporaryDirectory() as raw_work_dir:
            work_dir = Path(raw_work_dir)
            checkpoint_manager = CheckpointManager(str(work_dir))
            checkpoint_manager.save(
                TaskCheckpoint(
                    task_id="task",
                    ques_all="test",
                    comp_template="cumcm",
                    format_output="markdown",
                    questions={"ques_count": 2, "ques1": "q1", "ques2": "q2"},
                    ques_count=2,
                    modeler_response={"questions_solution": {}},
                    updated_at="now",
                )
            )
            workflow = MathModelWorkFlow()
            workflow.task_id = "task"
            workflow.work_dir = str(work_dir)

            with (
                patch("app.core.workflow.redis_manager.publish_message", AsyncMock()),
                patch(
                    "app.core.workflow.write_execution_validation_report",
                    return_value={
                        "status": "FAIL",
                        "checks": [
                            {"id": "ques2.constraints", "passed": False, "message": "missing"}
                        ],
                    },
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "数值可行性门禁"):
                    await workflow._run_solution_flows(
                        _Flows(),
                        ModelerToCoder(questions_solution={}),
                        _Coder([]),
                        _Writer([]),
                        _Interpreter(str(work_dir)),
                        _Output(),
                        checkpoint_manager,
                        {},
                    )

            self.assertIsNotNone(checkpoint_manager.get_solution_coder_response("ques1"))
            self.assertIsNone(checkpoint_manager.get_solution_coder_response("ques2"))

    async def test_targeted_repair_only_reexecutes_failed_subtask_and_keeps_passed_checkpoint(self):
        with tempfile.TemporaryDirectory() as raw_work_dir:
            work_dir = Path(raw_work_dir)
            checkpoint_manager = CheckpointManager(str(work_dir))
            checkpoint_manager.save(
                TaskCheckpoint(
                    task_id="task",
                    ques_all="test",
                    comp_template="cumcm",
                    format_output="markdown",
                    questions={"ques_count": 2, "ques1": "q1", "ques2": "q2"},
                    ques_count=2,
                    modeler_response={"questions_solution": {}},
                    updated_at="now",
                )
            )
            events = []
            workflow = MathModelWorkFlow()
            workflow.task_id = "task"
            workflow.work_dir = str(work_dir)

            def freeze(directory):
                Path(directory, "frozen_results.json").write_text("{}", encoding="utf-8")

            failed_report = {
                "status": "FAIL",
                "checks": [
                    {"id": "ques2.constraints", "passed": False, "message": "缺少结果文件。"},
                    {"id": "ques1.executed", "passed": True, "message": "ok"},
                ],
            }
            with (
                patch("app.core.workflow.redis_manager.publish_message", AsyncMock()),
                patch(
                    "app.core.workflow.write_execution_validation_report",
                    side_effect=[failed_report, {"status": "PASS", "checks": []}],
                ),
                patch("app.core.workflow.write_frozen_results_from_execution_validation", side_effect=freeze),
            ):
                await workflow._run_solution_flows(
                    _Flows(),
                    ModelerToCoder(questions_solution={}),
                    _Coder(events),
                    _Writer(events),
                    _Interpreter(str(work_dir)),
                    _Output(),
                    checkpoint_manager,
                    {},
                )

            code_subtasks = [event[1] for event in events if event[0] == "code"]
            self.assertEqual(
                code_subtasks,
                ["ques1", "ques2", "ques2_repair"],
            )
            self.assertEqual(checkpoint_manager._checkpoint.targeted_repair_attempts, 0)
            self.assertEqual(checkpoint_manager._checkpoint.workflow_state, "frozen")
            self.assertIsNotNone(checkpoint_manager.get_solution_coder_response("ques1"))
            self.assertIsNotNone(checkpoint_manager.get_solution_coder_response("ques2"))

    async def test_corrected_balance_rule_reuses_only_verified_formal_evidence(self):
        with tempfile.TemporaryDirectory() as raw_work_dir:
            work_dir = Path(raw_work_dir)
            checkpoint_manager = CheckpointManager(str(work_dir))
            checkpoint_manager.save(
                TaskCheckpoint(
                    task_id="task",
                    ques_all="test",
                    comp_template="cumcm",
                    format_output="markdown",
                    questions={"ques_count": 2, "ques1": "q1", "ques2": "q2"},
                    ques_count=2,
                    modeler_response={"questions_solution": {}},
                    workflow_state="repairing",
                    targeted_repair_attempts=1,
                    last_validation_failure={
                        "report": {
                            "checks": [
                                {"id": "ques1.balance_residual", "passed": False},
                                {"id": "ques2.balance_residual", "passed": False},
                            ]
                        }
                    },
                    updated_at="now",
                )
            )
            events = []
            workflow = MathModelWorkFlow()
            workflow.task_id = "task"
            workflow.work_dir = str(work_dir)

            def freeze(directory):
                Path(directory, "frozen_results.json").write_text("{}", encoding="utf-8")

            with (
                patch("app.core.workflow.redis_manager.publish_message", AsyncMock()),
                patch("app.core.workflow.write_execution_validation_report", return_value={"status": "PASS"}),
                patch("app.core.workflow.write_frozen_results_from_execution_validation", side_effect=freeze),
            ):
                await workflow._run_solution_flows(
                    _Flows(),
                    ModelerToCoder(questions_solution={}),
                    _Coder(events),
                    _Writer(events),
                    _Interpreter(str(work_dir)),
                    _Output(),
                    checkpoint_manager,
                    {},
                )

            self.assertEqual([event for event in events if event[0] == "code"], [])
            self.assertEqual(
                [event[1] for event in events if event[0] == "writer"], ["ques1", "ques2"]
            )
            self.assertEqual(checkpoint_manager._checkpoint.workflow_state, "frozen")

    async def test_preflight_repair_rewrites_only_reported_question_once(self):
        with tempfile.TemporaryDirectory() as raw_work_dir:
            work_dir = Path(raw_work_dir)
            checkpoint_manager = CheckpointManager(str(work_dir))
            checkpoint_manager.save(
                TaskCheckpoint(
                    task_id="task",
                    ques_all="test",
                    comp_template="cumcm",
                    format_output="markdown",
                    questions={"ques_count": 2, "ques1": "q1", "ques2": "q2"},
                    ques_count=2,
                    modeler_response={"questions_solution": {}},
                    updated_at="now",
                )
            )
            workflow = MathModelWorkFlow()
            workflow.task_id = "task"
            workflow.work_dir = str(work_dir)
            events = []
            output = _RepairOutput()
            report = {
                "status": "FAIL",
                "checks": {
                    "result_consistency": {
                        "passed": False,
                        "severity": "fail",
                        "conflicts": [
                            {
                                "paper_section": "5.2 问题二模型的建立与求解",
                                "location": "body",
                                "sentence": "wrong result",
                            }
                        ],
                        "abstract_conflicts": [],
                    }
                },
            }
            with (
                patch("app.core.workflow.redis_manager.publish_message", AsyncMock()),
                patch("app.core.workflow.build_result_fact_summary", return_value="frozen facts"),
            ):
                repaired = await workflow._repair_writer_preflight_once(
                    output, _Writer(events), checkpoint_manager, report
                )

            self.assertIs(repaired, report)
            self.assertEqual([event[1] for event in events], ["ques2_preflight_repair"])
            self.assertEqual(output.results["ques1"]["response_content"], "paper q1")
            self.assertEqual(output.results["ques2"]["response_content"], "paper ques2_preflight_repair")
            self.assertEqual(output.save_count, 1)
            self.assertEqual(checkpoint_manager._checkpoint.paper_repair_attempts, 1)

    async def test_preflight_repair_accepts_matching_figure_and_result_conflicts(self):
        with tempfile.TemporaryDirectory() as raw_work_dir:
            checkpoint_manager = CheckpointManager(raw_work_dir)
            checkpoint_manager.save(
                TaskCheckpoint(
                    task_id="task",
                    ques_all="test",
                    comp_template="cumcm",
                    format_output="markdown",
                    questions={"ques_count": 2, "ques1": "q1", "ques2": "q2"},
                    ques_count=2,
                    modeler_response={"questions_solution": {}},
                    updated_at="now",
                )
            )
            workflow = MathModelWorkFlow()
            workflow.task_id = "task"
            workflow.work_dir = raw_work_dir
            events = []
            output = _RepairOutput()
            report = {
                "status": "FAIL",
                "checks": {
                    "result_consistency": {
                        "passed": False,
                        "severity": "fail",
                        "conflicts": [
                            {"paper_section": "5.1 问题一模型的建立与求解", "location": "body"}
                        ],
                    },
                    "figure_result_consistency": {
                        "passed": False,
                        "severity": "fail",
                        "conflicts": [
                            {"paper_section": "5.1 问题一模型的建立与求解", "location": "body"}
                        ],
                    },
                }
            }

            with (
                patch("app.core.workflow.redis_manager.publish_message", AsyncMock()),
                patch("app.core.workflow.build_result_fact_summary", return_value="frozen facts"),
            ):
                repaired = await workflow._repair_writer_preflight_once(
                    output, _Writer(events), checkpoint_manager, report
                )

            self.assertIs(repaired, report)
            self.assertEqual([event[1] for event in events], ["ques1_preflight_repair"])
            self.assertEqual(output.results["ques1"]["response_content"], "paper ques1_preflight_repair")
            self.assertEqual(output.results["ques2"]["response_content"], "incorrect paper q2")

    async def test_preflight_non_section_failure_is_not_blindly_rewritten(self):
        with tempfile.TemporaryDirectory() as raw_work_dir:
            checkpoint_manager = CheckpointManager(raw_work_dir)
            checkpoint_manager.save(
                TaskCheckpoint(
                    task_id="task",
                    ques_all="test",
                    comp_template="cumcm",
                    format_output="markdown",
                    questions={"ques_count": 1, "ques1": "q1"},
                    ques_count=1,
                    modeler_response={"questions_solution": {}},
                    updated_at="now",
                )
            )
            workflow = MathModelWorkFlow()
            workflow.task_id = "task"
            workflow.work_dir = raw_work_dir
            output = _RepairOutput()
            report = {
                "status": "FAIL",
                "checks": {
                    "code_appendix": {"passed": False, "severity": "fail"}
                },
            }
            with patch("app.core.workflow.redis_manager.publish_message", AsyncMock()):
                repaired = await workflow._repair_writer_preflight_once(
                    output, _Writer([]), checkpoint_manager, report
                )

            self.assertIsNone(repaired)
            self.assertEqual(checkpoint_manager._checkpoint.paper_repair_attempts, 0)

    async def test_export_stops_before_pdf_when_single_preflight_repair_still_fails(self):
        with tempfile.TemporaryDirectory() as raw_work_dir:
            checkpoint_manager = CheckpointManager(raw_work_dir)
            checkpoint_manager.save(
                TaskCheckpoint(
                    task_id="task",
                    ques_all="test",
                    comp_template="cumcm",
                    format_output="markdown",
                    questions={"ques_count": 2, "ques1": "q1", "ques2": "q2"},
                    ques_count=2,
                    modeler_response={"questions_solution": {}},
                    updated_at="now",
                )
            )
            workflow = MathModelWorkFlow()
            workflow.task_id = "task"
            workflow.work_dir = raw_work_dir
            workflow.questions = {"ques_count": 2, "ques1": "q1", "ques2": "q2"}
            events = []
            output = _RepairOutput()
            failed_report = {
                "status": "FAIL",
                "checks": {
                    "result_consistency": {
                        "passed": False,
                        "severity": "fail",
                        "conflicts": [
                            {"paper_section": "5.2 问题二模型", "location": "body"}
                        ],
                        "abstract_conflicts": [],
                    }
                },
            }
            with (
                patch("app.core.workflow.redis_manager.publish_message", AsyncMock()),
                patch("app.core.workflow.prepare_paper_markdown", side_effect=[failed_report, failed_report]),
                patch("app.core.workflow.build_result_fact_summary", return_value="frozen facts"),
                patch("app.core.workflow.export_markdown_to_pdf") as export_pdf,
            ):
                with self.assertRaisesRegex(RuntimeError, "停止生成候选 PDF"):
                    await workflow._export_results(
                        output,
                        writer_agent=_Writer(events),
                        checkpoint_manager=checkpoint_manager,
                    )

            self.assertEqual([event[1] for event in events], ["ques2_preflight_repair"])
            export_pdf.assert_not_called()
            self.assertEqual(checkpoint_manager._checkpoint.paper_repair_attempts, 1)

    def test_loading_legacy_frozen_checkpoint_resets_completed_repair_budget(self):
        with tempfile.TemporaryDirectory() as raw_work_dir:
            manager = CheckpointManager(raw_work_dir)
            manager.save(
                TaskCheckpoint(
                    task_id="task",
                    ques_all="test",
                    comp_template="cumcm",
                    format_output="markdown",
                    questions={"ques_count": 1, "ques1": "q1"},
                    ques_count=1,
                    modeler_response={"questions_solution": {}},
                    workflow_state="frozen",
                    targeted_repair_attempts=1,
                    last_validation_failure={},
                    updated_at="now",
                )
            )
            loaded = CheckpointManager(raw_work_dir).load()

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.targeted_repair_attempts, 0)


class MainPathPlanReviewTest(unittest.IsolatedAsyncioTestCase):
    """execute() 主路径的计划级契约复核（_validate_plan_with_one_remodel）。

    只验证 helper 的编排（校验→冲突则重建模一次→仍冲突则中止），用一个通用
    ``evidence_terms`` 契约驱动，与具体题面参数规则解耦——入射角等领域规则由
    test_problem_contract 单独覆盖。
    """

    @staticmethod
    def _contract() -> ProblemContract:
        # 通用 requirement：计划文本须同时出现 10° 与 15°，否则判为契约冲突。
        return ProblemContract(
            required_requirements=[
                ContractRequirement(
                    key="dual_angle_evidence",
                    label="计划须使用题面给定的 10° 与 15° 入射角",
                    evidence_terms=["10°", "15°"],
                    source="test",
                )
            ]
        )

    _CONFORMING_PLAN = "使用 10° 与 15° 入射角，对同一晶圆两次测量联合求解"
    _CONFLICTING_PLAN = "假设垂直入射 0°，忽略题面给定角度"

    def _workflow(self) -> MathModelWorkFlow:
        workflow = MathModelWorkFlow()
        workflow.task_id = "task"
        workflow.work_dir = "/tmp/task"
        workflow.questions = {"ques_count": 1, "ques1": "q1"}
        return workflow

    async def test_conforming_plan_passes_without_remodel(self):
        workflow = self._workflow()
        plan = ModelerToCoder(questions_solution={"ques1": self._CONFORMING_PLAN})
        remodel = AsyncMock()

        with patch("app.core.workflow.redis_manager.publish_message", AsyncMock()):
            result = await workflow._validate_plan_with_one_remodel(
                self._contract(), plan, remodel
            )

        self.assertIs(result, plan)
        remodel.assert_not_awaited()

    async def test_conflicting_plan_triggers_one_remodel_then_passes(self):
        workflow = self._workflow()
        bad_plan = ModelerToCoder(questions_solution={"ques1": self._CONFLICTING_PLAN})
        good_plan = ModelerToCoder(questions_solution={"ques1": self._CONFORMING_PLAN})
        remodel = AsyncMock(return_value=good_plan)

        with patch("app.core.workflow.redis_manager.publish_message", AsyncMock()):
            result = await workflow._validate_plan_with_one_remodel(
                self._contract(), bad_plan, remodel
            )

        self.assertIs(result, good_plan)
        remodel.assert_awaited_once()

    async def test_two_conflicting_plans_stop_before_solving(self):
        workflow = self._workflow()
        bad_plan = ModelerToCoder(questions_solution={"ques1": self._CONFLICTING_PLAN})
        still_bad = ModelerToCoder(
            questions_solution={"ques1": "仍假设垂直入射 0°"}
        )
        remodel = AsyncMock(return_value=still_bad)

        with patch("app.core.workflow.redis_manager.publish_message", AsyncMock()):
            with self.assertRaisesRegex(RuntimeError, "连续两次与题面参数契约冲突"):
                await workflow._validate_plan_with_one_remodel(
                    self._contract(), bad_plan, remodel
                )

        remodel.assert_awaited_once()

    async def test_execute_wiring_stops_before_building_solver_agents(self):
        workflow = self._workflow()
        bad_plan = ModelerToCoder(
            questions_solution={"ques1": self._CONFLICTING_PLAN}
        )
        coordinator_response = CoordinatorToModeler(
            questions={"ques_count": 1, "ques1": "q1"},
            ques_count=1,
        )

        with tempfile.TemporaryDirectory() as work_dir:
            with (
                patch("app.core.workflow.create_work_dir", return_value=work_dir),
                patch(
                    "app.core.workflow.build_problem_contract",
                    return_value=self._contract(),
                ),
                patch("app.core.workflow.redis_manager.publish_message", AsyncMock()),
                patch("app.core.workflow.LLMFactory") as llm_factory,
                patch("app.core.workflow.CoordinatorAgent") as coordinator_agent,
                patch("app.core.workflow.ModelerAgent") as modeler_agent,
                patch.object(
                    workflow, "_build_agents", AsyncMock()
                ) as build_agents,
            ):
                llm_factory.return_value.get_all_llms.return_value = (
                    object(),
                    object(),
                    object(),
                    object(),
                )
                coordinator_agent.return_value.run = AsyncMock(
                    return_value=coordinator_response
                )
                modeler_agent.return_value.run = AsyncMock(
                    side_effect=[bad_plan, bad_plan]
                )

                with self.assertRaisesRegex(
                    RuntimeError, "连续两次与题面参数契约冲突"
                ):
                    await workflow.execute(Problem(task_id="task", ques_all="q1"))

        self.assertEqual(modeler_agent.call_count, 2)
        build_agents.assert_not_awaited()

    async def test_resume_revalidates_remodeled_plan_before_building_agents(self):
        with tempfile.TemporaryDirectory() as work_dir:
            checkpoint_manager = CheckpointManager(work_dir)
            checkpoint_manager.save(
                TaskCheckpoint(
                    task_id="task",
                    ques_all="q1",
                    comp_template="CHINA",
                    format_output="Markdown",
                    questions={"ques_count": 1, "ques1": "q1"},
                    ques_count=1,
                    modeler_response={
                        "questions_solution": {
                            "ques1": self._CONFLICTING_PLAN,
                        }
                    },
                    updated_at="now",
                )
            )
            workflow = self._workflow()
            still_bad = ModelerToCoder(
                questions_solution={"ques1": "仍假设垂直入射 0°"}
            )

            with (
                patch("app.core.workflow.get_work_dir", return_value=work_dir),
                patch(
                    "app.core.workflow.build_problem_contract",
                    return_value=self._contract(),
                ),
                patch("app.core.workflow.redis_manager.publish_message", AsyncMock()),
                patch("app.core.workflow.LLMFactory") as llm_factory,
                patch("app.core.workflow.ModelerAgent") as modeler_agent,
                patch.object(
                    workflow, "_archive_unverified_execution_context"
                ) as archive_context,
                patch.object(workflow, "_build_agents", AsyncMock()) as build_agents,
            ):
                llm_factory.return_value.get_all_llms.return_value = (
                    object(),
                    object(),
                    object(),
                    object(),
                )
                modeler_agent.return_value.run = AsyncMock(return_value=still_bad)

                with self.assertRaisesRegex(
                    RuntimeError, "连续两次与题面参数契约冲突"
                ):
                    await workflow.resume("task")

            archive_context.assert_called_once()
            modeler_agent.return_value.run.assert_awaited_once()
            build_agents.assert_not_awaited()


class PreflightRepairableSectionsTest(unittest.TestCase):
    """验证 problem_alignment 章节错位可被映射为待回修的写作节。"""

    def _report(self, issues: list[str]) -> dict:
        return {
            "checks": {
                "problem_alignment": {
                    "passed": False,
                    "severity": "fail",
                    "issues": issues,
                }
            }
        }

    def test_problem_alignment_issues_map_to_ques_sections(self):
        report = self._report(
            [
                "5.1 未以题面要求的双光束/一次反射模型回答问题1。",
                "5.2 未使用附件1/2的碳化硅数据回答问题2。",
                "5.3 未使用附件3/4完成多光束判定和硅外延层计算。",
            ]
        )
        sections = MathModelWorkFlow._preflight_repairable_sections(
            report, {"ques1", "ques2", "ques3", "eda", "firstPage"}
        )
        self.assertEqual(sections, ["ques1", "ques2", "ques3"])

    def test_unnumbered_alignment_issue_covers_declared_questions(self):
        report = self._report(
            ["正文把同一晶圆的双角度测量错误表述为两个独立样品。"]
        )
        sections = MathModelWorkFlow._preflight_repairable_sections(
            report, {"ques1", "ques2", "eda"}
        )
        self.assertEqual(sections, ["ques1", "ques2"])

    def test_non_repairable_check_still_blocks(self):
        report = {
            "checks": {
                "code_appendix": {"passed": False, "severity": "fail"},
            }
        }
        sections = MathModelWorkFlow._preflight_repairable_sections(
            report, {"ques1", "ques2"}
        )
        self.assertEqual(sections, [])


class FormalMetricAttributionAssertionTest(unittest.TestCase):
    """冻结后、Writer 前的 subtask_id 归属断言。"""

    def _write_freeze(self, work_dir, metrics):
        import hashlib
        import json

        source = Path(work_dir, "ques_results.csv")
        source.write_text("verified\n", encoding="utf-8")
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        Path(work_dir, "frozen_results.json").write_text(
            json.dumps(
                {
                    "schema": "mathmodel.result-freeze",
                    "version": 1,
                    "metrics": metrics,
                    "sources": [
                        {"relative_path": "ques_results.csv", "sha256": sha, "role": "evidence"}
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def test_passes_when_all_formal_metrics_have_subtask_id(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._write_freeze(
                work_dir,
                [
                    {"id": "q1_m", "subtask_id": "ques1", "label": "L1", "value": 1.0, "unit": "u", "explanation": "e"},
                    {"id": "q3_m", "subtask_id": "ques3", "label": "L3", "value": 3.0, "unit": "u", "explanation": "e"},
                ],
            )
            workflow = MathModelWorkFlow()
            workflow.work_dir = work_dir
            # 不应抛错
            workflow._assert_formal_metrics_have_subtask_id()

    def test_raises_when_a_metric_lacks_subtask_id(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._write_freeze(
                work_dir,
                [
                    {"id": "q1_m", "subtask_id": "ques1", "label": "L1", "value": 1.0, "unit": "u", "explanation": "e"},
                    {"id": "orphan_m", "label": "无归属", "value": 9.0, "unit": "u", "explanation": "e"},
                ],
            )
            workflow = MathModelWorkFlow()
            workflow.work_dir = work_dir
            with self.assertRaises(RuntimeError) as ctx:
                workflow._assert_formal_metrics_have_subtask_id()
            self.assertIn("无 subtask_id", str(ctx.exception))
            self.assertIn("orphan_m", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
