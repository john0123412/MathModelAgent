"""协调者 Agent 模块，负责识别用户意图并拆解数学建模问题。"""

import asyncio
from typing import Callable
from app.core.agents.agent import Agent
from app.core.llm.llm import LLM
from app.core.prompts import COORDINATOR_PROMPT
import json
import re
from app.utils.log_util import logger
from app.schemas.A2A import CoordinatorToModeler
from app.tools.json_repair import repair_json

MAX_JSON_REPAIR_ATTEMPTS = 5

# 正式问题键形如 ques1、ques2...（ques_count 不匹配该模式）
_QUES_KEY_RE = re.compile(r"ques(\d+)")


def _validate_questions_payload(payload: object) -> list[str]:
    """校验协调者输出的结构完整性，返回问题列表（空表示通过）。

    在拆题阶段就拦住结构缺陷：下游 `flows.get_writer_prompt` 直接取
    ``questions["background"]``，`UserOutput` 按 ``ques_count`` 生成章节
    序列并在拼装时索引各 ``quesN`` 章节——任何缺键或 ``ques_count`` 与
    实际 ``quesN`` 键不一致，都会在数小时的代码求解之后才在写作/导出
    阶段以 KeyError 暴露。

    这里刻意不加严 `app/schemas/A2A.py` 的 ``CoordinatorToModeler``：
    resume 路径会用旧 checkpoint 数据重建该对象，schema 加严会让旧任务
    无法续传；因此校验只针对新一轮 LLM 输出，在本模块内完成。

    Args:
        payload: ``json.loads`` 解析出的任意对象。

    Returns:
        中文描述的问题列表，每条具体到缺什么键/什么类型不对，便于直接
        回传给 LLM 修正；空列表表示通过校验。
    """
    if not isinstance(payload, dict):
        return [f"顶层必须是 JSON 对象（dict），实际是 {type(payload).__name__}"]

    issues: list[str] = []

    # ques_count：必须是 int（排除 bool）或可无损转 int 的字符串，且 >= 1
    ques_count: int | None = None
    if "ques_count" not in payload:
        issues.append("缺少 ques_count 键")
    else:
        raw_count = payload["ques_count"]
        if isinstance(raw_count, bool):
            issues.append("ques_count 必须是整数，实际是 bool")
        elif isinstance(raw_count, int):
            ques_count = raw_count
        elif isinstance(raw_count, str):
            try:
                ques_count = int(raw_count.strip())
            except ValueError:
                issues.append(
                    f"ques_count 必须是整数或纯数字字符串，实际值 {raw_count!r} 无法转换"
                )
        else:
            issues.append(
                f"ques_count 必须是整数，实际是 {type(raw_count).__name__}"
            )
        if ques_count is not None and ques_count < 1:
            issues.append(f"ques_count 必须 >= 1，实际是 {ques_count}")
            ques_count = None

    # background：写作阶段 get_writer_prompt 直接索引 questions["background"]
    if "background" not in payload:
        issues.append("缺少 background 键")
    elif not isinstance(payload["background"], str) or not payload["background"].strip():
        issues.append("background 必须是非空字符串")

    # ques_count 本身无效时无法确定 quesN 范围，先让 LLM 修正 ques_count
    if ques_count is not None:
        # 正向：ques1..ques{ques_count} 必须齐全且为非空字符串
        for i in range(1, ques_count + 1):
            key = f"ques{i}"
            if key not in payload:
                issues.append(
                    f"缺少问题 {key}"
                    f"（ques_count={ques_count} 要求 ques1..ques{ques_count} 全部存在）"
                )
                continue
            if not isinstance(payload[key], str) or not payload[key].strip():
                issues.append(f"{key} 必须是非空字符串")
        # 反向：多余的 quesN（N > ques_count）说明 ques_count 偏小，
        # 不拦截会在流程编排按 ques_count 生成序列时被静默丢题
        extra_keys = sorted(
            (
                key
                for key in payload
                if (match := _QUES_KEY_RE.fullmatch(key))
                and int(match.group(1)) > ques_count
            ),
            key=lambda item: int(item[4:]),
        )
        if extra_keys:
            issues.append(
                f"存在超出 ques_count={ques_count} 的多余问题键: "
                f"{', '.join(extra_keys)}；"
                "若确实有这些问题请调大 ques_count，否则删除多余键"
            )

    return issues


