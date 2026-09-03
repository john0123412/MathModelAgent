"""Regression tests for the Writer prompt's evidence-backed asset contract."""

import unittest

from app.core.prompts.writer import get_writer_prompt
from app.schemas.enums import FormatOutPut


class TestWriterPrompt(unittest.TestCase):
    def test_asset_plan_precedes_prose_and_covers_each_formal_question(self):
        prompt = get_writer_prompt(FormatOutPut.Markdown)

        self.assertIn("先完成资产计划，再写任何论文正文", prompt)
        self.assertIn("图表资产计划", prompt)
        self.assertIn("每个正式问题必须至少有一幅来自实际结果输出的来源图", prompt)
        self.assertIn("一张可追溯到实际结果输出的结果表", prompt)

    def test_asset_contract_forbids_redundant_or_invented_assets(self):
        prompt = get_writer_prompt(FormatOutPut.Markdown)

        self.assertIn("重复同一信息的时间序列图", prompt)
        self.assertIn("不得虚构、预写或引用尚未生成的图片、表格、文件名、图题、数值或结论", prompt)
        self.assertIn("论文中出现的每幅图和每张表都必须配有实质性解释", prompt)

    def test_abstract_length_is_quality_target_not_official_rule(self):
        prompt = get_writer_prompt(FormatOutPut.Markdown)

        self.assertIn("摘要信息完整度和首屏可读性的内容质量目标", prompt)
        self.assertIn("不是 CUMCM 官方页数规则或硬性字数规定", prompt)


if __name__ == "__main__":
    unittest.main()
