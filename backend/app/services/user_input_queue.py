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
_WORKFLOW_TARGETS: frozenset[str] = frozenset(
    {"coordinator", "modeler", "coder", "writer"}
)


class QueuedGuidance(TypedDict):
    """An in-memory advisory message addressed to one workflow role or all roles."""

    content: str
    target: GuidanceTarget
    # Broadcast records keep one bounded queue item and mutate this set as
    # roles consume it.  Targeted records use an empty set.
    remaining_targets: set[str]
    guidance_id: str | None


_queues: dict[str, asyncio.Queue[QueuedGuidance]] = {}


def get_queue(task_id: str) -> asyncio.Queue[QueuedGuidance]:
    """获取（或创建）指定任务的用户输入队列。"""
    return _queues.setdefault(task_id, asyncio.Queue(maxsize=MAX_QUEUE_SIZE))


def normalize_content(content: str) -> str:
    """Apply the shared length boundary before queuing or auditing guidance."""
    if len(content) > MAX_USER_INPUT_CHARS:
        return content[:MAX_USER_INPUT_CHARS] + TRUNCATION_SUFFIX
    return content


def push(task_id: str, content: str, target: GuidanceTarget = "all", guidance_id: str | None = None) -> bool:
    """向指定任务的队列追加一条用户输入。

    Args:
        task_id: 任务 ID。
        content: 用户插话内容，超过 MAX_USER_INPUT_CHARS 时截断。
        target: 接收角色；``all`` 会分别在每个角色的下一次模型调用前投递。
        guidance_id: 可选的客户端幂等键，用于重启后去重与回执查询。

    Returns:
        入队成功返回 True；队列已满被丢弃返回 False。
        现有调用点不强制处理返回值，保持签名向后兼容。
    """
    if target not in _KNOWN_TARGETS:
        return False
    content = normalize_content(content)
    # P1-6: same guidance_id with different content must conflict, not silently accept
    if guidance_id:
        existing = get_guidance_receipt(task_id, guidance_id)
        if existing is not None:
            existing_hash = existing.get("content_hash")
            import hashlib as _hl

            cur_hash = _hl.sha256(content.encode("utf-8")).hexdigest()[:16]
            if existing_hash != cur_hash:
                # Conflict: same ID, different content
                return False
            # Same content, already accepted/consumed, do not duplicate queue entry
            # But ensure in-memory queue still has it if not yet consumed (restart recovery)
            if existing.get("status") == "accepted":
                # Try to ensure queue has it (restart case where memory lost)
                _ensure_queue_has_guidance(task_id, guidance_id)
            return True
    try:
        remaining_targets = (
            set(_WORKFLOW_TARGETS) if target == "all" else set()
        )
        get_queue(task_id).put_nowait(
            {
                "content": content,
                "target": target,
                "remaining_targets": remaining_targets,
                "guidance_id": guidance_id,
            }
        )
        if guidance_id:
            import hashlib

            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
            store_guidance_receipt(task_id, guidance_id, target, content, content_hash, remaining_targets, status="accepted")
    except asyncio.QueueFull:
        return False
    return True


