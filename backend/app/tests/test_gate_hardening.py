"""批 G 门禁加固回归：方法声明-代码比对扩展、字面量结果 CSV、$ 开界与缺字形。

对应 09-03/09-04 复盘确定的三类已付出代价的失败模式：
- “正文声明 ε-约束/LNS/MILP，代码实为加权标量化/别的算法”（v23、A 稿）
- “验收数字未经计算直接写死进结果 CSV”
- “Markdown 源级检查对 PDF 渲染缺字形/`$ ` 开界完全无感”
"""

import os
import tempfile
import unittest

from app.tools.cross_modal_validator import (
    find_literal_result_writes,
    validate_code_text_parity,
)
from app.tools.paper_postprocessor import (
    _check_algorithm_evidence,
    _check_math_dollar_spacing,
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


if __name__ == "__main__":
    unittest.main()
