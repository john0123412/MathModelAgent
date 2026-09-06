"""批 G 门禁加固回归：方法声明-代码比对扩展、字面量结果 CSV、$ 开界与缺字形。

对应 09-03/09-04 复盘确定的三类已付出代价的失败模式：
- “正文声明 ε-约束/LNS/MILP，代码实为加权标量化/别的算法”（v23、A 稿）
- “验收数字未经计算直接写死进结果 CSV”
- “Markdown 源级检查对 PDF 渲染缺字形/`$ ` 开界完全无感”

09-05 追加三类（v23 收尾复盘）：
- “图6.1”章节式引用被 `图\s*(\d+)` 截成图 6，顶替真图引用且风格混用不报
- 表注编号删表/复制表后不连续，无任何检查
- 发链后 res.md/notebook/CSV 回改，旧报告哈希核对永远被动等待重跑（一晚六次链脱钩）
"""

import json
import os
import tempfile
import unittest

from app.tools.cross_modal_validator import (
    find_literal_result_writes,
    validate_code_text_parity,
)
from app.tools.final_acceptance import _check_artifact_freshness, _sha256_file
from app.tools.paper_postprocessor import (
    _check_algorithm_evidence,
    _check_figure_references,
    _check_math_dollar_spacing,
    _check_tables,
)
from app.tools.pdf_visual_checker import _check_missing_glyphs


class AlgorithmClaimGateExtensionTest(unittest.TestCase):
    """ALGORITHM_CLAIMS 扩展后的声明-证据比对语义。"""

    def _run(self, body: str, code: str | None) -> dict:
        with tempfile.TemporaryDirectory() as work_dir:
            if code is not None:
                with open(os.path.join(work_dir, "solver.py"), "w", encoding="utf-8") as f:
                    f.write(code)
            return _check_algorithm_evidence(work_dir, body)

    def test_epsilon_claim_with_weighted_scalarization_code_fails(self):
        # 事故向量：正文称 ε-约束法，代码是 baseline×eps 加权求和。
        check = self._run(
            "本文采用ε-约束法刻画碳-成本前沿。",
            "eps = 0.05\nfor lam in lambdas:\n    total = cost + eps * carbon\n",
        )
        claims = {c["algorithm"]: c["implemented"] for c in check["claims"]}
        self.assertIn("epsilon_constraint", claims)
        self.assertFalse(claims["epsilon_constraint"])

    def test_epsilon_claim_with_constraint_implementation_passes(self):
        check = self._run(
            "本文采用ε-约束法求解。",
            "eps = 0.05\nmodel.addConstr(cost <= cost_star * (1 + eps))\n",
        )
        self.assertTrue(check["passed"], check["claims"])

    def test_lns_claim_requires_code_evidence(self):
        missing = self._run("本文在修复环节采用大邻域搜索（LNS）修复可行解。", "x = 1\n")
        self.assertFalse(missing["passed"])
        found = self._run(
            "本文在修复环节采用大邻域搜索（LNS）修复可行解。",
            "def lns_destroy_repair(sol):\n    return destroy_and_repair(sol)\n",
        )
        self.assertTrue(found["passed"], found["claims"])

    def test_milp_claim_rejects_continuous_linprog(self):
        # HiGHS linprog 默认连续变量；正文声明整数规划必须看到整数证据。
        check = self._run(
            "问题二为混合整数规划，用 linprog 求解。",
            "from scipy.optimize import linprog\nres = linprog(c, A_ub=A_ub)\n",
        )
        claims = {c["algorithm"] for c in check["claims"] if not c["implemented"]}
        self.assertIn("milp", claims)

    def test_future_suggestion_for_new_methods_stays_exempt(self):
        check = self._run(
            "后续可改用模拟退火或大邻域搜索进一步提升效率。",
            "x = 1\n",
        )
        self.assertEqual(check["claims"], [])

    def test_future_context_after_algorithm_name_stays_exempt(self):
        check = self._run(
            "遗传算法可作为后续改进方向，混合整数规划留作进一步研究。",
            "x = 1\n",
        )
        self.assertTrue(check["passed"], check)
        self.assertEqual(check["claims"], [])
        self.assertEqual(len(check["excluded_claims"]), 2)

    def test_comparison_with_ga_and_pso_stays_exempt(self):
        check = self._run(
            "相较于 GA/PSO，本文采用线性规划完成当前求解。",
            "from scipy.optimize import linprog\n",
        )
        self.assertTrue(check["passed"], check)
        self.assertEqual(check["claims"], [])

    def test_current_ga_claim_without_evidence_still_fails(self):
        check = self._run("本文采用 GA 完成当前求解。", "x = 1\n")
        self.assertFalse(check["passed"], check)
        self.assertIn("genetic_algorithm", {item["algorithm"] for item in check["claims"]})

    def test_pending_milp_recalculation_stays_exempt(self):
        check = self._run(
            "后续需在混合整数规划框架下重新求解，以评估整数化损失。",
            "from scipy.optimize import linprog\n",
        )
        self.assertTrue(check["passed"], check)
        self.assertEqual(check["claims"], [])


