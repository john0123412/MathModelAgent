import unittest
from unittest import mock

from app.config.setting import settings
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


if __name__ == "__main__":
    unittest.main()
