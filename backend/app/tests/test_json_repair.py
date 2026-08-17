"""json_repair 程序化 JSON 容错修复工具的单元测试。

覆盖三类典型失败样本（截断 / 夹带文字 / 控制字符），以及合法透传
和不可恢复场景。另含对 CoordinatorAgent.run 集成修复路径的验证。
"""

import json
import unittest

from app.tools.json_repair import repair_json


class RepairTruncatedStringTest(unittest.TestCase):
    """模型输出因 token 截断导致字符串/结构未闭合。"""

    def test_truncated_string_value(self):
        """引号未闭合 → 应自动补齐并解析成功。"""
        raw = '{"ques_count": 4, "questions": [{"question": "未闭合'
        result = repair_json(raw)
        self.assertIsNotNone(result, "截断字符串应可修复")
        parsed = json.loads(result)
        self.assertIsInstance(parsed, dict)

    def test_truncated_after_colon(self):
        """键值对的值缺失 → 截断到上一个完整对。"""
        raw = '{"ques_count": 2, "ques1": "问题一", "ques2":'
        result = repair_json(raw)
        self.assertIsNotNone(result, "截断到上一个完整键值对应可修复")
        parsed = json.loads(result)
        self.assertIn("ques_count", parsed)

    def test_truncated_missing_closing_braces(self):
        """嵌套结构的 } 和 ] 缺失。"""
        raw = '{"ques_count": 2, "data": [{"q": "x"}, {"q": "y"}'
        result = repair_json(raw)
        self.assertIsNotNone(result)
        parsed = json.loads(result)
        self.assertEqual(parsed["ques_count"], 2)

    def test_trailing_comma_before_close(self):
        """尾部多余逗号 → 清理后解析成功。"""
        raw = '{"ques_count": 2, "ques1": "a", "ques2": "b",}'
        result = repair_json(raw)
        self.assertIsNotNone(result)
        parsed = json.loads(result)
        self.assertEqual(parsed["ques_count"], 2)


class RepairSurroundingTextTest(unittest.TestCase):
    """模型在 JSON 前后夹带解释文字。"""

    def test_text_before_and_after_json(self):
        raw = '好的，这是拆题结果:\n{"ques_count":3, "background":"bg", "ques1":"q1", "ques2":"q2", "ques3":"q3"}\n如有疑问请告知'
        result = repair_json(raw)
        self.assertIsNotNone(result)
        parsed = json.loads(result)
        self.assertEqual(parsed["ques_count"], 3)

    def test_text_before_json_only(self):
        raw = '以下是 JSON 输出：\n{"ques_count": 1, "background": "b", "ques1": "q1"}'
        result = repair_json(raw)
        self.assertIsNotNone(result)
        parsed = json.loads(result)
        self.assertEqual(parsed["ques_count"], 1)

    def test_markdown_fenced_json(self):
        raw = '```json\n{"ques_count": 2, "background": "b", "ques1": "q1", "ques2": "q2"}\n```'
        result = repair_json(raw)
        self.assertIsNotNone(result)
        parsed = json.loads(result)
        self.assertEqual(parsed["ques_count"], 2)


class RepairControlCharsTest(unittest.TestCase):
    """输出包含控制字符或零宽字符。"""

    def test_null_bytes(self):
        raw = '{"ques_count": 1, "back\x00ground": "bg", "ques1": "q"}'
        result = repair_json(raw)
        self.assertIsNotNone(result)
        parsed = json.loads(result)
        self.assertIn("background", parsed)

    def test_zero_width_chars(self):
        raw = '{"ques_count": 1, "background": "bg\u200b\u200c\u200d", "ques1": "\ufeffq"}'
        result = repair_json(raw)
        self.assertIsNotNone(result)
        parsed = json.loads(result)
        self.assertEqual(parsed["ques1"], "q")

    def test_mixed_control_and_zero_width(self):
        raw = '\x01\x02{"ques_count"\x03: 1, "background": "b", "ques1": "q"}\x04'
        result = repair_json(raw)
        self.assertIsNotNone(result)
        json.loads(result)


class RepairValidPassthroughTest(unittest.TestCase):
    """合法 JSON 应原样通过，不被修改。"""

    def test_valid_json_passes_through(self):
        valid = '{"ques_count": 2, "background": "bg", "ques1": "q1", "ques2": "q2"}'
        result = repair_json(valid)
        self.assertIsNotNone(result)
        self.assertEqual(json.loads(result), json.loads(valid))

    def test_valid_nested_json(self):
        valid = '{"ques_count": 1, "background": "bg", "ques1": "q", "data": [1, 2, 3]}'
        result = repair_json(valid)
        self.assertIsNotNone(result)
        self.assertEqual(json.loads(result), json.loads(valid))


class RepairUnrecoverableTest(unittest.TestCase):
    """完全无 JSON 结构的输入应返回 None。"""

    def test_plain_text_returns_none(self):
        self.assertIsNone(repair_json("abc123"))

    def test_empty_returns_none(self):
        self.assertIsNone(repair_json(""))

    def test_whitespace_returns_none(self):
        self.assertIsNone(repair_json("   \n  "))

    def test_html_returns_none(self):
        self.assertIsNone(repair_json("<html><body>hello</body></html>"))


class CoordinatorRunRepairsTruncatedTest(unittest.IsolatedAsyncioTestCase):
    """CoordinatorAgent.run 经 repair_json 自动修复截断 JSON。"""

    async def test_truncated_json_repaired_without_retry(self):
        """模型返回截断 JSON → repair_json 救回 → 不消耗重试次数。"""
        from app.core.agents.coordinator_agent import CoordinatorAgent
        from app.core.llm.types import StandardResponse

        # 构造一个截断的但可修复的 JSON（尾部缺 }）
        truncated = json.dumps(
            {
                "title": "测试",
                "background": "背景信息",
                "ques_count": 2,
                "ques1": "问题一",
                "ques2": "问题二",
            },
            ensure_ascii=False,
        )
        # 去掉最后的 } 模拟截断
        truncated = truncated[:-1]

        class FakeLLM:
            def __init__(self):
                self.calls = 0

            async def chat(self, history=None, agent_name=None, **kwargs):
                self.calls += 1
                return StandardResponse(content=truncated)

        agent = CoordinatorAgent(
            task_id="task-repair-test",
            model=FakeLLM(),
            cancel_event=None,
            user_input_provider=None,
        )

        result = await agent.run("题目全文")

        # 修复成功，应只调用 1 次 LLM（不需要重试）
        self.assertEqual(agent.model.calls, 1)
        self.assertEqual(result.ques_count, 2)
        self.assertIn("background", result.questions)


class RepairEdgeCasesTest(unittest.TestCase):
    """额外边界场景。"""

    def test_truncated_in_key(self):
        """键名被截断。"""
        raw = '{"ques_count": 1, "back'
        result = repair_json(raw)
        # 可能截断到上一个完整对，或补齐键
        if result is not None:
            json.loads(result)  # 至少不应抛错

    def test_escaped_quotes_in_value(self):
        """值内含转义引号 → 不应误判为字符串结束。"""
        raw = r'{"ques_count": 1, "background": "含\"引号\"", "ques1": "q"}'
        result = repair_json(raw)
        self.assertIsNotNone(result)
        parsed = json.loads(result)
        self.assertIn("引号", parsed["background"])

    def test_multiple_trailing_commas(self):
        """多层嵌套的尾部逗号。"""
        raw = '{"a": [1, 2, 3,], "b": {"c": "d",},}'
        result = repair_json(raw)
        self.assertIsNotNone(result)
        json.loads(result)


if __name__ == "__main__":
    unittest.main()