class NotebookParityTest(unittest.TestCase):
    def test_notebook_code_cells_are_scanned_as_python(self):
        with tempfile.TemporaryDirectory() as work_dir:
            notebook = {
                "cells": [
                    {"cell_type": "markdown", "source": ["result_table.to_csv('fake.csv')"]},
                    {"cell_type": "code", "source": ["result_table.to_csv('ques1_results.csv', index=False)\n"]},
                ]
            }
            path = os.path.join(work_dir, "notebook.ipynb")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(notebook, handle)
            report = validate_code_text_parity(
                "结果见 `ques1_results.csv`。", ["notebook.ipynb"], work_dir
            )
        self.assertTrue(report["passed"], report)
        self.assertIn("ques1_results.csv", report["code_generated_files"])

    def test_notebook_without_writer_still_warns(self):
        with tempfile.TemporaryDirectory() as work_dir:
            path = os.path.join(work_dir, "notebook.ipynb")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"cells": [{"cell_type": "code", "source": ["x = 1\\n"]}]}, handle)
            report = validate_code_text_parity(
                "结果见 `ques1_results.csv`。", ["notebook.ipynb"], work_dir
            )
        self.assertFalse(report["passed"])
        self.assertIn("ques1_results.csv", report["missing_critical_generators"])


class LiteralResultCsvTest(unittest.TestCase):
    """结果/验收 CSV 全部由字面量写出时必须拦截。"""

    def test_pure_literal_results_csv_is_flagged(self):
        code = (
            "import pandas as pd\n"
            "pd.DataFrame([[1.2, 3.4], [5.6, 7.8]], columns=['a', 'b']"
            ").to_csv('ques1_results.csv', index=False)\n"
        )
        hits = find_literal_result_writes(code)
        self.assertEqual([h["filename"] for h in hits], ["ques1_results.csv"])
        report = validate_code_text_parity("", [{"content": code}])
        self.assertEqual(report["status"], "WARN")
        self.assertFalse(report["passed"])

    def test_computed_dataframe_is_not_flagged(self):
        code = (
            "import pandas as pd\n"
            "rows = [[solve(i), i] for i in range(10)]\n"
            "pd.DataFrame(rows, columns=['v', 'i']).to_csv('ques1_results.csv')\n"
        )
        self.assertEqual(find_literal_result_writes(code), [])
        report = validate_code_text_parity("", [{"content": code}])
        self.assertEqual(report["status"], "PASS")

    def test_non_result_named_csv_is_ignored(self):
        code = "import pandas as pd\npd.DataFrame([[1, 2]]).to_csv('scenario_grid.csv')\n"
        self.assertEqual(find_literal_result_writes(code), [])

    def test_negated_literals_still_count_as_hardcoded(self):
        code = (
            "import pandas as pd\n"
            "pd.DataFrame([[-1.5, 2]]).to_csv('ques4_acceptance_metrics.csv')\n"
        )
        self.assertEqual(len(find_literal_result_writes(code)), 1)


