import unittest
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import nbformat

from app.config.setting import ApiType
from app.core.agents.coder_agent import (
    CoderAgent,
    _EVIDENCE_FAILURE_LIMIT,
    _formal_evidence_checklist,
)
from app.core.llm.types import StandardResponse, ToolCall
from app.tools.notebook_serializer import NotebookSerializer


class FakeModel:
    api_type = ApiType.ANTHROPIC

    async def chat(self, history, **kwargs):
        if any(msg.get("role") == "tool" and msg.get("tool_call_id") == "bad1" for msg in history):
            return StandardResponse(content="EDA complete without extra tools.")
        return StandardResponse(
            content="I need to list files first.",
            tool_calls=[ToolCall(id="bad1", name="LS", arguments='{"path":"."}')],
        )


class FakeCompatExecuteModel:
    api_type = ApiType.ANTHROPIC

    async def chat(self, history, **kwargs):
        if any(msg.get("role") == "tool" and msg.get("tool_call_id") == "compat1" for msg in history):
            return StandardResponse(content="Code execution done.")
        return StandardResponse(
            content="Executing Python code.",
            tool_calls=[
                ToolCall(
                    id="compat1",
                    name="CompatExecuteCode426487",
                    arguments='{"code":"print(123)"}',
                )
            ],
        )


class FakeRepeatingFinalExecuteModel:
    api_type = ApiType.ANTHROPIC

    def __init__(self):
        self.calls = 0

    async def chat(self, history, **kwargs):
        self.calls += 1
        return StandardResponse(
            content="Generating another completion summary.",
            tool_calls=[
                ToolCall(
                    id=f"final{self.calls}",
                    name="execute_code",
                    arguments='{"code":"print(\\"项目完成，所有文件已生成\\")"}',
                )
            ],
        )


class FakeRepeatingNonFinalExecuteModel:
    api_type = ApiType.ANTHROPIC

    def __init__(self):
        self.calls = 0

    async def chat(self, history, **kwargs):
        self.calls += 1
        return StandardResponse(
            content="Generating another chart.",
            tool_calls=[
                ToolCall(
                    id=f"chart{self.calls}",
                    name="execute_code",
                    arguments=f'{{"code":"print(\\"chart result {self.calls}\\")"}}',
                )
            ],
        )


class FakeCapThenEvidenceModel:
    api_type = ApiType.ANTHROPIC

    def __init__(self):
        self.calls = 0

    async def chat(self, history, **kwargs):
        self.calls += 1
        tool_names = {tool.get("name") for tool in kwargs.get("tools", [])}
        if tool_names == {"record_execution_evidence"}:
            return StandardResponse(
                content="Evidence committed after enforced hand-off.",
                tool_calls=[
                    ToolCall(
                        id="forced-evidence",
                        name="record_execution_evidence",
                        arguments=json.dumps(
                            {
                                "subtask_id": "ques2",
                                "constraints": [
                                    {
                                        "id": "capacity",
                                        "actual": 110.0,
                                        "comparison": "lte",
                                        "target": 110.0,
                                        "source_path": "ques2_results.json",
                                    }
                                ],
                                "metrics": [
                                    {
                                        "id": "new_profit",
                                        "label": "新利润",
                                        "value": 2366.6666667,
                                        "unit": "元",
                                        "explanation": "来自本次线性规划求解。",
                                        "aliases": ["目标函数值"],
                                        "source_path": "ques2_results.json",
                                    }
                                ],
                                "figures": [],
                            },
                            ensure_ascii=False,
                        ),
                    )
                ],
            )
        return StandardResponse(
            content="Generating another chart.",
            tool_calls=[
                ToolCall(
                    id=f"chart{self.calls}",
                    name="execute_code",
                    arguments=f'{{"code":"print(\\"chart result {self.calls}\\")"}}',
                )
            ],
        )


class FakeCloseoutAwareModel:
    api_type = ApiType.ANTHROPIC

    def __init__(self):
        self.calls = 0

    async def chat(self, history, **kwargs):
        self.calls += 1
        closeout_requested = any(
            msg.get("role") == "user" and "只剩 2 次成功代码执行额度" in msg.get("content", "")
            for msg in history
        )
        closeout_executed = any(
            msg.get("tool_call_id") == "closeout-code" for msg in history
        )
        if closeout_requested and closeout_executed:
            return _evidence_response("closeout-evidence", "ques1", "ques1_results.json")
        if closeout_requested:
            return StandardResponse(
                content="Land the declared numeric result source.",
                tool_calls=[
                    ToolCall(
                        id="closeout-code",
                        name="execute_code",
                        arguments='{"code":"print(\\"closeout\\")"}',
                    )
                ],
            )
        return StandardResponse(
            content="Continue exploration.",
            tool_calls=[
                ToolCall(
                    id=f"explore{self.calls}",
                    name="execute_code",
                    arguments=f'{{"code":"print(\\"explore {self.calls}\\")"}}',
                )
            ],
        )


class FakeAlwaysInvalidEvidenceModel:
    api_type = ApiType.ANTHROPIC

    def __init__(self):
        self.calls = 0

    async def chat(self, history, **kwargs):
        self.calls += 1
        if self.calls % 2 == 0:
            return _evidence_response(
                f"invalid-evidence-{self.calls}", "ques1", "missing_results.json"
            )
        return StandardResponse(
            content="Attempt evidence source repair.",
            tool_calls=[
                ToolCall(
                    id=f"repair-code-{self.calls}",
                    name="execute_code",
                    arguments='{"code":"print(1)"}',
                )
            ],
        )


class FakeStaleThenFreshEvidenceModel:
    api_type = ApiType.ANTHROPIC

    async def chat(self, history, **kwargs):
        if any(msg.get("tool_call_id") == "fresh-evidence" for msg in history):
            return StandardResponse(content="Fresh evidence recorded.")
        if any(msg.get("tool_call_id") == "code2" for msg in history):
            return _evidence_response("fresh-evidence", "ques1", "ques1_results.json")
        if any(msg.get("tool_call_id") == "stale-evidence" for msg in history):
            return StandardResponse(
                content="Regenerate the result file.",
                tool_calls=[
                    ToolCall(id="code2", name="execute_code", arguments='{"code":"print(2)"}')
                ],
            )
        if any(msg.get("tool_call_id") == "code1" for msg in history):
            return _evidence_response("stale-evidence", "ques1", "ques1_results.json")
        return StandardResponse(
            content="Compute first.",
            tool_calls=[ToolCall(id="code1", name="execute_code", arguments='{"code":"print(1)"}')],
        )


class FakeCrossQuestionEvidenceModel:
    api_type = ApiType.ANTHROPIC

    async def chat(self, history, **kwargs):
        if any(msg.get("tool_call_id") == "right-evidence" for msg in history):
            return StandardResponse(content="Correct-question evidence recorded.")
        if any(msg.get("tool_call_id") == "wrong-evidence" for msg in history):
            return _evidence_response("right-evidence", "ques2", "ques2_results.json")
        if any(msg.get("tool_call_id") == "code1" for msg in history):
            return _evidence_response("wrong-evidence", "ques1", "ques2_results.json")
        return StandardResponse(
            content="Compute q2.",
            tool_calls=[ToolCall(id="code1", name="execute_code", arguments='{"code":"print(2)"}')],
        )


class FakeParallelToolModel:
    api_type = ApiType.ANTHROPIC

    async def chat(self, history, **kwargs):
        if any(msg.get("tool_call_id") == "parallel-record" for msg in history):
            return StandardResponse(content="No valid tool action was taken.")
        return StandardResponse(
            content="Run and record at once.",
            tool_calls=[
                ToolCall(id="parallel-code", name="execute_code", arguments='{"code":"print(1)"}'),
                ToolCall(
                    id="parallel-record",
                    name="record_execution_evidence",
                    arguments='{"subtask_id":"ques1","constraints":[],"metrics":[],"figures":[]}',
                ),
            ],
        )


