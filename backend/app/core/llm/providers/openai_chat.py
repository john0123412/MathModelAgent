"""OpenAI Chat Completions API Provider。"""

from openai import AsyncOpenAI
from app.config.setting import settings
from app.core.llm.providers.base import BaseProvider
from app.core.llm.types import StandardResponse, ToolCall, Usage
from app.utils.log_util import logger
from app.utils.outbound_http import llm_http_client


class OpenAIChatProvider(BaseProvider):
    """OpenAI Chat Completions API (/v1/chat/completions) 实现。"""

    @staticmethod
    def _convert_tool_choice(
        tool_choice: str, tools: list[dict] | None = None
    ) -> str | dict:
        """Map the internal ``any`` contract to Chat Completions.

        OpenAI Chat Completions has no literal ``any`` value.  When exactly one
        OpenAI-style function is exposed, DeepSeek Chat accepts the explicit
        function selector and treats it as a required call.  Multiple tools
        cannot be selected deterministically, so they retain the compatible
        ``auto`` fallback.
        """
        if tool_choice == "any":
            if tools and len(tools) == 1:
                tool = tools[0]
                function = tool.get("function")
                tool_name = (
                    function.get("name")
                    if isinstance(function, dict)
                    else tool.get("name")
                )
                if isinstance(tool_name, str) and tool_name:
                    return {"type": "function", "function": {"name": tool_name}}
                logger.warning(
                    "OpenAI Chat provider received one tool without a valid name; "
                    "falling back from internal any to auto."
                )
            elif tools and len(tools) > 1:
                logger.warning(
                    "OpenAI Chat provider cannot force internal any with {} tools; "
                    "falling back to auto.",
                    len(tools),
                )
            return "auto"
        return tool_choice

    async def call(
        self,
        messages: list[dict],
        model: str,
        api_key: str,
        base_url: str | None = None,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        thinking: bool = True,
        response_format: dict | None = None,
    ) -> StandardResponse:
        async with llm_http_client(settings.LLM_REQUEST_TIMEOUT_SECONDS) as http_client:
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
                max_retries=0,
                http_client=http_client,
            )

            kwargs: dict = {"model": model, "messages": messages}
            if max_tokens:
                kwargs["max_tokens"] = max_tokens
            if top_p is not None:
                kwargs["top_p"] = top_p
            if not thinking:
                kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            if response_format:
                kwargs["response_format"] = response_format
            if tools:
                kwargs["tools"] = tools
                if tool_choice:
                    kwargs["tool_choice"] = self._convert_tool_choice(tool_choice, tools)

            response = await client.chat.completions.create(**kwargs)

            choice = response.choices[0]
            message = choice.message

            tool_calls: list[ToolCall] = []
            for tc in message.tool_calls or []:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                ))

            completion_details = getattr(
                response.usage, "completion_tokens_details", None
            )
            usage = Usage(
                prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                completion_tokens=response.usage.completion_tokens if response.usage else 0,
                reasoning_tokens=(
                    getattr(completion_details, "reasoning_tokens", 0) or 0
                ),
            )

            reasoning = getattr(message, "reasoning_content", None)
            return StandardResponse(
                content=message.content,
                reasoning_content=reasoning,
                tool_calls=tool_calls,
                usage=usage,
                finish_reason=getattr(choice, "finish_reason", None),
            )
