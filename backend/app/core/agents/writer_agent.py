"""写作手 Agent 模块，负责基于建模结果撰写学术论文。"""

import asyncio
import re
from typing import Callable
from app.core.agents.agent import Agent
from app.core.llm.llm import LLM
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

        if response.tool_calls:
            logger.info("检测到工具调用")
            # 更新对话历史 - 添加助手的工具调用响应。必须先记录完整工具调用，
            # 再逐一追加 tool 结果，避免多工具调用时上下文不一致。
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
                tool_id = tool_call.id
                if tool_call.name != "search_papers":
                    logger.warning(f"未知写作工具调用: {tool_call.name}")
                    continue

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
                    papers_str = error_msg
                else:
                    papers_str = scholar.papers_to_str(papers)
                # TODO: pass to frontend
                logger.info(f"搜索文献结果已获取: count={len(papers)}")
                await self.append_chat_history(
                    {
                        "role": "tool",
                        "content": papers_str,
                        "tool_call_id": tool_id,
                        "name": "search_papers",
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
        self.chat_history.append({"role": "assistant", "content": response_content, "reasoning_content": response.reasoning_content} if response.reasoning_content else {"role": "assistant", "content": response_content})
        logger.info(f"{self.__class__.__name__}:完成:执行对话")
        return WriterResponse(response_content=response_content, footnotes=footnotes)

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
