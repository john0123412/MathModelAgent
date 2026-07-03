import unittest

from app.core.functions import coder_tools_anthropic
from app.core.llm.providers.anthropic import AnthropicProvider


class AnthropicProviderToolConversionTest(unittest.TestCase):
    def test_convert_tools_keeps_native_anthropic_tool_schema(self):
        provider = AnthropicProvider()

        converted = provider._convert_tools(coder_tools_anthropic)

        self.assertEqual(len(converted), 1)
        self.assertEqual(converted[0]["name"], "execute_code")
        self.assertIn("input_schema", converted[0])


if __name__ == "__main__":
    unittest.main()