class MathDollarSpacingTest(unittest.TestCase):
    """开界 ``$ `` 空格在 Markdown 源级 lint。"""

    def test_space_after_opening_dollar_is_flagged(self):
        check = _check_math_dollar_spacing("利润总额为 $ \\sum_{i} x_i $ 元，其中…")
        self.assertFalse(check["passed"])
        self.assertEqual(check["issues"][0]["line"], 1)

    def test_correct_inline_math_passes(self):
        self.assertTrue(_check_math_dollar_spacing("利润总额为 $\\sum_{i} x_i$ 元。")["passed"])

    def test_display_math_and_currency_pass(self):
        md = "$$\n\\sum_i x_i = 100\n$$\n\n价格 $100 与 $200 相比。"
        self.assertTrue(_check_math_dollar_spacing(md)["passed"])

    def test_closing_dollar_before_space_is_not_false_positive(self):
        # 初版裸正则把闭界 `...$ 中文` 误判为开界，在终版论文上产生 35 处假阳性；
        # 行内配对状态机修复后，闭界+空格、多个正确行内式共存都必须放行。
        md = (
            "负载 $96\\,s/(\\sqrt{n}\\,\\bar{C})$ 口径）。图12 均值 $1\\,284\\,013\\,383$ CNY 吻合。\n"
            "区域 $r$ 在时隙 $t$ 的 AI GPU 负载等于各任务等效需求。"
        )
        self.assertTrue(_check_math_dollar_spacing(md)["passed"])

    def test_code_fence_content_is_ignored(self):
        md = "```python\nprint('$ x $')\n```\n"
        self.assertTrue(_check_math_dollar_spacing(md)["passed"])


class MissingGlyphScanTest(unittest.TestCase):
    """渲染后文本层的缺字形/乱码字符扫描。"""

    def test_white_square_u25a1_is_caught(self):
        check = _check_missing_glyphs(["正常页", "面积 □ 为 5"])
        self.assertFalse(check["passed"])
        self.assertEqual(check["offenders"][0]["page"], 2)

    def test_replacement_char_and_nul_are_caught(self):
        check = _check_missing_glyphs(["\ufffd 乱码", "nul\x00here", "干净"])
        pages = [o["page"] for o in check["offenders"]]
        self.assertEqual(pages, [1, 2])

    def test_uffff_missing_glyph_is_caught(self):
        # v23 事故：listings 缺 λ 字形时 MuPDF 文本层输出 U+FFFF，
        # 初版扫描集漏掉该字符本身，此测试锁死补口。
        sample = "log(f' [\uffff={lam_c}] 约束违反组"
        check = _check_missing_glyphs(["正常", sample])
        self.assertFalse(check["passed"])
        self.assertEqual(check["offenders"][0]["page"], 2)
        self.assertIn("\\uffff", check["offenders"][0]["counts"])

    def test_clean_text_passes(self):
        self.assertTrue(_check_missing_glyphs(["正常", "$x^2$"])["passed"])


