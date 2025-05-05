import json
from app.core.llm import LLM
from app.core.prompts import (
    get_completion_check_prompt,
    get_reflection_prompt,
    get_writer_prompt,
    CODER_PROMPT,
    MODELER_PROMPT,
)
from app.core.functions import tools
from app.models.model import CoderToWriter
from app.models.user_output import UserOutput
from app.utils.enums import CompTemplate, FormatOutPut
from app.utils.log_util import logger
from app.config.setting import settings
from app.utils.common_utils import get_current_files
from app.utils.redis_manager import redis_manager
from app.schemas.response import SystemMessage
from app.tools.base_interpreter import BaseCodeInterpreter


class Agent:
    def __init__(
        self,
        task_id: str,
        model: LLM,
        max_chat_turns: int = 30,  # 单个agent最大对话轮次
        user_output: UserOutput = None,
    ) -> None:
        self.task_id = task_id
        self.model = model
        self.chat_history: list[dict] = []  # 存储对话历史
        self.max_chat_turns = max_chat_turns  # 最大对话轮次
        self.current_chat_turns = 0  # 当前对话轮次计数器
        self.user_output = user_output

    async def run(self, prompt: str, system_prompt: str, sub_title: str) -> str:
        """
        执行agent的对话并返回结果和总结

        Args:
            prompt: 输入的提示

        Returns:
            str: 模型的响应
        """
        try:
            logger.info(f"{self.__class__.__name__}:开始:执行对话")
            self.current_chat_turns = 0  # 重置对话轮次计数器

            # 更新对话历史
            self.append_chat_history({"role": "system", "content": system_prompt})
            self.append_chat_history({"role": "user", "content": prompt})

            # 获取历史消息用于本次对话
            response = await self.model.chat(
                history=self.chat_history,
                agent_name=self.__class__.__name__,
                sub_title=sub_title,
            )
            response_content = response.choices[0].message.content
            self.chat_history.append({"role": "assistant", "content": response_content})
            logger.info(f"{self.__class__.__name__}:完成:执行对话")
            return response_content
        except Exception as e:
            error_msg = f"执行过程中遇到错误: {str(e)}"
            logger.error(f"Agent执行失败: {str(e)}")
            return error_msg

    def append_chat_history(self, msg: dict) -> None:
        self.chat_history.append(msg)
        # self.user_output.data_recorder.append_chat_history(
        # msg, agent_name=self.__class__.__name__
        # )


class ModelerAgent(Agent):  # 继承自Agent类而不是BaseModel
    def __init__(
        self,
        model: LLM,
        max_chat_turns: int = 30,  # 添加最大对话轮次限制
    ) -> None:
        super().__init__(model, max_chat_turns)
        self.system_prompt = MODELER_PROMPT


