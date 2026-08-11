"""建模手 Agent 模块，负责分析问题并制定建模方案。"""

import asyncio
from typing import Callable, get_args
from pydantic import ValidationError
from app.core.agents.agent import Agent
from app.core.llm.llm import LLM
from app.core.prompts import MODELER_PROMPT
from app.schemas.A2A import (
    AcceptanceMetric,
    CoordinatorToModeler,
    ExpectedArtifact,
    ModelPlan,
    ModelerToCoder,
)
from app.schemas.problem_contract import validate_modeler_plan
from app.utils.log_util import logger
import json
import re

# Keep one bounded format-correction turn after the initial response.  A
# second invalid response is terminal so a malformed ModelPlan cannot consume
# an unbounded provider budget before the Codex/manual recovery gate.
MAX_JSON_REPAIR_ATTEMPTS = 2

_ARTIFACT_KINDS = get_args(ExpectedArtifact.model_fields["kind"].annotation)
_METRIC_COMPARATORS = get_args(
    AcceptanceMetric.model_fields["comparator"].annotation
)
MODEL_PLAN_PROTOCOL_REMINDER = (
    '固定协议：schema_version 只能是 "mathmodel.model-plan.v1"；'
    "expected_artifacts[*].kind 只能是 "
    + ", ".join(map(str, _ARTIFACT_KINDS))
    + "；acceptance_metrics[*].comparator 只能是 "
    + ", ".join(map(str, _METRIC_COMPARATORS))
    + "；acceptance_metrics[*].target 必须是有限 JSON 数值，不得是字符串、数组、null、NaN 或无穷值。"
    "不要自造 report、model_description、check 等枚举值；说明性产物使用 other，"
    "需要核对等值时使用 eq；量纲/公式等定性检查使用 eq 1，并在 unit/description 解释 1 的含义。"
    "开放性判断题的指标必须结论中立：只验收模型比较完成、数据覆盖和结果可复算，"
    "不得用正向改善阈值、显著性阈值或存在标志预设结论。"
    "RMSE、R²、拟合误差、偏差、准确率、显著性和物理合理性等经验阈值必须在 description "
    "说明目标值来自题面/附件、数据统计或交叉验证、基线、文献或标准；仅写计算方法或物理常识无效。"
    "没有可靠依据时改用完成、覆盖、数值有限或可复算等结论中立指标，不得臆造数值门槛。"
)


def _format_validation_errors(exc: ValidationError) -> list[str]:
    """Return every schema error with a stable JSON field path."""
    issues: list[str] = []
    for error in exc.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    ):
        location = ".".join(str(part) for part in error["loc"])
        issues.append(f"ModelPlan schema 校验失败 [{location}]: {error['msg']}")
    return issues


def _escape_bare_quotes_inside_json_strings(json_str: str) -> str:
    """Escape LLM-produced inner quotes while preserving JSON delimiters.

    A quote closes a JSON string only when the following significant token is
    valid for the current object/array context.  Quotes embedded in prose such
    as ``得到"纯"双光束光谱`` are escaped instead.
    """
    result: list[str] = []
    containers: list[str] = []
    in_string = False
    escaped = False
    length = len(json_str)

    for index, char in enumerate(json_str):
        if not in_string:
            result.append(char)
            if char == '"':
                in_string = True
                escaped = False
            elif char in "{[":
                containers.append(char)
            elif char == "}" and containers and containers[-1] == "{":
                containers.pop()
            elif char == "]" and containers and containers[-1] == "[":
                containers.pop()
            continue

        if escaped:
            result.append(char)
            escaped = False
            continue
        if char == "\\":
            result.append(char)
            escaped = True
            continue
        if char != '"':
            result.append(char)
            continue

        next_index = index + 1
        while next_index < length and json_str[next_index].isspace():
            next_index += 1
        next_char = json_str[next_index] if next_index < length else ""
        closes_string = next_char in {"", ":", "}", "]"}
        if next_char == ",":
            following = next_index + 1
            while following < length and json_str[following].isspace():
                following += 1
            following_char = json_str[following] if following < length else ""
            if containers and containers[-1] == "{":
                closes_string = following_char in {'"', "}"}
            elif containers and containers[-1] == "[":
                closes_string = following_char in {
                    '"',
                    "{",
                    "[",
                    "-",
                    "t",
                    "f",
                    "n",
                    "]",
                } or following_char.isdigit()
            else:
                closes_string = True

        if closes_string:
            result.append(char)
            in_string = False
        else:
            result.append('\\"')

    return "".join(result)


