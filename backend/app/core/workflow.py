"""工作流模块，编排多 Agent 协作完成数学建模任务。"""

import asyncio
import datetime
import json
import os
import nbformat
from app.core.agents import WriterAgent, CoderAgent, CoordinatorAgent, ModelerAgent
from app.core.checkpoint import CheckpointManager, TaskCheckpoint
from app.schemas.A2A import ModelerToCoder, WriterResponse
from app.schemas.enums import CompTemplate, ExportProfile, FormatOutPut
from app.schemas.request import DEFAULT_MODELING_EXPORT_PROFILE, Problem
from app.schemas.response import SystemMessage
from app.services import user_input_queue
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
from app.tools.paper_postprocessor import prepare_paper_markdown
from app.tools.pdf_visual_checker import check_pdf_visual
from app.tools.submission_audit import write_submission_audit_report
from app.core.flows import Flows
from app.core.llm.llm_factory import LLMFactory


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

    async def _build_agents(
        self,
        coder_llm,
        writer_llm,
        comp_template: CompTemplate,
        format_output: FormatOutPut,
        user_input_provider,
    ) -> tuple[NotebookSerializer, BaseCodeInterpreter, CoderAgent, WriterAgent]:
        """构建代码手/写作手 Agent 及其依赖的沙盒环境（execute 与 resume 共享）。

        Args:
            coder_llm: 代码手使用的 LLM 实例。
            writer_llm: 写作手使用的 LLM 实例。
            comp_template: 竞赛模板类型。
            format_output: 输出格式。
            user_input_provider: 实时消息干预的输入提供函数。

        Returns:
            (notebook_serializer, code_interpreter, coder_agent, writer_agent) 元组。
        """
        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="正在创建代码沙盒环境"),
        )

        notebook_serializer = NotebookSerializer(work_dir=self.work_dir)
        code_interpreter = await create_interpreter(
            kind="local",
            task_id=self.task_id,
            work_dir=self.work_dir,
            notebook_serializer=notebook_serializer,
            timeout=3000,
        )

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

    async def _replay_notebook(
        self,
        code_interpreter: BaseCodeInterpreter,
        checkpoint_manager: CheckpointManager | None = None,
    ) -> None:
        """重放 notebook.ipynb 中已成功执行的代码单元格，重建内核变量状态（仅续传时调用）。

        优先级：
        1. 从变量快照恢复（最快，秒级）
        2. 增量重放（只重放新单元格）
        3. 全量重放（fallback）

        Args:
            code_interpreter: 新建的代码解释器实例。
            checkpoint_manager: 检查点管理器，用于增量重放。
        """
        # 尝试从变量快照恢复（最快）
        from app.tools.variable_snapshot import VariableSnapshot

        notebook_path = os.path.join(self.work_dir, "notebook.ipynb")
        snapshot = VariableSnapshot(self.work_dir)
        replay_start_cell_index = 0
        replay_start_code_index = 0
        replay_start_uses_cell_index = True
        replay_mode = "全量重放"

        if snapshot.exists():
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="从变量快照恢复计算环境..."),
            )

            # 获取内核客户端
            kernel_client = getattr(code_interpreter, "kc", None)
            if kernel_client and await snapshot.load(kernel_client):
                logger.info("变量快照恢复成功，跳过单元格重放")
                meta = snapshot.load_meta()
                replay_start_cell_index = self._safe_non_negative_int(
                    meta.get("notebook_cell_count"), default=0
                )
                replay_start_code_index = self._safe_non_negative_int(
                    meta.get("notebook_code_cell_count"), default=0
                )
                replay_start_uses_cell_index = "notebook_cell_count" in meta
                replay_mode = "快照后增量重放"
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content="计算环境恢复完成（从快照）"),
                )
            else:
                logger.warning("变量快照恢复失败，降级为全量重放")
                if checkpoint_manager is not None:
                    checkpoint_manager.set_variable_snapshot_exists(False)
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content="快照恢复失败，使用全量重放..."),
                )

        if not os.path.exists(notebook_path):
            if replay_mode == "快照后增量重放":
                logger.info("未找到 notebook.ipynb，已从变量快照恢复，跳过单元格重放")
                return
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

        # 无快照时必须全量重放；快照成功时只补齐快照之后新增的成功单元格。
        if replay_start_uses_cell_index:
            cells_to_replay = [
                (i, cell) for i, cell in all_code_cells if i >= replay_start_cell_index
            ]
        else:
            cells_to_replay = [
                (i, cell)
                for code_index, (i, cell) in enumerate(all_code_cells)
                if code_index >= replay_start_code_index
            ]

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

    @staticmethod
    def _safe_non_negative_int(value, default: int = 0) -> int:
        """将 metadata 字段转换为非负整数。"""
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(parsed, 0)

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
    ) -> None:
        """执行 solution_flows 循环（代码手求解 + 写作手撰写），已完成的阶段直接跳过。"""
        solution_flows = flows.get_solution_flows(self.questions, modeler_response)

        for key, value in solution_flows.items():
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
                SystemMessage(content=f"代码手开始求解{key}"),
            )

            coder_response = await coder_agent.run(
                prompt=value["coder_prompt"], subtask_title=key
            )

            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content=f"代码手求解成功{key}", type="success"),
            )

            writer_prompt = flows.get_writer_prompt(
                key,
                coder_response.code_response or "",
                code_interpreter,
                config_template,
            )

            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content=f"论文手开始写{key}部分"),
            )

            ## TODO: 图片引用错误
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

    async def _run_write_flows(
        self,
        flows: Flows,
        writer_agent: WriterAgent,
        user_output: UserOutput,
        checkpoint_manager: CheckpointManager,
        config_template: dict,
        ques_all: str,
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

            writer_response = await writer_agent.run(prompt=value, sub_title=key)

            user_output.set_res(key, writer_response)
            checkpoint_manager.mark_phase_completed(
                key, None, writer_response.model_dump()
            )

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
        payload = {
            "task_id": self.task_id,
            "status": "waiting_review",
            "gate_enabled": settings.HUMAN_MODEL_GATE_ENABLED,
            "created_at": datetime.datetime.now().isoformat(),
            "comp_template": problem.comp_template.value,
            "format_output": problem.format_output.value,
            "export_profile": problem.export_profile.value,
            "questions": self.questions,
            "ques_count": self.ques_count,
            "modeler_response": modeler_response.model_dump(),
            "review": {
                "approved": False,
                "approved_at": None,
                "comment": "",
            },
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

    async def _export_results(
        self,
        user_output: UserOutput,
        export_profile: ExportProfile | str | None = DEFAULT_MODELING_EXPORT_PROFILE,
    ) -> None:
        """保存结果并导出 PDF/LaTeX/候选清单（execute 与 resume 共享）。"""
        logger.info(user_output.get_res())

        user_output.save_result()
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
                export_profile=normalize_export_profile(export_profile).value,
                declared_problem_count=declared_problem_count or None,
            )
            if preflight_report.get("status") == "PASS":
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content="论文排版预检通过，已规范参考文献并附加核心代码"),
                )
            else:
                logger.warning(f"论文排版预检存在风险: {preflight_report}")
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
        except Exception as e:
            logger.error(f"论文排版后处理失败: {e}")
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
            logger.warning(f"PDF 生成跳过: {pdf_result['reason']}")
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content=f"已跳过 PDF 生成: {pdf_result['reason']}，其余结果（Markdown/Word）不受影响",
                    type="warning",
                ),
            )

        pdf_visual_result = None
        if pdf_result["success"]:
            pdf_visual_result = check_pdf_visual(pdf_path, self.work_dir)
            if pdf_visual_result.get("success"):
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content="PDF 后验视觉检查通过"),
                )
            else:
                logger.warning(f"PDF 后验视觉检查存在风险: {pdf_visual_result}")
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
                        "pdf": pdf_result,
                        "pdf_visual_check": pdf_visual_result,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.error(f"写入 export_status.json 失败: {e}")

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
                logger.error(f"LaTeX sidecar 导出失败: {tex_result['reason']}")
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content=f"LaTeX 项目导出失败: {tex_result['reason']}，其余结果不受影响",
                        type="warning",
                    ),
                )
            else:
                logger.warning(f"LaTeX sidecar 导出跳过: {tex_result['reason']}")
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(
                        content=f"已跳过 LaTeX 项目导出: {tex_result['reason']}，其余结果不受影响",
                        type="warning",
                    ),
                )
        except Exception as e:
            logger.error(f"LaTeX sidecar 导出异常: {e}")
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content=f"LaTeX 项目导出异常: {e}，其余结果不受影响", type="warning"
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
            logger.error(f"submission_audit_report 生成失败: {e}")
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content=f"submission_audit_report 生成失败: {e}", type="warning"
                ),
            )

        ################################################ generate candidate manifest
        try:
            write_candidate_manifest(self.work_dir, self.task_id)
        except Exception as e:
            logger.error(f"candidate_manifest.json 生成失败: {e}")
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content=f"candidate_manifest.json 生成失败: {e}", type="error"
                ),
            )

    async def execute(self, problem: Problem):  # type: ignore[reportIncompatibleMethodOverride]
        """执行数学建模工作流。

        Args:
            problem: 包含题目信息、模板配置等的 Problem 对象。
        """
        self.task_id = problem.task_id
        self.work_dir = create_work_dir(self.task_id)

        llm_factory = LLMFactory(self.task_id)
        coordinator_llm, modeler_llm, coder_llm, writer_llm = llm_factory.get_all_llms()

        # 实时消息干预：取出排队中的用户输入，注入下一次 LLM 调用
        user_input_provider = lambda: user_input_queue.pop_all(self.task_id)  # noqa: E731

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
            coordinator_response = await coordinator_agent.run(problem.ques_all)
            self.questions = coordinator_response.questions
            self.ques_count = coordinator_response.ques_count
        except Exception as e:
            #  非数学建模问题
            logger.error(f"CoordinatorAgent 执行失败: {e}")
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

        modeler_agent = ModelerAgent(
            self.task_id,
            modeler_llm,
            context_window=settings.MODELER_CONTEXT_WINDOW,
            cancel_event=self.cancel_event,
            user_input_provider=user_input_provider,
        )

        modeler_response = await modeler_agent.run(coordinator_response)
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
                questions=self.questions,
                ques_count=self.ques_count,
                modeler_response=modeler_response.model_dump(),
                updated_at=datetime.datetime.now().isoformat(),
            )
        )
        self._write_modeling_decision(problem, modeler_response)
        if settings.HUMAN_MODEL_GATE_ENABLED:
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

        user_output = UserOutput(work_dir=self.work_dir, ques_count=self.ques_count)

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
        )

        flows = Flows(self.questions)
        config_template = get_config_template(problem.comp_template)

        ################################################ solution steps
        await self._run_solution_flows(
            flows,
            modeler_response,
            coder_agent,
            writer_agent,
            code_interpreter,
            user_output,
            checkpoint_manager,
            config_template,
        )

        # 关闭沙盒
        await code_interpreter.cleanup()

        ################################################ write steps
        await self._run_write_flows(
            flows,
            writer_agent,
            user_output,
            checkpoint_manager,
            config_template,
            problem.ques_all,
        )

        await self._export_results(user_output, problem.export_profile)

    async def resume(self, task_id: str) -> None:
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
        comp_template = CompTemplate(checkpoint.comp_template)
        format_output = FormatOutPut(checkpoint.format_output)
        export_profile = ExportProfile(checkpoint.export_profile)
        modeler_response = ModelerToCoder.model_validate(checkpoint.modeler_response)
        self._write_modeler_plan(modeler_response)

        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content="正在从检查点续传任务，跳过已完成阶段..."),
        )

        llm_factory = LLMFactory(self.task_id)
        # 续传时不重新调用协调者/建模手，只需要代码手和写作手的 LLM
        _coordinator_llm, _modeler_llm, coder_llm, writer_llm = (
            llm_factory.get_all_llms()
        )

        user_input_provider = lambda: user_input_queue.pop_all(self.task_id)  # noqa: E731

        user_output = UserOutput(work_dir=self.work_dir, ques_count=self.ques_count)

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
        )

        # 重建 Jupyter 内核变量状态
        await self._replay_notebook(code_interpreter, checkpoint_manager)

        flows = Flows(self.questions)
        config_template = get_config_template(comp_template)

        ################################################ solution steps
        await self._run_solution_flows(
            flows,
            modeler_response,
            coder_agent,
            writer_agent,
            code_interpreter,
            user_output,
            checkpoint_manager,
            config_template,
        )

        # 关闭沙盒
        await code_interpreter.cleanup()

        ################################################ write steps
        await self._run_write_flows(
            flows,
            writer_agent,
            user_output,
            checkpoint_manager,
            config_template,
            checkpoint.ques_all,
        )

        await self._export_results(user_output, export_profile)
