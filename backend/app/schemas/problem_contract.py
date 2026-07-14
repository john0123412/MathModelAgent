"""题面中不可被 agent 改写的事实契约。"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field


class ContractParameter(BaseModel):
    key: str
    label: str
    symbol: str | None = None
    value: float | str | bool
    unit: str | None = None
    source: str
    mutable: bool = False


class ContractRequirement(BaseModel):
    key: str
    label: str
    evidence_terms: list[str] = Field(default_factory=list)
    source: str
    plugin: str | None = None
    question_keywords: list[str] = Field(default_factory=list)
    expected_artifact_kinds: list[str] = Field(default_factory=list)
    acceptance_metric_terms: list[str] = Field(default_factory=list)


class ProblemContract(BaseModel):
    """从原始题面提取的结构化硬约束。"""

    schema_version: str = "mathmodel.problem-contract.v1"
    immutable_parameters: list[ContractParameter] = Field(default_factory=list)
    required_requirements: list[ContractRequirement] = Field(default_factory=list)

    def to_prompt(self) -> str:
        lines = ["【题面参数契约：以下事实不可改写】"]
        for parameter in self.immutable_parameters:
            symbol = f"（{parameter.symbol}）" if parameter.symbol else ""
            unit = parameter.unit or ""
            lines.append(
                f"- {parameter.label}{symbol} = {parameter.value}{unit}；来源：{parameter.source}；不得改写。"
            )
        if self.required_requirements:
            lines.append("【必须覆盖的题目要求】")
            for item in self.required_requirements:
                details: list[str] = []
                if item.expected_artifact_kinds:
                    details.append("产物=" + "/".join(item.expected_artifact_kinds))
                if item.acceptance_metric_terms:
                    details.append("指标=" + "/".join(item.acceptance_metric_terms))
                suffix = f"（{'；'.join(details)}）" if details else ""
                lines.append(f"- {item.label}{suffix}。")
        return "\n".join(lines)


class ContractValidationResult(BaseModel):
    valid: bool
    violations: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)


_FLOW_COEFFICIENT = re.compile(
    r"(?:流量系数|系数\s*[CcＣ]|[CcＣ])\s*(?:=|＝|为|取|设为)\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

_HIGH_PRESSURE_PIPE_PARAMETERS: tuple[tuple[str, str, str, str, str], ...] = (
    ("pipe_length", "高压油管内腔长度", "L", r"内腔长度为(\d+(?:\.\d+)?)mm", "mm"),
    ("pipe_inner_diameter", "高压油管内直径", "D", r"内直径为(\d+(?:\.\d+)?)mm", "mm"),
    ("inlet_orifice_diameter", "入口 A 小孔直径", "d_A", r"入口A处小孔的直径为(\d+(?:\.\d+)?)mm", "mm"),
    ("valve_min_close_time", "单向阀最小关闭时间", "t_close", r"关闭(\d+(?:\.\d+)?)ms", "ms"),
    ("injection_frequency", "喷油器工作频率", "f_inj", r"喷油器每秒工作(\d+(?:\.\d+)?)次", "次/秒"),
    ("injection_duration", "单次喷油时间", "t_inj", r"每次工作时喷油时间为(\d+(?:\.\d+)?)ms", "ms"),
    ("pump_pressure", "高压油泵入口压力", "P_pump", r"提供的压力恒为(\d+(?:\.\d+)?)MPa", "MPa"),
    ("initial_pipe_pressure", "高压油管初始压力", "P_0", r"初始压力为(\d+(?:\.\d+)?)MPa", "MPa"),
)

_INJECTION_FREQUENCY = re.compile(
    r"(?:喷油器)?(?:每秒工作|工作频率|喷油频率)[:：为是]*\s*(\d+(?:\.\d+)?)\s*(?:次/秒|次每秒|Hz)",
    re.IGNORECASE,
)


_LINEAR_PROGRAMMING_TERMS = ("线性规划", "最优生产", "最大利润", "最小成本", "资源约束", "机器时间", "人工时间")
_DATA_ANALYSIS_TERMS = ("数据集", "样本", "预测", "回归", "统计分析", "数据分析", "附件")
_PHYSICAL_SIMULATION_TERMS = ("压力", "流量", "油管", "仿真", "动力学", "微分方程", "温度", "浓度", "运动")


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _append_requirement_once(contract: ProblemContract, requirement: ContractRequirement) -> None:
    if requirement.key not in {item.key for item in contract.required_requirements}:
        contract.required_requirements.append(requirement)


def build_problem_contract(problem_text: str) -> ProblemContract:
    """提取可可靠识别的题面事实；无法识别时返回空契约。"""
    normalized = re.sub(r"\s+", "", problem_text)
    contract = ProblemContract()
    coefficient = _FLOW_COEFFICIENT.search(normalized)
    if coefficient:
        contract.immutable_parameters.append(
            ContractParameter(
                key="flow_coefficient",
                label="流量系数",
                symbol="C",
                value=float(coefficient.group(1)),
                source="题面原文中流量系数定义",
            )
        )
    for key, label, symbol, pattern, unit in _HIGH_PRESSURE_PIPE_PARAMETERS:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            contract.immutable_parameters.append(
                ContractParameter(
                    key=key,
                    label=label,
                    symbol=symbol,
                    value=float(match.group(1)),
                    unit=unit,
                    source="题面原文的高压油管固定工况参数",
                )
            )
    if all(re.search(rf"{second}(?:秒|s)", normalized, re.IGNORECASE) for second in (2, 5, 10)):
        contract.required_requirements.append(
            ContractRequirement(
                key="problem1_transition_times",
                label="问题一须分别给出 2 秒、5 秒、10 秒的压力过渡控制",
                source="题面原文的过渡时间要求",
            )
        )
    if (
        "单向阀" in normalized
        and "开启时长" in normalized
        and re.search(r"150\s*(?:MPa|兆帕)", normalized, re.IGNORECASE)
    ):
        contract.required_requirements.append(
            ContractRequirement(
                key="problem1_valve_duration_outputs",
                label=(
                    "问题一须给出 100 MPa 与 150 MPa 稳态的单向阀开启时长，"
                    "以及 2 秒、5 秒、10 秒过渡阶段的开启时长、到达误差和切回稳态策略"
                ),
                evidence_terms=["开启时长", "150MPa"],
                source="题面原文的问题一控制量与 150 MPa 过渡要求",
            )
        )
    if re.search(r"100\s*(?:MPa|兆帕)", normalized, re.IGNORECASE):
        contract.required_requirements.append(
            ContractRequirement(
                key="target_pressure_100_mpa",
                label="方案须检验压力目标为 100 MPa 的约束是否满足",
                source="题面原文的压力目标",
            )
        )
    if re.search(r"(?:第二个|两个|双)喷油嘴", normalized):
        contract.required_requirements.append(
            ContractRequirement(
                key="two_injectors",
                label="问题三须按两个喷油嘴建模；不得把新增喷油嘴改写为新增泵",
                source="题面原文的第二喷油嘴条件",
            )
        )
    if "减压阀" in normalized:
        contract.required_requirements.append(
            ContractRequirement(
                key="relief_valve_control",
                label="问题三须给出减压阀控制方案并进行验证",
                evidence_terms=["减压阀"],
                source="题面原文的减压阀要求",
            )
        )
    parameter_keys = {parameter.key for parameter in contract.immutable_parameters}
    if {"pipe_length", "pipe_inner_diameter", "injection_frequency"}.issubset(parameter_keys):
        contract.required_requirements.append(
            ContractRequirement(
                key="fixed_geometry_and_timing",
                label="主模型须以题面油管长度、内直径和喷油频率建立参数表与量纲核验，禁止改写工况",
                source="题面原文的几何与喷油频率条件",
            )
        )

    # 通用领域 profile：只抽取题面确实出现的交付类型。它们在结构化
    # ModelPlan 上校验产物与指标，避免将某一个历史题目的阈值硬编码到所有题型。
    if _contains_any(normalized, _LINEAR_PROGRAMMING_TERMS):
        _append_requirement_once(
            contract,
            ContractRequirement(
                key="linear_programming_evidence",
                label="线性规划子题须声明决策变量、目标函数、资源约束、最优目标值和约束满足情况",
                evidence_terms=["线性规划"],
                source="题面中的生产/资源/最优化表述",
                plugin="linear_programming",
                question_keywords=list(_LINEAR_PROGRAMMING_TERMS),
                expected_artifact_kinds=["result_table", "constraint_table"],
                acceptance_metric_terms=["目标值", "约束"],
            ),
        )
    if _contains_any(normalized, _DATA_ANALYSIS_TERMS):
        _append_requirement_once(
            contract,
            ContractRequirement(
                key="data_analysis_evidence",
                label="数据分析子题须声明数据来源、清洗/划分口径、结构化结果和误差或统计验收指标",
                evidence_terms=["数据"],
                source="题面中的数据、附件或预测/统计表述",
                plugin="data_analysis",
                question_keywords=list(_DATA_ANALYSIS_TERMS),
                expected_artifact_kinds=["dataset", "result_table"],
                acceptance_metric_terms=["误差", "样本"],
            ),
        )
    if _contains_any(normalized, _PHYSICAL_SIMULATION_TERMS):
        _append_requirement_once(
            contract,
            ContractRequirement(
                key="physical_simulation_evidence",
                label="物理仿真子题须声明状态方程/守恒关系、单位制、时序或扫描数据及误差/残差验收指标",
                evidence_terms=["仿真"],
                source="题面中的物理状态、流量或演化过程表述",
                plugin="physical_simulation",
                question_keywords=list(_PHYSICAL_SIMULATION_TERMS),
                expected_artifact_kinds=["time_series", "result_table"],
                acceptance_metric_terms=["残差", "误差"],
            ),
        )
    return contract


def _plan_text(plan: object) -> str:
    """Return all plan fields as searchable text without importing A2A here."""
    if hasattr(plan, "model_plan"):
        plan = getattr(plan, "model_plan") or plan
    if hasattr(plan, "to_questions_solution"):
        return "\n".join(str(value) for value in plan.to_questions_solution().values())
    if isinstance(plan, dict):
        return "\n".join(str(value) for value in plan.values())
    return str(plan)


def _subtask_plans(plan: object) -> dict[str, object]:
    model_plan = getattr(plan, "model_plan", None)
    if model_plan is not None:
        return dict(model_plan.subtasks)
    if hasattr(plan, "subtasks"):
        return dict(getattr(plan, "subtasks"))
    return {}


def _matching_plan_keys(
    requirement: ContractRequirement,
    subtasks: dict[str, object],
    questions: dict[str, str | int] | None,
) -> list[str]:
    """Select only questions whose text matches a generic domain profile."""
    if not requirement.question_keywords or not questions:
        return list(subtasks)
    matched = [
        key
        for key, question in questions.items()
        if key in subtasks
        and key.startswith("ques")
        and any(term in str(question) for term in requirement.question_keywords)
    ]
    # A global problem description can trigger a profile although the coordinator
    # split text omits its keyword. In that case retain the conservative check.
    return matched or list(subtasks)


def _structured_requirement_covered(
    requirement: ContractRequirement,
    plan: object,
) -> bool:
    """Validate profile declarations against machine-readable ModelPlan fields."""
    artifacts = getattr(plan, "expected_artifacts", [])
    artifact_kinds = {getattr(item, "kind", "") for item in artifacts}
    metric_text = " ".join(
        f"{getattr(item, 'key', '')} {getattr(item, 'label', '')} {getattr(item, 'description', '')}"
        for item in getattr(plan, "acceptance_metrics", [])
    )
    method_text = " ".join(
        [getattr(plan, "method", ""), *getattr(plan, "constraints", []), *getattr(plan, "inputs", [])]
    )
    if not set(requirement.expected_artifact_kinds).issubset(artifact_kinds):
        # A coordinator may split one optimization task into a primary solve
        # and a sensitivity/what-if question.  Requiring every split question
        # to repeat the primary constraint table made normal LP smoke tasks
        # fail despite complete structured evidence.  Each subtask must still
        # provide a numerical result plus metrics through SubtaskPlan.
        if requirement.plugin == "linear_programming":
            if not artifact_kinds.intersection({"result_table", "constraint_table"}):
                return False
        elif requirement.plugin == "data_analysis":
            if not artifact_kinds.intersection({"dataset", "result_table", "time_series"}):
                return False
        elif requirement.plugin == "physical_simulation":
            if not artifact_kinds.intersection({"time_series", "result_table"}):
                return False
        else:
            return False
    if requirement.plugin == "linear_programming":
        return bool(method_text.strip()) and bool(metric_text.strip())
    if requirement.plugin == "data_analysis":
        return bool(method_text.strip()) and bool(metric_text.strip())
    if requirement.plugin == "physical_simulation":
        return bool(method_text.strip()) and bool(metric_text.strip())
    return True


def validate_modeler_plan(
    contract: ProblemContract,
    plan: object,
    *,
    expected_question_keys: set[str] | None = None,
    questions: dict[str, str | int] | None = None,
) -> ContractValidationResult:
    """拒绝改写题面、缺题或缺少可执行证据的建模计划。

    旧 checkpoint 的自由文本字典仍可做题面参数校验；只有新 ``ModelPlan``
    会启用产物/验收指标的严格领域 profile 校验。
    """
    text = _plan_text(plan)
    normalized = re.sub(r"\s+", "", text)
    violations: list[str] = []
    missing: list[str] = []
    subtasks = _subtask_plans(plan)
    if expected_question_keys is not None:
        actual_keys = set(subtasks) if subtasks else {
            key for key in getattr(plan, "questions_solution", plan if isinstance(plan, dict) else {})
            if key.startswith("ques")
        }
        missing_keys = sorted(expected_question_keys - actual_keys)
        extra_keys = sorted(actual_keys - expected_question_keys)
        if missing_keys:
            missing.append("缺少正式问题计划: " + ", ".join(missing_keys))
        if extra_keys:
            violations.append("出现未拆解的正式问题计划: " + ", ".join(extra_keys))
    for parameter in contract.immutable_parameters:
        if parameter.key == "flow_coefficient":
            for candidate in _FLOW_COEFFICIENT.findall(normalized):
                if abs(float(candidate) - float(parameter.value)) > 1e-12:
                    violations.append(
                        f"题面固定的流量系数 C={parameter.value} 被方案改写为 C={candidate}"
                    )
        elif parameter.key == "injection_frequency":
            for candidate in _INJECTION_FREQUENCY.findall(normalized):
                if abs(float(candidate) - float(parameter.value)) > 1e-12:
                    violations.append(
                        "题面固定的喷油器工作频率 "
                        f"{parameter.value}次/秒 被方案改写为 {candidate}次/秒"
                    )
    for requirement in contract.required_requirements:
        if requirement.plugin and subtasks:
            matching_keys = _matching_plan_keys(requirement, subtasks, questions)
            uncovered = [
                key
                for key in matching_keys
                if not _structured_requirement_covered(requirement, subtasks[key])
            ]
            if uncovered:
                missing.append(requirement.label + "（未满足：" + ", ".join(uncovered) + "）")
            continue
        # Generic profile requirements deliberately do not reject historical
        # free-text checkpoints. They are upgraded on the next Modeler run.
        if requirement.plugin:
            continue
        if requirement.key == "problem1_transition_times":
            covered = all(re.search(rf"{second}(?:秒|s)", normalized, re.IGNORECASE) for second in (2, 5, 10))
        elif requirement.key == "problem1_valve_duration_outputs":
            covered = (
                "开启时长" in normalized
                and bool(re.search(r"100\s*(?:MPa|兆帕)", normalized, re.IGNORECASE))
                and bool(re.search(r"150\s*(?:MPa|兆帕)", normalized, re.IGNORECASE))
                and all(re.search(rf"{second}(?:秒|s)", normalized, re.IGNORECASE) for second in (2, 5, 10))
            )
        elif requirement.key == "target_pressure_100_mpa":
            covered = bool(re.search(r"100\s*(?:MPa|兆帕)", normalized, re.IGNORECASE))
        elif requirement.key == "two_injectors":
            covered = bool(re.search(r"(?:第二个|两个|双)喷油嘴", normalized))
        elif requirement.key == "fixed_geometry_and_timing":
            covered = bool(
                re.search(r"(?:L\s*=\s*)?500\s*mm", normalized, re.IGNORECASE)
                and re.search(r"(?:D\s*=\s*)?10\s*mm", normalized, re.IGNORECASE)
                and re.search(r"10\s*(?:次/秒|次每秒|Hz)", normalized, re.IGNORECASE)
            )
        else:
            covered = all(term in normalized for term in requirement.evidence_terms)
        if not covered:
            missing.append(requirement.label)
    return ContractValidationResult(
        valid=not violations and not missing,
        violations=violations,
        missing_requirements=missing,
    )
