"""Writer prompt contract tests."""

import unittest

from app.core.prompts.writer import get_writer_prompt
from app.schemas.enums import FormatOutPut


class TestWriterPromptContract(unittest.TestCase):
    def test_prompt_requires_numbered_reference_lines_and_no_empty_references(self):
        prompt = get_writer_prompt(FormatOutPut.Markdown)

        self.assertIn("参考文献不能为空", prompt)
        self.assertIn("[1] 作者. 题名[J]. 刊名, 年份.", prompt)
        self.assertIn("{[^1] 完整引用信息}", prompt)


if __name__ == "__main__":
    unittest.main()
