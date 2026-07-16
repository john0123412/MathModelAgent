"""代码手 Agent 模块，负责生成和执行 Python 代码完成建模任务。"""

import asyncio
import ast
import json
import re
from pathlib import Path
from typing import Callable
from app.core.agents.agent import Agent
from app.config.setting import settings, ApiType
from app.utils.log_util import logger
from app.services.redis_manager import redis_manager
from app.schemas.response import SystemMessage, InterpreterMessage
from app.tools.base_interpreter import BaseCodeInterpreter
from app.core.llm.llm import LLM
from app.schemas.A2A import CoderToWriter
from app.core.prompts import CODER_PROMPT
from app.utils.common_utils import get_current_files
from app.core.prompts import get_reflection_prompt
from app.core.functions import coder_tools, coder_tools_anthropic
from app.tools.execution_validation import record_execution_evidence

# TODO: 时间等待过久，stop 进程
# TODO: 支持 cuda
# TODO: 引入创新方案：

_FINAL_OUTPUT_MARKERS = (
    "项目完成",
    "任务完成",
    "交付完成",
    "所有文件已生成",
    "所有文件均已生成",
    "最终完成",
    "核心输出",
)

_PARENT_PATH_PATTERN = re.compile(r"(^|[\\/])\.\.([\\/]|$)")
_WORK_DIR_PATH_PATTERN = re.compile(
    r"(^|[\\/])(?:backend[\\/])?project[\\/]work_dir([\\/]|$)"
)
_FORMAL_SUBTASK_PATTERN = re.compile(r"^(ques[1-9][0-9]*)(?:_repair)?$")


def _looks_like_final_tool_output(output: str) -> bool:
    """判断工具输出是否明显是收尾总结，避免模型反复生成完成证书/总结。"""
    if not output:
        return False
    return any(marker in output for marker in _FINAL_OUTPUT_MARKERS)


def _iter_string_literals(code: str):
    try:
        tree = ast.parse(code)
    except SyntaxError:
        yield code
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def _find_cross_task_path(code: str) -> str | None:
    """检测模型生成代码是否试图读取当前任务目录之外的历史任务文件。"""
    for value in _iter_string_literals(code):
        normalized = value.replace("\\", "/")
        if _PARENT_PATH_PATTERN.search(normalized):
            return value
        if _WORK_DIR_PATH_PATTERN.search(normalized):
            return value
    return None


def _formal_subtask_id(subtask_title: str) -> str | None:
    """Return the formal ``quesN`` id for a normal or directed-repair turn."""
    matched = _FORMAL_SUBTASK_PATTERN.fullmatch(subtask_title.strip())
    return matched.group(1) if matched else None


def _snapshot_task_files(work_dir: str) -> dict[str, tuple[int, int]]:
    """Return cheap fingerprints for task-local files created by this Coder turn."""
    root = Path(work_dir).resolve()
    if not root.is_dir():
        return {}
    snapshots: dict[str, tuple[int, int]] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        relative = str(path.relative_to(root)).replace("\\", "/")
        snapshots[relative] = (stat.st_size, stat.st_mtime_ns)
    return snapshots


def _changed_task_files(
    before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]
) -> set[str]:
    return {path for path, fingerprint in after.items() if before.get(path) != fingerprint}


def _evidence_source_paths(arguments: object) -> set[str]:
    """Extract result and figure-data paths supplied to the evidence recorder."""
    if not isinstance(arguments, dict):
        return set()
    paths: set[str] = set()
    for metric in arguments.get("metrics", []):
        if isinstance(metric, dict) and isinstance(metric.get("source_path"), str):
            paths.add(str(Path(metric["source_path"])).replace("\\", "/"))
    for constraint in arguments.get("constraints", []):
        if isinstance(constraint, dict) and isinstance(constraint.get("source_path"), str):
            paths.add(str(Path(constraint["source_path"])).replace("\\", "/"))
    for figure in arguments.get("figures", []):
        if not isinstance(figure, dict):
            continue
        for field in ("path", "data_path"):
            if isinstance(figure.get(field), str):
                paths.add(str(Path(figure[field])).replace("\\", "/"))
    return paths


