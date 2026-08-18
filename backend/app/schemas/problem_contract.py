"""题面中不可被 agent 改写的事实契约。"""

from __future__ import annotations

import json
import re
from typing import Literal

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


class BoundaryCondition(BaseModel):
    axis: Literal["x", "y", "z", "radial", "other"]
    boundary_type: Literal[
        "periodic",
        "clamped_electrode",
        "absorbing",
        "reflecting",
        "fixed_value",
        "open",
        "not_applicable",
    ] = "not_applicable"
    description: str = ""
    is_periodic: bool = False


class ProblemContract(BaseModel):
    """从原始题面提取的结构化硬约束。"""

    schema_version: str = "mathmodel.problem-contract.v1"
    immutable_parameters: list[ContractParameter] = Field(default_factory=list)
    required_requirements: list[ContractRequirement] = Field(default_factory=list)
    boundary_conditions: list[BoundaryCondition] = Field(default_factory=list)

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
        if self.boundary_conditions:
            lines.append("【边界与拓扑契约】")
            for bc in self.boundary_conditions:
                periodic_str = "周期边界" if bc.is_periodic or bc.boundary_type == "periodic" else "非周期/独立边界"
                lines.append(
                    f"- 坐标轴 {bc.axis}: {bc.boundary_type} ({periodic_str})；说明: {bc.description or '无'}。"
                )
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