# 代码强
class CoderAgent(Agent):  # 同样继承自Agent类
    def __init__(
        self,
        task_id: str,
        model: LLM,
        work_dir: str,  # 工作目录
        max_chat_turns: int = settings.MAX_CHAT_TURNS,  # 最大聊天次数
        max_retries: int = settings.MAX_RETRIES,  # 最大反思次数
        code_interpreter: BaseCodeInterpreter = None,
    ) -> None:
        super().__init__(task_id, model, max_chat_turns)
        self.work_dir = work_dir
        self.max_retries = max_retries
        self.is_first_run = True
        self.system_prompt = CODER_PROMPT
        self.code_interpreter = code_interpreter

    async def run(self, prompt: str, subtask_title: str) -> CoderToWriter:
        logger.info(f"{self.__class__.__name__}:开始:执行子任务: {subtask_title}")
        self.code_interpreter.add_section(subtask_title)

        # 如果是第一次运行，则添加系统提示
        if self.is_first_run:
            logger.info("首次运行，添加系统提示和数据集文件信息")
            self.is_first_run = False
            self.append_chat_history({"role": "system", "content": self.system_prompt})
            # 当前数据集文件
            self.append_chat_history(
                {
                    "role": "user",
                    "content": f"当前文件夹下的数据集文件{get_current_files(self.work_dir, 'data')}",
                }
            )

        # 添加 sub_task
        logger.info(f"添加子任务提示: {prompt}")
        self.append_chat_history({"role": "user", "content": prompt})

        retry_count = 0
        last_error_message = ""
        task_completed = False

        if self.current_chat_turns >= self.max_chat_turns:
            logger.error(f"超过最大聊天次数: {self.max_chat_turns}")
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="超过最大聊天次数", type="error"),
            )
            raise Exception(
                f"Reached maximum number of chat turns ({self.max_chat_turns}). Task incomplete."
            )

        if retry_count >= self.max_retries:
            logger.error(f"超过最大尝试次数: {self.max_retries}")
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(content="超过最大尝试次数", type="error"),
            )
            raise Exception(
                f"Failed to complete task after {self.max_retries} attempts. Last error: {last_error_message}"
            )

        # try:
        while (
            not task_completed
            and retry_count < self.max_retries
            and self.current_chat_turns < self.max_chat_turns
        ):
            self.current_chat_turns += 1
            logger.info(f"当前对话轮次: {self.current_chat_turns}")
            response = await self.model.chat(
                history=self.chat_history,
                tools=tools,
                tool_choice="auto",
                agent_name=self.__class__.__name__,
            )

            # 如果有工具调用
            if (
                hasattr(response.choices[0].message, "tool_calls")
                and response.choices[0].message.tool_calls
            ):
                logger.info("检测到工具调用")
                tool_call = response.choices[0].message.tool_calls[0]
                tool_id = tool_call.id
                # TODO: json JSON解析时遇到了无效的转义字符
                if tool_call.function.name == "execute_code":
                    logger.info(f"调用工具: {tool_call.function.name}")
                    await redis_manager.publish_message(
                        self.task_id,
                        SystemMessage(
                            content=f"代码手调用{tool_call.function.name}工具"
                        ),
                    )
                    code = json.loads(tool_call.function.arguments)["code"]
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
                                        "name": "execute_code",
                                        "arguments": json.dumps({"code": code}),
                                    },
                                }
                            ],
                        }
                    )

                    # 执行工具调用
                    logger.info("执行工具调用")
                    (
                        text_to_gpt,
                        error_occurred,
                        error_message,
                    ) = await self.code_interpreter.execute_code(code)

                    # 记录执行结果

                    # 添加工具执行结果
                    self.append_chat_history(
                        {
                            "role": "tool",
                            "content": text_to_gpt,
                            "tool_call_id": tool_id,
                        }
                    )
                    # 代码执行错误
                    if error_occurred:
                        logger.warning(f"代码执行错误: {error_message}")
                        retry_count += 1
                        logger.info(f"当前尝试次:{retry_count} / {self.max_retries}")
                        last_error_message = error_message
                        reflection_prompt = get_reflection_prompt(error_message, code)

                        await redis_manager.publish_message(
                            self.task_id,
                            SystemMessage(content="代码手反思错误", type="error"),
                        )

                        self.append_chat_history(
                            {"role": "user", "content": reflection_prompt}
                        )
                        # 如果代码出错，返回重新开始
                        continue

                    # 检查任务完成情况时也计入对话轮次
                    self.current_chat_turns += 1
                    logger.info(
                        f"当前对话轮次: {self.current_chat_turns} / {self.max_chat_turns}"
                    )
                    # 使用所有执行结果生成检查提示
                    logger.info("判断是否完成")

                    completion_check_prompt = get_completion_check_prompt(
                        prompt, text_to_gpt
                    )
                    self.append_chat_history(
                        {"role": "user", "content": completion_check_prompt}
                    )

                    completion_response = await self.model.chat(
                        history=self.chat_history,
                        tools=tools,
                        tool_choice="auto",
                        agent_name=self.__class__.__name__,
                    )

                    # # TODO: 压缩对话历史

                    ## 没有调用工具，代表已经完成了
                    if not (
                        hasattr(completion_response.choices[0].message, "tool_calls")
                        and completion_response.choices[0].message.tool_calls
                    ):
                        logger.info("没有调用工具，代表任务已完成")
                        task_completed = True
                        return completion_response.choices[0].message.content
            else:
                logger.info("没有工具，代表任务完成")

            if retry_count >= self.max_retries:
                logger.error(f"超过最大尝试次数: {self.max_retries}")
                return f"Failed to complete task after {self.max_retries} attempts. Last error: {last_error_message}"

            if self.current_chat_turns >= self.max_chat_turns:
                logger.error(f"超过最大对话轮次: {self.max_chat_turns}")
                return f"Reached maximum number of chat turns ({self.max_chat_turns}). Task incomplete."

        logger.info(f"{self.__class__.__name__}:完成:执行子任务: {subtask_title}")

        return response.choices[0].message.content


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
    ) -> None:
        super().__init__(task_id, model, max_chat_turns, user_output)
        self.format_out_put = format_output
        self.comp_template = comp_template
        self.system_prompt = get_writer_prompt(format_output)
        self.available_images: list[str] = []

    async def run(
        self,
        prompt: str,
        available_images: list[str] = None,
        sub_title: str = None,
    ) -> str:
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
            prompt = prompt + image_prompt

        return await super().run(prompt, self.system_prompt, sub_title)

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
