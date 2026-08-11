"""论文导出后处理测试。"""

import hashlib
import json
import os
import tempfile
import unittest

from app.tools.paper_postprocessor import (
    append_code_appendix,
    build_claim_trace,
    build_preflight_report,
    ensure_figure_references,
    ensure_table_captions,
    escape_pipes_in_table_math_cells,
    normalize_bold_standalone_labels,
    normalize_cjk_inline_spacing,
    normalize_chinese_references,
    normalize_deterministic_eda_terms,
    normalize_deterministic_random_simulation_code_terms,
    normalize_english_transitions,
    normalize_extra_problem_labels,
    normalize_image_captions,
    normalize_heading_blank_lines,
    normalize_keywords,
    normalize_markdown_headings,
    normalize_submission_wording,
    normalize_strong_claim_wording,
    prepare_paper_markdown,
    remove_deterministic_random_simulation,
    remove_empty_reference_section,
    remove_orphan_definition_reference_lines,
    shorten_long_code_separator_lines,
    strip_unmatched_inline_references,
)
from app.tools.semantic_layout_review import normalize_markdown_semantics


def _canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class TestNormalizeChineseReferences(unittest.TestCase):
    """验证参考文献被整理为中文论文常见的独立编号行。"""

    def test_footnote_references_become_numbered_lines(self):
        markdown = (
            "# 标题\n\n"
            "正文引用一[^1]，正文引用二[^2]。\n\n"
            "## 参考文献\n\n"
            "[^1]: 贾俊平. 统计学[M]. 北京: 中国人民大学出版社, 2018.\n"
            "[^2]: Spearman C. The proof and measurement of association[J]. American Journal of Psychology, 1904.\n"
        )

        normalized = normalize_chinese_references(markdown)

        self.assertIn("正文引用一[1]，正文引用二[2]。", normalized)
        self.assertIn("## 参考文献\n\n[1] 贾俊平. 统计学[M]. 北京: 中国人民大学出版社, 2018.", normalized)
        self.assertIn(
            "\n\n[2] Spearman C. The proof and measurement of association[J]. American Journal of Psychology, 1904.",
            normalized,
        )
        self.assertNotIn("[^1]:", normalized)

    def test_cjk_inline_spacing_is_normalized_without_touching_code(self):
        markdown = "正文含有 凸轮 轮廓 曲线。\n\n```python\nlabel = '凸轮 轮廓'\n```\n"

        normalized = normalize_cjk_inline_spacing(markdown)

        self.assertIn("凸轮轮廓曲线", normalized)
        self.assertIn("label = '凸轮 轮廓'", normalized)

    def test_existing_numbered_references_are_renumbered_contiguously(self):
        markdown = (
            "正文[3]。\n\n"
            "# 八、参考文献\n\n"
            "[3] 第三条文献。\n"
            "[8] 第八条文献跨行\n"
            "继续说明。\n"
        )

        normalized = normalize_chinese_references(markdown)

        self.assertIn("正文[1]。", normalized)
        self.assertIn("## 参考文献\n\n[1] 第三条文献。", normalized)
        self.assertIn("\n[2] 第八条文献跨行 继续说明。", normalized)
        self.assertNotIn("[8]", normalized)

    def test_reference_normalization_preserves_existing_appendix(self):
        markdown = (
            "# 标题\n\n"
            "正文[1]。\n\n"
            "## 参考文献\n\n"
            "[1] 文献。\n\n"
            "# 附录\n\n"
            "## 附录B 源程序代码\n\n"
            "```python\n"
            "print('ok')\n"
            "```\n"
        )

        normalized = normalize_chinese_references(markdown)

        self.assertIn("## 参考文献\n\n[1] 文献。", normalized)
        self.assertIn("# 附录\n\n## 附录B 源程序代码", normalized)
        self.assertIn("```python\nprint('ok')\n```", normalized)
        self.assertNotIn("[1] 文献。 # 附录", normalized)

    def test_keywords_heading_is_normalized_to_single_line(self):
        markdown = "## 摘要\n\n正文。\n\n## 关键词\n\n线性规划 敏感性分析 生产优化 资源分配\n\n# 一、问题重述"

        normalized = normalize_keywords(markdown)

        self.assertIn("关键词：线性规划；敏感性分析；生产优化；资源分配", normalized)
        self.assertNotIn("## 关键词\n\n线性规划", normalized)

    def test_bold_abstract_and_keywords_headings_are_normalized(self):
        markdown = (
            "**摘要**\n\n这是摘要正文。\n\n"
            "**关键词**\n线性规划；敏感性分析；生产优化；资源分配\n\n"
            "# 一、问题重述"
        )

        normalized = normalize_keywords(normalize_markdown_headings(markdown))

        self.assertIn("## 摘要\n这是摘要正文。", normalized)
        self.assertIn("关键词：线性规划；敏感性分析；生产优化；资源分配", normalized)

    def test_bare_abstract_heading_is_normalized(self):
        markdown = (
            "标题：基于线性规划的生产优化研究\n\n"
            "摘要\n\n"
            "本文围绕生产优化问题建立线性规划模型，结合资源约束、利润目标和敏感性分析给出可复核方案。"
            "模型通过目标函数和约束条件刻画生产过程，并比较资源变化前后的最优利润。"
    "结果表明，机器时间变化会带来可解释的边际收益，人工资源仍可能构成关键瓶颈，并可通过对偶价格说明其经济含义。\n\n"
            "关键词：线性规划；敏感性分析；生产优化；资源约束\n\n"
            "# 一、问题重述"
        )

        normalized = normalize_markdown_headings(markdown)
        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=normalized,
            code_sources=[],
        )

        self.assertIn("## 摘要", normalized)
        self.assertTrue(report["checks"]["abstract"]["passed"])

    def test_heading_blank_lines_are_repaired_without_touching_code(self):
        markdown = (
            "上一段正文。\n"
            "### 6.1.2 被 Pandoc 误作正文的标题\n"
            "标题后的正文。\n\n"
            "```python\n"
            "literal = '### 代码中的标题'\n"
            "```\n"
        )

        normalized, inserted = normalize_heading_blank_lines(markdown)

        self.assertEqual(inserted, 1)
        self.assertIn("上一段正文。\n\n### 6.1.2", normalized)
        self.assertIn("literal = '### 代码中的标题'", normalized)

    def test_semantic_normalizer_repairs_only_visible_cumcm_layout_slips(self):
        markdown = (
            "## 二、问题分析\n\n"
            "资源配置需要实现利润最大化{}。\n\n"
            "公式 $A={} $ 必须保留。\n\n"
            "```python\n"
            "heading = '## 二、问题分析'\n"
            "marker = '{}'\n"
            "```\n"
        )

        updated, fixups = normalize_markdown_semantics(markdown)

        self.assertIn("# 二、问题分析", updated)
        self.assertIn("资源配置需要实现利润最大化。", updated)
        self.assertIn("$A={} $", updated)
        self.assertIn("heading = '## 二、问题分析'", updated)
        self.assertIn("marker = '{}'", updated)
        self.assertEqual(fixups["normalised_main_section_headings"], 1)
        self.assertEqual(fixups["removed_empty_reference_markers"], 1)

    def test_bold_inline_keywords_are_detected(self):
        markdown = (
            "## 摘要\n\n这是摘要正文。\n\n"
            "**关键词**：线性规划；敏感性分析；生产优化；资源分配\n"
        )

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=[],
        )

        self.assertTrue(report["checks"]["keywords"]["passed"])

    def test_unmatched_inline_numeric_references_are_removed(self):
        markdown = (
            "正文引用已有文献[1]，但这里误写了缺失文献[2]和[3]。\n\n"
            "## 参考文献\n\n[1] 文献。"
        )

        updated, removed = strip_unmatched_inline_references(markdown)
        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=updated,
            code_sources=[],
        )

        self.assertEqual(removed, [2, 3])
        self.assertIn("已有文献[1]", updated)
        self.assertNotIn("[2]", updated)
        self.assertNotIn("[3]", updated)
        self.assertTrue(report["checks"]["references"]["passed"])
        self.assertEqual(report["checks"]["references"]["missing_inline"], [])

    def test_inline_numeric_references_are_removed_when_reference_section_empty(self):
        markdown = "正文错误引用了空参考文献[1]。\n\n## 参考文献"

        updated, removed = strip_unmatched_inline_references(markdown)
        updated, removed_empty_section = remove_empty_reference_section(updated)
        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=updated,
            code_sources=[],
        )

        self.assertEqual(removed, [1])
        self.assertTrue(removed_empty_section)
        self.assertNotIn("[1]", updated)
        self.assertNotIn("## 参考文献", updated)
        self.assertTrue(report["checks"]["references"]["passed"])
        self.assertEqual(report["checks"]["references"]["inline"], [])

    def test_preflight_fails_unmatched_inline_numeric_references(self):
        markdown = (
            "正文引用已有文献[1]，但这里误写了缺失文献[2]。\n\n"
            "## 参考文献\n\n[1] 文献。"
        )

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=[],
        )

        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"]["references"]["passed"])
        self.assertEqual(report["checks"]["references"]["missing_inline"], [2])

    def test_table_captions_are_inserted_before_markdown_tables(self):
        markdown = (
            "# 四、符号说明\n\n"
            "| 符号 | 含义 |\n"
            "| --- | --- |\n"
            "| x | 产量 |\n\n"
            "## 附录A 支撑材料文件列表\n\n"
            "| 文件名 | 类型 |\n"
            "| --- | --- |\n"
            "| result.csv | 数据/结果文件 |\n"
        )

        updated = ensure_table_captions(markdown)
        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=updated,
            code_sources=[],
        )

        self.assertIn("表1 符号说明", updated)
        self.assertIn("表2 支撑材料文件列表", updated)
        self.assertTrue(report["checks"]["tables"]["passed"])
        self.assertEqual(report["checks"]["tables"]["uncaptioned_tables"], [])

    def test_preflight_flags_uncaptioned_markdown_tables(self):
        markdown = (
            "| 符号 | 含义 |\n"
            "| --- | --- |\n"
            "| x | 产量 |\n"
        )

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=[],
        )

        self.assertFalse(report["checks"]["tables"]["passed"])
        self.assertEqual(report["checks"]["tables"]["uncaptioned_tables"][0]["table_index"], 1)

    def test_invalid_pipe_table_structure_is_a_hard_failure(self):
        markdown = (
            "表1 非法表格\n\n"
            "| A | B |\n"
            "| --- | --- |\n"
            "| 1 | 2 | 3 |\n"
        )

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=[],
        )

        self.assertEqual(report["status"], "FAIL")
        structure = report["checks"]["markdown_structure"]
        self.assertFalse(structure["passed"])
        self.assertTrue(
            any(item["type"] == "invalid_markdown_table" for item in structure["issues"])
        )

    def test_pipe_table_inside_fenced_code_is_not_validated_as_paper_table(self):
        markdown = "```text\n| not | a | table |\n```\n"

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=[],
        )

        self.assertTrue(report["checks"]["markdown_structure"]["passed"])

    def test_failed_attempt_images_are_excluded_from_generated_assets(self):
        with tempfile.TemporaryDirectory() as work_dir:
            failed_dir = os.path.join(work_dir, "failed_attempts")
            os.makedirs(failed_dir)
            with open(os.path.join(failed_dir, "old.png"), "wb") as handle:
                handle.write(b"old")

            report = build_preflight_report(
                work_dir=work_dir,
                markdown="# 摘要\n\n正文。",
                code_sources=[],
            )

        self.assertEqual(report["checks"]["images"]["unused_generated"], [])
        self.assertEqual(
            report["source_sha256"],
            hashlib.sha256("# 摘要\n\n正文。".encode("utf-8")).hexdigest(),
        )

    def test_body_figure_without_numbered_prose_reference_is_conditional(self):
        markdown = "正文分析。\n\n![灵敏度分析](result.png)\n"

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=[],
        )

        check = report["checks"]["figure_references"]
        self.assertFalse(check["passed"])
        self.assertEqual(check["severity"], "conditional")
        self.assertEqual(check["missing_references"][0]["figure_number"], 1)

    def test_numbered_figure_reference_closes_body_figure_loop(self):
        markdown = "灵敏度变化如图1所示。\n\n![灵敏度分析](result.png)\n"

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=[],
        )

        self.assertTrue(report["checks"]["figure_references"]["passed"])

    def test_missing_body_figure_reference_is_inserted_idempotently(self):
        markdown = "正文分析。\n\n![灵敏度分析](result.png)\n\n# 附录\n\n![附录图](appendix.png)\n"

        normalized, inserted = ensure_figure_references(markdown)
        repeated, repeated_inserted = ensure_figure_references(normalized)

        self.assertEqual(inserted, 1)
        self.assertIn("如图1所示，灵敏度分析展示了本节相关计算结果。", normalized)
        self.assertEqual(repeated, normalized)
        self.assertEqual(repeated_inserted, 0)

    def test_fractional_piece_wording_in_continuous_model_is_conditional(self):
        markdown = (
            "本文采用连续型线性规划并允许小数解。\n\n"
            "最优方案为产品A 46.67件、产品B 16.67件。\n"
        )

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=[],
        )

        check = report["checks"]["continuous_quantity_wording"]
        self.assertFalse(check["passed"])
        self.assertEqual(check["severity"], "conditional")
        self.assertEqual(len(check["ambiguous_units"]), 2)

    def test_continuous_production_equivalent_wording_is_accepted(self):
        markdown = (
            "本文采用连续型线性规划并允许小数解。\n\n"
            "最优方案为产品A 46.67个连续生产当量、产品B 16.67个连续生产当量。\n"
        )

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=[],
        )

        self.assertTrue(report["checks"]["continuous_quantity_wording"]["passed"])

    def test_fractional_piece_wording_in_code_appendix_is_ignored(self):
        markdown = (
            "本文采用连续型线性规划并允许小数解。\n\n"
            "# 附录\n\n```python\nprint('46.67件')\n```\n"
        )

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=[],
        )

        self.assertTrue(report["checks"]["continuous_quantity_wording"]["passed"])

    def test_extra_problem_labels_are_normalized_outside_code_and_paths(self):
        markdown = (
            "本文只列出（1）和（2）两个问题。\n\n"
            "![问题3_参数利润敏感性](问题3_参数利润敏感性.png)\n\n"
            "| 文件名 | 类型 |\n"
            "| --- | --- |\n"
            "| 问题3_敏感性汇总.csv | 数据/结果文件 |\n\n"
            "```python\n"
            "fig.savefig('问题3_参数利润敏感性.png')\n"
            "```\n"
        )

        updated, replacements = normalize_extra_problem_labels(markdown)

        self.assertEqual(replacements, 2)
        self.assertIn("![灵敏度分析_参数利润敏感性](问题3_参数利润敏感性.png)", updated)
        self.assertIn("| 灵敏度分析_敏感性汇总.csv | 数据/结果文件 |", updated)
        self.assertIn("fig.savefig('问题3_参数利润敏感性.png')", updated)

    def test_extra_problem_paragraphs_use_explicit_declared_problem_count(self):
        markdown = (
            "# 一、问题重述\n\n"
            "**问题一：最优生产方案确定**\n\n"
            "确定最优生产方案。\n\n"
            "**问题二：资源变动敏感性分析**\n\n"
            "分析机器时间增加10小时的影响。\n\n"
            "**问题三：参数影响深入探究**\n\n"
            "扩展分析不同参数变化对生产系统的影响。\n\n"
            "![问题3_参数利润敏感性](问题3_参数利润敏感性.png)\n"
        )

        updated, replacements = normalize_extra_problem_labels(
            markdown,
            declared_count=2,
        )

        self.assertEqual(replacements, 2)
        self.assertIn("**灵敏度分析：参数影响深入探究**", updated)
        self.assertNotIn("问题三：参数影响深入探究", updated)
        self.assertIn("![灵敏度分析_参数利润敏感性](问题3_参数利润敏感性.png)", updated)

    def test_image_captions_are_cleaned_without_touching_paths_or_code(self):
        markdown = (
            "![灵敏度分析_机器工时对最优利润影响.png](灵敏度分析_机器工时对最优利润影响.png)\n"
            "![](figures/model-output-chart.png)\n"
            "```python\n"
            "print('![raw_name.png](raw_name.png)')\n"
            "```\n"
        )

        updated = normalize_image_captions(markdown)

        self.assertIn(
            "![灵敏度分析 机器工时对最优利润影响](灵敏度分析_机器工时对最优利润影响.png)",
            updated,
        )
        self.assertIn("![model output chart](figures/model-output-chart.png)", updated)
        self.assertIn("print('![raw_name.png](raw_name.png)')", updated)

    def test_question_plot_image_caption_becomes_descriptive(self):
        updated = normalize_image_captions(
            "![ques1 plot](ques1_plot.png)\n![Ques2 chart](ques2_plot.png)\n"
        )

        self.assertIn(
            "![问题1的优化结果图](ques1_plot.png)", updated
        )
        self.assertIn(
            "![问题2的优化结果图](ques2_plot.png)", updated
        )

    def test_english_transitions_are_normalized_outside_code(self):
        markdown = (
            "Overall，模型结果稳定。However，这一结论仍需复核。"
            " In addition，该图可解释。\n\n"
            "```python\n"
            "print('Overall should stay')\n"
            "```\n"
        )

        updated = normalize_english_transitions(markdown)

        self.assertIn("总体来看，模型结果稳定。不过，这一结论仍需复核。此外，该图可解释。", updated)
        self.assertIn("print('Overall should stay')", updated)

    def test_deterministic_eda_terms_are_normalized_outside_code(self):
        markdown = (
            "## 4.2 描述性统计\n\n"
            "本优化问题的参数集由题目给定的确定性常量构成，不涉及随机样本数据。"
            "针对产品生产参数进行描述性统计分析。\n\n"
            "```python\n"
            "print('描述性统计')\n"
            "```\n"
        )

        updated, replacements = normalize_deterministic_eda_terms(markdown)

        self.assertEqual(replacements, 2)
        self.assertIn("## 4.2 参数核验", updated)
        self.assertIn("参数核验分析", updated)
        self.assertIn("print('描述性统计')", updated)

    def test_deterministic_random_simulation_is_removed_outside_code(self):
        markdown = (
            "本题为确定性线性规划问题。\n\n"
            "蒙特卡洛模拟进一步评估了模型在随机扰动下的鲁棒性。\n\n"
            "![灵敏度分析 Monte Carlo模拟](灵敏度分析_Monte_Carlo模拟.png)\n\n"
            "| 文件名 | 类型 |\n"
            "| --- | --- |\n"
            "| 灵敏度分析_Monte_Carlo模拟.png | 图片文件 |\n"
            "| 灵敏度分析_约束紧度.png | 图片文件 |\n\n"
            "```python\n"
            "print('Monte Carlo模拟代码作为源程序保留')\n"
            "```\n"
        )

        updated, removed = remove_deterministic_random_simulation(markdown)

        self.assertEqual(removed, 3)
        self.assertNotIn("蒙特卡洛模拟进一步评估", updated)
        self.assertNotIn("![灵敏度分析 Monte Carlo模拟]", updated)
        self.assertNotIn("| 灵敏度分析_Monte_Carlo模拟.png |", updated)
        self.assertIn("| 灵敏度分析_约束紧度.png | 图片文件 |", updated)
        self.assertIn("print('Monte Carlo模拟代码作为源程序保留')", updated)

    def test_deterministic_random_simulation_terms_are_relabelled_inside_code(self):
        markdown = (
            "本题为确定性线性规划问题。\n\n"
            "```python\n"
            "print('Monte Carlo模拟')\n"
            "print('利润系数±5%随机扰动')\n"
            "plt.savefig('灵敏度分析_Monte_Carlo模拟.png')\n"
            "```\n"
        )

        updated, replacements = normalize_deterministic_random_simulation_code_terms(
            markdown
        )

        self.assertEqual(replacements, 3)
        self.assertNotRegex(updated, r"Monte[\s_]*Carlo|随机扰动")
        self.assertIn("参数扰动扩展", updated)
        self.assertIn("参数扰动", updated)

    def test_strong_claim_wording_is_downgraded_outside_code(self):
        markdown = (
            "模型验证了最优解的唯一性，并可精确预测利润变化。\n\n"
            "```python\n"
            "print('验证了最优解的唯一性')\n"
            "```\n"
        )

        updated, replacements = normalize_strong_claim_wording(markdown)

        self.assertGreaterEqual(replacements, 2)
        self.assertIn("模型表明最优解的可复核性，并可估计利润变化。", updated)
        self.assertIn("print('验证了最优解的唯一性')", updated)

    def test_submission_wording_is_normalized_in_visible_text_and_appendix_code(self):
        markdown = (
            "对偶理论可快速估算资源边际价值。\n\n"
            "```python\n"
            "# 题目给定的参数（根据用户描述推断）\n"
            "profit_per_A = 40  # 假设，待验证\n"
            "print('用户边界估算验证与纠正')\n"
            "```\n"
        )

        updated, replacements = normalize_submission_wording(markdown)

        self.assertGreaterEqual(replacements, 4)
        self.assertIn("快速测算资源边际价值", updated)
        self.assertNotRegex(updated, r"用户|推断|估算|待验证")
        self.assertIn("根据题目描述核定", updated)
        self.assertIn("需核验", updated)

    def test_bold_standalone_labels_become_headings_outside_code(self):
        markdown = (
            "**假设1：数据有效性假设**\n"
            "题目参数均为确定常数。\n\n"
            "```python\n"
            "print('**假设1：数据有效性假设**')\n"
            "```\n"
        )

        updated, replacements = normalize_bold_standalone_labels(markdown)

        self.assertEqual(replacements, 1)
        self.assertIn("### 假设1：数据有效性假设\n题目参数均为确定常数。", updated)
        self.assertIn("print('**假设1：数据有效性假设**')", updated)

    def test_orphan_definition_reference_lines_are_removed_outside_code(self):
        markdown = (
            "生产资源分配优化是制造业管理中的经典问题。\n\n"
            ": Author A. Journal Name, 2022. DOI: 10.1234/example.\n\n"
            "```python\n"
            "print(': Author A. Journal Name, 2022. DOI: 10.1234/example.')\n"
            "```\n"
        )

        updated, removed = remove_orphan_definition_reference_lines(markdown)

        self.assertEqual(removed, 1)
        self.assertNotIn(": Author A. Journal Name, 2022. DOI", updated.split("```", 1)[0])
        self.assertIn("print(': Author A. Journal Name, 2022. DOI", updated)