class CoordinatorAgent(Agent):
    """协调者 Agent，判断用户输入是否为数学建模问题并拆解为结构化问题列表。"""
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
            guidance_target="coordinator",
        )
        self.system_prompt = COORDINATOR_PROMPT

    async def run(self, ques_all: str) -> CoordinatorToModeler:  # type: ignore[reportIncompatibleMethodOverride]
        """解析用户输入的问题并格式化为结构化 JSON。

        Args:
            ques_all: 用户输入的完整题目信息。

        Returns:
            CoordinatorToModeler 对象，包含结构化问题和问题数量。
        """
        await self.append_chat_history(
            {"role": "system", "content": self.system_prompt}
        )
        await self.append_chat_history({"role": "user", "content": ques_all})
        attempt = 0
        while True:
            response = await self._chat(
                history=self.chat_history,
                agent_name=self.__class__.__name__,
            )
            raw_content = response.content or ""

            # 清理 JSON 字符串
            json_str = raw_content.replace("```json", "").replace("```", "").strip()
            json_str = re.sub(r"[\x00-\x1F\x7F]", "", json_str)

            issues: list[str] = []
            questions: dict | None = None
            if not json_str:
                issues.append("返回内容为空，未包含任何 JSON")
            else:
                try:
                    payload = json.loads(json_str)
                except json.JSONDecodeError as exc:
                    # 程序化修复：截断/夹带文字/控制字符等常见畸形
                    repaired = repair_json(raw_content)
                    if repaired is not None:
                        try:
                            payload = json.loads(repaired)
                        except json.JSONDecodeError:
                            payload = None
                        if payload is not None:
                            logger.info(
                                "repair_json 自动修复成功（原始错误: {}）",
                                exc,
                            )
                        else:
                            issues.append(
                                f"JSON 解析失败且自动修复未能恢复: {exc}"
                            )
                    else:
                        issues.append(
                            f"JSON 解析失败且无可修复的 JSON 结构: {exc}"
                        )
                    if payload is not None:
                        issues = _validate_questions_payload(payload)
                        if not issues:
                            questions = payload
                else:
                    issues = _validate_questions_payload(payload)
                    if not issues:
                        questions = payload

            if questions is not None:
                # 校验已保证 ques_count 是 int 或可无损转 int 的字符串；
                # 归一化为 int，避免下游 range()/序列生成拿到字符串
                ques_count = int(str(questions["ques_count"]).strip())
                questions["ques_count"] = ques_count
                logger.info(f"题目拆分已完成: ques_count={ques_count}")
                return CoordinatorToModeler(questions=questions, ques_count=ques_count)

            attempt += 1
            logger.warning(
                "拆题输出校验失败 (尝试 {}): {}", attempt, "; ".join(issues)
            )
            if attempt >= MAX_JSON_REPAIR_ATTEMPTS:
                raise ValueError(
                    f"CoordinatorAgent 连续 {attempt} 次返回无效拆题输出: "
                    + "; ".join(issues)
                )

            # 重试反馈：把上一轮原始输出以 assistant 身份放回历史，
            # 再追加 user 纠错消息。不能再堆叠 system 消息——部分
            # OpenAI 兼容网关拒绝 mid-history system role，且模型看不到
            # 自己上一轮输出就无法针对性修正
            retry_msg: dict = {"role": "assistant", "content": raw_content}
            if response.reasoning_content:
                retry_msg["reasoning_content"] = response.reasoning_content
            await self.append_chat_history(retry_msg)

            # 前 3 次保持逐项修正反馈；第 4 次起用极简降级 prompt
            if attempt < 4:
                correction_content = (
                    "你上一次的输出存在以下问题: "
                    + "; ".join(issues)
                    + "。注意无需复杂数学推演或冗长思考，请直接输出修正后的完整 JSON，"
                    "不要输出任何解释文字。"
                )
            else:
                correction_content = (
                    "输出格式多次错误。请直接输出最小合法 JSON，"
                    '格式为 {"title": "...", "background": "...", '
                    '"ques_count": N, "ques1": "...", ...}，'
                    "禁止冗长思考分析、禁止任何解释文字、禁止 Markdown 标记。"
                )

            await self.append_chat_history(
                {"role": "user", "content": correction_content}
            )
