import asyncio
import unittest
from unittest import mock
from types import SimpleNamespace

from app.config.setting import settings
from app.core.llm.llm import LLM, LLMConfigError
from app.core.llm.providers.openai_chat import OpenAIChatProvider
from app.core.llm.providers.openai_responses import OpenAIResponsesProvider
from app.core.llm.types import StandardResponse, Usage
from app.utils.outbound_http import llm_http_client


class ProviderTimeoutTest(unittest.IsolatedAsyncioTestCase):
    def test_openai_responses_required_tool_choice_uses_literal(self):
        provider = OpenAIResponsesProvider()

        self.assertEqual(provider._convert_tool_choice("required"), "required")
        self.assertEqual(provider._convert_tool_choice("any"), "required")

    def test_openai_chat_any_tool_choice_forces_the_single_tool(self):
        provider = OpenAIChatProvider()
        tools = [
            {
                "type": "function",
                "function": {"name": "execute_code", "parameters": {}},
            }
        ]

        self.assertEqual(
            provider._convert_tool_choice("any", tools),
            {"type": "function", "function": {"name": "execute_code"}},
        )

    def test_openai_chat_any_tool_choice_warns_and_falls_back_for_multiple_tools(self):
        provider = OpenAIChatProvider()
        tools = [
            {"type": "function", "function": {"name": "execute_code"}},
            {
                "type": "function",
                "function": {"name": "record_execution_evidence"},
            },
        ]

        with mock.patch("app.core.llm.providers.openai_chat.logger.warning") as warning:
            self.assertEqual(provider._convert_tool_choice("any", tools), "auto")

        warning.assert_called_once()

    async def test_openai_chat_provider_uses_configured_timeout(self):
        provider = OpenAIChatProvider()

        with mock.patch(
            "app.core.llm.providers.openai_chat.AsyncOpenAI"
        ) as client_cls:
            client = client_cls.return_value
            client.chat.completions.create.side_effect = RuntimeError("stop")

            with self.assertRaises(RuntimeError):
                await provider.call(
                    messages=[{"role": "user", "content": "hi"}],
                    model="test-model",
                    api_key="test-key",
                    base_url="https://example.test/v1",
                    thinking=False,
                    response_format={"type": "json_object"},
                )

        self.assertEqual(
            client_cls.call_args.kwargs["timeout"],
            settings.LLM_REQUEST_TIMEOUT_SECONDS,
        )
        self.assertEqual(client_cls.call_args.kwargs["max_retries"], 0)
        self.assertEqual(
            client.chat.completions.create.call_args.kwargs["extra_body"],
            {"thinking": {"type": "disabled"}},
        )
        self.assertEqual(
            client.chat.completions.create.call_args.kwargs["response_format"],
            {"type": "json_object"},
        )

    async def test_openai_chat_provider_preserves_completion_metadata(self):
        provider = OpenAIChatProvider()
        raw_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(
                        content=None,
                        reasoning_content="not logged by the provider",
                        tool_calls=[],
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=12,
                completion_tokens=8192,
                completion_tokens_details=SimpleNamespace(reasoning_tokens=8170),
            ),
        )

        with mock.patch(
            "app.core.llm.providers.openai_chat.AsyncOpenAI"
        ) as client_cls:
            client = client_cls.return_value
            client.chat.completions.create = mock.AsyncMock(
                return_value=raw_response
            )
            response = await provider.call(
                messages=[{"role": "user", "content": "return JSON"}],
                model="test-model",
                api_key="test-key",
                base_url="https://example.test/v1",
            )

        self.assertIsNone(response.content)
        self.assertEqual(response.finish_reason, "length")
        self.assertEqual(response.usage.completion_tokens, 8192)
        self.assertEqual(response.usage.reasoning_tokens, 8170)

    async def test_llm_chat_forwards_thinking_to_provider(self):
        class CapturingProvider:
            def __init__(self):
                self.kwargs = None

            async def call(self, **kwargs):
                self.kwargs = kwargs
                return StandardResponse(content="ok", usage=Usage())

        model = LLM(api_key="test-key", model="test-model")
        provider = CapturingProvider()
        model.provider = provider
        with (
            mock.patch.object(model, "_validate_config"),
            mock.patch.object(model, "send_message", new=mock.AsyncMock()),
        ):
            await model.chat(
                thinking=False,
                response_format={"type": "json_object"},
                max_retries=1,
            )

        self.assertFalse(provider.kwargs["thinking"])
        self.assertEqual(provider.kwargs["response_format"], {"type": "json_object"})

    async def test_openai_responses_provider_uses_configured_timeout(self):
        provider = OpenAIResponsesProvider()

        with mock.patch(
            "app.core.llm.providers.openai_responses.AsyncOpenAI"
        ) as client_cls:
            client = client_cls.return_value
            client.responses.create.side_effect = RuntimeError("stop")

            with self.assertRaises(RuntimeError):
                await provider.call(
                    messages=[{"role": "user", "content": "hi"}],
                    model="test-model",
                    api_key="test-key",
                    base_url="https://example.test/v1",
                )

        self.assertEqual(
            client_cls.call_args.kwargs["timeout"],
            settings.LLM_REQUEST_TIMEOUT_SECONDS,
        )
        self.assertEqual(client_cls.call_args.kwargs["max_retries"], 0)

    async def test_llm_chat_enforces_outer_timeout(self):
        class HungProvider:
            def __init__(self):
                self.cancelled = asyncio.Event()

            async def call(self, **_kwargs):
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled.set()
                    raise

        model = LLM(
            api_key="test-key",
            model="test-model",
            base_url="https://example.test/v1",
        )
        provider = HungProvider()
        model.provider = provider

        with mock.patch.object(model, "_validate_config"), mock.patch.object(
            settings, "LLM_REQUEST_TIMEOUT_SECONDS", 0.01
        ):
            with self.assertRaises(asyncio.TimeoutError):
                await model.chat(max_retries=1)

        self.assertTrue(provider.cancelled.is_set())

    async def test_llm_chat_retries_transient_dns_validation_failure(self):
        class SuccessfulProvider:
            def __init__(self):
                self.calls = 0

            async def call(self, **_kwargs):
                self.calls += 1
                return StandardResponse(content="ok", usage=Usage())

        model = LLM(api_key="test-key", model="test-model")
        provider = SuccessfulProvider()
        model.provider = provider
        with (
            mock.patch.object(
                model,
                "_validate_config",
                side_effect=[ValueError("LLM Base URL 主机无法解析"), None],
            ) as validate,
            mock.patch.object(model, "send_message", new=mock.AsyncMock()),
            mock.patch("app.core.llm.llm.asyncio.sleep", new=mock.AsyncMock()),
        ):
            response = await model.chat(max_retries=2, retry_delay=0)

        self.assertEqual(response.content, "ok")
        self.assertEqual(validate.call_count, 2)
        self.assertEqual(provider.calls, 1)

    async def test_llm_chat_does_not_retry_invalid_configuration(self):
        model = LLM(api_key="test-key", model="test-model")
        with mock.patch.object(
            model,
            "_validate_config",
            side_effect=ValueError("ModelerAgent 未配置 API Key"),
        ) as validate:
            with self.assertRaisesRegex(ValueError, "未配置 API Key"):
                await model.chat(max_retries=3, retry_delay=0)

        self.assertEqual(validate.call_count, 1)

    async def test_llm_chat_missing_api_key_raises_config_error_immediately(self):
        model = LLM(
            api_key="",
            model="test-model",
            base_url="https://example.test/v1",
        )
        model.provider.call = mock.AsyncMock()

        with self.assertRaisesRegex(LLMConfigError, "未配置 API Key"):
            await model.chat(
                max_retries=3,
                retry_delay=0,
                agent_name="ModelerAgent",
            )

        model.provider.call.assert_not_awaited()

    async def test_llm_http_client_only_uses_explicit_proxy_setting(self):
        with mock.patch("app.utils.outbound_http.httpx.AsyncClient") as client_cls:
            with mock.patch.object(
                settings, "LLM_OUTBOUND_PROXY", "http://proxy.example:8080"
            ):
                async with llm_http_client(12):
                    pass

        self.assertFalse(client_cls.call_args.kwargs["trust_env"])
        self.assertEqual(
            client_cls.call_args.kwargs["proxy"], "http://proxy.example:8080"
        )


