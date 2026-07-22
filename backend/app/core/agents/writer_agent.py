"""写作手 Agent 模块，负责基于建模结果撰写学术论文。"""

import asyncio
import re
from typing import Callable
from app.core.agents.agent import Agent
from app.core.llm.llm import LLM
from app.core.llm.types import StandardResponse, ToolCall
from app.core.prompts import get_writer_prompt
from app.schemas.enums import CompTemplate, FormatOutPut
from app.config.setting import ApiType
from app.tools.openalex_scholar import OpenAlexScholar
from app.utils.log_util import logger
from app.services.redis_manager import redis_manager
from app.schemas.response import SystemMessage, WriterMessage
import json
from app.core.functions import writer_tools, writer_tools_anthropic
from app.schemas.A2A import WriterResponse


# TODO: 并行 parallel
# TODO: 获取当前文件下的文件
# TODO: 引用cites tool

# 真工具调用的最大往返轮数。reasoning 模型可能连续多轮只返回 tool_calls
# （content 为空），若不设上限会无限搜索文献；若只允许一轮（旧行为），
# 第二轮 tool_calls 的 content 为空会被直接当成章节正文，静默产出空章节。
MAX_TOOL_ROUNDS = 3

PSEUDO_SEARCH_TOOL_RE = re.compile(
    r"<tool_call>\s*<function=search_papers>(?P<body>.*?)</function>\s*</tool_call>",
    re.DOTALL,
)
PSEUDO_TOOL_PARAM_RE = re.compile(
    r"<parameter=(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)>(?P<value>.*?)</parameter>",
    re.DOTALL,
)


def _has_pseudo_tool_call(content: str) -> bool:
    return bool(PSEUDO_SEARCH_TOOL_RE.search(content or ""))


def _parse_pseudo_search_tool_call(content: str) -> dict | None:
    """Parse XML-like tool text emitted by some OpenAI-compatible models."""
    match = PSEUDO_SEARCH_TOOL_RE.search(content or "")
    if not match:
        return None

    params: dict = {}
    for param in PSEUDO_TOOL_PARAM_RE.finditer(match.group("body")):
        name = param.group("name")
        value = param.group("value").strip()
        if name in {"limit", "year_from", "year_to", "min_citations"}:
            params[name] = int(value) if value and value.lower() != "none" else None
        elif name == "include_web":
            lowered = value.lower()
            params[name] = None if lowered == "none" else lowered == "true"
        elif name == "source_types":
            try:
                params[name] = json.loads(value)
            except json.JSONDecodeError:
                params[name] = [value] if value else None
        else:
            params[name] = value
    return params if params.get("query") else None


