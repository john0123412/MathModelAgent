"""断点续传检查点模块，负责工作流阶段结果的持久化与恢复。"""

import os
import datetime
from pydantic import BaseModel, Field
from app.utils.log_util import logger


class PhaseCheckpoint(BaseModel):
    """单个阶段的检查点记录。"""

    key: str
    coder_response: dict | None = None  # CoderToWriter.model_dump()，仅 solution_flows 阶段有
    writer_response: dict | None = None  # WriterResponse.model_dump()
    completed_at: str


class TaskCheckpoint(BaseModel):
    """任务级检查点，记录续传所需的全部状态。"""

    task_id: str
    ques_all: str
    comp_template: str
    format_output: str
    export_profile: str = "default"
    questions: dict[str, str | int]
    ques_count: int
    modeler_response: dict  # ModelerToCoder.model_dump()
    completed_phases: dict[str, PhaseCheckpoint] = Field(default_factory=dict)
    updated_at: str
    
    # 新增：增量重放支持
    executed_cell_indices: list[int] = Field(default_factory=list)  # 已执行的单元格索引
    has_variable_snapshot: bool = False  # 是否有变量快照
    # 代码手与论文手必须被最终验证门禁隔开。该字段保存已经执行、但尚未
    # 写作的 solution 阶段，保证续传时无需让未经验证的旧 Writer 文本复用。
    solution_coder_responses: dict[str, dict] = Field(default_factory=dict)
    # 最终执行验证失败后，保留已通过子题，仅允许对失败子题做一次自动定向回修。
    # 计数持久化，避免续传后绕过“连续两次失败即停止”的恢复规程。
    workflow_state: str = "solving"
    targeted_repair_attempts: int = 0
    last_validation_failure: dict = Field(default_factory=dict)
    # 代码证据冻结通过后，论文预检仍可能发现 Writer 把冻结事实写错。
    # 该计数与代码回修预算独立：它只允许一次受控的定向改写，续传也不能
    # 静默绕过第二次预检失败。
    paper_repair_attempts: int = 0
    last_paper_preflight_failure: dict = Field(default_factory=dict)
    # 连续两次真实验证失败后，只允许经人工明确批准的一次恢复；这不是
    # 自动重试预算，且会保留批准理由供任务审计。
    manual_recovery_attempts: int = 0
    last_manual_recovery: dict = Field(default_factory=dict)


