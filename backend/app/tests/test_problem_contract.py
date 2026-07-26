"""题面参数契约和建模输入守卫测试。"""

import json
import unittest

from app.core.agents.modeler_agent import ModelerAgent
from app.core.flows import Flows
from app.core.llm.types import StandardResponse
from app.schemas.A2A import (
    AcceptanceMetric,
    CoordinatorToModeler,
    ExpectedArtifact,
    ModelPlan,
    ModelerToCoder,
    SubtaskPlan,
)
from app.schemas.problem_contract import ProblemContract, build_problem_contract, validate_modeler_plan


HIGH_PRESSURE_PIPE_PROBLEM = """
流量系数 C=0.85。问题一：分别在 2 秒、5 秒、10 秒内完成压力调节。
问题二：使高压油管压力稳定在 100 MPa。
问题三：新增第二个喷油嘴，并设计减压阀控制方案。
"""

HIGH_PRESSURE_PIPE_FIXED_CONDITIONS = """
高压油管的内腔长度为500mm，内直径为10mm，供油入口 A 处小孔的直径为1.4mm。
单向阀每打开一次后就要关闭10ms。喷油器每秒工作10次，每次工作时喷油时间为2.4ms。
高压油泵在入口 A 处提供的压力恒为160 MPa，高压油管内的初始压力为100 MPa。
流量系数 C=0.85。
"""

HIGH_PRESSURE_PIPE_Q1_CONTROL = HIGH_PRESSURE_PIPE_FIXED_CONDITIONS + """
如果要将高压油管内压力稳定在 100MPa 左右，如何设置单向阀每次开启的时长？
如果将压力从 100MPa 增加到 150MPa，并分别经过约 2 秒、5 秒、10 秒后稳定，开启时长应如何调整？
"""

OPTICAL_ANGLE_PAIR_PROBLEM = """
问题 1 如果考虑外延层和衬底界面只有一次反射、透射所产生的干涉条纹，建立数学模型。
问题 2 对附件 1 和附件 2 提供的碳化硅晶圆片光谱实测数据给出计算结果。
问题 3 分析附件 3 和附件 4 提供的硅晶圆片测试结果是否出现多光束干涉。
附件说明：(1) 附件 1.xlsx 和附件 2.xlsx 是入射角分别为 10° 和 15° 时针对同一块碳化硅晶圆片的测试结果。
(2) 附件 3.xlsx 和附件 4.xlsx 是入射角分别为 10° 和 15° 时针对同一块硅晶圆片的测试结果。
"""


