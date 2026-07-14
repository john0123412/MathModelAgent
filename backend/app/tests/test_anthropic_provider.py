import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.core.functions import coder_tools_anthropic
from app.core.llm.providers.anthropic import AnthropicProvider


class AnthropicProviderToolConversionTest(unittest.TestCase):
    def test_convert_tools_keeps_native_anthropic_tool_schema(self):
        provider = AnthropicProvider()

        converted = provider._convert_tools(coder_tools_anthropic)

        self.assertEqual(len(converted), len(coder_tools_anthropic))
        self.assertEqual(
            [tool["name"] for tool in converted],
            ["execute_code", "record_execution_evidence"],
        )
        self.assertEqual(converted, coder_tools_anthropic)


class AnthropicProviderAuthenticationTest(unittest.IsolatedAsyncioTestCase):
    async def test_official_base_url_uses_api_key(self):
        client = self._fake_client()

        with patch("app.core.llm.providers.anthropic.AsyncAnthropic", return_value=client) as create_client:
            response = await AnthropicProvider().call(
                messages=[{"role": "user", "content": "Hi"}],
                model="claude-test",
                api_key="official-key",
                base_url="https://api.anthropic.com/v1",
                max_tokens=1,
            )

        self.assertEqual(response.content, "ok")
        create_client.assert_called_once()
        kwargs = create_client.call_args.kwargs
        self.assertEqual(kwargs.get("api_key"), "official-key")
        self.assertIsNone(kwargs.get("auth_token"))
        self.assertEqual(kwargs.get("max_retries"), 0)

    async def test_non_official_base_url_uses_auth_token(self):
        client = self._fake_client()

        with patch("app.core.llm.providers.anthropic.AsyncAnthropic", return_value=client) as create_client:
            response = await AnthropicProvider().call(
                messages=[{"role": "user", "content": "Hi"}],
                model="hy3-preview",
                api_key="gateway-token",
                base_url="https://example.test/v1/ai/cloudbase",
                max_tokens=1,
            )

        self.assertEqual(response.content, "ok")
        create_client.assert_called_once()
        kwargs = create_client.call_args.kwargs
        self.assertIsNone(kwargs.get("api_key"))
        self.assertEqual(kwargs.get("auth_token"), "gateway-token")
        self.assertEqual(kwargs.get("max_retries"), 0)

    def _fake_client(self):
        client = SimpleNamespace(
            messages=SimpleNamespace(
                create=AsyncMock(
                    return_value=SimpleNamespace(
                        content=[SimpleNamespace(type="text", text="ok")],
                        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                    )
                )
            )
        )
        return client


if __name__ == "__main__":
    unittest.main()
