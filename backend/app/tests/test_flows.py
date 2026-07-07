"""工作流提示边界测试。"""

import unittest

from app.core.flows import Flows
from app.schemas.A2A import ModelerToCoder


class TestFlows(unittest.TestCase):
    """验证流程提示不会鼓励无数据题目造样本。"""

    def test_eda_prompt_forbids_simulated_dataset_when_no_data_files(self):
        flows = Flows(
            {
                "ques_count": 1,
                "ques1": "在给定资源约束下求最优生产方案。",
            }
        )
        modeler_response = ModelerToCoder(
            questions_solution={"eda": "核验题目给定参数。"}
        )

        solution_flows = flows.get_solution_flows(flows.questions, modeler_response)
        eda_prompt = solution_flows["eda"]["coder_prompt"]

        self.assertIn("数据集文件列表为空", eda_prompt)
        self.assertIn("不得随机生成样本", eda_prompt)
        self.assertIn("不得创建“模拟数据集.csv”", eda_prompt)
        self.assertIn("约束可行性", eda_prompt)


if __name__ == "__main__":
    unittest.main()