class TestProblemContract(unittest.TestCase):
    def test_extracts_optical_angle_pairs_and_same_sample_relationships(self):
        contract = build_problem_contract(OPTICAL_ANGLE_PAIR_PROBLEM)
        values = {
            item.key: item.value
            for item in contract.immutable_parameters
            if item.key.startswith("incident_angle_")
        }
        self.assertEqual(values, {"incident_angle_1": 10.0, "incident_angle_2": 15.0})
        requirement_keys = {item.key for item in contract.required_requirements}
        self.assertTrue(
            {
                "incident_angle_pair",
                "paired_angle_same_sample_1_2",
                "paired_angle_same_sample_3_4",
            }.issubset(requirement_keys)
        )

    def test_accepts_question_scoped_dual_angle_same_sample_plan(self):
        result = validate_modeler_plan(
            build_problem_contract(OPTICAL_ANGLE_PAIR_PROBLEM),
            {
                "ques1": "推导任意入射角下的双光束干涉模型。",
                "ques2": "附件1和附件2是同一块碳化硅晶圆在10°与15°下的配对测量，联合估计厚度。",
                "ques3": "附件3和附件4是同一块硅晶圆在10°与15°下的配对测量，检验多光束干涉。",
            },
        )
        self.assertTrue(result.valid, result.model_dump_json())

    def test_accepts_same_wafer_at_different_incident_angles(self):
        result = validate_modeler_plan(
            build_problem_contract(OPTICAL_ANGLE_PAIR_PROBLEM),
            {
                "ques1": "推导任意入射角下的双光束干涉模型。",
                "ques2": (
                    "附件1和附件2是同一碳化硅晶圆片在不同入射角（10°和15°）"
                    "下的配对测量，厚度和折射率参数相同，联合建模。"
                ),
                "ques3": (
                    "附件3和附件4是同一硅晶圆片在不同入射角（10°和15°）"
                    "下的配对测量，联合检验多光束干涉。"
                ),
            },
        )
        self.assertTrue(result.valid, result.model_dump_json())

    def test_accepts_plan_that_quotes_the_prohibition_itself(self):
        """方案原样引用契约禁令（“不得改写为不同样品”）属于遵守，不得误判为违规。"""
        result = validate_modeler_plan(
            build_problem_contract(OPTICAL_ANGLE_PAIR_PROBLEM),
            {
                "ques1": "推导任意入射角下的双光束干涉模型。",
                "ques2": (
                    "附件1和附件2是同一块碳化硅晶圆片在题面实测入射角10°和15°下的"
                    "配对测量联合建模，不得改写为不同样品或两个独立样品；"
                    "最终厚度d必须在两组角度数据之间共享，不得将两组数据视为不同晶圆片。"
                ),
                "ques3": (
                    "附件3和附件4是同一块硅晶圆片在10°和15°下的配对测量，"
                    "联合检验多光束干涉，禁止视为两片独立晶圆。"
                ),
            },
        )
        self.assertTrue(result.valid, result.model_dump_json())

    def test_accepts_decimal_angles_that_end_in_zero(self):
        """10.0°/15.0度 的小数写法不得被 0° 覆写检查误判（.0° 不是 0°）。"""
        result = validate_modeler_plan(
            build_problem_contract(OPTICAL_ANGLE_PAIR_PROBLEM),
            {
                "ques1": "推导任意入射角下的双光束干涉模型。",
                "ques2": (
                    "附件1和附件2是同一块碳化硅晶圆片的配对测量；"
                    "theta_1=10.0°、theta_2=15.0°为不可修改的题面参数，"
                    "必须直接用于算法，不得替换入射角。"
                ),
                "ques3": (
                    "附件3和附件4是同一块硅晶圆片在10.0度和15.0度下的配对测量，"
                    "联合检验多光束干涉。"
                ),
            },
        )
        self.assertTrue(result.valid, result.model_dump_json())

    def test_rejects_wafer_itself_being_different_or_independent(self):
        result = validate_modeler_plan(
            build_problem_contract(OPTICAL_ANGLE_PAIR_PROBLEM),
            {
                "ques1": "推导一般干涉模型。",
                "ques2": "附件1和附件2对应的晶圆彼此不同，分别在10°和15°下计算。",
                "ques3": "附件3和附件4使用两片独立硅晶圆，分别在10°和15°下计算。",
            },
        )
        self.assertFalse(result.valid)
        violation_text = " ".join(result.violations)
        self.assertIn("附件1/2", violation_text)
        self.assertIn("附件3/4", violation_text)
        self.assertIn("独立样品", violation_text)

    def test_rejects_zero_degree_override_even_if_angles_are_mentioned_elsewhere(self):
        result = validate_modeler_plan(
            build_problem_contract(OPTICAL_ANGLE_PAIR_PROBLEM),
            {
                "ques1": "题面给出10°和15°，先推导一般公式。",
                "ques2": "附件1和附件2作为两片独立晶圆，采用垂直入射近似，入射角0°。",
                "ques3": "附件3和附件4为同一块硅晶圆，但统一令入射角为0°。",
            },
        )
        self.assertFalse(result.valid)
        violation_text = " ".join(result.violations)
        self.assertIn("附件1/2", violation_text)
        self.assertIn("附件3/4", violation_text)
        self.assertIn("0°", violation_text)
        self.assertIn("独立样品", violation_text)

    def test_rejects_swapped_attachment_pair_assignment(self):
        result = validate_modeler_plan(
            build_problem_contract(OPTICAL_ANGLE_PAIR_PROBLEM),
            {
                "ques1": "建立一般干涉模型。",
                "ques2": "附件1和附件3为同一块晶圆，在10°和15°下联合计算。",
                "ques3": "附件2和附件4为同一块晶圆，在10°和15°下联合计算。",
            },
        )
        self.assertFalse(result.valid)
        missing_text = " ".join(result.missing_requirements)
        self.assertIn("附件1/2", missing_text)
        self.assertIn("附件3/4", missing_text)

    def test_negative_zero_degree_constraint_is_not_treated_as_override(self):
        result = validate_modeler_plan(
            build_problem_contract(OPTICAL_ANGLE_PAIR_PROBLEM),
            {
                "ques1": "推导一般模型。",
                "ques2": "附件1/2为同一块碳化硅晶圆在10°、15°下的测量，不得采用0°近似。",
                "ques3": "附件3/4为同一块硅晶圆在10°、15°下的测量，禁止垂直入射替换。",
            },
        )
        self.assertTrue(result.valid, result.model_dump_json())

    def test_non_optical_angle_text_does_not_create_attachment_contract(self):
        contract = build_problem_contract("斜坡角度为10°和15°，比较两个独立试件。")
        self.assertFalse(
            any(
                item.key.startswith("incident_angle_")
                for item in contract.immutable_parameters
            )
        )

    def test_extracts_hard_parameter_and_required_outputs(self):
        contract = build_problem_contract(HIGH_PRESSURE_PIPE_PROBLEM)
        self.assertEqual(contract.immutable_parameters[0].value, 0.85)
        self.assertFalse(contract.immutable_parameters[0].mutable)
        self.assertTrue(
            {"problem1_transition_times", "target_pressure_100_mpa", "two_injectors", "relief_valve_control"}
            .issubset({item.key for item in contract.required_requirements})
        )
        self.assertIn(
            "physical_simulation_evidence",
            {item.key for item in contract.required_requirements},
        )

    def test_rejects_overridden_coefficient_and_missing_requirements(self):
        result = validate_modeler_plan(
            build_problem_contract(HIGH_PRESSURE_PIPE_PROBLEM),
            {"ques1": "设流量系数 C=0.6，并只研究 2 秒方案。"},
        )
        self.assertFalse(result.valid)
        self.assertIn("C=0.6", result.violations[0])
        self.assertIn("5 秒", result.missing_requirements[0])

    def test_accepts_complete_plan_that_preserves_hard_parameter(self):
        result = validate_modeler_plan(
            build_problem_contract(HIGH_PRESSURE_PIPE_PROBLEM),
            {
                "ques1": "使用题面流量系数 C=0.85，分别给出 2 秒、5 秒和 10 秒过渡控制。",
                "ques2": "以 100 MPa 为硬约束，检验稳态均值和波动。",
                "ques3": "按两个喷油嘴错峰建模，并给出减压阀周期控制。",
            },
        )
        self.assertTrue(result.valid)

    def test_coder_prompt_carries_contract_and_infeasibility_rule(self):
        contract = build_problem_contract(HIGH_PRESSURE_PIPE_PROBLEM)
        flows = Flows({"ques_count": 1, "ques1": "使压力稳定在 100 MPa"}, contract)
        prompts = flows.get_solution_flows(
            flows.questions, ModelerToCoder(questions_solution={"ques1": "求解"})
        )
        self.assertIn("流量系数（C） = 0.85", prompts["ques1"]["coder_prompt"])
        self.assertIn("禁止称为最优解", prompts["ques1"]["coder_prompt"])

    def test_extracts_non_default_pressure_target_without_assuming_a_fluctuation_limit(self):
        contract = build_problem_contract("请使油管压力稳定在 120 MPa，并报告实际波动。")

        requirement = next(
            item for item in contract.required_requirements if item.key == "target_pressure_120_mpa"
        )
        self.assertEqual(requirement.evidence_terms, ["120MPa"])

    def test_extracts_fixed_pipe_conditions_and_rejects_wrong_frequency(self):
        contract = build_problem_contract(HIGH_PRESSURE_PIPE_FIXED_CONDITIONS)
        values = {item.key: item.value for item in contract.immutable_parameters}
        self.assertEqual(values["pipe_length"], 500.0)
        self.assertEqual(values["pipe_inner_diameter"], 10.0)
        self.assertEqual(values["injection_frequency"], 10.0)
        result = validate_modeler_plan(
            contract,
            {"ques1": "油管长度 L=500 mm，内径 D=10 mm，喷油器工作频率为100次/秒。"},
        )
        self.assertFalse(result.valid)
        self.assertIn("100次/秒", " ".join(result.violations))

    def test_extracts_problem_one_valve_duration_deliverables(self):
        contract = build_problem_contract(HIGH_PRESSURE_PIPE_Q1_CONTROL)
        self.assertIn(
            "problem1_valve_duration_outputs",
            {item.key for item in contract.required_requirements},
        )


