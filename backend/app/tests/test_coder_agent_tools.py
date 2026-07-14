import unittest
import json
import os
import tempfile
from unittest.mock import AsyncMock, patch

from app.config.setting import ApiType
from app.core.agents.coder_agent import CoderAgent
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
                work_dir, "ques1_results.json", {"profit": 2200.0}
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
                work_dir, "ques2_results.json", {"profit": 2366.6666667}
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


if __name__ == "__main__":
    unittest.main()