class CheckpointManager:
    """检查点管理器，负责 checkpoint.json 的原子读写。"""

    def __init__(self, work_dir: str):
        self.work_dir = work_dir
        self.checkpoint_path = os.path.join(work_dir, "checkpoint.json")
        self._checkpoint: TaskCheckpoint | None = None

    def save(self, checkpoint: TaskCheckpoint) -> None:
        """原子写入检查点到 work_dir/checkpoint.json。

        Args:
            checkpoint: 待持久化的检查点对象。
        """
        self._checkpoint = checkpoint
        tmp_path = self.checkpoint_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(checkpoint.model_dump_json(indent=2))
            os.replace(tmp_path, self.checkpoint_path)
        except Exception as e:
            logger.error(f"保存检查点失败: {e}")
            raise

    def load(self) -> TaskCheckpoint | None:
        """加载检查点文件。

        Returns:
            检查点对象；文件不存在或解析失败时返回 None。
        """
        if not os.path.exists(self.checkpoint_path):
            return None
        try:
            with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                self._checkpoint = TaskCheckpoint.model_validate_json(f.read())
            # A successfully frozen result ends the *consecutive* execution
            # failure sequence.  Older checkpoints kept the historical repair
            # count even after a passing freeze, which could make a later,
            # newly introduced evidence check consume a non-existent second
            # failure budget before Coder was allowed to repair it.
            if (
                self._checkpoint.workflow_state == "frozen"
                and not self._checkpoint.last_validation_failure
                and self._checkpoint.targeted_repair_attempts
            ):
                self._checkpoint.targeted_repair_attempts = 0
                self._checkpoint.updated_at = datetime.datetime.now().isoformat()
                self.save(self._checkpoint)
            return self._checkpoint
        except Exception as e:
            logger.error(f"加载检查点失败: {e}")
            return None

    def is_completed(self, key: str) -> bool:
        """判断指定阶段是否已在检查点中完成。"""
        return self._checkpoint is not None and key in self._checkpoint.completed_phases

    def get_phase(self, key: str) -> PhaseCheckpoint | None:
        """获取指定阶段的检查点记录，不存在时返回 None。"""
        if self._checkpoint is None:
            return None
        return self._checkpoint.completed_phases.get(key)

    def get_solution_coder_response(self, key: str) -> dict | None:
        """读取已完成代码阶段的响应，兼容旧版联合阶段检查点。"""
        if self._checkpoint is None:
            return None
        phase = self._checkpoint.completed_phases.get(key)
        if phase and phase.coder_response is not None:
            return phase.coder_response
        return self._checkpoint.solution_coder_responses.get(key)

    def mark_solution_coder_completed(self, key: str, coder_response: dict) -> None:
        """保存代码执行结果，等待最终验证通过后才允许 Writer 使用。"""
        if self._checkpoint is None:
            raise RuntimeError("CheckpointManager 尚未初始化，需先调用 save() 建立基础检查点")
        self._checkpoint.solution_coder_responses[key] = coder_response
        self._checkpoint.updated_at = datetime.datetime.now().isoformat()
        self.save(self._checkpoint)

    def invalidate_solution_coder_responses(self, keys: list[str]) -> None:
        """Discard code and prose hand-offs that failed the final evidence gate.

        A successful tool call is not a successful mathematical solution. Keeping
        its checkpoint after a failed execution manifest would make resume skip the
        required recalculation and repeatedly fail at the same gate.
        """
        if self._checkpoint is None:
            raise RuntimeError("CheckpointManager 尚未初始化")
        for key in keys:
            self._checkpoint.solution_coder_responses.pop(key, None)
            self._checkpoint.completed_phases.pop(key, None)
        self._checkpoint.updated_at = datetime.datetime.now().isoformat()
        self.save(self._checkpoint)

    def record_validation_failure(
        self,
        failed_subtasks: list[str],
        report: dict,
    ) -> int:
        """Persist one final-validation failure and enter the repairing state.

        The caller deliberately decides whether another repair is allowed.  This
        keeps the durable counter independent of a particular LLM/provider and
        prevents resume from silently restarting an exhausted retry budget.
        """
        if self._checkpoint is None:
            raise RuntimeError("CheckpointManager 尚未初始化")
        self._checkpoint.targeted_repair_attempts += 1
        self._checkpoint.workflow_state = "repairing"
        self._checkpoint.last_validation_failure = {
            "failed_subtasks": sorted(set(failed_subtasks)),
            "report": report,
            "recorded_at": datetime.datetime.now().isoformat(),
        }
        self._checkpoint.updated_at = datetime.datetime.now().isoformat()
        self.save(self._checkpoint)
        return self._checkpoint.targeted_repair_attempts

    def mark_results_frozen(self) -> None:
        """Record that all execution evidence passed and was frozen."""
        if self._checkpoint is None:
            raise RuntimeError("CheckpointManager 尚未初始化")
        self._checkpoint.workflow_state = "frozen"
        self._checkpoint.targeted_repair_attempts = 0
        self._checkpoint.last_validation_failure = {}
        self._checkpoint.updated_at = datetime.datetime.now().isoformat()
        self.save(self._checkpoint)

    def repair_attempts_exhausted(self) -> bool:
        """Return whether two real final-validation failures were recorded."""
        return bool(
            self._checkpoint is not None
            and self._checkpoint.targeted_repair_attempts >= 2
        )

    def authorize_manual_execution_recovery(self, mode: str, note: str = "") -> None:
        """Authorize exactly one post-exhaustion Coder attempt.

        The caller must explicitly attest to a verified provider change or a
        lower-cost reproducible algorithm.  Starting from attempt count one
        lets the next failed validation consume the final budget immediately,
        so this path never creates another automatic repair loop.
        """
        if self._checkpoint is None:
            raise RuntimeError("CheckpointManager 尚未初始化")
        if self._checkpoint.manual_recovery_attempts >= 1:
            raise RuntimeError("本任务已使用过一次人工执行恢复授权")
        if not self.repair_attempts_exhausted():
            raise RuntimeError("当前执行验证失败次数未耗尽，无需人工恢复授权")
        self._checkpoint.manual_recovery_attempts += 1
        self._checkpoint.targeted_repair_attempts = 1
        self._checkpoint.workflow_state = "manual_recovery"
        self._checkpoint.last_manual_recovery = {
            "mode": mode,
            "note": note[:1000],
            "authorized_at": datetime.datetime.now().isoformat(),
        }
        self._checkpoint.updated_at = datetime.datetime.now().isoformat()
        self.save(self._checkpoint)

    def record_paper_preflight_failure(self, report: dict) -> int:
        """Persist a post-writing preflight failure before one targeted rewrite."""
        if self._checkpoint is None:
            raise RuntimeError("CheckpointManager 尚未初始化")
        self._checkpoint.paper_repair_attempts += 1
        self._checkpoint.workflow_state = "paper_repairing"
        self._checkpoint.last_paper_preflight_failure = {
            "report": report,
            "recorded_at": datetime.datetime.now().isoformat(),
        }
        self._checkpoint.updated_at = datetime.datetime.now().isoformat()
        self.save(self._checkpoint)
        return self._checkpoint.paper_repair_attempts

    def mark_paper_preflight_passed(self) -> None:
        """Record that the latest assembled manuscript passed the technical preflight."""
        if self._checkpoint is None:
            raise RuntimeError("CheckpointManager 尚未初始化")
        self._checkpoint.workflow_state = "paper_preflight_passed"
        self._checkpoint.last_paper_preflight_failure = {}
        self._checkpoint.updated_at = datetime.datetime.now().isoformat()
        self.save(self._checkpoint)

    def paper_repair_attempts_exhausted(self) -> bool:
        """Return whether the one allowed post-writing repair was already used."""
        return bool(
            self._checkpoint is not None
            and self._checkpoint.paper_repair_attempts >= 2
        )

    def replace_modeler_response(self, modeler_response: dict) -> None:
        """Replace an invalid modeling plan and discard every dependent hand-off."""
        if self._checkpoint is None:
            raise RuntimeError("CheckpointManager 尚未初始化")
        self._checkpoint.modeler_response = modeler_response
        self._checkpoint.solution_coder_responses.clear()
        self._checkpoint.completed_phases.clear()
        self._checkpoint.executed_cell_indices.clear()
        self._checkpoint.has_variable_snapshot = False
        self._checkpoint.updated_at = datetime.datetime.now().isoformat()
        self.save(self._checkpoint)

    def mark_phase_completed(
        self,
        key: str,
        coder_response: dict | None,
        writer_response: dict,
    ) -> None:
        """标记指定阶段已完成并立即落盘。

        Args:
            key: 阶段标识（如 eda、ques1）。
            coder_response: CoderToWriter.model_dump() 结果，写作阶段为 None。
            writer_response: WriterResponse.model_dump() 结果。
        """
        if self._checkpoint is None:
            raise RuntimeError("CheckpointManager 尚未初始化，需先调用 save() 建立基础检查点")

        self._checkpoint.completed_phases[key] = PhaseCheckpoint(
            key=key,
            coder_response=coder_response,
            writer_response=writer_response,
            completed_at=datetime.datetime.now().isoformat(),
        )
        self._checkpoint.updated_at = datetime.datetime.now().isoformat()
        self.save(self._checkpoint)
    
    def add_executed_cell(self, cell_index: int) -> None:
        """记录已执行的单元格索引（增量重放支持）。
        
        Args:
            cell_index: 单元格在 notebook 中的索引
        """
        if self._checkpoint is None:
            raise RuntimeError("CheckpointManager 尚未初始化")
        
        if cell_index not in self._checkpoint.executed_cell_indices:
            self._checkpoint.executed_cell_indices.append(cell_index)
            self._checkpoint.updated_at = datetime.datetime.now().isoformat()
            self.save(self._checkpoint)
    
    def set_variable_snapshot_exists(self, exists: bool) -> None:
        """设置变量快照是否存在标志。
        
        Args:
            exists: 是否有变量快照
        """
        if self._checkpoint is None:
            raise RuntimeError("CheckpointManager 尚未初始化")
        
        self._checkpoint.has_variable_snapshot = exists
        self._checkpoint.updated_at = datetime.datetime.now().isoformat()
        self.save(self._checkpoint)
    
    def get_executed_cells(self) -> list[int]:
        """获取已执行的单元格索引列表。"""
        if self._checkpoint is None:
            return []
        return self._checkpoint.executed_cell_indices
    
    def has_variable_snapshot(self) -> bool:
        """检查是否有变量快照。"""
        if self._checkpoint is None:
            return False
        return self._checkpoint.has_variable_snapshot