class SequencedModel:
    def __init__(self, responses: list[str]):
        self.responses = iter(responses)

    async def chat(self, **_kwargs):
        return StandardResponse(content=next(self.responses))


class TestModelerContractGuard(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _minimal_model_plan() -> dict:
        return {
            "schema_version": "mathmodel.model-plan.v1",
            "eda": "核验题面参数、附件列和单位。",
            "subtasks": {
                "ques1": {
                    "inputs": ["题面与附件数据"],
                    "method": "读取题面与附件数据，建立模型并用独立计算复核主要结果。",
                    "constraints": ["保留题面给定参数和单位"],
                    "expected_artifacts": [
                        {
                            "path": "ques1_results.csv",
                            "kind": "result_table",
                            "description": "主要数值结果与计算口径",
                        }
                    ],
                    "acceptance_metrics": [
                        {
                            "key": "result_check",
                            "label": "结果复核值",
                            "comparator": "eq",
                            "target": 1,
                            "description": "与独立复算结果比较",
                        }
                    ],
                    "visualization": "绘制结果与复算对比图。",
                }
            },
            "sensitivity_analysis": "扰动关键输入并比较主要结果。",
        }

    async def test_modeler_retries_when_plan_overrides_hard_parameter(self):
        contract = build_problem_contract(HIGH_PRESSURE_PIPE_PROBLEM)
        agent = ModelerAgent(
            task_id="contract-test",
            model=SequencedModel(
                [
                    '{"ques1": "设流量系数 C=0.6，仅研究2秒"}',
                    json.dumps(
                        {
                            "schema_version": "mathmodel.model-plan.v1",
                            "eda": "核验题设参数与单位。",
                            "subtasks": {
                                "ques1": {
                                    "inputs": ["题面流量系数 C=0.85", "题设压力目标"],
                                    "method": "以质量守恒状态方程进行数值仿真，分别计算2秒、5秒和10秒；并按两个喷油嘴和减压阀控制验证100 MPa目标。",
                                    "constraints": ["使用 C=0.85", "压力目标为100 MPa"],
                                    "expected_artifacts": [
                                        {"path": "ques1_results.csv", "kind": "result_table", "description": "稳态和过渡控制结果"},
                                        {"path": "ques1_series.csv", "kind": "time_series", "description": "压力时序和流量平衡"},
                                    ],
                                    "acceptance_metrics": [
                                        {"key": "pressure_error", "label": "压力目标误差", "comparator": "le", "target": 1, "unit": "MPa", "description": "与100 MPa目标比较"},
                                        {"key": "mass_balance_residual", "label": "质量守恒残差", "comparator": "le", "target": 0.01, "description": "由供回油流量平衡计算"},
                                    ],
                                    "visualization": "压力时序图。",
                                }
                            },
                            "sensitivity_analysis": "扰动阀门时长并比较压力误差。",
                        },
                        ensure_ascii=False,
                    ),
                ]
            ),
        )

        result = await agent.run(
            CoordinatorToModeler(
                questions={"ques_count": 3, "ques1": "题目一"},
                ques_count=3,
                problem_contract=contract,
            )
        )

        self.assertIn("C=0.85", result.questions_solution["ques1"])
        self.assertTrue(
            any("不是可执行的完整 ModelPlan" in msg.get("content", "") for msg in agent.chat_history)
        )

    async def test_modeler_converges_after_distinct_enum_errors(self):
        wrong_version = self._minimal_model_plan()
        wrong_version["schema_version"] = "mathmodel.model-plan.v2"
        wrong_kind = self._minimal_model_plan()
        wrong_kind["subtasks"]["ques1"]["expected_artifacts"][0]["kind"] = (
            "report"
        )
        wrong_comparator = self._minimal_model_plan()
        wrong_comparator["subtasks"]["ques1"]["acceptance_metrics"][0][
            "comparator"
        ] = "check"
        valid = self._minimal_model_plan()
        agent = ModelerAgent(
            task_id="enum-repair-test",
            model=SequencedModel(
                [
                    json.dumps(wrong_version, ensure_ascii=False),
                    json.dumps(wrong_kind, ensure_ascii=False),
                    json.dumps(wrong_comparator, ensure_ascii=False),
                    json.dumps(valid, ensure_ascii=False),
                ]
            ),
        )

        result = await agent.run(
            CoordinatorToModeler(
                questions={"ques_count": 1, "ques1": "完成建模和数值复核"},
                ques_count=1,
                problem_contract=ProblemContract(),
            )
        )

        self.assertEqual(result.model_plan.schema_version, "mathmodel.model-plan.v1")
        repair_messages = [
            str(message.get("content", ""))
            for message in agent.chat_history
            if message.get("role") == "user"
            and "固定协议" in str(message.get("content", ""))
        ]
        self.assertEqual(len(repair_messages), 3)
        self.assertTrue(all("result_table" in message for message in repair_messages))
        self.assertTrue(all("within" in message for message in repair_messages))
        self.assertIn("schema_version", repair_messages[0])
        self.assertIn("expected_artifacts.0.kind", repair_messages[1])
        self.assertIn("acceptance_metrics.0.comparator", repair_messages[2])

    async def test_modeler_repairs_non_numeric_acceptance_target(self):
        invalid = self._minimal_model_plan()
        invalid["subtasks"]["ques1"]["acceptance_metrics"][0]["target"] = "长度单位"
        valid = self._minimal_model_plan()
        agent = ModelerAgent(
            task_id="numeric-target-repair-test",
            model=SequencedModel(
                [
                    json.dumps(invalid, ensure_ascii=False),
                    json.dumps(valid, ensure_ascii=False),
                ]
            ),
        )

        result = await agent.run(
            CoordinatorToModeler(
                questions={"ques_count": 1, "ques1": "推导公式并完成量纲复核"},
                ques_count=1,
                problem_contract=ProblemContract(),
            )
        )

        metric = result.model_plan.subtasks["ques1"].acceptance_metrics[0]
        self.assertEqual(metric.target, 1.0)
        repair_message = next(
            str(message.get("content", ""))
            for message in agent.chat_history
            if message.get("role") == "user"
            and "acceptance_metrics.0.target" in str(message.get("content", ""))
        )
        self.assertIn("有限 JSON 数值", repair_message)
        self.assertIn("eq 1", repair_message)

    def test_acceptance_metric_rejects_non_finite_target(self):
        for target in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    AcceptanceMetric(
                        key="dimension_check",
                        label="量纲检查",
                        comparator="eq",
                        target=target,
                        description="以1表示量纲检查通过",
                    )


class TestStructuredModelPlan(unittest.TestCase):
    def _linear_plan(self) -> ModelPlan:
        return ModelPlan(
            eda="核验题设资源参数、单位和可行域边界。",
            subtasks={
                "ques1": SubtaskPlan(
                    inputs=["题面机器时间、人工时间和单位利润"],
                    method="定义决策变量，写出目标函数和全部资源约束，采用线性规划求解并逐项回代约束。",
                    constraints=["产品数量非负", "机器与人工资源不得超过题设上限"],
                    expected_artifacts=[
                        ExpectedArtifact(path="ques1_results.csv", kind="result_table", description="最优决策变量与目标函数值"),
                        ExpectedArtifact(path="ques1_constraints.csv", kind="constraint_table", description="各资源约束的松弛量"),
                    ],
                    acceptance_metrics=[
                        AcceptanceMetric(key="objective_value", label="最优目标值", comparator="ge", target=0, unit="元", description="由线性目标函数计算"),
                        AcceptanceMetric(key="max_constraint_violation", label="最大约束违反量", comparator="le", target=0, description="逐项回代资源约束"),
                    ],
                    visualization="绘制可行域边界和资源敏感性折线图。",
                )
            },
            sensitivity_analysis="将机器时间增加10小时，比较最优目标值变化。",
        )

    def test_linear_programming_profile_requires_machine_readable_evidence(self):
        contract = build_problem_contract(
            "某工厂最优生产 A、B 产品，最大利润，受机器时间和人工时间资源约束。"
        )
        response = ModelerToCoder(model_plan=self._linear_plan())
        result = validate_modeler_plan(
            contract,
            response,
            expected_question_keys={"ques1"},
            questions={"ques1": "求最优生产方案和最大利润。"},
        )
        self.assertTrue(result.valid, result.model_dump_json())
        self.assertIn(
            "linear_programming_evidence",
            {item.key for item in contract.required_requirements},
        )
        self.assertIn("预期产物", response.questions_solution["ques1"])

    def test_exact_question_coverage_is_checked(self):
        plan = self._linear_plan()
        result = validate_modeler_plan(
            ProblemContract(),
            ModelerToCoder(model_plan=plan),
            expected_question_keys={"ques1", "ques2"},
        )
        self.assertFalse(result.valid)
        self.assertIn("ques2", " ".join(result.missing_requirements))

    def test_linear_programming_sensitivity_subtask_need_not_repeat_constraint_table(self):
        plan = self._linear_plan()
        plan.subtasks["ques2"] = SubtaskPlan(
            inputs=["问题一最优解与机器时间增加10小时的情景"],
            method="在同一线性规划模型下替换机器时间上限，重新求解并比较目标值变化。",
            constraints=["人工时间约束保持不变", "产品数量保持非负"],
            expected_artifacts=[
                ExpectedArtifact(
                    path="ques2_results.csv",
                    kind="result_table",
                    description="扩容情景的最优解与利润变化",
                )
            ],
            acceptance_metrics=[
                AcceptanceMetric(
                    key="profit_change",
                    label="扩容后的利润变化",
                    comparator="ge",
                    target=0,
                    unit="元",
                    description="比较两次线性规划求解的目标值",
                )
            ],
            visualization="绘制扩容前后的产品组合和利润对比图。",
        )
        result = validate_modeler_plan(
            build_problem_contract(
                "某工厂最优生产 A、B 产品，最大利润，受机器时间和人工时间资源约束。"
            ),
            ModelerToCoder(model_plan=plan),
            expected_question_keys={"ques1", "ques2"},
            questions={"ques1": "求最优方案", "ques2": "机器时间增加10小时后的利润变化"},
        )
        self.assertTrue(result.valid, result.model_dump_json())

    def test_open_decision_rejects_metric_that_forces_positive_conclusion(self):
        plan = self._linear_plan()
        plan.subtasks["ques1"].acceptance_metrics = [
            AcceptanceMetric(
                key="silicon_fit_improvement",
                label="多光束模型拟合改善",
                comparator="ge",
                target=0.01,
                description="比较多光束与双光束模型的拟合优度",
            )
        ]
        result = validate_modeler_plan(
            ProblemContract(),
            ModelerToCoder(model_plan=plan),
            expected_question_keys={"ques1"},
            questions={"ques1": "判断硅晶圆是否出现多光束干涉，并分析其影响。"},
        )
        self.assertFalse(result.valid)
        self.assertIn("silicon_fit_improvement", " ".join(result.violations))
        self.assertIn("结论中立", " ".join(result.violations))

    def test_open_decision_rejects_forced_significance_but_accepts_neutral_completion(self):
        plan = self._linear_plan()
        plan.subtasks["ques1"].acceptance_metrics = [
            AcceptanceMetric(
                key="comparison_p_value",
                label="模型比较显著性 p 值",
                comparator="le",
                target=0.05,
                description="通过模型比较计算显著性",
            )
        ]
        question = {"ques1": "检验是否存在额外干涉效应。"}
        forced = validate_modeler_plan(
            ProblemContract(),
            ModelerToCoder(model_plan=plan),
            expected_question_keys={"ques1"},
            questions=question,
        )
        self.assertFalse(forced.valid)

        plan.subtasks["ques1"].acceptance_metrics = [
            AcceptanceMetric(
                key="model_comparison_completed",
                label="模型比较完成标志",
                comparator="eq",
                target=1,
                description="1 表示两类候选模型均已拟合并保存可复算结果",
            )
        ]
        neutral = validate_modeler_plan(
            ProblemContract(),
            ModelerToCoder(model_plan=plan),
            expected_question_keys={"ques1"},
            questions=question,
        )
        self.assertTrue(neutral.valid, neutral.model_dump_json())

    def test_empirical_quality_threshold_requires_explicit_target_basis(self):
        plan = self._linear_plan()
        plan.subtasks["ques1"].acceptance_metrics = [
            AcceptanceMetric(
                key="rmse_fit",
                label="反射率拟合均方根误差",
                comparator="le",
                target=0.05,
                unit="%",
                description="由拟合结果直接计算，目标小于 0.05% 以验证模型",
            )
        ]
        unsupported = validate_modeler_plan(
            ProblemContract(),
            ModelerToCoder(model_plan=plan),
            expected_question_keys={"ques1"},
        )
        self.assertFalse(unsupported.valid)
        self.assertIn("rmse_fit", " ".join(unsupported.violations))
        self.assertIn("目标值依据", " ".join(unsupported.violations))

        plan.subtasks["ques1"].acceptance_metrics[0].description = (
            "0.05% 阈值依据题面明确给出的测试标准"
        )
        supported = validate_modeler_plan(
            ProblemContract(),
            ModelerToCoder(model_plan=plan),
            expected_question_keys={"ques1"},
        )
        self.assertTrue(supported.valid, supported.model_dump_json())

    def test_vague_problem_wording_cannot_be_recast_as_numeric_quality_threshold(self):
        plan = self._linear_plan()
        plan.subtasks["ques1"].acceptance_metrics = [
            AcceptanceMetric(
                key="transition_time_error",
                label="过渡时间误差",
                comparator="le",
                target=0.1,
                unit="s",
                description="阈值 0.1s 基于题面“约 2s”的模糊表述，取为目标时间的 5%。",
            )
        ]
        result = validate_modeler_plan(
            ProblemContract(),
            ModelerToCoder(model_plan=plan),
            expected_question_keys={"ques1"},
        )
        self.assertFalse(result.valid)
        self.assertIn("transition_time_error", " ".join(result.violations))

    def test_common_sense_is_not_a_physical_plausibility_threshold_basis(self):
        plan = self._linear_plan()
        plan.subtasks["ques1"].acceptance_metrics = [
            AcceptanceMetric(
                key="physical_plausibility",
                label="参数物理合理性",
                comparator="eq",
                target=1,
                description="参数处于物理常识范围时记为 1",
            )
        ]
        result = validate_modeler_plan(
            ProblemContract(),
            ModelerToCoder(model_plan=plan),
            expected_question_keys={"ques1"},
        )
        self.assertFalse(result.valid)
        self.assertIn("physical_plausibility", " ".join(result.violations))

    def test_empirical_fit_completion_flag_remains_conclusion_neutral(self):
        plan = self._linear_plan()
        plan.subtasks["ques1"].acceptance_metrics = [
            AcceptanceMetric(
                key="model_fit_completed",
                label="候选模型拟合完成标志",
                comparator="eq",
                target=1,
                description="1 表示所有候选模型均已拟合并保存可复算结果",
            )
        ]
        result = validate_modeler_plan(
            ProblemContract(),
            ModelerToCoder(model_plan=plan),
            expected_question_keys={"ques1"},
        )
        self.assertTrue(result.valid, result.model_dump_json())

    def test_neutral_words_in_description_cannot_mask_arbitrary_fit_bound(self):
        plan = self._linear_plan()
        plan.subtasks["ques1"].acceptance_metrics = [
            AcceptanceMetric(
                key="fit_error_bound",
                label="模型拟合误差上限",
                comparator="le",
                target=100,
                unit="%",
                description="RMSE 小于 100%，以确保数值有限且结果可复算",
            )
        ]
        result = validate_modeler_plan(
            ProblemContract(),
            ModelerToCoder(model_plan=plan),
            expected_question_keys={"ques1"},
        )
        self.assertFalse(result.valid)
        self.assertIn("fit_error_bound", " ".join(result.violations))

    def test_zero_bound_physical_feasibility_is_not_an_empirical_threshold(self):
        plan = self._linear_plan()
        plan.subtasks["ques1"].acceptance_metrics = [
            AcceptanceMetric(
                key="thickness_positive",
                label="外延层厚度为正",
                comparator="gt",
                target=0,
                unit="μm",
                description="厚度大于零用于验证变量定义和物理可行性",
            )
        ]
        result = validate_modeler_plan(
            ProblemContract(),
            ModelerToCoder(model_plan=plan),
            expected_question_keys={"ques1"},
        )
        self.assertTrue(result.valid, result.model_dump_json())

    def test_generic_profiles_are_selected_by_problem_language(self):
        data_contract = build_problem_contract("附件给出样本数据，请清洗数据并建立回归预测模型。")
        physics_contract = build_problem_contract("研究流量和压力随时间演化的物理仿真系统。")
        self.assertIn(
            "data_analysis_evidence",
            {item.key for item in data_contract.required_requirements},
        )
        self.assertIn(
            "physical_simulation_evidence",
            {item.key for item in physics_contract.required_requirements},
        )


if __name__ == "__main__":
    unittest.main()