class ThinkingDisableFallbackTest(unittest.IsolatedAsyncioTestCase):
    """GLM-5.3（tokenrouter 实测）不支持禁思考参数：400 时剥 extra_body 重试一次。"""

    @staticmethod
    def _bad_request(message: str):
        import httpx
        from openai import BadRequestError

        return BadRequestError(
            message,
            response=httpx.Response(
                400, request=httpx.Request("POST", "https://example.test/v1")
            ),
            body=None,
        )

    async def test_thinking_unsupported_retries_without_extra_body(self):
        provider = OpenAIChatProvider()
        ok_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content="ok", reasoning_content=None, tool_calls=[]
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=1,
                completion_tokens=1,
                completion_tokens_details=None,
            ),
        )

        with mock.patch(
            "app.core.llm.providers.openai_chat.AsyncOpenAI"
        ) as client_cls:
            client = client_cls.return_value
            client.chat.completions.create.side_effect = [
                self._bad_request("GLM-5.3 does not support disabling thinking"),
                asyncio.sleep(0, result=ok_response),
            ]
            response = await provider.call(
                messages=[{"role": "user", "content": "hi"}],
                model="z-ai/glm-5.3-free",
                api_key="k",
                base_url="https://example.test/v1",
                thinking=False,
            )

        self.assertEqual(response.content, "ok")
        first, second = client.chat.completions.create.call_args_list
        self.assertEqual(
            first.kwargs["extra_body"], {"thinking": {"type": "disabled"}}
        )
        self.assertNotIn("extra_body", second.kwargs)

    async def test_unrelated_bad_request_is_reraised(self):
        provider = OpenAIChatProvider()

        with mock.patch(
            "app.core.llm.providers.openai_chat.AsyncOpenAI"
        ) as client_cls:
            client = client_cls.return_value
            client.chat.completions.create.side_effect = self._bad_request(
                "invalid api key"
            )
            with self.assertRaises(Exception):
                await provider.call(
                    messages=[{"role": "user", "content": "hi"}],
                    model="m",
                    api_key="k",
                    base_url="https://example.test/v1",
                    thinking=False,
                )

        self.assertEqual(client.chat.completions.create.call_count, 1)


if __name__ == "__main__":
    unittest.main()
