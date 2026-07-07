"""论文导出后处理测试。"""

import json
import os
import tempfile
import unittest

from app.tools.paper_postprocessor import (
    append_code_appendix,
    build_claim_trace,
    build_preflight_report,
    ensure_table_captions,
    normalize_bold_standalone_labels,
    normalize_chinese_references,
    normalize_deterministic_eda_terms,
    normalize_deterministic_random_simulation_code_terms,
    normalize_english_transitions,
    normalize_extra_problem_labels,
    normalize_image_captions,
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
            "结果表明，机器时间变化会带来可解释的边际收益，人工资源仍可能构成关键瓶颈。\n\n"
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
    """验证最终论文末尾会附 CUMCM 要求的支撑材料清单与核心代码。"""

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
        self.assertIn("### B.1 problem_1.py", updated)
        self.assertIn("```python\nx = 1\n```", updated)
        self.assertNotIn("print('hello')", updated)

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
        self.assertNotIn("print(x)", updated)

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
        self.assertNotIn("print('ok')", updated)
        self.assertNotIn(long_separator, updated)

    def test_preflight_flags_print_heavy_appendix(self):
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

        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"]["appendix_console_noise"]["passed"])

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
                    "# 一、问题重述\n\n正文。\n\n"
                    "# 二、问题分析\n\n正文。\n\n"
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
        self.assertIn("正文[1]。", updated)
        self.assertIn("# 附录", updated)
        self.assertIn("## 附录A 支撑材料文件列表", updated)
        self.assertIn("## 附录B 源程序代码", updated)
        self.assertTrue(saved_report["checks"]["references"]["passed"])
        self.assertTrue(saved_report["checks"]["export_profile"]["passed"])
        self.assertTrue(saved_report["checks"]["code_appendix"]["passed"])
        self.assertTrue(saved_report["checks"]["support_materials"]["passed"])
        self.assertTrue(saved_report["checks"]["claim_trace"]["passed"])
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


if __name__ == "__main__":
    unittest.main()
