"""任务级用户输入队列，用于实时消息干预功能。

进程内存储，和 _active_tasks 一样的持久化级别：仅在任务运行期间有意义，
进程重启后任务本身也会中断，队列内容无需跨进程持久化。

该通道来自 WebSocket 且历史上无鉴权，push 侧做长度与容量约束，
防止恶意连接的超长注入与内存滥用（纵深防御）。
"""

import asyncio

# 单条插话内容的最大长度（字符），超出部分截断，防止超长提示词注入
MAX_USER_INPUT_CHARS = 4000
# 截断标记，附加在被截断内容末尾，提示下游这不是完整输入
TRUNCATION_SUFFIX = "…[已截断]"
# 每个任务队列的容量上限，满后丢弃新消息，防止内存滥用
MAX_QUEUE_SIZE = 20

_queues: dict[str, asyncio.Queue[str]] = {}


def get_queue(task_id: str) -> asyncio.Queue[str]:
    """获取（或创建）指定任务的用户输入队列。"""
    return _queues.setdefault(task_id, asyncio.Queue(maxsize=MAX_QUEUE_SIZE))


def push(task_id: str, content: str) -> bool:
    """向指定任务的队列追加一条用户输入。

    Args:
        task_id: 任务 ID。
        content: 用户插话内容，超过 MAX_USER_INPUT_CHARS 时截断。

    Returns:
        入队成功返回 True；队列已满被丢弃返回 False。
        现有调用点不强制处理返回值，保持签名向后兼容。
    """
    if len(content) > MAX_USER_INPUT_CHARS:
        content = content[:MAX_USER_INPUT_CHARS] + TRUNCATION_SUFFIX
    try:
        get_queue(task_id).put_nowait(content)
    except asyncio.QueueFull:
        return False
    return True


def pop_all(task_id: str) -> list[str]:
    """取出并清空指定任务当前排队的所有用户输入。"""
    queue = _queues.get(task_id)
    if not queue:
        return []
    messages = []
    while not queue.empty():
        messages.append(queue.get_nowait())
    return messages


def clear(task_id: str) -> None:
    """任务结束后清理队列，避免内存累积。"""
    _queues.pop(task_id, None)