def _evidence_response(tool_id, subtask_id, source_path):
    return StandardResponse(
        content="Record the result evidence.",
        tool_calls=[
            ToolCall(
                id=tool_id,
                name="record_execution_evidence",
                arguments=json.dumps(
                    {
                        "subtask_id": subtask_id,
                        "constraints": [
                            {
                                "id": "capacity",
                                "actual": 1.0,
                                "comparison": "gte",
                                "target": 0.0,
                                "source_path": source_path,
                            }
                        ],
                        "metrics": [
                            {
                                "id": "objective_value",
                                "label": "目标函数值",
                                "value": 1.0,
                                "unit": "元",
                                "explanation": "来自本轮求解。",
                                "aliases": [],
                                "source_path": source_path,
                            }
                        ],
                        "figures": [],
                    },
                    ensure_ascii=False,
                ),
            )
        ],
    )


class FakeCrossTaskFileModel:
    api_type = ApiType.ANTHROPIC

    async def chat(self, history, **kwargs):
        if any(msg.get("role") == "tool" and msg.get("tool_call_id") == "cross1" for msg in history):
            return StandardResponse(content="Used current task files only.")
        return StandardResponse(
            content="Reading prior task output.",
            tool_calls=[
                ToolCall(
                    id="cross1",
                    name="execute_code",
                    arguments=(
                        '{"code":"src = \\"../20260703-080537-0ed1df87/result1.xlsx\\"\\n'
                        'print(src)"}'
                    ),
                )
            ],
        )


class FakeEvidenceRecordModel:
    api_type = ApiType.ANTHROPIC

    async def chat(self, history, **kwargs):
        if any(msg.get("role") == "tool" and msg.get("tool_call_id") == "evidence1" for msg in history):
            return StandardResponse(content="Evidence recorded; coding complete.")
        if any(msg.get("role") == "tool" and msg.get("tool_call_id") == "code1" for msg in history):
            return StandardResponse(
                content="Record the executed result.",
                tool_calls=[
                    ToolCall(
                        id="evidence1",
                        name="record_execution_evidence",
                        arguments=json.dumps(
                            {
                                "subtask_id": "ques1",
                                "constraints": [
                                    {
                                        "id": "profit_target",
                                        "actual": 2200.0,
                                        "comparison": "gte",
                                        "target": 0.0,
                                        "source_path": "ques1_results.json",
                                    }
                                ],
                                "metrics": [
                                    {
                                        "id": "profit",
                                        "label": "最大利润",
                                        "value": 2200.0,
                                        "unit": "元",
                                        "explanation": "由实际线性规划求解得到。",
                                        "aliases": [],
                                        "source_path": "ques1_results.json",
                                    }
                                ],
                                "figures": [],
                            },
                            ensure_ascii=False,
                        ),
                    )
                ],
            )
        return StandardResponse(
            content="Solve and save the result.",
            tool_calls=[
                ToolCall(id="code1", name="execute_code", arguments='{"code":"print(2200)"}')
            ],
        )


class FakeNoToolThenExecuteModel:
    """A compatible provider that ignores the first required tool turn."""

    api_type = ApiType.ANTHROPIC

    def __init__(self):
        self.calls = 0
        self.tool_choices = []
        self.offered_tool_names = []
        self.thinking = []

    async def chat(self, history, **kwargs):
        self.calls += 1
        self.tool_choices.append(kwargs.get("tool_choice"))
        self.thinking.append(kwargs.get("thinking"))
        self.offered_tool_names.append(
            {
                tool.get("name") or tool.get("function", {}).get("name")
                for tool in kwargs.get("tools", [])
            }
        )
        if self.calls == 1:
            return StandardResponse(content="I have finished the calculation.")
        if self.calls == 2:
            return StandardResponse(
                content="Execute the calculation.",
                tool_calls=[
                    ToolCall(id="forced-code", name="execute_code", arguments='{"code":"print(2200)"}')
                ],
            )
        if self.calls == 3:
            return _evidence_response("forced-evidence", "ques1", "ques1_results.json")
        return StandardResponse(content="Evidence recorded.")


class FakeNonFormalStaleEvidenceModel:
    """Simulate a provider returning a recorder call that was not offered."""

    api_type = ApiType.ANTHROPIC

    def __init__(self):
        self.offered_tool_names = []

    async def chat(self, history, **kwargs):
        self.offered_tool_names.append(
            {tool.get("name") for tool in kwargs.get("tools", [])}
        )
        if any(
            message.get("tool_call_id") == "eda-stale-evidence"
            for message in history
        ):
            return StandardResponse(content="EDA complete after the rejected stale call.")
        if any(message.get("tool_call_id") == "eda-code" for message in history):
            return StandardResponse(
                content="Attempting a stale formal recorder call.",
                tool_calls=[
                    ToolCall(
                        id="eda-stale-evidence",
                        name="record_execution_evidence",
                        arguments='{"subtask_id":"ques1","constraints":[],"metrics":[],"figures":[]}',
                    )
                ],
            )
        return StandardResponse(
            content="Execute EDA.",
            tool_calls=[
                ToolCall(
                    id="eda-code", name="execute_code", arguments='{"code":"print(1)"}'
                )
            ],
        )


class FakeInterpreter:
    def add_section(self, _title):
        pass

    async def get_created_images(self, _subtask_title):
        return []


class RecordingInterpreter(FakeInterpreter):
    def __init__(self):
        self.executed_code = []

    async def execute_code(self, code):
        self.executed_code.append(code)
        return "ok", False, ""


class FinalOutputInterpreter(RecordingInterpreter):
    async def execute_code(self, code):
        self.executed_code.append(code)
        return "项目完成，所有文件已生成", False, ""


class NonFinalOutputInterpreter(RecordingInterpreter):
    async def execute_code(self, code):
        self.executed_code.append(code)
        return f"图表分析输出 {len(self.executed_code)}", False, ""


