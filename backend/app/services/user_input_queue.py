"""任务级用户输入队列，用于实时消息干预功能。

进程内存储，和 _active_tasks 一样的持久化级别：仅在任务运行期间有意义，
进程重启后任务本身也会中断，队列内容无需跨进程持久化。

该通道来自 WebSocket 且历史上无鉴权，push 侧做长度与容量约束，
防止恶意连接的超长注入与内存滥用（纵深防御）。
"""

import asyncio
from typing import Literal, TypedDict

# 单条插话内容的最大长度（字符），超出部分截断，防止超长提示词注入
MAX_USER_INPUT_CHARS = 4000
# 截断标记，附加在被截断内容末尾，提示下游这不是完整输入
TRUNCATION_SUFFIX = "…[已截断]"
# 每个任务队列的容量上限，满后丢弃新消息，防止内存滥用
MAX_QUEUE_SIZE = 20

GuidanceTarget = Literal["coordinator", "modeler", "coder", "writer", "all"]
_KNOWN_TARGETS: set[str] = {"coordinator", "modeler", "coder", "writer", "all"}


class QueuedGuidance(TypedDict):
    """An in-memory advisory message addressed to one workflow role or all roles."""

    content: str
    target: GuidanceTarget


_queues: dict[str, asyncio.Queue[QueuedGuidance]] = {}


def get_queue(task_id: str) -> asyncio.Queue[QueuedGuidance]:
    """获取（或创建）指定任务的用户输入队列。"""
    return _queues.setdefault(task_id, asyncio.Queue(maxsize=MAX_QUEUE_SIZE))


def normalize_content(content: str) -> str:
    """Apply the shared length boundary before queuing or auditing guidance."""
    if len(content) > MAX_USER_INPUT_CHARS:
        return content[:MAX_USER_INPUT_CHARS] + TRUNCATION_SUFFIX
    return content


def push(task_id: str, content: str, target: GuidanceTarget = "all") -> bool:
    """向指定任务的队列追加一条用户输入。

    Args:
        task_id: 任务 ID。
        content: 用户插话内容，超过 MAX_USER_INPUT_CHARS 时截断。
        target: 接收角色；``all`` 会分别在每个角色的下一次模型调用前投递。

    Returns:
        入队成功返回 True；队列已满被丢弃返回 False。
        现有调用点不强制处理返回值，保持签名向后兼容。
    """
    if target not in _KNOWN_TARGETS:
        return False
    content = normalize_content(content)
    try:
        get_queue(task_id).put_nowait({"content": content, "target": target})
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
        messages.append(queue.get_nowait()["content"])
    return messages


def pop_for(task_id: str, target: GuidanceTarget) -> list[str]:
    """Return only guidance for ``target`` while preserving other roles' advice.

    A broadcast entry is copied to each role logically: it stays in the queue
    until every normal workflow role has consumed it. This avoids the previous
    race in which the coordinator could accidentally consume advice intended
    for the Coder.
    """
    queue = _queues.get(task_id)
    if not queue:
        return []

    matched: list[str] = []
    retained: list[QueuedGuidance] = []
    while not queue.empty():
        item = queue.get_nowait()
        item_target = item["target"]
        if item_target == target:
            matched.append(item["content"])
        elif item_target == "all":
            matched.append(item["content"])
            # Keep a separate remaining-recipient entry rather than letting
            # whichever role runs first consume a broadcast instruction.
            for other_target in _KNOWN_TARGETS - {"all", target}:
                retained.append({"content": item["content"], "target": other_target})
        else:
            retained.append(item)

    for item in retained:
        queue.put_nowait(item)
    return matched


def clear(task_id: str) -> None:
    """任务结束后清理队列，避免内存累积。"""
    _queues.pop(task_id, None)