class CoderAgent(Agent):
    """代码手 Agent，通过 LLM 生成代码并在解释器中执行，支持错误反思和重试。"""
    def __init__(
        self,
        task_id: str,
        model: LLM,
        work_dir: str,  # 工作目录
        max_chat_turns: int | None = settings.MAX_CHAT_TURNS,  # 最大聊天次数熔断上限（跨子任务累计）；显式传 None 表示无限制
        max_retries: int | None = settings.MAX_RETRIES,  # 单子任务最大重试次数熔断上限；显式传 None 表示无限制
        max_successful_tool_calls: int | None = settings.CODER_MAX_SUCCESSFUL_TOOL_CALLS_PER_SUBTASK,
        code_interpreter: BaseCodeInterpreter | None = None,
        context_window: int = 128000,
        cancel_event: asyncio.Event | None = None,
        user_input_provider: Callable[[], list[str]] | None = None,
    ) -> None:
        super().__init__(
            task_id,
            model,
            context_window,
            cancel_event=cancel_event,
            user_input_provider=user_input_provider,
        )
        self.work_dir = work_dir
        self.max_chat_turns = max_chat_turns
        self.current_chat_turns = 0
        self.max_retries = max_retries
        self.max_successful_tool_calls = max_successful_tool_calls
        self.is_first_run = True
        self.system_prompt = CODER_PROMPT
        self.code_interpreter = code_interpreter

    async def run(self, prompt: str, subtask_title: str) -> CoderToWriter:  # type: ignore[reportIncompatibleMethodOverride]
        """执行代码手子任务，生成并运行代码。

        Args:
            prompt: 子任务描述。
            subtask_title: 子任务标题，用于分段输出。

        Returns:
            CoderToWriter 对象，包含代码执行结果和生成的图片列表。
        """
        logger.info(
            f"{self.__class__.__name__}:开始执行子任务: "
            f"title_chars={len(subtask_title)}"
        )
        if self.code_interpreter is None:
            raise RuntimeError("code_interpreter 未初始化")
        self.code_interpreter.add_section(subtask_title)

        # 根据 api_type 选择 tools 格式
        api_type = self.model.api_type
        tools = coder_tools_anthropic if api_type == ApiType.ANTHROPIC else coder_tools

        # 如果是第一次运行，则添加系统提示
        if self.is_first_run:
            logger.info("首次运行，添加系统提示和数据集文件信息")
            self.is_first_run = False
            await self.append_chat_history(
                {"role": "system", "content": self.system_prompt}
            )
            # 当前数据集文件
            await self.append_chat_history(
                {
                    "role": "user",
                    "content": f"当前文件夹下的数据集文件{get_current_files(self.work_dir, 'data')}",
                }
            )

        # 添加 sub_task
        logger.info(f"添加子任务提示: chars={len(prompt)}")
        await self.append_chat_history({"role": "user", "content": prompt})

        retry_count = 0
        last_error_message = ""
        consecutive_final_outputs = 0
        successful_tool_calls = 0
        execution_error_occurred = False
        formal_subtask_id = _formal_subtask_id(subtask_title)
        evidence_commit_required = False
        evidence_changed_paths: set[str] = set()

        while True:
            if self.max_retries is not None and retry_count >= self.max_retries:
                logger.error(f"超过最大尝试次数: {self.max_retries}")
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content="超过最大尝试次数", type="error"),
                )
                logger.warning(
                    "任务失败，超过最大尝试次数: "
                    f"max_retries={self.max_retries}, "
                    f"last_error_chars={len(last_error_message)}"
                )
                return CoderToWriter(
                    code_response=f"任务失败，超过最大尝试次数{self.max_retries}, 最后错误信息: {last_error_message}",
                    created_images=[],
                    execution_attempted=successful_tool_calls > 0 or bool(last_error_message),
                    execution_succeeded=False,
                    execution_error_occurred=execution_error_occurred,
                )


            if self.max_chat_turns is not None and self.current_chat_turns >= self.max_chat_turns:
                logger.error(f"超过最大聊天次数: {self.max_chat_turns}")
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content="超过最大聊天次数", type="error"),
                )
                raise Exception(
                    f"Reached maximum number of chat turns ({self.max_chat_turns}). Task incomplete."
                )

            active_tools = tools
            active_tool_choice = "auto"
            if evidence_commit_required:
                # A code-run limit is a circuit breaker, not proof that the
                # formal subtask is complete.  At this boundary expose only the
                # trusted recorder, so a model cannot spend another turn on a
                # plot, notebook narration, or a hand-written manifest.
                active_tools = [
                    tool
                    for tool in tools
                    if (
                        tool.get("name") == "record_execution_evidence"
                        or tool.get("function", {}).get("name")
                        == "record_execution_evidence"
                    )
                ]
                active_tool_choice = "required"

            self.current_chat_turns += 1
            logger.info(f"当前对话轮次: {self.current_chat_turns}")
            
            try:
                response = await self._chat(
                    history=self.chat_history,
                    tools=active_tools,
                    tool_choice=active_tool_choice,
                    agent_name=self.__class__.__name__,
                )

                # 如果有工具调用
                if response.tool_calls:
                    logger.info("检测到工具调用")
                    if len(response.tool_calls) != 1:
                        # The legacy loop handled only the first call but still
                        # placed every call in chat history, leaving providers
                        # with orphaned tool-call ids.  A formal computation is
                        # intentionally one action per turn: execute, inspect,
                        # then record evidence.
                        assistant_msg: dict = {"role": "assistant", "content": response.content}
                        if response.reasoning_content:
                            assistant_msg["reasoning_content"] = response.reasoning_content
                        assistant_msg["tool_calls"] = [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.name, "arguments": tc.arguments},
                            }
                            for tc in response.tool_calls
                        ]
                        await self.append_chat_history(assistant_msg)
                        for tool_call in response.tool_calls:
                            await self.append_chat_history(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "name": tool_call.name,
                                    "content": (
                                        "每轮只能调用一个工具。请先执行或检查一个动作；"
                                        "结果文件写完后，在下一轮单独调用 "
                                        "record_execution_evidence。"
                                    ),
                                }
                            )
                        continue
                    tool_call = response.tool_calls[0]
                    tool_id = tool_call.id

                    is_execute_code_tool = (
                        tool_call.name == "execute_code"
                        or tool_call.name.startswith("CompatExecuteCode")
                    )
                    is_record_evidence_tool = tool_call.name == "record_execution_evidence"

                    if evidence_commit_required and not is_record_evidence_tool:
                        # Some compatible providers may return a stale tool
                        # call even after the tool list has been narrowed. Do
                        # not execute it: accepting it would bypass the
                        # evidence boundary that the cap is meant to enforce.
                        assistant_msg: dict = {
                            "role": "assistant", "content": response.content
                        }
                        if response.reasoning_content:
                            assistant_msg["reasoning_content"] = response.reasoning_content
                        assistant_msg["tool_calls"] = [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": tc.arguments,
                                },
                            }
                            for tc in response.tool_calls
                        ]
                        await self.append_chat_history(assistant_msg)
                        await self.append_chat_history(
                            {
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "name": tool_call.name,
                                "content": (
                                    "执行次数上限已到。现在只能调用 "
                                    "record_execution_evidence；不得继续执行代码。"
                                ),
                            }
                        )
                        continue

                    if is_record_evidence_tool:
                        logger.info("代码手提交受控执行证据")
                        assistant_msg: dict = {"role": "assistant", "content": response.content}
                        if response.reasoning_content:
                            assistant_msg["reasoning_content"] = response.reasoning_content
                        assistant_msg["tool_calls"] = [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.name, "arguments": tc.arguments},
                            }
                            for tc in response.tool_calls
                        ]
                        await self.append_chat_history(assistant_msg)
                        try:
                            arguments = json.loads(tool_call.arguments)
                            submitted_subtask_id = (
                                arguments.get("subtask_id")
                                if isinstance(arguments, dict)
                                else None
                            )
                            if (
                                formal_subtask_id is not None
                                and submitted_subtask_id != formal_subtask_id
                            ):
                                result = {
                                    "ok": False,
                                    "errors": [
                                        "当前 Coder 回合只能记录 "
                                        f"{formal_subtask_id}，不能改写 {submitted_subtask_id!r}。"
                                    ],
                                }
                            else:
                                source_paths = _evidence_source_paths(arguments)
                                stale_paths = source_paths - evidence_changed_paths
                                if formal_subtask_id is not None and not successful_tool_calls:
                                    result = {
                                        "ok": False,
                                        "errors": [
                                            "正式问题必须先成功执行代码并生成结果文件，才能提交执行证据。"
                                        ],
                                    }
                                elif formal_subtask_id is not None and stale_paths:
                                    result = {
                                        "ok": False,
                                        "errors": [
                                            "证据来源必须由本轮实际代码执行新建或更新；"
                                            f"当前未检测到更新：{', '.join(sorted(stale_paths))}。"
                                        ],
                                    }
                                else:
                                    result = record_execution_evidence(
                                        self.work_dir, **arguments
                                    )
                        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                            result = {
                                "ok": False,
                                "errors": [f"证据记录参数无效：{type(exc).__name__}。"],
                            }
                        await self.append_chat_history(
                            {
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "name": tool_call.name,
                                "content": json.dumps(result, ensure_ascii=False),
                            }
                        )
                        await redis_manager.publish_message(
                            self.task_id,
                            SystemMessage(
                                content=(
                                    "代码手已记录可验证执行证据"
                                    if result.get("ok")
                                    else "代码手提交的执行证据不完整，请按错误信息修正"
                                ),
                                type="error" if not result.get("ok") else "info",
                            ),
                        )
                        # The LLM receives the exact server-generated outcome and
                        # can correct only the failing source/record on its next
                        # turn.  This call never counts as code execution itself.
                        if result.get("ok"):
                            # A formal Coder turn owns one question.  Once its
                            # backend-owned evidence is persisted, stop this
                            # turn before a later model response can overwrite
                            # result files and invalidate the fresh manifest.
                            return CoderToWriter(
                                code_response=(
                                    response.content
                                    or "已在受控收束阶段记录执行证据。"
                                ),
                                created_images=await self.code_interpreter.get_created_images(
                                    subtask_title
                                ),
                                execution_attempted=successful_tool_calls > 0,
                                execution_succeeded=not execution_error_occurred,
                                execution_error_occurred=execution_error_occurred,
                            )
                        if evidence_commit_required and not result.get("ok"):
                            # Let the model repair the source file or arguments,
                            # then require another recorder call at the next cap.
                            evidence_commit_required = False
                        continue

                    if is_execute_code_tool:
                        logger.info(f"调用工具: {tool_call.name}")
                        await redis_manager.publish_message(
                            self.task_id,
                            SystemMessage(
                                content=f"代码手调用{tool_call.name}工具"
                            ),
                        )

                        code = json.loads(tool_call.arguments)["code"]
                        unsafe_path = _find_cross_task_path(code)
                        if unsafe_path is not None:
                            logger.warning("拒绝跨任务目录文件访问")
                            assistant_msg: dict = {
                                "role": "assistant",
                                "content": response.content,
                            }
                            if response.reasoning_content:
                                assistant_msg["reasoning_content"] = response.reasoning_content
                            assistant_msg["tool_calls"] = [
                                {
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {
                                        "name": tc.name,
                                        "arguments": tc.arguments,
                                    },
                                }
                                for tc in response.tool_calls
                            ]
                            await self.append_chat_history(assistant_msg)
                            await self.append_chat_history(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_id,
                                    "name": tool_call.name,
                                    "content": (
                                        "安全限制：代码不得读取当前任务目录之外的文件，"
                                        f"已拒绝路径 {unsafe_path!r}。"
                                        "请只使用当前任务目录中的文件；如果缺少模板或数据，"
                                        "请在当前目录直接创建所需输出文件。"
                                    ),
                                }
                            )
                            await redis_manager.publish_message(
                                self.task_id,
                                SystemMessage(
                                    content="代码手拒绝跨任务目录文件访问",
                                    type="error",
                                ),
                            )
                            continue

                        await redis_manager.publish_message(
                            self.task_id,
                            InterpreterMessage(
                                input={"code": code},
                            ),
                        )

                        # 更新对话历史 - 添加助手的响应
                        assistant_msg: dict = {"role": "assistant", "content": response.content}
                        if response.reasoning_content:
                            assistant_msg["reasoning_content"] = response.reasoning_content
                        if response.tool_calls:
                            assistant_msg["tool_calls"] = [
                                {
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {"name": tc.name, "arguments": tc.arguments},
                                }
                                for tc in response.tool_calls
                            ]
                        await self.append_chat_history(assistant_msg)

                        # 执行工具调用
                        logger.info("执行工具调用")
                        before_execution_files = (
                            _snapshot_task_files(self.work_dir)
                            if formal_subtask_id is not None
                            else {}
                        )
                        (
                            text_to_gpt,
                            error_occurred,
                            error_message,
                        ) = await self.code_interpreter.execute_code(code)

                        # 添加工具执行结果
                        if error_occurred:
                            execution_error_occurred = True
                            # 即使发生错误也要添加tool响应
                            await self.append_chat_history(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_id,
                                    "name": tool_call.name,
                                    "content": error_message,
                                }
                            )

                            logger.warning(
                                f"代码执行错误: error_chars={len(error_message)}"
                            )
                            retry_count += 1
                            logger.info(f"当前尝试次:{retry_count} / {self.max_retries}")
                            last_error_message = error_message
                            reflection_prompt = get_reflection_prompt(error_message, code)

                            await redis_manager.publish_message(
                                self.task_id,
                                SystemMessage(content="代码手反思纠正错误", type="error"),
                            )

                            await self.append_chat_history(
                                {"role": "user", "content": reflection_prompt}
                            )
                            continue
                        else:
                            # 成功执行的tool响应
                            # Keep the historical notebook error for audit, but a
                            # later successful execution means the current tool
                            # state is no longer an unresolved interpreter error.
                            execution_error_occurred = False
                            successful_tool_calls += 1
                            if formal_subtask_id is not None:
                                after_execution_files = _snapshot_task_files(self.work_dir)
                                evidence_changed_paths.update(
                                    _changed_task_files(
                                        before_execution_files, after_execution_files
                                    )
                                )
                            await self.append_chat_history(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_id,
                                    "name": tool_call.name,
                                    "content": text_to_gpt,
                                }
                            )
                            if _looks_like_final_tool_output(text_to_gpt):
                                consecutive_final_outputs += 1
                            else:
                                consecutive_final_outputs = 0

                            if consecutive_final_outputs >= 2 and formal_subtask_id is None:
                                logger.info("连续检测到完成性工具输出，自动收束代码手任务")
                                await redis_manager.publish_message(
                                    self.task_id,
                                    SystemMessage(content="代码手检测到任务已完成，自动收束"),
                                )
                                return CoderToWriter(
                                    code_response=text_to_gpt,
                                    created_images=await self.code_interpreter.get_created_images(
                                        subtask_title
                                    ),
                                    execution_attempted=True,
                                    execution_succeeded=not execution_error_occurred,
                                    execution_error_occurred=execution_error_occurred,
                                )
                            if consecutive_final_outputs >= 2 and formal_subtask_id is not None:
                                evidence_commit_required = True
                                await self.append_chat_history(
                                    {
                                        "role": "user",
                                        "content": (
                                            "完成性文字不能替代正式题目的计算证据。现在只能调用 "
                                            "record_execution_evidence，为当前问题 "
                                            f"{formal_subtask_id} 提交本轮新生成的结果来源。"
                                        ),
                                    }
                                )
                                continue
                            if (
                                self.max_successful_tool_calls is not None
                                and successful_tool_calls >= self.max_successful_tool_calls
                            ):
                                if formal_subtask_id:
                                    evidence_commit_required = True
                                    await self.append_chat_history(
                                        {
                                            "role": "user",
                                            "content": (
                                                "已达到代码执行上限。不要再运行代码、不要导入后端函数、"
                                                "不要手写 execution_validation.json。现在请立刻调用唯一"
                                                "可用的 record_execution_evidence，为当前正式问题 "
                                                f"{formal_subtask_id} 提交刚刚生成的结果文件、约束、指标和图表数据来源。"
                                            ),
                                        }
                                    )
                                    await redis_manager.publish_message(
                                        self.task_id,
                                        SystemMessage(
                                            content="代码执行上限已到，强制提交受控执行证据",
                                            type="warning",
                                        ),
                                    )
                                    continue
                                logger.info(
                                    "成功工具调用达到上限，自动收束代码手任务: "
                                    f"{successful_tool_calls}"
                                )
                                await redis_manager.publish_message(
                                    self.task_id,
                                    SystemMessage(
                                        content=(
                                            "代码手已完成多轮成功执行，达到自动收束上限，"
                                            "进入下一阶段"
                                        ),
                                    ),
                                )
                                return CoderToWriter(
                                    code_response=text_to_gpt,
                                    created_images=await self.code_interpreter.get_created_images(
                                        subtask_title
                                    ),
                                    execution_attempted=True,
                                    execution_succeeded=not execution_error_occurred,
                                    execution_error_occurred=execution_error_occurred,
                                )
                            # 成功执行后继续循环，等待下一步指令
                            continue
                    else:
                        logger.warning(f"不支持的工具调用: {tool_call.name}")
                        assistant_msg: dict = {"role": "assistant", "content": response.content}
                        if response.reasoning_content:
                            assistant_msg["reasoning_content"] = response.reasoning_content
                        assistant_msg["tool_calls"] = [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.name, "arguments": tc.arguments},
                            }
                            for tc in response.tool_calls
                        ]
                        await self.append_chat_history(assistant_msg)
                        await self.append_chat_history(
                            {
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "name": tool_call.name,
                                "content": (
                                    f"不支持工具 {tool_call.name}。"
                                    "请使用 execute_code 执行计算，完成后使用 "
                                    "record_execution_evidence 记录该题证据；"
                                    "如无需执行代码，请直接给出最终结果，不要再调用其他工具。"
                                ),
                            }
                        )
                        continue
                else:
                    if evidence_commit_required:
                        await self.append_chat_history(
                            {
                                "role": "user",
                                "content": (
                                    "当前正式问题尚未提交受控执行证据。请调用 "
                                    "record_execution_evidence，不要只输出文字。"
                                ),
                            }
                        )
                        continue
                    if formal_subtask_id is not None and successful_tool_calls:
                        evidence_commit_required = True
                        await self.append_chat_history(
                            {
                                "role": "user",
                                "content": (
                                    "正式问题已执行代码但尚未记录受控证据。请调用 "
                                    "record_execution_evidence；不要只输出完成说明。"
                                ),
                            }
                        )
                        continue
                    # 没有工具调用，表示任务完成
                    logger.info("没有工具调用，任务完成")
                    return CoderToWriter(
                        code_response=response.content,
                        created_images=await self.code_interpreter.get_created_images(
                            subtask_title
                        ),
                        execution_attempted=successful_tool_calls > 0,
                        execution_succeeded=(
                            successful_tool_calls > 0 and not execution_error_occurred
                        ),
                        execution_error_occurred=execution_error_occurred,
                    )
                    
            except asyncio.CancelledError:
                # 用户主动停止任务，向上传播，不做退避重试
                raise
            except Exception as exc:
                logger.error(f"执行过程中发生异常: {type(exc).__name__}")
                retry_count += 1
                last_error_message = str(exc)
                # WHY 必须退避：内层 llm.py 每次调用已自带 3 次重试，能走到
                # 这里说明是持续性故障（欠费/断网等）。若立即 continue 会形成
                # 无限紧循环持续打 LLM API 烧钱，直到任务超时。指数退避给
                # 故障恢复留时间，也压低失败期的请求频率。
                if self.cancel_event is not None and self.cancel_event.is_set():
                    # 用户已请求停止时不再傻等退避，立即结束
                    raise asyncio.CancelledError("任务被用户停止") from exc
                await asyncio.sleep(min(2 ** min(retry_count, 6), 60.0))
                continue
            logger.info(
                f"{self.__class__.__name__}:完成执行子任务: "
                f"title_chars={len(subtask_title)}"
            )
