"""Agent 间通信数据模型定义。"""

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.problem_contract import ProblemContract


class CoordinatorToModeler(BaseModel):
    """协调者传递给建模手的数据结构。"""
    questions: dict
    ques_count: int
    problem_contract: ProblemContract | None = None


class ExpectedArtifact(BaseModel):
    """某个正式子题在执行后必须留下的可复核产物。"""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, description="任务目录内的预期相对路径或文件名")
    kind: Literal[
        "result_table",
        "constraint_table",
        "figure_data",
        "figure",
        "time_series",
        "parameter_audit",
        "dataset",
        "other",
    ]
    description: str = Field(min_length=3)


class AcceptanceMetric(BaseModel):
    """能由 Coder 的结构化结果验证的一个验收指标。"""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=2)
    comparator: Literal["le", "lt", "ge", "gt", "eq", "within"]
    target: float = Field(allow_inf_nan=False)
    unit: str | None = None
    description: str = Field(min_length=3)


class SubtaskPlan(BaseModel):
    """一个 ``quesN`` 的输入—方法—约束—证据计划。"""

    model_config = ConfigDict(extra="forbid")

    inputs: list[str] = Field(min_length=1)
    method: str = Field(min_length=12)
    constraints: list[str] = Field(min_length=1)
    expected_artifacts: list[ExpectedArtifact] = Field(min_length=1)
    acceptance_metrics: list[AcceptanceMetric] = Field(min_length=1)
    visualization: str = Field(min_length=3)
    diagnostic_profile: Literal[
        "exact",
        "numerical",
        "optimization",
        "fitting",
        "simulation",
        "not_applicable",
    ] = "not_applicable"
    diagnostic_requirements: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_structured_numeric_evidence(self) -> "SubtaskPlan":
        """Prevent a plan that promises only a PNG or prose conclusion."""
        kinds = {artifact.kind for artifact in self.expected_artifacts}
        if not kinds.intersection({"result_table", "time_series", "dataset"}):
            raise ValueError("expected_artifacts 必须包含 result_table、time_series 或 dataset 数值产物")
        return self

    def to_coder_summary(self) -> str:
        """Render a concise, deterministic prompt fragment for the Coder."""
        artifacts = "；".join(
            f"{item.path}（{item.kind}：{item.description}）"
            for item in self.expected_artifacts
        )
        metrics = "；".join(
            f"{item.label}({item.key}) {item.comparator} {item.target}"
            + (f" [{item.unit}]" if item.unit else "")
            for item in self.acceptance_metrics
        )
        return (
            f"输入：{'；'.join(self.inputs)}\n"
            f"方法：{self.method}\n"
            f"约束：{'；'.join(self.constraints)}\n"
            f"预期产物：{artifacts}\n"
            f"验收指标：{metrics}\n"
            f"诊断类型：{self.diagnostic_profile}\n"
            f"诊断要求：{'；'.join(self.diagnostic_requirements) or '无额外诊断'}\n"
            f"可视化：{self.visualization}"
        )


class ModelPlan(BaseModel):
    """建模手到代码手的严格交接契约。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["mathmodel.model-plan.v1"] = "mathmodel.model-plan.v1"
    eda: str = Field(min_length=3)
    subtasks: dict[str, SubtaskPlan] = Field(min_length=1)
    sensitivity_analysis: str = Field(min_length=3)

    @model_validator(mode="after")
    def only_allow_formal_question_keys(self) -> "ModelPlan":
        invalid = sorted(
            key for key in self.subtasks if not re.fullmatch(r"ques[1-9]\d*", key)
        )
        if invalid:
            raise ValueError(f"subtasks 只能包含 quesN 键，发现: {', '.join(invalid)}")
        return self

    def coverage_issues(self, expected_question_keys: set[str]) -> list[str]:
        actual = set(self.subtasks)
        missing = sorted(expected_question_keys - actual)
        unexpected = sorted(actual - expected_question_keys)
        issues: list[str] = []
        if missing:
            issues.append("缺少正式问题计划: " + ", ".join(missing))
        if unexpected:
            issues.append("出现未拆解的正式问题计划: " + ", ".join(unexpected))
        return issues

    def to_questions_solution(self) -> dict[str, str]:
        """Compatibility view for old checkpoints and prose-only consumers."""
        return {
            "eda": self.eda,
            **{
                key: plan.to_coder_summary()
                for key, plan in self.subtasks.items()
            },
            "sensitivity_analysis": self.sensitivity_analysis,
        }


class ModelerToCoder(BaseModel):
    """建模手传递给代码手的数据结构。

    ``model_plan`` 是新任务唯一允许的结构化交接。``questions_solution``
    保留为旧 checkpoint 的兼容视图；存在 ``model_plan`` 时由后者自动生成。
    """

    model_plan: ModelPlan | None = None
    questions_solution: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def derive_legacy_solution_view(self) -> "ModelerToCoder":
        if self.model_plan:
            derived = self.model_plan.to_questions_solution()
            if self.questions_solution and self.questions_solution != derived:
                raise ValueError("model_plan 与 questions_solution 不一致；新任务只能以 model_plan 为准")
            self.questions_solution = derived
        return self

    def get_subtask_plan(self, key: str) -> SubtaskPlan | None:
        if not self.model_plan:
            return None
        return self.model_plan.subtasks.get(key)


class CoderToWriter(BaseModel):
    """代码手传递给写作手的数据结构。"""
    code_response: str | None = None
    code_output: str | None = None
    created_images: list[str] | None = None
    execution_attempted: bool = False
    execution_succeeded: bool = False
    execution_error_occurred: bool = False


class WriterResponse(BaseModel):
    """写作手的响应数据结构。"""
    response_content: Any
    footnotes: list[tuple[str, str]] | None = None
