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
_PRESSURE_TARGET = re.compile(
    r"(?:压力|油管压力|高压油管压力)[^。；;\n]{0,24}?"
    r"(?:稳定在|保持在|维持在|目标(?:为|是)?|达到)\s*"
    r"(\d+(?:\.\d+)?)\s*(?:MPa|兆帕)",
    re.IGNORECASE,
)

_ATTACHMENT_ANGLE_SAMPLE_PAIR = re.compile(
    r"附件(\d+)(?:\.xlsx)?(?:和|与|、|及)附件(\d+)(?:\.xlsx)?"
    r"[^。；]{0,100}?入射角(?:分别)?(?:为|是)?"
    r"(\d+(?:\.\d+)?)\s*[°度](?:和|与|、|及)"
    r"(\d+(?:\.\d+)?)\s*[°度]"
    r"[^。；]{0,60}?同一(?:块|片|个)?([^，。；]{1,24}?)(?:的)?测试结果",
    re.IGNORECASE,
)

_SAME_SAMPLE = re.compile(r"同一(?:块|片|个)?[^。；]{0,10}?(?:晶圆|样品)")
_INDEPENDENT_SAMPLE = re.compile(
    r"(?:(?:不同|独立|分别的)(?:碳化硅|硅)?(?:晶圆片?|样品)"
    r"|(?:两块|两片|两个)(?:相互|彼此)?(?:不同|独立)?(?:的)?"
    r"(?:碳化硅|硅)?(?:晶圆片?|样品)"
    r"|(?:晶圆片?|样品)(?:彼此|相互|各自|分别)?"
    r"(?:为|是|均为|视为|作为)?(?:不同|独立))"
)
# 方案常把契约禁令原样写进约束（如“不得改写为不同样品”），这属于遵守而非违规；
# 与 _OVERRIDE_NEGATION 同思路，仅当独立样品表述前没有近距离否定词时才算改写。
_INDEPENDENT_SAMPLE_NEGATION = re.compile(
    r"(?:不得|不能|不可|不应|不要|禁止|避免|拒绝|切勿|而不是|而非|不将|不视为|不当作|不改写)"
)


def _contains_independent_sample_claim(text: str) -> bool:
    """Detect affirmative independent-sample rewrites, ignoring prohibitions."""
    for clause in re.split(r"[。；;\n]", text):
        compact = re.sub(r"\s+", "", clause)
        if not compact:
            continue
        for match in _INDEPENDENT_SAMPLE.finditer(compact):
            prefix = compact[max(0, match.start() - 16) : match.start()]
            if _INDEPENDENT_SAMPLE_NEGATION.search(prefix):
                continue
            return True
    return False

_OVERRIDE_NEGATION = re.compile(
    r"(?:不|不得|禁止|避免|拒绝|不能|不可|不应|无需)[^。；]{0,16}"
    r"(?:(?<![\d.])0(?:\.0+)?\s*[°度]|垂直入射|法向入射|正入射)"
)
# 负向断言须同时排除数字与小数点：否则 10.0°/15.0度 里的 “.0°” 会被误认成 0°。
_ZERO_DEGREE = re.compile(r"(?<![\d.])0(?:\.0+)?\s*[°度]")

