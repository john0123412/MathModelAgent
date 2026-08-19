"""工作流模块，编排多 Agent 协作完成数学建模任务。"""

import asyncio
import datetime
import hashlib
import json
import os
import re
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
import nbformat
from app.core.agents import WriterAgent, CoderAgent, CoordinatorAgent, ModelerAgent
from app.core.checkpoint import CheckpointManager, TaskCheckpoint
from app.schemas.A2A import CoordinatorToModeler, CoderToWriter, ModelerToCoder, WriterResponse
from app.schemas.enums import CompTemplate, ExportProfile, FormatOutPut
from app.schemas.request import DEFAULT_MODELING_EXPORT_PROFILE, Problem
from app.schemas.response import SystemMessage
from app.services import user_input_queue
from app.services.task_recovery import write_task_request_snapshot
from app.tools.base_interpreter import BaseCodeInterpreter
from app.tools.openalex_scholar import OpenAlexScholar
from app.utils.log_util import logger
from app.utils.common_utils import create_work_dir, get_config_template, get_work_dir
from app.models.user_output import UserOutput
from app.config.setting import settings
from app.tools.interpreter_factory import create_interpreter
from app.services.redis_manager import redis_manager
from app.tools.notebook_serializer import NotebookSerializer
from app.tools.pdf_exporter import export_markdown_to_pdf
from app.tools.tex_project_exporter import export_markdown_to_latex_project
from app.tools.candidate_exporter import write_candidate_manifest
from app.tools.export_profiles import normalize_export_profile
from app.tools.export_template_override import (
    TemplateOverrideError,
    get_editorial_policy_override,
    get_pdf_visual_constraints,
    load_export_template_override,
)
from app.tools.paper_postprocessor import build_result_fact_summary, prepare_paper_markdown
from app.tools.result_integrity import validate_result_freeze
from app.tools.pdf_visual_checker import (
    CUMCM2026_STRICT_EDITORIAL_QUALITY_POLICY,
    DEFAULT_EDITORIAL_QUALITY_POLICY,
    check_pdf_visual,
)
from app.tools.submission_audit import write_submission_audit_report
from app.tools.execution_validation import (
    write_execution_validation_report,
    write_frozen_results_from_execution_validation,
)
from app.tools.execution_quality_review import write_execution_quality_review
from app.tools.ai_usage_exporter import ensure_ai_usage_details
from app.core.flows import Flows
from app.core.llm.llm_factory import LLMFactory
from app.schemas.problem_contract import (
    ProblemContract,
    build_problem_contract,
    validate_modeler_plan,
)


_FORMAL_EDITORIAL_EXPORT_PROFILES = {"cumcm2025", "cumcm2026"}


def _pdf_editorial_quality_policy(
    export_profile: ExportProfile | str | None,
) -> str:
    """Choose the internal PDF quality policy for the selected profile.

    This policy is intentionally not an assertion about official CUMCM page
    limits.  It only makes the project's formal CUMCM candidate path reject
    the low-density abstract/body failure that this audit uncovered; all
    non-CUMCM and smoke paths retain the non-blocking diagnostic policy.
    """
    profile = normalize_export_profile(export_profile).value
    return (
        CUMCM2026_STRICT_EDITORIAL_QUALITY_POLICY
        if profile in _FORMAL_EDITORIAL_EXPORT_PROFILES
        else DEFAULT_EDITORIAL_QUALITY_POLICY
    )


class WorkFlow:
    """工作流基类。"""

    def __init__(self):
        pass

    def execute(self) -> None:
        """执行工作流。"""
        # RichPrinter.workflow_start()
        # RichPrinter.workflow_end()
        pass