class WriterAgent(Agent):
    """写作手 Agent，基于建模和代码执行结果撰写竞赛论文。"""
    def __init__(
        self,
        task_id: str,
        model: LLM,
        comp_template: CompTemplate = CompTemplate.CHINA,
        format_output: FormatOutPut = FormatOutPut.Markdown,
        scholar: OpenAlexScholar | None = None,
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
            guidance_target="writer",
        )
        self.format_out_put = format_output
        self.comp_template = comp_template
        self.scholar = scholar
        self.is_first_run = True
        self.system_prompt = get_writer_prompt(format_output)
        self.available_images: list[str] = []

    async def run(  # type: ignore[reportIncompatibleMethodOverride]
        self,
        prompt: str,
        available_images: list[str] | None = None,
        sub_title: str | None = None,
    ) -> WriterResponse:
        """
        执行写作任务
        Args:
            prompt: 写作提示
            available_images: 可用的图片相对路径列表（如 20250420-173744-9f87792c/编号_分布.png）
            sub_title: 子任务标题
        """
        logger.info(f"写作子任务已开始: title_chars={len(sub_title or '')}")

        # 根据 api_type 选择 tools 格式
        api_type = self.model.api_type
        tools = writer_tools_anthropic if api_type == ApiType.ANTHROPIC else writer_tools
        if self.scholar is None:
            tools = []

        if self.is_first_run:
            self.is_first_run = False
            await self.append_chat_history(
                {"role": "system", "content": self.system_prompt}
            )

        if available_images:
            self.available_images = available_images
            image_lines = "\n".join(
                [f"- ![{img}]({img})" for img in available_images]
            )
            image_prompt = (
                f"\n\n【必须插入的图片列表】\n"
                f"以下图片是代码手生成的，你必须在论文相关段落后用 Markdown 格式逐一插入：\n"
                f"{image_lines}\n"
                f"插入格式为独占一行的 ![描述](文件名)，每张图片后需配3行以上的分析解读。\n"
            )
            logger.info(
                "写作图片提示已添加: "
                f"image_count={len(available_images)}, chars={len(image_prompt)}"
            )
            prompt = prompt + image_prompt

        logger.info(f"{self.__class__.__name__}:开始:执行对话")

        await self.append_chat_history({"role": "user", "content": prompt})

        # 获取历史消息用于本次对话
        response = await self._chat(
            history=self.chat_history,
            tools=tools,
            tool_choice="auto",
            agent_name=self.__class__.__name__,
            sub_title=sub_title,
        )

        footnotes = []
        response_content: str = ""
        # 记录“产生最终正文的那次响应”，最终 assistant 历史消息的
        # reasoning_content 必须取自它，否则会把第一轮的推理错配到
        # 后续轮次生成的正文上。
        content_response: StandardResponse = response

        if response.tool_calls:
            logger.info("检测到工具调用")
            # 有界循环处理真工具调用：reasoning 模型常连续多轮只返回
            # tool_calls（此时 content 为空）。旧实现只跟进一轮，第二轮
            # 工具调用响应会被直接当作正文，导致章节静默为空。
            tool_rounds = 0
            while response.tool_calls and tool_rounds < MAX_TOOL_ROUNDS:
                tool_rounds += 1
                await self._append_assistant_tool_calls_msg(response)

                for tool_call in response.tool_calls:
                    if tool_call.name != "search_papers":
                        logger.warning(f"未知写作工具调用: {tool_call.name}")
                        # 未知工具也必须补占位 tool 响应：OpenAI 协议要求
                        # 每个 tool_call 都有对应的 role=tool 消息，否则
                        # 孤儿 tool_call 会被历史修复逻辑剔除或使请求报错。
                        papers_str = f"工具 {tool_call.name} 不受支持，未执行。"
                    else:
                        papers_str = await self._execute_search_papers(tool_call)
                    await self.append_chat_history(
                        {
                            "role": "tool",
                            "content": papers_str,
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                        }
                    )

                response = await self._chat(
                    history=self.chat_history,
                    tools=tools,
                    tool_choice="auto",
                    agent_name=self.__class__.__name__,
                    sub_title=sub_title,
                )

            if response.tool_calls:
                # 超过轮次上限仍要求调用工具：先写入本轮 assistant(tool_calls)
                # 与占位 tool 响应保持协议配对，再禁用工具强制输出正文，
                # 避免无限检索文献而始终不产出章节内容。
                logger.warning(
                    f"写作手工具往返超过 {MAX_TOOL_ROUNDS} 轮，禁用工具强制收尾"
                )
                await self._append_assistant_tool_calls_msg(response)
                for tool_call in response.tool_calls:
                    await self.append_chat_history(
                        {
                            "role": "tool",
                            "content": "文献检索轮次已达上限，该工具调用未执行。",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                        }
                    )
                await self.append_chat_history(
                    {
                        "role": "user",
                        "content": (
                            "文献检索已充分，现在禁止再调用任何工具，"
                            "请直接输出本章节完整正文。"
                        ),
                    }
                )
                response = await self._chat(
                    history=self.chat_history,
                    tools=[],
                    tool_choice=None,
                    agent_name=self.__class__.__name__,
                    sub_title=sub_title,
                )

            response_content = response.content or ""
            content_response = response
        else:
            response_content = response.content or ""
            pseudo_arguments = _parse_pseudo_search_tool_call(response_content)
            if pseudo_arguments is not None and self.scholar is not None:
                logger.info("检测到文本形式 search_papers 伪工具调用，执行兼容检索")
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content="写作手执行文本形式 search_papers 兼容检索"),
                )
                query = pseudo_arguments.get("query", "")
                try:
                    papers = await self.scholar.search_papers(
                        query=query,
                        limit=pseudo_arguments.get("limit", 8),
                        year_from=pseudo_arguments.get("year_from"),
                        year_to=pseudo_arguments.get("year_to"),
                        min_citations=pseudo_arguments.get("min_citations"),
                        source_types=pseudo_arguments.get("source_types"),
                        include_web=pseudo_arguments.get("include_web"),
                    )
                    papers_str = self.scholar.papers_to_str(papers)
                except Exception as exc:
                    logger.error(
                        "文本形式 search_papers 兼容检索失败: "
                        f"{type(exc).__name__}"
                    )
                    papers_str = f"文献检索失败: {type(exc).__name__}"

                await self.append_chat_history(
                    {"role": "assistant", "content": response_content}
                )
                await self.append_chat_history(
                    {
                        "role": "user",
                        "content": (
                            "文献检索结果如下，请基于这些结果直接输出本节论文正文。"
                            "不要输出工具调用标记。若使用文献，必须写成 "
                            "{[^1] 完整引用信息} 格式：\n\n"
                            f"{papers_str}"
                        ),
                    }
                )
                next_response = await self._chat(
                    history=self.chat_history,
                    tools=tools,
                    tool_choice="auto",
                    agent_name=self.__class__.__name__,
                    sub_title=sub_title,
                )
                response_content = next_response.content or ""
                content_response = next_response
                if _has_pseudo_tool_call(response_content):
                    await self.append_chat_history(
                        {"role": "assistant", "content": response_content}
                    )
                    await self.append_chat_history(
                        {
                            "role": "user",
                            "content": (
                                "上一次输出仍然是工具调用标记。现在禁止调用任何工具，"
                                "也不要输出 <tool_call>。请直接按照原写作任务输出完整论文正文；"
                                "如果是模型章节，必须包含“# 五、模型的建立与求解”或对应的 5.x 小节标题。"
                            ),
                        }
                    )
                    final_response = await self._chat(
                        history=self.chat_history,
                        tools=[],
                        tool_choice=None,
                        agent_name=self.__class__.__name__,
                        sub_title=sub_title,
                    )
                    response_content = final_response.content or ""
                    content_response = final_response

        if not response_content.strip():
            # 终局空内容防线：无论走哪条路径，空正文都不允许静默进入
            # user_output——否则要到论文预检才暴露，届时只剩一次定向回修。
            # 只重试一次，仍为空则记录错误并原样返回，让上游门禁可见。
            logger.warning("写作手输出为空，追加提示并禁用工具重试一次")
            await self.append_chat_history(
                {
                    "role": "user",
                    "content": "上一轮输出为空，请直接输出本章节完整正文。",
                }
            )
            retry_response = await self._chat(
                history=self.chat_history,
                tools=[],
                tool_choice=None,
                agent_name=self.__class__.__name__,
                sub_title=sub_title,
            )
            response_content = retry_response.content or ""
            content_response = retry_response
            if not response_content.strip():
                logger.error("写作手空内容重试后仍为空，原样返回交由上游门禁处理")

        final_assistant_msg: dict = {"role": "assistant", "content": response_content}
        if content_response.reasoning_content:
            # reasoning_content 必须取产生本次正文那轮响应的值：旧实现固定取
            # 第一轮 response 的推理，多轮工具往返后会张冠李戴。
            final_assistant_msg["reasoning_content"] = (
                content_response.reasoning_content
            )
        self.chat_history.append(final_assistant_msg)
        logger.info(f"{self.__class__.__name__}:完成:执行对话")
        return WriterResponse(response_content=response_content, footnotes=footnotes)

    async def _append_assistant_tool_calls_msg(
        self, response: StandardResponse
    ) -> None:
        """把带 tool_calls 的 assistant 响应写入对话历史。

        必须先记录完整工具调用，再逐一追加 tool 结果，避免多工具调用时
        上下文不一致。

        Args:
            response: 含 tool_calls 的 LLM 标准响应。
        """
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

    async def _execute_search_papers(self, tool_call: ToolCall) -> str:
        """执行 search_papers 工具调用并返回文本结果。

        Args:
            tool_call: search_papers 工具调用。

        Returns:
            文献检索结果文本；失败时返回错误说明。
        """
        logger.info("调用工具: search_papers")
        await redis_manager.publish_message(
            self.task_id,
            SystemMessage(content=f"写作手调用{tool_call.name}工具"),
        )

        arguments = json.loads(tool_call.arguments or "{}")
        query = arguments.get("query", "")

        await redis_manager.publish_message(
            self.task_id,
            WriterMessage(content=query),
        )

        scholar = self.scholar
        try:
            if scholar is None:
                raise RuntimeError("scholar 未初始化")
            papers = await scholar.search_papers(
                query=query,
                limit=arguments.get("limit", 8),
                year_from=arguments.get("year_from"),
                year_to=arguments.get("year_to"),
                min_citations=arguments.get("min_citations"),
                source_types=arguments.get("source_types"),
                include_web=arguments.get("include_web"),
            )
        except Exception as exc:
            error_msg = f"搜索文献失败: {type(exc).__name__}"
            logger.error(error_msg)
            return error_msg
        # TODO: pass to frontend
        logger.info(f"搜索文献结果已获取: count={len(papers)}")
        return scholar.papers_to_str(papers)

    async def summarize(self) -> str:
        """总结对话内容，生成任务执行摘要。"""
        try:
            await self.append_chat_history(
                {"role": "user", "content": "请简单总结以上完成什么任务取得什么结果:"}
            )
            # 获取历史消息用于本次对话
            response = await self._chat(
                history=self.chat_history, agent_name=self.__class__.__name__
            )
            response_content = response.content or ""
            summary_msg: dict = {"role": "assistant", "content": response_content}
            if response.reasoning_content:
                summary_msg["reasoning_content"] = response.reasoning_content
            await self.append_chat_history(summary_msg)
            return response_content
        except Exception as exc:
            logger.error(f"总结生成失败: {type(exc).__name__}")
            # 返回一个基础总结，避免完全失败
            return "由于网络原因无法生成详细总结，但已完成主要任务处理。"
