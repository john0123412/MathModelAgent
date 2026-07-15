"""CoordinatorAgent 拆题输出结构校验测试。

验证结构问题（缺 background、ques_count 与 quesN 键不一致等）在拆题阶段
就触发重试或失败，而不是数小时后在写作/导出阶段才 KeyError。
"""

import json
import unittest

from app.core.agents.coordinator_agent import (
    MAX_JSON_REPAIR_ATTEMPTS,
    CoordinatorAgent,
    _validate_questions_payload,
)
from app.core.llm.types import StandardResponse


def _valid_payload() -> dict:
    """构造一份应通过校验的最小拆题 payload。"""
    return {
        "title": "生产计划",
        "background": "工厂生产两种产品，资源有限。",
        "ques_count": 2,
        "ques1": "求最优生产方案。",
        "ques2": "分析资源约束的影子价格。",
    }


class FakeLLM:
    """按预设脚本顺序返回响应的假 LLM，不触发网络与 Redis。"""

    def __init__(self, responses: list[StandardResponse]):
        self.responses = list(responses)
        self.calls = 0

    async def chat(self, history=None, agent_name=None, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


def _make_agent(responses: list[StandardResponse]) -> CoordinatorAgent:
    """构造使用假 LLM 的 CoordinatorAgent（无取消事件、无用户插话）。"""
    return CoordinatorAgent(
        task_id="task-test",
        model=FakeLLM(responses),
        cancel_event=None,
        user_input_provider=None,
    )


class CoordinatorRunValidationTest(unittest.IsolatedAsyncioTestCase):
    """CoordinatorAgent.run 的结构校验重试与失败行为。"""

    async def test_missing_background_triggers_retry_then_succeeds(self):
        # 用例 A：第一轮缺 background 应触发重试，第二轮补全后成功
        bad = _valid_payload()
        del bad["background"]
        agent = _make_agent(
            [
                StandardResponse(
                    content=json.dumps(bad, ensure_ascii=False),
                    reasoning_content="第一次拆题思考",
                ),
                StandardResponse(
                    content=json.dumps(_valid_payload(), ensure_ascii=False)
                ),
            ]
        )

        result = await agent.run("题目全文")

        self.assertEqual(agent.model.calls, 2)
        self.assertEqual(result.ques_count, 2)
        self.assertIn("background", result.questions)

        # 历史中只允许最初一条 system 消息，重试不得堆叠 system
        system_msgs = [m for m in agent.chat_history if m["role"] == "system"]
        self.assertEqual(len(system_msgs), 1)

        # 上一轮 assistant 原始输出必须回到历史，且带 reasoning_content
        assistant_msgs = [
            m for m in agent.chat_history if m["role"] == "assistant"
        ]
        self.assertEqual(len(assistant_msgs), 1)
        self.assertIn("ques1", assistant_msgs[0]["content"])
        self.assertEqual(
            assistant_msgs[0].get("reasoning_content"), "第一次拆题思考"
        )

        # assistant 之后应跟一条包含具体校验问题的 user 纠错消息
        assistant_idx = agent.chat_history.index(assistant_msgs[0])
        correction = agent.chat_history[assistant_idx + 1]
        self.assertEqual(correction["role"], "user")
        self.assertIn("background", correction["content"])
        self.assertIn("JSON", correction["content"])

    async def test_inconsistent_ques_count_exhausts_retries(self):
        # 用例 B：ques_count=3 但只有 ques1/ques2，三轮均失败后抛 ValueError
        bad = _valid_payload()
        bad["ques_count"] = 3
        agent = _make_agent(
            [
                StandardResponse(content=json.dumps(bad, ensure_ascii=False))
                for _ in range(MAX_JSON_REPAIR_ATTEMPTS)
            ]
        )

        with self.assertRaises(ValueError) as ctx:
            await agent.run("题目全文")

        message = str(ctx.exception)
        self.assertIn("ques3", message)
        self.assertIn(str(MAX_JSON_REPAIR_ATTEMPTS), message)
        self.assertEqual(agent.model.calls, MAX_JSON_REPAIR_ATTEMPTS)

    async def test_valid_output_with_numeric_string_count_passes_once(self):
        # 用例 D：数字字符串 ques_count="2" 一次通过并归一化为 int
        payload = _valid_payload()
        payload["ques_count"] = "2"
        agent = _make_agent(
            [
                StandardResponse(
                    content="```json\n"
                    + json.dumps(payload, ensure_ascii=False)
                    + "\n```"
                )
            ]
        )

        result = await agent.run("题目全文")

        self.assertEqual(agent.model.calls, 1)
        self.assertIsInstance(result.ques_count, int)
        self.assertEqual(result.ques_count, 2)
        self.assertIsInstance(result.questions["ques_count"], int)
        self.assertEqual(result.questions["ques_count"], 2)


class ValidateQuestionsPayloadTest(unittest.TestCase):
    """_validate_questions_payload 纯函数的校验规则。"""

    def test_valid_payload_returns_no_issues(self):
        self.assertEqual(_validate_questions_payload(_valid_payload()), [])

    def test_numeric_string_ques_count_is_accepted(self):
        payload = _valid_payload()
        payload["ques_count"] = "2"
        self.assertEqual(_validate_questions_payload(payload), [])

    def test_non_dict_payload_is_rejected(self):
        issues = _validate_questions_payload(["not", "a", "dict"])
        self.assertEqual(len(issues), 1)
        self.assertIn("JSON 对象", issues[0])

    def test_missing_ques_count_is_reported(self):
        payload = _valid_payload()
        del payload["ques_count"]
        issues = _validate_questions_payload(payload)
        self.assertTrue(any("ques_count" in issue for issue in issues))

    def test_non_integer_ques_count_is_reported(self):
        for bad_count in ("三", 2.5, 0, -1, True):
            payload = _valid_payload()
            payload["ques_count"] = bad_count
            issues = _validate_questions_payload(payload)
            self.assertTrue(
                any("ques_count" in issue for issue in issues),
                msg=f"ques_count={bad_count!r} 应被判为问题",
            )

    def test_missing_background_is_reported(self):
        payload = _valid_payload()
        del payload["background"]
        issues = _validate_questions_payload(payload)
        self.assertTrue(any("background" in issue for issue in issues))

    def test_blank_background_is_reported(self):
        payload = _valid_payload()
        payload["background"] = "   "
        issues = _validate_questions_payload(payload)
        self.assertTrue(any("background" in issue for issue in issues))

    def test_missing_question_key_is_reported(self):
        payload = _valid_payload()
        del payload["ques2"]
        issues = _validate_questions_payload(payload)
        self.assertTrue(any("ques2" in issue for issue in issues))

    def test_blank_question_value_is_reported(self):
        payload = _valid_payload()
        payload["ques1"] = ""
        issues = _validate_questions_payload(payload)
        self.assertTrue(any("ques1" in issue for issue in issues))

    def test_extra_question_key_beyond_count_is_reported(self):
        # 用例 C：ques_count=3 但出现 ques4，防止 ques_count 偏小静默丢题
        payload = _valid_payload()
        payload["ques_count"] = 3
        payload["ques3"] = "第三问。"
        payload["ques4"] = "第四问不该存在。"
        issues = _validate_questions_payload(payload)
        self.assertTrue(any("ques4" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
