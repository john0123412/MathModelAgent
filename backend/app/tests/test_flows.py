"""工作流提示边界测试。"""

import os
import tempfile
import unittest

from app.core.flows import Flows
from app.schemas.A2A import (
    AcceptanceMetric,
    ExpectedArtifact,
    ModelPlan,
    ModelerToCoder,
    SubtaskPlan,
)


class FakeCodeInterpreter:
    def __init__(self, work_dir: str):
        self.work_dir = work_dir

    def get_code_output(self, section: str) -> str:
        return f"{section} code output"


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

    def test_solution_prompt_carries_structured_subtask_contract(self):
        plan = ModelPlan(
            eda="核验题面常量和单位。",
            subtasks={
                "ques1": SubtaskPlan(
                    inputs=["题面资源约束"],
                    method="定义决策变量、目标函数和全部约束，使用线性规划后逐项回代验证。",
                    constraints=["变量非负"],
                    expected_artifacts=[
                        ExpectedArtifact(path="ques1_results.csv", kind="result_table", description="最优解和目标值"),
                    ],
                    acceptance_metrics=[
                        AcceptanceMetric(key="objective_value", label="最优目标值", comparator="ge", target=0, description="由目标函数计算"),
                    ],
                    visualization="绘制可行域边界图。",
                )
            },
            sensitivity_analysis="比较资源上限变化。",
        )
        flows = Flows({"ques_count": 1, "ques1": "求最优生产方案。"})
        prompt = flows.get_solution_flows(
            flows.questions,
            ModelerToCoder(model_plan=plan),
        )["ques1"]["coder_prompt"]

        self.assertIn("建模手结构化交接", prompt)
        self.assertIn("ques1_results.csv", prompt)
        self.assertIn("objective_value", prompt)

    def test_writer_prompt_uses_persisted_response_when_resume_cache_is_missing(self):
        class MissingOutputCacheInterpreter(FakeCodeInterpreter):
            def get_code_output(self, section: str) -> str:
                raise KeyError(section)

        with tempfile.TemporaryDirectory() as work_dir:
            flows = Flows(
                {
                    "ques_count": 1,
                    "background": "生产计划优化。",
                    "ques1": "求最优生产方案。",
                }
            )

            prompt = flows.get_writer_prompt(
                "eda",
                "从检查点恢复的 EDA 代码说明。",
                MissingOutputCacheInterpreter(work_dir),
                {
                    "eda": "EDA模板",
                    "ques1": "模板",
                    "sensitivity_analysis": "敏感性模板",
                },
            )

        self.assertIn("从检查点恢复的 EDA 代码说明。", prompt)
        self.assertIn("EDA模板", prompt)

    def test_writer_prompt_includes_structured_result_facts(self):
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
            flows = Flows(
                {
                    "ques_count": 1,
                    "background": "生产计划优化。",
                    "ques1": "求最优生产方案。",
                }
            )

            prompt = flows.get_writer_prompt(
                "ques1",
                "coder response",
                FakeCodeInterpreter(work_dir),
                {
                    "eda": "EDA模板",
                    "ques1": "模板",
                    "sensitivity_analysis": "敏感性模板",
                },
            )

        self.assertIn("结构化结果事实", prompt)
        self.assertIn("机器时间影子价格 = 16.6667 元/小时", prompt)
        self.assertIn("人工时间影子价格 = 6.6667 元/小时", prompt)
        self.assertIn("正文关键数值必须优先使用以上结构化事实", prompt)


if __name__ == "__main__":
    unittest.main()
