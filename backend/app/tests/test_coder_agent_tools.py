import unittest
import json
import os
import tempfile
from unittest.mock import AsyncMock, patch

from app.config.setting import ApiType
from app.core.agents.coder_agent import CoderAgent, _EVIDENCE_FAILURE_LIMIT
from app.core.llm.types import StandardResponse, ToolCall


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


def _sha256_of(work_dir, filename):
    import hashlib

    with open(os.path.join(work_dir, filename), "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


if __name__ == "__main__":
    unittest.main()
