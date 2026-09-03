"""建模手 Agent 模块，负责分析问题并制定建模方案。"""

import asyncio
from copy import deepcopy
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
MODELER_JSON_RESPONSE_FORMAT = {"type": "json_object"}

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
    "【待求解/优化未知量严禁猜测精确等值】：对于待求解的最优目标值、决策变量、影子价格、灵敏度增量等未知结果，"
    "建模阶段严禁猜测具体数值设为 eq 目标（如猜测 shadow_price eq 10 或 profit_change eq 100 会导致代码手被门禁阻断）。"
    "这类未知待求解指标必须使用合理性范围约束（如 comparator='ge', target=0.0）、求解器状态（solver_status eq 1.0）"
    "或约束违反量（violation_max eq 0.0）；仅在题面原文给出了明确硬性数值目标（如压力维持在 150.0 MPa）时才使用精确等值 eq。"
    "开放性判断题的指标必须结论中立：只验收模型比较完成、数据覆盖和结果可复算，"
    "不得用正向改善阈值、显著性阈值或存在标志预设结论。"
    "RMSE、R²、拟合误差、偏差、准确率、显著性和物理合理性等经验阈值必须在 description "
    "按“阈值/目标值/判据/容差 + 依据/来自/基于 + 题目原文/数据统计/交叉验证/文献标准”"
    "说明目标值依据（基线归入文献标准）；"
    "仅写计算方法或物理常识无效。"
    "没有可靠依据时改用完成、覆盖、数值有限或可复算等结论中立指标，不得臆造数值门槛。"
    "输出前逐条核对 diagnostic_requirements：凡含步长/网格/step/grid（包括网格搜索、网格加密）的要求，"
    "acceptance_metrics 的 key、label 或 description 必须明确含步长/网格/step/grid；"
    "iteration_count、候选点评估次数或笼统收敛标志不能替代该对应指标。"
)

_EMPIRICAL_THRESHOLD_BASIS_ISSUE = "经验质量阈值缺少目标值依据"


def _only_empirical_threshold_basis_issues(issues: list[str]) -> bool:
    """Return whether every failure is a repairable metric-basis violation."""
    return bool(issues) and all(
        _EMPIRICAL_THRESHOLD_BASIS_ISSUE in issue for issue in issues
    )


def _apply_acceptance_metric_description_patch(
    original_payload: dict,
    patch_payload: dict,
) -> tuple[dict | None, list[str]]:
    """Apply a narrowly-scoped Modeler repair without replacing the ModelPlan.

    A full Plan is already structurally valid when this path is selected. The
    repair model therefore only needs to return descriptions for the rejected
    metrics, which prevents a second full serialization from dropping a valid
    question or top-level field.
    """
    updates = patch_payload.get("description_updates")
    if not isinstance(updates, list) or not updates:
        return None, ["定向依据修复必须返回非空 description_updates JSON 数组"]

    merged = deepcopy(original_payload)
    subtasks = merged.get("subtasks")
    if not isinstance(subtasks, dict):
        return None, ["原 ModelPlan 缺少可修复的 subtasks"]

    errors: list[str] = []
    seen_targets: set[tuple[str, str]] = set()
    for index, update in enumerate(updates):
        if not isinstance(update, dict):
            errors.append(f"description_updates[{index}] 必须是对象")
            continue

        subtask_key = update.get("subtask")
        metric_key = update.get("key")
        description = update.get("description")
        if not isinstance(subtask_key, str) or not isinstance(metric_key, str):
            errors.append(
                f"description_updates[{index}] 必须包含字符串 subtask 和 key"
            )
            continue
        if not isinstance(description, str) or not description.strip():
            errors.append(
                f"description_updates[{index}].description 必须是非空字符串"
            )
            continue

        target = (subtask_key, metric_key)
        if target in seen_targets:
            errors.append(
                f"description_updates[{index}] 重复更新 {subtask_key}.{metric_key}"
            )
            continue
        seen_targets.add(target)

        subtask = subtasks.get(subtask_key)
        metrics = subtask.get("acceptance_metrics") if isinstance(subtask, dict) else None
        if not isinstance(metrics, list):
            errors.append(f"未找到验收指标所属问题 {subtask_key}")
            continue
        metric = next(
            (
                candidate
                for candidate in metrics
                if isinstance(candidate, dict) and candidate.get("key") == metric_key
            ),
            None,
        )
        if metric is None:
            errors.append(f"未找到验收指标 {subtask_key}.{metric_key}")
            continue
        metric["description"] = description.strip()

    if errors:
        return None, errors
    return merged, []