def _ensure_queue_has_guidance(task_id: str, guidance_id: str) -> None:
    """Restart recovery: if guidance is accepted but not in memory, re-queue it."""
    queue = _queues.get(task_id)
    if queue is not None and not queue.empty():
        # Check if already in queue
        for item in list(queue._queue):  # type: ignore[attr-defined]
            if item.get("guidance_id") == guidance_id:
                return
    # Not in memory, load from store and re-queue
    store = _load_guidance_store(task_id)
    entry = store.get(guidance_id)
    if entry and entry.get("status") == "accepted":
        content = entry.get("content", "")
        target = entry.get("target", "all")
        remaining = set(entry.get("remaining_targets", []))
        if not remaining and target == "all":
            remaining = set(_WORKFLOW_TARGETS)
        # Do not re-store, just queue
        try:
            get_queue(task_id).put_nowait(
                {
                    "content": content,
                    "target": target,
                    "remaining_targets": remaining,
                    "guidance_id": guidance_id,
                }
            )
        except asyncio.QueueFull:
            pass


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
    """Return only guidance for ``target`` while preserving other roles' advice."""
    # P1-6: rehydrate from persistent store if in-memory queue is empty but store has pending
    queue = _queues.get(task_id)
    if not queue or queue.empty():
        # Try to restore pending guidance from store
        store = _load_guidance_store(task_id)
        for gid, entry in store.items():
            if entry.get("status") != "accepted":
                continue
            # Check if already in queue
            already = False
            if queue:
                for item in list(queue._queue):  # type: ignore[attr-defined]
                    if item.get("guidance_id") == gid:
                        already = True
                        break
            if already:
                continue
            content = entry.get("content", "")
            tgt = entry.get("target", "all")
            remaining = set(entry.get("remaining_targets", []))
            if not remaining and tgt == "all":
                remaining = set(_WORKFLOW_TARGETS)
            if target in remaining or tgt == target or tgt == "all":
                try:
                    get_queue(task_id).put_nowait(
                        {
                            "content": content,
                            "target": tgt,
                            "remaining_targets": remaining,
                            "guidance_id": gid,
                        }
                    )
                except asyncio.QueueFull:
                    pass
        queue = _queues.get(task_id)
        if not queue:
            return []

    matched: list[str] = []
    retained: list[QueuedGuidance] = []
    consumed_ids: list[str] = []
    # Track broadcast partial consumption to update store
    broadcast_updates: dict[str, set[str]] = {}
    while not queue.empty():
        item = queue.get_nowait()
        item_target = item["target"]
        if item_target == target:
            matched.append(item["content"])
            if item.get("guidance_id"):
                consumed_ids.append(item["guidance_id"])  # type: ignore[arg-type]
        elif item_target == "all":
            remaining = set(item.get("remaining_targets", _WORKFLOW_TARGETS))
            if target in remaining:
                matched.append(item["content"])
                remaining.remove(target)
                # Track partial consumption for store
                if item.get("guidance_id"):
                    gid = item["guidance_id"]  # type: ignore[assignment]
                    broadcast_updates[gid] = remaining
            if remaining:
                item["remaining_targets"] = remaining
                retained.append(item)
            else:
                if item.get("guidance_id"):
                    consumed_ids.append(item["guidance_id"])  # type: ignore[arg-type]
        else:
            retained.append(item)

    for item in retained:
        queue.put_nowait(item)
    # Update store for broadcast partial consumption
    for gid, remaining in broadcast_updates.items():
        try:
            store = _load_guidance_store(task_id)
            entry = store.get(gid)
            if entry:
                entry["remaining_targets"] = sorted(remaining)
                # If still has remaining, keep status accepted, else mark consumed via mark_guidance_consumed
                if not remaining:
                    entry["status"] = "consumed"
                    entry["consumed_at"] = __import__("datetime").datetime.now().isoformat()
                _save_guidance_store(task_id, store)
        except Exception:
            pass
    for gid in consumed_ids:
        try:
            mark_guidance_consumed(task_id, gid)
        except Exception:
            pass
    return matched


def _guidance_store_path(task_id: str) -> str:
    from app.utils.common_utils import get_work_dir
    import os

    try:
        work_dir = get_work_dir(task_id)
    except FileNotFoundError:
        return ""
    return os.path.join(work_dir, "guidance_store.json")


def _load_guidance_store(task_id: str) -> dict:
    import json
    import os

    path = _guidance_store_path(task_id)
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_guidance_store(task_id: str, store: dict) -> None:
    import json
    import os
    import tempfile

    path = _guidance_store_path(task_id)
    if not path:
        return
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix="guidance_store.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def store_guidance_receipt(
    task_id: str,
    guidance_id: str,
    target: str,
    content: str,
    content_hash: str,
    remaining_targets: set[str] | None = None,
    status: str = "accepted",
) -> None:
    """Persist guidance receipt for restart safety (roadmap B-2, P1-6)."""
    if not guidance_id:
        return
    store = _load_guidance_store(task_id)
    if guidance_id in store:
        existing = store[guidance_id]
        # Same ID, different content -> keep original, caller will have returned False
        if existing.get("content_hash") != content_hash:
            return
        return
    store[guidance_id] = {
        "target": target,
        "content": content,
        "content_hash": content_hash,
        "remaining_targets": sorted(remaining_targets) if remaining_targets else [],
        "status": status,
        "created_at": __import__("datetime").datetime.now().isoformat(),
    }
    _save_guidance_store(task_id, store)


def mark_guidance_consumed(task_id: str, guidance_id: str) -> None:
    store = _load_guidance_store(task_id)
    entry = store.get(guidance_id)
    if entry and entry.get("status") == "accepted":
        entry["status"] = "consumed"
        entry["consumed_at"] = __import__("datetime").datetime.now().isoformat()
        _save_guidance_store(task_id, store)


def get_guidance_receipt(task_id: str, guidance_id: str) -> dict | None:
    store = _load_guidance_store(task_id)
    return store.get(guidance_id)


def clear(task_id: str) -> None:
    """任务结束后清理队列，避免内存累积。"""
    _queues.pop(task_id, None)
    # Keep guidance_store.json for audit, do not delete
