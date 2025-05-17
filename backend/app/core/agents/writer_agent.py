from app.core.agents.agent import Agent
from app.core.llm.llm import LLM
from app.core.prompts import get_writer_prompt
from app.utils.enums import CompTemplate, FormatOutPut
from app.models.user_output import UserOutput
from app.tools.openalex_scholar import OpenAlexScholar
from app.utils.log_util import logger
from app.utils.redis_manager import redis_manager
from app.schemas.response import SystemMessage
import json
from app.core.functions import writer_tools
from app.utils.common_utils import get_footnotes
from icecream import ic
from app.models.model import WriterResponse


# 长文本
# 长文本
# TODO: 并行 parallel
# TODO: 获取当前文件下的文件
# TODO: 引用cites tool
class WriterAgent(Agent):  # 同样继承自Agent类
    def __init__(
        self,
        task_id: str,
        model: LLM,
        max_chat_turns: int = 10,  # 添加最大对话轮次限制
        comp_template: CompTemplate = CompTemplate,
        format_output: FormatOutPut = FormatOutPut.Markdown,
        user_output: UserOutput = None,
        scholar: OpenAlexScholar = None,
    ) -> None:
        super().__init__(task_id, model, max_chat_turns, user_output)
        self.format_out_put = format_output
        self.comp_template = comp_template
        self.scholar = scholar
        self.system_prompt = get_writer_prompt(format_output)
        self.available_images: list[str] = []

    async def run(
        self,
        prompt: str,
        available_images: list[str] = None,
        sub_title: str = None,
    ) -> WriterResponse:
        """
        执行写作任务
        Args:
            prompt: 写作提示
            available_images: 可用的图片相对路径列表（如 20250420-173744-9f87792c/编号_分布.png）
            sub_title: 子任务标题
        """
        logger.info(f"subtitle是:{sub_title}")

        if available_images:
            self.available_images = available_images
            # 拼接成完整URL
            image_list = ",".join(available_images)
            image_prompt = f"\n可用的图片链接列表：\n{image_list}\n请在写作时适当引用这些图片链接。"
            ic(image_prompt)
            prompt = prompt + image_prompt

        logger.info(f"{self.__class__.__name__}:开始:执行对话")
        self.current_chat_turns += 1  # 重置对话轮次计数器

        # 更新对话历史
        self.append_chat_history({"role": "system", "content": self.system_prompt})
        self.append_chat_history({"role": "user", "content": prompt})

        # 获取历史消息用于本次对话
        response = await self.model.chat(
            history=self.chat_history,
            tools=writer_tools,
            tool_choice="auto",
            agent_name=self.__class__.__name__,
            sub_title=sub_title,
        )

        if (
            hasattr(response.choices[0].message, "tool_calls")
            and response.choices[0].message.tool_calls
        ):
            logger.info("检测到工具调用")
            tool_call = response.choices[0].message.tool_calls[0]
            tool_id = tool_call.id
            tool_call.function.name
            if tool_call.function.name == "search_papers":
                logger.info("调用工具: search_papers")
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content=f"写作手调用{tool_call.function.name}工具"),
                )

                query = json.loads(tool_call.function.arguments)["query"]
                footnotes = get_footnotes(query)
                full_content = response.choices[0].message.content
                # 更新对话历史 - 添加助手的响应
                self.append_chat_history(
                    {
                        "role": "assistant",
                        "content": full_content,
                        "tool_calls": [
                            {
                                "id": tool_id,
                                "type": "function",
                                "function": {
                                    "name": "search_papers",
                                    "arguments": json.dumps({"query": query}),
                                },
                            }
                        ],
                    }
                )

                try:
                    papers = self.scholar.search_papers(query)
                except Exception as e:
                    logger.error(f"搜索文献失败: {str(e)}")
                    return f"搜索文献失败: {str(e)}"
                # TODO: pass to frontend
                papers_str = self.scholar.papers_to_str(papers)
                logger.info(f"搜索文献结果\n{papers_str}")
                self.append_chat_history(
                    {
                        "role": "tool",
                        "content": papers_str,
                        "tool_call_id": tool_id,
                        "name": "search_papers",
                    }
                )
                next_response = await self.model.chat(
                    history=self.chat_history,
                    tools=writer_tools,
                    tool_choice="auto",
                    agent_name=self.__class__.__name__,
                    sub_title=sub_title,
                )
                response_content = next_response.choices[0].message.content
        else:
            response_content = response.choices[0].message.content
        self.chat_history.append({"role": "assistant", "content": response_content})
        logger.info(f"{self.__class__.__name__}:完成:执行对话")
        return WriterResponse(response_content=response_content, footnotes=footnotes)

    async def summarize(self) -> str:
        """
        总结对话内容
        """
        try:
            self.append_chat_history(
                {"role": "user", "content": "请简单总结以上完成什么任务取得什么结果:"}
            )
            # 获取历史消息用于本次对话
            response = await self.model.chat(
                history=self.chat_history, agent_name=self.__class__.__name__
            )
            self.append_chat_history(
                {"role": "assistant", "content": response.choices[0].message.content}
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"总结生成失败: {str(e)}")
            # 返回一个基础总结，避免完全失败
            return "由于网络原因无法生成详细总结，但已完成主要任务处理。"