_SAMPLE_THICKNESS_PAIR = re.compile(
    r"(?:同一(?:块|片|个)?([^，。；\n]{1,24}?)(?:的)?|样品[^，。；\n]{0,12}?)"
    r"厚度(?:分别)?(?:为|是)?\s*"
    r"(\d+(?:\.\d+)?)\s*(?:nm|微米|μm|um|mm)"
    r"(?:和|与|、|及)\s*"
    r"(\d+(?:\.\d+)?)\s*(?:nm|微米|μm|um|mm)",
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
_ZERO_DEGREE = re.compile(r"(?<![\d.])0(?:\.0+)?\s*[°度]")

_OPEN_ENDED_DECISION_QUESTION = re.compile(
    r"(?:是否|能否|有无|何种|哪个|更优|最优|最佳|哪一种|哪种|选择|判断|评估|比较|权衡|"
    r"是否存在|是否达到|是否显著|是否可行|是否合理|是否导通|是否连通"
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
    r"(?:existence|occurrence|detected|conduction|conductive|存在性|是否存在|发生标志|效果标志|导通|是否导通|连通|是否连通)",
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
    r"(?:complet(?:ed|ion|e|eness)"
    r"|coverage|finite|reproducib"
    r"|(?:structure|format|valid(?:ation)?|match|check|verify)(?:_(?:ok|pass|done|flag))?"
    r"|完成标志|完成率|覆盖(?:数|率)?|数值有限|可复算|格式正确|结构完整)",
    re.IGNORECASE,
)
_ALGORITHM_DIAGNOSTIC_METRIC = re.compile(
    r"(?:iteration[s]?|step[s]?(?:_count)?|grid[_ ]?(?:size|count|points)"
    r"|convergence[_ ]?(?:check|flag|status)"
    r"|bisection|newton|epoch[s]?|batch[_ ]?(?:size|count)"
    r"|precision|resolution|tolerance|format|sample_size|replicate[s]?"
    r"|迭代(?:次数|步数)?|网格(?:数|点数)?|收敛(?:检查|标志)?|精度|分辨率|容差|格式|采样点数|重复次数)",
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
    r"(?:题目原文|题面|题设|附件|数据(?:统计|分布|分位数|噪声)|样本统计|训练集|验证集|"
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
_LINEAR_PROGRAMMING_METHOD_RE = re.compile(
    r"(?:线性规划|整数规划|混合整数|单纯形|\blinprog\b|\blinear\s+program(?:ming)?\b|\bsimplex\b)",
    re.IGNORECASE,
)
_DATA_ANALYSIS_TERMS = ("数据集", "样本", "预测", "回归", "统计分析", "数据分析", "附件")
_PHYSICAL_SIMULATION_TERMS = ("压力", "流量", "油管", "仿真", "动力学", "微分方程", "温度", "浓度", "运动")

_Q1_OUTFLOW_TERMS = ("喷油速率", "喷油流量", "流出流量", "q_out", "qout")
_Q23_NEEDLE_LIFT_TERMS = ("针阀升程", "有效面积", "喷嘴流量")
_Q3_TIMING_TERMS = ("同步", "错相", "错峰", "相位", "时序", "时间差", "offset")
_Q3_COMPARISON_TERMS = ("比较", "对比", "扫描", "权衡", "选择", "备选")
_TWO_INJECTOR_RE = re.compile(r"(?:第二个|两个|双|(?:再)?增加一个)喷油嘴")
_SOURCE_NEGATION_RE = re.compile(
    r"(?:不(?:读取|采用|使用|作为|来自|取自|依据|参考)|未(?:读取|采用|使用)|"
    r"不得|不能|不可|并非|而非|不应|禁止|避免|仅(?:讨论|说明|提及))"
)

# Keep the plan-level check in sync with the source-backed diagnostic gate in
# ``execution_validation.py``.  A requirement only activates its first group;
# ordinary prose such as "记录输出轨迹和单位" therefore remains compatible.
_STRUCTURED_DIAGNOSTIC_REQUIREMENT_GROUPS = (
    (
        ("求解器", "solver", "状态方程", "state_equation", "state equation"),
        ("求解器", "solver", "状态", "status", "最优性", "optimality", "收敛", "convergence"),
    ),
    (
        ("松弛", "slack"),
        ("松弛", "slack", "约束", "constraint", "边界", "bound", "violation"),
    ),
    (
        ("质量", "守恒", "balance", "residual"),
        ("质量", "守恒", "balance", "residual", "残差", "能量", "energy", "误差", "error"),
    ),
    (
        ("双喷嘴", "双喷油器", "injector"),
        ("双喷嘴", "双喷油器", "injector", "喷嘴", "nozzle"),
    ),
    (
        ("减压阀", "溢流阀", "relief"),
        ("减压阀", "溢流阀", "relief", "阀门", "valve"),
    ),
    (
        ("可行性", "feasible"),
        ("可行性", "feasible", "连通", "connectivity", "导通", "conduction", "相交", "intersection"),
    ),
    (
        ("步长", "网格", "step", "grid", "mesh", "加密", "refinement"),
        ("步长", "网格", "step", "grid", "mesh", "加密", "refinement", "分辨率", "resolution", "采样", "sample"),
    ),
    (
        ("蒙特卡洛", "monte carlo", "mc"),
        ("蒙特卡洛", "monte carlo", "mc", "方差", "variance", "置信区间", "confidence", "采样", "sample"),
    ),
    (
        ("敏感性分析", "灵敏度分析", "sensitivity_analysis"),
        ("敏感性", "灵敏度", "sensitivity", "鲁棒性", "robustness"),
    ),
    (
        ("几何碰撞", "相交距离", "geometric_collision"),
        ("几何", "geometry", "距离", "distance", "碰撞", "collision", "截断", "truncation", "镜像", "mirror", "周期", "periodic"),
    ),
)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _append_requirement_once(contract: ProblemContract, requirement: ContractRequirement) -> None:
    if requirement.key not in {item.key for item in contract.required_requirements}:
        contract.required_requirements.append(requirement)


def affirmatively_binds_source(
    text: str,
    source: str,
    terms: tuple[str, ...],
) -> bool:
    """Return whether a clause positively binds a named source to given terms.

    Mere token co-occurrence is not a provenance statement: ``图2不采用，q_out
    由外推得到`` used to satisfy the Q1 source lock.  Keep the check clause
    scoped, reject a nearby negative relation, and require an actual data-use
    verb.  This helper is also used by the paper preflight so planning and
    manuscript validation cannot disagree about what counts as a source lock.
    """
    normalized_source = source.lower()
    for clause in re.split(r"[。；;\n]", text):
        compact = re.sub(r"\s+", "", clause).lower()
        if (
            normalized_source not in compact
            or not any(term in compact for term in terms)
        ):
            continue
        source_index = compact.find(normalized_source)
        context = compact[max(0, source_index - 24) : source_index + 80]
        if _SOURCE_NEGATION_RE.search(context):
            continue
        escaped_source = re.escape(normalized_source)
        if re.search(
            rf"(?:由|来自|读取|采用|使用|根据|依据|取自|参照|沿用|继承|承接).{{0,36}}{escaped_source}",
            compact,
        ):
            return True
        if re.search(
            rf"{escaped_source}.{{0,36}}(?:给出|提供|用于|作为|计算|驱动|输入|数据源|曲线|读取|采用|使用)",
            compact,
        ):
            return True
    return False


def _affirmatively_uses_attachment2_for_q1_outflow(text: str) -> bool:
    """Return whether Q1 wrongly binds Attachment 2 to its outflow curve."""
    return affirmatively_binds_source(text, "附件2", _Q1_OUTFLOW_TERMS)


def _affirmatively_uses_figure2_for_q1_outflow(text: str) -> bool:
    return affirmatively_binds_source(text, "图2", _Q1_OUTFLOW_TERMS)


def _affirmatively_uses_attachment2_for_needle_lift(text: str) -> bool:
    return affirmatively_binds_source(text, "附件2", _Q23_NEEDLE_LIFT_TERMS)


def _mentions_q3_timing_comparison(text: str) -> bool:
    compact = re.sub(r"\s+", "", text).lower()
    timing_count = sum(term in compact for term in _Q3_TIMING_TERMS)
    has_comparison = any(
        term in compact
        and not re.search(rf"(?:不|未|无需|无需再){re.escape(term)}", compact)
        for term in _Q3_COMPARISON_TERMS
    )
    has_sync = "同步" in compact and not re.search(
        r"(?:不(?:采用|使用|考虑)?|未(?:采用|使用|考虑)?).{0,12}同步", compact
    )
    alternate_terms = ("错相", "错峰", "相位差", "时间差", "offset")
    has_alternate = False
    for term in alternate_terms:
        for match in re.finditer(re.escape(term), compact):
            context = compact[max(0, match.start() - 36) : match.end()]
            if re.search(
                r"(?:不(?:比较|采用|使用|考虑)?|未(?:比较|采用|使用|考虑)?|"
                r"无需(?:比较|采用|使用|考虑)?|唯一采用同步|仅采用同步|固定为同步).{0,24}"
                + re.escape(term),
                context,
            ):
                continue
            has_alternate = True
            break
        if has_alternate:
            break
    return timing_count >= 1 and has_comparison and has_sync and has_alternate


def _q3_inherits_q2_model_source(text: str) -> bool:
    """Accept an explicit Q3 inheritance of the already source-locked Q2 model."""
    compact = re.sub(r"\s+", "", text).lower()
    patterns = (
        r"(?:沿用|继承|承接|基于|采用|使用).{0,18}(?:问题2|问题二|q2)",
        r"(?:问题2|问题二|q2).{0,18}(?:所有)?(?:参数|模型|针阀|喷嘴)",
    )
    for pattern in patterns:
        match = re.search(pattern, compact)
        if match is None:
            continue
        context = compact[max(0, match.start() - 12) : match.end() + 24]
        if not _SOURCE_NEGATION_RE.search(context):
            return True
    return False


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
    if (
        "图2" in normalized
        and "喷油嘴B处向外喷油的速率" in normalized
        and "问题1" in normalized
    ):
        _append_requirement_once(
            contract,
            ContractRequirement(
                key="q1_injection_rate_source_figure2",
                label="问题一喷油流出速率必须来自题面图2，不得以附件2针阀升程曲线替代",
                evidence_terms=["图2", "喷油速率"],
                source="题面问题一明确指定的喷油速率图2",
            ),
        )
    if "附件2" in normalized and "针阀升程与时间的关系" in normalized:
        _append_requirement_once(
            contract,
            ContractRequirement(
                key="q23_needle_lift_source_attachment2",
                label="问题二和问题三的针阀升程/喷嘴有效面积必须使用附件2，并与问题一图2数据源分离",
                evidence_terms=["附件2", "针阀升程"],
                source="题面问题二的针阀升程附件说明及问题三对问题二模型的继承",
            ),
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
    if _TWO_INJECTOR_RE.search(normalized):
        contract.required_requirements.append(
            ContractRequirement(
                key="two_injectors",
                label="问题三须按两个喷油嘴建模；不得把新增喷油嘴改写为新增泵",
                source="题面原文的第二喷油嘴条件",
            )
        )
        _append_requirement_once(
            contract,
            ContractRequirement(
                key="q3_injector_timing_comparison",
                label="问题三须比较至少两种双喷嘴同步/错相/错峰时序策略，并给出选择依据",
                evidence_terms=["喷油嘴", "相位", "比较"],
                source="题面要求调整两个同规律喷油嘴的喷油器和供油策略",
                expected_artifact_kinds=["result_table"],
                acceptance_metric_terms=[
                    "phase_offset_ms",
                    "alternate_phase_offset_ms",
                    "strategy_objective",
                    "alternate_phase_objective",
                ],
            ),
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
        persisted_model_plan = plan.get("model_plan")
        if isinstance(persisted_model_plan, dict):
            persisted_subtasks = persisted_model_plan.get("subtasks")
            if isinstance(persisted_subtasks, dict):
                return {
                    str(key): json.dumps(value, ensure_ascii=False, sort_keys=True)
                    for key, value in persisted_subtasks.items()
                }
        persisted_questions = plan.get("questions_solution")
        if isinstance(persisted_questions, dict):
            return {str(key): str(value) for key, value in persisted_questions.items()}
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
    if isinstance(plan, dict):
        model_plan = plan.get("model_plan", plan)
        if isinstance(model_plan, dict) and isinstance(model_plan.get("subtasks"), dict):
            return dict(model_plan["subtasks"])
    return {}


def _plan_field(value: object, field: str, default: object = None) -> object:
    if isinstance(value, dict):
        return value.get(field, default)
    return getattr(value, field, default)


def _conclusion_forcing_metrics(plan: object, question: str) -> list[str]:
    """Find acceptance thresholds that predetermine an open scientific decision."""
    if not _OPEN_ENDED_DECISION_QUESTION.search(question):
        return []
    issues: list[str] = []
    for metric in _plan_field(plan, "acceptance_metrics", []) or []:
        comparator = str(_plan_field(metric, "comparator", ""))
        target = float(_plan_field(metric, "target", 0))
        metric_text = " ".join(
            str(_plan_field(metric, field, ""))
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
            and target in {0, 1, 0.0, 1.0}
            # 放行结论中立的“过程完整性 / 可复算性”完成标志
            # （如 distance_calculation_completeness / result_reproducibility /
            #  *_complete / *_match eq 1），只拒绝真正在执行前预设科学结论
            # 为肯定的指标（如 conduction / 是否导通 / existence eq 1）。
            and not _NEUTRAL_COMPLETION_METRIC.search(metric_text)
        )
        if forces_direction or forces_significance or forces_boolean_outcome:
            issues.append(f"{_plan_field(metric, 'key', 'unknown')} {comparator} {target:g}")
    return issues


def _unsupported_empirical_thresholds(plan: object) -> list[str]:
    """Find empirical quality targets whose numeric cutoff has no stated basis."""
    issues: list[str] = []
    for metric in _plan_field(plan, "acceptance_metrics", []) or []:
        identity_text = " ".join(
            str(_plan_field(metric, field, "")) for field in ("key", "label")
        )
        description = str(_plan_field(metric, "description", ""))
        metric_text = f"{identity_text} {description}"
        comparator = str(_plan_field(metric, "comparator", ""))
        target = float(_plan_field(metric, "target", 0))
        if not _EMPIRICAL_QUALITY_METRIC.search(metric_text):
            continue
        if _NEUTRAL_COMPLETION_METRIC.search(identity_text):
            continue
        # Algorithm diagnostic parameters (iteration counts, grid sizes, convergence
        # checks) are not empirical quality thresholds — they record algorithm
        # configuration or execution diagnostics, not quality judgments.
        if _ALGORITHM_DIAGNOSTIC_METRIC.search(identity_text):
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
        issues.append(f"{_plan_field(metric, 'key', 'unknown')} {comparator} {target:g}")
    return issues


def _matching_plan_keys(
    requirement: ContractRequirement,
    subtasks: dict[str, object],
    questions: dict[str, str | int] | None,
) -> list[str]:
    """Select only questions whose text matches a generic domain profile."""
    conventional_key = next(
        (
            f"ques{number}"
            for number in range(1, 10)
            if requirement.key.startswith(f"q{number}_")
            or requirement.key.startswith(f"q{number}")
        ),
        None,
    )
    if conventional_key is not None:
        return [conventional_key] if conventional_key in subtasks else []
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
    artifacts = _plan_field(plan, "expected_artifacts", []) or []
    artifact_kinds = {_plan_field(item, "kind", "") for item in artifacts}
    metric_text = " ".join(
        f"{_plan_field(item, 'key', '')} {_plan_field(item, 'label', '')} {_plan_field(item, 'description', '')}"
        for item in (_plan_field(plan, "acceptance_metrics", []) or [])
    )
    method_text = " ".join(
        [
            str(_plan_field(plan, "method", "")),
            *[str(item) for item in (_plan_field(plan, "constraints", []) or [])],
            *[str(item) for item in (_plan_field(plan, "inputs", []) or [])],
        ]
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
    required_metric_terms = [term.lower() for term in requirement.acceptance_metric_terms]
    return bool(method_text.strip()) and all(
        term in metric_text.lower() for term in required_metric_terms
    )


def _has_structured_artifact_fields(subtasks: dict[str, object]) -> bool:
    """Distinguish a schema-backed ModelPlan from compatibility dictionaries."""
    return bool(subtasks) and all(
        _plan_field(subtask, "expected_artifacts", None) is not None
        and _plan_field(subtask, "acceptance_metrics", None) is not None
        for subtask in subtasks.values()
    )


def _is_linear_programming_subtask(subtask: object) -> bool:
    """Return whether the declared method is an LP-style optimization solve.

    ``numerical`` is appropriate for discretisation/refinement diagnostics, but
    not for a linear program merely because its solution is numeric. Keeping
    this check on the method text avoids imposing an optimization profile on a
    generic problem that happens to mention a resource or a profit elsewhere.
    """
    method = _plan_field(subtask, "method", "")
    return isinstance(method, str) and bool(_LINEAR_PROGRAMMING_METHOD_RE.search(method))


def _structured_diagnostic_metric_gaps(subtask: object) -> list[str]:
    """Find explicit diagnostic requirements with no declared metric support.

    This is intentionally a plan-level check: it binds a requirement to the
    ModelPlan's metric ``key``/``label``/``description`` before Coder executes
    anything. Runtime source-backed evidence remains the responsibility of
    ``execution_validation.py``.
    """
    profile = str(_plan_field(subtask, "diagnostic_profile", "")).lower()
    if profile not in {"simulation", "optimization"}:
        return []
    requirements = _plan_field(subtask, "diagnostic_requirements", [])
    if not isinstance(requirements, list):
        return []
    metric_texts = [
        " ".join(
            str(_plan_field(metric, field, ""))
            for field in ("key", "label", "description")
        ).lower()
        for metric in (_plan_field(subtask, "acceptance_metrics", []) or [])
    ]
    gaps: list[str] = []
    for raw_requirement in requirements:
        if not isinstance(raw_requirement, str) or not raw_requirement.strip():
            continue
        lowered_requirement = raw_requirement.lower()
        matching_groups = [
            (req_tokens, metric_tokens)
            for req_tokens, metric_tokens in _STRUCTURED_DIAGNOSTIC_REQUIREMENT_GROUPS
            if any(token.lower() in lowered_requirement for token in req_tokens)
        ]
        if not matching_groups:
            continue
        is_covered = any(
            any(
                any(token.lower() in metric_text for token in metric_tokens)
                for metric_text in metric_texts
            )
            for _, metric_tokens in matching_groups
        )
        if not is_covered:
            gaps.append(raw_requirement.strip())
    return gaps


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
    sections = _plan_sections(plan)
    active_question_keys = expected_question_keys or {
        key for key in sections if re.fullmatch(r"ques[1-9]\d*", key)
    }
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
        diagnostic_profile = _plan_field(subtask, "diagnostic_profile", "not_applicable")
        if (
            _is_linear_programming_subtask(subtask)
            and diagnostic_profile not in {"optimization", "not_applicable", None, ""}
        ):
            violations.append(
                f"{key} 的方法明确为线性规划，却声明 diagnostic_profile={diagnostic_profile!r}；"
                "线性规划及其资源敏感性重求解必须使用 optimization，"
                "以登记求解器状态、可行性和松弛量等诊断。"
            )
        for metric in _plan_field(subtask, "acceptance_metrics", []) or []:
            label = " ".join(
                str(_plan_field(metric, field, ""))
                for field in ("key", "label", "description")
            ).lower()
            comparator = str(_plan_field(metric, "comparator", "")).lower()
            target = _plan_field(metric, "target", None)
            if (
                any(term in label for term in ("守恒", "平衡", "conservation", "balance"))
                and comparator == "eq"
                and target in {0, 0.0, 1, 1.0}
            ):
                violations.append(
                    f"{key} 将守恒/平衡诊断强制为精确 {target}；"
                    "守恒残差必须实际落表并作为诊断报告，不能在无题面容差时充当硬验收阈值"
                )
        diagnostic_gaps = _structured_diagnostic_metric_gaps(subtask)
        if diagnostic_gaps:
            missing.append(
                f"{key} 诊断要求缺少对应验收指标关键词：" + "；".join(diagnostic_gaps)
            )
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
        if (
            subtasks
            and _has_structured_artifact_fields(subtasks)
            and (
                requirement.expected_artifact_kinds
                or requirement.acceptance_metric_terms
            )
        ):
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
        elif requirement.key == "q1_injection_rate_source_figure2":
            if active_question_keys and "ques1" not in active_question_keys:
                continue
            q1_text = sections.get("ques1", text)
            covered = _affirmatively_uses_figure2_for_q1_outflow(q1_text)
            if _affirmatively_uses_attachment2_for_q1_outflow(q1_text):
                violations.append("问题一把附件2针阀升程曲线作为喷油速率/流出流量来源；题面要求使用图2")
        elif requirement.key == "q23_needle_lift_source_attachment2":
            relevant_keys = [
                key for key in ("ques2", "ques3")
                if not active_question_keys or key in active_question_keys
            ]
            if not relevant_keys:
                continue
            q2_source_locked = _affirmatively_uses_attachment2_for_needle_lift(
                sections.get("ques2", "")
            )
            uncovered_keys = []
            for key in relevant_keys:
                explicitly_locked = _affirmatively_uses_attachment2_for_needle_lift(
                    sections.get(key, "")
                )
                inherited_from_q2 = (
                    key == "ques3"
                    and q2_source_locked
                    and _q3_inherits_q2_model_source(sections.get("ques3", ""))
                )
                if not (explicitly_locked or inherited_from_q2):
                    uncovered_keys.append(key)
            covered = not uncovered_keys
            if uncovered_keys:
                missing.append(
                    requirement.label + "（未满足：" + ", ".join(uncovered_keys) + "）"
                )
                continue
        elif requirement.key == "q3_injector_timing_comparison":
            if active_question_keys and "ques3" not in active_question_keys:
                continue
            covered = _mentions_q3_timing_comparison(sections.get("ques3", text))
        elif requirement.key.startswith("target_pressure_"):
            covered = all(term in normalized for term in requirement.evidence_terms)
        elif requirement.key == "two_injectors":
            covered = bool(_TWO_INJECTOR_RE.search(normalized))
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
