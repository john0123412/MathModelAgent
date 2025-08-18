from app.core.agents.agent import Agent
from app.core.llm.llm import LLM
from app.core.prompts import COORDINATOR_PROMPT
import json
import re
from app.utils.log_util import logger
from app.schemas.A2A import CoordinatorToModeler


class CoordinatorAgent(Agent):
    def __init__(
        self,
        task_id: str,
        model: LLM,
        max_chat_turns: int = 30,
    ) -> None:
        super().__init__(task_id, model, max_chat_turns)
        self.system_prompt = COORDINATOR_PROMPT

    async def run(self, ques_all: str) -> CoordinatorToModeler:
        """用户输入问题 使用LLM 格式化 questions"""
        await self.append_chat_history(
            {"role": "system", "content": self.system_prompt}
        )
        await self.append_chat_history({"role": "user", "content": ques_all})

        response = await self.model.chat(
            history=self.chat_history,
            agent_name=self.__class__.__name__,
        )
        json_str = response.choices[0].message.content

        # if not json_str.startswith("```json"):
        #     logger.info(f"拒绝回答用户非数学建模请求:{json_str}")
        #     raise ValueError(f"拒绝回答用户非数学建模请求:{json_str}")

        # 清理 JSON 字符串
        json_str = json_str.replace("```json", "").replace("```", "").strip()
        # 移除可能的控制字符
        json_str = re.sub(r"[\x00-\x1F\x7F]", "", json_str)

        if not json_str:
            raise ValueError("返回的 JSON 字符串为空，请检查输入内容。")

        try:
            questions = json.loads(json_str)
            ques_count = questions["ques_count"]
            logger.info(f"questions:{questions}")
            return CoordinatorToModeler(questions=questions, ques_count=ques_count)
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析错误，原始字符串: {json_str}")
            logger.error(f"错误详情: {str(e)}")
            raise ValueError(f"JSON 解析错误: {e}")