class FigureReferenceSectionStyleTest(unittest.TestCase):
    """章节式图引用（“图6.1”）不得顶替扁平图号，风格混用必须报出。"""

    def test_section_style_reference_is_not_counted_as_flat_number(self):
        # v23 事故形态："图6.1" 被旧正则截成图 6，真图 1 的缺失引用被顶替。
        md = "![图1 结果](fig1.png)\n\n结果如图6.1所示。\n"
        check = _check_figure_references(md)
        self.assertFalse(check["passed"])
        self.assertEqual(check["missing_references"][0]["figure_number"], 1)
        self.assertEqual(check["section_style_references"][0]["reference"], "图6.1")
        self.assertNotIn(6, check["referenced_numbers"])

    def test_flat_references_pass(self):
        md = (
            "![图1 结果](fig1.png)\n\n"
            "结果如图1所示。\n\n"
            "![图2 收敛](fig2.png)\n\n"
            "收敛过程见图2。\n"
        )
        check = _check_figure_references(md)
        self.assertTrue(check["passed"])
        self.assertEqual(check["section_style_references"], [])

    def test_section_style_only_body_reports_style_issue(self):
        md = (
            "![图1 结果](fig1.png)\n\n![图2 收敛](fig2.png)\n\n"
            "结果如图6.1所示。\n\n收敛见图6.2。\n"
        )
        check = _check_figure_references(md)
        self.assertFalse(check["passed"])
        self.assertEqual(
            {item["reference"] for item in check["section_style_references"]},
            {"图6.1", "图6.2"},
        )


class TableCaptionSequenceTest(unittest.TestCase):
    """表注编号从 1 起连续；章节式表注与扁平编号混用必须报出。"""

    @staticmethod
    def _table(caption: str) -> str:
        return (
            f"{caption}\n\n"
            "| A | B |\n"
            "| --- | --- |\n"
            "| 1 | 2 |\n\n"
        )

    def test_consecutive_numbers_pass(self):
        md = self._table("表1 静态结果") + self._table("表2 动态结果")
        check = _check_tables(md)
        self.assertTrue(check["passed"])
        self.assertEqual(check["caption_sequence_issues"], [])

    def test_gap_and_duplicate_are_flagged(self):
        # [1,3,3]：第 2 个位置既跳号又重号，按位置比较至少报出一次。
        md = (
            self._table("表1 静态结果")
            + self._table("表3 动态结果")
            + self._table("表3 复算")
        )
        check = _check_tables(md)
        self.assertFalse(check["passed"])
        self.assertEqual(
            [i["table_position"] for i in check["caption_sequence_issues"]],
            [2],
        )

    def test_section_style_caption_is_flagged(self):
        md = self._table("表4-1 分情景结果")
        check = _check_tables(md)
        self.assertFalse(check["passed"])
        self.assertEqual(len(check["section_style_captions"]), 1)
        self.assertEqual(check["caption_sequence_issues"], [])


class ArtifactFreshnessMtimeSentinelTest(unittest.TestCase):
    """发链后源文件回改（md/notebook/CSV）必须让旧报告脱钩——mtime 哨兵。"""

    @staticmethod
    def _make_batch(work_dir: str) -> float:
        base = 1_700_000_000.0

        def write(name: str, content: str, at: float) -> str:
            path = os.path.join(work_dir, name)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.utime(path, (at, at))
            return path

        write("res.md", "# 论文\n", base)
        write("res.json", "{}", base + 1)
        write("frozen_results.json", "{}", base + 2)
        write("notebook.ipynb", "{}", base + 3)
        write("ques1_metrics.csv", "a,b\n1,2\n", base + 4)
        write("res.pdf", "pdf-bytes", base + 5)
        write("res.docx", "docx-bytes", base + 6)
        hashes = {
            name: _sha256_file(os.path.join(work_dir, name))
            for name in ("res.md", "res.json", "res.docx", "res.pdf", "frozen_results.json")
        }

        def write_json(name: str, payload: dict, at: float) -> None:
            path = write(name, "{}", at)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.utime(path, (at, at))

        write_json(
            "export_status.json",
            {
                "pdf": {
                    "success": True,
                    "source_sha256": hashes["res.md"],
                    "output_sha256": hashes["res.pdf"],
                }
            },
            base + 7,
        )
        write_json(
            "docx_export_status.json",
            {
                "success": True,
                "source_sha256": hashes["res.md"],
                "output_sha256": hashes["res.docx"],
            },
            base + 8,
        )
        write_json(
            "candidate_manifest.json",
            {"artifact_set_id": "test", "artifact_hashes": hashes},
            base + 9,
        )
        return base

    def test_fresh_batch_passes(self):
        with tempfile.TemporaryDirectory() as work_dir:
            self._make_batch(work_dir)
            check = _check_artifact_freshness(work_dir)
            self.assertTrue(check["passed"], check["evidence"]["mismatches"])

    def test_source_touched_after_export_is_flagged(self):
        with tempfile.TemporaryDirectory() as work_dir:
            base = self._make_batch(work_dir)
            future = base + 10_000
            for name in ("res.md", "notebook.ipynb", "ques1_metrics.csv"):
                os.utime(os.path.join(work_dir, name), (future, future))
            check = _check_artifact_freshness(work_dir)
            self.assertFalse(check["passed"])
            flagged = {
                mismatch.split(" 的修改时间")[0]
                for mismatch in check["evidence"]["mismatches"]
            }
            self.assertEqual(flagged, {"res.md", "notebook.ipynb", "ques1_metrics.csv"})


