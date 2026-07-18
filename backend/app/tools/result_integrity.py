"""Structured result-freeze helpers used by the writer and paper preflight.

The module deliberately does not infer mathematical facts from prose.  A
``frozen_results.json`` file is an explicit hand-off from a successful code
execution/validation step to the writer.  Its numbers are therefore the only
computed numbers that a writer may use once the file is present.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any


FREEZE_FILENAMES = (
    "frozen_results.json",
    "result_freeze.json",
    "reports/frozen_numbers.json",  # compatible with skill 3a-result-freeze
)
FREEZE_SCHEMAS = {"mathmodel.result-freeze", "mathmodel.writer-result-freeze"}
FREEZE_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path(work_dir: str, relative_path: str) -> str | None:
    if not isinstance(relative_path, str) or not relative_path.strip():
        return None
    root = os.path.realpath(work_dir)
    candidate = os.path.realpath(os.path.join(root, relative_path))
    try:
        if os.path.commonpath((root, candidate)) != root:
            return None
    except ValueError:
        return None
    return candidate


def load_result_freeze(work_dir: str) -> dict[str, Any] | None:
    """Return the first valid-looking freeze document, or ``None`` if absent.

    The returned value includes only a relative ``_path`` helper.  Detailed
    schema errors are reported by :func:`validate_result_freeze`, so callers
    can distinguish a missing optional artifact from an invalid active one.
    """
    for relative_path in FREEZE_FILENAMES:
        path = os.path.join(work_dir, relative_path)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                document = json.load(handle)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {"_path": relative_path, "_invalid_json": True}
        if not isinstance(document, dict):
            return {"_path": relative_path, "_invalid_json": True}
        document = dict(document)
        document["_path"] = relative_path.replace("\\", "/")
        return document
    return None


def _metric_label(metric: dict[str, Any]) -> str:
    return str(metric.get("label") or metric.get("id") or "").strip()


def _metric_aliases(metric: dict[str, Any]) -> list[str]:
    aliases = [_metric_label(metric)]
    raw_aliases = metric.get("aliases", [])
    if isinstance(raw_aliases, list):
        aliases.extend(str(item).strip() for item in raw_aliases)
    return [item for item in dict.fromkeys(aliases) if item]


def validate_result_freeze(work_dir: str, document: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate schema, metric semantics and evidence hashes for a freeze."""
    document = document if document is not None else load_result_freeze(work_dir)
    if document is None:
        return {"active": False, "passed": True, "errors": [], "metrics": []}

    errors: list[dict[str, str]] = []
    if document.get("_invalid_json"):
        return {
            "active": True,
            "passed": False,
            "path": document.get("_path", "frozen_results.json"),
            "errors": [{"code": "freeze_unreadable", "detail": "冻结结果文件不是有效 JSON。"}],
            "metrics": [],
        }
    if document.get("schema") not in FREEZE_SCHEMAS or document.get("version") != FREEZE_VERSION:
        errors.append({"code": "freeze_schema_invalid", "detail": "冻结结果 schema 或版本无效。"})

    raw_metrics = document.get("metrics")
    metrics: list[dict[str, Any]] = []
    if not isinstance(raw_metrics, list) or not raw_metrics:
        errors.append({"code": "metrics_missing", "detail": "冻结结果必须含有非空 metrics。"})
    else:
        metric_ids: set[str] = set()
        for index, raw_metric in enumerate(raw_metrics):
            if not isinstance(raw_metric, dict):
                errors.append({"code": "metric_invalid", "detail": f"metrics[{index}] 不是对象。"})
                continue
            metric = dict(raw_metric)
            metric_id = str(metric.get("id", "")).strip()
            label = _metric_label(metric)
            if not metric_id or not label:
                errors.append({"code": "metric_identity_missing", "detail": f"metrics[{index}] 缺少 id 或 label。"})
            elif metric_id in metric_ids:
                errors.append({"code": "metric_duplicate", "detail": f"重复指标 id：{metric_id}。"})
            metric_ids.add(metric_id)
            if not isinstance(metric.get("value"), (int, float)) or isinstance(metric.get("value"), bool):
                errors.append({"code": "metric_value_invalid", "detail": f"指标 {metric_id or index} 的 value 必须是数值。"})
            if not str(metric.get("unit", "")).strip() or not str(metric.get("explanation", "")).strip():
                errors.append({"code": "metric_semantics_missing", "detail": f"指标 {metric_id or index} 缺少 unit 或 explanation。"})
            metrics.append(metric)

    sources = document.get("sources", [])
    if not isinstance(sources, list) or not sources:
        errors.append({"code": "sources_missing", "detail": "冻结结果必须包含可核验的来源文件。"})
    else:
        for index, source in enumerate(sources):
            if not isinstance(source, dict):
                errors.append({"code": "source_invalid", "detail": f"sources[{index}] 不是对象。"})
                continue
            relative_path = source.get("relative_path") or source.get("path")
            expected_hash = source.get("sha256")
            source_path = _safe_path(work_dir, str(relative_path or ""))
            if source_path is None:
                errors.append({"code": "source_path_invalid", "detail": f"sources[{index}] 路径无效。"})
                continue
            if not isinstance(expected_hash, str) or not _SHA256_RE.fullmatch(expected_hash):
                errors.append({"code": "source_hash_invalid", "detail": f"来源 {relative_path} 缺少有效 SHA-256。"})
                continue
            if not os.path.isfile(source_path):
                errors.append({"code": "source_missing", "detail": f"来源文件不存在：{relative_path}。"})
            elif _sha256(source_path) != expected_hash:
                errors.append({"code": "source_hash_changed", "detail": f"来源文件已变化：{relative_path}。"})

    return {
        "active": True,
        "passed": not errors,
        "path": document.get("_path", "frozen_results.json"),
        "errors": errors,
        "metrics": metrics,
        "document": document,
    }