class ResultWritingInterpreter(NonFinalOutputInterpreter):
    def __init__(self, work_dir, filename, payload):
        super().__init__()
        self.work_dir = work_dir
        self.filename = filename
        self.payload = payload

    async def execute_code(self, code):
        self.executed_code.append(code)
        payload = {**self.payload, "run": len(self.executed_code)}
        with open(os.path.join(self.work_dir, self.filename), "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return f"图表分析输出 {len(self.executed_code)}", False, ""


class CloseoutResultWritingInterpreter(NonFinalOutputInterpreter):
    def __init__(self, work_dir):
        super().__init__()
        self.work_dir = work_dir

    async def execute_code(self, code):
        self.executed_code.append(code)
        if len(self.executed_code) == 2:
            with open(
                os.path.join(self.work_dir, "ques1_results.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump({"objective_value": 1.0}, handle)
        return f"图表分析输出 {len(self.executed_code)}", False, ""


class SecondRunResultWritingInterpreter(ResultWritingInterpreter):
    async def execute_code(self, code):
        self.executed_code.append(code)
        if len(self.executed_code) > 1:
            payload = {**self.payload, "run": len(self.executed_code)}
            with open(os.path.join(self.work_dir, self.filename), "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
        return f"图表分析输出 {len(self.executed_code)}", False, ""


class FinalResultWritingInterpreter(ResultWritingInterpreter):
    async def execute_code(self, code):
        self.executed_code.append(code)
        payload = {**self.payload, "run": len(self.executed_code)}
        with open(os.path.join(self.work_dir, self.filename), "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return "项目完成，所有文件已生成", False, ""


class FakeEmptyCloseoutModel:
    """证据合格但收束轮 content 为空；后续纯文本叙述轮返回可用叙述。

    记录：代码执行次数、证据轮次、以及是否发生过 tools=None 的纯文本叙述轮。
    """

    api_type = ApiType.ANTHROPIC

    def __init__(self, narration_content="本题采用双光束模型联合拟合并复算厚度。"):
        self.calls = 0
        self.code_calls = 0
        self.narration_calls = 0
        self.narration_content = narration_content

    async def chat(self, history, **kwargs):
        self.calls += 1
        # 纯文本叙述轮：主循环之外，tools 显式为 None。
        if kwargs.get("tools") is None:
            self.narration_calls += 1
            return StandardResponse(content=self.narration_content)
        if any(msg.get("tool_call_id") == "code1" for msg in history):
            # 证据轮：content 为空，只调证据工具。
            resp = _evidence_response("ev1", "ques1", "ques1_results.json")
            resp.content = ""
            return resp
        self.code_calls += 1
        return StandardResponse(
            content="Compute first.",
            tool_calls=[
                ToolCall(id="code1", name="execute_code", arguments='{"code":"print(1)"}')
            ],
        )


class FakeEmptyCloseoutThenBadNarrationModel(FakeEmptyCloseoutModel):
    """叙述轮再次返回空 → 应降级到本题确定性兜底。"""

    def __init__(self, subtask_id="ques1"):
        super().__init__()
        self.subtask_id = subtask_id

    async def chat(self, history, **kwargs):
        self.calls += 1
        if kwargs.get("tools") is None:
            self.narration_calls += 1
            return StandardResponse(content="")
        if any(msg.get("tool_call_id") == "code1" for msg in history):
            resp = _evidence_response(
                "ev1", self.subtask_id, f"{self.subtask_id}_results.json"
            )
            resp.content = ""
            return resp
        self.code_calls += 1
        return StandardResponse(
            content="Compute first.",
            tool_calls=[
                ToolCall(id="code1", name="execute_code", arguments='{"code":"print(1)"}')
            ],
        )


class FakeEmptyCloseoutThenRaisingNarrationModel(FakeEmptyCloseoutModel):
    """叙述轮抛异常（模拟超时/协议错误）→ 应降级到本题确定性兜底。"""

    def __init__(self, subtask_id="ques1"):
        super().__init__()
        self.subtask_id = subtask_id

    async def chat(self, history, **kwargs):
        self.calls += 1
        if kwargs.get("tools") is None:
            self.narration_calls += 1
            raise TimeoutError("narration timed out")
        if any(msg.get("tool_call_id") == "code1" for msg in history):
            resp = _evidence_response(
                "ev1", self.subtask_id, f"{self.subtask_id}_results.json"
            )
            resp.content = ""
            return resp
        self.code_calls += 1
        return StandardResponse(
            content="Compute first.",
            tool_calls=[
                ToolCall(id="code1", name="execute_code", arguments='{"code":"print(1)"}')
            ],
        )


class CoderAgentToolHandlingTest(unittest.IsolatedAsyncioTestCase):
    def test_quality_repair_archives_stale_notebook_and_starts_empty_source(self):
        with tempfile.TemporaryDirectory() as work_dir:
            serializer = NotebookSerializer(work_dir=work_dir)
            serializer.add_code_cell_to_notebook("stale_successful_exploration = 1")
            interpreter = FakeInterpreter()
            interpreter.notebook_serializer = serializer
            agent = CoderAgent(
                task_id="t1",
                model=FakeModel(),
                work_dir=work_dir,
                code_interpreter=interpreter,
            )

            agent.prepare_quality_repair_source()
            agent.prepare_quality_repair_source()

            current = nbformat.read(
                os.path.join(work_dir, "notebook.ipynb"), as_version=4
            )
            self.assertEqual(current.cells, [])
            archived = list(
                Path(work_dir).glob(
                    "failed_attempts/quality_repair/*/notebook.ipynb"
                )
            )
            self.assertEqual(len(archived), 1)
            old = nbformat.read(archived[0], as_version=4)
            self.assertEqual(
                [cell.source for cell in old.cells],
                ["stale_successful_exploration = 1"],
            )

    def test_formal_evidence_checklist_repeats_every_model_plan_constraint(self):
        """正式子题提示必须逐项带入不可省略的计划约束。"""
        with tempfile.TemporaryDirectory() as work_dir:
            with open(
                os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(
                    {
                        "model_plan": {
                            "subtasks": {
                                "ques1": {
                                    "acceptance_metrics": [
                                        {
                                            "key": "pressure_stability_error",
                                            "comparator": "le",
                                            "target": 5.0,
                                        },
                                        {
                                            "key": "transition_time_error",
                                            "comparator": "le",
                                            "target": 0.1,
                                        },
                                    ],
                                    "diagnostic_profile": "simulation",
                                    "diagnostic_requirements": [
                                        "验证系统总质量守恒并记录残差。",
                                        "验证减压阀只在阈值上方开启。",
                                    ],
                                }
                            }
                        }
                    },
                    handle,
                )

            checklist = _formal_evidence_checklist(work_dir, "ques1")

        self.assertIn("pressure_stability_error", checklist)
        self.assertIn("le 5.0", checklist)
        self.assertIn("transition_time_error", checklist)
        self.assertIn("le 0.1", checklist)
        self.assertIn("record_execution_evidence", checklist)
        self.assertIn("不可省略的诊断证据", checklist)
        self.assertIn("质量守恒", checklist)
        self.assertIn("减压阀", checklist)
        self.assertIn("source-backed metric", checklist)

    def test_optimization_evidence_checklist_uses_metrics_and_explicit_solver_guidance(self):
        with tempfile.TemporaryDirectory() as work_dir:
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
                                            "key": "profit_change",
                                            "comparator": "ge",
                                            "target": 0,
                                        }
                                    ],
                                    "diagnostic_profile": "optimization",
                                    "diagnostic_requirements": [
                                        "记录求解器状态、可行性和约束松弛量。"
                                    ],
                                    "expected_artifacts": [
                                        {
                                            "path": "ques2_sensitivity_results.csv",
                                            "kind": "result_table",
                                        }
                                    ],
                                }
                            }
                        }
                    },
                    handle,
                )

            checklist = _formal_evidence_checklist(work_dir, "ques2")

        self.assertIn("record_execution_evidence 的 metrics", checklist)
        self.assertIn("solver_status", checklist)
        self.assertIn("松弛量", checklist)
        self.assertIn("ques2_sensitivity_results.csv", checklist)
        self.assertIn("本轮 execute_code 中新建或更新", checklist)
        self.assertIn("metrics.value", checklist)
        self.assertIn("source_path", checklist)
        self.assertIn("新最优决策变量", checklist)

    async def test_first_run_includes_complete_problem_context_before_eda(self):
        """无附件的确定性题也必须把原始参数传给 EDA Coder。"""
        agent = CoderAgent(
            task_id="t1",
            model=FakeModel(),
            work_dir=".",
            max_chat_turns=3,
            code_interpreter=FakeInterpreter(),
            problem_context="A 需2小时机器、1小时人工，利润40元；机器时间最多100小时。",
        )

        with patch("app.core.agents.coder_agent.redis_manager.publish_message", new=AsyncMock()):
            await agent.run("仅做题面常量核验", "eda")

        user_messages = [
            message["content"]
            for message in agent.chat_history
            if message.get("role") == "user"
        ]
        self.assertIn("完整原始题面", user_messages[0])
        self.assertIn("机器时间最多100小时", user_messages[0])
        self.assertIn("当前文件夹下的数据集文件", user_messages[1])

    async def test_record_execution_evidence_tool_writes_backend_generated_manifest(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "ques1_results.json"), "w", encoding="utf-8") as handle:
                json.dump({"profit": 2200.0}, handle)
            interpreter = ResultWritingInterpreter(
                work_dir, "ques1_results.json", {"profit": 2200.0}
            )
            agent = CoderAgent(
                task_id="t1",
                model=FakeEvidenceRecordModel(),
                work_dir=work_dir,
                max_chat_turns=4,
                code_interpreter=interpreter,
            )

            with patch("app.core.agents.coder_agent.redis_manager.publish_message", new=AsyncMock()):
                result = await agent.run("solve", "ques1")

            self.assertEqual(result.code_response, "Record the executed result.")
            self.assertEqual(interpreter.executed_code, ["print(2200)"])
            with open(os.path.join(work_dir, "execution_validation.json"), encoding="utf-8") as handle:
                manifest = json.load(handle)
            self.assertEqual(manifest["generated_by"], "trusted_record_execution_evidence")
            self.assertEqual(manifest["subtasks"][0]["id"], "ques1")
            self.assertTrue(manifest["subtasks"][0]["feasible"])

    async def test_formal_subtask_recovers_from_plain_text_without_execution(self):
        with tempfile.TemporaryDirectory() as work_dir:
            model = FakeNoToolThenExecuteModel()
            interpreter = ResultWritingInterpreter(
                work_dir, "ques1_results.json", {"profit": 2200.0}
            )
            agent = CoderAgent(
                task_id="t1",
                model=model,
                work_dir=work_dir,
                max_chat_turns=6,
                code_interpreter=interpreter,
            )

            with patch(
                "app.core.agents.coder_agent.redis_manager.publish_message",
                new=AsyncMock(),
            ):
                result = await agent.run("solve", "ques1")

            self.assertTrue(result.execution_succeeded)
            self.assertEqual(interpreter.executed_code, ['print(2200)'])
            self.assertEqual(model.tool_choices[:2], ["any", "any"])
            self.assertEqual(model.thinking[:3], [False, False, False])
            self.assertEqual(model.offered_tool_names[:2], [{"execute_code"}, {"execute_code"}])
            self.assertEqual(
                model.offered_tool_names[2],
                {"execute_code", "record_execution_evidence"},
            )
            self.assertTrue(
                any(
                    message.get("role") == "user"
                    and "尚未执行代码" in message.get("content", "")
                    for message in agent.chat_history
                )
            )

    async def test_unsupported_tool_call_gets_feedback_instead_of_looping(self):
        agent = CoderAgent(
            task_id="t1",
            model=FakeModel(),
            work_dir=".",
            max_chat_turns=3,
            code_interpreter=FakeInterpreter(),
        )

        with patch("app.core.agents.coder_agent.redis_manager.publish_message", new=AsyncMock()):
            result = await agent.run("do eda", "eda")

        self.assertEqual(result.code_response, "EDA complete without extra tools.")
        self.assertFalse(result.execution_attempted)
        self.assertFalse(result.execution_succeeded)
        self.assertTrue(
            any(
                msg.get("role") == "tool"
                and msg.get("tool_call_id") == "bad1"
                and "不支持" in msg.get("content", "")
                for msg in agent.chat_history
            )
        )

    async def test_compat_execute_code_tool_name_is_treated_as_execute_code(self):
        interpreter = RecordingInterpreter()
        agent = CoderAgent(
            task_id="t1",
            model=FakeCompatExecuteModel(),
            work_dir=".",
            max_chat_turns=3,
            code_interpreter=interpreter,
        )

        with patch("app.core.agents.coder_agent.redis_manager.publish_message", new=AsyncMock()):
            result = await agent.run("do eda", "eda")

        self.assertEqual(result.code_response, "Code execution done.")
        self.assertEqual(interpreter.executed_code, ["print(123)"])
        self.assertTrue(result.execution_attempted)
        self.assertTrue(result.execution_succeeded)

    async def test_nonformal_eda_never_records_formal_evidence(self):
        model = FakeNonFormalStaleEvidenceModel()
        interpreter = RecordingInterpreter()
        agent = CoderAgent(
            task_id="t1",
            model=model,
            work_dir=".",
            max_chat_turns=4,
            code_interpreter=interpreter,
        )

        with (
            patch(
                "app.core.agents.coder_agent.redis_manager.publish_message",
                new=AsyncMock(),
            ),
            patch("app.core.agents.coder_agent.record_execution_evidence") as recorder,
        ):
            result = await agent.run("do eda", "eda")

        self.assertEqual(interpreter.executed_code, ["print(1)"])
        self.assertTrue(result.execution_attempted)
        self.assertTrue(result.execution_succeeded)
        self.assertTrue(
            all(
                "record_execution_evidence" not in tool_names
                for tool_names in model.offered_tool_names
            )
        )
        recorder.assert_not_called()
        self.assertTrue(
            any(
                message.get("tool_call_id") == "eda-stale-evidence"
                and "非正式 EDA" in message.get("content", "")
                for message in agent.chat_history
            )
        )

    async def test_repeated_final_tool_outputs_auto_complete(self):
        interpreter = FinalOutputInterpreter()
        agent = CoderAgent(
            task_id="t1",
            model=FakeRepeatingFinalExecuteModel(),
            work_dir=".",
            max_chat_turns=10,
            code_interpreter=interpreter,
        )

        with patch("app.core.agents.coder_agent.redis_manager.publish_message", new=AsyncMock()):
            result = await agent.run("do eda", "eda")

        self.assertIn("项目完成", result.code_response)
        self.assertEqual(len(interpreter.executed_code), 2)

    async def test_repeated_successful_tool_outputs_auto_complete_at_cap(self):
        interpreter = NonFinalOutputInterpreter()
        agent = CoderAgent(
            task_id="t1",
            model=FakeRepeatingNonFinalExecuteModel(),
            work_dir=".",
            max_chat_turns=10,
            max_successful_tool_calls=3,
            code_interpreter=interpreter,
        )

        with patch("app.core.agents.coder_agent.redis_manager.publish_message", new=AsyncMock()):
            result = await agent.run("solve", "eda")

        self.assertEqual(result.code_response, "图表分析输出 3")
        self.assertEqual(len(interpreter.executed_code), 3)

    async def test_formal_subtask_cap_forces_trusted_evidence_handoff(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "ques2_results.json"), "w", encoding="utf-8") as handle:
                json.dump({"machine_time": 110.0, "profit": 2366.6666667}, handle)
            interpreter = ResultWritingInterpreter(
                work_dir,
                "ques2_results.json",
                {"machine_time": 110.0, "profit": 2366.6666667},
            )
            agent = CoderAgent(
                task_id="t1",
                model=FakeCapThenEvidenceModel(),
                work_dir=work_dir,
                max_chat_turns=5,
                max_successful_tool_calls=2,
                code_interpreter=interpreter,
            )

            with patch("app.core.agents.coder_agent.redis_manager.publish_message", new=AsyncMock()):
                result = await agent.run("solve", "ques2_repair")

            self.assertEqual(result.code_response, "Evidence committed after enforced hand-off.")
            self.assertEqual(len(interpreter.executed_code), 2)
            with open(os.path.join(work_dir, "execution_validation.json"), encoding="utf-8") as handle:
                manifest = json.load(handle)
            self.assertEqual(manifest["subtasks"][0]["id"], "ques2")
            self.assertTrue(manifest["subtasks"][0]["feasible"])

    async def test_formal_subtask_warns_at_two_calls_and_lands_results(self):
        with tempfile.TemporaryDirectory() as work_dir:
            interpreter = CloseoutResultWritingInterpreter(work_dir)
            agent = CoderAgent(
                task_id="t1",
                model=FakeCloseoutAwareModel(),
                work_dir=work_dir,
                max_chat_turns=6,
                max_successful_tool_calls=3,
                code_interpreter=interpreter,
            )

            with patch(
                "app.core.agents.coder_agent.redis_manager.publish_message",
                new=AsyncMock(),
            ):
                result = await agent.run("solve", "ques1")

            self.assertTrue(result.execution_succeeded)
            self.assertEqual(len(interpreter.executed_code), 2)
            self.assertTrue(
                any(
                    msg.get("role") == "user"
                    and "只剩 2 次成功代码执行额度" in msg.get("content", "")
                    for msg in agent.chat_history
                )
            )
            self.assertTrue(
                os.path.exists(os.path.join(work_dir, "execution_validation.json"))
            )

    async def test_repeated_invalid_evidence_stops_at_bounded_failure_limit(self):
        with tempfile.TemporaryDirectory() as work_dir:
            interpreter = RecordingInterpreter()
            agent = CoderAgent(
                task_id="t1",
                model=FakeAlwaysInvalidEvidenceModel(),
                work_dir=work_dir,
                max_chat_turns=20,
                max_successful_tool_calls=1,
                code_interpreter=interpreter,
            )

            with patch(
                "app.core.agents.coder_agent.redis_manager.publish_message",
                new=AsyncMock(),
            ):
                result = await agent.run("solve", "ques1")

            self.assertFalse(result.execution_succeeded)
            self.assertTrue(result.execution_error_occurred)
            self.assertIn(
                f"连续 {_EVIDENCE_FAILURE_LIMIT} 次不完整", result.code_response
            )
            self.assertEqual(len(interpreter.executed_code), _EVIDENCE_FAILURE_LIMIT)

    async def test_formal_completion_markers_still_require_evidence(self):
        with tempfile.TemporaryDirectory() as work_dir:
            interpreter = FinalResultWritingInterpreter(
                work_dir,
                "ques2_results.json",
                {"machine_time": 110.0, "profit": 2366.6666667},
            )
            agent = CoderAgent(
                task_id="t1",
                model=FakeCapThenEvidenceModel(),
                work_dir=work_dir,
                max_chat_turns=5,
                max_successful_tool_calls=8,
                code_interpreter=interpreter,
            )

            with patch("app.core.agents.coder_agent.redis_manager.publish_message", new=AsyncMock()):
                result = await agent.run("solve", "ques2")

            self.assertEqual(result.code_response, "Evidence committed after enforced hand-off.")
            self.assertEqual(len(interpreter.executed_code), 2)
            self.assertTrue(os.path.exists(os.path.join(work_dir, "execution_validation.json")))

    async def test_stale_evidence_is_rejected_until_this_turn_updates_result_file(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "ques1_results.json"), "w", encoding="utf-8") as handle:
                json.dump({"old": True}, handle)
            interpreter = SecondRunResultWritingInterpreter(
                work_dir, "ques1_results.json", {"profit": 2200.0, "evidence": 1.0}
            )
            agent = CoderAgent(
                task_id="t1",
                model=FakeStaleThenFreshEvidenceModel(),
                work_dir=work_dir,
                max_chat_turns=6,
                code_interpreter=interpreter,
            )

            with patch("app.core.agents.coder_agent.redis_manager.publish_message", new=AsyncMock()):
                result = await agent.run("solve", "ques1")

            self.assertEqual(result.code_response, "Record the result evidence.")
            self.assertEqual(len(interpreter.executed_code), 2)
            self.assertTrue(
                any(
                    msg.get("tool_call_id") == "stale-evidence"
                    and "本轮实际代码执行新建或更新" in msg.get("content", "")
                    for msg in agent.chat_history
                )
            )

    async def test_formal_turn_cannot_record_another_question(self):
        with tempfile.TemporaryDirectory() as work_dir:
            interpreter = ResultWritingInterpreter(
                work_dir,
                "ques2_results.json",
                {"profit": 2366.6666667, "evidence": 1.0},
            )
            agent = CoderAgent(
                task_id="t1",
                model=FakeCrossQuestionEvidenceModel(),
                work_dir=work_dir,
                max_chat_turns=5,
                code_interpreter=interpreter,
            )

            with patch("app.core.agents.coder_agent.redis_manager.publish_message", new=AsyncMock()):
                await agent.run("solve", "ques2_repair")

            with open(os.path.join(work_dir, "execution_validation.json"), encoding="utf-8") as handle:
                manifest = json.load(handle)
            self.assertEqual(manifest["subtasks"][0]["id"], "ques2")
            self.assertTrue(
                any(
                    msg.get("tool_call_id") == "wrong-evidence"
                    and "只能记录 ques2" in msg.get("content", "")
                    for msg in agent.chat_history
                )
            )

    async def test_parallel_tool_calls_are_rejected_without_orphaned_ids(self):
        interpreter = RecordingInterpreter()
        agent = CoderAgent(
            task_id="t1",
            model=FakeParallelToolModel(),
            work_dir=".",
            max_chat_turns=3,
            code_interpreter=interpreter,
        )

        with patch("app.core.agents.coder_agent.redis_manager.publish_message", new=AsyncMock()):
            result = await agent.run("solve", "ques1")

        self.assertFalse(result.execution_attempted)
        self.assertEqual(interpreter.executed_code, [])
        responses = {
            msg.get("tool_call_id")
            for msg in agent.chat_history
            if msg.get("role") == "tool"
        }
        self.assertEqual(responses, {"parallel-code", "parallel-record"})

    async def test_cross_task_parent_path_is_rejected_before_execution(self):
        interpreter = RecordingInterpreter()
        agent = CoderAgent(
            task_id="t1",
            model=FakeCrossTaskFileModel(),
            work_dir=".",
            max_chat_turns=3,
            code_interpreter=interpreter,
        )

        with patch("app.core.agents.coder_agent.redis_manager.publish_message", new=AsyncMock()):
            result = await agent.run("solve", "ques1")

        self.assertEqual(result.code_response, "Used current task files only.")
        self.assertEqual(interpreter.executed_code, [])
        self.assertTrue(
            any(
                msg.get("role") == "tool"
                and msg.get("tool_call_id") == "cross1"
                and "当前任务目录" in msg.get("content", "")
                for msg in agent.chat_history
            )
        )

    async def test_empty_closeout_triggers_single_controlled_narration_turn(self):
        """方案1：证据合格但收束轮 content 为空时，追加且仅追加一轮受控叙述。

        受控叙述轮不得执行代码、不得增加主循环轮次/retry，也不得留下占位符。
        """
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "ques1_results.json"), "w", encoding="utf-8") as handle:
                json.dump({"objective_value": 1.0}, handle)
            interpreter = ResultWritingInterpreter(
                work_dir, "ques1_results.json", {"objective_value": 1.0}
            )
            model = FakeEmptyCloseoutModel()
            agent = CoderAgent(
                task_id="t1",
                model=model,
                work_dir=work_dir,
                max_chat_turns=6,
                code_interpreter=interpreter,
            )

            with patch("app.core.agents.coder_agent.redis_manager.publish_message", new=AsyncMock()):
                result = await agent.run("solve ques1", "ques1")

            # 叙述轮触发且仅触发一次
            self.assertEqual(model.narration_calls, 1)
            # 返回模型叙述，而非占位符
            self.assertEqual(result.code_response, "本题采用双光束模型联合拟合并复算厚度。")
            self.assertNotEqual(result.code_response, "已在受控收束阶段记录执行证据。")
            # 叙述轮没有触发额外代码执行（只有主循环的那一次）
            self.assertEqual(len(interpreter.executed_code), 1)
            self.assertTrue(result.execution_succeeded)

    async def test_empty_narration_falls_back_to_deterministic_subtask_summary(self):
        """方案2：叙述轮再次返回空 → 用本题确定性兜底，含本题事实、无占位符。"""
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "ques3_results.json"), "w", encoding="utf-8") as handle:
                json.dump({"thickness": 1.0}, handle)
            # 冻结本题指标，供确定性兜底引用
            with open(os.path.join(work_dir, "frozen_results.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "schema": "mathmodel.result-freeze",
                        "version": 1,
                        "metrics": [
                            {
                                "id": "q3_si_thickness",
                                "subtask_id": "ques3",
                                "label": "硅外延层Airy联合厚度",
                                "value": 1.015833,
                                "unit": "um",
                                "explanation": "附件3/4硅晶圆片多光束联合拟合厚度。",
                            }
                        ],
                        "sources": [{"relative_path": "ques3_results.json", "sha256": _sha256_of(work_dir, "ques3_results.json"), "role": "evidence"}],
                    },
                    handle,
                    ensure_ascii=False,
                )
            interpreter = ResultWritingInterpreter(
                work_dir, "ques3_results.json", {"thickness": 1.0}
            )
            model = FakeEmptyCloseoutThenBadNarrationModel(subtask_id="ques3")
            agent = CoderAgent(
                task_id="t1",
                model=model,
                work_dir=work_dir,
                max_chat_turns=6,
                code_interpreter=interpreter,
            )
            # 首条 user 提示带本题 key 和硅晶圆题目，供兜底提取
            agent.chat_history = []

            with patch("app.core.agents.coder_agent.redis_manager.publish_message", new=AsyncMock()):
                result = await agent.run(
                    "ques3 分析附件3和附件4硅晶圆片是否出现多光束干涉", "ques3"
                )

            self.assertEqual(model.narration_calls, 1)
            self.assertNotEqual(result.code_response, "已在受控收束阶段记录执行证据。")
            # 兜底为本题结构化说明，锁定到 ques3 且带本题题目
            self.assertIn("ques3 方法—产物—结果", result.code_response)
            self.assertIn("硅晶圆片是否出现多光束干涉", result.code_response)
            # 不含其它子任务/碳化硅敏感性叙述
            self.assertNotIn("碳化硅", result.code_response)
            self.assertNotIn("sensitivity", result.code_response.lower())

    def test_deterministic_narration_includes_only_current_subtask_facts(self):
        """方案2 单元级：确定性兜底只引用本题冻结指标，排除其它子任务。"""
        from app.core.agents.coder_agent import _deterministic_subtask_narration

        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "ques3_results.json"), "w", encoding="utf-8") as handle:
                handle.write("thickness=1.015833\n")
            with open(os.path.join(work_dir, "frozen_results.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "schema": "mathmodel.result-freeze",
                        "version": 1,
                        "metrics": [
                            {
                                "id": "q3_si_thickness",
                                "subtask_id": "ques3",
                                "label": "硅外延层Airy联合厚度",
                                "value": 1.015833,
                                "unit": "um",
                                "explanation": "附件3/4硅晶圆片多光束联合拟合厚度。",
                            },
                            {
                                "id": "q1_sic_thickness",
                                "subtask_id": "ques1",
                                "label": "碳化硅外延层厚度",
                                "value": 113.235423,
                                "unit": "um",
                                "explanation": "碳化硅双角度联合拟合厚度。",
                            },
                        ],
                        "sources": [
                            {
                                "relative_path": "ques3_results.json",
                                "sha256": _sha256_of(work_dir, "ques3_results.json"),
                                "role": "evidence",
                            }
                        ],
                    },
                    handle,
                    ensure_ascii=False,
                )
            narration = _deterministic_subtask_narration(
                work_dir,
                "ques3",
                "分析附件3和附件4硅晶圆片是否出现多光束干涉",
                "对附件3/4硅晶圆片双角度联合拟合并做多光束条件审计。",
                ["ques3_multibeam_condition_audit.csv", "ques3_results.csv"],
            )

        # 含本题冻结指标
        self.assertIn("硅外延层Airy联合厚度", narration)
        self.assertIn("1.015833", narration)
        # 含本题产物与方法
        self.assertIn("ques3_multibeam_condition_audit.csv", narration)
        self.assertIn("多光束条件审计", narration)
        # 严格排除其它子任务（碳化硅 ques1）的指标
        self.assertNotIn("碳化硅外延层厚度", narration)
        self.assertNotIn("113.235423", narration)

    async def test_narration_exception_falls_back_to_deterministic_summary(self):
        """方案2：叙述轮抛异常（超时）→ 立即降级到确定性兜底，不卡住收束。"""
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "ques1_results.json"), "w", encoding="utf-8") as handle:
                json.dump({"objective_value": 1.0}, handle)
            interpreter = ResultWritingInterpreter(
                work_dir, "ques1_results.json", {"objective_value": 1.0}
            )
            model = FakeEmptyCloseoutThenRaisingNarrationModel()
            agent = CoderAgent(
                task_id="t1",
                model=model,
                work_dir=work_dir,
                max_chat_turns=6,
                code_interpreter=interpreter,
            )

            with patch("app.core.agents.coder_agent.redis_manager.publish_message", new=AsyncMock()):
                result = await agent.run("ques1 求最优方案", "ques1")

            self.assertEqual(model.narration_calls, 1)
            self.assertNotEqual(result.code_response, "已在受控收束阶段记录执行证据。")
            self.assertIn("ques1", result.code_response)
            self.assertTrue(result.execution_succeeded)


