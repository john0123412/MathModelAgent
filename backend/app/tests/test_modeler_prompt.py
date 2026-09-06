"""Modeler prompt 硬性规范回归（六坑行动项 ①②④）。

防止三类已付过代价的建模短视被未来 prompt 改写悄悄移除：
①解析结构题禁纯仿真主求解；②NP-hard 必须先给简化论证；③optimization 类
必须固化"主求解器+独立方法双算一致"。
"""

import unittest

from app.core.prompts.modeler import MODELER_PROMPT


class ModelerPromptHardRulesTest(unittest.TestCase):
    def test_mechanism_first_no_pure_simulation_shortcut(self):
        self.assertIn("不得以蒙特卡洛、随机模拟等纯仿真作为主求解手段", MODELER_PROMPT)
        self.assertIn("评分端重模型机理", MODELER_PROMPT)

    def test_np_hard_requires_simplification_argument(self):
        self.assertIn("复杂度分析与工程简化论证", MODELER_PROMPT)
        self.assertIn("严禁未经论证直接套遗传算法、模拟退火、粒子群", MODELER_PROMPT)

    def test_optimization_requires_dual_computation(self):
        self.assertIn("主求解器 + 独立方法双算一致", MODELER_PROMPT)
        self.assertIn("vertex_enumeration_consistent", MODELER_PROMPT)
        self.assertIn("不得只用求解器 `success` 充当最优性证据", MODELER_PROMPT)

    def test_existing_schema_contract_untouched(self):
        self.assertIn('"schema_version": "mathmodel.model-plan.v1"', MODELER_PROMPT)
        self.assertIn("ques4", MODELER_PROMPT)


if __name__ == "__main__":
    unittest.main()
