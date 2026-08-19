"""Unit tests for Architecture Upgrade Proposal components (FactStore, CrossModalValidator, AbstractBudgetEngine, and Prompts)."""

import os
import tempfile
import unittest

from app.core.prompts.coder import CODER_PROMPT
from app.core.prompts.modeler import MODELER_PROMPT
from app.core.prompts.writer import get_writer_prompt
from app.tools.abstract_budget_engine import AbstractBudgetEngine
from app.tools.cross_modal_validator import (
    audit_cross_modal,
    extract_code_generated_files,
    validate_code_text_parity,
)
from app.tools.fact_store import FactStore


class TestArchitectureUpgradeComponents(unittest.TestCase):
    """验证架构升级方案落地模块的功能。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    # ------------------ 1. FactStore 单元测试 ------------------
    def test_fact_store_register_and_lookup(self):
        store = FactStore(work_dir=self.work_dir)
        store.register_metric(
            name="phi_star",
            value=0.013487,
            subtask_id="ques3",
            unit="%",
            label="最优体积分数",
            source="ques3_results.csv",
            wilson_low=0.8564,
            wilson_high=0.9383,
        )

        fact = store.get("phi_star", subtask_id="ques3")
        self.assertIsNotNone(fact)
        self.assertEqual(fact.value, 0.013487)
        self.assertEqual(fact.format_value(precision=6), "0.013487")
        self.assertEqual(store.get_value("phi_star", subtask_id="ques3"), 0.013487)

    def test_fact_store_placeholder_rendering(self):
        store = FactStore(work_dir=self.work_dir)
        store.register_metric(
            name="cost_star",
            value=7.88,
            subtask_id="ques4",
            unit="元",
            label="最低成本",
            source="ques4_optimal_solution.csv",
        )
        store.register_metric(
            name="na_star",
            value=531,
            subtask_id="ques4",
            unit="根",
            label="最优圆柱数量",
            source="ques4_optimal_solution.csv",
        )

        template = (
            "求得最优决策为 N_A = {{ facts.ques4.na_star }} 根，"
            "最低总成本为 {{ facts.ques4.cost_star }} 元。"
        )
        rendered, replacements = store.render_template(template)
        self.assertIn("N_A = 531 根", rendered)
        self.assertIn("最低总成本为 7.88 元", rendered)
        self.assertEqual(len(replacements), 2)

    def test_fact_store_disk_persistence_and_reloading(self):
        store = FactStore(work_dir=self.work_dir)
        store.register_metric(name="p_target", value=0.90, subtask_id="ques3")
        saved_path = store.save_to_disk(self.work_dir)
        self.assertTrue(os.path.isfile(saved_path))

        reloaded = FactStore.load_from_disk(self.work_dir)
        self.assertEqual(reloaded.get_value("p_target", subtask_id="ques3"), 0.90)

    # ------------------ 2. CrossModalValidator 单元测试 ------------------
    def test_ast_file_generation_extraction(self):
        sample_code = """
import pandas as pd
import numpy as np

df = pd.DataFrame({"col": [1, 2, 3]})
df.to_csv("ques4_global_frontier_certificate.csv", index=False)
df.to_excel("ques4_results.xlsx")

with open("ques3_acceptance_metrics.csv", "w") as f:
    f.write("a,b\\n1,2\\n")
"""
        generated_files, output_calls = extract_code_generated_files(sample_code)
        self.assertIn("ques4_global_frontier_certificate.csv", generated_files)
        self.assertIn("ques4_results.xlsx", generated_files)
        self.assertIn("ques3_acceptance_metrics.csv", generated_files)
        self.assertGreaterEqual(len(output_calls), 3)

    def test_code_text_parity_detection(self):
        markdown_text = """
# 五、模型求解与分析
我们在研究中通过计算生成了全域排除证书 `ques4_global_frontier_certificate.csv`，
并且所有数据已记录在 `ques3_results.csv` 中。
"""
        # 场景 A: 代码中完整包含了两个文件的生成
        code_complete = """