class MathModelWorkFlow(WorkFlow):
    """数学建模工作流，协调协调者、建模手、代码手和写作手完成完整建模任务。"""

    task_id: str  #
    work_dir: str  # worklow work dir
    ques_count: int = 0  # 问题数量
    questions: dict[str, str | int] = {}  # 问题
    cancel_event: asyncio.Event | None = None  # 取消信号

    async def _check_cancelled(self) -> None:
        """检查是否收到取消信号，若已取消则发布通知并抛出 CancelledError。"""
        if self.cancel_event and self.cancel_event.is_set():
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="任务已停止", type="warning"),
            )
            raise asyncio.CancelledError("任务被用户停止")

    async def _cleanup_interpreter(
        self, code_interpreter: BaseCodeInterpreter
    ) -> None:
        """Release the execution environment without masking workflow failures."""
        try:
            await code_interpreter.cleanup()
        except Exception as exc:
            logger.warning(
                "代码执行环境清理失败: error_type={}", type(exc).__name__
            )

    @asynccontextmanager
    async def _managed_interpreter(self, code_interpreter: BaseCodeInterpreter):
        """Guarantee cleanup when coding, cancellation, or export preparation fails."""
        try:
            yield code_interpreter
        finally:
            await self._cleanup_interpreter(code_interpreter)

    async def _build_agents(
        self,
        coder_llm,
        writer_llm,
        comp_template: CompTemplate,
        format_output: FormatOutPut,
        user_input_provider,
        problem_context: str,
        checkpoint_manager: CheckpointManager | None = None,
    ) -> tuple[NotebookSerializer, BaseCodeInterpreter, CoderAgent, WriterAgent]:
        """构建代码手/写作手 Agent 及其依赖的沙盒环境（execute 与 resume 共享）。

        Args:
            coder_llm: 代码手使用的 LLM 实例。
            writer_llm: 写作手使用的 LLM 实例。
            comp_template: 竞赛模板类型。
            format_output: 输出格式。
            user_input_provider: 实时消息干预的输入提供函数。
            problem_context: 原始题面，供 Coder 在首次调用时核对确定性参数。

        Returns:
            (notebook_serializer, code_interpreter, coder_agent, writer_agent) 元组。
        """
        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="正在创建代码执行环境"),
        )

        notebook_serializer = NotebookSerializer(work_dir=self.work_dir)
        code_interpreter = await create_interpreter(
            task_id=self.task_id,
            work_dir=self.work_dir,
            notebook_serializer=notebook_serializer,
            timeout=3000,
        )
        try:
            scholar = OpenAlexScholar(
                task_id=self.task_id,
                email=settings.OPENALEX_EMAIL,
                api_key=settings.OPENALEX_API_KEY,
                tavily_api_key=settings.TAVILY_API_KEY,
                web_search_enabled=settings.SEARCH_ENABLED,
            )
            if not settings.OPENALEX_EMAIL:
                logger.warning("OPENALEX_EMAIL 未配置，将跳过 OpenAlex，继续使用其他文献源")
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content="OpenAlex Email 未配置，文献检索将使用其他可用来源",
                        type="warning",
                    ),
                )

            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="创建完成"),
            )

            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="初始化代码手"),
            )

            coder_agent = CoderAgent(
                task_id=self.task_id,
                model=coder_llm,
                work_dir=self.work_dir,
                max_chat_turns=settings.MAX_CHAT_TURNS,
                max_retries=settings.MAX_RETRIES,
                code_interpreter=code_interpreter,
                context_window=settings.CODER_CONTEXT_WINDOW,
                cancel_event=self.cancel_event,
                user_input_provider=user_input_provider,
                problem_context=problem_context,
                checkpoint_manager=checkpoint_manager,
            )

            writer_agent = WriterAgent(
                task_id=self.task_id,
                model=writer_llm,
                comp_template=comp_template,
                format_output=format_output,
                scholar=scholar,
                context_window=settings.WRITER_CONTEXT_WINDOW,
                cancel_event=self.cancel_event,
                user_input_provider=user_input_provider,
            )

            return notebook_serializer, code_interpreter, coder_agent, writer_agent
        except BaseException:
            await self._cleanup_interpreter(code_interpreter)
            raise

    async def _replay_notebook(
        self,
        code_interpreter: BaseCodeInterpreter,
        checkpoint_manager: CheckpointManager | None = None,
    ) -> None:
        """重放 notebook.ipynb 中已成功执行的代码单元格，重建内核变量状态（仅续传时调用）。

        优先级：
        1. 从变量快照恢复（最快，秒级）
        2. 全量重放（快照缺失或恢复失败时的 fallback）

        Args:
            code_interpreter: 新建的代码解释器实例。
            checkpoint_manager: 检查点管理器，用于更新快照可用状态。
        """
        # 尝试从变量快照恢复（最快）
        from app.tools.variable_snapshot import VariableSnapshot

        notebook_path = os.path.join(self.work_dir, "notebook.ipynb")
        snapshot = VariableSnapshot(self.work_dir)
        replay_mode = "全量重放"

        if snapshot.exists():
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="从变量快照恢复计算环境..."),
            )

            # 获取内核客户端
            kernel_client = getattr(code_interpreter, "kc", None)
            if kernel_client and await snapshot.load(kernel_client):
                logger.info("变量快照恢复成功，丢弃快照后的未完成阶段代码")
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content="计算环境恢复完成（从快照；未完成阶段不会重放）"
                    ),
                )
                return
            else:
                logger.warning("变量快照恢复失败，降级为全量重放")
                if checkpoint_manager is not None:
                    checkpoint_manager.set_variable_snapshot_exists(False)
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content="快照恢复失败，使用全量重放..."),
                )

        if not os.path.exists(notebook_path):
            logger.info("未找到 notebook.ipynb，跳过内核状态重放")
            return

        # 读取 notebook
        nb = nbformat.read(notebook_path, as_version=4)

        # 筛选所有有效的代码单元格（带索引）
        all_code_cells = [
            (i, cell)
            for i, cell in enumerate(nb.get("cells", []))
            if cell.get("cell_type") == "code"
            and not any(
                o.get("output_type") == "error" for o in (cell.get("outputs") or [])
            )
            and (cell.get("source") or "").strip()
        ]

        # A restored snapshot is returned above.  Replaying arbitrary cells after a
        # snapshot can repeat a cancelled, expensive partial phase and corrupt the
        # durable checkpoint boundary, so fallback replay is intentionally all-or-none.
        cells_to_replay = all_code_cells

        total = len(cells_to_replay)
        total_all = len(all_code_cells)

        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(
                content=f"正在{replay_mode}计算环境: {total}/{total_all} 个单元格..."
            ),
        )

        replayed = 0
        for cell_index, cell in cells_to_replay:
            _, error_occurred, error_message = await code_interpreter.replay_code(
                cell["source"]
            )
            if error_occurred:
                raise RuntimeError(f"重放单元格 {cell_index} 失败: {error_message}")
            replayed += 1

            if replayed % 10 == 0 or replayed == total:
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content=f"重建计算环境: {replayed}/{total} 个单元格"),
                )

        logger.info(
            f"内核状态重放完成（{replay_mode}），共重放 {replayed} 个代码单元格"
        )
        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(
                content=f"计算环境重建完成（{replay_mode}），共重放 {replayed} 个单元格"
            ),
        )

    def _get_notebook_cell_counts(self) -> tuple[int, int]:
        """获取当前 notebook 的总单元格和代码单元格数量。"""
        notebook_path = os.path.join(self.work_dir, "notebook.ipynb")
        if not os.path.exists(notebook_path):
            return 0, 0
        try:
            nb = nbformat.read(notebook_path, as_version=4)
            total_cell_count = len(nb.get("cells", []))
            code_cell_count = sum(
                1 for cell in nb.get("cells", []) if cell.get("cell_type") == "code"
            )
            return total_cell_count, code_cell_count
        except Exception as e:
            logger.warning(f"读取 notebook 单元格数量失败: {e}")
            return 0, 0

    def _archive_unverified_execution_context(self) -> None:
        """Keep failed evidence for audit while ensuring a repaired plan starts clean."""
        archived_dir = os.path.join(
            self.work_dir,
            "failed_attempts",
            datetime.datetime.now().strftime("%Y%m%d-%H%M%S"),
        )
        names = (
            "notebook.ipynb",
            "variable_snapshot.pkl",
            "variable_snapshot_meta.json",
            "execution_validation.json",
            "execution_validation_report.json",
            "frozen_results.json",
        )
        existing = [
            name for name in names if os.path.isfile(os.path.join(self.work_dir, name))
        ]
        if not existing:
            return
        os.makedirs(archived_dir, exist_ok=True)
        for name in existing:
            os.replace(
                os.path.join(self.work_dir, name), os.path.join(archived_dir, name)
            )
        logger.warning(f"已归档未通过的执行上下文，重新建立干净求解环境: {archived_dir}")

    @staticmethod
    def _safe_non_negative_int(value, default: int = 0) -> int:
        """将 metadata 字段转换为非负整数。"""
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(parsed, 0)

    @staticmethod
    def _failed_subtasks_from_execution_report(
        report: dict,
        required_subtasks: list[str],
    ) -> list[str]:
        """Map final validation failures back to formal question keys.

        A malformed top-level manifest cannot be assigned safely, so it is
        treated as a repair request for every required question.  Per-question
        checks retain the already-passed Coder checkpoints of other questions.
        """
        failed: set[str] = set()
        global_failure = False
        for check in report.get("checks", []):
            if not isinstance(check, dict) or check.get("passed") is True:
                continue
            check_id = str(check.get("id", ""))
            for key in required_subtasks:
                if check_id == key or check_id.startswith(f"{key}."):
                    failed.add(key)
                    break
            else:
                if check_id in {"execution_manifest", "required_subtasks", "metrics"}:
                    global_failure = True
        return list(required_subtasks) if global_failure else sorted(failed)

    @staticmethod
    def _repair_failure_summary(report: dict, failed_subtasks: list[str]) -> str:
        """Keep the Coder repair context factual and bounded."""
        lines: list[str] = []
        for check in report.get("checks", []):
            if not isinstance(check, dict) or check.get("passed") is True:
                continue
            check_id = str(check.get("id", ""))
            if check_id in {"execution_manifest", "required_subtasks", "metrics"} or any(
                check_id == key or check_id.startswith(f"{key}.")
                for key in failed_subtasks
            ):
                lines.append(f"- {check_id}: {check.get('message', '验证失败')}")
        return "\n".join(lines[:40]) or "- 未能从报告中定位到单项失败；请核对 execution_validation_report.json。"

    @staticmethod
    def _can_reuse_evidence_after_validator_fix(
        checkpoint: TaskCheckpoint | None,
        current_report: dict,
        required_subtasks: list[str],
    ) -> bool:
        """Allow a narrowly-scoped recovery from a corrected validator rule.

        This is deliberately not a generic resume bypass.  It applies only when
        the persisted failure was entirely the old physical balance-residual
        rule for the same formal questions and the current full validation is
        already PASS against the durable execution manifest.
        """
        if (
            checkpoint is None
            or checkpoint.workflow_state != "repairing"
            or current_report.get("status") != "PASS"
        ):
            return False
        previous_report = checkpoint.last_validation_failure.get("report", {})
        checks = previous_report.get("checks", [])
        failed_ids = {
            str(check.get("id", ""))
            for check in checks
            if isinstance(check, dict) and check.get("passed") is False
        }
        expected_ids = {f"{key}.balance_residual" for key in required_subtasks}
        return bool(failed_ids) and failed_ids.issubset(expected_ids)

    def _evidence_backed_coder_response(self, key: str) -> CoderToWriter:
        """Build a Writer hand-off that carries no unverified model narration."""
        images = [
            name
            for name in os.listdir(self.work_dir)
            if name.startswith(f"{key}_")
            and name.lower().endswith((".png", ".jpg", ".jpeg", ".svg"))
        ]
        return CoderToWriter(
            code_response=(
                "本题既有执行证据已通过当前完整门禁并被冻结；"
                "正文数值、约束结论和图表说明必须以 frozen_results.json 与结果 CSV 为准。"
            ),
            created_images=sorted(images),
            execution_attempted=True,
            execution_succeeded=True,
            execution_error_occurred=False,
        )

    @staticmethod
    def _quality_repair_sensitivity_response() -> CoderToWriter:
        """Replace stale sensitivity prose with a source-only hand-off.

        Sensitivity analysis is not a formal quesN evidence owner.  After a
        quality-review rejection its previous exploratory numbers are not
        trustworthy, so a repair must not call the model merely to recreate a
        second numerical baseline.  Writer may mention only the refreshed
        formal sources if the problem requires a sensitivity section.
        """
        return CoderToWriter(
            code_response=(
                "质量返修已使旧敏感性探索交接失效；本轮不复用其数值或图表。"
                "如需撰写扩展分析，只能引用本轮正式题的结果 CSV、"
                "execution_validation.json 和冻结结果，不能新增敏感性数值。"
            ),
            created_images=[],
            execution_attempted=True,
            execution_succeeded=True,
            execution_error_occurred=False,
        )

    async def _run_solution_flows(
        self,
        flows: Flows,
        modeler_response: ModelerToCoder,
        coder_agent: CoderAgent,
        writer_agent: WriterAgent,
        code_interpreter: BaseCodeInterpreter,
        user_output: UserOutput,
        checkpoint_manager: CheckpointManager,
        config_template: dict,
        recovery_context: str = "",
        quality_repair: bool = False,
    ) -> str | None:
        """先完成全部代码求解与验证冻结，再允许论文手撰写。"""
        solution_flows = flows.get_solution_flows(self.questions, modeler_response)
        if checkpoint_manager.repair_attempts_exhausted():
            raise RuntimeError(
                "最终执行验证已连续两次失败；按恢复规程已停止自动回修，"
                "请由指定决策人切换已验证 provider 或确认低开销可复核算法后再续传。"
            )
        coder_responses: dict[str, CoderToWriter] = {}
        required_subtasks = [
            flow_key
            for flow_key in solution_flows
            if flow_key.startswith("ques") and flow_key != "ques_count"
        ]
        checkpoint = checkpoint_manager._checkpoint
        quality_repair = quality_repair or bool(
            checkpoint
            and checkpoint.workflow_state in {"quality_repair", "repairing"}
            and checkpoint_manager.quality_repair_source_is_prepared()
        )
        recovery_reuses_verified_evidence = False
        if checkpoint is not None and checkpoint.workflow_state == "repairing":
            current_report = write_execution_validation_report(
                self.work_dir,
                required_subtasks=required_subtasks,
            )
            recovery_reuses_verified_evidence = self._can_reuse_evidence_after_validator_fix(
                checkpoint,
                current_report,
                required_subtasks,
            )
            if recovery_reuses_verified_evidence:
                logger.warning(
                    "旧验证器规则已修正；复用当前完整门禁通过的执行证据，避免重复 Coder 调用"
                )

        for key, value in solution_flows.items():
            await self._check_cancelled()

            if quality_repair and key == "sensitivity_analysis":
                # A prior sensitivity handoff is intentionally removed by
                # request_quality_repair.  Keep this stage deterministic and
                # source-only instead of waking the provider for stale data.
                coder_response = self._quality_repair_sensitivity_response()
                coder_responses[key] = coder_response
                checkpoint_manager.mark_solution_coder_completed(
                    key, coder_response.model_dump()
                )
                continue

            saved_coder_response = checkpoint_manager.get_solution_coder_response(key)
            if saved_coder_response is not None:
                logger.info(f"复用已完成的代码阶段，等待最终验证后再写作: {key}")
                coder_responses[key] = CoderToWriter.model_validate(saved_coder_response)
                continue

            if recovery_reuses_verified_evidence and key in required_subtasks:
                coder_response = self._evidence_backed_coder_response(key)
                coder_responses[key] = coder_response
                checkpoint_manager.mark_solution_coder_completed(
                    key, coder_response.model_dump()
                )
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content=f"复用已验证执行证据，跳过重复代码调用: {key}",
                        type="success",
                    ),
                )
                continue

            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content=f"代码手开始求解{key}"),
            )

            coder_prompt = value["coder_prompt"]
            if recovery_context:
                coder_prompt = (
                    "【受控恢复上下文】\n"
                    f"{recovery_context}\n"
                    "请据此重新检查本题计算路径；不得把恢复过程或失败描述写入论文。\n\n"
                    + coder_prompt
                )
            coder_kwargs = {"quality_repair": True} if quality_repair else {}
            coder_response = await coder_agent.run(
                prompt=coder_prompt, subtask_title=key, **coder_kwargs
            )

            if (
                not coder_response.execution_attempted
                or not coder_response.execution_succeeded
                or coder_response.execution_error_occurred
            ):
                if key not in required_subtasks:
                    # EDA is allowed to execute code but never owns a formal
                    # quesN evidence manifest.  It must still stop the task
                    # when it fails, yet writing `required_subtasks=["eda"]`
                    # creates a misleading report that later treats EDA as a
                    # required formal question.
                    await redis_manager.publish_message(
                        self.task_id,
                        SystemMessage(
                            content=(
                                f"非正式代码阶段 {key} 未成功执行，已停止进入正式问题；"
                                "未生成正式执行验证报告。"
                            ),
                            type="error",
                        ),
                    )
                    raise RuntimeError(
                        f"非正式代码阶段 {key} 未成功执行，无法进入正式问题"
                    )

                # Requiring the per-question manifest keeps the persisted
                # report aligned with the authoritative failed task status
                # instead of emitting a misleading PASS for a clean notebook
                # that never recorded execution evidence.
                report = write_execution_validation_report(
                    self.work_dir,
                    required_subtasks=[key],
                )
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content=(
                            f"代码手未提供可验证的成功执行证据，已停止 {key} 的写作；"
                            "请查看 execution_validation_report.json"
                        ),
                        type="error",
                    ),
                )
                diagnostic_status = report.get("status")
                diagnostic_summary = (
                    "尚未执行正式逐题验证"
                    if diagnostic_status == "PASS"
                    else f"诊断报告状态: {diagnostic_status}"
                )
                raise RuntimeError(
                    f"代码阶段 {key} 未提供成功执行证据；{diagnostic_summary}"
                )

            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content=f"代码手求解成功{key}", type="success"),
            )
            coder_responses[key] = coder_response
            checkpoint_manager.mark_solution_coder_completed(
                key, coder_response.model_dump()
            )

            # 保存变量快照（用于下次快速恢复）
            from app.tools.variable_snapshot import VariableSnapshot

            snapshot = VariableSnapshot(self.work_dir)
            kernel_client = getattr(code_interpreter, "kc", None)
            if kernel_client:
                try:
                    notebook_cell_count, notebook_code_cell_count = (
                        self._get_notebook_cell_counts()
                    )
                    saved = await snapshot.save(
                        kernel_client,
                        notebook_cell_count=notebook_cell_count,
                        notebook_code_cell_count=notebook_code_cell_count,
                    )
                    checkpoint_manager.set_variable_snapshot_exists(saved)
                    if saved:
                        logger.info(f"变量快照已保存: {key}")
                    else:
                        logger.warning(f"变量快照保存失败: {key}")
                except Exception as e:
                    checkpoint_manager.set_variable_snapshot_exists(False)
                    logger.warning(f"保存变量快照失败: {e}")

            # 强制清空内核状态，确保下一个问题必须从文件读取数据（避免跨问题隐式依赖）
            if hasattr(code_interpreter, "restart_kernel"):
                await code_interpreter.restart_kernel()
                logger.info(f"已重置内核，确保 {key} 与后续子任务状态隔离")

        # `execution_validation.json` is assembled by the trusted evidence
        # recorder called within each formal Coder subtask.  Do not ask the
        # model to maintain a second, cross-question manifest here: that was
        # the source of `tasks`/`subtasks`, path and SHA-256 hand-off errors.
        report = write_execution_validation_report(
            self.work_dir,
            required_subtasks=required_subtasks,
        )
        if report.get("status") != "PASS":
            failed_subtasks = self._failed_subtasks_from_execution_report(
                report, required_subtasks
            )
            if not failed_subtasks:
                # Keep the failure actionable even if a future validator adds a
                # new global check without a question prefix.
                failed_subtasks = list(required_subtasks)
            repair_attempt = checkpoint_manager.record_validation_failure(
                failed_subtasks, report
            )
            if repair_attempt == 1:
                checkpoint_manager.invalidate_solution_coder_responses(failed_subtasks)
                failure_summary = self._repair_failure_summary(report, failed_subtasks)
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content=(
                            "最终验证未通过，开始一次定向回修："
                            + "、".join(failed_subtasks)
                            + "；已通过问题的代码检查点将保留。"
                        ),
                        type="warning",
                    ),
                )
                for key in failed_subtasks:
                    await self._check_cancelled()
                    repair_prompt = (
                        "这是最终执行验证后的唯一一次定向回修。只修复当前正式问题，"
                        "不得重算或改写已通过问题。必须实际执行并覆盖本题结果文件，"
                        "随后通过受控证据记录流程更新本题的验证证据。\n\n"
                        f"当前问题：{key}\n原始求解要求：\n{solution_flows[key]['coder_prompt']}\n\n"
                        "验证失败项：\n"
                        f"{failure_summary}\n\n"
                        "保留所有已通过问题的文件和数值；不要把失败解释写进论文。"
                    )
                    repaired_response = await coder_agent.run(
                        prompt=repair_prompt,
                        subtask_title=f"{key}_repair",
                    )
                    if (
                        not repaired_response.execution_attempted
                        or not repaired_response.execution_succeeded
                        or repaired_response.execution_error_occurred
                    ):
                        # The original validation failure plus this failed repair
                        # consumes the two-failure budget immediately.
                        checkpoint_manager.record_validation_failure(
                            failed_subtasks,
                            {"checks": [{"id": key, "passed": False, "message": "定向回修代码未成功执行。"}]},
                        )
                        raise RuntimeError(
                            "定向回修代码未成功执行；已按连续两次失败恢复规程停止。"
                        )
                    coder_responses[key] = repaired_response
                    checkpoint_manager.mark_solution_coder_completed(
                        key, repaired_response.model_dump()
                    )

                # The repair Coder call has to use `record_execution_evidence`
                # for the repaired question.  Revalidate directly from the
                # backend-owned manifest; never introduce a free-form manifest
                # repair turn.
                report = write_execution_validation_report(
                    self.work_dir, required_subtasks=required_subtasks
                )

            if report.get("status") != "PASS":
                # The first failure was recorded before repair.  A failed repair
                # is the second real failure and must not enter an automatic loop.
                if repair_attempt == 1:
                    exhausted_subtasks = (
                        self._failed_subtasks_from_execution_report(
                            report, required_subtasks
                        )
                        or failed_subtasks
                    )
                    checkpoint_manager.record_validation_failure(exhausted_subtasks, report)
                    # The second failure is not reusable evidence.  Passed
                    # questions were never removed; only the exhausted repair
                    # boundary is cleared before manual recovery takes over.
                    checkpoint_manager.invalidate_solution_coder_responses(exhausted_subtasks)
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content=(
                            "代码执行或数值可行性验证连续失败，已停止论文写作和自动回修；"
                            "请查看 execution_validation_report.json 并按恢复规程处理。"
                        ),
                        type="error",
                    ),
                )
                raise RuntimeError("代码执行/数值可行性门禁未通过，定向回修已停止")
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content="定向回修后的最终执行验证通过。",
                    type="success",
                ),
            )
        try:
            write_frozen_results_from_execution_validation(self.work_dir)
            checkpoint_manager.mark_results_frozen()
        except Exception as exc:
            raise RuntimeError("执行验证通过但冻结结果写入失败") from exc

        # 运行时一致性断言：Writer 分节写作依赖每条正式题指标的 subtask_id 做
        # 物理隔离。若正式题指标缺 subtask_id，隔离会退化为“无归属放行”，可能
        # 让本题看到其它子任务事实。此处在进入 Writer 前强制核验，发现缺失即
        # 停止，不依赖兼容放行继续生成论文。
        self._assert_formal_metrics_have_subtask_id()

        # 技术执行 PASS 只能证明代码证据完整，不能证明数学模型或物理结果合理。
        # 明确失败/非有限数值一律暂停；启用 require_model_review 的任务即使机器
        # 未命中也必须由 Codex/人工逐题复核。审批与结果表哈希绑定，改动结果后
        # 旧审批自动失效。
        quality_report = write_execution_quality_review(self.work_dir)
        checkpoint = checkpoint_manager._checkpoint
        requires_manual_review = bool(
            quality_report.get("status") == "NEEDS_REVIEW"
            or (checkpoint is not None and checkpoint.require_model_review)
        )
        review_id = str(quality_report.get("review_id", ""))
        if requires_manual_review and not checkpoint_manager.quality_review_is_approved(
            review_id
        ):
            checkpoint_manager.record_quality_review_pending(quality_report)
            failed_subtasks = quality_report.get("failed_subtasks") or []
            target_text = "、".join(map(str, failed_subtasks)) or "全部正式子题"
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content=(
                        "冻结结果等待 Codex/人工质量复核，论文写作尚未开始。"
                        f"重点复核：{target_text}；请查看 execution_quality_review.md。"
                    ),
                    type="warning",
                ),
            )
            return "waiting_quality_review"

        # 此处开始才允许 Writer 接触代码结果。即使旧检查点中有 Writer 文本，
        # 也必须重写，避免把冻结前生成的未验证数值带入本次导出。
        for key, coder_response in coder_responses.items():
            await self._check_cancelled()
            writer_prompt = flows.get_writer_prompt(
                key,
                coder_response.code_response or "",
                code_interpreter,
                config_template,
            )
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content=f"最终执行验证通过，论文手开始写{key}部分"),
            )
            writer_response = await writer_agent.run(
                writer_prompt,
                available_images=coder_response.created_images,
                sub_title=key,
            )
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content=f"论文手完成{key}部分"),
            )
            user_output.set_res(key, writer_response)
            checkpoint_manager.mark_phase_completed(
                key, coder_response.model_dump(), writer_response.model_dump()
            )
        return None

    async def _run_write_flows(
        self,
        flows: Flows,
        writer_agent: WriterAgent,
        user_output: UserOutput,
        checkpoint_manager: CheckpointManager,
        config_template: dict,
        ques_all: str,
        recovery_context: str = "",
    ) -> None:
        """执行 write_flows 循环（写作手独立撰写各章节），已完成的阶段直接跳过。"""
        write_flows = flows.get_write_flows(user_output, config_template, ques_all)
        for key, value in write_flows.items():
            await self._check_cancelled()

            phase = checkpoint_manager.get_phase(key)
            if phase is not None:
                logger.info(f"跳过已完成阶段: {key}")
                user_output.set_res(
                    key, WriterResponse.model_validate(phase.writer_response)
                )
                continue

            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content=f"论文手开始写{key}部分"),
            )

            writer_prompt = value
            if recovery_context:
                writer_prompt = (
                    "【受控恢复要求】仅使用当前已冻结的计算证据完成论文；"
                    "不要在论文中提及任何失败、重试或恢复过程。\n\n" + value
                )
            writer_response = await writer_agent.run(prompt=writer_prompt, sub_title=key)

            user_output.set_res(key, writer_response)
            checkpoint_manager.mark_phase_completed(
                key, None, writer_response.model_dump()
            )

    async def _validate_plan_with_one_remodel(
        self,
        problem_contract: ProblemContract,
        modeler_response: ModelerToCoder,
        remodel: Callable[[], Awaitable[ModelerToCoder]],
    ) -> ModelerToCoder:
        """用题面契约独立复核建模计划，冲突时定向重建模一次。

        这是 execute() 主流程与 resume() 续传路径共享的“计划级”防线：建模手内部
        自校验之外，再用契约在 Agent 之外独立卡一道，避免改写题面参数的方案一路
        放行到执行与冻结。首次冲突重建模一次，仍冲突则抛错干净中止，不进入自动循环。

        Args:
            problem_contract: 题面参数契约。
            modeler_response: 建模手首次返回的方案。
            remodel: 无参异步回调，返回一份全新的建模方案（调用方负责用干净的
                建模手实例重建，避免复用被污染的对话历史）。

        Returns:
            通过契约复核的建模方案。

        Raises:
            RuntimeError: 连续两次方案都与题面参数契约冲突。
        """
        expected_question_keys = {
            key
            for key in self.questions
            if key.startswith("ques") and key != "ques_count"
        }

        def _check(plan: ModelerToCoder) -> list[str]:
            result = validate_modeler_plan(
                problem_contract,
                plan,
                expected_question_keys=expected_question_keys,
                questions=self.questions,
            )
            return result.violations + result.missing_requirements

        conflicts = _check(modeler_response)
        if not conflicts:
            return modeler_response

        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(
                content="建模方案与题面参数契约冲突，正在重新建模：" + "；".join(conflicts),
                type="warning",
            ),
        )
        modeler_response = await remodel()
        conflicts = _check(modeler_response)
        if conflicts:
            raise RuntimeError(
                "建模方案复核连续两次与题面参数契约冲突，已停止求解：" + "；".join(conflicts)
            )
        return modeler_response

    def _write_modeler_plan(self, modeler_response: ModelerToCoder) -> None:
        """将建模手方案保存为可见产物，便于用户检查和续传审计。"""
        plan_json_path = os.path.join(self.work_dir, "modeler_plan.json")
        plan_md_path = os.path.join(self.work_dir, "modeler_plan.md")
        questions_solution = modeler_response.questions_solution

        with open(plan_json_path, "w", encoding="utf-8") as f:
            json.dump(
                modeler_response.model_dump(),
                f,
                ensure_ascii=False,
                indent=2,
            )

        lines = ["# 建模手方案", ""]
        for key, solution in questions_solution.items():
            lines.extend([f"## {key}", "", str(solution).strip(), ""])

        with open(plan_md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines).rstrip() + "\n")

    def _write_modeling_decision(
        self,
        problem: Problem,
        modeler_response: ModelerToCoder,
    ) -> None:
        """写出人工建模确认门禁所需的审计文件。"""
        decision_json_path = os.path.join(self.work_dir, "modeling_decision.json")
        decision_md_path = os.path.join(self.work_dir, "modeling_decision.md")
        review_history: list[dict] = []
        prior_gate_enabled = False
        if os.path.exists(decision_json_path):
            try:
                with open(decision_json_path, encoding="utf-8") as decision_file:
                    prior_decision = json.load(decision_file)
                prior_history = prior_decision.get("review_history", [])
                if isinstance(prior_history, list):
                    review_history = prior_history
                prior_gate_enabled = prior_decision.get("gate_enabled") is True
            except (OSError, json.JSONDecodeError):
                logger.warning("读取已有建模审查历史失败，将重建确认文件")

        modeler_payload = modeler_response.model_dump()
        modeler_plan_sha256 = hashlib.sha256(
            json.dumps(
                modeler_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        payload = {
            "task_id": self.task_id,
            "status": "waiting_review",
            "gate_enabled": (
                settings.HUMAN_MODEL_GATE_ENABLED
                or problem.require_model_review
                or prior_gate_enabled
            ),
            "created_at": datetime.datetime.now().isoformat(),
            "comp_template": problem.comp_template.value,
            "format_output": problem.format_output.value,
            "export_profile": problem.export_profile.value,
            "questions": self.questions,
            "ques_count": self.ques_count,
            "modeler_response": modeler_payload,
            "modeler_plan_sha256": modeler_plan_sha256,
            "review": {
                "approved": False,
                "approved_at": None,
                "comment": "",
            },
            "review_history": review_history,
        }
        with open(decision_json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        lines = [
            "# 建模方案人工确认",
            "",
            f"- 任务 ID：`{self.task_id}`",
            "- 状态：`waiting_review`",
            f"- 导出排版：`{problem.export_profile.value}`",
            "",
            "## 拆分问题",
            "",
        ]
        for key, question in self.questions.items():
            lines.append(f"- `{key}`：{question}")
        lines.extend(["", "## 建模方案", ""])
        for key, solution in modeler_response.questions_solution.items():
            lines.extend([f"### {key}", "", str(solution).strip(), ""])
        lines.extend(
            [
                "## 确认方式",
                "",
                f"通过 `POST /modeling/{self.task_id}/approve-modeling` 确认后继续代码求解与写作流程。",
                "",
            ]
        )
        with open(decision_md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines).rstrip() + "\n")

    def accept_codex_modeling(self, task_id: str, modeler_response: ModelerToCoder) -> None:
        """Accept a reviewer-authored plan through the same contract gate.

        This is a bounded recovery path for a task whose Modeler exhausted its
        schema/contract retries.  It does not grant a privileged bypass: the
        submitted plan is parsed as the normal schema, validated against the
        immutable problem contract, persisted as a checkpoint, and then paused
        for the normal explicit approval before Coder may run.
        """
        self.task_id = task_id
        self.work_dir = get_work_dir(task_id)
        checkpoint_manager = CheckpointManager(self.work_dir)
        checkpoint = checkpoint_manager.load()
        if checkpoint is None:
            raise FileNotFoundError(f"未找到可接管的检查点: {task_id}")
        if modeler_response.model_plan is None:
            raise ValueError("Codex 接管建模必须提交结构化 model_plan。")
        self.questions = checkpoint.questions
        self.ques_count = checkpoint.ques_count
        problem_contract = build_problem_contract(checkpoint.ques_all)
        result = validate_modeler_plan(
            problem_contract,
            modeler_response,
            expected_question_keys={
                key for key in self.questions if key.startswith("ques") and key != "ques_count"
            },
            questions=self.questions,
        )
        issues = result.violations + result.missing_requirements
        if issues:
            raise ValueError("Codex 接管方案未通过题面契约：" + "；".join(issues))
        response = modeler_response.model_copy(
            update={"questions_solution": modeler_response.model_plan.to_questions_solution()}
        )
        checkpoint_manager.replace_modeler_response(response.model_dump())
        self._write_modeler_plan(response)
        problem = Problem(
            task_id=task_id,
            ques_all=checkpoint.ques_all,
            comp_template=CompTemplate(checkpoint.comp_template),
            format_output=FormatOutPut(checkpoint.format_output),
            export_profile=ExportProfile(checkpoint.export_profile),
            require_model_review=checkpoint.require_model_review,
        )
        self._write_modeling_decision(problem, response)

    async def revise_modeling(self, task_id: str, review_comment: str) -> str:
        """Rebuild a paused ModelPlan once from an explicit reviewer comment.

        This path never resumes Coder directly.  The new response is subject to
        the same schema and problem-contract checks as task creation, replaces
        the checkpointed plan atomically, and pauses at the review gate again.
        """
        self.task_id = task_id
        self.work_dir = get_work_dir(task_id)
        checkpoint_manager = CheckpointManager(self.work_dir)
        checkpoint = checkpoint_manager.load()
        if checkpoint is None:
            raise FileNotFoundError(f"未找到可修订的检查点: {task_id}")

        self.questions = checkpoint.questions
        self.ques_count = checkpoint.ques_count
        problem_contract = build_problem_contract(checkpoint.ques_all)
        with open(
            os.path.join(self.work_dir, "problem_contract.json"),
            "w",
            encoding="utf-8",
        ) as contract_file:
            json.dump(problem_contract.model_dump(), contract_file, ensure_ascii=False, indent=2)

        llm_factory = LLMFactory(self.task_id)
        _coordinator_llm, modeler_llm, _coder_llm, _writer_llm = (
            llm_factory.get_all_llms()
        )
        user_input_provider = lambda target="all": user_input_queue.pop_for(  # noqa: E731
            self.task_id, target
        )
        coordinator_context = CoordinatorToModeler(
            questions=self.questions,
            ques_count=self.ques_count,
            problem_contract=problem_contract,
        )
        revision_context = (
            "这是审查者退回后的唯一一次受控建模修订。必须逐项回应以下审查意见；"
            "不得把无可靠题面、附件、可核验数据统计、文献或标准依据的经验数值写为硬阈值。"
            "没有依据时改为结论中立、可复算的完成或记录指标。\n"
            "审查意见：" + review_comment[:3000]
        )

        async def _run_modeler() -> ModelerToCoder:
            modeler_agent = ModelerAgent(
                self.task_id,
                modeler_llm,
                context_window=settings.MODELER_CONTEXT_WINDOW,
                cancel_event=self.cancel_event,
                user_input_provider=user_input_provider,
            )
            return await modeler_agent.run(
                coordinator_context, recovery_context=revision_context
            )

        modeler_response = await _run_modeler()
        modeler_response = await self._validate_plan_with_one_remodel(
            problem_contract, modeler_response, _run_modeler
        )
        checkpoint_manager.replace_modeler_response(modeler_response.model_dump())
        self._write_modeler_plan(modeler_response)

        problem = Problem(
            task_id=self.task_id,
            ques_all=checkpoint.ques_all,
            comp_template=CompTemplate(checkpoint.comp_template),
            format_output=FormatOutPut(checkpoint.format_output),
            export_profile=ExportProfile(checkpoint.export_profile),
            require_model_review=checkpoint.require_model_review,
        )
        self._write_modeling_decision(problem, modeler_response)
        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="建模方案已按审查意见修订，等待再次确认", type="warning"),
        )
        return "waiting_review"

    def _assert_formal_metrics_have_subtask_id(self) -> None:
        """冻结后、Writer 前：确保正式题指标都能被明确归属到某个 quesN。

        Writer 分节隔离靠 metric.subtask_id 物理过滤。缺 subtask_id 会退化为
        “无归属放行”，可能让本题 prompt 看到其它子任务事实。为不让论文在这种
        情况下继续生成，此处发现缺归属即抛错停在 Writer 之前。
        """
        validation = validate_result_freeze(self.work_dir)
        if not validation.get("active") or not validation.get("passed"):
            return
        formal_re = re.compile(r"^ques[0-9]+$", re.IGNORECASE)
        unattributed: list[str] = []
        attributed: set[str] = set()
        for metric in validation.get("metrics", []):
            subtask_id = str(metric.get("subtask_id", "")).strip()
            if formal_re.match(subtask_id):
                attributed.add(subtask_id.lower())
                continue
            # 无归属或归属值非 quesN 形态：记录该指标以便定位
            unattributed.append(
                str(metric.get("id") or metric.get("label") or "<未命名指标>")
            )
        logger.info(
            "冻结指标归属核验: attributed_subtasks=%s, unattributed_metric_count=%d",
            sorted(attributed),
            len(unattributed),
        )
        if unattributed:
            raise RuntimeError(
                "冻结结果存在无 subtask_id 归属的正式题指标，已在进入 Writer 前停止，"
                "避免子任务隔离退化为无归属放行。缺归属指标："
                f"{', '.join(unattributed[:20])}"
            )

    @staticmethod
    def _preflight_failure_summary(report: dict) -> str:
        """Make a bounded, actionable Writer brief from hard preflight checks."""
        lines: list[str] = []
        checks = report.get("checks", {}) if isinstance(report, dict) else {}
        if not isinstance(checks, dict):
            return "- paper_preflight_report.json 格式无效。"
        for check_id, check in checks.items():
            if not isinstance(check, dict) or check.get("passed") is True:
                continue
            if check.get("severity") != "fail":
                continue
            details = {
                key: value
                for key, value in check.items()
                if key not in {"passed", "severity"}
            }
            rendered = json.dumps(details, ensure_ascii=False, separators=(",", ":"))
            lines.append(f"- {check_id}: {rendered[:2400]}")
        return "\n".join(lines[:12]) or "- 未定位到可修复的硬门禁项。"

    @staticmethod
    def _preflight_repairable_sections(report: dict, available_sections: set[str]) -> list[str]:
        """Map result-consistency conflicts to only the Writer sections at fault.

        The checker reports section headings rather than Agent keys.  We only
        auto-rewrite a section when that mapping is unambiguous; broad layout,
        source-code and reference failures remain hard stops for human repair.
        """
        checks = report.get("checks", {}) if isinstance(report, dict) else {}
        if not isinstance(checks, dict):
            return []
        repairable = {
            "result_consistency",
            "figure_result_consistency",
            "algorithm_evidence",
            "infeasible_optimality",
            "claim_trace",
            "problem_alignment",
        }
        failed = {
            check_id: check
            for check_id, check in checks.items()
            if isinstance(check, dict)
            and check.get("passed") is False
            and check.get("severity") == "fail"
        }
        if not failed or not set(failed).issubset(repairable):
            return []

        sections: set[str] = set()
        consistency = failed.get("result_consistency", {})
        conflicts = []
        if isinstance(consistency, dict):
            conflicts = list(consistency.get("conflicts", [])) + list(
                consistency.get("abstract_conflicts", [])
            )
        figure_consistency = failed.get("figure_result_consistency", {})
        if isinstance(figure_consistency, dict):
            conflicts.extend(figure_consistency.get("conflicts", []))
        for conflict in conflicts:
            if not isinstance(conflict, dict):
                continue
            location = str(conflict.get("location", ""))
            if location == "abstract" and "firstPage" in available_sections:
                sections.add("firstPage")
            heading = str(conflict.get("paper_section", ""))
            match = re.search(r"问题\s*([0-9一二三四五六七八九十]+)", heading)
            if match:
                raw_index = match.group(1)
                chinese_index = {
                    "一": "1",
                    "二": "2",
                    "三": "3",
                    "四": "4",
                    "五": "5",
                    "六": "6",
                    "七": "7",
                    "八": "8",
                    "九": "9",
                    "十": "10",
                }.get(raw_index, raw_index)
                candidate = f"ques{chinese_index}"
                if candidate in available_sections:
                    sections.add(candidate)
        # problem_alignment 报告的是 "5.N ..." 形式的章节错位（正文与题面问题
        # 编号对不上）。逐条解析节号 N → ques{N}，让写作手按题号重写对应章节；
        # 无节号前缀的整体性问题（如把双角度误述为两片样品）无法安全定位到单节，
        # 保守起见把已声明的三题一并纳入回修。
        alignment = failed.get("problem_alignment", {})
        if isinstance(alignment, dict):
            alignment_issues = [
                str(item) for item in alignment.get("issues", [])
            ]
            for issue in alignment_issues:
                numbered = re.match(r"\s*5\.([0-9])", issue)
                if numbered:
                    candidate = f"ques{numbered.group(1)}"
                    if candidate in available_sections:
                        sections.add(candidate)
                    continue
                # 无节号前缀：整体性错位，纳入全部已声明题目章节。
                for key in sorted(available_sections):
                    if re.fullmatch(r"ques[0-9]+", key):
                        sections.add(key)
        # A claim-trace or method-evidence failure is not safely assignable by
        # heading.  Keep it human-visible instead of paying for a blind rewrite.
        if not sections:
            return []
        return sorted(sections, key=lambda key: (key != "firstPage", key))

    async def _repair_writer_preflight_once(
        self,
        user_output: UserOutput,
        writer_agent: WriterAgent,
        checkpoint_manager: CheckpointManager,
        report: dict,
    ) -> dict | None:
        """Rewrite only report-identified prose once, then let caller recheck."""
        sections = self._preflight_repairable_sections(report, set(user_output.get_res()))
        if not sections:
            return None
        attempt = checkpoint_manager.record_paper_preflight_failure(report)
        if attempt != 1:
            return None
        failure_summary = self._preflight_failure_summary(report)
        frozen_facts = build_result_fact_summary(self.work_dir)
        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(
                content="论文预检发现冻结结果与正文不一致，开始一次定向正文回修：" + "、".join(sections),
                type="warning",
            ),
        )
        for key in sections:
            previous = user_output.get_res()[key]["response_content"]
            prompt = (
                "这是论文最终技术预检后的唯一一次定向回修。不要编程、不要修改任何结果文件、"
                "不要改写其他章节，也不要编造未冻结的数值。请只返回下列章节的完整替换正文，"
                "保留原章节标题和必要的公式/图表引用。所有计算数值必须逐项服从冻结结果；"
                "若原句把题设、旧解和新解混在一起，应删去错误叙述并改为冻结事实支持的表述。\n\n"
                f"【待替换章节】{key}\n{previous}\n\n"
                f"{frozen_facts}\n\n"
                "【预检失败证据】\n"
                f"{failure_summary}\n"
            )
            response = await writer_agent.run(prompt, sub_title=f"{key}_preflight_repair")
            user_output.set_res(key, response)
            phase = checkpoint_manager.get_phase(key)
            checkpoint_manager.mark_phase_completed(
                key,
                phase.coder_response if phase else None,
                response.model_dump(),
            )
        user_output.save_result()
        return report

    async def _export_results(
        self,
        user_output: UserOutput,
        export_profile: ExportProfile | str | None = DEFAULT_MODELING_EXPORT_PROFILE,
        writer_agent: WriterAgent | None = None,
        checkpoint_manager: CheckpointManager | None = None,
    ) -> None:
        """保存结果并导出 PDF/LaTeX/候选清单（execute 与 resume 共享）。"""
        logger.info(user_output.get_res())

        user_output.save_result()
        profile_key = normalize_export_profile(export_profile).value
        try:
            template_override = load_export_template_override(
                self.work_dir, profile_key
            )
            editorial_policy = get_editorial_policy_override(
                self.work_dir, profile_key
            )
            pdf_visual_constraints = get_pdf_visual_constraints(
                self.work_dir, profile_key
            )
        except TemplateOverrideError as exc:
            raise RuntimeError(f"任务级模板覆盖无效，已停止导出: {exc}") from exc
        ai_usage_result = ensure_ai_usage_details(
            self.work_dir,
            export_profile=profile_key,
        )
        if ai_usage_result.get("enabled") and not ai_usage_result.get("success"):
            logger.warning("AI工具使用详情 PDF 生成失败，cumcm2026 预检将拒绝导出")
        try:
            declared_problem_count = len(
                [
                    key
                    for key in self.questions
                    if key.startswith("ques") and key != "ques_count"
                ]
            )
            preflight_report = prepare_paper_markdown(
                self.work_dir,
                "res.md",
                export_profile=profile_key,
                declared_problem_count=declared_problem_count or None,
                editorial_policy=editorial_policy,
                template_override_audit=template_override["audit"],
            )
            if (
                preflight_report.get("status") == "FAIL"
                and writer_agent is not None
                and checkpoint_manager is not None
            ):
                repaired = await self._repair_writer_preflight_once(
                    user_output, writer_agent, checkpoint_manager, preflight_report
                )
                if repaired is not None:
                    preflight_report = prepare_paper_markdown(
                        self.work_dir,
                        "res.md",
                        export_profile=profile_key,
                        declared_problem_count=declared_problem_count or None,
                        editorial_policy=editorial_policy,
                        template_override_audit=template_override["audit"],
                    )
            if preflight_report.get("status") == "PASS" and checkpoint_manager is not None:
                checkpoint_manager.mark_paper_preflight_passed()
            if preflight_report.get("status") == "PASS":
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content="论文排版预检通过，已规范参考文献并附加核心代码"),
                )
            else:
                logger.warning(
                    "论文排版预检存在风险: "
                    f"status={preflight_report.get('status', 'unknown')}"
                )
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content=(
                            "论文排版预检完成但存在风险 "
                            f"({preflight_report.get('status')})，请查看 paper_preflight_report.json"
                        ),
                        type="warning",
                    ),
                )
                if preflight_report.get("status") == "FAIL":
                    raise RuntimeError(
                        "论文预检硬门禁未通过；已停止生成候选 PDF，请查看 paper_preflight_report.json。"
                    )
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"论文排版后处理失败: {type(e).__name__}")
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content=f"论文排版后处理失败: {e}，将继续导出原始 Markdown",
                    type="warning",
                ),
            )

        ################################################ generate PDF
        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="正在生成 PDF 论文..."),
        )
        md_path = os.path.join(self.work_dir, "res.md")
        pdf_path = os.path.join(self.work_dir, "res.pdf")
        pdf_result = export_markdown_to_pdf(
            md_path, pdf_path, self.work_dir, export_profile=export_profile
        )

        if pdf_result["success"]:
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="PDF 论文生成完成"),
            )
        elif pdf_result["enabled"]:
            # pandoc/xelatex 都存在，但转换本身失败
            logger.error(
                f"PDF 生成失败: {pdf_result['reason']}, stderr={pdf_result['stderr']}"
            )
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content=f"PDF 论文生成失败: {pdf_result['reason']}，其余结果（Markdown/Word）不受影响",
                    type="error",
                ),
            )
        else:
            # 环境缺失（文件不存在、pandoc/xelatex 未安装），主动跳过
            logger.warning("PDF 生成跳过")
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content=f"已跳过 PDF 生成: {pdf_result['reason']}，其余结果（Markdown/Word）不受影响",
                    type="warning",
                ),
            )

        # Always refresh the visual report. On export failure the exporter has
        # already removed any old PDF, so this writes a fresh SKIPPED/FAIL
        # report instead of leaving a previous PASS report reusable.
        pdf_visual_result = check_pdf_visual(
            pdf_path,
            self.work_dir,
            quality_policy=_pdf_editorial_quality_policy(export_profile),
            export_profile=profile_key,
            template_override_audit=template_override["audit"],
            **pdf_visual_constraints,
        )
        if pdf_visual_result.get("success"):
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="PDF 后验视觉检查通过"),
            )
        else:
            logger.warning(
                "PDF 后验视觉检查存在风险: "
                f"status={pdf_visual_result.get('status', 'unknown')}"
            )
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content="PDF 后验视觉检查存在风险，请查看 pdf_visual_check.json",
                    type="warning",
                ),
            )

        export_status_path = os.path.join(self.work_dir, "export_status.json")
        try:
            with open(export_status_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "export_profile": normalize_export_profile(
                            export_profile
                        ).value,
                        "template_override": template_override["audit"],
                        "pdf": pdf_result,
                        "pdf_visual_check": pdf_visual_result,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.error(f"写入 export_status.json 失败: {type(e).__name__}")

        ################################################ generate LaTeX sidecar project
        try:
            tex_result = export_markdown_to_latex_project(
                md_path, self.work_dir, export_profile=export_profile
            )
            if tex_result["success"]:
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content="LaTeX 项目（latex_project/）导出完成，可供进一步精修"
                    ),
                )
            elif tex_result["enabled"]:
                logger.error("LaTeX sidecar 导出失败")
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content=f"LaTeX 项目导出失败: {tex_result['reason']}，其余结果不受影响",
                        type="warning",
                    ),
                )
            else:
                logger.warning("LaTeX sidecar 导出跳过")
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content=f"已跳过 LaTeX 项目导出: {tex_result['reason']}，其余结果不受影响",
                        type="warning",
                    ),
                )
        except Exception as e:
            logger.error(f"LaTeX sidecar 导出异常: {type(e).__name__}")
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content=f"LaTeX 项目导出异常: {e}，其余结果不受影响", type="warning"
                ),
            )

        ################################################ generate candidate manifest before audit
        try:
            write_candidate_manifest(self.work_dir, self.task_id)
        except Exception as e:
            logger.error(f"candidate_manifest.json 生成失败: {type(e).__name__}")
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content=f"candidate_manifest.json 生成失败: {e}", type="error"
                ),
            )

        ################################################ generate submission audit report
        try:
            audit_report = write_submission_audit_report(self.work_dir)
            if audit_report.get("status") == "PASS":
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content="提交产物自动审核通过"),
                )
            else:
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content="提交产物自动审核存在风险，请查看 submission_audit_report.json",
                        type="warning",
                    ),
                )
        except Exception as e:
            logger.error(f"submission_audit_report 生成失败: {type(e).__name__}")
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content=f"submission_audit_report 生成失败: {e}", type="warning"
                ),
            )

    async def _resume_paper_repair_candidate_export(
        self,
        checkpoint_manager: CheckpointManager,
        export_profile: ExportProfile,
    ) -> None:
        """Export a staged Codex paper repair without waking any provider.

        The ordinary ``paper_repair_pending_export``, independent
        ``editorial_repair_pending_export``, and participant-authorized
        ``format_compliance_pending_export`` states can only be written by the
        bounded local paper-candidate tool after it validated the whole
        manuscript in an isolated copy of the frozen task.  The separate
        ``presentation_reflow_pending_export`` state is a one-time,
        no-prose-change deterministic layout refresh.  Rehydrate the exact
        persisted Writer responses and run the ordinary preflight/export
        chain; do not replay Coder/Writer flows or turn the repair into an
        unreviewed model call.
        """
        checkpoint = checkpoint_manager._checkpoint
        if checkpoint is None:
            raise RuntimeError("论文候选续传缺少检查点")
        user_output = UserOutput(
            work_dir=self.work_dir,
            ques_count=self.ques_count,
            export_profile=checkpoint.export_profile,
        )
        expected = set(user_output.seq)
        actual = set(checkpoint.completed_phases)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            details: list[str] = []
            if missing:
                details.append("缺少=" + ", ".join(missing))
            if extra:
                details.append("多出=" + ", ".join(extra))
            raise RuntimeError("论文候选续传的 Writer 阶段不完整：" + "；".join(details))
        for key in user_output.seq:
            phase = checkpoint.completed_phases[key]
            if phase.writer_response is None:
                raise RuntimeError(f"论文候选续传缺少 Writer 正文: {key}")
            user_output.set_res(key, WriterResponse.model_validate(phase.writer_response))

        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(
                content="已载入通过隔离预检的论文候选，跳过 MiMo 写作并进入正式导出",
                type="warning",
            ),
        )
        await self._export_results(
            user_output,
            export_profile,
            writer_agent=None,
            checkpoint_manager=checkpoint_manager,
        )

    async def execute(
        self, problem: Problem, recovery_context: str = ""
    ):  # type: ignore[reportIncompatibleMethodOverride]
        """执行数学建模工作流。

        Args:
            problem: 包含题目信息、模板配置等的 Problem 对象。
        """
        self.task_id = problem.task_id
        self.work_dir = create_work_dir(self.task_id)
        write_task_request_snapshot(
            self.work_dir,
            {
                "task_id": problem.task_id,
                "ques_all": problem.ques_all,
                "comp_template": problem.comp_template.value,
                "format_output": problem.format_output.value,
                "export_profile": problem.export_profile.value,
                "require_model_review": problem.require_model_review,
            },
        )
        problem_contract = build_problem_contract(problem.ques_all)
        with open(
            os.path.join(self.work_dir, "problem_contract.json"),
            "w",
            encoding="utf-8",
        ) as contract_file:
            json.dump(problem_contract.model_dump(), contract_file, ensure_ascii=False, indent=2)

        llm_factory = LLMFactory(self.task_id)
        coordinator_llm, modeler_llm, coder_llm, writer_llm = llm_factory.get_all_llms()

        # 角色定向的外部引导：每个 Agent 只取得给自己的建议，避免竞争消费。
        user_input_provider = lambda target="all": user_input_queue.pop_for(  # noqa: E731
            self.task_id, target
        )

        coordinator_agent = CoordinatorAgent(
            self.task_id,
            coordinator_llm,
            context_window=settings.COORDINATOR_CONTEXT_WINDOW,
            cancel_event=self.cancel_event,
            user_input_provider=user_input_provider,
        )

        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="识别用户意图和拆解问题ing..."),
        )

        await self._check_cancelled()

        try:
            coordinator_input = problem.ques_all
            if recovery_context:
                coordinator_input += (
                    "\n\n【受控恢复上下文】\n"
                    + recovery_context
                    + "\n请重新拆解并校验题意；不要将恢复过程写入最终论文。"
                )
            coordinator_response = await coordinator_agent.run(coordinator_input)
            coordinator_response.problem_contract = problem_contract
            self.questions = coordinator_response.questions
            self.ques_count = coordinator_response.ques_count
        except Exception as e:
            #  非数学建模问题
            logger.error(f"CoordinatorAgent 执行失败: {type(e).__name__}")
            raise e

        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="识别用户意图和拆解问题完成,任务转交给建模手"),
        )

        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="建模手开始建模ing..."),
        )

        await self._check_cancelled()

        # Keep the coordinator result recoverable even if Modeler exhausts its
        # retries.  A Codex reviewer can then submit a separately validated
        # plan instead of recreating the task or bypassing downstream gates.
        checkpoint_manager = CheckpointManager(self.work_dir)
        checkpoint_manager.save(
            TaskCheckpoint(
                task_id=self.task_id,
                ques_all=problem.ques_all,
                comp_template=problem.comp_template.value,
                format_output=problem.format_output.value,
                export_profile=problem.export_profile.value,
                require_model_review=problem.require_model_review,
                questions=self.questions,
                ques_count=self.ques_count,
                modeler_response={},
                updated_at=datetime.datetime.now().isoformat(),
            )
        )

        modeler_agent = ModelerAgent(
            self.task_id,
            modeler_llm,
            context_window=settings.MODELER_CONTEXT_WINDOW,
            cancel_event=self.cancel_event,
            user_input_provider=user_input_provider,
        )

        modeler_response = await modeler_agent.run(
            coordinator_response, recovery_context=recovery_context
        )

        # 计划级独立复核：建模手内部自校验之外，主流程再用题面契约独立卡一道。
        # resume() 续传路径已有这道独立防线（见 validate_modeler_plan 调用），而
        # execute() 从头跑此前只依赖建模手“自己校验自己”，一旦内部校验存在盲区，
        # 改写题面参数（如把实测入射角替换为垂直入射）会一路放行到执行与冻结。
        async def _remodel() -> ModelerToCoder:
            # 从头跑此时尚未执行任何求解代码，无未验收上下文需要归档；
            # 用全新建模手实例重建一次，避免复用被污染的对话历史。
            fresh_modeler = ModelerAgent(
                self.task_id,
                modeler_llm,
                context_window=settings.MODELER_CONTEXT_WINDOW,
                cancel_event=self.cancel_event,
                user_input_provider=user_input_provider,
            )
            return await fresh_modeler.run(
                coordinator_response, recovery_context=recovery_context
            )

        modeler_response = await self._validate_plan_with_one_remodel(
            problem_contract, modeler_response, _remodel
        )

        self._write_modeler_plan(modeler_response)
        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="建模手建模完成，已生成 modeler_plan.md"),
        )

        # 断点续传：协调者和建模手完成后立刻落盘一次检查点，
        # 后续每个 solution/write 阶段完成后再增量更新
        checkpoint_manager = CheckpointManager(self.work_dir)
        checkpoint_manager.save(
            TaskCheckpoint(
                task_id=self.task_id,
                ques_all=problem.ques_all,
                comp_template=problem.comp_template.value,
                format_output=problem.format_output.value,
                export_profile=problem.export_profile.value,
                require_model_review=problem.require_model_review,
                questions=self.questions,
                ques_count=self.ques_count,
                modeler_response=modeler_response.model_dump(),
                updated_at=datetime.datetime.now().isoformat(),
            )
        )
        self._write_modeling_decision(problem, modeler_response)
        if settings.HUMAN_MODEL_GATE_ENABLED or problem.require_model_review:
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content=(
                        "建模方案已生成，任务等待人工确认。"
                        "请查看 modeling_decision.md，确认后继续代码求解。"
                    ),
                    type="warning",
                ),
            )
            return "waiting_review"

        user_output = UserOutput(
            work_dir=self.work_dir,
            ques_count=self.ques_count,
            export_profile=problem.export_profile.value,
        )

        (
            notebook_serializer,
            code_interpreter,
            coder_agent,
            writer_agent,
        ) = await self._build_agents(
            coder_llm,
            writer_llm,
            problem.comp_template,
            problem.format_output,
            user_input_provider,
            problem.ques_all,
            checkpoint_manager,
        )

        flows = Flows(self.questions, problem_contract)
        config_template = get_config_template(problem.comp_template)

        ################################################ solution steps
        async with self._managed_interpreter(code_interpreter):
            solution_result = await self._run_solution_flows(
                flows,
                modeler_response,
                coder_agent,
                writer_agent,
                code_interpreter,
                user_output,
                checkpoint_manager,
                config_template,
                recovery_context,
            )
            if solution_result == "waiting_quality_review":
                return solution_result

        ################################################ write steps
        await self._run_write_flows(
            flows,
            writer_agent,
            user_output,
            checkpoint_manager,
            config_template,
            problem.ques_all,
            recovery_context,
        )

        await self._export_results(
            user_output,
            problem.export_profile,
            writer_agent=writer_agent,
            checkpoint_manager=checkpoint_manager,
        )

    async def resume(self, task_id: str, recovery_context: str = "") -> str | None:
        """从检查点恢复并继续执行数学建模工作流。

        跳过协调者/建模手，跳过 checkpoint 中已完成的阶段，并通过重放
        notebook.ipynb 中已成功执行的代码单元格重建 Jupyter 内核变量状态。

        Args:
            task_id: 待续传的任务 ID。

        Raises:
            FileNotFoundError: 任务目录或检查点不存在时抛出。
        """
        self.task_id = task_id
        self.work_dir = get_work_dir(task_id)

        checkpoint_manager = CheckpointManager(self.work_dir)
        checkpoint = checkpoint_manager.load()
        if checkpoint is None:
            raise FileNotFoundError(f"未找到可续传的检查点: {task_id}")

        self.questions = checkpoint.questions
        self.ques_count = checkpoint.ques_count
        problem_contract = build_problem_contract(checkpoint.ques_all)
        with open(
            os.path.join(self.work_dir, "problem_contract.json"),
            "w",
            encoding="utf-8",
        ) as contract_file:
            json.dump(problem_contract.model_dump(), contract_file, ensure_ascii=False, indent=2)
        comp_template = CompTemplate(checkpoint.comp_template)
        format_output = FormatOutPut(checkpoint.format_output)
        export_profile = ExportProfile(checkpoint.export_profile)
        modeler_response = ModelerToCoder.model_validate(checkpoint.modeler_response)

        if checkpoint.workflow_state in {
            "paper_repair_pending_export",
            "editorial_repair_pending_export",
            "presentation_reflow_pending_export",
            "format_compliance_pending_export",
        }:
            await self._resume_paper_repair_candidate_export(
                checkpoint_manager, export_profile
            )
            return None

        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="正在从检查点续传任务，跳过已完成阶段..."),
        )

        llm_factory = LLMFactory(self.task_id)
        # 续传时不重新调用协调者/建模手，只需要代码手和写作手的 LLM
        _coordinator_llm, modeler_llm, coder_llm, writer_llm = (
            llm_factory.get_all_llms()
        )

        user_input_provider = lambda target="all": user_input_queue.pop_for(  # noqa: E731
            self.task_id, target
        )

        original_modeler_response = modeler_response

        async def _remodel() -> ModelerToCoder:
            # 历史方案已经违反当前契约，其执行上下文不得再被重放。先归档，
            # 再用干净建模手重建；新方案仍须由共享 helper 做第二次独立复核。
            self._archive_unverified_execution_context()
            modeler_agent = ModelerAgent(
                self.task_id,
                modeler_llm,
                context_window=settings.MODELER_CONTEXT_WINDOW,
                cancel_event=self.cancel_event,
                user_input_provider=user_input_provider,
            )
            return await modeler_agent.run(
                CoordinatorToModeler(
                    questions=self.questions,
                    ques_count=self.ques_count,
                    problem_contract=problem_contract,
                ),
                recovery_context=recovery_context,
            )

        modeler_response = await self._validate_plan_with_one_remodel(
            problem_contract, modeler_response, _remodel
        )
        if modeler_response is not original_modeler_response:
            checkpoint_manager.replace_modeler_response(modeler_response.model_dump())
            checkpoint = checkpoint_manager.load() or checkpoint
            self._write_modeler_plan(modeler_response)
            problem = Problem(
                task_id=self.task_id,
                ques_all=checkpoint.ques_all,
                comp_template=comp_template,
                format_output=format_output,
                export_profile=export_profile,
                require_model_review=checkpoint.require_model_review,
            )
            decision_path = os.path.join(self.work_dir, "modeling_decision.json")
            prior_gate_enabled = False
            try:
                with open(decision_path, encoding="utf-8") as decision_file:
                    prior_gate_enabled = (
                        json.load(decision_file).get("gate_enabled") is True
                    )
            except (OSError, json.JSONDecodeError):
                pass
            if (
                settings.HUMAN_MODEL_GATE_ENABLED
                or checkpoint.require_model_review
                or prior_gate_enabled
            ):
                # A replacement plan invalidates the prior approval.  Pause
                # before interpreter startup so no Coder execution can use a
                # plan the reviewer never saw.
                self._write_modeling_decision(problem, modeler_response)
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content="续传时重建了建模方案，等待重新人工确认后才会执行代码。",
                        type="warning",
                    ),
                )
                return "waiting_review"
        else:
            self._write_modeler_plan(modeler_response)

        user_output = UserOutput(
            work_dir=self.work_dir,
            ques_count=self.ques_count,
            export_profile=checkpoint.export_profile,
        )

        (
            notebook_serializer,
            code_interpreter,
            coder_agent,
            writer_agent,
        ) = await self._build_agents(
            coder_llm,
            writer_llm,
            comp_template,
            format_output,
            user_input_provider,
            checkpoint.ques_all,
            checkpoint_manager,
        )

        flows = Flows(self.questions, problem_contract)
        config_template = get_config_template(comp_template)
        quality_repair = checkpoint.workflow_state == "quality_repair" or bool(
            checkpoint.workflow_state == "repairing"
            and checkpoint_manager.quality_repair_source_is_prepared()
        )

        async with self._managed_interpreter(code_interpreter):
            if quality_repair:
                # 质量复核明确退回时，旧 notebook 中的成功探索也可能已经
                # 被判定为过时/错误。先由 Coder 的显式返修准备动作隔离旧源，
                # 再从新内核开始；不能把旧变量快照或旧单元重放为新修正前置。
                coder_agent.prepare_quality_repair_source(checkpoint_manager)
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content="质量复核定向返修已隔离旧 notebook，使用新内核重建源码链",
                        type="warning",
                    ),
                )
            else:
                # 重建 Jupyter 内核变量状态
                await self._replay_notebook(code_interpreter, checkpoint_manager)

            ################################################ solution steps
            solution_result = await self._run_solution_flows(
                flows,
                modeler_response,
                coder_agent,
                writer_agent,
                code_interpreter,
                user_output,
                checkpoint_manager,
                config_template,
                recovery_context,
                quality_repair=quality_repair,
            )
            if solution_result == "waiting_quality_review":
                return solution_result

        ################################################ write steps
        await self._run_write_flows(
            flows,
            writer_agent,
            user_output,
            checkpoint_manager,
            config_template,
            checkpoint.ques_all,
            recovery_context,
        )

        await self._export_results(
            user_output,
            export_profile,
            writer_agent=writer_agent,
            checkpoint_manager=checkpoint_manager,
        )
        return None
