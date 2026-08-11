"""断点续传检查点模块，负责工作流阶段结果的持久化与恢复。"""

import os
import datetime
from pathlib import Path
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
    require_model_review: bool = False
    # 审查者可退回 ModelPlan 一次，以给出明确、可审计的建模修订意见；
    # 它不是无限重试预算，超过一次必须由人工另行决定如何处置。
    modeling_review_revisions: int = 0
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
    # Editorial quality is a separate, post-delivery review.  It must not
    # reopen the ordinary Writer/preflight repair budget that was already
    # consumed by a completed task.
    editorial_repair_attempts: int = 0
    last_editorial_quality_failure: dict = Field(default_factory=dict)
    # A deterministic postprocessor correction may need one export-only reflow
    # after a completed delivery.  It must never replace Writer prose or reopen
    # provider work, and remains independently auditable.
    presentation_reflow_attempts: int = 0
    last_presentation_reflow: dict = Field(default_factory=dict)
    # A participant-requested formal-format replacement is separate from both
    # technical paper repair and visual-only reflow.  It may update prose and
    # appendices, but not results, code evidence, or the frozen-result hash.
    format_compliance_attempts: int = 0
    last_format_compliance: dict = Field(default_factory=dict)
    # 连续两次真实验证失败后，只允许经人工明确批准的一次恢复；这不是
    # 自动重试预算，且会保留批准理由供任务审计。
    manual_recovery_attempts: int = 0
    last_manual_recovery: dict = Field(default_factory=dict)
    # 执行证据 PASS 不等于数学/物理质量合格。冻结结果在进入 Writer 前必须
    # 经过可审计的 Codex/人工复核；审批只绑定到当前结果文件哈希生成的 review_id。
    quality_review_status: str = "not_run"
    quality_review_id: str = ""
    quality_review_repairs: int = 0
    quality_review_history: list[dict] = Field(default_factory=list)
    # 质量返修的源码链必须只建立一次。候选 CLI 与 /resume 共享此持久边界，
    # 避免候选已经写入干净 notebook 后再次隔离/恢复旧源。
    quality_repair_source_prepared: bool = False


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
        # Once the refreshed source has been frozen, later ordinary resume
        # should use its current notebook/snapshot like any other frozen task.
        self._checkpoint.quality_repair_source_prepared = False
        self._checkpoint.updated_at = datetime.datetime.now().isoformat()
        self.save(self._checkpoint)

    def record_quality_review_pending(self, report: dict) -> None:
        """Pause before Writer until the current frozen evidence is reviewed."""
        if self._checkpoint is None:
            raise RuntimeError("CheckpointManager 尚未初始化")
        review_id = str(report.get("review_id", "")).strip()
        if not review_id:
            raise RuntimeError("质量复核报告缺少 review_id")
        self._checkpoint.workflow_state = "waiting_quality_review"
        self._checkpoint.quality_review_status = "pending"
        self._checkpoint.quality_review_id = review_id
        self._checkpoint.updated_at = datetime.datetime.now().isoformat()
        self.save(self._checkpoint)

    def quality_review_is_approved(self, review_id: str) -> bool:
        """Return whether approval is bound to this exact frozen-result review."""
        return bool(
            self._checkpoint is not None
            and self._checkpoint.quality_review_status == "approved"
            and self._checkpoint.quality_review_id == review_id
        )

    def approve_quality_review(self, review_id: str, comment: str) -> None:
        """Approve one exact review packet with a mandatory audit rationale."""
        if self._checkpoint is None:
            raise RuntimeError("CheckpointManager 尚未初始化")
        if self._checkpoint.workflow_state != "waiting_quality_review":
            raise RuntimeError("当前任务不在执行质量复核状态")
        if self._checkpoint.quality_review_id != review_id:
            raise RuntimeError("结果文件已变化，请重新读取最新质量复核报告")
        rationale = comment.strip()
        if not rationale:
            raise RuntimeError("质量复核放行理由不能为空")
        self._checkpoint.quality_review_status = "approved"
        self._checkpoint.quality_review_history.append(
            {
                "action": "approved",
                "review_id": review_id,
                "comment": rationale[:2000],
                "recorded_at": datetime.datetime.now().isoformat(),
            }
        )
        self._checkpoint.updated_at = datetime.datetime.now().isoformat()
        self.save(self._checkpoint)

    def request_quality_repair(
        self, review_id: str, failed_subtasks: list[str], comment: str
    ) -> None:
        """Invalidate selected code hand-offs for one reviewer-directed repair."""
        if self._checkpoint is None:
            raise RuntimeError("CheckpointManager 尚未初始化")
        if self._checkpoint.workflow_state != "waiting_quality_review":
            raise RuntimeError("当前任务不在执行质量复核状态")
        if self._checkpoint.quality_review_id != review_id:
            raise RuntimeError("结果文件已变化，请重新读取最新质量复核报告")
        if self._checkpoint.quality_review_repairs >= 1:
            raise RuntimeError("本任务已使用一次质量复核定向返修，不再自动返修")
        subtasks = sorted(set(failed_subtasks))
        if not subtasks:
            raise RuntimeError("质量返修至少需要一个子题")
        rationale = comment.strip()
        if not rationale:
            raise RuntimeError("质量返修意见不能为空")
        self._checkpoint.quality_review_repairs += 1
        self._checkpoint.quality_review_status = "repair_requested"
        self._checkpoint.workflow_state = "quality_repair"
        self._checkpoint.quality_repair_source_prepared = False
        self._checkpoint.executed_cell_indices.clear()
        self._checkpoint.has_variable_snapshot = False
        for key in subtasks:
            self._checkpoint.solution_coder_responses.pop(key, None)
        # 质量复核可以只退回正式题，但此前的敏感性探索可能已经被判定为
        # 错误草稿。它不是正式题证据，不能作为新返修论文的旧 handoff 复用。
        self._checkpoint.solution_coder_responses.pop("sensitivity_analysis", None)
        # 冻结事实变化后所有 Writer 章节都必须重建，不能复用旧论文文字。
        self._checkpoint.completed_phases.clear()
        self._checkpoint.quality_review_history.append(
            {
                "action": "repair_requested",
                "review_id": review_id,
                "failed_subtasks": subtasks,
                "comment": rationale[:2000],
                "recorded_at": datetime.datetime.now().isoformat(),
            }
        )
        self._checkpoint.updated_at = datetime.datetime.now().isoformat()
        self.save(self._checkpoint)

    def quality_repair_source_is_prepared(self) -> bool:
        """Return whether the current quality-repair source chain is durable."""
        return bool(
            self._checkpoint is not None
            and self._checkpoint.quality_repair_source_prepared
        )

    def prepare_quality_repair_source(self, notebook_path: str | None = None) -> bool:
        """Atomically establish the one clean source boundary for quality repair.

        The old notebook and variable snapshot are moved under the task's audit
        directory exactly once.  Callers then append new cells to the now-clean
        notebook.  Returning ``False`` means a prior candidate/resume already
        prepared this chain, so its current source must be left untouched.
        """
        if self._checkpoint is None:
            raise RuntimeError("CheckpointManager 尚未初始化")
        if self._checkpoint.quality_repair_source_prepared:
            return False
        if self._checkpoint.workflow_state not in {"quality_repair", "repairing"}:
            raise RuntimeError("当前任务不在质量返修源码准备状态")

        root = Path(self.work_dir).resolve()
        source = Path(notebook_path) if notebook_path else root / "notebook.ipynb"
        source = source.resolve()
        try:
            source.relative_to(root)
        except ValueError as exc:
            raise RuntimeError("质量返修 notebook 路径越出任务目录") from exc

        files_to_archive = [
            path
            for path in (
                source,
                root / "variable_snapshot.pkl",
                root / "variable_snapshot_meta.json",
            )
            if path.is_file()
        ]
        if files_to_archive:
            archive_root = root / "failed_attempts" / "quality_repair"
            archive_root.mkdir(parents=True, exist_ok=True)
            archive_dir = archive_root / datetime.datetime.now().strftime(
                "%Y%m%d-%H%M%S-%f"
            )
            archive_dir.mkdir(parents=True, exist_ok=False)
            moved: list[tuple[Path, Path]] = []
            try:
                for path in files_to_archive:
                    destination = archive_dir / path.name
                    path.replace(destination)
                    moved.append((path, destination))
            except OSError as exc:
                for original, archived in reversed(moved):
                    try:
                        archived.replace(original)
                    except OSError:
                        logger.error(f"质量返修源码隔离回滚失败: {original.name}")
                raise RuntimeError("质量返修无法隔离旧源码或变量快照") from exc

        self._checkpoint.quality_repair_source_prepared = True
        self._checkpoint.executed_cell_indices.clear()
        self._checkpoint.has_variable_snapshot = False
        self._checkpoint.updated_at = datetime.datetime.now().isoformat()
        self.save(self._checkpoint)
        logger.warning("质量返修已建立一次性干净源码边界")
        return True

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

    def apply_paper_repair_candidate(
        self,
        sections: dict[str, dict],
        *,
        previous_preflight_report: dict,
        candidate_audit: dict,
    ) -> None:
        """Persist one reviewed manuscript replacement for export-only resume.

        A post-freeze paper repair is deliberately narrower than a normal
        Writer retry: it may replace prose, but must not alter code evidence,
        frozen results, or the ModelPlan.  The caller has already validated a
        complete candidate in an isolated staging directory.  Storing the same
        replacement in ``completed_phases`` prevents a later ``/resume`` from
        silently restoring stale Writer text before it exports the paper.
        """
        if self._checkpoint is None:
            raise RuntimeError("CheckpointManager 尚未初始化")
        if self._checkpoint.workflow_state != "frozen":
            raise RuntimeError("论文候选修复只允许在冻结结果状态执行")
        if self._checkpoint.paper_repair_attempts:
            raise RuntimeError("本任务已使用论文预检回修预算，不能再次替换正文")
        if not isinstance(sections, dict) or not sections:
            raise RuntimeError("论文候选修复缺少章节内容")

        expected_keys = set(self._checkpoint.completed_phases)
        actual_keys = set(sections)
        if expected_keys != actual_keys:
            missing = sorted(expected_keys - actual_keys)
            extra = sorted(actual_keys - expected_keys)
            details: list[str] = []
            if missing:
                details.append("缺少=" + ", ".join(missing))
            if extra:
                details.append("多出=" + ", ".join(extra))
            raise RuntimeError("论文候选章节集合必须与既有 Writer 阶段完全一致：" + "；".join(details))

        now = datetime.datetime.now().isoformat()
        for key, response in sections.items():
            if not isinstance(response, dict) or not isinstance(
                response.get("response_content"), str
            ):
                raise RuntimeError(f"论文候选章节格式无效: {key}")
            phase = self._checkpoint.completed_phases[key]
            phase.writer_response = response
            phase.completed_at = now

        self._checkpoint.paper_repair_attempts = 1
        self._checkpoint.workflow_state = "paper_repair_pending_export"
        self._checkpoint.last_paper_preflight_failure = {
            "report": previous_preflight_report,
            "candidate_audit": candidate_audit,
            "recorded_at": now,
        }
        self._checkpoint.updated_at = now
        self.save(self._checkpoint)

    def apply_editorial_repair_candidate(
        self,
        sections: dict[str, dict],
        *,
        editorial_quality_failure: dict,
        candidate_audit: dict,
    ) -> None:
        """Persist one post-completion editorial replacement for export-only resume.

        This is intentionally distinct from :meth:`apply_paper_repair_candidate`.
        The normal path remains limited to a frozen task with an unused ordinary
        preflight-repair budget, while this path is only for a completed or
        preflight-passed manuscript that a later editorial-quality report rejects.
        """
        if self._checkpoint is None:
            raise RuntimeError("CheckpointManager 尚未初始化")
        if self._checkpoint.workflow_state not in {"paper_preflight_passed", "completed"}:
            raise RuntimeError("编辑质量候选只允许在论文预检通过或已完成状态执行")
        if self._checkpoint.editorial_repair_attempts:
            raise RuntimeError("本任务已使用编辑质量返修预算，不能再次替换正文")
        if not isinstance(sections, dict) or not sections:
            raise RuntimeError("编辑质量候选缺少章节内容")

        expected_keys = set(self._checkpoint.completed_phases)
        actual_keys = set(sections)
        if expected_keys != actual_keys:
            missing = sorted(expected_keys - actual_keys)
            extra = sorted(actual_keys - expected_keys)
            details: list[str] = []
            if missing:
                details.append("缺少=" + ", ".join(missing))
            if extra:
                details.append("多出=" + ", ".join(extra))
            raise RuntimeError("编辑质量候选章节集合必须与既有 Writer 阶段完全一致：" + "；".join(details))

        now = datetime.datetime.now().isoformat()
        for key, response in sections.items():
            if not isinstance(response, dict) or not isinstance(
                response.get("response_content"), str
            ):
                raise RuntimeError(f"编辑质量候选章节格式无效: {key}")
            phase = self._checkpoint.completed_phases[key]
            if phase.writer_response is None:
                raise RuntimeError(f"编辑质量候选缺少既有 Writer 阶段: {key}")
            phase.writer_response = response
            phase.completed_at = now

        self._checkpoint.editorial_repair_attempts = 1
        self._checkpoint.workflow_state = "editorial_repair_pending_export"
        self._checkpoint.last_editorial_quality_failure = {
            "report": editorial_quality_failure,
            "candidate_audit": candidate_audit,
            "recorded_at": now,
        }
        self._checkpoint.updated_at = now
        self.save(self._checkpoint)

    def stage_presentation_reflow(self, *, reflow_audit: dict) -> None:
        """Stage one frozen, no-prose-change export refresh.

        This narrow transition exists for deterministic renderer/postprocessor
        fixes discovered by visual review.  It neither changes Writer hand-offs
        nor permits a second editorial candidate; the ordinary export-only
        resume still reconstructs the paper from the persisted hand-offs and
        reruns every export gate.
        """
        if self._checkpoint is None:
            raise RuntimeError("CheckpointManager 尚未初始化")
        if self._checkpoint.workflow_state not in {"paper_preflight_passed", "completed"}:
            raise RuntimeError("版式重排只允许在论文预检通过或已完成状态执行")
        if self._checkpoint.presentation_reflow_attempts:
            raise RuntimeError("本任务已使用版式重排预算，不能再次自动重排")
        if not isinstance(reflow_audit, dict) or not reflow_audit:
            raise RuntimeError("版式重排缺少审计记录")

        now = datetime.datetime.now().isoformat()
        self._checkpoint.presentation_reflow_attempts = 1
        self._checkpoint.workflow_state = "presentation_reflow_pending_export"
        self._checkpoint.last_presentation_reflow = {
            "audit": reflow_audit,
            "recorded_at": now,
        }
        self._checkpoint.updated_at = now
        self.save(self._checkpoint)

    def apply_format_compliance_candidate(
        self,
        sections: dict[str, dict],
        *,
        candidate_audit: dict,
    ) -> None:
        """Persist one participant-authorized format-compliance replacement.

        This path is deliberately independent from the exhausted paper and
        editorial repair budgets.  It is only reachable through the bounded
        local candidate tool after an isolated preflight succeeds, then the
        normal resume path re-runs exports and all technical gates.
        """
        if self._checkpoint is None:
            raise RuntimeError("CheckpointManager 尚未初始化")
        if self._checkpoint.workflow_state not in {"paper_preflight_passed", "completed"}:
            raise RuntimeError("格式合规候选只允许在论文预检通过或已完成状态执行")
        if self._checkpoint.format_compliance_attempts:
            raise RuntimeError("本任务已使用格式合规候选预算，不能再次替换正文")
        if not isinstance(sections, dict) or not sections:
            raise RuntimeError("格式合规候选缺少章节内容")

        expected_keys = set(self._checkpoint.completed_phases)
        actual_keys = set(sections)
        if expected_keys != actual_keys:
            missing = sorted(expected_keys - actual_keys)
            extra = sorted(actual_keys - expected_keys)
            details: list[str] = []
            if missing:
                details.append("缺少=" + ", ".join(missing))
            if extra:
                details.append("多出=" + ", ".join(extra))
            raise RuntimeError("格式合规候选章节集合必须与既有 Writer 阶段完全一致：" + "；".join(details))

        now = datetime.datetime.now().isoformat()
        for key, response in sections.items():
            if not isinstance(response, dict) or not isinstance(
                response.get("response_content"), str
            ):
                raise RuntimeError(f"格式合规候选章节格式无效: {key}")
            phase = self._checkpoint.completed_phases[key]
            if phase.writer_response is None:
                raise RuntimeError(f"格式合规候选缺少既有 Writer 阶段: {key}")
            phase.writer_response = response
            phase.completed_at = now

        self._checkpoint.format_compliance_attempts = 1
        self._checkpoint.workflow_state = "format_compliance_pending_export"
        self._checkpoint.last_format_compliance = {
            "candidate_audit": candidate_audit,
            "recorded_at": now,
        }
        self._checkpoint.updated_at = now
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
        self._checkpoint.quality_repair_source_prepared = False
        self._checkpoint.updated_at = datetime.datetime.now().isoformat()
        self.save(self._checkpoint)

    def record_modeling_revision_request(self) -> int:
        """Record one reviewer-requested ModelPlan revision with a hard cap."""
        if self._checkpoint is None:
            raise RuntimeError("CheckpointManager 尚未初始化")
        if self._checkpoint.modeling_review_revisions >= 1:
            raise RuntimeError("本任务已使用一次建模方案退回修订，不再自动重建模")
        self._checkpoint.modeling_review_revisions += 1
        self._checkpoint.workflow_state = "modeling_revision"
        self._checkpoint.updated_at = datetime.datetime.now().isoformat()
        self.save(self._checkpoint)
        return self._checkpoint.modeling_review_revisions

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