_OPEN_ENDED_DECISION_QUESTION = re.compile(
    r"(?:(?:判断|判定|检验|验证|确定|研究|分析).{0,24}(?:是否|有无)"
    r"|(?:是否|有无).{0,24}(?:存在|发生|显著|必要|影响|改善|提升)"
    r"|\bwhether\b)",
    re.IGNORECASE,
)
_DIRECTIONAL_OUTCOME_METRIC = re.compile(
    r"(?:improvement|increase|gain|effect|提升|改善|改进|增益|效果)",
    re.IGNORECASE,
)
_SIGNIFICANCE_OUTCOME_METRIC = re.compile(
    r"(?:p[_ -]?value|significance|significant|p值|显著性|显著)",
    re.IGNORECASE,
)
_BOOLEAN_OUTCOME_METRIC = re.compile(
    r"(?:existence|occurrence|detected|存在性|是否存在|发生标志|效果标志)",
    re.IGNORECASE,
)
_EMPIRICAL_QUALITY_METRIC = re.compile(
    r"(?:rmse|mae|mse|r[_ -]?(?:2|squared)|fit[_ -]?(?:r2|error|quality|score)"
    r"|fitting[_ -]?(?:error|quality|score)|error[_ -]?(?:bound|rate)"
    r"|deviation|accuracy|plausibility|p[_ -]?value|significance|time[_ -]?error"
    r"|均方根|拟合(?:误差|优度|精度)|误差(?:界|率|上限)|时间误差|偏差|准确率|精度"
    r"|合理性|p值|显著性)",
    re.IGNORECASE,
)
_NEUTRAL_COMPLETION_METRIC = re.compile(
    r"(?:completed|completion|coverage|finite|reproducib|完成标志|完成率|覆盖(?:数|率)?"
    r"|数值有限|可复算)",
    re.IGNORECASE,
)
_ZERO_BOUND_FEASIBILITY_METRIC = re.compile(
    r"(?:positive|positivity|non[_ -]?negative|greater[_ -]?than[_ -]?zero|"
    r"正值|为正|非负)",
    re.IGNORECASE,
)
_THRESHOLD_TERM = (
    r"(?:阈值|目标值?|界限|上限|下限|容差|判据|"
    r"threshold|target|bound|limit|tolerance|criterion)"
)
_THRESHOLD_SOURCE = (
    r"(?:题面|题设|附件|数据(?:统计|分布|分位数|噪声)|样本统计|训练集|验证集|"
    r"交叉验证|基线|对照|文献|论文|标准|规范|"
    r"problem statement|attachment|data (?:statistic|distribution|quantile|noise)|"
    r"training set|validation set|cross-validation|baseline|reference|literature|standard)"
)
_THRESHOLD_BASIS = re.compile(
    rf"(?:{_THRESHOLD_TERM}.{{0,32}}(?:依据|来自|取自|按照|基于|由|from|based on)"
    rf".{{0,32}}{_THRESHOLD_SOURCE}"
    rf"|(?:依据|按照|基于|由|using|based on).{{0,24}}{_THRESHOLD_SOURCE}"
    rf".{{0,32}}(?:确定|设定|给出|规定|导出|计算|估计|determin|derive|set|specif)"
    rf".{{0,24}}{_THRESHOLD_TERM}?"
    rf"|{_THRESHOLD_SOURCE}.{{0,32}}(?:给出|规定|确定|导出|作为|specif|determin|derive)"
    rf".{{0,24}}{_THRESHOLD_TERM})",
    re.IGNORECASE,
)
_VAGUE_PROMPT_AS_NUMERIC_BASIS = re.compile(
    r"(?:题面|题设).{0,48}(?:约|左右|尽可能|定性|模糊).{0,96}"
    r"(?:阈值|容许|允许|误差|偏差|[0-9]+\s*%)",
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
    attachment_pairs = list(_ATTACHMENT_ANGLE_SAMPLE_PAIR.finditer(normalized))
    incident_angles: list[float] = []
    for pair in attachment_pairs:
        first_attachment, second_attachment, first_angle, second_angle, material = (
            pair.groups()
        )
        for raw_angle in (first_angle, second_angle):
            angle = float(raw_angle)
            if angle not in incident_angles:
                incident_angles.append(angle)
        material = material.removeprefix("针对").strip()
        _append_requirement_once(
            contract,
            ContractRequirement(
                key=(
                    "paired_angle_same_sample_"
                    f"{first_attachment}_{second_attachment}"
                ),
                label=(
                    f"附件{first_attachment}/{second_attachment}须按同一{material}在"
                    f"{float(first_angle):g}°与{float(second_angle):g}°下的配对测量联合建模"
                ),
                evidence_terms=[
                    f"附件{first_attachment}",
                    f"附件{second_attachment}",
                    f"{float(first_angle):g}°",
                    f"{float(second_angle):g}°",
                    "同一",
                ],
                source="题面附件说明中的样品、附件与双角度对应关系",
            ),
        )
    for index, angle in enumerate(incident_angles, start=1):
        contract.immutable_parameters.append(
            ContractParameter(
                key=f"incident_angle_{index}",
                label=f"附件测量入射角 {index}",
                symbol=f"theta_{index}",
                value=angle,
                unit="°",
                source="题面附件说明中的实测入射角",
            )
        )
    if incident_angles:
        _append_requirement_once(
            contract,
            ContractRequirement(
                key="incident_angle_pair",
                label=(
                    "实测数据算法须使用题面给定的 "
                    + " 与 ".join(f"{angle:g}°" for angle in incident_angles)
                    + " 入射角，不得替换为 0° 或垂直入射"
                ),
                evidence_terms=[f"{angle:g}°" for angle in incident_angles],
                source="题面附件说明中的实测入射角",
            ),
        )
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
    for match in _PRESSURE_TARGET.finditer(normalized):
        target_pressure = float(match.group(1))
        target_key = f"{target_pressure:g}".replace(".", "_")
        _append_requirement_once(
            contract,
            ContractRequirement(
                key=f"target_pressure_{target_key}_mpa",
                label=f"方案须检验压力目标为 {target_pressure:g} MPa 的约束是否满足",
                evidence_terms=[f"{target_pressure:g}MPa"],
                source="题面原文的压力目标",
            ),
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
    sections = _plan_sections(plan)
    if sections:
        return "\n".join(sections.values())
    if hasattr(plan, "model_plan"):
        plan = getattr(plan, "model_plan") or plan
    if hasattr(plan, "to_questions_solution"):
        return "\n".join(str(value) for value in plan.to_questions_solution().values())
    if isinstance(plan, dict):
        return "\n".join(str(value) for value in plan.values())
    return str(plan)


def _plan_sections(plan: object) -> dict[str, str]:
    """Return the compatibility question map for structured and legacy plans."""
    model_plan = getattr(plan, "model_plan", None)
    if model_plan is not None and hasattr(model_plan, "to_questions_solution"):
        return {
            str(key): str(value)
            for key, value in model_plan.to_questions_solution().items()
        }
    questions_solution = getattr(plan, "questions_solution", None)
    if isinstance(questions_solution, dict):
        return {str(key): str(value) for key, value in questions_solution.items()}
    if isinstance(plan, dict):
        return {str(key): str(value) for key, value in plan.items()}
    return {}


def _mentions_attachment_pair(text: str, first: str, second: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if f"附件{first}" in compact and f"附件{second}" in compact:
        return True
    return bool(
        re.search(
            rf"附件{re.escape(first)}(?:和|与|、|及|/)(?:附件)?{re.escape(second)}",
            compact,
        )
    )


def _mentions_angle(text: str, angle: float) -> bool:
    return bool(
        re.search(
            rf"(?<!\d){float(angle):g}(?:\.0+)?\s*[°度]",
            text,
        )
    )


def _contains_incident_angle_override(text: str) -> bool:
    """Detect affirmative replacement by 0°/normal incidence, ignoring prohibitions."""
    for clause in re.split(r"[。；;\n]", text):
        compact = re.sub(r"\s+", "", clause)
        if not compact or _OVERRIDE_NEGATION.search(compact):
            continue
        if any(term in compact for term in ("垂直入射", "法向入射", "正入射")):
            return True
        if (
            _ZERO_DEGREE.search(compact)
            and re.search(r"(?:入射角|theta|θ)", compact, re.IGNORECASE)
            and re.search(r"(?:取|设|令|假设|近似|统一|采用|按|视为|=|为)", compact)
        ):
            return True
    return False


def _paired_requirement_plan_text(
    requirement: ContractRequirement,
    plan: object,
    questions: dict[str, str | int] | None,
) -> tuple[str, str, str]:
    """Select the subtask that owns a concrete attachment pair requirement."""
    match = re.fullmatch(r"paired_angle_same_sample_(\d+)_(\d+)", requirement.key)
    if match is None:
        raise ValueError(f"非法附件配对契约键: {requirement.key}")
    first, second = match.groups()
    sections = _plan_sections(plan)
    matched_keys = [
        key
        for key, question in (questions or {}).items()
        if key in sections and _mentions_attachment_pair(str(question), first, second)
    ]
    if not matched_keys:
        conventional_key = {("1", "2"): "ques2", ("3", "4"): "ques3"}.get(
            (first, second)
        )
        if conventional_key in sections:
            matched_keys = [conventional_key]
    selected = "\n".join(sections[key] for key in matched_keys)
    return selected or _plan_text(plan), first, second


def _subtask_plans(plan: object) -> dict[str, object]:
    model_plan = getattr(plan, "model_plan", None)
    if model_plan is not None:
        return dict(model_plan.subtasks)
    if hasattr(plan, "subtasks"):
        return dict(getattr(plan, "subtasks"))
    return {}


def _conclusion_forcing_metrics(plan: object, question: str) -> list[str]:
    """Find acceptance thresholds that predetermine an open scientific decision."""
    if not _OPEN_ENDED_DECISION_QUESTION.search(question):
        return []
    issues: list[str] = []
    for metric in getattr(plan, "acceptance_metrics", []):
        comparator = str(getattr(metric, "comparator", ""))
        target = float(getattr(metric, "target", 0))
        metric_text = " ".join(
            str(getattr(metric, field, ""))
            for field in ("key", "label", "description")
        )
        forces_direction = (
            _DIRECTIONAL_OUTCOME_METRIC.search(metric_text)
            and (
                (comparator in {"ge", "gt"} and target > 0)
                or (comparator in {"le", "lt"} and target < 0)
            )
        )
        forces_significance = (
            _SIGNIFICANCE_OUTCOME_METRIC.search(metric_text)
            and comparator in {"le", "lt"}
            and 0 <= target < 1
        )
        forces_boolean_outcome = (
            _BOOLEAN_OUTCOME_METRIC.search(metric_text)
            and comparator == "eq"
            and target in {0, 1}
        )
        if forces_direction or forces_significance or forces_boolean_outcome:
            issues.append(
                f"{getattr(metric, 'key', 'unknown')} {comparator} {target:g}"
            )
    return issues


def _unsupported_empirical_thresholds(plan: object) -> list[str]:
    """Find empirical quality targets whose numeric cutoff has no stated basis."""
    issues: list[str] = []
    for metric in getattr(plan, "acceptance_metrics", []):
        identity_text = " ".join(
            str(getattr(metric, field, "")) for field in ("key", "label")
        )
        description = str(getattr(metric, "description", ""))
        metric_text = f"{identity_text} {description}"
        comparator = str(getattr(metric, "comparator", ""))
        target = float(getattr(metric, "target", 0))
        if not _EMPIRICAL_QUALITY_METRIC.search(metric_text):
            continue
        if _NEUTRAL_COMPLETION_METRIC.search(identity_text):
            continue
        if (
            _ZERO_BOUND_FEASIBILITY_METRIC.search(identity_text)
            and comparator in {"ge", "gt"}
            and target == 0
        ):
            continue
        # “约”“左右”“尽可能”等题面语言说明需要报告目标和结果，不能反推
        # 一个未经题面给出的 5%/0.1 秒硬质量门槛。否则模型会把自己的
        # 假设变成必须通过的 acceptance contract，造成无解或伪造证据。
        if _THRESHOLD_BASIS.search(description) and not _VAGUE_PROMPT_AS_NUMERIC_BASIS.search(description):
            continue
        issues.append(f"{getattr(metric, 'key', 'unknown')} {comparator} {target:g}")
    return issues


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
    for key, subtask in subtasks.items():
        question = str((questions or {}).get(key, ""))
        forcing_metrics = _conclusion_forcing_metrics(subtask, question)
        if forcing_metrics:
            violations.append(
                f"{key} 的验收指标在执行前强制开放性判定结论："
                + "、".join(forcing_metrics)
                + "；请改用模型比较已完成、数据覆盖、数值有限或结果可复算等结论中立指标"
            )
        unsupported_thresholds = _unsupported_empirical_thresholds(subtask)
        if unsupported_thresholds:
            violations.append(
                f"{key} 的经验质量阈值缺少目标值依据："
                + "、".join(unsupported_thresholds)
                + "；description 必须说明阈值来自题面/附件、数据统计或交叉验证、"
                "基线、文献或标准；仅说明指标如何计算或声称符合常识不构成依据"
            )
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
        if requirement.key.startswith("paired_angle_same_sample_"):
            requirement_text, first, second = _paired_requirement_plan_text(
                requirement, plan, questions
            )
            expected_angles = [
                float(parameter.value)
                for parameter in contract.immutable_parameters
                if parameter.key.startswith("incident_angle_")
            ]
            has_pair = _mentions_attachment_pair(requirement_text, first, second)
            has_same_sample = bool(_SAME_SAMPLE.search(requirement_text))
            has_angles = all(
                _mentions_angle(requirement_text, angle) for angle in expected_angles
            )
            if _contains_independent_sample_claim(requirement_text):
                violations.append(
                    f"附件{first}/{second}被方案改写为不同或独立样品"
                )
            if _contains_incident_angle_override(requirement_text):
                violations.append(
                    f"附件{first}/{second}的实测入射角被方案替换为 0° 或垂直入射"
                )
            covered = has_pair and has_same_sample and has_angles
        elif requirement.key == "incident_angle_pair":
            expected_angles = [
                float(parameter.value)
                for parameter in contract.immutable_parameters
                if parameter.key.startswith("incident_angle_")
            ]
            covered = all(_mentions_angle(normalized, angle) for angle in expected_angles)
        elif requirement.key == "problem1_transition_times":
            covered = all(re.search(rf"{second}(?:秒|s)", normalized, re.IGNORECASE) for second in (2, 5, 10))
        elif requirement.key == "problem1_valve_duration_outputs":
            covered = (
                "开启时长" in normalized
                and bool(re.search(r"100\s*(?:MPa|兆帕)", normalized, re.IGNORECASE))
                and bool(re.search(r"150\s*(?:MPa|兆帕)", normalized, re.IGNORECASE))
                and all(re.search(rf"{second}(?:秒|s)", normalized, re.IGNORECASE) for second in (2, 5, 10))
            )
        elif requirement.key.startswith("target_pressure_"):
            covered = all(term in normalized for term in requirement.evidence_terms)
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
