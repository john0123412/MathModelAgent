"""语义排版审查回归测试。"""

import unittest

from app.tools.semantic_layout_review import review_markdown


class TestSemanticLayoutReview(unittest.TestCase):
    def test_detects_misnested_main_sections_and_empty_references(self):
        markdown = (
            "# 一、问题重述\n\n正文。\n\n"
            "## 二、问题分析\n\n正文。\n\n"
            "# 三、模型假设\n\n"
            "### 假设1：参数确定\n\n正文。{}\n\n"
            "# 附录\n\n附录。"
        )

        report = review_markdown(markdown)

        self.assertEqual(report["status"], "WARN")
        self.assertFalse(report["blocking"])
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("main_section_level_mismatch", codes)
        self.assertIn("subsection_level_mismatch", codes)
        self.assertIn("empty_reference_marker", codes)
        self.assertIn("appendix_page_break_hint", codes)

    def test_accepts_consistent_heading_semantics_with_page_break(self):
        markdown = (
            "# 一、问题重述\n\n正文。\n\n"
            "# 二、问题分析\n\n"
            "## 2.1 问题一的分析\n\n正文。\n\n"
            "# 三、模型假设\n\n"
            "## 假设1：参数确定\n\n正文。\n\n"
            "# 五、模型的建立与求解\n\n"
            "### 5.1.1 问题的建立\n\n正文。\n\n"
            "<!-- pagebreak -->\n\n"
            "# 附录\n\n"
            "## 附录A 支撑材料文件列表\n\n列表。\n\n"
            "```python\n## 不是论文标题\nprint('{}')\n```\n"
        )

        report = review_markdown(markdown)

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["issue_count"], 0)
        self.assertTrue(all(item["kind"] != "other" for item in report["headings"]))

    def test_profile_pdf_appendix_break_avoids_markdown_only_warning(self):
        markdown = "# 一、问题重述\n\n正文。\n\n# 附录\n\n附录。"

        report = review_markdown(markdown, appendix_pagebreak_in_pdf=True)

        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["pdf_layout_policy"]["appendix_pagebreak_in_pdf"])

    def test_detects_filename_like_figure_caption(self):
        report = review_markdown("![fig1_feasible_region](fig1_feasible_region.png)")

        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("filename_like_figure_caption", codes)

    def test_accepts_descriptive_chinese_caption_that_matches_filename(self):
        report = review_markdown("![灵敏度分析利润随机器时间变化](灵敏度分析_利润随机器时间变化.png)")

        codes = {issue["code"] for issue in report["issues"]}
        self.assertNotIn("filename_like_figure_caption", codes)


if __name__ == "__main__":
    unittest.main()
