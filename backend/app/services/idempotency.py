"""Idempotency support for POST /modeling.

Roadmap B-2: Idempotency-Key + normalized request hash.
Same key + same content -> replay original task_id (200 with idempotent_replay:true)
Same key + different content -> 409 Conflict
Different key -> new task.

Persistence: file under WORK_DIR_ROOT/.idempotency/ + optional Redis fallback.
Single worker assumption, file-level atomic replace is sufficient.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from app.utils.common_utils import WORK_DIR_ROOT
from app.utils.log_util import logger

STORE_DIRNAME = ".idempotency"
STORE_FILENAME = "keys.json"
LOCK_SUFFIX = ".lock"


def _store_dir() -> Path:
    return Path(WORK_DIR_ROOT) / STORE_DIRNAME


def _store_path() -> Path:
    return _store_dir() / STORE_FILENAME


def _ensure_store_dir() -> None:
    _store_dir().mkdir(parents=True, exist_ok=True)


def _load_store() -> dict[str, Any]:
    p = _store_path()
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"读取幂等存储失败: {type(exc).__name__}")
        return {}


def _save_store(data: dict[str, Any]) -> None:
    _ensure_store_dir()
    p = _store_path()
    fd, tmp = tempfile.mkstemp(prefix=STORE_FILENAME + ".", suffix=".tmp", dir=str(_store_dir()))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, p)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def build_request_hash(
    ques_all: str,
    comp_template: str,
    format_output: str,
    export_profile: str,
    file_hashes: list[str],
    guidance_hash: str | None = None,
) -> str:
    return _normalize_request_hash(ques_all, comp_template, format_output, export_profile, file_hashes, guidance_hash)


def _normalize_request_hash(
    ques_all: str,
    comp_template: str,
    format_output: str,
    export_profile: str,
    file_hashes: list[str],
    guidance_hash: str | None = None,
) -> str:
    parts = [
        (ques_all or "").strip(),
        comp_template or "",
        format_output or "",
        export_profile or "",
        guidance_hash or "",
    ]
    for h in sorted(file_hashes):
        parts.append(h)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def check_idempotency(
    idempotency_key: str | None,
    request_hash: str,
) -> tuple[str | None, str | None]:
    """Check existing mapping.

    Returns (existing_task_id, conflict_reason).
    - If no key or no store -> (None, None) => create new
    - If same key+same hash -> (task_id, None) => replay
    - If same key+different hash -> (None, reason) => 409
    """
    if not idempotency_key:
        return None, None
    key = idempotency_key.strip()
    if not key:
        return None, None
    # Validate key format (alphanumeric + -_ , 8-128 chars)
    if len(key) < 8 or len(key) > 128:
        return None, "Idempotency-Key 长度必须为 8-128"
    store = _load_store()
    entry = store.get(key)
    if entry is None:
        return None, None
    if not isinstance(entry, dict):
        return None, None
    stored_hash = entry.get("request_hash")
    stored_task = entry.get("task_id")
    if stored_hash == request_hash and isinstance(stored_task, str) and stored_task:
        # Verify task still exists (work_dir may have been cleaned)
        work_dir = Path(WORK_DIR_ROOT) / stored_task
        if work_dir.is_dir():
            return stored_task, None
        # Stale entry, treat as not found
        return None, None
    return None, f"Idempotency-Key 已用于不同内容的请求（原任务 {stored_task}）"


def record_idempotency(
    idempotency_key: str | None,
    request_hash: str,
    task_id: str,
) -> None:
    if not idempotency_key:
        return
    key = idempotency_key.strip()
    if not key or len(key) < 8 or len(key) > 128:
        return
    store = _load_store()
    store[key] = {
        "task_id": task_id,
        "request_hash": request_hash,
        "created_at": datetime.datetime.now().isoformat(),
    }
    # Keep at most 1000 entries (LRU by created_at)
    if len(store) > 1000:
        sorted_items = sorted(store.items(), key=lambda x: x[1].get("created_at", ""))
        for k, _ in sorted_items[: len(store) - 1000]:
            store.pop(k, None)
    _save_store(store)


def compute_file_hashes(file_infos: list[dict[str, Any]]) -> list[str]:
    return [f"{info.get('name')}:{info.get('sha256')}" for info in file_infos if info.get("sha256")]


def compute_guidance_hash(guidance_content: str | None) -> str | None:
    if not guidance_content or not guidance_content.strip():
        return None
    return hashlib.sha256(guidance_content.strip().encode("utf-8")).hexdigest()[:16]
