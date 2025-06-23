from app.core.llm.llm import LLM, simple_chat
from app.utils.log_util import logger


class Agent:
    def __init__(
        self,
        task_id: str,
        model: LLM,
        max_chat_turns: int = 30,  # 单个agent最大对话轮次
        max_memory: int = 25,  # 最大记忆轮次
    ) -> None:
        self.task_id = task_id
        self.model = model
        self.chat_history: list[dict] = []  # 存储对话历史
        self.max_chat_turns = max_chat_turns  # 最大对话轮次
        self.current_chat_turns = 0  # 当前对话轮次计数器
        self.max_memory = max_memory  # 最大记忆轮次

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
            await self.append_chat_history({"role": "system", "content": system_prompt})
            await self.append_chat_history({"role": "user", "content": prompt})

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

    async def append_chat_history(self, msg: dict) -> None:
        await self.clear_memory()
        self.chat_history.append(msg)

    async def clear_memory(self):
        """当聊天历史超过最大记忆轮次时，使用 simple_chat 进行总结压缩"""
        if len(self.chat_history) <= self.max_memory:
            return

        logger.info(
            f"{self.__class__.__name__}:开始清除记忆，当前记录数：{len(self.chat_history)}"
        )

        try:
            # 保留第一条系统消息
            system_msg = (
                self.chat_history[0]
                if self.chat_history and self.chat_history[0]["role"] == "system"
                else None
            )

            # 构造总结提示
            summarize_history = []
            if system_msg:
                summarize_history.append(system_msg)

            # 添加要总结的对话内容（跳过第一条系统消息和最后5条消息）
            start_idx = 1 if system_msg else 0
            end_idx = len(self.chat_history) - 5

            if end_idx > start_idx:
                summarize_history.append(
                    {
                        "role": "user",
                        "content": f"请简洁总结以下对话的关键内容和重要结论，保留重要的上下文信息：\n\n{self._format_history_for_summary(self.chat_history[start_idx:end_idx])}",
                    }
                )

                # 调用 simple_chat 进行总结
                summary = await simple_chat(self.model, summarize_history)

                # 重构聊天历史：系统消息 + 总结 + 最后5条消息
                new_history = []
                if system_msg:
                    new_history.append(system_msg)

                new_history.append(
                    {"role": "assistant", "content": f"[历史对话总结] {summary}"}
                )

                # 添加最后5条消息
                new_history.extend(self.chat_history[-5:])

                self.chat_history = new_history
                logger.info(
                    f"{self.__class__.__name__}:记忆清除完成，压缩至：{len(self.chat_history)}条记录"
                )
            else:
                logger.info(f"{self.__class__.__name__}:无需清除记忆，记录数量合理")

        except Exception as e:
            logger.error(f"记忆清除失败，使用简单切片策略: {str(e)}")
            # 如果总结失败，回退到简单的切片策略
            self.chat_history = self.chat_history[:2] + self.chat_history[-5:]

    def _format_history_for_summary(self, history: list[dict]) -> str:
        """格式化历史记录用于总结"""
        formatted = []
        for msg in history:
            role = msg["role"]
            content = (
                msg["content"][:500] + "..."
                if len(msg["content"]) > 500
                else msg["content"]
            )  # 限制长度
            formatted.append(f"{role}: {content}")
        return "\n".join(formatted)
