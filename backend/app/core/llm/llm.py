"""LLM 交互模块，封装大语言模型的调用、重试和消息发送。"""

from typing import Any
from app.utils.common_utils import transform_link, split_footnotes
from app.utils.log_util import logger
import asyncio
from app.schemas.response import (
    CoderMessage,
    WriterMessage,
    ModelerMessage,
    SystemMessage,
    CoordinatorMessage,
)
from app.services.redis_manager import redis_manager
from app.schemas.enums import AgentType
from app.config.setting import ApiType, settings
from app.core.llm.types import StandardResponse
from app.core.llm.providers.base import BaseProvider
from app.core.llm.providers.openai_chat import OpenAIChatProvider
from app.core.llm.providers.openai_responses import OpenAIResponsesProvider
from app.core.llm.providers.anthropic import AnthropicProvider
from app.services.token_usage import record_token_usage
from app.utils.security import validate_llm_base_url

# 兜底默认值；实际值优先取 settings.LLM_MAX_RETRIES，便于按 provider 稳定性调整
# （远程网关偶发连接抖动时，3 次约 6 秒的重试窗口经常不够跨过一次抖动）。
DEFAULT_LLM_MAX_RETRIES = 3
_TRANSIENT_BASE_URL_VALIDATION_ERROR = "LLM Base URL 主机无法解析"


class LLMConfigError(RuntimeError):
    """LLM 模型或 API Key 缺失时抛出，避免被 JSON 修复循环捕获。"""


def _record_token_usage_best_effort(
    task_id: str,
    agent_name: str,
    model: str | None,
    response: StandardResponse,
) -> None:
    """记录 token usage；统计失败不能影响 LLM 主调用。"""
    try:
        record_token_usage(task_id, agent_name, model, response.usage)
    except Exception as exc:
        logger.warning(
            "Token usage 统计写入失败，已跳过: "
            f"{type(exc).__name__}"
        )