df1.to_csv("ques4_global_frontier_certificate.csv")
df2.to_csv("ques3_results.csv")
"""
        res_pass = validate_code_text_parity(markdown_text, code_complete, self.work_dir)
        self.assertTrue(res_pass["passed"])
        self.assertEqual(res_pass["status"], "PASS")
        self.assertEqual(len(res_pass["missing_critical_generators"]), 0)

        # 场景 B: 正文声称有证书，但代码中缺失
        code_incomplete = """
df2.to_csv("ques3_results.csv")
"""
        res_fail = validate_code_text_parity(markdown_text, code_incomplete, self.work_dir)
        self.assertFalse(res_fail["passed"])
        self.assertIn("ques4_global_frontier_certificate.csv", res_fail["missing_critical_generators"])

    def test_audit_cross_modal_writes_report(self):
        report = audit_cross_modal(self.work_dir, markdown_text="正文测试", code_sources=[])
        report_path = os.path.join(self.work_dir, "cross_modal_audit.json")
        self.assertTrue(os.path.isfile(report_path))
        self.assertIn("status", report)

    def test_audit_optimality_certificates_catches_contradictions(self):
        from app.tools.cross_modal_validator import audit_optimality_certificates

        # 创建一个宣称最优成本为 7.88 的最优解文件
        opt_path = os.path.join(self.work_dir, "ques4_optimal_solution.csv")
        with open(opt_path, "w", encoding="utf-8") as f:
            f.write("total_cost_yuan,N_A,N_B\n7.882177,531,0\n")

        # 场景 A: 证书中的点全部被成功排除 (Wilson_low < 0.90)
        cert_pass_path = os.path.join(self.work_dir, "ques4_global_frontier_certificate.csv")
        with open(cert_pass_path, "w", encoding="utf-8") as f:
            f.write("N_A,N_B_max,total_cost_yuan,wilson_low,status\n")
            f.write("500,274,7.881104,0.855150,EXCLUDED\n")
            f.write("520,97,7.881418,0.888400,EXCLUDED\n")

        res_pass = audit_optimality_certificates(self.work_dir)
        self.assertTrue(res_pass["passed"])
        self.assertEqual(res_pass["status"], "PASS")
        self.assertEqual(res_pass["contradiction_count"], 0)

        # 场景 B: 证书中存在一个成本更低但被标记为 FEASIBLE 的矛盾点
        with open(cert_pass_path, "w", encoding="utf-8") as f:
            f.write("N_A,N_B_max,total_cost_yuan,wilson_low,status\n")
            f.write("500,274,7.881104,0.855150,EXCLUDED\n")
            f.write("530,8,7.880737,0.901931,FEASIBLE\n")

        res_fail = audit_optimality_certificates(self.work_dir)
        self.assertFalse(res_fail["passed"])
        self.assertEqual(res_fail["status"], "FAIL")
        self.assertEqual(res_fail["contradiction_count"], 1)
        self.assertIn("530", str(res_fail["contradictions"]))

    # ------------------ 3. AbstractBudgetEngine 单元测试 ------------------
    def test_abstract_budget_engine_micro_adjustments(self):
        adjustments_mod = AbstractBudgetEngine.get_adaptive_micro_adjustments("moderate")
        self.assertIn("linestretch", adjustments_mod)
        self.assertIn("fontsize", adjustments_mod)

        adjustments_heavy = AbstractBudgetEngine.get_adaptive_micro_adjustments("heavy")
        self.assertEqual(adjustments_heavy["linestretch"], "1.15")

    # ------------------ 4. 提示词升级契约测试 ------------------
    def test_modeler_prompt_contains_rigor_and_literature(self):
        self.assertIn("Wilson 95% 置信区间", MODELER_PROMPT)
        self.assertIn("一维上确界前沿排除证明算法", MODELER_PROMPT)
        self.assertIn("Balberg 排除体积理论", MODELER_PROMPT)
        self.assertIn("Lorenz & Ziff", MODELER_PROMPT)
        self.assertIn("Spherocylinder", MODELER_PROMPT)

    def test_coder_prompt_contains_advanced_templates(self):
        self.assertIn("Composite Figures", CODER_PROMPT)
        self.assertIn("Mechanism Diagrams", CODER_PROMPT)
        self.assertIn("wilson_score_interval", CODER_PROMPT)
        self.assertIn("ques4_global_frontier_certificate.csv", CODER_PROMPT)

    def test_writer_prompt_contains_consistency_and_literature(self):
        writer_prompt = get_writer_prompt()
        self.assertIn("复合多子图解析", writer_prompt)
        self.assertIn("机理图/算法流程图解读", writer_prompt)
        self.assertIn("统计标准统一性", writer_prompt)
        self.assertIn("Balberg 排除体积理论", writer_prompt)

    def test_audit_latex_formatting_integrity(self):
        from app.tools.cross_modal_validator import audit_latex_formatting_integrity

        # 正确格式
        clean_text = "在本文最优解 $M=5000$ 密集采样下，求得最优解为 $N_A^*=531, N_B^*=0, C^*=7.88\\text{ 元}$。"
        res_clean = audit_latex_formatting_integrity(clean_text)
        self.assertTrue(res_clean["passed"])
        self.assertEqual(res_clean["issue_count"], 0)

        # 损坏格式（正文变量展开损坏，如 =500$, .90$, .88\text）
        corrupt_text = "基准样本量 =500$ 且概率低于 .90$，总成本低于 .88\\text{ 元}$。"
        res_corrupt = audit_latex_formatting_integrity(corrupt_text)
        self.assertFalse(res_corrupt["passed"])
        self.assertGreater(res_corrupt["issue_count"], 0)

        # 附录代码块内注释损坏检测
        code_fence_corrupt = (
            "### 附录B 源码\n"
            "```python\n"
            "# 经扫描（基准样本量 =500$ 且概率严格低于 .90$）\n"
            "def solver():\n"
            "    pass\n"
            "```\n"
        )
        res_code_corrupt = audit_latex_formatting_integrity(code_fence_corrupt)
        self.assertFalse(res_code_corrupt["passed"])
        self.assertGreater(res_code_corrupt["issue_count"], 0)
        self.assertEqual(res_code_corrupt["issues"][0]["type"], "corrupted_latex_in_code")

    def test_audit_on_real_artifacts(self):
        """对真实任务目录下的 res.md 与 master_solver.py 进行真实对齐与门禁核验。"""
        from app.tools.cross_modal_validator import (
            audit_cross_modal,
            audit_latex_formatting_integrity,
        )

        real_work_dir = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "../../project/work_dir/20260817-163525-f2715db564e250aec38490e2c03e8a68",
            )
        )
        if not os.path.isdir(real_work_dir):
            return

        res_md_path = os.path.join(real_work_dir, "res.md")
        if os.path.isfile(res_md_path):
            with open(res_md_path, encoding="utf-8", errors="replace") as f:
                md_content = f.read()

            # 1. 真实 res.md 的 LaTeX 与代码块格式门禁
            latex_res = audit_latex_formatting_integrity(md_content)
            self.assertIn("passed", latex_res)
            self.assertIn("issues", latex_res)
            self.assertTrue(
                latex_res["passed"],
                f"真实 res.md 未通过 LaTeX 完整性审计: {latex_res['issues']}",
            )

            # 2. 真实工作目录跨模态完整审计
            cross_res = audit_cross_modal(real_work_dir)
            self.assertIn("status", cross_res)
            self.assertIn("passed", cross_res)
            self.assertEqual(
                cross_res["status"],
                "PASS",
                f"真实任务跨模态审计未通过: {cross_res}",
            )


if __name__ == "__main__":
    unittest.main()


