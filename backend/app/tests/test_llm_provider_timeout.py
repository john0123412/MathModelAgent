import asyncio
import unittest
from unittest import mock

from app.config.setting import settings
from app.core.llm.llm import LLM
from app.core.llm.providers.openai_chat import OpenAIChatProvider
from app.core.llm.providers.openai_responses import OpenAIResponsesProvider


class ProviderTimeoutTest(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