class NotebookSerializerExecEvidenceTest(unittest.TestCase):
    """09-05 LP 冒烟实锤：序列化器历史上不打计数、stdout 不落 stream，
    与 PR #50 伪执行门禁的"真内核必打计数/print 必有 stream"假设冲突。
    修复后管道自身产物必须零误报，手工拼装仍必须被拦。"""

    def test_pipeline_serialized_notebook_passes_pseudo_exec_gate(self):
        import json
        from pathlib import Path
        from app.tools.notebook_serializer import NotebookSerializer
        from app.tools.execution_validation import _notebook_issues

        with tempfile.TemporaryDirectory() as wd:
            serializer = NotebookSerializer(work_dir=wd)
            serializer.add_code_cell_to_notebook('print("hello")\nx = 1\nx')
            serializer.add_code_cell_output_to_notebook("hello\n")
            nb = json.loads(Path(wd, "notebook.ipynb").read_text(encoding="utf-8"))
            code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
            self.assertEqual([c["execution_count"] for c in code_cells], [1])
            self.assertIn("stream", [o["output_type"] for o in code_cells[0]["outputs"]])
            by_id = {
                issue["id"]: issue
                for issue in _notebook_issues(Path(wd), has_execution_manifest=True)
            }
            self.assertIn("pseudo_exec.print_without_stream", by_id)
            self.assertIn("pseudo_exec.output_without_count", by_id)
            self.assertTrue(by_id["pseudo_exec.print_without_stream"]["passed"])
            self.assertTrue(by_id["pseudo_exec.output_without_count"]["passed"])

    def test_hand_assembled_output_without_count_still_blocked(self):
        import json
        from pathlib import Path
        from app.tools.notebook_serializer import NotebookSerializer
        from app.tools.execution_validation import _notebook_issues

        with tempfile.TemporaryDirectory() as wd:
            serializer = NotebookSerializer(work_dir=wd)
            serializer.add_code_cell_to_notebook("print(1)")
            serializer.add_code_cell_output_to_notebook("1\n")
            nb = json.loads(Path(wd, "notebook.ipynb").read_text(encoding="utf-8"))
            nb["cells"].append(
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "source": ["print(2)"],
                    "outputs": [
                        {
                            "output_type": "display_data",
                            "data": {"text/plain": ["2"]},
                            "metadata": {},
                        }
                    ],
                }
            )
            Path(wd, "notebook.ipynb").write_text(json.dumps(nb), encoding="utf-8")
            by_id = {
                issue["id"]: issue
                for issue in _notebook_issues(Path(wd), has_execution_manifest=True)
            }
            self.assertIn("pseudo_exec.output_without_count", by_id)
            self.assertFalse(by_id["pseudo_exec.output_without_count"]["passed"])
            self.assertEqual(by_id["pseudo_exec.output_without_count"]["evidence"]["cells"], [1])


if __name__ == "__main__":
    unittest.main()