class TestAppendCodeAppendix(unittest.TestCase):
    """验证最终论文末尾会附 CUMCM 要求的支撑材料清单与完整代码。"""

    def test_appends_support_material_list_and_python_files_after_references(self):
        with tempfile.TemporaryDirectory() as work_dir:
            code_path = os.path.join(work_dir, "problem_1.py")
            with open(code_path, "w", encoding="utf-8") as f:
                f.write("x = 1\nprint('hello')\n")
            with open(os.path.join(work_dir, "result.csv"), "w", encoding="utf-8") as f:
                f.write("x,y\n1,2\n")
            with open(os.path.join(work_dir, "figure.png"), "wb") as f:
                f.write(b"png")
            with open(os.path.join(work_dir, "test_save.png"), "wb") as f:
                f.write(b"png")

            markdown = "正文。\n\n## 参考文献\n\n[1] 文献。"
            updated, sources = append_code_appendix(markdown, work_dir)

        self.assertEqual(sources, ["problem_1.py"])
        self.assertIn("## 参考文献\n\n[1] 文献。\n\n# 附录", updated)
        self.assertIn("## 附录A 支撑材料文件列表", updated)
        self.assertIn("| problem_1.py | 源程序代码 |", updated)
        self.assertIn("| result.csv | 数据/结果文件 |", updated)
        self.assertIn("| figure.png | 图片文件 |", updated)
        self.assertNotIn("test_save.png", updated)
        self.assertIn("## 附录B 源程序代码", updated)
        self.assertIn("### B.1 problem_1.py\n\nSHA-256:\n", updated)
        self.assertIn("```python\nx = 1\nprint('hello')\n```", updated)

    def test_extracts_notebook_code_when_no_python_files_exist(self):
        with tempfile.TemporaryDirectory() as work_dir:
            notebook = {
                "cells": [
                    {"cell_type": "markdown", "source": ["# note"]},
                    {"cell_type": "code", "source": ["x = 1\n", "print(x)\n"]},
                ]
            }
            with open(os.path.join(work_dir, "notebook.ipynb"), "w", encoding="utf-8") as f:
                json.dump(notebook, f)

            updated, sources = append_code_appendix("正文。", work_dir)

        self.assertEqual(sources, ["notebook.ipynb"])
        self.assertIn("## 附录A 支撑材料文件列表", updated)
        self.assertIn("| notebook.ipynb | 源程序代码 |", updated)
        self.assertIn("# Cell 1", updated)
        self.assertIn("x = 1", updated)
        self.assertIn("print(x)", updated)

    def test_code_appendix_fence_is_longer_than_embedded_backticks(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "problem.py"), "w", encoding="utf-8") as f:
                f.write("snippet = '''\\n```python\\nprint(1)\\n```\\n'''\n")

            updated, sources = append_code_appendix("正文。", work_dir)

        self.assertEqual(sources, ["problem.py"])
        self.assertIn("~~~python\nsnippet = '''", updated)
        self.assertIn("\n~~~", updated)

    def test_code_appendix_escapes_lstlisting_end_marker(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "problem.py"), "w", encoding="utf-8") as f:
                f.write("latex = r'''\\end{lstlisting}\\n\\begin{table}[H]\\n'''")

            updated, sources = append_code_appendix("正文。", work_dir)

        self.assertEqual(sources, ["problem.py"])
        self.assertNotIn(r"\end{lstlisting}", updated)
        self.assertIn(r"\end{lstlisting }", updated)

    def test_code_appendix_shortens_long_separator_lines(self):
        with tempfile.TemporaryDirectory() as work_dir:
            long_separator = "=" * 80
            with open(os.path.join(work_dir, "problem.py"), "w", encoding="utf-8") as f:
                f.write(f"# {long_separator}\nx = 1\nprint('ok')\n")

            updated, sources = append_code_appendix("正文。", work_dir)

        self.assertEqual(sources, ["problem.py"])
        self.assertIn("x = 1", updated)
        self.assertIn("print('ok')", updated)
        self.assertNotIn(long_separator, updated)

    def test_preflight_accepts_complete_source_with_print_calls(self):
        noisy_code = "\n".join(f"print({index})" for index in range(25))
        markdown = (
            "# 基于优化模型的生产方案研究\n\n"
            "## 摘要\n\n"
            "本文围绕生产优化问题建立线性规划模型，结合资源约束、利润目标和敏感性分析给出可复核的生产方案。"
            "模型首先对机器时间和人工时间进行约束刻画，随后通过目标函数求解最大利润，并在结果分析中讨论资源变化对利润的影响。"
            "结果表明，所给方案能够在约束范围内获得较高利润，同时机器时间增加会带来边际收益变化。\n\n"
            "关键词：线性规划；生产优化；敏感性分析；资源约束\n\n"
            "# 一、问题重述\n\n正文。\n\n"
            "# 二、问题分析\n\n正文。\n\n"
            "# 三、模型假设\n\n正文。\n\n"
            "# 四、符号说明\n\n正文。\n\n"
            "# 五、模型的建立与求解\n\n正文。\n\n"
            "# 六、模型的分析与检验\n\n正文。\n\n"
            "# 七、模型的评价、改进与推广\n\n正文。\n\n"
            "## 参考文献\n\n[1] 文献。\n\n"
            "# 附录\n\n"
            "## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
            f"## 附录B 源程序代码\n\n```python\n{noisy_code}\n```\n"
        )

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=["problem.py"],
        )

        self.assertTrue(report["checks"]["appendix_console_noise"]["passed"])

    def test_preflight_does_not_treat_future_algorithm_as_implemented_claim(self):
        markdown = (
            "# 标题\n\n"
            "## 摘要\n\n"
            "本文建立可复核的压力控制模型，并通过网格搜索得到控制参数。\n\n"
            "关键词：压力控制；网格搜索；敏感性分析；燃油系统\n\n"
            "# 一、问题重述\n\n正文。\n\n"
            "# 二、问题分析\n\n正文。\n\n"
            "# 三、模型假设\n\n正文。\n\n"
            "# 四、符号说明\n\n正文。\n\n"
            "# 五、模型的建立与求解\n\n正文。\n\n"
            "# 六、模型的分析与检验\n\n正文。\n\n"
            "# 七、模型的评价、改进与推广\n\n"
            "后续可升级为遗传算法或粒子群优化，以提升高维参数搜索效率。\n\n"
            "# 附录\n\n"
            "## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
            "## 附录B 源程序代码\n\n本论文没有用到程序。\n"
        )

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(), markdown=markdown, code_sources=[]
        )

        self.assertTrue(report["checks"]["algorithm_evidence"]["passed"])
        self.assertEqual(report["checks"]["algorithm_evidence"]["claims"], [])

    def test_preflight_does_not_treat_rejected_algorithm_comparison_as_claim(self):
        markdown = (
            "# 标题\n\n## 摘要\n\n本文采用线性规划。\n\n"
            "关键词：线性规划；生产优化；资源约束\n\n"
            "# 一、问题重述\n\n正文。\n\n# 二、问题分析\n\n"
            "若采用启发式算法如遗传算法，虽能处理非线性问题，"
            "但对本题线性结构的求解效率不及线性规划。\n\n"
            "# 三、模型假设\n\n正文。\n\n# 四、符号说明\n\n正文。\n\n"
            "# 五、模型的建立与求解\n\n正文。\n\n"
            "# 六、模型的分析与检验\n\n正文。\n\n"
            "# 七、模型的评价、改进与推广\n\n正文。\n\n"
            "# 附录\n\n## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
            "## 附录B 源程序代码\n\n本论文没有用到程序。\n"
        )

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(), markdown=markdown, code_sources=[]
        )

        self.assertTrue(report["checks"]["algorithm_evidence"]["passed"])
        self.assertEqual(report["checks"]["algorithm_evidence"]["claims"], [])

    def test_preflight_does_not_hide_actual_algorithm_claim_after_rejected_sentence(self):
        markdown = (
            "# 标题\n\n## 摘要\n\n本文建立可复核的离散优化模型。\n\n"
            "关键词：优化；复核\n\n# 一、问题重述\n\n正文。\n\n"
            "# 二、问题分析\n\n若采用遗传算法作为未来备选方案，本文此前并未采用。"
            "本文采用遗传算法完成当前求解。\n\n# 三、模型假设\n\n正文。\n\n"
            "# 四、符号说明\n\n正文。\n\n# 五、模型的建立与求解\n\n正文。\n\n"
            "# 六、模型的分析与检验\n\n正文。\n\n# 七、模型的评价、改进与推广\n\n正文。\n\n"
            "# 附录\n\n## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
            "## 附录B 源程序代码\n\n本论文没有用到程序。\n"
        )
        with tempfile.TemporaryDirectory() as work_dir:
            report = build_preflight_report(work_dir, markdown, code_sources=[])

        check = report["checks"]["algorithm_evidence"]
        self.assertFalse(check["passed"])
        self.assertIn(
            {"algorithm": "genetic_algorithm", "implemented": False, "sources": []},
            check["claims"],
        )

    def test_existing_fenced_code_separator_lines_are_shortened(self):
        markdown = "```python\n" + ("=" * 80) + "\nprint('ok')\n```\n"

        updated, count = shorten_long_code_separator_lines(markdown)

        self.assertEqual(count, 1)
        self.assertIn("=" * 48, updated)
        self.assertNotIn("=" * 80, updated)

    def test_appends_no_program_statement_when_no_code_exists(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "result.csv"), "w", encoding="utf-8") as f:
                f.write("x,y\n1,2\n")

            updated, sources = append_code_appendix("正文。", work_dir)

        self.assertEqual(sources, [])
        self.assertIn("## 附录A 支撑材料文件列表", updated)
        self.assertIn("| result.csv | 数据/结果文件 |", updated)
        self.assertIn("本论文没有用到程序", updated)

    def test_key_appendix_mode_uses_vetted_algorithm_note_without_full_notebook(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "solver.py"), "w", encoding="utf-8") as f:
                f.write("def solve():\n    return 1\n")
            with open(os.path.join(work_dir, "paper_appendix_config.json"), "w", encoding="utf-8") as f:
                json.dump({"mode": "key"}, f)
            with open(os.path.join(work_dir, "key_algorithms.md"), "w", encoding="utf-8") as f:
                f.write("### B.1 线性规划核心步骤\n\n```text\nsolve constraints\n```")

            updated, sources = append_code_appendix("正文。", work_dir)

        self.assertEqual(sources, ["solver.py"])
        self.assertIn("精简展示模式", updated)
        self.assertIn("solve constraints", updated)
        self.assertNotIn("def solve", updated)


