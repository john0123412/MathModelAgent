import json
from app.utils.common_utils import transform_link
from app.utils.log_util import logger
import time
from app.schemas.response import (
    CoderMessage,
    WriterMessage,
    ModelerMessage,
    SystemMessage,
    CoordinatorMessage,
)
from app.services.redis_manager import redis_manager
from litellm import acompletion
import litellm
from app.schemas.enums import AgentType


class LLM:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        task_id: str,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.chat_count = 0
        self.max_tokens: int | None = None  # 添加最大token数限制
        self.task_id = task_id

    async def chat(
        self,
        history: list = None,
        tools: list = None,
        tool_choice: str = None,
        max_retries: int = 8,  # 添加最大重试次数
        retry_delay: float = 1.0,  # 添加重试延迟
        top_p: float | None = None,  # 添加top_p参数,
        agent_name: AgentType = AgentType.SYSTEM,  # CoderAgent or WriterAgent
        sub_title: str | None = None,
    ) -> str:
        logger.info(f"subtitle是:{sub_title}")

        kwargs = {
            "api_key": self.api_key,
            "model": self.model,
            "messages": history,
            "stream": False,
            "top_p": top_p,
        }

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        if self.max_tokens:
            kwargs["max_tokens"] = self.max_tokens

        if self.base_url:
            kwargs["base_url"] = self.base_url

        # TODO: stream 输出
        for attempt in range(max_retries):
            try:
                # completion = self.client.chat.completions.create(**kwargs)
                response = await acompletion(**kwargs)
                logger.info(f"API返回: {response}")
                if not response or not hasattr(response, "choices"):
                    raise ValueError("无效的API响应")
                self.chat_count += 1
                await self.send_message(response, agent_name, sub_title)
                return response
            except (json.JSONDecodeError, litellm.InternalServerError) as e:
                logger.error(f"第{attempt + 1}次重试: {str(e)}")
                if attempt < max_retries - 1:  # 如果不是最后一次尝试
                    time.sleep(retry_delay * (attempt + 1))  # 指数退避
                    continue
                logger.debug(f"请求参数: {kwargs}")
                raise  # 如果所有重试都失败，则抛出异常

    async def send_message(self, response, agent_name, sub_title=None):
        logger.info(f"subtitle是:{sub_title}")
        content = response.choices[0].message.content

        match agent_name:
            case AgentType.CODER:
                agent_msg: CoderMessage = CoderMessage(content=content)
            case AgentType.WRITER:
                # 处理 Markdown 格式的图片语法
                content = transform_link(self.task_id, content)
                agent_msg: WriterMessage = WriterMessage(
                    content=content,
                    sub_title=sub_title,
                )
            case AgentType.MODELER:
                agent_msg: ModelerMessage = ModelerMessage(content=content)
            case AgentType.SYSTEM:
                agent_msg: SystemMessage = SystemMessage(content=content)
            case AgentType.COORDINATOR:
                agent_msg: CoordinatorMessage = CoordinatorMessage(content=content)
            case _:
                raise ValueError(f"不支持的agent类型: {agent_name}")

        await redis_manager.publish_message(
            self.task_id,
            agent_msg,
        )


# class DeepSeekModel(LLM):
#     def __init__(
#         self,
#         api_key: str,
#         model: str,
#         base_url: str,
#         task_id: str,
#     ):
#         super().__init__(api_key, model, base_url, task_id)
# self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)


async def simple_chat(model: LLM, history: list) -> str:
    """
    Description of the function.

    Args:
        model (LLM): 模型
        history (list): 构造好的历史记录（包含system_prompt,user_prompt）

    Returns:
        return_type: Description of the return value.
    """
    kwargs = {
        "api_key": model.api_key,
        "model": model.model,
        "messages": history,
        "stream": False,
    }

    if model.base_url:
        kwargs["base_url"] = model.base_url

    response = await acompletion(**kwargs)

    return response.choices[0].message.content
