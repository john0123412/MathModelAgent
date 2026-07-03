import unittest
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


class CoderAgentToolHandlingTest(unittest.IsolatedAsyncioTestCase):
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
