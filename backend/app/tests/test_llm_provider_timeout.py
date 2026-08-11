import asyncio
import unittest
from unittest import mock

from app.config.setting import settings
from app.core.llm.llm import LLM
from app.core.llm.providers.openai_chat import OpenAIChatProvider
from app.core.llm.providers.openai_responses import OpenAIResponsesProvider
from app.core.llm.types import StandardResponse, Usage
from app.utils.outbound_http import llm_http_client


class ProviderTimeoutTest(unittest.IsolatedAsyncioTestCase):
    def test_openai_responses_required_tool_choice_uses_literal(self):
        provider = OpenAIResponsesProvider()

        self.assertEqual(provider._convert_tool_choice("required"), "required")

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
                )

        self.assertEqual(
            client_cls.call_args.kwargs["timeout"],
            settings.LLM_REQUEST_TIMEOUT_SECONDS,
        )
        self.assertEqual(client_cls.call_args.kwargs["max_retries"], 0)

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


if __name__ == "__main__":
    unittest.main()
