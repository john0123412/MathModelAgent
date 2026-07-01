"""断点续传检查点模块，负责工作流阶段结果的持久化与恢复。"""

import os
import datetime
from pydantic import BaseModel, Field
from app.utils.log_util import logger


class PhaseCheckpoint(BaseModel):
    """单个阶段的检查点记录。"""

    key: str
    coder_response: dict | None = None  # CoderToWriter.model_dump()，仅 solution_flows 阶段有
    writer_response: dict  # WriterResponse.model_dump()
    completed_at: str


class TaskCheckpoint(BaseModel):
    """任务级检查点，记录续传所需的全部状态。"""

    task_id: str
    ques_all: str
    comp_template: str
    format_output: str
    questions: dict[str, str | int]
    ques_count: int
    modeler_response: dict  # ModelerToCoder.model_dump()
    completed_phases: dict[str, PhaseCheckpoint] = Field(default_factory=dict)
    updated_at: str
    
    # 新增：增量重放支持
    executed_cell_indices: list[int] = Field(default_factory=list)  # 已执行的单元格索引
    has_variable_snapshot: bool = False  # 是否有变量快照


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
