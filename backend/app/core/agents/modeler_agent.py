"""建模手 Agent 模块，负责分析问题并制定建模方案。"""

import asyncio
from typing import Callable
from pydantic import ValidationError
from app.core.agents.agent import Agent
from app.core.llm.llm import LLM
from app.core.prompts import MODELER_PROMPT
from app.schemas.A2A import CoordinatorToModeler, ModelPlan, ModelerToCoder
from app.schemas.problem_contract import validate_modeler_plan
from app.utils.log_util import logger
import json
import re

MAX_JSON_REPAIR_ATTEMPTS = 3


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
        )
        self.system_prompt = MODELER_PROMPT

    async def run(self, coordinator_to_modeler: CoordinatorToModeler) -> ModelerToCoder:  # type: ignore[reportIncompatibleMethodOverride]
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
                    issues.append("ModelPlan schema 校验失败: " + exc.errors()[0]["msg"])
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
                        "acceptance_metrics：" + "; ".join(issues)
                    ),
                }
            )
