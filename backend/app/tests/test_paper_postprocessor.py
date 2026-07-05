"""论文导出后处理测试。"""

import json
import os
import tempfile
import unittest

from app.tools.paper_postprocessor import (
    append_code_appendix,
    build_claim_trace,
    build_preflight_report,
    normalize_chinese_references,
    normalize_keywords,
    normalize_markdown_headings,
    prepare_paper_markdown,
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
        self.assertIn("\n[2] Spearman C. The proof and measurement of association[J]. American Journal of Psychology, 1904.", normalized)
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


class TestAppendCodeAppendix(unittest.TestCase):
    """验证最终论文末尾会附 CUMCM 要求的支撑材料清单与核心代码。"""

    def test_appends_support_material_list_and_python_files_after_references(self):
        with tempfile.TemporaryDirectory() as work_dir:
            code_path = os.path.join(work_dir, "problem_1.py")
            with open(code_path, "w", encoding="utf-8") as f:
                f.write("print('hello')\n")
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
        self.assertIn("```python\nprint('hello')\n```", updated)

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
        self.assertIn("x = 1\nprint(x)", updated)

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
