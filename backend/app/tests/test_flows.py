"""工作流提示边界测试。"""

import json
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
from app.schemas.problem_contract import ContractRequirement, ProblemContract


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

    def test_linear_programming_prompt_requires_resource_evidence_not_physical_residual(self):
        flows = Flows(
            {"ques_count": 1, "ques1": "求最优生产方案。"},
            ProblemContract(
                required_requirements=[
                    ContractRequirement(
                        key="linear_programming_evidence",
                        label="线性规划证据",
                        source="test",
                        plugin="linear_programming",
                    )
                ]
            ),
        )
        prompt = flows.get_solution_flows(
            flows.questions, ModelerToCoder(questions_solution={})
        )["ques1"]["coder_prompt"]

        self.assertIn("每条资源约束", prompt)
        self.assertIn("不要求质量/流量守恒残差", prompt)

    def test_pressure_target_prompt_names_the_metric_the_gate_requires(self):
        """题面给出压力目标时，必须显式索要门禁认可的峰峰值指标。

        `execution_validation` 要求单位为 MPa 的实际压力偏差/峰峰值指标，且不接受
        步长收敛差。提示词若不点名这个指标，Coder 只会记录“仿真完成”标志位或收敛量，
        任务会卡在门禁上而不是给出可复核结论。
        """
        flows = Flows(
            {"ques_count": 1, "ques1": "使高压油管内压力尽可能稳定在 100 MPa。"},
            ProblemContract(
                required_requirements=[
                    ContractRequirement(
                        key="target_pressure_100_mpa",
                        label="压力目标 100 MPa",
                        source="test",
                        evidence_terms=["100MPa"],
                    )
                ]
            ),
        )
        prompt = flows.get_solution_flows(
            flows.questions, ModelerToCoder(questions_solution={})
        )["ques1"]["coder_prompt"]

        self.assertIn("ques1_pressure_peak_to_peak", prompt)
        self.assertIn("MPa", prompt)
        self.assertIn("步长收敛差", prompt)

    def test_prompt_without_pressure_target_omits_the_peak_to_peak_requirement(self):
        """无压力目标的题不应被塞入无关的峰峰值指标要求。"""
        flows = Flows({"ques_count": 1, "ques1": "求最优生产方案。"})
        prompt = flows.get_solution_flows(
            flows.questions, ModelerToCoder(questions_solution={})
        )["ques1"]["coder_prompt"]

        self.assertNotIn("pressure_peak_to_peak", prompt)

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

    def test_quesx_writer_prompt_locks_scope_to_current_subtask(self):
        """方案3：写某个正式题时必须显式锁定到本题，禁止借用其它子任务叙事。"""
        with tempfile.TemporaryDirectory() as work_dir:
            flows = Flows(
                {
                    "ques_count": 3,
                    "background": "薄膜干涉测厚。",
                    "ques1": "建立一次反射双光束干涉模型。",
                    "ques2": "对附件1/2碳化硅数据计算厚度。",
                    "ques3": "分析附件3/4硅晶圆片是否出现多光束干涉并计算硅外延层厚度。",
                }
            )
            prompt = flows.get_writer_prompt(
                "ques3",
                "ques3 coder response",
                FakeCodeInterpreter(work_dir),
                {
                    "eda": "EDA模板",
                    "ques1": "模板1",
                    "ques2": "模板2",
                    "ques3": "模板3",
                    "sensitivity_analysis": "敏感性模板",
                },
            )

        # 明确锁定当前子任务 key，并写出本题题目
        self.assertIn("本节写作范围锁定：仅限 ques3", prompt)
        self.assertIn("分析附件3/4硅晶圆片是否出现多光束干涉", prompt)
        # 显式列出被禁止借用的其它子任务 key，含 sensitivity_analysis
        self.assertIn("sensitivity_analysis", prompt)
        self.assertIn("ques1", prompt)
        self.assertIn("ques2", prompt)
        self.assertIn("不得引用 sensitivity_analysis", prompt)
        # 本题 coder 响应在，其它子任务的方法响应不得出现在本题 prompt
        self.assertIn("ques3 coder response", prompt)
        self.assertNotIn("ques1 code output", prompt)
        self.assertNotIn("ques2 code output", prompt)

    def _write_marked_freeze(self, work_dir: str) -> None:
        """写入带唯一标记的三子任务冻结指标，用于内容级隔离验证。"""
        import hashlib

        source = os.path.join(work_dir, "ques_results.csv")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write("verified evidence\n")
        with open(source, "rb") as handle:
            sha = hashlib.sha256(handle.read()).hexdigest()
        with open(os.path.join(work_dir, "frozen_results.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "schema": "mathmodel.result-freeze",
                    "version": 1,
                    "metrics": [
                        {
                            "id": "q1_marker_metric",
                            "subtask_id": "ques1",
                            "label": "Q1唯一标记双光束厚度",
                            "value": 111.111,
                            "unit": "um",
                            "explanation": "ques1 唯一标记指标。",
                        },
                        {
                            "id": "q3_marker_metric",
                            "subtask_id": "ques3",
                            "label": "Q3唯一标记硅Airy多光束厚度",
                            "value": 333.333,
                            "unit": "um",
                            "explanation": "ques3 唯一标记指标，含附件3/4硅晶圆多光束。",
                        },
                    ],
                    "sources": [
                        {"relative_path": "ques_results.csv", "sha256": sha, "role": "evidence"}
                    ],
                },
                handle,
                ensure_ascii=False,
            )

    def test_quesx_prompt_physically_filters_other_subtask_frozen_facts(self):
        """内容级隔离：写 ques3 时 prompt 只含 ques3 的 frozen 指标标记，
        物理过滤掉 ques1 指标；写 ques1 时反之。不是仅靠提示词屏蔽。"""
        templates = {
            "eda": "EDA模板",
            "ques1": "模板1",
            "ques2": "模板2",
            "ques3": "模板3",
            "sensitivity_analysis": "敏感性模板",
        }
        with tempfile.TemporaryDirectory() as work_dir:
            self._write_marked_freeze(work_dir)
            flows = Flows(
                {
                    "ques_count": 3,
                    "background": "薄膜干涉测厚。",
                    "ques1": "建立一次反射双光束干涉模型。",
                    "ques2": "对附件1/2碳化硅数据计算厚度。",
                    "ques3": "分析附件3/4硅晶圆片是否出现多光束干涉并计算硅外延层厚度。",
                }
            )
            q3_prompt = flows.get_writer_prompt(
                "ques3",
                "Q3_CODER_NARRATION 附件3/4硅晶圆Airy多光束联合拟合",
                FakeCodeInterpreter(work_dir),
                templates,
            )
            q1_prompt = flows.get_writer_prompt(
                "ques1",
                "Q1_CODER_NARRATION 双光束一次反射建模",
                FakeCodeInterpreter(work_dir),
                templates,
            )

        # ques3 prompt：含本题 frozen 标记与本题 coder 叙述
        self.assertIn("Q3唯一标记硅Airy多光束厚度", q3_prompt)
        self.assertIn("333.333", q3_prompt)
        self.assertIn("Q3_CODER_NARRATION", q3_prompt)
        # 物理过滤掉 ques1 的 frozen 标记与 ques1 的 coder 叙述
        self.assertNotIn("Q1唯一标记双光束厚度", q3_prompt)
        self.assertNotIn("111.111", q3_prompt)
        self.assertNotIn("Q1_CODER_NARRATION", q3_prompt)
        self.assertNotIn("ques1 code output", q3_prompt)

        # ques1 prompt：含本题标记，物理过滤掉 ques3 的 Airy/多光束/附件3/4 事实
        self.assertIn("Q1唯一标记双光束厚度", q1_prompt)
        self.assertIn("111.111", q1_prompt)
        self.assertNotIn("Q3唯一标记硅Airy多光束厚度", q1_prompt)
        self.assertNotIn("333.333", q1_prompt)
        self.assertNotIn("Q3_CODER_NARRATION", q1_prompt)


if __name__ == "__main__":
    unittest.main()
