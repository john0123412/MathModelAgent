"""通用工具函数单元测试。"""

import unittest

from app.utils.common_utils import split_footnotes


class TestCommonUtils(unittest.TestCase):
    """测试 common_utils 模块的核心函数。"""

    def test_split_footnotes(self):
        """测试脚注分离功能。

        split_footnotes 只剥离末尾的脚注定义块（"\\n[^1]: ..."），
        正文中的行内引用标记（如 "[^1]"）应保留 —— 这与 app/core/llm/llm.py
        中的实际用法一致：流式展示时先隐藏脚注定义原文，但仍保留引用标记。
        """
        text = "Example[^1]\n\n[^1]: Footnote content"
        main, notes = split_footnotes(text)
        self.assertEqual(main, "Example[^1]")
        self.assertEqual(notes, [("1", "Footnote content")])


if __name__ == "__main__":
    unittest.main()