def repair_json(json_str: str) -> dict | None:
    """尝试修复 LLM 输出的格式错误的 JSON。

    Args:
        json_str: 可能包含格式错误的 JSON 字符串。

    Returns:
        修复后的字典，无法修复时返回 None。
    """
    json_str = json_str.replace("```json", "").replace("```", "").strip()

    # Try direct parse first
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # Models occasionally quote a term inside an otherwise valid JSON string
    # without escaping it.  Repair only quotes that cannot be structural
    # delimiters in the current container context.
    try:
        return json.loads(_escape_bare_quotes_inside_json_strings(json_str))
    except json.JSONDecodeError:
        pass

    # Fix unescaped newlines and quotes inside string values
    try:
        fixed = re.sub(
            r'(?<=: ")(.*?)(?=",\s*\n\s*"|"\s*\n\s*})',
            lambda m: m.group(0).replace('"', '\\"'),
            json_str,
            flags=re.DOTALL,
        )
        return json.loads(fixed)
    except (json.JSONDecodeError, re.error):
        pass

    # Extract key-value pairs with regex as last resort
    try:
        pattern = r'"(\w+)"\s*:\s*"((?:[^"\\]|\\.|"(?!,\s*\n)|"(?!\s*\n\s*}))*)"'
        matches = re.findall(pattern, json_str, re.DOTALL)
        if matches:
            return {k: v.replace('\\"', '"') for k, v in matches}
    except re.error:
        pass

    return None


class ModelerAgent(Agent):
    """建模手 Agent，分析问题类型并制定建模方案、求解方法和可视化策略。"""
    def __init__(
        self,
        task_id: str,
        model: LLM,
        context_window: int = 128000,
        cancel_event: asyncio.Event | None = None,
        user_input_provider: Callable[[], list[str]] | None = None,
    ) -> None:
        super().__init__(
            task_id,
            model,
            context_window,
            cancel_event=cancel_event,
            user_input_provider=user_input_provider,
            guidance_target="modeler",
        )
        self.system_prompt = MODELER_PROMPT

    async def run(
        self,
        coordinator_to_modeler: CoordinatorToModeler,
        recovery_context: str = "",
    ) -> ModelerToCoder:  # type: ignore[reportIncompatibleMethodOverride]
        """根据协调者拆解的问题生成建模方案。

        Args:
            coordinator_to_modeler: 协调者传递的结构化问题信息。

        Returns:
            ModelerToCoder 对象，包含各问题的建模解决方案。
        """
        await self.append_chat_history(
            {"role": "system", "content": self.system_prompt}
        )
        await self.append_chat_history(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "questions": coordinator_to_modeler.questions,
                        "problem_contract": (
                            coordinator_to_modeler.problem_contract.model_dump()
                            if coordinator_to_modeler.problem_contract
                            else None
                        ),
                        **(
                            {
                                "recovery_context": (
                                    recovery_context[:2400]
                                    + "\n请据此重新审视方案；不得将失败或恢复过程写进论文。"
                                )
                            }
                            if recovery_context
                            else {}
                        ),
                    },
                    ensure_ascii=False,
                ),
            }
        )

        attempt = 0
        while True:
            response = await self._chat(
                history=self.chat_history,
                agent_name=self.__class__.__name__,
            )

            json_str = response.content
            if not json_str:
                raise ValueError("返回的 JSON 字符串为空，请检查输入内容。")

            payload = repair_json(json_str)
            issues: list[str] = []
            if payload:
                try:
                    model_plan = ModelPlan.model_validate(payload)
                    modeler_response = ModelerToCoder(model_plan=model_plan)
                    expected_question_keys = {
                        key
                        for key in coordinator_to_modeler.questions
                        if key.startswith("ques") and key != "ques_count"
                    }
                    issues.extend(model_plan.coverage_issues(expected_question_keys))
                    if coordinator_to_modeler.problem_contract:
                        validation = validate_modeler_plan(
                            coordinator_to_modeler.problem_contract,
                            modeler_response,
                            expected_question_keys=expected_question_keys,
                            questions=coordinator_to_modeler.questions,
                        )
                        issues.extend(validation.violations + validation.missing_requirements)
                    if not issues:
                        return modeler_response
                except ValidationError as exc:
                    issues.extend(_format_validation_errors(exc))
            else:
                issues.append("JSON 无法解析")

            attempt += 1
            logger.warning("ModelPlan 校验失败 (第{}次): {}", attempt, "; ".join(issues))
            if attempt >= MAX_JSON_REPAIR_ATTEMPTS:
                raise ValueError(
                    "ModelerAgent 连续返回不合格的 ModelPlan: " + "; ".join(issues)
                )
            retry_msg: dict = {"role": "assistant", "content": json_str}
            if response.reasoning_content:
                retry_msg["reasoning_content"] = response.reasoning_content
            await self.append_chat_history(retry_msg)
            await self.append_chat_history(
                {
                    "role": "user",
                    "content": (
                        "你的输出不是可执行的完整 ModelPlan。请只修正后重新输出完整 JSON，"
                        "保留全部 quesN，并补齐 inputs、method、constraints、expected_artifacts、"
                        "acceptance_metrics。\n"
                        + MODEL_PLAN_PROTOCOL_REMINDER
                        + "\n本轮全部校验错误：\n- "
                        + "\n- ".join(issues)
                    ),
                }
            )