class TestPreparePaperMarkdown(unittest.TestCase):
    """验证后处理会回写 res.md 并生成预检报告。"""

    def test_prepare_writes_preflight_report(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "res.md"), "w", encoding="utf-8") as f:
                f.write(
                    "# 基于线性规划的生产优化研究\n\n"
                    "## 摘要\n\n"
                    "本文针对生产资源约束下的利润最大化问题建立线性规划模型，综合机器时间、人工时间和单位利润构造目标函数。"
                    "通过求解约束方程并进行敏感性分析，得到可复核的最优生产方案。结果表明，该方案能够在资源限制内提升总利润，"
                    "同时机器时间变化会对最优利润产生可解释的边际影响。\n\n"
                    "关键词：线性规划；生产优化；敏感性分析；资源约束\n\n"
                    "# 一、问题重述\n\n正文{}。\n\n"
                    "## 二、问题分析\n\n正文。\n\n"
                    "# 三、模型假设\n\n正文。\n\n"
                    "# 四、符号说明\n\n正文。\n\n"
                    "# 五、模型的建立与求解\n\n正文[^1]。\n\n"
                    "# 六、模型的分析与检验\n\n正文。\n\n"
                    "# 七、模型的评价、改进与推广\n\n正文。\n\n"
                    "## 参考文献\n\n[^1]: 文献。"
                )
            with open(os.path.join(work_dir, "problem.py"), "w", encoding="utf-8") as f:
                f.write("print('ok')\n")

            report = prepare_paper_markdown(work_dir, "res.md")

            with open(os.path.join(work_dir, "res.md"), encoding="utf-8") as f:
                updated = f.read()
            with open(
                os.path.join(work_dir, "paper_preflight_report.json"),
                encoding="utf-8",
            ) as f:
                saved_report = json.load(f)
            with open(os.path.join(work_dir, "res.md"), "rb") as f:
                written_md_hash = hashlib.sha256(f.read()).hexdigest()
            generated_audit_files = {
                filename: os.path.exists(os.path.join(work_dir, filename))
                for filename in (
                    "paper_outline.json",
                    "figure_usage.json",
                    "claim_trace.json",
                    "claim_trace.md",
                )
            }

        self.assertEqual(report["status"], "PASS")
        self.assertIn("conclusion", saved_report)
        self.assertEqual(saved_report["status"], "PASS")
        self.assertEqual(saved_report["source_sha256"], written_md_hash)
        self.assertIn("正文[1]。", updated)
        self.assertIn("# 二、问题分析", updated)
        self.assertNotIn("正文{}。", updated)
        self.assertIn("# 附录", updated)
        self.assertIn("## 附录A 支撑材料文件列表", updated)
        self.assertIn("## 附录B 源程序代码", updated)
        self.assertTrue(saved_report["checks"]["references"]["passed"])
        self.assertTrue(saved_report["checks"]["export_profile"]["passed"])
        self.assertTrue(saved_report["checks"]["code_appendix"]["passed"])
        self.assertTrue(saved_report["checks"]["support_materials"]["passed"])
        self.assertTrue(saved_report["checks"]["claim_trace"]["passed"])
        semantic_issue_codes = {
            issue["code"]
            for issue in saved_report["checks"]["semantic_layout"].get("issues", [])
        }
        self.assertNotIn("main_section_level_mismatch", semantic_issue_codes)
        self.assertNotIn("empty_reference_marker", semantic_issue_codes)
        self.assertEqual(saved_report["fixups"]["normalised_main_section_headings"], 1)
        self.assertEqual(saved_report["fixups"]["removed_empty_reference_markers"], 1)
        self.assertTrue(all(generated_audit_files.values()), generated_audit_files)

    def test_prepare_removes_missing_image_references_before_preflight(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "res.md"), "w", encoding="utf-8") as f:
                f.write(
                    "# 基于线性规划的生产优化研究\n\n"
                    "**摘要**\n\n"
                    "本文围绕生产优化问题建立线性规划模型，结合资源约束、利润目标和敏感性分析给出可复核的生产方案。"
                    "模型首先对机器时间和人工时间进行约束刻画，随后通过目标函数求解最大利润，并在结果分析中讨论资源变化对利润的影响。"
                    "结果表明，所给方案能够在约束范围内获得较高利润，同时机器时间增加会带来边际收益变化。\n\n"
                    "**关键词**\n线性规划；敏感性分析；生产优化；资源约束\n\n"
                    "# 一、问题重述\n\n正文。\n\n"
                    "# 二、问题分析\n\n正文。\n\n"
                    "# 三、模型假设\n\n正文。\n\n"
                    "# 四、符号说明\n\n正文。\n\n"
                    "# 五、模型的建立与求解\n\n正文。\n\n"
                    "# 六、模型的分析与检验\n\n正文。\n\n"
                    "# 七、模型的评价、改进与推广\n\n正文。\n\n"
                    "![不存在的图](missing.png)\n\n"
                    "## 参考文献\n\n[1] 文献。"
                )
            with open(os.path.join(work_dir, "problem.py"), "w", encoding="utf-8") as f:
                f.write("print('ok')\n")

            report = prepare_paper_markdown(work_dir, "res.md")
            with open(os.path.join(work_dir, "res.md"), encoding="utf-8") as f:
                updated = f.read()

        self.assertNotIn("missing.png", updated)
        self.assertTrue(report["checks"]["images"]["passed"])
        self.assertTrue(report["checks"]["abstract"]["passed"])
        self.assertTrue(report["checks"]["keywords"]["passed"])

    def test_prepare_writes_human_readable_markdown_report(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "res.md"), "w", encoding="utf-8") as f:
                f.write("正文[^1]。\n\n## 参考文献\n\n[^1]: 文献。")
            with open(os.path.join(work_dir, "problem.py"), "w", encoding="utf-8") as f:
                f.write("print('ok')\n")

            prepare_paper_markdown(work_dir, "res.md")

            md_report_path = os.path.join(work_dir, "paper_preflight_report.md")
            self.assertTrue(os.path.exists(md_report_path))
            with open(md_report_path, encoding="utf-8") as f:
                md_report = f.read()

        self.assertIn("# Paper Preflight Report", md_report)
        self.assertIn("## Hard Gates", md_report)
        self.assertIn("## Conditional Checks", md_report)
        self.assertIn("| Check | Result | Detail |", md_report)
        self.assertIn("references", md_report)

    def test_wrong_export_profile_fails_for_cumcm_task(self):
        markdown = (
            "# 基于优化模型的生产方案研究\n\n"
            "## 摘要\n\n"
            "本文围绕生产优化问题建立线性规划模型，结合资源约束、利润目标和敏感性分析给出可复核的生产方案。"
            "模型首先对机器时间和人工时间进行约束刻画，随后通过目标函数求解最大利润，并在结果分析中讨论资源变化对利润的影响。"
            "结果表明，所给方案能够在约束范围内获得较高利润，同时机器时间增加会带来边际收益变化。\n\n"
            "关键词：线性规划；敏感性分析；生产优化；资源约束\n\n"
            "# 一、问题重述\n\n正文。\n\n"
            "# 二、问题分析\n\n正文。\n\n"
            "# 三、模型假设\n\n正文。\n\n"
            "# 四、符号说明\n\n正文。\n\n"
            "# 五、模型的建立与求解\n\n正文。\n\n"
            "# 六、模型的分析与检验\n\n正文。\n\n"
            "# 七、模型的评价、改进与推广\n\n正文。\n\n"
            "## 参考文献\n\n[1] 文献。\n\n"
            "# 附录\n\n"
            "## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
            "## 附录B 源程序代码\n\n```python\nprint('ok')\n```\n"
        )

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=["problem.py"],
            export_profile="huashubei",
        )

        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"]["export_profile"]["passed"])

    def test_claim_trace_strong_wording_without_evidence_fails_preflight(self):
        markdown = (
            "# 方案\n\n"
            "## 摘要\n\n"
            "本文证明该方案显著优于所有方案，并可精确预测后续利润。\n\n"
            "关键词：线性规划；生产优化；敏感性分析\n\n"
            "# 一、问题重述\n\n正文。\n\n"
            "# 二、问题分析\n\n正文。\n\n"
            "# 三、模型假设\n\n正文。\n\n"
            "# 四、符号说明\n\n正文。\n\n"
            "# 五、模型的建立与求解\n\n正文。\n\n"
            "# 六、模型的分析与检验\n\n正文。\n\n"
            "# 七、模型的评价、改进与推广\n\n正文。\n\n"
            "## 参考文献\n\n[1] 文献。\n\n"
            "# 附录\n\n"
            "## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
            "## 附录B 源程序代码\n\n```python\nprint('ok')\n```\n"
        )
        trace = build_claim_trace(markdown, [])
        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=[],
            claim_trace=trace,
        )

        self.assertEqual(trace["status"], "FAIL")
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"]["claim_trace"]["passed"])
        self.assertEqual(report["checks"]["claim_trace"]["severity"], "fail")

    def test_numeric_code_backed_strong_wording_passes_claim_trace(self):
        markdown = (
            "# 方案\n\n"
            "结果表明，最优解处机器时间完全利用，利润增加166.7元。\n"
        )

        trace = build_claim_trace(markdown, ["notebook.ipynb"])

        self.assertEqual(trace["status"], "PASS")

    def test_preflight_fails_shadow_price_conflicts_with_result_csv(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(
                os.path.join(work_dir, "机器时间敏感性分析结果.csv"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(
                    "分析项目,数值,单位,备注\n"
                    "机器时间影子价格,16.666666666666668,元/小时,理论计算\n"
                    "人工时间影子价格,6.666666666666667,元/小时,理论计算\n"
                )
            markdown = (
                "# 方案\n\n"
                "## 摘要\n\n"
                "本文围绕生产优化问题建立线性规划模型，结合资源约束、利润目标和敏感性分析给出可复核的生产方案。"
                "模型首先对机器时间和人工时间进行约束刻画，随后通过目标函数求解最大利润，并在结果分析中讨论资源变化对利润的影响。"
                "结果表明，机器时间和人工时间的影子价格分别为26.7元/小时和13.3元/小时。\n\n"
                "关键词：线性规划；生产优化；敏感性分析；资源约束\n\n"
                "# 一、问题重述\n\n正文。\n\n"
                "# 二、问题分析\n\n正文。\n\n"
                "# 三、模型假设\n\n正文。\n\n"
                "# 四、符号说明\n\n正文。\n\n"
                "# 五、模型的建立与求解\n\n正文。\n\n"
                "# 六、模型的分析与检验\n\n正文。\n\n"
                "# 七、模型的评价、改进与推广\n\n正文。\n\n"
                "## 参考文献\n\n[1] 文献。\n\n"
                "# 附录\n\n"
                "## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
                "## 附录B 源程序代码\n\n```python\nprint('ok')\n```\n"
            )

            report = build_preflight_report(
                work_dir=work_dir,
                markdown=markdown,
                code_sources=["problem.py"],
            )

        self.assertEqual(report["status"], "FAIL")
        check = report["checks"]["result_consistency"]
        self.assertFalse(check["passed"])
        self.assertEqual(check["severity"], "fail")
        self.assertEqual(len(check["conflicts"]), 2)

    def test_preflight_passes_matching_shadow_price_result_csv(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(
                os.path.join(work_dir, "机器时间敏感性分析结果.csv"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(
                    "分析项目,数值,单位,备注\n"
                    "机器时间影子价格,16.666666666666668,元/小时,理论计算\n"
                    "人工时间影子价格,6.666666666666667,元/小时,理论计算\n"
                )
            markdown = (
                "# 方案\n\n"
                "## 摘要\n\n"
                "本文围绕生产优化问题建立线性规划模型，结合资源约束、利润目标和敏感性分析给出可复核的生产方案。"
                "模型首先对机器时间和人工时间进行约束刻画，随后通过目标函数求解最大利润，并在结果分析中讨论资源变化对利润的影响。"
                "结果表明，机器时间和人工时间的影子价格分别为16.67元/小时和6.67元/小时。\n\n"
                "关键词：线性规划；生产优化；敏感性分析；资源约束\n\n"
                "# 一、问题重述\n\n正文。\n\n"
                "# 二、问题分析\n\n正文。\n\n"
                "# 三、模型假设\n\n正文。\n\n"
                "# 四、符号说明\n\n正文。\n\n"
                "# 五、模型的建立与求解\n\n正文。\n\n"
                "# 六、模型的分析与检验\n\n正文。\n\n"
                "# 七、模型的评价、改进与推广\n\n正文。\n\n"
                "## 参考文献\n\n[1] 文献。\n\n"
                "# 附录\n\n"
                "## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
                "## 附录B 源程序代码\n\n```python\nprint('ok')\n```\n"
            )

            report = build_preflight_report(
                work_dir=work_dir,
                markdown=markdown,
                code_sources=["problem.py"],
            )

        check = report["checks"]["result_consistency"]
        self.assertTrue(check["passed"])
        self.assertEqual(check["conflicts"], [])

    def test_frozen_result_consistency_distinguishes_result_claims_from_context(self):
        """Sensitivity prose and unit parameters must not be treated as frozen results."""
        metrics = [
            {
                "id": "optimal_profit",
                "base_id": "optimal_profit",
                "subtask_id": "ques1",
                "label": "最优利润",
                "aliases": ["最大利润"],
                "value": 2200.0,
                "unit": "元",
                "explanation": "原始生产方案的最优目标值",
            },
            {
                "id": "original_profit",
                "base_id": "original_profit",
                "subtask_id": "ques2",
                "label": "原始利润",
                "value": 2200.0,
                "unit": "元",
                "explanation": "敏感性分析前的目标值",
            },
            {
                "id": "new_profit",
                "base_id": "new_profit",
                "subtask_id": "ques2",
                "label": "新利润",
                "value": 2366.666667,
                "unit": "元",
                "explanation": "机器时间增加后的目标值",
            },
            {
                "id": "machine_time_used",
                "base_id": "machine_time_used",
                "subtask_id": "ques1",
                "label": "机器时间使用量",
                "aliases": ["机器时间消耗"],
                "value": 100.0,
                "unit": "小时",
                "explanation": "原始最优方案的机器时间使用量",
            },
            {
                "id": "labor_time_used",
                "base_id": "labor_time_used",
                "subtask_id": "ques1",
                "label": "人工时间使用量",
                "aliases": ["人工时间消耗"],
                "value": 80.0,
                "unit": "小时",
                "explanation": "原始最优方案的人工时间使用量",
            },
        ]
        correct_markdown = (
            "最优利润从2200元提升至2366.666667元。\n\n"
            "新最优利润达到2366.666667元，较原始利润增加166.666667元，增长率达7.575758%。\n\n"
            "当机器时间约束增加10小时（即从100小时增加到110小时）时，分析最优生产方案和最大利润的变化。\n\n"
            "产品A的机器时间消耗效率（2小时/件）与人工时间消耗效率（1小时/件）更有利。"
        )
        wrong_markdown = (
            "最优利润为2600元。原始利润为2600元。新利润达到2500元。"
            "机器时间使用量为90小时。"
        )
        mixed_metric_markdown = "原始利润为2100元，调整后最优利润为2366.666667元。"
        repeated_alias_markdown = "原始利润的变化情况，原始利润为2100元。"
        with tempfile.TemporaryDirectory() as work_dir:
            source_path = os.path.join(work_dir, "result.csv")
            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write("verified result evidence\n")
            with open(source_path, "rb") as handle:
                source_sha256 = hashlib.sha256(handle.read()).hexdigest()
            with open(os.path.join(work_dir, "frozen_results.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "schema": "mathmodel.result-freeze",
                        "version": 1,
                        "metrics": metrics,
                        "sources": [
                            {
                                "relative_path": "result.csv",
                                "sha256": source_sha256,
                                "role": "evidence",
                            }
                        ],
                    },
                    handle,
                    ensure_ascii=False,
                )

            correct = build_preflight_report(work_dir, correct_markdown, code_sources=[])
            wrong = build_preflight_report(work_dir, wrong_markdown, code_sources=[])
            mixed_metric = build_preflight_report(work_dir, mixed_metric_markdown, code_sources=[])
            repeated_alias = build_preflight_report(work_dir, repeated_alias_markdown, code_sources=[])

        self.assertTrue(correct["checks"]["result_consistency"]["passed"])
        self.assertEqual(correct["checks"]["result_consistency"]["conflicts"], [])
        self.assertFalse(wrong["checks"]["result_consistency"]["passed"])
        self.assertEqual(
            {item["fact"] for item in wrong["checks"]["result_consistency"]["conflicts"]},
            {"最优利润", "原始利润", "新利润", "机器时间使用量"},
        )
        self.assertFalse(mixed_metric["checks"]["result_consistency"]["passed"])
        self.assertEqual(
            mixed_metric["checks"]["result_consistency"]["conflicts"][0]["fact"],
            "原始利润",
        )
        self.assertFalse(repeated_alias["checks"]["result_consistency"]["passed"])
        self.assertEqual(
            repeated_alias["checks"]["result_consistency"]["conflicts"][0]["fact"],
            "原始利润",
        )

    def test_frozen_result_consistency_ignores_substring_alias_of_longer_metric(self):
        """中文指标名无词边界：短名（硅外延层厚度）落在长名（碳化硅外延层厚度）
        内部时，正文对长名指标的正确陈述不得被误判为短名指标的数值冲突，
        否则假冲突会写进定向回修证据、使论文回修永不收敛。"""
        metrics = [
            {
                "id": "q1_sic_thickness",
                "base_id": "q1_sic_thickness",
                "subtask_id": "ques1",
                "label": "碳化硅外延层厚度",
                "value": 113.235423,
                "unit": "um",
                "explanation": "碳化硅晶圆片双角度联合拟合厚度",
            },
            {
                "id": "q1_si_thickness",
                "base_id": "q1_si_thickness",
                "subtask_id": "ques1",
                "label": "硅外延层厚度",
                "value": 15.261941,
                "unit": "um",
                "explanation": "硅晶圆片双角度联合拟合厚度",
            },
        ]
        # 两句都陈述各自指标的正确冻结值；短名指标不得把碳化硅句的 113.23 当冲突。
        correct_markdown = (
            "碳化硅外延层厚度拟合结果为 113.235423 微米。\n\n"
            "硅外延层厚度拟合结果为 15.261941 微米。"
        )
        # 硅句写错值时仍须被本指标拦下。
        wrong_markdown = (
            "碳化硅外延层厚度拟合结果为 113.235423 微米。\n\n"
            "硅外延层厚度拟合结果为 99.9 微米。"
        )
        with tempfile.TemporaryDirectory() as work_dir:
            source_path = os.path.join(work_dir, "result.csv")
            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write("verified result evidence\n")
            with open(source_path, "rb") as handle:
                source_sha256 = hashlib.sha256(handle.read()).hexdigest()
            with open(os.path.join(work_dir, "frozen_results.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "schema": "mathmodel.result-freeze",
                        "version": 1,
                        "metrics": metrics,
                        "sources": [
                            {
                                "relative_path": "result.csv",
                                "sha256": source_sha256,
                                "role": "evidence",
                            }
                        ],
                    },
                    handle,
                    ensure_ascii=False,
                )
            correct = build_preflight_report(work_dir, correct_markdown, code_sources=[])
            wrong = build_preflight_report(work_dir, wrong_markdown, code_sources=[])

        self.assertTrue(
            correct["checks"]["result_consistency"]["passed"],
            correct["checks"]["result_consistency"]["conflicts"],
        )
        self.assertFalse(wrong["checks"]["result_consistency"]["passed"])
        self.assertEqual(
            {item["fact"] for item in wrong["checks"]["result_consistency"]["conflicts"]},
            {"硅外延层厚度"},
        )

    def test_frozen_range_span_uses_endpoints_and_respects_eda_scope(self):
        """范围指标比较端点差，且题目指标不扫描 4.2 的 EDA 覆盖范围。"""
        metric = {
            "id": "wavelength_range",
            "base_id": "wavelength_range",
            "subtask_id": "ques1",
            "label": "波长范围",
            "value": 22.5,
            "unit": "μm",
            "explanation": "从2.5μm到25μm的跨度",
        }
        correct_markdown = (
            "## 4.2 描述性统计\n\n"
            "附件1的实际波长范围为3.22-19.16 μm。\n\n"
            "## 5.1.2 模型的求解\n\n"
            "理论波长范围为2.5 μm至25 μm。\n"
        )
        wrong_markdown = (
            "## 4.2 描述性统计\n\n"
            "附件1的实际波长范围为3.22-19.16 μm。\n\n"
            "## 5.1.2 模型的求解\n\n"
            "理论波长范围为2.5 μm至24 μm。\n"
        )
        with tempfile.TemporaryDirectory() as work_dir:
            source_path = os.path.join(work_dir, "result.csv")
            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write("verified result evidence\n")
            with open(source_path, "rb") as handle:
                source_sha256 = hashlib.sha256(handle.read()).hexdigest()
            with open(
                os.path.join(work_dir, "frozen_results.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(
                    {
                        "schema": "mathmodel.result-freeze",
                        "version": 1,
                        "metrics": [metric],
                        "sources": [
                            {
                                "relative_path": "result.csv",
                                "sha256": source_sha256,
                                "role": "evidence",
                            }
                        ],
                    },
                    handle,
                    ensure_ascii=False,
                )

            correct = build_preflight_report(work_dir, correct_markdown, code_sources=[])
            wrong = build_preflight_report(work_dir, wrong_markdown, code_sources=[])

        correct_check = correct["checks"]["result_consistency"]
        self.assertTrue(correct_check["passed"], correct_check["conflicts"])
        self.assertEqual(correct_check["conflicts"], [])
        wrong_check = wrong["checks"]["result_consistency"]
        self.assertFalse(wrong_check["passed"])
        self.assertEqual(len(wrong_check["conflicts"]), 1)
        self.assertEqual(wrong_check["conflicts"][0]["paper_section"], "5.1.2 模型的求解")
        self.assertIn(21.5, wrong_check["conflicts"][0]["paper_numbers"])

    def test_frozen_result_consistency_reads_result_position_and_variant_scope(self):
        """演算链取等号后的结果位；共享别名的新旧变体按语境归属，不交叉误报。"""
        metrics = [
            {
                "id": "optimal_profit",
                "base_id": "optimal_profit",
                "subtask_id": "ques1",
                "label": "最优利润",
                "aliases": ["最大利润"],
                "value": 2200.0,
                "unit": "元",
                "explanation": "原始生产方案的最优目标值",
            },
            {
                "id": "new_optimal_profit",
                "base_id": "new_optimal_profit",
                "subtask_id": "ques2",
                "label": "新最优利润",
                "aliases": ["最大利润"],
                "value": 2366.666667,
                "unit": "元",
                "explanation": "机器时间增加后的目标值",
            },
            {
                "id": "machine_time_used",
                "base_id": "machine_time_used",
                "subtask_id": "ques1",
                "label": "机器时间使用量",
                "aliases": ["机器时间消耗"],
                "value": 100.0,
                "unit": "小时",
                "explanation": "原始最优方案的机器时间使用量",
            },
            {
                "id": "machine_time_used_new",
                "base_id": "machine_time_used_new",
                "subtask_id": "ques2",
                "label": "机器时间使用量",
                "aliases": ["机器时间消耗"],
                "value": 110.0,
                "unit": "小时",
                "explanation": "调整后方案的机器时间使用量",
            },
            {
                "id": "labor_time_used",
                "base_id": "labor_time_used",
                "subtask_id": "ques1",
                "label": "人工时间使用量",
                "value": 80.0,
                "unit": "小时",
                "explanation": "原始最优方案的人工时间使用量",
            },
            {
                "id": "profit_increase",
                "base_id": "profit_increase",
                "subtask_id": "ques2",
                "label": "利润增加量",
                "value": 166.666667,
                "unit": "元",
                "explanation": "机器时间增加后的利润增量",
            },
            {
                "id": "shadow_price",
                "base_id": "shadow_price",
                "subtask_id": "ques2",
                "label": "影子价格",
                "aliases": ["对偶价格"],
                "value": 16.666667,
                "unit": "元/小时",
                "explanation": "机器时间约束的影子价格",
            },
        ]
        # 全部句式取自真实任务 20260715-083558 被误报的正文
        correct_markdown = (
            "此时，最大利润为\\(z^{*} = 40 \\times 40 + 30 \\times 20 = 2200\\)元。\n\n"
            "最优生产方案下，机器时间使用量为\\(2 \\times 40 + 20 = 100\\)小时，"
            "人工时间使用量为\\(40 + 2 \\times 20 = 80\\)小时，恰好达到资源上限。\n\n"
            "机器时间约束的影子价格计算为"
            "\\(\\frac{\\Delta z}{\\Delta b} = \\frac{166.67}{10} = 16.67\\)元/小时。\n\n"
            "影子价格 = 利润增加量 / 机器时间增加量 = 166.67元 / 10小时 = 16.67元/小时。\n\n"
            "重新求解模型，最大利润提升至约2366.67元。\n\n"
            "新方案下的最大利润为2366.67元，相较于原利润增加了166.67元。\n\n"
            "将该坐标代入目标函数，得到新的最大利润为"
            "\\(z' = 40 \\times 46.67 + 30 \\times 16.67 = 2366.67\\)元。\n\n"
            "根据冻结结果，原问题的最优生产方案对应最大利润为2200.0元。"
        )
        wrong_markdown = (
            "此时，最大利润为\\(z^{*} = 40 \\times 40 + 30 \\times 20 = 2400\\)元。\n\n"
            "新方案下的最大利润为2500元。\n\n"
            "机器时间使用量为\\(2 \\times 40 + 20 = 90\\)小时。"
        )
        with tempfile.TemporaryDirectory() as work_dir:
            source_path = os.path.join(work_dir, "result.csv")
            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write("verified result evidence\n")
            with open(source_path, "rb") as handle:
                source_sha256 = hashlib.sha256(handle.read()).hexdigest()
            with open(
                os.path.join(work_dir, "frozen_results.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(
                    {
                        "schema": "mathmodel.result-freeze",
                        "version": 1,
                        "metrics": metrics,
                        "sources": [
                            {
                                "relative_path": "result.csv",
                                "sha256": source_sha256,
                                "role": "evidence",
                            }
                        ],
                    },
                    handle,
                    ensure_ascii=False,
                )

            correct = build_preflight_report(work_dir, correct_markdown, code_sources=[])
            wrong = build_preflight_report(work_dir, wrong_markdown, code_sources=[])

        self.assertTrue(
            correct["checks"]["result_consistency"]["passed"],
            correct["checks"]["result_consistency"]["conflicts"],
        )
        self.assertEqual(correct["checks"]["result_consistency"]["conflicts"], [])
        wrong_check = wrong["checks"]["result_consistency"]
        self.assertFalse(wrong_check["passed"])
        # 无归属前缀的错误值（“最大利润为2400元”）无法判定新旧变体，
        # 同句对共享别名的两个变体各报一次冲突是保守且可接受的
        self.assertEqual(
            {item["fact"] for item in wrong_check["conflicts"]},
            {"最优利润", "新最优利润", "机器时间使用量"},
        )
        # 带“新方案下”归属的错误值只归属新变体，不得再挂到基线指标
        explicit_new = [
            item
            for item in wrong_check["conflicts"]
            if "2500" in str(item["paper_numbers"])
        ]
        self.assertEqual({item["fact"] for item in explicit_new}, {"新最优利润"})

    def test_figure_result_consistency_uses_result_position_and_variant_scope(self):
        """图表邻近句复用同一取数架构：演算链结果位与新旧变体归属。"""
        metrics = [
            {
                "id": "optimal_profit",
                "base_id": "optimal_profit",
                "subtask_id": "ques1",
                "label": "最优利润",
                "aliases": ["最大利润"],
                "value": 2200.0,
                "unit": "元",
                "explanation": "原始生产方案的最优目标值",
            },
            {
                "id": "new_optimal_profit",
                "base_id": "new_optimal_profit",
                "subtask_id": "ques2",
                "label": "新最优利润",
                "aliases": ["最大利润"],
                "value": 2366.666667,
                "unit": "元",
                "explanation": "机器时间增加后的目标值",
            },
        ]
        markdown_ok = (
            "![问题1可行域](问题1_可行域与最优解.png)\n\n"
            "将该坐标代入目标函数，得到最大利润为"
            "\\(z^{*} = 40 \\times 40 + 30 \\times 20 = 2200\\)元。"
            "重新求解模型，得到对应的最大利润提升至约2366.67元。\n"
        )
        markdown_bad = (
            "![问题1可行域](问题1_可行域与最优解.png)\n\n"
            "将该坐标代入目标函数，得到最大利润为"
            "\\(z^{*} = 40 \\times 40 + 30 \\times 20 = 2400\\)元。\n"
        )
        with tempfile.TemporaryDirectory() as work_dir:
            source_path = os.path.join(work_dir, "result.csv")
            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write("verified result evidence\n")
            with open(source_path, "rb") as handle:
                source_sha256 = hashlib.sha256(handle.read()).hexdigest()
            with open(
                os.path.join(work_dir, "问题1_可行域与最优解.png"), "wb"
            ) as handle:
                handle.write(b"png placeholder for text-level test")
            with open(
                os.path.join(work_dir, "frozen_results.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(
                    {
                        "schema": "mathmodel.result-freeze",
                        "version": 1,
                        "metrics": metrics,
                        "sources": [
                            {
                                "relative_path": "result.csv",
                                "sha256": source_sha256,
                                "role": "evidence",
                            }
                        ],
                        "figures": [
                            {
                                "path": "问题1_可行域与最优解.png",
                                "metric_ids": ["optimal_profit", "new_optimal_profit"],
                            }
                        ],
                    },
                    handle,
                    ensure_ascii=False,
                )

            report_ok = build_preflight_report(work_dir, markdown_ok, code_sources=[])
            report_bad = build_preflight_report(work_dir, markdown_bad, code_sources=[])

        ok_check = report_ok["checks"]["figure_result_consistency"]
        self.assertTrue(ok_check["passed"], ok_check["conflicts"])
        bad_check = report_bad["checks"]["figure_result_consistency"]
        self.assertFalse(bad_check["passed"])
        # 2400 与两个变体的冻结值都不一致且无归属前缀：对共享别名的两个
        # 绑定指标各报一次是保守行为；关键断言是错误值被拦截且句子正确
        self.assertEqual(
            {item["fact"] for item in bad_check["conflicts"]},
            {"最优利润", "新最优利润"},
        )
        self.assertTrue(
            all(2400.0 in item["paper_numbers"] for item in bad_check["conflicts"])
        )


    def test_variant_sibling_exemption_works_without_explicit_aliases(self):
        """真实 Coder 生成的冻结结果只有 label，不设 aliases 字段。

        基线 label=最大利润 / 新变体 label=新最大利润 → _metric_aliases 无交集
        → sibling exemption 失效 → 正文"最大利润提升至2266.67元"被误报。

        真实任务 20260726-155823 的 preflight 结果。
        """
        metrics = [
            {
                "id": "objective_value",
                "subtask_id": "ques1",
                "label": "最大利润",
                "value": 2200.0,
                "unit": "元",
                "explanation": "原始方案的目标函数最优值。",
            },
            {
                "id": "new_objective_value",
                "subtask_id": "ques2",
                "label": "新最大利润",
                "value": 2266.6667,
                "unit": "元",
                "explanation": "机器时间增加后的目标函数最优值。",
            },
        ]
        # 句子明确说调整后场景，不带"新方案下"前缀
        markdown = (
            "当机器时间增加至90小时时，新最优解调整为产品A 36.67件、"
            "产品B 26.67件，最大利润提升至2266.67元。"
        )
        with tempfile.TemporaryDirectory() as work_dir:
            source_path = os.path.join(work_dir, "result.csv")
            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write("evidence\n")
            with open(source_path, "rb") as handle:
                source_sha256 = hashlib.sha256(handle.read()).hexdigest()
            with open(
                os.path.join(work_dir, "frozen_results.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(
                    {
                        "schema": "mathmodel.result-freeze",
                        "version": 1,
                        "metrics": metrics,
                        "sources": [
                            {
                                "relative_path": "result.csv",
                                "sha256": source_sha256,
                                "role": "evidence",
                            }
                        ],
                    },
                    handle,
                    ensure_ascii=False,
                )

            report = build_preflight_report(work_dir, markdown, code_sources=[])

        rc = report["checks"]["result_consistency"]
        self.assertTrue(rc["passed"], rc.get("conflicts"))
        self.assertEqual(rc["conflicts"], [])

    def test_variant_sibling_exemption_still_blocks_wrong_baseline_value(self):
        """sibling exemption 豁免的是正确的新变体值，不是任意错误数字。"""
        metrics = [
            {
                "id": "objective_value",
                "subtask_id": "ques1",
                "label": "最大利润",
                "value": 2200.0,
                "unit": "元",
                "explanation": "原始方案的目标函数最优值。",
            },
            {
                "id": "new_objective_value",
                "subtask_id": "ques2",
                "label": "新最大利润",
                "value": 2266.6667,
                "unit": "元",
                "explanation": "机器时间增加后的目标函数最优值。",
            },
        ]
        # 故意把新变体的值写错
        markdown = (
            "当机器时间增加至90小时时，新最优解调整为产品A 36.67件、"
            "产品B 26.67件，最大利润提升至2500.0元。"
        )
        with tempfile.TemporaryDirectory() as work_dir:
            source_path = os.path.join(work_dir, "result.csv")
            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write("evidence\n")
            with open(source_path, "rb") as handle:
                source_sha256 = hashlib.sha256(handle.read()).hexdigest()
            with open(
                os.path.join(work_dir, "frozen_results.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(
                    {
                        "schema": "mathmodel.result-freeze",
                        "version": 1,
                        "metrics": metrics,
                        "sources": [
                            {
                                "relative_path": "result.csv",
                                "sha256": source_sha256,
                                "role": "evidence",
                            }
                        ],
                    },
                    handle,
                    ensure_ascii=False,
                )

            report = build_preflight_report(work_dir, markdown, code_sources=[])

        rc = report["checks"]["result_consistency"]
        self.assertFalse(rc["passed"])
        conflicts = rc["conflicts"]
        self.assertGreaterEqual(len(conflicts), 1)
        self.assertTrue(
            any(2500.0 in item.get("paper_numbers", []) for item in conflicts),
            conflicts,
        )

    def test_preflight_ignores_symbol_subscripts_in_result_consistency(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(
                os.path.join(work_dir, "敏感性分析结果汇总表.csv"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write("分析项目,数值,单位,备注\n机器时间影子价格,16.67,元/小时,理论计算\n")
            markdown = (
                "# 方案\n\n"
                "## 摘要\n\n"
                "本文围绕生产优化问题建立线性规划模型，结合资源约束、利润目标和敏感性分析给出可复核的生产方案。"
                "模型首先对机器时间和人工时间进行约束刻画，随后通过目标函数求解最大利润，并在结果分析中讨论资源变化对利润的影响。"
                "结果表明，机器时间影子价格为16.67元/小时。\n\n"
                "关键词：线性规划；生产优化；敏感性分析；资源约束\n\n"
                "# 一、问题重述\n\n正文。\n\n"
                "# 二、问题分析\n\n正文。\n\n"
                "# 三、模型假设\n\n正文。\n\n"
                "# 四、符号说明\n\n"
                "| 符号 | 含义 | 单位 |\n"
                "| --- | --- | --- |\n"
                "| $\\lambda_1$ | 机器时间影子价格 | 元/小时 |\n\n"
                "# 五、模型的建立与求解\n\n正文。\n\n"
                "# 六、模型的分析与检验\n\n正文。\n\n"
                "# 七、模型的评价、改进与推广\n\n正文。\n\n"
                "## 参考文献\n\n[1] 文献。\n\n"
                "# 附录\n\n"
                "## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
                "## 附录B 源程序代码\n\n```python\nprint('ok')\n```\n"
            )

            report = build_preflight_report(
                work_dir=work_dir,
                markdown=markdown,
                code_sources=["problem.py"],
            )

        check = report["checks"]["result_consistency"]
        self.assertTrue(check["passed"])
        self.assertEqual(check["conflicts"], [])

    def test_preflight_fails_swapped_shadow_prices_in_respective_sentence(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(
                os.path.join(work_dir, "机器时间敏感性分析结果.csv"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(
                    "分析项目,数值,单位,备注\n"
                    "机器时间影子价格,16.666666666666668,元/小时,理论计算\n"
                    "人工时间影子价格,6.666666666666667,元/小时,理论计算\n"
                )
            markdown = (
                "# 方案\n\n"
                "## 摘要\n\n"
                "本文围绕生产优化问题建立线性规划模型，结合资源约束、利润目标和敏感性分析给出可复核的生产方案。"
                "模型首先对机器时间和人工时间进行约束刻画，随后通过目标函数求解最大利润，并在结果分析中讨论资源变化对利润的影响。"
                "结果表明，机器时间和人工时间的影子价格分别为6.67元/小时和16.67元/小时。\n\n"
                "关键词：线性规划；生产优化；敏感性分析；资源约束\n\n"
                "# 一、问题重述\n\n正文。\n\n"
                "# 二、问题分析\n\n正文。\n\n"
                "# 三、模型假设\n\n正文。\n\n"
                "# 四、符号说明\n\n正文。\n\n"
                "# 五、模型的建立与求解\n\n正文。\n\n"
                "# 六、模型的分析与检验\n\n正文。\n\n"
                "# 七、模型的评价、改进与推广\n\n正文。\n\n"
                "## 参考文献\n\n[1] 文献。\n\n"
                "# 附录\n\n"
                "## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
                "## 附录B 源程序代码\n\n```python\nprint('ok')\n```\n"
            )

            report = build_preflight_report(
                work_dir=work_dir,
                markdown=markdown,
                code_sources=["problem.py"],
            )

        check = report["checks"]["result_consistency"]
        self.assertFalse(check["passed"])
        self.assertEqual(len(check["conflicts"]), 2)

    def test_preflight_uses_filename_context_for_generic_shadow_price_csv_row(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(
                os.path.join(work_dir, "机器时间敏感性分析结果汇总.csv"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(
                    "分析项目,数值,单位,备注\n"
                    "影子价格,16.666666666666668,元/小时,每增加1h机器时间利润增加\n"
                )
            markdown = (
                "# 方案\n\n"
                "## 摘要\n\n"
                "本文围绕生产优化问题建立线性规划模型，结合资源约束、利润目标和敏感性分析给出可复核的生产方案。"
                "模型首先对机器时间和人工时间进行约束刻画，随后通过目标函数求解最大利润，并在结果分析中讨论资源变化对利润的影响。"
                "结果表明，机器时间影子价格为26.7元/小时。\n\n"
                "关键词：线性规划；生产优化；敏感性分析；资源约束\n\n"
                "# 一、问题重述\n\n正文。\n\n"
                "# 二、问题分析\n\n正文。\n\n"
                "# 三、模型假设\n\n正文。\n\n"
                "# 四、符号说明\n\n正文。\n\n"
                "# 五、模型的建立与求解\n\n正文。\n\n"
                "# 六、模型的分析与检验\n\n正文。\n\n"
                "# 七、模型的评价、改进与推广\n\n正文。\n\n"
                "## 参考文献\n\n[1] 文献。\n\n"
                "# 附录\n\n"
                "## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
                "## 附录B 源程序代码\n\n```python\nprint('ok')\n```\n"
            )

            report = build_preflight_report(
                work_dir=work_dir,
                markdown=markdown,
                code_sources=["problem.py"],
            )

        check = report["checks"]["result_consistency"]
        self.assertFalse(check["passed"])
        self.assertEqual(check["facts"][0]["fact"], "机器时间影子价格")
        self.assertEqual(len(check["conflicts"]), 1)


class TestEnhancedPreflightChecks(unittest.TestCase):
    """验证增强预检规则。"""

    def test_complete_paper_passes_structure_checks(self):
        markdown = (
            "# 基于优化模型的生产方案研究\n\n"
            "## 摘要\n\n"
            "本文围绕生产优化问题建立线性规划模型，结合资源约束、利润目标和敏感性分析给出可复核的生产方案。"
            "模型首先对机器时间和人工时间进行约束刻画，随后通过目标函数求解最大利润，并在结果分析中讨论资源变化对利润的影响。"
            "结果表明，所给方案能够在约束范围内获得较高利润，同时机器时间增加会带来边际收益变化。\n\n"
            "关键词：线性规划；敏感性分析；生产优化；资源约束\n\n"
            "# 一、问题重述\n\n正文。\n\n"
            "# 二、问题分析\n\n正文。\n\n"
            "# 三、模型假设\n\n正文。\n\n"
            "# 四、符号说明\n\n正文。\n\n"
            "# 五、模型的建立与求解\n\n"
            "表1 变量说明\n\n"
            "| 变量 | 含义 | 单位 |\n| --- | --- | --- |\n| x | A产品数量 | 件 |\n"
            "# 六、模型的分析与检验\n\n正文。\n\n"
            "# 七、模型的评价、改进与推广\n\n正文。\n\n"
            "## 参考文献\n\n[1] 贾俊平. 统计学[M]. 北京: 中国人民大学出版社, 2018.\n\n"
            "# 附录\n\n"
            "## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
            "## 附录B 源程序代码\n\n```python\nprint('ok')\n```\n"
        )

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=["problem.py"],
        )

        self.assertTrue(report["checks"]["abstract"]["passed"])
        self.assertTrue(report["checks"]["keywords"]["passed"])
        self.assertTrue(report["checks"]["sections"]["passed"])
        self.assertTrue(report["checks"]["internal_paths"]["passed"])
        self.assertTrue(report["checks"]["tables"]["passed"])

    def test_code_block_hash_comments_do_not_pollute_heading_list(self):
        markdown = (
            "# 基于优化模型的生产方案研究\n\n"
            "## 摘要\n\n"
            "本文围绕生产优化问题建立线性规划模型，结合资源约束、利润目标和敏感性分析给出可复核的生产方案。"
            "模型首先对机器时间和人工时间进行约束刻画，随后通过目标函数求解最大利润，并在结果分析中讨论资源变化对利润的影响。"
            "结果表明，所给方案能够在约束范围内获得较高利润，同时机器时间增加会带来边际收益变化。\n\n"
            "关键词：线性规划；敏感性分析；生产优化；资源约束\n\n"
            "# 一、问题重述\n\n正文。\n\n"
            "# 二、问题分析\n\n正文。\n\n"
            "# 三、模型假设\n\n正文。\n\n"
            "# 四、符号说明\n\n正文。\n\n"
            "# 五、模型的建立与求解\n\n正文。\n\n"
            "# 六、模型的分析与检验\n\n正文。\n\n"
            "# 七、模型的评价、改进与推广\n\n正文。\n\n"
            "## 参考文献\n\n[1] 文献。\n\n"
            "# 附录\n\n"
            "## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
            "## 附录B 源程序代码\n\n"
            "```python\n"
            "# Cell 1\n"
            "# 1. 参数定义\n"
            "print('ok')\n"
            "```\n"
        )

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=["notebook.ipynb"],
        )

        headings = report["checks"]["sections"]["headings"]
        self.assertTrue(report["checks"]["sections"]["passed"])
        self.assertNotIn("Cell 1", headings)
        self.assertNotIn("1. 参数定义", headings)

    def test_wide_tables_inside_code_blocks_are_ignored(self):
        markdown = (
            "# 基于优化模型的生产方案研究\n\n"
            "## 摘要\n\n"
            "本文围绕生产优化问题建立线性规划模型，结合资源约束、利润目标和敏感性分析给出可复核的生产方案。"
            "模型首先对机器时间和人工时间进行约束刻画，随后通过目标函数求解最大利润，并在结果分析中讨论资源变化对利润的影响。"
            "结果表明，所给方案能够在约束范围内获得较高利润，同时机器时间增加会带来边际收益变化。\n\n"
            "关键词：线性规划；敏感性分析；生产优化；资源约束\n\n"
            "# 一、问题重述\n\n正文。\n\n"
            "# 二、问题分析\n\n正文。\n\n"
            "# 三、模型假设\n\n正文。\n\n"
            "# 四、符号说明\n\n正文。\n\n"
            "# 五、模型的建立与求解\n\n正文。\n\n"
            "# 六、模型的分析与检验\n\n正文。\n\n"
            "# 七、模型的评价、改进与推广\n\n正文。\n\n"
            "## 参考文献\n\n[1] 文献。\n\n"
            "# 附录\n\n"
            "## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
            "## 附录B 源程序代码\n\n"
            "```python\n"
            "print('| A | B | C | D | E | F | G |')\n"
            "print('| --- | --- | --- | --- | --- | --- | --- |')\n"
            "```\n"
        )

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=["problem.py"],
        )

        self.assertTrue(report["checks"]["tables"]["passed"])

    def test_short_numeric_seven_column_table_is_allowed(self):
        markdown = (
            "# 基于优化模型的生产方案研究\n\n"
            "## 摘要\n\n"
            "本文围绕生产优化问题建立线性规划模型，结合资源约束、利润目标和敏感性分析给出可复核的生产方案。"
            "模型首先对机器时间和人工时间进行约束刻画，随后通过目标函数求解最大利润，并在结果分析中讨论资源变化对利润的影响。"
            "结果表明，所给方案能够在约束范围内获得较高利润，同时机器时间增加会带来边际收益变化。\n\n"
            "关键词：线性规划；敏感性分析；生产优化；资源约束\n\n"
            "# 一、问题重述\n\n正文。\n\n"
            "# 二、问题分析\n\n正文。\n\n"
            "# 三、模型假设\n\n正文。\n\n"
            "# 四、符号说明\n\n正文。\n\n"
            "# 五、模型的建立与求解\n\n正文。\n\n"
            "# 六、模型的分析与检验\n\n正文。\n\n"
            "# 七、模型的评价、改进与推广\n\n正文。\n\n"
            "表1 角点利润比较\n\n"
            "| 角点编号 | x值 | y值 | 2x+y | x+2y | 40x+30y | 是否可行 |\n"
            "|:--------:|:---:|:---:|:----:|:----:|:-------:|:--------:|\n"
            "| 4 | 40 | 20 | 100 | 80 | 2200 | 是 |\n\n"
            "## 参考文献\n\n[1] 文献。\n\n"
            "# 附录\n\n"
            "## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
            "## 附录B 源程序代码\n\n```python\nprint('ok')\n```\n"
        )

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=["problem.py"],
        )

        self.assertTrue(report["checks"]["tables"]["passed"])

    def test_detects_missing_structure_path_leak_wide_table_and_unused_image(self):
        with tempfile.TemporaryDirectory() as work_dir:
            os.makedirs(os.path.join(work_dir, "figures"), exist_ok=True)
            with open(os.path.join(work_dir, "figures", "unused.png"), "wb") as f:
                f.write(b"png")

            markdown = (
                "# 草稿\n\n"
                "摘要太短。\n\n"
                "关键词：线性规划\n\n"
                "正文泄露路径 D:\\workspace\\MathModelAgent\\backend\\project\\work_dir\\task-1。\n\n"
                "| A指标说明 | B指标说明 | C指标说明 | D指标说明 | E指标说明 | F指标说明 | G指标说明 |\n"
                "| --- | --- | --- | --- | --- | --- | --- |\n"
                "| 该列包含较长的说明文本 | 该列包含较长的说明文本 | 该列包含较长的说明文本 | 该列包含较长的说明文本 | 该列包含较长的说明文本 | 该列包含较长的说明文本 | 该列包含较长的说明文本 |\n\n"
                "## 参考文献\n\n[1] 文献。\n\n"
                "# 附录\n\n"
                "## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
                "## 附录B 源程序代码\n\n```python\nprint('ok')\n```\n"
            )

            report = build_preflight_report(
                work_dir=work_dir,
                markdown=markdown,
                code_sources=["problem.py"],
            )

        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"]["abstract"]["passed"])
        self.assertFalse(report["checks"]["keywords"]["passed"])
        self.assertFalse(report["checks"]["sections"]["passed"])
        self.assertFalse(report["checks"]["internal_paths"]["passed"])
        self.assertFalse(report["checks"]["tables"]["passed"])
        self.assertFalse(report["checks"]["images"]["passed"])
        self.assertIn("figures/unused.png", report["checks"]["images"]["unused_generated"])
        self.assertTrue(report["checks"]["tables"]["wide_tables"])

    def test_internal_path_check_ignores_urls_and_fenced_code(self):
        markdown = (
            "# 基于优化模型的生产方案研究\n\n"
            "## 摘要\n\n"
            "本文围绕生产优化问题建立线性规划模型，结合资源约束、利润目标和敏感性分析给出可复核的生产方案。"
            "模型首先对机器时间和人工时间进行约束刻画，随后通过目标函数求解最大利润，并在结果分析中讨论资源变化对利润的影响。"
            "结果表明，所给方案能够在约束范围内获得较高利润，同时机器时间增加会带来边际收益变化。\n\n"
            "关键词：线性规划；生产优化；敏感性分析；资源约束\n\n"
            "正文引用 https://www.tug.org/texlive/ 作为外部资料链接。\n\n"
            "# 一、问题重述\n\n正文。\n\n"
            "# 二、问题分析\n\n正文。\n\n"
            "# 三、模型假设\n\n正文。\n\n"
            "# 四、符号说明\n\n正文。\n\n"
            "# 五、模型的建立与求解\n\n正文。\n\n"
            "# 六、模型的分析与检验\n\n正文。\n\n"
            "# 七、模型的评价、改进与推广\n\n正文。\n\n"
            "## 参考文献\n\n[1] 文献。\n\n"
            "# 附录\n\n"
            "## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
            "## 附录B 源程序代码\n\n"
            "```python\n"
            "path = 'D:\\\\workspace\\\\MathModelAgent\\\\backend\\\\project\\\\work_dir\\\\task-1'\n"
            "print(path)\n"
            "```\n"
        )

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=["problem.py"],
        )

        self.assertTrue(report["checks"]["internal_paths"]["passed"])

    def test_submission_identity_fields_fail_preflight(self):
        markdown = (
            "# 基于优化模型的生产方案研究\n\n"
            "## 摘要\n\n"
            "本文围绕生产优化问题建立线性规划模型，结合资源约束、利润目标和敏感性分析给出可复核的生产方案。"
            "模型首先对机器时间和人工时间进行约束刻画，随后通过目标函数求解最大利润，并在结果分析中讨论资源变化对利润的影响。"
            "结果表明，所给方案能够在约束范围内获得较高利润，同时机器时间增加会带来边际收益变化。\n\n"
            "关键词：线性规划；生产优化；敏感性分析；资源约束\n\n"
            "参赛队号：12345\n\n"
            "# 一、问题重述\n\n正文。\n\n"
            "# 二、问题分析\n\n正文。\n\n"
            "# 三、模型假设\n\n正文。\n\n"
            "# 四、符号说明\n\n正文。\n\n"
            "# 五、模型的建立与求解\n\n正文。\n\n"
            "# 六、模型的分析与检验\n\n正文。\n\n"
            "# 七、模型的评价、改进与推广\n\n正文。\n\n"
            "## 参考文献\n\n[1] 文献。\n\n"
            "# 附录\n\n"
            "## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
            "## 附录B 源程序代码\n\n```python\nprint('ok')\n```\n"
        )

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=["problem.py"],
        )

        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"]["submission_anonymity"]["passed"])
        self.assertIn("参赛队号", report["checks"]["submission_anonymity"]["matches"])

    def test_tilde_fenced_code_blocks_are_ignored_by_preflight(self):
        markdown = (
            "# 基于优化模型的生产方案研究\n\n"
            "## 摘要\n\n"
            "本文围绕生产优化问题建立线性规划模型，结合资源约束、利润目标和敏感性分析给出可复核的生产方案。"
            "模型首先对机器时间和人工时间进行约束刻画，随后通过目标函数求解最大利润，并在结果分析中讨论资源变化对利润的影响。"
            "结果表明，所给方案能够在约束范围内获得较高利润，同时机器时间增加会带来边际收益变化。\n\n"
            "关键词：线性规划；生产优化；敏感性分析；资源约束\n\n"
            "# 一、问题重述\n\n正文。\n\n"
            "# 二、问题分析\n\n正文。\n\n"
            "# 三、模型假设\n\n正文。\n\n"
            "# 四、符号说明\n\n正文。\n\n"
            "# 五、模型的建立与求解\n\n正文。\n\n"
            "# 六、模型的分析与检验\n\n正文。\n\n"
            "# 七、模型的评价、改进与推广\n\n正文。\n\n"
            "## 参考文献\n\n[1] 文献。\n\n"
            "# 附录\n\n"
            "## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
            "## 附录B 源程序代码\n\n"
            "~~~python\n"
            "# 这个标题不应进入论文大纲\n"
            "path = 'D:\\\\workspace\\\\MathModelAgent\\\\backend\\\\project\\\\work_dir\\\\task-1'\n"
            "print('| A | B | C | D | E | F | G |')\n"
            "print('| --- | --- | --- | --- | --- | --- | --- |')\n"
            "~~~\n"
        )

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=["problem.py"],
        )

        self.assertTrue(report["checks"]["internal_paths"]["passed"])
        self.assertTrue(report["checks"]["sections"]["passed"])
        self.assertNotIn("这个标题不应进入论文大纲", report["checks"]["sections"]["headings"])
        self.assertTrue(report["checks"]["tables"]["passed"])

    def test_missing_keywords_only_is_conditional_pass(self):
        markdown = (
            "# 基于优化模型的生产方案研究\n\n"
            "## 摘要\n\n"
            "本文围绕生产优化问题建立线性规划模型，结合资源约束、利润目标和敏感性分析给出可复核的生产方案。"
            "模型首先对机器时间和人工时间进行约束刻画，随后通过目标函数求解最大利润，并在结果分析中讨论资源变化对利润的影响。"
            "结果表明，所给方案能够在约束范围内获得较高利润，同时机器时间增加会带来边际收益变化。\n\n"
            "# 一、问题重述\n\n正文。\n\n"
            "# 二、问题分析\n\n正文。\n\n"
            "# 三、模型假设\n\n正文。\n\n"
            "# 四、符号说明\n\n正文。\n\n"
            "# 五、模型的建立与求解\n\n正文。\n\n"
            "# 六、模型的分析与检验\n\n正文。\n\n"
            "# 七、模型的评价、改进与推广\n\n正文。\n\n"
            "## 参考文献\n\n[1] 文献。\n\n"
            "# 附录\n\n"
            "## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
            "## 附录B 源程序代码\n\n```python\nprint('ok')\n```\n"
        )

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=["problem.py"],
        )

        self.assertEqual(report["status"], "CONDITIONAL_PASS")
        self.assertEqual(report["checks"]["keywords"]["severity"], "conditional")

    def test_missing_abstract_or_core_sections_fail(self):
        markdown = (
            "# 草稿\n\n"
            "关键词：线性规划；生产优化；敏感性分析\n\n"
            "# 一、问题重述\n\n正文。\n\n"
            "## 参考文献\n\n[1] 文献。\n\n"
            "# 附录\n\n"
            "## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
            "## 附录B 源程序代码\n\n```python\nprint('ok')\n```\n"
        )

        report = build_preflight_report(
            work_dir=tempfile.gettempdir(),
            markdown=markdown,
            code_sources=["problem.py"],
        )

        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["checks"]["abstract"]["severity"], "fail")
        self.assertEqual(report["checks"]["sections"]["severity"], "fail")

    def test_unused_generated_image_only_is_conditional_pass(self):
        with tempfile.TemporaryDirectory() as work_dir:
            os.makedirs(os.path.join(work_dir, "figures"), exist_ok=True)
            with open(os.path.join(work_dir, "figures", "exploratory.png"), "wb") as f:
                f.write(b"png")

            markdown = (
                "# 基于优化模型的生产方案研究\n\n"
                "## 摘要\n\n"
                "本文围绕生产优化问题建立线性规划模型，结合资源约束、利润目标和敏感性分析给出可复核的生产方案。"
                "模型首先对机器时间和人工时间进行约束刻画，随后通过目标函数求解最大利润，并在结果分析中讨论资源变化对利润的影响。"
                "结果表明，所给方案能够在约束范围内获得较高利润，同时机器时间增加会带来边际收益变化。\n\n"
                "关键词：线性规划；生产优化；敏感性分析；资源约束\n\n"
                "# 一、问题重述\n\n正文。\n\n"
                "# 二、问题分析\n\n正文。\n\n"
                "# 三、模型假设\n\n正文。\n\n"
                "# 四、符号说明\n\n正文。\n\n"
                "# 五、模型的建立与求解\n\n正文。\n\n"
                "# 六、模型的分析与检验\n\n正文。\n\n"
                "# 七、模型的评价、改进与推广\n\n正文。\n\n"
                "## 参考文献\n\n[1] 文献。\n\n"
                "# 附录\n\n"
                "## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
                "## 附录B 源程序代码\n\n```python\nprint('ok')\n```\n"
            )

            report = build_preflight_report(
                work_dir=work_dir,
                markdown=markdown,
                code_sources=["problem.py"],
            )

        self.assertEqual(report["status"], "CONDITIONAL_PASS")
        self.assertEqual(report["checks"]["images"]["severity"], "conditional")
        self.assertIn("figures/exploratory.png", report["checks"]["images"]["unused_generated"])

    def test_support_material_image_is_accounted_without_inline_reference(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "exploratory.png"), "wb") as f:
                f.write(b"png")

            markdown = (
                "# 基于优化模型的生产方案研究\n\n"
                "## 摘要\n\n"
                "本文围绕生产优化问题建立线性规划模型，结合资源约束、利润目标和敏感性分析给出可复核的生产方案。"
                "模型首先对机器时间和人工时间进行约束刻画，随后通过目标函数求解最大利润，并在结果分析中讨论资源变化对利润的影响。"
                "结果表明，所给方案能够在约束范围内获得较高利润，同时机器时间增加会带来边际收益变化。\n\n"
                "关键词：线性规划；生产优化；敏感性分析；资源约束\n\n"
                "# 一、问题重述\n\n正文。\n\n"
                "# 二、问题分析\n\n正文。\n\n"
                "# 三、模型假设\n\n正文。\n\n"
                "# 四、符号说明\n\n正文。\n\n"
                "# 五、模型的建立与求解\n\n正文。\n\n"
                "# 六、模型的分析与检验\n\n正文。\n\n"
                "# 七、模型的评价、改进与推广\n\n正文。\n\n"
                "## 参考文献\n\n[1] 文献。\n\n"
                "# 附录\n\n"
                "## 附录A 支撑材料文件列表\n\n"
                "| 文件名 | 类型 |\n"
                "| --- | --- |\n"
                "| exploratory.png | 图片文件 |\n\n"
                "## 附录B 源程序代码\n\n```python\nprint('ok')\n```\n"
            )

            report = build_preflight_report(
                work_dir=work_dir,
                markdown=markdown,
                code_sources=["problem.py"],
            )

        self.assertEqual(report["checks"]["images"]["unused_generated"], [])
        self.assertEqual(report["checks"]["images"]["severity"], "pass")


class TestContestCriticalPreflightGates(unittest.TestCase):
    def test_required_modeling_decision_must_have_human_approval_evidence(self):
        with tempfile.TemporaryDirectory() as work_dir:
            plan = {"questions_solution": {"ques1": "建立可执行模型。"}}
            with open(
                os.path.join(work_dir, "task_request.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump({"require_model_review": True}, handle)
            with open(
                os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(plan, handle)

            missing = build_preflight_report(work_dir, "正文", code_sources=[])

            with open(
                os.path.join(work_dir, "modeling_decision.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    {
                        "gate_enabled": True,
                        "status": "approved",
                        "review": {
                            "approved": True,
                            "approved_at": "2026-08-07T20:00:00",
                        },
                        "modeler_response": plan,
                        "modeler_plan_sha256": _canonical_json_sha256(plan),
                    },
                    handle,
                )
            with open(
                os.path.join(work_dir, "modeling_decision.md"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("# 建模方案人工审批\n\n已审批。\n")

            approved = build_preflight_report(work_dir, "正文", code_sources=[])

        self.assertFalse(missing["checks"]["modeling_decision"]["passed"])
        self.assertTrue(approved["checks"]["modeling_decision"]["passed"])

    def test_modeling_approval_is_invalid_when_current_plan_differs(self):
        approved_plan = {"questions_solution": {"ques1": "已审批方案。"}}
        current_plan = {"questions_solution": {"ques1": "审批后替换的另一方案。"}}
        with tempfile.TemporaryDirectory() as work_dir:
            with open(
                os.path.join(work_dir, "task_request.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump({"require_model_review": True}, handle)
            with open(
                os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(current_plan, handle)
            with open(
                os.path.join(work_dir, "modeling_decision.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    {
                        "status": "approved",
                        "gate_enabled": True,
                        "modeler_response": approved_plan,
                        "modeler_plan_sha256": _canonical_json_sha256(approved_plan),
                        "review": {
                            "approved": True,
                            "approved_at": "2026-08-07T20:00:00",
                        },
                    },
                    handle,
                )
            with open(
                os.path.join(work_dir, "modeling_decision.md"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("# 建模方案人工审批\n")

            report = build_preflight_report(work_dir, "正文", code_sources=[])

        check = report["checks"]["modeling_decision"]
        self.assertFalse(check["passed"])
        self.assertFalse(check["approved_plan_matches_current"])

    def test_modeling_approval_is_invalid_when_declared_hash_is_corrupt(self):
        plan = {"questions_solution": {"ques1": "已审批方案。"}}
        with tempfile.TemporaryDirectory() as work_dir:
            with open(
                os.path.join(work_dir, "task_request.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump({"require_model_review": True}, handle)
            with open(
                os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(plan, handle)
            with open(
                os.path.join(work_dir, "modeling_decision.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(
                    {
                        "status": "approved",
                        "gate_enabled": True,
                        "modeler_response": plan,
                        "modeler_plan_sha256": "0" * 64,
                        "review": {
                            "approved": True,
                            "approved_at": "2026-08-07T20:00:00",
                        },
                    },
                    handle,
                )
            with open(
                os.path.join(work_dir, "modeling_decision.md"), "w", encoding="utf-8"
            ) as handle:
                handle.write("# 建模方案人工审批\n")

            report = build_preflight_report(work_dir, "正文", code_sources=[])

        check = report["checks"]["modeling_decision"]
        self.assertFalse(check["passed"])
        self.assertFalse(check["declared_hash_matches_approved_payload"])

    def test_approved_high_pressure_plan_is_rechecked_against_current_contract(self):
        problem = (
            "高压油管问题1中喷油嘴B处向外喷油的速率如图2所示。"
            "问题2中一个喷油周期内针阀升程与时间的关系由附件2给出。"
            "问题3增加第二个喷油嘴，并调整喷油器和供油策略。"
        )
        plan = {
            "questions_solution": {
                "ques1": "问题一使用题面图2喷油速率。",
                "ques2": "问题二使用附件2针阀升程计算喷嘴有效面积。",
                "ques3": "沿用问题2所有参数及模型，两个喷油嘴默认同步。",
            }
        }
        with tempfile.TemporaryDirectory() as work_dir:
            with open(
                os.path.join(work_dir, "task_request.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(
                    {"require_model_review": True, "ques_all": problem},
                    handle,
                    ensure_ascii=False,
                )
            for filename, payload in (
                ("modeler_plan.json", plan),
                (
                    "modeling_decision.json",
                    {
                        "status": "approved",
                        "gate_enabled": True,
                        "modeler_response": plan,
                        "modeler_plan_sha256": _canonical_json_sha256(plan),
                        "review": {
                            "approved": True,
                            "approved_at": "2026-08-07T20:00:00",
                        },
                    },
                ),
            ):
                with open(
                    os.path.join(work_dir, filename), "w", encoding="utf-8"
                ) as handle:
                    json.dump(payload, handle, ensure_ascii=False)
            with open(
                os.path.join(work_dir, "modeling_decision.md"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("# 建模方案人工审批\n")

            report = build_preflight_report(work_dir, "正文", code_sources=[])

        check = report["checks"]["modeling_decision"]
        self.assertFalse(check["passed"])
        self.assertTrue(check["approved_plan_matches_current"])
        self.assertFalse(check["current_plan_contract_valid"])
        self.assertTrue(
            any("同步/错相" in item for item in check["plan_missing_requirements"])
        )

    def test_cumcm_ai_disclosure_requires_position_pdf_and_support_listing(self):
        markdown = (
            "## AI工具使用声明\n\n"
            "本任务使用AI辅助，最终提交前由参赛队员复核。\n\n"
            "## 参考文献\n\n"
            "[1] 文献。\n\n"
            "| 文件名 | 类型 |\n"
            "| --- | --- |\n"
            "| AI工具使用详情.pdf | AI工具使用详情 |\n"
        )
        with tempfile.TemporaryDirectory() as work_dir:
            missing_pdf = build_preflight_report(
                work_dir,
                markdown,
                code_sources=[],
                export_profile="cumcm2026",
            )
            with open(
                os.path.join(work_dir, "AI工具使用详情.pdf"), "wb"
            ) as handle:
                handle.write(b"%PDF-1.4\n" + b"x" * 200)
            invalid_pdf = build_preflight_report(
                work_dir,
                markdown,
                code_sources=[],
                export_profile="cumcm2026",
            )
            import fitz

            valid_pdf_path = os.path.join(work_dir, "AI工具使用详情.pdf")
            document = fitz.open()
            page = document.new_page()
            page.insert_text((72, 72), "AI usage details")
            document.save(valid_pdf_path)
            document.close()
            complete = build_preflight_report(
                work_dir,
                markdown,
                code_sources=[],
                export_profile="cumcm2026",
            )

        self.assertFalse(missing_pdf["checks"]["ai_disclosure"]["passed"])
        self.assertFalse(invalid_pdf["checks"]["ai_disclosure"]["passed"])
        self.assertTrue(complete["checks"]["ai_disclosure"]["passed"])

    def test_reproducibility_claims_require_current_hash_bound_replay_report(self):
        markdown = "隔离副本独立重跑后逐字节一致，数值复现PASS。"
        with tempfile.TemporaryDirectory() as work_dir:
            result_path = os.path.join(work_dir, "result.csv")
            with open(result_path, "wb") as handle:
                handle.write(b"x,y\n1,2\n")
            digest = hashlib.sha256(b"x,y\n1,2\n").hexdigest()

            missing = build_preflight_report(work_dir, markdown, code_sources=[])
            with open(
                os.path.join(work_dir, "independent_replay_report.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    {
                        "byte_reproducibility": {"status": "PASS"},
                        "numerical_reproducibility": {"status": "PASS"},
                        "files": [
                            {
                                "path": "result.csv",
                                "reference_sha256": digest,
                                "byte_match": True,
                                "numerical_match": True,
                            }
                        ],
                    },
                    handle,
                )
            current = build_preflight_report(work_dir, markdown, code_sources=[])
            with open(result_path, "ab") as handle:
                handle.write(b"2,3\n")
            stale = build_preflight_report(work_dir, markdown, code_sources=[])

        self.assertFalse(missing["checks"]["reproducibility_claims"]["passed"])
        self.assertTrue(current["checks"]["reproducibility_claims"]["passed"])
        self.assertFalse(stale["checks"]["reproducibility_claims"]["passed"])

    def test_numerical_reproducibility_claim_rejects_stale_reference_file(self):
        markdown = "数值复现PASS，最大绝对差为0。"
        with tempfile.TemporaryDirectory() as work_dir:
            result_path = os.path.join(work_dir, "result.csv")
            original = b"x,y\n1,2\n"
            with open(result_path, "wb") as handle:
                handle.write(original)
            digest = hashlib.sha256(original).hexdigest()
            with open(
                os.path.join(work_dir, "independent_replay_report.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    {
                        "byte_reproducibility": {"status": "FAIL"},
                        "numerical_reproducibility": {"status": "PASS"},
                        "files": [
                            {
                                "path": "result.csv",
                                "reference_sha256": digest,
                                "byte_match": False,
                                "numerical_match": True,
                            }
                        ],
                    },
                    handle,
                )
            current = build_preflight_report(work_dir, markdown, code_sources=[])
            with open(result_path, "ab") as handle:
                handle.write(b"2,3\n")
            stale = build_preflight_report(work_dir, markdown, code_sources=[])

        self.assertTrue(current["checks"]["reproducibility_claims"]["passed"])
        self.assertFalse(stale["checks"]["reproducibility_claims"]["passed"])


class TestProblemAlignmentGate(unittest.TestCase):
    def test_high_pressure_sections_enforce_source_and_phase_alignment(self):
        problem = (
            "高压油管问题1中喷油嘴B处向外喷油的速率如图2所示。"
            "问题2中针阀升程与时间的关系由附件2给出。"
            "问题3增加第二个喷油嘴，并调整喷油器和供油策略。"
        )
        wrong_markdown = (
            "## 5.1 问题一\n\n使用附件2针阀升程计算喷油流量。\n\n"
            "## 5.2 问题二\n\n使用附件2针阀升程计算有效面积。\n\n"
            "## 5.3 问题三\n\n两个喷油嘴默认同步运行。\n"
        )
        correct_markdown = (
            "## 5.1 问题一\n\n问题一的喷油流出速率Q_out读取题面图2。\n\n"
            "## 5.2 问题二\n\n使用附件2针阀升程计算喷嘴有效面积。\n\n"
            "## 5.3 问题三\n\n沿用问题二所有参数及模型，比较同步与50 ms错相方案，并按联合目标值选择策略。\n"
        )
        with tempfile.TemporaryDirectory() as work_dir:
            with open(
                os.path.join(work_dir, "task_request.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump({"ques_all": problem}, handle, ensure_ascii=False)
            wrong = build_preflight_report(work_dir, wrong_markdown, code_sources=[])
            correct = build_preflight_report(work_dir, correct_markdown, code_sources=[])

        wrong_check = wrong["checks"]["problem_alignment"]
        self.assertFalse(wrong_check["passed"])
        self.assertIn(
            "5.1 把附件2针阀升程曲线作为问题一喷油速率来源，违反题面图2数据源约束。",
            wrong_check["issues"],
        )
        self.assertIn(
            "5.3 未比较同步与至少一种错相/错峰双喷嘴时序策略，也未给出可复核的选择依据。",
            wrong_check["issues"],
        )
        self.assertTrue(
            correct["checks"]["problem_alignment"]["passed"],
            correct["checks"]["problem_alignment"]["issues"],
        )

    def test_high_pressure_alignment_rejects_negated_or_substituted_sources(self):
        problem = (
            "高压油管问题1中喷油嘴B处向外喷油的速率如图2所示。"
            "问题2中针阀升程与时间的关系由附件2给出。"
            "问题3增加第二个喷油嘴，并调整喷油器和供油策略。"
        )
        markdown = (
            "## 5.1 问题一\n\n图2不采用，Q_out喷油流量由拟合外推。\n\n"
            "## 5.2 问题二\n\n附件2不使用，针阀升程由自建曲线计算有效面积。\n\n"
            "## 5.3 问题三\n\n附件2未使用，喷嘴流量改由经验式给出；比较同步与50 ms错相方案。\n"
        )
        with tempfile.TemporaryDirectory() as work_dir:
            with open(
                os.path.join(work_dir, "task_request.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump({"ques_all": problem}, handle, ensure_ascii=False)
            report = build_preflight_report(work_dir, markdown, code_sources=[])

        check = report["checks"]["problem_alignment"]
        self.assertFalse(check["passed"])
        self.assertIn("5.1 未明确把题面图2作为问题一喷油流出速率的数据源。", check["issues"])
        self.assertIn("5.2 未明确使用附件2针阀升程计算喷嘴流量/有效面积。", check["issues"])
        self.assertIn("5.3 未明确使用附件2针阀升程模型，或正向继承已锁定的问题二模型。", check["issues"])

    def test_optical_sections_must_follow_problem_order_and_sample_relationship(self):
        problem = (
            "问题1 如果考虑只有一次反射、透射，建立模型。"
            "问题2 使用附件1和附件2。"
            "问题3 研究多光束干涉并使用附件3和附件4。"
        )
        wrong_markdown = (
            "## 5.1 问题一\n\n本文采用Airy多光束模型进行厚度反演，比较双光束误差。\n\n"
            "## 5.2 问题二\n\n使用附件3和附件4的硅数据。\n\n"
            "## 5.3 问题三\n\n建立多光束判据。\n\n"
            "碳化硅两片样品的结果一致。\n"
        )
        correct_markdown = (
            "## 5.1 问题一\n\n建立两束反射光的双光束模型。\n\n"
            "## 5.2 问题二\n\n附件1和附件2是同一碳化硅晶圆在10°和15°下的测量。\n\n"
            "## 5.3 问题三\n\n对附件3和附件4建立多光束模型。\n"
        )
        with tempfile.TemporaryDirectory() as work_dir:
            with open(
                os.path.join(work_dir, "task_request.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump({"ques_all": problem}, handle, ensure_ascii=False)
            wrong = build_preflight_report(work_dir, wrong_markdown, code_sources=[])
            correct = build_preflight_report(work_dir, correct_markdown, code_sources=[])

        wrong_check = wrong["checks"]["problem_alignment"]
        self.assertFalse(wrong_check["passed"])
        self.assertGreaterEqual(len(wrong_check["issues"]), 4)
        self.assertTrue(correct["checks"]["problem_alignment"]["passed"])

    def test_latex_incident_angles_are_recognized(self):
        """论文用 LaTeX ``$10^\\circ$``/``$15^{\\circ}$`` 声明入射角时不应被误判为缺失。"""
        problem = (
            "问题1 如果考虑只有一次反射、透射，建立模型。"
            "问题2 使用附件1和附件2。"
            "问题3 研究多光束干涉并使用附件3和附件4。"
        )
        latex_markdown = (
            "## 5.1 问题一\n\n建立两束反射光的双光束模型。\n\n"
            "## 5.2 问题二\n\n附件1和附件2是同一碳化硅晶圆在 $10^\\circ$ 与 $15^{\\circ}$ 下的测量。\n\n"
            "## 5.3 问题三\n\n对附件3和附件4建立多光束模型。\n"
        )
        with tempfile.TemporaryDirectory() as work_dir:
            with open(
                os.path.join(work_dir, "task_request.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump({"ques_all": problem}, handle, ensure_ascii=False)
            report = build_preflight_report(work_dir, latex_markdown, code_sources=[])

        check = report["checks"]["problem_alignment"]
        self.assertTrue(check["passed"])
        self.assertNotIn(
            "5.2 未明确使用附件1/2对应的10°与15°入射角。", check["issues"]
        )

    def test_ques3_written_as_carbide_sensitivity_analysis_is_rejected(self):
        """第11轮真实故障复现：Writer 把 5.3 写成碳化硅 Bootstrap 敏感性分析，
        没有用附件3/4 对硅晶圆做多光束判定 → 必须被 problem_alignment 拦下。
        修复后正确的 5.3（用附件3/4 硅晶圆多光束）必须通过。"""
        problem = (
            "问题1 如果考虑只有一次反射、透射，建立模型。"
            "问题2 使用附件1和附件2。"
            "问题3 研究多光束干涉并使用附件3和附件4。"
        )
        # 跑题版：5.3 整节只做碳化硅（附件1/2）Bootstrap 敏感性，未触及附件3/4 硅晶圆
        carbide_sensitivity_markdown = (
            "## 5.1 问题一\n\n建立两束反射光的双光束模型。\n\n"
            "## 5.2 问题二\n\n附件1和附件2是同一碳化硅晶圆在10°和15°下的测量。\n\n"
            "## 5.3 问题三\n\n"
            "问题三可视为厚度反演结果的稳定性分析问题，重点考察碳化硅双角度联合"
            "拟合结果对观测数据扰动的敏感程度。采用Bootstrap重采样方法对联合反演"
            "结果进行不确定性评估，设附件1和附件2中的有效观测数据分别重采样。\n"
        )
        # 正确版：5.3 用附件3/4 硅晶圆做多光束判定
        correct_markdown = (
            "## 5.1 问题一\n\n建立两束反射光的双光束模型。\n\n"
            "## 5.2 问题二\n\n附件1和附件2是同一碳化硅晶圆在10°和15°下的测量。\n\n"
            "## 5.3 问题三\n\n"
            "对附件3和附件4的同一块硅晶圆片建立多光束干涉模型，推导多光束必要条件，"
            "判定是否出现多光束干涉并给出硅外延层厚度。\n"
        )
        with tempfile.TemporaryDirectory() as work_dir:
            with open(
                os.path.join(work_dir, "task_request.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump({"ques_all": problem}, handle, ensure_ascii=False)
            wrong = build_preflight_report(
                work_dir, carbide_sensitivity_markdown, code_sources=[]
            )
            correct = build_preflight_report(work_dir, correct_markdown, code_sources=[])

        wrong_check = wrong["checks"]["problem_alignment"]
        self.assertFalse(wrong_check["passed"])
        self.assertIn(
            "5.3 未使用附件3/4完成多光束判定和硅外延层计算。", wrong_check["issues"]
        )
        self.assertTrue(
            correct["checks"]["problem_alignment"]["passed"],
            correct["checks"]["problem_alignment"]["issues"],
        )


class TestEscapePipesInTableMathCells(unittest.TestCase):
    """验证表格单元格内 LaTeX 绝对值竖线被转义，避免破坏表格列数。"""

    def test_absolute_value_pipe_in_table_cell_is_escaped(self):
        markdown = (
            "| 符号 | 含义 | 单位 |\n"
            "|---|---|---|\n"
            "| $\\rho$ | 往返反射振幅乘积，$\\rho=|r_1r_2|$ | — |\n"
            "| $R_i$ | 实测反射率 | $\\%$ |\n"
        )
        fixed, count = escape_pipes_in_table_math_cells(markdown)
        # 两个裸竖线应被转义为 \vert。
        self.assertEqual(count, 2)
        self.assertNotIn("|r_1r_2|", fixed)
        self.assertIn(r"\vert", fixed)
        # 每个表格行去掉转义后的结构列数应一致（均为 3 列 = 4 个结构分隔符）。
        for line in fixed.splitlines():
            if line.startswith("|"):
                self.assertEqual(line.count("|"), 4, msg=line)

    def test_structural_pipes_and_non_table_text_untouched(self):
        markdown = (
            "正文里的 $|x|$ 不是表格，不应被改写。\n\n"
            "| A | B |\n"
            "|---|---|\n"
            "| 1 | 2 |\n"
        )
        fixed, count = escape_pipes_in_table_math_cells(markdown)
        self.assertEqual(count, 0)
        self.assertIn("正文里的 $|x|$ 不是表格", fixed)

    def test_preflight_table_passes_after_escape(self):
        with tempfile.TemporaryDirectory() as work_dir:
            markdown = (
                "# 标题\n\n"
                "## 四、符号说明\n\n"
                "| 符号 | 含义 | 单位 |\n"
                "|---|---|---|\n"
                "| $\\rho$ | 乘积 $\\rho=|r_1r_2|$ | — |\n"
                "| $d$ | 厚度 | $\\mu m$ |\n\n"
            )
            report = build_preflight_report(
                work_dir,
                escape_pipes_in_table_math_cells(markdown)[0],
                code_sources=[],
            )
        self.assertTrue(report["checks"]["markdown_structure"]["passed"])


class TestEditorialQualityPreflight(unittest.TestCase):
    """Internal editorial policy is opt-in and explicitly non-official."""

    def test_abstract_count_excludes_following_keywords(self):
        markdown = (
            "## 摘要\n\n"
            + "甲" * 119
            + "\n\n关键词：线性规划；敏感性；生产；优化\n\n"
            + "# 一、问题重述\n\n正文。\n"
        )

        report = build_preflight_report(
            tempfile.gettempdir(), markdown, code_sources=[]
        )

        abstract = report["checks"]["abstract"]
        self.assertEqual(abstract["char_count"], 119)
        self.assertFalse(abstract["passed"])

    def test_require_references_cannot_be_bypassed_by_disabling_style_check(self):
        report = build_preflight_report(
            tempfile.gettempdir(),
            "## 摘要\n\n正文。\n\n关键词：甲；乙；丙\n\n# 一、问题重述\n\n正文。",
            code_sources=[],
            editorial_policy={
                "base": "cumcm_formal",
                "min_body_chars": 0,
                "min_result_figures": 0,
                "min_result_tables": 0,
                "min_result_figures_per_question": 0,
                "min_result_tables_per_question": 0,
                "require_asset_source_trace": False,
                "min_abstract_paragraphs": 0,
                "require_references": True,
                "require_reference_style": False,
            },
        )

        editorial = report["checks"]["editorial_quality"]
        self.assertFalse(editorial["passed"])
        self.assertIn("参考文献缺失、编号顺序或格式不符合要求", editorial["failures"])

    def test_formal_editorial_policy_requires_result_assets_per_question(self):
        markdown = (
            "## 摘要\n\n" + "甲" * 120 + "\n\n"
            "关键词：线性规划；敏感性；生产；优化\n\n"
            "# 一、问题重述\n\n题目包含两个问题。\n\n"
            "## 问题一结果分析\n\n图1 展示问题一的优化结果。\n\n"
            "![问题一优化结果图](q1_result.png)\n\n"
            "表1 问题一优化结果\n\n"
            "| 指标 | 结果 |\n| --- | --- |\n| 利润 | 2200 |\n"
        )

        report = build_preflight_report(
            tempfile.gettempdir(),
            markdown,
            code_sources=[],
            declared_problem_count=2,
            editorial_policy={
                "base": "cumcm_formal",
                "min_body_chars": 0,
                "min_abstract_paragraphs": 0,
                "require_references": False,
                "require_reference_style": False,
            },
        )

        editorial = report["checks"]["editorial_quality"]
        self.assertFalse(editorial["passed"])
        self.assertTrue(editorial["enforced"])
        self.assertFalse(editorial["official_rule"])
        self.assertEqual(editorial["result_assets"]["figure_count"], 1)
        self.assertEqual(editorial["result_assets"]["table_count"], 1)
        self.assertEqual(editorial["missing_questions"], [2])
        self.assertEqual(editorial["severity"], "fail")

    def test_formal_editorial_policy_flags_missing_result_figure_and_table(self):
        markdown = (
            "## 摘要\n\n" + "甲" * 120 + "\n\n"
            "关键词：线性规划；敏感性；生产；优化\n\n"
            "# 一、问题重述\n\n题目包含一个问题。\n\n"
            "## 问题一结果分析\n\n仅给出文字结论，没有图表。\n"
        )

        report = build_preflight_report(
            tempfile.gettempdir(),
            markdown,
            code_sources=[],
            declared_problem_count=1,
            editorial_policy={
                "base": "cumcm_formal",
                "min_body_chars": 0,
                "min_abstract_paragraphs": 0,
                "require_references": False,
                "require_reference_style": False,
            },
        )

        editorial = report["checks"]["editorial_quality"]
        self.assertEqual(editorial["result_assets"]["figure_count"], 0)
        self.assertEqual(editorial["result_assets"]["table_count"], 0)
        self.assertEqual(editorial["missing_figure_questions"], [1])
        self.assertEqual(editorial["missing_table_questions"], [1])

    def test_smoke_policy_reports_gaps_without_failing_editorial_gate(self):
        markdown = "## 摘要\n\n" + "甲" * 120 + "\n\n关键词：甲；乙；丙\n"

        report = build_preflight_report(
            tempfile.gettempdir(),
            markdown,
            code_sources=[],
            declared_problem_count=2,
            editorial_policy="smoke",
        )

        editorial = report["checks"]["editorial_quality"]
        self.assertTrue(editorial["passed"])
        self.assertFalse(editorial["quality_passed"])
        self.assertFalse(editorial["enforced"])
        self.assertEqual(editorial["severity"], "info")

    def test_formal_editorial_policy_requires_source_hash_manifest(self):
        with tempfile.TemporaryDirectory() as work_dir:
            image_path = os.path.join(work_dir, "q1_result.png")
            with open(image_path, "wb") as handle:
                handle.write(b"not a rendered image; editorial trace fixture")
            markdown = (
                "## 摘要\n\n" + "甲" * 120 + "\n\n"
                "关键词：线性规划；敏感性；生产；优化\n\n"
                "## 问题一结果分析\n\n"
                "![问题一结果图](q1_result.png)\n\n"
                "表1 问题一结果\n\n"
                "| 指标 | 结果 |\n| --- | --- |\n| 利润 | 2200 |\n"
            )
            report = build_preflight_report(
                work_dir,
                markdown,
                code_sources=[],
                declared_problem_count=1,
                editorial_policy={
                    "base": "cumcm_formal",
                    "min_body_chars": 0,
                    "min_abstract_paragraphs": 0,
                    "require_references": False,
                    "require_reference_style": False,
                },
            )

        trace = report["checks"]["editorial_quality"]["asset_source_trace"]
        self.assertFalse(trace["passed"])
        self.assertIn("缺少 paper_assets_manifest.json", trace["errors"])

    def test_formal_editorial_policy_accepts_matching_asset_source_hashes(self):
        with tempfile.TemporaryDirectory() as work_dir:
            image_path = os.path.join(work_dir, "q1_result.png")
            source_path = os.path.join(work_dir, "ques1_result.csv")
            with open(image_path, "wb") as handle:
                handle.write(b"not a rendered image; editorial trace fixture")
            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write("metric,value\nduration,1.0\n")
            with open(source_path, "rb") as handle:
                source_hash = hashlib.sha256(handle.read()).hexdigest()
            with open(
                os.path.join(work_dir, "paper_assets_manifest.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    {
                        "figures": [{
                            "path": "q1_result.png",
                            "questions": ["ques1"],
                            "source_paths": ["ques1_result.csv"],
                            "source_sha256": {"ques1_result.csv": source_hash},
                        }],
                        "tables": [{
                            "id": "table_q1",
                            "questions": ["ques1"],
                            "source_paths": ["ques1_result.csv"],
                            "source_sha256": {"ques1_result.csv": source_hash},
                        }],
                    },
                    handle,
                )
            markdown = (
                "## 摘要\n\n" + "甲" * 120 + "\n\n"
                "关键词：线性规划；敏感性；生产；优化\n\n"
                "## 问题一结果分析\n\n"
                "![问题一结果图](q1_result.png)\n\n"
                "表1 问题一结果\n\n"
                "| 指标 | 结果 |\n| --- | --- |\n| 利润 | 2200 |\n"
            )
            report = build_preflight_report(
                work_dir,
                markdown,
                code_sources=[],
                declared_problem_count=1,
                editorial_policy={
                    "base": "cumcm_formal",
                    "min_body_chars": 0,
                    "min_abstract_paragraphs": 0,
                    "require_references": False,
                    "require_reference_style": False,
                },
            )

        editorial = report["checks"]["editorial_quality"]
        self.assertTrue(editorial["asset_source_trace"]["passed"])
        self.assertTrue(editorial["passed"], editorial["failures"])

    def test_formal_editorial_policy_rejects_changed_asset_source_hash(self):
        with tempfile.TemporaryDirectory() as work_dir:
            image_path = os.path.join(work_dir, "q1_result.png")
            source_path = os.path.join(work_dir, "ques1_result.csv")
            with open(image_path, "wb") as handle:
                handle.write(b"not a rendered image; editorial trace fixture")
            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write("metric,value\nduration,changed\n")
            with open(
                os.path.join(work_dir, "paper_assets_manifest.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    {
                        "figures": [{
                            "path": "q1_result.png",
                            "questions": ["ques1"],
                            "source_paths": ["ques1_result.csv"],
                            "source_sha256": {"ques1_result.csv": "0" * 64},
                        }],
                        "tables": [{
                            "id": "table_q1",
                            "questions": ["ques1"],
                            "source_paths": ["ques1_result.csv"],
                            "source_sha256": {"ques1_result.csv": "0" * 64},
                        }],
                    },
                    handle,
                )
            markdown = (
                "## 摘要\n\n" + "甲" * 120 + "\n\n"
                "关键词：线性规划；敏感性；生产；优化\n\n"
                "## 问题一结果分析\n\n"
                "![问题一结果图](q1_result.png)\n\n"
                "表1 问题一结果\n\n"
                "| 指标 | 结果 |\n| --- | --- |\n| 利润 | 2200 |\n"
            )
            report = build_preflight_report(
                work_dir,
                markdown,
                code_sources=[],
                declared_problem_count=1,
                editorial_policy={
                    "base": "cumcm_formal",
                    "min_body_chars": 0,
                    "min_abstract_paragraphs": 0,
                    "require_references": False,
                    "require_reference_style": False,
                },
            )

        trace = report["checks"]["editorial_quality"]["asset_source_trace"]
        self.assertFalse(trace["passed"])
        self.assertTrue(any("来源哈希失配" in error for error in trace["errors"]))

    def test_editorial_asset_binding_handles_question_four_before_chinese_noun(self):
        """``问题四三机`` must not be misread as a nonexistent question 43."""
        with tempfile.TemporaryDirectory() as work_dir:
            image_path = os.path.join(work_dir, "q4_result.png")
            source_path = os.path.join(work_dir, "ques4_result.csv")
            with open(image_path, "wb") as handle:
                handle.write(b"editorial question binding fixture")
            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write("metric,value\nduration,1.0\n")
            with open(source_path, "rb") as handle:
                source_hash = hashlib.sha256(handle.read()).hexdigest()
            with open(
                os.path.join(work_dir, "paper_assets_manifest.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    {
                        "figures": [{
                            "path": "q4_result.png",
                            "questions": ["ques4"],
                            "source_paths": ["ques4_result.csv"],
                            "source_sha256": {"ques4_result.csv": source_hash},
                        }],
                        "tables": [{
                            "id": "table_q4",
                            "questions": ["ques4"],
                            "source_paths": ["ques4_result.csv"],
                            "source_sha256": {"ques4_result.csv": source_hash},
                        }],
                    },
                    handle,
                )
            markdown = (
                "## 摘要\n\n" + "甲" * 120 + "\n\n"
                "关键词：线性规划；敏感性；生产；优化\n\n"
                "## 问题四：三机协同结果\n\n"
                "![问题四三机遮蔽区间](q4_result.png)\n\n"
                "表4 问题四三机遮蔽结果\n\n"
                "| 指标 | 结果 |\n| --- | --- |\n| 时长 | 1.0 |\n"
            )
            report = build_preflight_report(
                work_dir,
                markdown,
                code_sources=[],
                declared_problem_count=4,
                editorial_policy={
                    "base": "cumcm_formal",
                    "min_body_chars": 0,
                    "min_abstract_paragraphs": 0,
                    "require_references": False,
                    "require_reference_style": False,
                },
            )

        assets = report["checks"]["editorial_quality"]["question_assets"]
        self.assertEqual(assets["4"]["figures"], ["figure_1"])
        self.assertEqual(assets["4"]["tables"], ["table_1"])


if __name__ == "__main__":
    unittest.main()