class LLM:
    """大语言模型封装类，提供对话调用、重试和工具调用验证功能。"""

    def __init__(
        self,
        api_type: ApiType | None = None,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        task_id: str = "",
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ):
        self.api_type = api_type
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.chat_count = 0
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.task_id = task_id
        self.provider = self._create_provider(api_type)

    def _create_provider(self, api_type: ApiType | None) -> BaseProvider:
        """根据 api_type 创建对应的 Provider。"""
        match api_type:
            case ApiType.OPENAI_RESPONSES:
                return OpenAIResponsesProvider()
            case ApiType.ANTHROPIC:
                return AnthropicProvider()
            case _:
                # 默认使用 OpenAI Chat Completions（兼容未配置 api_type 的情况）
                return OpenAIChatProvider()

    def _validate_config(self, agent_name: str) -> None:
        """验证 LLM 配置是否完整。"""
        if not self.model or not str(self.model).strip():
            raise LLMConfigError(f"{agent_name} 未配置模型 ID，请设置对应的 *_MODEL")
        if not self.api_key or not str(self.api_key).strip():
            raise LLMConfigError(f"{agent_name} 未配置 API Key，请设置对应的 *_API_KEY")
        self.base_url = validate_llm_base_url(
            self.base_url,
            allow_private_hosts=settings.ALLOW_PRIVATE_LLM_BASE_URLS,
        )

    @staticmethod
    def _is_retryable_config_error(exc: Exception) -> bool:
        """Keep transient DNS failures inside the bounded LLM retry budget.

        The endpoint must still be resolved and checked for public addresses
        before *every* provider call.  Only a resolver outage is retryable;
        missing credentials, unsafe URLs, and all other validation errors fail
        immediately instead of being hidden by network retries.
        """
        return isinstance(exc, ValueError) and str(exc) == _TRANSIENT_BASE_URL_VALIDATION_ERROR

    async def chat(
        self,
        history: list | None = None,
        tools: list | None = None,
        tool_choice: str | None = None,
        max_retries: int | None = None,
        retry_delay: float = 1.0,
        top_p: float | None = None,
        thinking: bool = True,
        response_format: dict | None = None,
        agent_name: str = "SystemAgent",
        sub_title: str | None = None,
    ) -> StandardResponse:
        if max_retries is not None:
            max_attempts = max_retries
        else:
            max_attempts = getattr(
                settings, "LLM_MAX_RETRIES", DEFAULT_LLM_MAX_RETRIES
            ) or DEFAULT_LLM_MAX_RETRIES

        # 验证和修复工具调用完整性（仅对 OpenAI 格式的历史有效）
        if history:
            history = self._validate_and_fix_tool_calls(history)

        messages = history or []

        attempt = 0
        while True:
            # Roadmap C: budget check before each provider attempt (including retries) – must be inside loop
            if self.task_id:
                try:
                    from app.services.task_budget import check_budget_before_call

                    # Use work_dir from task_id; budget persists across resume
                    from app.utils.common_utils import get_work_dir as _get_wd

                    wd = _get_wd(self.task_id)
                    allowed, reason = check_budget_before_call(wd, self.task_id)
                    if not allowed:
                        raise RuntimeError(f"任务预算已耗尽，拒绝新调用: {reason}")
                except RuntimeError:
                    raise
                except Exception:
                    pass
            try:
                # DNS validation is intentionally repeated before every remote
                # call to retain the SSRF/DNS-rebinding protection.  Placing it
                # inside this loop lets a short resolver outage use the same
                # bounded retry policy as a transient provider connection error.
                self._validate_config(agent_name)
                # Providers also set their HTTP client timeout, but this outer bound
                # prevents SDK retry policies from extending a single LLM attempt.
                provider_kwargs = {
                    "messages": messages,
                    "model": self.model,
                    "api_key": self.api_key,
                    "base_url": self.base_url,
                    "tools": tools,
                    "tool_choice": tool_choice,
                    "max_tokens": self.max_tokens,
                    "top_p": top_p,
                    "thinking": thinking,
                }
                if self.reasoning_effort:
                    provider_kwargs["reasoning_effort"] = self.reasoning_effort
                if response_format is not None:
                    provider_kwargs["response_format"] = response_format
                response = await asyncio.wait_for(
                    self.provider.call(**provider_kwargs),
                    timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
                )
                logger.info(
                    "API 响应已接收: "
                    f"content_chars={len(response.content or '')}, "
                    f"reasoning_chars={len(response.reasoning_content or '')}, "
                    f"tool_calls={len(response.tool_calls)}, "
                    f"finish_reason={response.finish_reason or 'unknown'}, "
                    f"completion_tokens={response.usage.completion_tokens}, "
                    f"reasoning_tokens={response.usage.reasoning_tokens}"
                )
                self.chat_count += 1
                _record_token_usage_best_effort(
                    self.task_id,
                    agent_name,
                    self.model,
                    response,
                )
                await self.send_message(response, agent_name, sub_title)
                return response
            except Exception as e:
                # Roadmap C: record every real provider attempt, including failures, as unknown
                # Config errors are not provider attempts and should not be counted
                is_config_error = isinstance(e, LLMConfigError) or (isinstance(e, ValueError) and not self._is_retryable_config_error(e))
                if self.task_id and not is_config_error:
                    try:
                        from app.services.task_budget import record_provider_call as _record_budget_fail
                        from app.utils.common_utils import get_work_dir as _get_wd2

                        wd2 = _get_wd2(self.task_id)
                        _record_budget_fail(wd2, self.task_id, known_tokens=None, duration_seconds=None)
                    except Exception:
                        pass
                # 配置错误在每次调用前都会被检查；它不是网络瞬态错误，
                # 也不能落入 Coordinator/Modeler 的 JSON 修复循环。
                if isinstance(e, LLMConfigError):
                    raise
                attempt += 1
                logger.error(f"第{attempt}次重试: {type(e).__name__}: {e}")
                if isinstance(e, ValueError) and not self._is_retryable_config_error(e):
                    raise
                if attempt >= max_attempts:
                    raise
                await asyncio.sleep(retry_delay * min(attempt, 10))

    def _validate_and_fix_tool_calls(self, history: list) -> list:
        """验证并修复工具调用完整性。"""
        if not history:
            return history

        fixed_history = []
        i = 0

        while i < len(history):
            msg = history[i]

            if isinstance(msg, dict) and "tool_calls" in msg and msg["tool_calls"]:
                valid_tool_calls = []
                for tool_call in msg["tool_calls"]:
                    tool_call_id = tool_call.get("id")
                    if tool_call_id:
                        found_response = False
                        for j in range(i + 1, len(history)):
                            if (
                                history[j].get("role") == "tool"
                                and history[j].get("tool_call_id") == tool_call_id
                            ):
                                found_response = True
                                break
                        if found_response:
                            valid_tool_calls.append(tool_call)

                if valid_tool_calls:
                    fixed_msg = msg.copy()
                    fixed_msg["tool_calls"] = valid_tool_calls
                    fixed_history.append(fixed_msg)
                else:
                    cleaned_msg = {k: v for k, v in msg.items() if k != "tool_calls"}
                    if cleaned_msg.get("content"):
                        fixed_history.append(cleaned_msg)

            elif isinstance(msg, dict) and msg.get("role") == "tool":
                tool_call_id = msg.get("tool_call_id")
                found_call = False
                for j in range(len(fixed_history)):
                    if fixed_history[j].get("tool_calls") and any(
                        tc.get("id") == tool_call_id
                        for tc in fixed_history[j]["tool_calls"]
                    ):
                        found_call = True
                        break
                if found_call:
                    fixed_history.append(msg)
            else:
                fixed_history.append(msg)

            i += 1

        return fixed_history

    async def send_message(
        self,
        response: StandardResponse,
        agent_name: str,
        sub_title: str | None = None,
    ):
        """将 LLM 响应通过 Redis 发送给前端。"""
        content = response.content

        if content is None:
            return

        agent_msg: Any = None
        match agent_name:
            case AgentType.CODER:
                agent_msg = CoderMessage(content=content)
            case AgentType.WRITER:
                content, _ = split_footnotes(content)
                content = transform_link(self.task_id, content)
                agent_msg = WriterMessage(content=content, sub_title=sub_title)
            case AgentType.MODELER:
                agent_msg = ModelerMessage(content=content)
            case AgentType.SYSTEM:
                agent_msg = SystemMessage(content=content)
            case AgentType.COORDINATOR:
                agent_msg = CoordinatorMessage(content=content)
            case _:
                raise ValueError(f"不支持的agent类型: {agent_name}")

        await redis_manager.publish_message(self.task_id, agent_msg)


async def simple_chat(model: LLM, history: list) -> str:
    """使用 LLM 进行简单的单轮对话。"""
    model._validate_config("simple_chat")
    response = await asyncio.wait_for(
        model.provider.call(
            messages=history,
            model=model.model,  # type: ignore[arg-type]
            api_key=model.api_key,  # type: ignore[arg-type]
            base_url=model.base_url,
        ),
        timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
    )
    _record_token_usage_best_effort(
        model.task_id,
        "simple_chat",
        model.model,
        response,
    )
    return response.content or ""