def build_frozen_result_summary(work_dir: str, subtask_id: str | None = None) -> str:
    """Create the writer-only fact block from a validated result freeze.

    当传入 ``subtask_id`` 时，只输出该子任务自己的冻结指标（物理过滤），用于
    Writer 分节写作的子任务隔离：写 quesN 时看不到其它子任务的 frozen 指标。
    未指定 subtask_id（如 eda/敏感性/全局校验）时返回全部指标，保持原行为。
    """
    validation = validate_result_freeze(work_dir)
    if not validation["active"]:
        return ""
    if not validation["passed"]:
        details = "；".join(error["detail"] for error in validation["errors"])
        return (
            "【冻结结果状态：不可用】\n"
            f"{details}\n"
            "不得写入任何新的计算结论、最优参数或算法效果；应如实说明结果尚未通过可追溯性核验。"
        )

    document = validation["document"]
    target = str(subtask_id).lower() if subtask_id else None

    def _in_scope(metric: dict[str, Any]) -> bool:
        # 只排除“明确归属到其它子任务”的指标；无 subtask_id 的指标无法归属，
        # 放行（与非冻结 CSV 路径一致，避免误删无法归属的合法事实）。
        if target is None:
            return True
        own = str(metric.get("subtask_id", "")).lower()
        if not own:
            return True
        return own == target

    scoped_header = (
        f"【冻结结果事实（唯一数值来源，仅限本题 {subtask_id}）】"
        if target is not None
        else "【冻结结果事实（唯一数值来源）】"
    )
    lines = [
        scoped_header,
        f"冻结文件：{validation['path']}。正文、摘要、图题、结论中的计算结果只能使用下列指标；"
        "不得以代码手自然语言总结、图像目测或模型记忆补写其他数值。题面给定常量须明确标为题设，"
        "不能伪装成计算结果。",
    ]
    for metric in validation["metrics"]:
        if not _in_scope(metric):
            continue
        lines.append(
            f"- {metric['id']}：{_metric_label(metric)} = {metric['value']} {metric['unit']}"
            f"（{metric['explanation']}）"
        )
    for subtask in document.get("subtasks", []):
        if not isinstance(subtask, dict):
            continue
        if target is not None and str(subtask.get("id", "")).lower() != target:
            continue
        feasible = subtask.get("feasible")
        if feasible is False:
            identifier = subtask.get("id") or subtask.get("problem") or "当前子问题"
            lines.append(
                f"- {identifier}：当前执行结果不可行；禁止称其为最优方案、最优解或已满足目标。"
            )
    return "\n".join(lines)


def metric_aliases(metric: dict[str, Any]) -> list[str]:
    """Public, deterministic aliases used by the prose and figure checks."""
    return _metric_aliases(metric)
