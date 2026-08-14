"""Regression tests for the Coder numerical-execution budget contract."""

import unittest

from app.core.agents.modeler_agent import MODEL_PLAN_PROTOCOL_REMINDER
from app.core.prompts import CODER_PROMPT, MODELER_PROMPT, get_writer_prompt


class CoderPromptTest(unittest.TestCase):
    def test_numerical_simulation_budget_contract_is_present(self):
        """A future prompt edit must not reintroduce monolithic ODE sweeps."""
        self.assertIn("EXECUTION-BUDGET CONTRACT", CODER_PROMPT)
        self.assertIn("representative trajectory", CODER_PROMPT)
        self.assertIn("vectorized or event-driven screen", CODER_PROMPT)
        self.assertIn("coarse-versus-refined comparison", CODER_PROMPT)
        self.assertIn("resumable stages", CODER_PROMPT)
        self.assertIn("For simulation/optimization tasks", CODER_PROMPT)
        self.assertIn("cached, event-driven, or analytically", CODER_PROMPT)
        self.assertIn("shortlist explicitly finite", CODER_PROMPT)
        self.assertIn("run budget and grid strategy", CODER_PROMPT)

    def test_high_pressure_source_and_phase_contracts_are_present(self):
        writer_prompt = get_writer_prompt()

        self.assertIn("问题一的喷油速率来自题面图2", MODELER_PROMPT)
        self.assertIn("至少比较两种可执行方案", MODELER_PROMPT)
        self.assertIn("问题一的喷油速率只来自题面图2", CODER_PROMPT)
        self.assertIn("alternate_phase_objective", CODER_PROMPT)
        self.assertIn("问题一喷油流出速率来自题面图2", writer_prompt)
        self.assertIn("independent_replay_report.json", writer_prompt)

    def test_modeler_prompt_requires_metric_target_bases(self):
        self.assertIn("acceptance_metrics[*].description", MODELER_PROMPT)
        self.assertIn("题目原文 / 数据统计 / 交叉验证 / 文献标准", MODELER_PROMPT)
        self.assertIn("阈值词 + 依据/来自/基于 + 来源词", MODELER_PROMPT)
        self.assertIn("“来源”不是允许的连接器", MODELER_PROMPT)
        self.assertIn("r2_test 的阈值依据", MODELER_PROMPT)
        self.assertIn("阈值/目标值/判据/容差 + 依据/来自/基于", MODEL_PLAN_PROTOCOL_REMINDER)
        self.assertIn("仅有 `iteration_count`", MODELER_PROMPT)
        self.assertIn("iteration_count、候选点评估次数", MODEL_PLAN_PROTOCOL_REMINDER)

    def test_formal_paper_assets_require_source_hash_trace(self):
        self.assertIn("FORMAL PAPER ASSET SOURCE TRACE", CODER_PROMPT)
        self.assertIn("paper_assets_manifest.json", CODER_PROMPT)
        self.assertIn("source_paths", CODER_PROMPT)
        self.assertIn("source_sha256", CODER_PROMPT)
        self.assertIn("do not fill", CODER_PROMPT)