class TestPersistentFailureBudget(unittest.IsolatedAsyncioTestCase):
    def test_load_and_save_evidence_failure_count(self):
        from app.core.agents.coder_agent import (
            _load_evidence_failure_count,
            _save_evidence_failure_count,
            _reset_evidence_failure_count,
        )
        with tempfile.TemporaryDirectory() as work_dir:
            self.assertEqual(_load_evidence_failure_count(work_dir, "ques1"), 0)
            _save_evidence_failure_count(work_dir, "ques1", 2, task_id="task-test")
            self.assertEqual(_load_evidence_failure_count(work_dir, "ques1", task_id="task-test"), 2)
            # Other subtasks independent
            self.assertEqual(_load_evidence_failure_count(work_dir, "ques2"), 0)
            _save_evidence_failure_count(work_dir, "ques2", 1, task_id="task-test")
            self.assertEqual(_load_evidence_failure_count(work_dir, "ques1", task_id="task-test"), 2)
            self.assertEqual(_load_evidence_failure_count(work_dir, "ques2", task_id="task-test"), 1)
            # Reset ques1
            _reset_evidence_failure_count(work_dir, "ques1", task_id="task-test")
            self.assertEqual(_load_evidence_failure_count(work_dir, "ques1", task_id="task-test"), 0)
            self.assertEqual(_load_evidence_failure_count(work_dir, "ques2", task_id="task-test"), 1)

    def test_fail_closed_on_corrupt_budget_json(self):
        from app.core.agents.coder_agent import _load_evidence_failure_count
        with tempfile.TemporaryDirectory() as work_dir:
            budget_file = Path(work_dir) / "evidence_failure_budget.json"
            budget_file.write_text("{corrupt json ...", encoding="utf-8")
            # 异常 JSON 触发 fail-closed，直接返回最大限制 3
            self.assertEqual(_load_evidence_failure_count(work_dir, "ques1"), 3)

    def test_fail_closed_on_invalid_count_or_plan_mismatch(self):
        from app.core.agents.coder_agent import (
            _load_evidence_failure_count,
            _find_cross_task_path,
            _save_evidence_failure_count,
        )
        with tempfile.TemporaryDirectory() as work_dir:
            budget_file = Path(work_dir) / "evidence_failure_budget.json"
            # 1. String count
            budget_file.write_text(
                json.dumps({"task_id": "t1", "subtasks": {"ques1": {"count": "2", "plan_sha256": "sha1"}}}),
                encoding="utf-8",
            )
            self.assertEqual(_load_evidence_failure_count(work_dir, "ques1", task_id="t1", plan_sha256="sha1"), 3)

            # 2. Negative count
            budget_file.write_text(
                json.dumps({"task_id": "t1", "subtasks": {"ques1": {"count": -100, "plan_sha256": "sha1"}}}),
                encoding="utf-8",
            )
            self.assertEqual(_load_evidence_failure_count(work_dir, "ques1", task_id="t1", plan_sha256="sha1"), 3)

            # 3. Plan sha256 mismatch
            budget_file.write_text(
                json.dumps({"task_id": "t1", "subtasks": {"ques1": {"count": 1, "plan_sha256": "wrong_sha"}}}),
                encoding="utf-8",
            )
            self.assertEqual(_load_evidence_failure_count(work_dir, "ques1", task_id="t1", plan_sha256="correct_sha"), 3)

            # 4. Missing task_id or plan_sha256
            budget_file.write_text(
                json.dumps({"subtasks": {"ques1": {"count": 1, "plan_sha256": "sha1"}}}),
                encoding="utf-8",
            )
            self.assertEqual(_load_evidence_failure_count(work_dir, "ques1", task_id="t1", plan_sha256="sha1"), 3)

            budget_file.write_text(
                json.dumps({"task_id": "t1", "subtasks": {"ques1": {"count": 1}}}),
                encoding="utf-8",
            )
            self.assertEqual(_load_evidence_failure_count(work_dir, "ques1", task_id="t1", plan_sha256="sha1"), 3)

            # 5. Legacy bare integer subtask record
            budget_file.write_text(
                json.dumps({"task_id": "t1", "subtasks": {"ques1": 2}}),
                encoding="utf-8",
            )
            self.assertEqual(_load_evidence_failure_count(work_dir, "ques1", task_id="t1", plan_sha256="sha1"), 3)

            # 6. Anti-tampering check (including string concatenation)
            self.assertIsNotNone(_find_cross_task_path('open("evidence_failure_budget.json", "w")'))
            self.assertIsNotNone(_find_cross_task_path('os.remove("evidence_failure_budget.json")'))
            self.assertIsNotNone(_find_cross_task_path('name = "evidence_failure_" + "budget.json"\nopen(name, "w")'))

            # 7. Runtime protected files snapshot & auto-restoration integrity test
            from app.core.agents.coder_agent import _snapshot_protected_files, _verify_and_restore_protected_files
            budget_file.write_text(json.dumps({"task_id": "t1", "subtasks": {"ques1": {"count": 2, "plan_sha256": "sha1"}}}), encoding="utf-8")
            snapshots = _snapshot_protected_files(work_dir)
            # 模拟执行代码通过动态变量或系统调用篡改文件
            tampered_name = "evidence_" + "failure_" + "budget.json"
            (Path(work_dir) / tampered_name).write_text(json.dumps({"task_id": "t1", "subtasks": {"ques1": {"count": 0, "plan_sha256": "sha1"}}}), encoding="utf-8")
            ok, err = _verify_and_restore_protected_files(work_dir, snapshots)
            self.assertFalse(ok)
            self.assertIn("非法篡改", err)
            # 验证已被自动恢复为原内容
            restored = json.loads(budget_file.read_text(encoding="utf-8"))
            self.assertEqual(restored["subtasks"]["ques1"]["count"], 2)

            # 8. Save failure raises RuntimeError fail-closed
            with patch("builtins.open", side_effect=OSError("Disk full")):
                with self.assertRaises(RuntimeError) as caught:
                    _save_evidence_failure_count(work_dir, "ques1", 1, task_id="t1")
                self.assertIn("FAIL_CLOSED", str(caught.exception))

    async def test_circuit_breaker_immediately_raises_on_resumed_instance_without_calling_llm(self):
        from app.core.agents.coder_agent import CoderAgent, _save_evidence_failure_count
        with tempfile.TemporaryDirectory() as work_dir:
            _save_evidence_failure_count(work_dir, "ques1", 3, task_id="task-circuit")
            chat_mock = AsyncMock()
            agent = CoderAgent(
                task_id="task-circuit",
                model=chat_mock,
                work_dir=work_dir,
                code_interpreter=FinalOutputInterpreter(),
            )
            with patch("app.core.agents.coder_agent.redis_manager.publish_message", AsyncMock()):
                with self.assertRaises(RuntimeError) as caught:
                    await agent.run("求解ques1", "ques1")
            self.assertIn("PLAN_CONFLICT", str(caught.exception))
            chat_mock.assert_not_called()


    def test_protected_files_integrity_four_paths(self):
        from app.core.agents.coder_agent import _snapshot_protected_files, _verify_and_restore_protected_files
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)

            # 1. 路径一：原本不存在的文件被新建 -> 必须检测、删除并返回 False
            before = _snapshot_protected_files(work_dir)
            self.assertIsNone(before.get("checkpoint.json"))
            # 模拟代码执行非法创建 checkpoint.json
            (root / "checkpoint.json").write_text("{}", encoding="utf-8")
            ok, err = _verify_and_restore_protected_files(work_dir, before)
            self.assertFalse(ok)
            self.assertIn("新建，已清理", err)
            self.assertFalse((root / "checkpoint.json").exists())

            # 2. 路径二：原本存在的文件被修改 -> 必须检测、恢复并返回 False
            (root / "evidence_failure_budget.json").write_text('{"count": 1}', encoding="utf-8")
            before_mod = _snapshot_protected_files(work_dir)
            # 模拟代码篡改
            (root / "evidence_failure_budget.json").write_text('{"count": 0}', encoding="utf-8")
            ok, err = _verify_and_restore_protected_files(work_dir, before_mod)
            self.assertFalse(ok)
            self.assertIn("篡改，已恢复", err)
            self.assertEqual((root / "evidence_failure_budget.json").read_text(encoding="utf-8"), '{"count": 1}')

            # 3. 路径三：原本存在的文件被删除 -> 必须检测、恢复并返回 False
            before_del = _snapshot_protected_files(work_dir)
            (root / "evidence_failure_budget.json").unlink()
            ok, err = _verify_and_restore_protected_files(work_dir, before_del)
            self.assertFalse(ok)
            self.assertIn("删除，已恢复", err)
            self.assertEqual((root / "evidence_failure_budget.json").read_text(encoding="utf-8"), '{"count": 1}')

            # 4. 路径四：执行抛出异常 -> finally 块中复核仍能恢复被修改的文件
            before_exc = _snapshot_protected_files(work_dir)
            try:
                (root / "evidence_failure_budget.json").write_text('{"tampered": true}', encoding="utf-8")
                raise RuntimeError("Interpreter error")
            except RuntimeError:
                pass
            finally:
                ok_exc, err_exc = _verify_and_restore_protected_files(work_dir, before_exc)
            self.assertFalse(ok_exc)
            self.assertIn("篡改，已恢复", err_exc)
            self.assertEqual((root / "evidence_failure_budget.json").read_text(encoding="utf-8"), '{"count": 1}')

    def test_protected_files_concurrent_multi_file_tamper_restoration(self):
        """同时篡改 checkpoint.json、frozen_results.json 并新建 evidence_failure_budget.json，三项必须一次性全部恢复与清理。"""
        from app.core.agents.coder_agent import _snapshot_protected_files, _verify_and_restore_protected_files

        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            (root / "checkpoint.json").write_text('{"task": "orig_checkpoint"}', encoding="utf-8")
            (root / "frozen_results.json").write_text('{"task": "orig_frozen"}', encoding="utf-8")

            # 初始快照：checkpoint 与 frozen_results 存在，evidence_failure_budget 不存在
            before = _snapshot_protected_files(work_dir)
            self.assertIsNotNone(before["checkpoint.json"])
            self.assertIsNotNone(before["frozen_results.json"])
            self.assertIsNone(before["evidence_failure_budget.json"])

            # 模拟代码同时篡改两者并新建第三者
            (root / "checkpoint.json").write_text('{"task": "tampered_checkpoint"}', encoding="utf-8")
            (root / "frozen_results.json").write_text('{"task": "tampered_frozen"}', encoding="utf-8")
            (root / "evidence_failure_budget.json").write_text('{"task": "illegal_created"}', encoding="utf-8")

            ok, err = _verify_and_restore_protected_files(work_dir, before)
            self.assertFalse(ok)
            # 必须收集到全部 3 个违规项
            self.assertIn("checkpoint.json", err)
            self.assertIn("frozen_results.json", err)
            self.assertIn("evidence_failure_budget.json", err)

            # 两个篡改文件必须已原子恢复原始内容
            self.assertEqual((root / "checkpoint.json").read_text(encoding="utf-8"), '{"task": "orig_checkpoint"}')
            self.assertEqual((root / "frozen_results.json").read_text(encoding="utf-8"), '{"task": "orig_frozen"}')
            # 非法新建文件必须已被清理删除
            self.assertFalse((root / "evidence_failure_budget.json").exists())

    def test_protected_files_snapshot_read_failure_raises_snapshot_failed(self):
        """反例：快照时存在受保护文件但读取失败，必须 fail-closed 抛出 PROTECTED_FILE_SNAPSHOT_FAILED。"""
        from app.core.agents.coder_agent import _snapshot_protected_files

        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            target = root / "checkpoint.json"
            target.write_text("{}", encoding="utf-8")

            with patch.object(Path, "read_bytes", side_effect=PermissionError("Permission Denied")):
                with self.assertRaises(RuntimeError) as caught:
                    _snapshot_protected_files(work_dir)
                self.assertIn("PROTECTED_FILE_SNAPSHOT_FAILED", str(caught.exception))

    def test_protected_files_recovery_failure_does_not_report_restored(self):
        """反例：原子恢复失败时不得报告'已恢复'，必须明确包含 PROTECTED_FILE_RECOVERY_FAILED。"""
        from app.core.agents.coder_agent import _snapshot_protected_files, _verify_and_restore_protected_files

        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            target = root / "checkpoint.json"
            target.write_text('{"task": "orig"}', encoding="utf-8")

            before = _snapshot_protected_files(work_dir)
            target.write_text('{"task": "tampered"}', encoding="utf-8")

            # 模拟原子写入失败
            with patch("app.core.agents.coder_agent._atomic_write_bytes", side_effect=OSError("Disk Full")):
                ok, err = _verify_and_restore_protected_files(work_dir, before)
                self.assertFalse(ok)
                self.assertIn("PROTECTED_FILE_RECOVERY_FAILED", err)
                self.assertNotIn("已恢复", err)

    def test_protected_files_cleanup_failure_does_not_report_cleaned(self):
        """反例：删除非法新建文件失败时不得报告'已清理'，必须明确包含 PROTECTED_FILE_RECOVERY_FAILED。"""
        from app.core.agents.coder_agent import _snapshot_protected_files, _verify_and_restore_protected_files

        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            before = _snapshot_protected_files(work_dir)
            target = root / "evidence_failure_budget.json"
            target.write_text('{"task": "illegal"}', encoding="utf-8")
            # 模拟删除失败
            with patch.object(Path, "unlink", side_effect=PermissionError("Locked")):
                ok, err = _verify_and_restore_protected_files(work_dir, before)
                self.assertFalse(ok)
                self.assertIn("PROTECTED_FILE_RECOVERY_FAILED", err)
                self.assertNotIn("已清理", err)

    async def test_coder_run_execution_exception_with_tamper_exposes_security_error(self):
        """反例：代码执行抛出异常且同时篡改受保护文件，安全/恢复错误必须明确暴露并抛出 ProtectedFileTamperError。"""
        from app.core.agents.coder_agent import CoderAgent, ProtectedFileTamperError
        from app.core.llm.types import ToolCall

        class TamperingAndFailingInterpreter(FakeInterpreter):
            def __init__(self, work_dir):
                self.work_dir = work_dir
            async def execute_code(self, code):
                # 篡改受保护文件
                (Path(self.work_dir) / "checkpoint.json").write_text('{"tampered": true}', encoding="utf-8")
                # 模拟执行抛出异常
                raise ZeroDivisionError("division by zero in user code")

        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            (root / "checkpoint.json").write_text('{"task": "original"}', encoding="utf-8")

            call_count = 0
            async def _fake_chat(**kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return StandardResponse(
                        content=None,
                        tool_calls=[ToolCall(id="tc1", name="execute_code", arguments='{"code": "1/0"}')],
                    )
                return StandardResponse(content="停止", tool_calls=None)

            agent = CoderAgent(
                task_id="task-tamper-exc",
                model=AsyncMock(),
                work_dir=work_dir,
                code_interpreter=TamperingAndFailingInterpreter(work_dir),
            )
            agent._chat = _fake_chat

            with patch("app.core.agents.coder_agent.redis_manager.publish_message", AsyncMock()):
                with self.assertRaises(ProtectedFileTamperError) as caught:
                    await agent.run("求解ques1", "ques1")
                self.assertIn("SecurityError", str(caught.exception))

            # 验证篡改文件已恢复
            self.assertEqual((root / "checkpoint.json").read_text(encoding="utf-8"), '{"task": "original"}')
            self.assertEqual(call_count, 1)
    async def test_coder_run_tamper_restored_raises_tamper_error_and_terminates(self):
        """集成反例：execute_code 篡改受保护文件后，即使原子恢复成功，也必须立即抛出 ProtectedFileTamperError，且 _chat 严格只调用 1 次。"""
        from app.core.agents.coder_agent import CoderAgent, ProtectedFileTamperError
        from app.core.llm.types import ToolCall

        class TamperingInterpreter(FakeInterpreter):
            def __init__(self, work_dir):
                self.work_dir = work_dir
            async def execute_code(self, code):
                (Path(self.work_dir) / "checkpoint.json").write_text('{"tampered": true}', encoding="utf-8")
                return "ok", False, ""

        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            (root / "checkpoint.json").write_text('{"task": "original"}', encoding="utf-8")

            call_count = 0
            async def _fake_chat(**kwargs):
                nonlocal call_count
                call_count += 1
                return StandardResponse(
                    content=None,
                    tool_calls=[ToolCall(id="tc1", name="execute_code", arguments='{"code": "print(1)"}')],
                )

            agent = CoderAgent(
                task_id="task-tamper-restored",
                model=AsyncMock(),
                work_dir=work_dir,
                code_interpreter=TamperingInterpreter(work_dir),
            )
            agent._chat = _fake_chat

            with patch("app.core.agents.coder_agent.redis_manager.publish_message", AsyncMock()):
                with self.assertRaises(ProtectedFileTamperError) as caught:
                    await agent.run("求解ques1", "ques1")
                self.assertIn("SecurityError", str(caught.exception))

            # 1. 验证文件已成功恢复
            self.assertEqual((root / "checkpoint.json").read_text(encoding="utf-8"), '{"task": "original"}')
            # 2. 验证 _chat 严格只调用 1 次（不进行第二轮模型调用）
            self.assertEqual(call_count, 1)

    async def test_coder_run_recovery_failure_terminates_immediately_single_chat_turn(self):
        """集成反例：受保护文件恢复失败时，CoderAgent.run 必须立即抛出 ProtectedFileRecoveryError 且 _chat 只调用 1 次，禁止进入下一轮重试。"""
        from app.core.agents.coder_agent import CoderAgent, ProtectedFileRecoveryError
        from app.core.llm.types import ToolCall

        class TamperingInterpreter(FakeInterpreter):
            def __init__(self, work_dir):
                self.work_dir = work_dir
            async def execute_code(self, code):
                (Path(self.work_dir) / "checkpoint.json").write_text('{"tampered": true}', encoding="utf-8")
                return "ok", False, ""

        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            (root / "checkpoint.json").write_text('{"task": "original"}', encoding="utf-8")

            call_count = 0
            async def _fake_chat(**kwargs):
                nonlocal call_count
                call_count += 1
                return StandardResponse(
                    content=None,
                    tool_calls=[ToolCall(id="tc1", name="execute_code", arguments='{"code": "print(1)"}')],
                )

            agent = CoderAgent(
                task_id="task-recovery-fail",
                model=AsyncMock(),
                work_dir=work_dir,
                code_interpreter=TamperingInterpreter(work_dir),
            )
            agent._chat = _fake_chat

            with patch("app.core.agents.coder_agent._atomic_write_bytes", side_effect=OSError("Disk Full")):
                with patch("app.core.agents.coder_agent.redis_manager.publish_message", AsyncMock()):
                    with self.assertRaises(ProtectedFileRecoveryError) as caught:
                        await agent.run("求解ques1", "ques1")
                    self.assertIn("PROTECTED_FILE_RECOVERY_FAILED", str(caught.exception))

            # 必须只调用一次，绝不能进入第二轮或重试
            self.assertEqual(call_count, 1)

    async def test_coder_run_snapshot_failure_terminates_immediately(self):
        """集成反例：受保护文件快照失败时，CoderAgent.run 必须立即抛出 ProtectedFileSnapshotError 且不进入重试。"""
        from app.core.agents.coder_agent import CoderAgent, ProtectedFileSnapshotError
        from app.core.llm.types import ToolCall

        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            (root / "checkpoint.json").write_text('{"task": "original"}', encoding="utf-8")

            call_count = 0
            async def _fake_chat(**kwargs):
                nonlocal call_count
                call_count += 1
                return StandardResponse(
                    content=None,
                    tool_calls=[ToolCall(id="tc1", name="execute_code", arguments='{"code": "print(1)"}')],
                )

            agent = CoderAgent(
                task_id="task-snap-fail",
                model=AsyncMock(),
                work_dir=work_dir,
                code_interpreter=FakeInterpreter(),
            )
            agent._chat = _fake_chat

            with patch.object(Path, "read_bytes", side_effect=PermissionError("Permission Denied")):
                with patch("app.core.agents.coder_agent.redis_manager.publish_message", AsyncMock()):
                    with self.assertRaises(ProtectedFileSnapshotError) as caught:
                        await agent.run("求解ques1", "ques1")
                    self.assertIn("PROTECTED_FILE_SNAPSHOT_FAILED", str(caught.exception))

            # 必须立即终止，不发生多轮重试
            self.assertEqual(call_count, 1)


def _sha256_of(work_dir, filename):
    import hashlib

    with open(os.path.join(work_dir, filename), "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


if __name__ == "__main__":
    unittest.main()