def _model_plan_repair_prompt(issues: list[str]) -> str:
    """Build either a targeted description repair or a full-plan repair prompt."""
    issue_list = "\n- " + "\n- ".join(issues)
    if _only_empirical_threshold_basis_issues(issues):
        return (
            "你的 ModelPlan 结构和除以下项目外的内容已经通过校验。仅补写被拒验收指标的 "
            "acceptance_metrics[*].description 来源；不得修改原 Plan 的任何其他字段。"
            "不要重新输出整份 ModelPlan。只输出一个 JSON 对象（不要 Markdown），格式为："
            '{"description_updates":[{"subtask":"quesN","key":"metric_key","description":"目标值依据：题目原文/数据统计/交叉验证/文献标准……"}]}。'
            "每个 update 只能对应下列被拒指标，且 description 必须明确说明阈值或目标值来自 "
            "题目原文、数据统计、交叉验证或文献标准之一（基线归入文献标准）；"
            "只写计算方法或“符合常识”无效。"
            "\n被拒指标与错误："
            + issue_list
        )
    return (
        "你的输出不是可执行的完整 ModelPlan。请修正后重新输出完整 JSON，"
        "保留全部 quesN，并补齐 inputs、method、constraints、expected_artifacts、"
        "acceptance_metrics。\n"
        + MODEL_PLAN_PROTOCOL_REMINDER
        + "\n本轮全部校验错误："
        + issue_list
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


def _normalize_acceptance_metric_keys(payload: dict) -> None:
    """Normalize ModelPlan metric keys in place before strict schema validation.

    Models routinely emit human-readable keys such as ``prob_0.50`` or
    ``search_range_nA`` while the schema permits only lowercase slug-like
    identifiers.  Preserve the metric semantics, but rewrite its key so a
    structurally correct plan is not rejected solely for this presentation
    detail.  Missing or malformed subtasks remain the schema validator's job.
    """
    subtasks = payload.get("subtasks") if isinstance(payload, dict) else None
    if not isinstance(subtasks, dict):
        return

    for subtask in subtasks.values():
        if not isinstance(subtask, dict):
            continue
        metrics = subtask.get("acceptance_metrics")
        if not isinstance(metrics, list):
            continue
        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            raw_key = metric.get("key")
            if not isinstance(raw_key, str) or not raw_key:
                continue

            normalized = raw_key.strip().lower()
            normalized = re.sub(r"[^a-z0-9_]", "_", normalized)
            if normalized and not normalized[0].isalpha():
                normalized = "m_" + normalized
            normalized = re.sub(r"_+", "_", normalized).strip("_")
            metric["key"] = normalized or "metric"


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
        # Roadmap D: inject modeling guides per diagnostic profile (deterministic baseline, hard constraints, etc.)
        guides_text = ""
        try:
            from app.resources.modeling_guides import get_all_guides_manifest, load_guide

            manifest = get_all_guides_manifest()
            for g in manifest.get("guides", []):
                name = g.get("name", "")
                content = load_guide(name)
                if content:
                    guides_text += f"\n\n# 建模规范 [{name}]\n" + content[:1500]
        except Exception:
            guides_text = ""
        self.system_prompt = MODELER_PROMPT + guides_text

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
        pending_description_patch_base: dict | None = None
        while True:
            response = await self._chat(
                history=self.chat_history,
                # A ModelPlan is a one-shot structured payload with no tools.
                # DeepSeek V4 enables thinking by default; disable it here so a
                # bounded completion budget is reserved for the JSON contract.
                thinking=False,
                response_format=MODELER_JSON_RESPONSE_FORMAT,
                agent_name=self.__class__.__name__,
            )

            json_str = (response.content or "").strip()
            issues: list[str] = []
            repairable_payload: dict | None = None
            if not json_str:
                issues.append(
                    "返回内容为空 "
                    f"(finish_reason={response.finish_reason or 'unknown'}, "
                    f"reasoning_chars={len(response.reasoning_content or '')}, "
                    f"completion_tokens={response.usage.completion_tokens}, "
                    f"reasoning_tokens={response.usage.reasoning_tokens})"
                )
            else:
                payload = repair_json(json_str)
                if payload:
                    if pending_description_patch_base is not None:
                        if isinstance(payload, dict) and "description_updates" in payload:
                            payload, patch_issues = (
                                _apply_acceptance_metric_description_patch(
                                    pending_description_patch_base,
                                    payload,
                                )
                            )
                            issues.extend(patch_issues)
                        elif (
                            isinstance(payload, dict)
                            and "schema_version" in payload
                            and "subtasks" in payload
                        ):
                            # Be tolerant of a provider that ignores the narrow
                            # patch format, while retaining the full-plan repair
                            # fallback used for all other validation failures.
                            pass
                        else:
                            issues.append(
                                "定向依据修复必须返回 description_updates JSON 对象"
                            )
                            payload = None
                        pending_description_patch_base = None
                    if payload:
                        _normalize_acceptance_metric_keys(payload)
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
                                issues.extend(
                                    validation.violations + validation.missing_requirements
                                )
                            if not issues:
                                return modeler_response
                            repairable_payload = payload
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
            if (
                repairable_payload is not None
                and _only_empirical_threshold_basis_issues(issues)
            ):
                pending_description_patch_base = repairable_payload
            else:
                pending_description_patch_base = None
            retry_msg: dict = {"role": "assistant", "content": json_str}
            # Modeler never exposes tools, and its next turn is deliberately
            # non-thinking.  Do not replay a possibly incomplete CoT from an
            # invalid response into the repair turn.
            await self.append_chat_history(retry_msg)
            await self.append_chat_history(
                {
                    "role": "user",
                    "content": _model_plan_repair_prompt(issues),
                }
            )
