"""代码手 Agent 模块，负责生成和执行 Python 代码完成建模任务。"""

import asyncio
import ast
import datetime
import hashlib
import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Callable

from nbformat import v4 as nbf
from app.core.agents.agent import Agent
from app.core.checkpoint import CheckpointManager
from app.config.setting import settings, ApiType
from app.utils.log_util import logger
from app.services.redis_manager import redis_manager
from app.schemas.response import SystemMessage, InterpreterMessage
from app.tools.base_interpreter import BaseCodeInterpreter
from app.core.llm.llm import LLM
from app.schemas.A2A import CoderToWriter
from app.core.prompts import CODER_PROMPT
from app.utils.common_utils import get_current_files
from app.core.prompts import get_reflection_prompt
from app.core.functions import coder_tools, coder_tools_anthropic
from app.tools.execution_validation import record_execution_evidence
from app.tools.json_repair import repair_json
from app.tools.result_integrity import validate_result_freeze


class ProtectedFileSnapshotError(RuntimeError):
    """受保护文件快照阶段失败异常（严格 fail-closed，禁止进入模型重试）。"""


class ProtectedFileRecoveryError(RuntimeError):
    """受保护文件恢复/清理阶段失败异常（严格 fail-closed，禁止进入模型重试）。"""


class ProtectedFileTamperError(RuntimeError):
    """代码非法篡改受保护文件异常（严格 fail-closed，禁止静默或循环返修）。"""


# TODO: 时间等待过久，stop 进程
# TODO: 支持 cuda
# TODO: 引入创新方案：

_FINAL_OUTPUT_MARKERS = (
    "项目完成",
    "任务完成",
    "交付完成",
    "所有文件已生成",
    "所有文件均已生成",
    "最终完成",
    "核心输出",
)

_PARENT_PATH_PATTERN = re.compile(r"(^|[\\/])\.\.([\\/]|$)")
_WORK_DIR_PATH_PATTERN = re.compile(
    r"(^|[\\/])(?:backend[\\/])?project[\\/]work_dir([\\/]|$)"
)
_FORMAL_SUBTASK_PATTERN = re.compile(r"^(ques[1-9][0-9]*)(?:_repair)?$")
_EVIDENCE_FAILURE_LIMIT = 3
_CLOSEOUT_WARNING_REMAINING_CALLS = 2
_CONSECUTIVE_AGENT_EXCEPTION_LIMIT = 2


def _looks_like_final_tool_output(output: str) -> bool:
    """判断工具输出是否明显是收尾总结，避免模型反复生成完成证书/总结。"""
    if not output:
        return False
    return any(marker in output for marker in _FINAL_OUTPUT_MARKERS)


def _evaluate_string_expr(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _evaluate_string_expr(node.left)
        right = _evaluate_string_expr(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        parts = []
        for val_node in node.values:
            part = _evaluate_string_expr(val_node)
            if part is not None:
                parts.append(part)
        if parts:
            return "".join(parts)
    return None


def _iter_string_literals(code: str):
    try:
        tree = ast.parse(code)
    except SyntaxError:
        yield code
        return
    for node in ast.walk(tree):
        val = _evaluate_string_expr(node)
        if val is not None:
            yield val


_PROTECTED_TASK_FILES = {
    "evidence_failure_budget.json",
    "checkpoint.json",
    "variable_snapshot.pkl",
    "variable_snapshot_meta.json",
    "frozen_results.json",
    "input_manifest.json",
    "task_status.json",
    "problem_contract.json",
    "modeler_plan.json",
}


def _find_cross_task_path(code: str) -> str | None:
    """检测模型生成代码是否试图读取当前任务目录之外的历史任务文件或篡改受保护文件。"""
    for value in _iter_string_literals(code):
        normalized = value.replace("\\", "/")
        if _PARENT_PATH_PATTERN.search(normalized):
            return value
        if _WORK_DIR_PATH_PATTERN.search(normalized):
            return value
        base_name = os.path.basename(normalized.rstrip("/"))
        if base_name in _PROTECTED_TASK_FILES:
            return value
    for protected in _PROTECTED_TASK_FILES:
        stem = protected.split(".")[0]
        if stem in code:
            return stem
    return None


def _read_evidence_failure_file(
    budget_file: Path,
    subtask_id: str,
    task_id: str = "",
    plan_sha256: str = "",
) -> int:
    """读取并严格校验预算文件（fail-closed）。"""
    if not budget_file.is_file():
        return 0
    try:
        raw = budget_file.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            logger.error(f"evidence_failure_budget 格式非字典，fail-closed 熔断: {raw[:200]}")
            return _EVIDENCE_FAILURE_LIMIT
        saved_task_id = data.get("task_id")
        if not saved_task_id or not isinstance(saved_task_id, str):
            logger.error("evidence_failure_budget task_id 缺失，fail-closed 熔断")
            return _EVIDENCE_FAILURE_LIMIT
        if task_id and saved_task_id != task_id:
            logger.error(f"evidence_failure_budget task_id 不匹配: {saved_task_id} vs {task_id}")
            return _EVIDENCE_FAILURE_LIMIT
        subtasks = data.get("subtasks")
        if not isinstance(subtasks, dict):
            logger.error("evidence_failure_budget subtasks 缺失或非字典，fail-closed 熔断")
            return _EVIDENCE_FAILURE_LIMIT
        if subtask_id not in subtasks:
            return 0
        entry = subtasks.get(subtask_id)
        if not isinstance(entry, dict) or isinstance(entry, bool):
            logger.error(f"evidence_failure_budget subtask {subtask_id} 记录非字典格式（拒绝旧格式），fail-closed 熔断")
            return _EVIDENCE_FAILURE_LIMIT
        saved_plan_sha = entry.get("plan_sha256")
        if plan_sha256:
            if not saved_plan_sha or not isinstance(saved_plan_sha, str) or saved_plan_sha != plan_sha256:
                logger.error(f"evidence_failure_budget plan_sha256 缺失或不匹配: {saved_plan_sha!r} vs {plan_sha256!r}")
                return _EVIDENCE_FAILURE_LIMIT
        val = entry.get("count")
        if isinstance(val, bool) or not isinstance(val, int):
            return _EVIDENCE_FAILURE_LIMIT
        if val < 0 or val > _EVIDENCE_FAILURE_LIMIT:
            return _EVIDENCE_FAILURE_LIMIT
        return val
    except Exception as exc:
        logger.error(f"读取 evidence_failure_budget 异常，fail-closed 熔断: {exc}")
        return _EVIDENCE_FAILURE_LIMIT


def _load_evidence_failure_count(
    work_dir: str | Path | None,
    subtask_id: str | None,
    task_id: str = "",
    plan_sha256: str = "",
) -> int:
    """从任务持久化文件中读取当前子题的执行证据连续失败次数（fail-closed）。"""
    if not work_dir or not subtask_id:
        return 0
    budget_file = Path(work_dir) / "evidence_failure_budget.json"
    if not plan_sha256:
        plan_file = Path(work_dir) / "modeler_plan.json"
        if plan_file.is_file():
            try:
                plan_sha256 = hashlib.sha256(plan_file.read_bytes()).hexdigest()
            except Exception:
                pass
    return _read_evidence_failure_file(
        budget_file, subtask_id, task_id=task_id, plan_sha256=plan_sha256
    )


def _save_evidence_failure_count(
    work_dir: str | Path | None,
    subtask_id: str | None,
    count: int,
    task_id: str = "",
    plan_sha256: str = "",
) -> None:
    """持久化记录当前子题的执行证据失败次数，跨 resume 续传不重置。"""
    if not work_dir or not subtask_id:
        return
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError(f"count 必须为非布尔非负整数: {count}")
    count = min(count, _EVIDENCE_FAILURE_LIMIT)
    budget_file = Path(work_dir) / "evidence_failure_budget.json"
    data: dict = {}
    if budget_file.is_file():
        try:
            data = json.loads(budget_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
    data["task_id"] = task_id or data.get("task_id", "")
    if not plan_sha256:
        plan_file = Path(work_dir) / "modeler_plan.json"
        if plan_file.is_file():
            try:
                plan_sha256 = hashlib.sha256(plan_file.read_bytes()).hexdigest()
            except Exception:
                pass
    subtasks = data.setdefault("subtasks", {})
    if not isinstance(subtasks, dict):
        subtasks = {}
        data["subtasks"] = subtasks
    subtasks[subtask_id] = {
        "count": int(count),
        "plan_sha256": plan_sha256,
        "updated_at": datetime.datetime.now().isoformat(),
    }
    tmp_file = budget_file.with_suffix(".json.tmp")
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            import os
            os.fsync(f.fileno())
        tmp_file.replace(budget_file)
    except Exception as exc:
        logger.error(f"持久化 evidence_failure_budget 失败: {exc}")
        raise RuntimeError(f"FAIL_CLOSED: 持久化 evidence_failure_budget 失败: {exc}") from exc


def _reset_evidence_failure_count(
    work_dir: str | Path | None,
    subtask_id: str | None,
    task_id: str = "",
    plan_sha256: str = "",
) -> None:
    """执行证据合格后重置当前子题的失败计数。"""
    _save_evidence_failure_count(
        work_dir, subtask_id, 0, task_id=task_id, plan_sha256=plan_sha256
    )


def _formal_subtask_id(subtask_title: str) -> str | None:


    """Return the formal ``quesN`` id for a normal or directed-repair turn."""
    matched = _FORMAL_SUBTASK_PATTERN.fullmatch(subtask_title.strip())
    return matched.group(1) if matched else None


def _formal_evidence_checklist(work_dir: str, subtask_id: str | None) -> str:
    """Render the immutable ModelPlan contract beside each formal Coder turn."""
    if not subtask_id:
        return ""
    try:
        payload = json.loads((Path(work_dir) / "modeler_plan.json").read_text(encoding="utf-8"))
        subtasks = payload.get("model_plan", {}).get("subtasks", {})
        plan = subtasks.get(subtask_id, {}) if isinstance(subtasks, dict) else {}
        metrics = plan.get("acceptance_metrics", []) if isinstance(plan, dict) else []
        diagnostic_profile = plan.get("diagnostic_profile") if isinstance(plan, dict) else None
        diagnostic_requirements = plan.get("diagnostic_requirements", []) if isinstance(plan, dict) else []
        expected_artifacts = plan.get("expected_artifacts", []) if isinstance(plan, dict) else []
    except (OSError, ValueError, TypeError):
        return ""
    if not isinstance(metrics, list):
        metrics = []
    if not isinstance(expected_artifacts, list):
        expected_artifacts = []
    lines = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        key = metric.get("key")
        comparator = metric.get("comparator")
        target = metric.get("target")
        label = metric.get("label") or key
        unit = metric.get("unit") or ""
        desc = metric.get("description") or ""
        if isinstance(key, str) and isinstance(comparator, str):
            evidence_comp = {
                "eq": "abs_diff_lte",
                "le": "lte",
                "lte": "lte",
                "ge": "gte",
                "gte": "gte",
                "gt": "gt",
                "lt": "lt",
            }.get(comparator, comparator)
            extra_field = ", tolerance: 0.0" if comparator == "eq" else ""
        desc_info = (
            f"（{label}，单位：{unit}，说明：{desc}）"
            if desc
            else (f"（{label}，单位：{unit}）" if (unit or label != key) else "")
        )
        lines.append(
            f"- `{key}`{desc_info}: `{comparator} {target}` "
            f"（调用 record_execution_evidence 时在 constraints 填写 id: `{key}`, comparison: `{evidence_comp}`, target: `{target}`{extra_field}）"
        )
    sections = []
    if lines:
        sections.append(
            "【本题不可省略的 ModelPlan 验收指标】\n"
            + "\n".join(lines)
            + "\n注意：上述每一项都必须写入本题新建/更新的数值结果文件或验收表，并在调用 record_execution_evidence 时完整包含在 constraints 数组中（包含 id、actual、comparison、target、source_path）；缺项或 direction/target 篡改会直接失败。\n"
            + "特别提醒：对于 precision、error、se、tolerance、step 等精度/误差/步长类指标（如 phi_precision、mc_se），actual 请填入实际计算得到的精度/误差数值（如 0.001、0.01 等），必须满足目标比较关系（如 <= 0.005 或 <= 0.02），绝不能误填为主结果数值（如 18.0）！\n"
            + "推荐同时生成标准验收表 `"
            + (f"{subtask_id}_acceptance_metrics.csv" if subtask_id else "quesN_acceptance_metrics.csv")
            + "`（表头：`指标ID,指标名称,数值,单位,目标值,是否达标`）。"
        )
    artifact_lines = []
    for artifact in expected_artifacts:
        if not isinstance(artifact, dict):
            continue
        path = artifact.get("path")
        kind = artifact.get("kind")
        if isinstance(path, str) and path.strip():
            artifact_lines.append(f"- `{path.strip()}`（{kind or 'artifact'}）")
    if artifact_lines:
        sections.append(
            "【本题必须落盘的 ModelPlan 产物】\\n"
            + "\\n".join(artifact_lines)
            + "\\n上述每个路径必须在本轮 execute_code 中新建或更新，不能用同类但不同文件名替代。"
            "record_execution_evidence 的 metrics、constraints 和 figures 只可引用本轮新建/更新的来源；"
            "每个 `metrics.value` 与 `constraints.actual` 都必须以同一单位和足够精度"
            "实际写入其声明的 `source_path`（包括 `1.0` 一类复核标志），不能只在代码输出或正文中出现；"
            "若提交 figures，图像 `path` 与数值 `data_path` 都必须由本轮生成或更新，"
            "否则不要把旧图列入 figures。"
        )
    if diagnostic_profile and diagnostic_profile != "not_applicable":
        requirements = [
            str(item).strip()
            for item in diagnostic_requirements
            if isinstance(item, str) and item.strip()
        ]
        sections.append(
            "【本题不可省略的诊断证据】\\n"
            f"诊断类型：`{diagnostic_profile}`。"
            + ("\\n计划要求：\\n" + "\\n".join(f"- {item}" for item in requirements) if requirements else "")
            + "\\n每一项计划要求都要有至少一个 source-backed metric；指标 id、标签或说明必须直接包含相应关键词。"
            "例如质量守恒/平衡要求必须提交由时序数组算出的 residual 或 balance metric；"
            "减压阀、双喷嘴和可行性要求也必须各自有对应指标。只写 `check=1` 或仅在 CSV 中提及而不提交 metric 会被拒绝。"
            + (
                "\\n仿真型诊断（simulation）必须在 record_execution_evidence 的 metrics 数组中提交至少一个包含"
                "仿真诊断关键词（如 seed / 随机种子 / variance / 方差 / std / ci / 置信 / convergence / 收敛 / error / 误差 / sample / 采样）的指标，"
                "且该指标的 value 必须真实记录在 CSV 文件中。"
                if diagnostic_profile == "simulation"
                else ""
            )
            + (
                "\\n数值型诊断（numerical）必须在 record_execution_evidence 的 metrics 数组中提交至少一个包含"
                "数值诊断关键词（如 convergence / 收敛 / step / 步长 / residual / 残差 / error / 误差 / iteration / 迭代 / tolerance / 容差）的指标，"
                "且该指标的 value 必须真实记录在 CSV 文件中。"
                if diagnostic_profile == "numerical"
                else ""
            )
            + (
                "\\n拟合型诊断（fitting）必须在 record_execution_evidence 的 metrics 数组中提交至少一个包含"
                "拟合诊断关键词（如 residual / 残差 / rmse / mae / r2 / holdout / bootstrap / fit / loss / 损失）的指标，"
                "且该指标的 value 必须真实记录在 CSV 文件中。"
                if diagnostic_profile == "fitting"
                else ""
            )
            + (
                "\\n优化型诊断除计划的验收指标外，至少将求解器状态（如 `solver_status=1`）、"
                "约束可行性和计划要求的松弛量/独立复算分别作为 source-backed metrics 提交；"
                "它们不能只留在 `*_diagnostic_report.csv` 中。若本题为线性规划重求解或灵敏度分析，"
                "还要把实际的新最优决策变量（例如 `optimal_x1`、`optimal_x2`）以及新旧目标值分别作为 metrics 提交；"
                "仅在正文或结果表中描述变量不够。"
                if diagnostic_profile == "optimization"
                else ""
            )
        )
    return "\\n\\n".join(sections)


def _snapshot_task_files(work_dir: str) -> dict[str, tuple[int, int]]:
    """Return cheap fingerprints for task-local files created by this Coder turn."""
    root = Path(work_dir).resolve()
    if not root.is_dir():
        return {}
    snapshots: dict[str, tuple[int, int]] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        relative = str(path.relative_to(root)).replace("\\", "/")
        snapshots[relative] = (stat.st_size, stat.st_mtime_ns)
    return snapshots


def _snapshot_protected_files(
    work_dir: str | Path,
) -> dict[str, tuple[str, bytes] | None]:
    """Capture sha256 checksums and backup bytes of protected state files, or None if non-existent."""
    root = Path(work_dir).resolve()
    protected_snapshots: dict[str, tuple[str, bytes] | None] = {}
    for filename in _PROTECTED_TASK_FILES:
        target = root / filename
        if target.exists():
            try:
                raw_bytes = target.read_bytes()
                protected_snapshots[filename] = (
                    hashlib.sha256(raw_bytes).hexdigest(),
                    raw_bytes,
                )
            except Exception as exc:
                logger.error(f"读取受保护文件快照失败 ({filename}): {exc}")
                raise ProtectedFileSnapshotError(
                    f"PROTECTED_FILE_SNAPSHOT_FAILED: 无法读取受保护文件（{filename}）快照: {exc}"
                ) from exc
        else:
            protected_snapshots[filename] = None
    return protected_snapshots


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    """原子化写入文件：同目录临时文件写入、flush、fsync 并 os.replace 替换。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f"{target.name}.tmp.{uuid.uuid4().hex}")
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass


def _verify_and_restore_protected_files(
    work_dir: str | Path,
    before_snapshots: dict[str, tuple[str, bytes] | None],
) -> tuple[bool, str]:
    """遍历全量受保护系统状态文件，执行后完整性检测、删除非法新建文件并原子恢复受损文件。"""
    root = Path(work_dir).resolve()
    errors: list[str] = []

    for filename, snapshot in before_snapshots.items():
        target = root / filename
        if snapshot is None:
            # 原本不存在的文件：若执行后被新建，必须全部清理删除
            if target.exists():
                try:
                    if target.is_file():
                        target.unlink(missing_ok=True)
                    elif target.is_dir():
                        shutil.rmtree(target, ignore_errors=True)
                except Exception as exc:
                    logger.error(f"清理非法新建受保护文件（{filename}）异常: {exc}")
                if target.exists():
                    errors.append(f"PROTECTED_FILE_RECOVERY_FAILED: 清理非法新建受保护文件（{filename}）失败")
                else:
                    errors.append(f"受保护系统状态文件（{filename}）被代码非法新建，已清理")
        else:
            expected_hash, backup_bytes = snapshot
            if not target.is_file():
                # 原子恢复被删除的文件
                restore_ok = False
                try:
                    _atomic_write_bytes(target, backup_bytes)
                    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == expected_hash:
                        restore_ok = True
                except Exception as exc:
                    logger.error(f"恢复被删除受保护文件 {filename} 失败: {exc}")
                if restore_ok:
                    errors.append(f"受保护系统状态文件（{filename}）被代码非法删除，已恢复")
                else:
                    errors.append(f"PROTECTED_FILE_RECOVERY_FAILED: 恢复被删除受保护文件（{filename}）失败")
            else:
                try:
                    current_hash = hashlib.sha256(target.read_bytes()).hexdigest()
                except Exception:
                    current_hash = None

                if current_hash != expected_hash:
                    restore_ok = False
                    try:
                        _atomic_write_bytes(target, backup_bytes)
                        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == expected_hash:
                            restore_ok = True
                    except Exception as exc:
                        logger.error(f"恢复被篡改受保护文件 {filename} 失败: {exc}")
                    if restore_ok:
                        errors.append(f"受保护系统状态文件（{filename}）被代码非法篡改，已恢复")
                    else:
                        errors.append(f"PROTECTED_FILE_RECOVERY_FAILED: 恢复受保护文件（{filename}）失败")

    if errors:
        return False, " | ".join(errors)
    return True, ""


def _changed_task_files(
    before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]
) -> set[str]:
    return {path for path, fingerprint in after.items() if before.get(path) != fingerprint}


def _evidence_source_paths(arguments: object) -> set[str]:
    """Extract result and figure-data paths supplied to the evidence recorder."""
    if not isinstance(arguments, dict):
        return set()
    paths: set[str] = set()
    for metric in arguments.get("metrics", []):
        if isinstance(metric, dict) and isinstance(metric.get("source_path"), str):
            paths.add(str(Path(metric["source_path"])).replace("\\", "/"))
    for constraint in arguments.get("constraints", []):
        if isinstance(constraint, dict) and isinstance(constraint.get("source_path"), str):
            paths.add(str(Path(constraint["source_path"])).replace("\\", "/"))
    for figure in arguments.get("figures", []):
        if not isinstance(figure, dict):
            continue
        for field in ("path", "data_path"):
            if isinstance(figure.get(field), str):
                paths.add(str(Path(figure[field])).replace("\\", "/"))
    return paths


_CLOSEOUT_PLACEHOLDER = "已在受控收束阶段记录执行证据。"


def _has_method_narration(content: str) -> bool:
    """判断收束响应是否已含可用的方法叙述。

    按需求仅在“为空或只有占位内容”时判为缺失，避免误伤模型产出的合法简短
    叙述（历史测试依赖此行为）。
    """
    text = (content or "").strip()
    return bool(text) and text != _CLOSEOUT_PLACEHOLDER.strip()


def _subtask_frozen_metrics(work_dir: str, subtask_id: str) -> list[dict]:
    """本题冻结指标（严格按 subtask_id 过滤，绝不混入其它子任务）。"""
    try:
        validation = validate_result_freeze(work_dir)
    except Exception:  # noqa: BLE001 - 兜底不得因读取异常而中断收束
        return []
    if not validation.get("active") or not validation.get("passed"):
        return []
    target = str(subtask_id).lower()
    return [
        metric
        for metric in validation.get("metrics", [])
        if str(metric.get("subtask_id", "")).lower() == target
    ]


def _subtask_artifact_paths(work_dir: str, subtask_id: str | None) -> set[str]:
    """本题产物文件名（按 ``quesN_`` 前缀过滤，仅本题，不跨题）。"""
    if not subtask_id:
        return set()
    prefix = f"{subtask_id}_"
    try:
        entries = list(Path(work_dir).iterdir())
    except OSError:
        return set()
    return {
        entry.name
        for entry in entries
        if entry.is_file() and entry.name.startswith(prefix)
    }


def _deterministic_subtask_narration(
    work_dir: str,
    subtask_id: str,
    question_text: str,
    plan_summary: str,
    artifact_paths: list[str],
) -> str:
    """方案2：本题确定性兜底叙述。

    只使用本题（``subtask_id``）自己的：题目、Modeler 计划、冻结指标、产物清单。
    绝不拼接全局 ``build_result_fact_summary`` 或其它子任务内容，避免再次跨题
    污染。即使追加叙述调用失败，也用它替代无信息占位符
    “已在受控收束阶段记录执行证据”。
    """
    metrics = _subtask_frozen_metrics(work_dir, subtask_id)
    lines: list[str] = [f"【{subtask_id} 方法—产物—结果（系统按冻结事实整理）】"]
    if question_text.strip():
        lines.append(f"- 本题目标：{question_text.strip()}")
    if plan_summary.strip():
        lines.append(f"- 采用的模型/方法（依据 Modeler 计划）：{plan_summary.strip()}")
    if artifact_paths:
        lines.append("- 生成的主要产物：" + "、".join(artifact_paths))
    if metrics:
        lines.append("- 已冻结的关键结果：")
        for metric in metrics:
            label = metric.get("label") or metric.get("id")
            value = metric.get("value")
            unit = metric.get("unit", "")
            unit_str = f" {unit}" if unit else ""
            lines.append(f"    · {label} = {value}{unit_str}")
    else:
        lines.append(
            "- 已冻结的关键结果：请仅依据本题结果文件如实叙述，不得推测或新增数值。"
        )
    lines.append(
        "以上为系统按本题冻结事实整理的结构化说明，仅供方法与结果叙述；"
        "不得据此推测、修改或新增任何数值。"
    )
    return "\n".join(lines)


class CoderAgent(Agent):
    """代码手 Agent，通过 LLM 生成代码并在解释器中执行，支持错误反思和重试。"""
    def __init__(
        self,
        task_id: str,
        model: LLM,
        work_dir: str,  # 工作目录
        max_chat_turns: int | None = settings.MAX_CHAT_TURNS,  # 最大聊天次数熔断上限（跨子任务累计）；显式传 None 表示无限制
        max_retries: int | None = settings.MAX_RETRIES,  # 单子任务最大重试次数熔断上限；显式传 None 表示无限制
        max_successful_tool_calls: int | None = settings.CODER_MAX_SUCCESSFUL_TOOL_CALLS_PER_SUBTASK,
        code_interpreter: BaseCodeInterpreter | None = None,
        context_window: int = 128000,
        cancel_event: asyncio.Event | None = None,
        user_input_provider: Callable[[], list[str]] | None = None,
        problem_context: str = "",
        checkpoint_manager: CheckpointManager | None = None,
    ) -> None:
        super().__init__(
            task_id,
            model,
            context_window,
            cancel_event=cancel_event,
            user_input_provider=user_input_provider,
            guidance_target="coder",
        )
        self.work_dir = work_dir
        self.max_chat_turns = max_chat_turns
        self.current_chat_turns = 0
        self.max_retries = max_retries
        self.max_successful_tool_calls = max_successful_tool_calls
        self.is_first_run = True
        self.system_prompt = CODER_PROMPT
        self.code_interpreter = code_interpreter
        self.problem_context = problem_context.strip()
        self._quality_repair_source_prepared = False
        self.checkpoint_manager = checkpoint_manager

    def prepare_quality_repair_source(
        self, checkpoint_manager: CheckpointManager | None = None
    ) -> None:
        """隔离质量复核前的 notebook，建立新的可重放源码入口。

        质量复核退回表示旧的“成功”探索也可能已经被人工判定为过时或错误。
        这些单元不能继续作为新修正的前置状态，否则修正代码只会被追加到旧
        草稿之后，干净内核重跑仍可能得到相互矛盾的结果。旧 notebook 仍保留在
        任务的 failed_attempts 审计目录中；当前 notebook 只从新的成功执行单元
        开始。该方法只由显式 ``quality_repair=True`` 的受控返修调用。
        """
        if self._quality_repair_source_prepared:
            return
        serializer = getattr(self.code_interpreter, "notebook_serializer", None)
        if serializer is None:
            raise RuntimeError("质量返修无法定位 notebook 序列化器")

        notebook_path = getattr(serializer, "notebook_path", None)
        source_path = Path(notebook_path) if notebook_path else None
        manager = checkpoint_manager or self.checkpoint_manager
        if manager is not None and manager._checkpoint is None:
            manager.load()
        if manager is not None and manager._checkpoint is not None:
            prepared_now = manager.prepare_quality_repair_source(
                str(source_path) if source_path else None
            )
            if not prepared_now:
                # A candidate or an earlier Coder turn already owns this clean
                # source chain; never reset the serializer loaded from it.
                self._quality_repair_source_prepared = True
                return
            serializer.nb = nbf.new_notebook()
            if hasattr(serializer, "segmentation_output_content"):
                serializer.segmentation_output_content = {}
            if hasattr(serializer, "current_segmentation"):
                serializer.current_segmentation = ""
            serializer.write_to_notebook()
            self._quality_repair_source_prepared = True
            logger.warning("质量复核返修已隔离旧 notebook，开始建立新的可重放源码链")
            return

        # Compatibility for direct unit callers that construct a CoderAgent
        # without a task checkpoint.  The workflow and repair-candidate paths
        # always use the durable manager branch above.
        files_to_archive = [
            path
            for path in (source_path,)
            if path is not None and path.is_file()
        ]
        # A stale variable snapshot is another replayable source of old state.
        # Isolate it with the notebook so a later resume cannot silently restore
        # variables from before the quality-review decision.
        files_to_archive.extend(
            path
            for path in (
                Path(self.work_dir) / "variable_snapshot.pkl",
                Path(self.work_dir) / "variable_snapshot_meta.json",
            )
            if path.is_file()
        )
        if files_to_archive:
            archive_root = Path(self.work_dir) / "failed_attempts" / "quality_repair"
            archive_root.mkdir(parents=True, exist_ok=True)
            archive_dir = archive_root / datetime.datetime.now().strftime(
                "%Y%m%d-%H%M%S-%f"
            )
            archive_dir.mkdir(parents=True, exist_ok=False)
            for source_path in files_to_archive:
                try:
                    source_path.replace(archive_dir / source_path.name)
                except OSError as exc:
                    # Do not silently overwrite the only historical source if
                    # audit isolation failed.  The caller can report this as a
                    # bounded quality-repair failure instead of producing an
                    # ambiguous chain.
                    raise RuntimeError(
                        f"质量返修无法隔离旧 {source_path.name}"
                    ) from exc

        serializer.nb = nbf.new_notebook()
        # NotebookSerializer keeps these fields for section output aggregation;
        # stale values must not leak into the new repair turn either.
        if hasattr(serializer, "segmentation_output_content"):
            serializer.segmentation_output_content = {}
        if hasattr(serializer, "current_segmentation"):
            serializer.current_segmentation = ""
        serializer.write_to_notebook()
        self._quality_repair_source_prepared = True
        logger.warning("质量复核返修已隔离旧 notebook，开始建立新的可重放源码链")

    async def run(
        self,
        prompt: str,
        subtask_title: str,
        *,
        quality_repair: bool = False,
    ) -> CoderToWriter:  # type: ignore[reportIncompatibleMethodOverride]
        """执行代码手子任务，生成并运行代码。

        Args:
            prompt: 子任务描述。
            subtask_title: 子任务标题，用于分段输出。

        Returns:
            CoderToWriter 对象，包含代码执行结果和生成的图片列表。
        """
        logger.info(
            f"{self.__class__.__name__}:开始执行子任务: "
            f"title_chars={len(subtask_title)}"
        )
        if self.code_interpreter is None:
            raise RuntimeError("code_interpreter 未初始化")
        if quality_repair:
            self.prepare_quality_repair_source()
        self.code_interpreter.add_section(subtask_title)

        # 根据 api_type 选择 tools 格式
        api_type = self.model.api_type
        tools = coder_tools_anthropic if api_type == ApiType.ANTHROPIC else coder_tools

        # 如果是第一次运行，则添加系统提示
        if self.is_first_run:
            logger.info("首次运行，添加系统提示和数据集文件信息")
            self.is_first_run = False
            await self.append_chat_history(
                {"role": "system", "content": self.system_prompt}
            )
            if self.problem_context:
                await self.append_chat_history(
                    {
                        "role": "user",
                        "content": (
                            "【完整原始题面（唯一事实来源，不得省略其中参数）】\n"
                            + self.problem_context
                        ),
                    }
                )
            # 当前数据集文件
            await self.append_chat_history(
                {
                    "role": "user",
                    "content": f"当前文件夹下的数据集文件{get_current_files(self.work_dir, 'data')}",
                }
            )

        formal_subtask_id = _formal_subtask_id(subtask_title)
        if formal_subtask_id is None:
            # EDA and other non-formal preparation turns may execute code, but
            # they never own a quesN execution manifest.  Keeping the trusted
            # recorder out of their tool list prevents an otherwise successful
            # EDA pass from being converted into a rejected formal submission.
            tools = [
                tool
                for tool in tools
                if (
                    tool.get("name") != "record_execution_evidence"
                    and tool.get("function", {}).get("name")
                    != "record_execution_evidence"
                )
            ]
        # 添加 sub_task
        logger.info(f"添加子任务提示: chars={len(prompt)}")
        await self.append_chat_history({"role": "user", "content": prompt})
        evidence_checklist = _formal_evidence_checklist(self.work_dir, formal_subtask_id)
        if evidence_checklist:
            await self.append_chat_history({"role": "user", "content": evidence_checklist})

        retry_count = 0
        last_error_message = ""
        consecutive_final_outputs = 0
        successful_tool_calls = 0
        execution_error_occurred = False
        evidence_commit_required = False
        evidence_changed_paths: set[str] = set()
        evidence_failure_count = _load_evidence_failure_count(
            self.work_dir, formal_subtask_id, task_id=self.task_id
        )
        if formal_subtask_id and evidence_failure_count >= _EVIDENCE_FAILURE_LIMIT:
            logger.error(
                "受控执行证据失败预算已耗尽，立即熔断拒绝启动 Coder: "
                f"subtask={formal_subtask_id}, failures={evidence_failure_count}"
            )
            await redis_manager.publish_message(
                self.task_id,
                SystemMessage(
                    content=f"子任务 {formal_subtask_id} 执行证据失败预算已耗尽（{evidence_failure_count} 次），已触发熔断保护",
                    type="error",
                ),
            )
            raise RuntimeError(
                f"PLAN_CONFLICT: 子任务 {formal_subtask_id} 受控执行证据已连续失败 {evidence_failure_count} 次，"
                "可能存在 ModelPlan 与真实求解结果冲突；熔断保护已触发，请修正计划或切换 provider 后重试。"
            )
        last_closeout_warning_remaining: int | None = None


        consecutive_agent_exceptions = 0
        no_tool_response_count = 0
        saw_tool_calls = False

        while True:
            if self.max_retries is not None and retry_count >= self.max_retries:
                logger.error(f"超过最大尝试次数: {self.max_retries}")
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content="超过最大尝试次数", type="error"),
                )
                logger.warning(
                    "任务失败，超过最大尝试次数: "
                    f"max_retries={self.max_retries}, "
                    f"last_error_chars={len(last_error_message)}"
                )
                return CoderToWriter(
                    code_response=f"任务失败，超过最大尝试次数{self.max_retries}, 最后错误信息: {last_error_message}",
                    created_images=[],
                    execution_attempted=successful_tool_calls > 0 or bool(last_error_message),
                    execution_succeeded=False,
                    execution_error_occurred=execution_error_occurred,
                )


            if self.max_chat_turns is not None and self.current_chat_turns >= self.max_chat_turns:
                logger.error(f"超过最大聊天次数: {self.max_chat_turns}")
                await redis_manager.publish_message(
                    self.task_id,
                    SystemMessage(content="超过最大聊天次数", type="error"),
                )
                raise Exception(
                    f"Reached maximum number of chat turns ({self.max_chat_turns}). Task incomplete."
                )

            active_tools = tools
            active_tool_choice = "auto"
            # Keep every formal-subtask tool turn in the same DeepSeek mode.
            # The forced first turn disables thinking and therefore has no
            # reasoning_content to round-trip.  Re-enabling thinking after its
            # tool result would make DeepSeek reject that assistant tool-call
            # history with BadRequestError (400).
            active_thinking = formal_subtask_id is None
            if evidence_commit_required:
                # A code-run limit is a circuit breaker, not proof that the
                # formal subtask is complete.  At this boundary expose only the
                # trusted recorder, so a model cannot spend another turn on a
                # plot, notebook narration, or a hand-written manifest.
                active_tools = [
                    tool
                    for tool in tools
                    if (
                        tool.get("name") == "record_execution_evidence"
                        or tool.get("function", {}).get("name")
                        == "record_execution_evidence"
                    )
                ]
                # Use the internal ``any`` contract, exposing only the
                # recorder so every provider has one deterministic action.
                active_tool_choice = "any"
            elif formal_subtask_id is not None:
                if successful_tool_calls == 0:
                    # A formal question cannot be considered complete without
                    # at least one executed code cell.  Offer only the
                    # executable action for its first turn so the forced
                    # ``any`` contract cannot select stale evidence.
                    active_tools = [
                        tool
                        for tool in tools
                        if (
                            tool.get("name") == "execute_code"
                            or tool.get("function", {}).get("name") == "execute_code"
                        )
                    ]
                    active_tool_choice = "any"

            self.current_chat_turns += 1
            logger.info(f"当前对话轮次: {self.current_chat_turns}")
            
            try:
                response = await self._chat(
                    history=self.chat_history,
                    tools=active_tools,
                    tool_choice=active_tool_choice,
                    thinking=active_thinking,
                    agent_name=self.__class__.__name__,
                )
                consecutive_agent_exceptions = 0

                # 如果有工具调用
                if response.tool_calls:
                    saw_tool_calls = True
                    no_tool_response_count = 0
                    logger.info("检测到工具调用")
                    if len(response.tool_calls) != 1:
                        # The legacy loop handled only the first call but still
                        # placed every call in chat history, leaving providers
                        # with orphaned tool-call ids.  A formal computation is
                        # intentionally one action per turn: execute, inspect,
                        # then record evidence.
                        assistant_msg: dict = {"role": "assistant", "content": response.content}
                        if response.reasoning_content:
                            assistant_msg["reasoning_content"] = response.reasoning_content
                        assistant_msg["tool_calls"] = [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.name, "arguments": tc.arguments},
                            }
                            for tc in response.tool_calls
                        ]
                        await self.append_chat_history(assistant_msg)
                        for tool_call in response.tool_calls:
                            await self.append_chat_history(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "name": tool_call.name,
                                    "content": (
                                        "每轮只能调用一个工具。请先执行或检查一个动作；"
                                        "结果文件写完后，在下一轮单独调用 "
                                        "record_execution_evidence。"
                                    ),
                                }
                            )
                        continue
                    tool_call = response.tool_calls[0]
                    tool_id = tool_call.id

                    is_execute_code_tool = (
                        tool_call.name == "execute_code"
                        or tool_call.name.startswith("CompatExecuteCode")
                    )
                    is_record_evidence_tool = tool_call.name == "record_execution_evidence"

                    if evidence_commit_required and not is_record_evidence_tool:
                        # Some compatible providers may return a stale tool
                        # call even after the tool list has been narrowed. Do
                        # not execute it: accepting it would bypass the
                        # evidence boundary that the cap is meant to enforce.
                        assistant_msg: dict = {
                            "role": "assistant", "content": response.content
                        }
                        if response.reasoning_content:
                            assistant_msg["reasoning_content"] = response.reasoning_content
                        assistant_msg["tool_calls"] = [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": tc.arguments,
                                },
                            }
                            for tc in response.tool_calls
                        ]
                        await self.append_chat_history(assistant_msg)
                        await self.append_chat_history(
                            {
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "name": tool_call.name,
                                "content": (
                                    "执行次数上限已到。现在只能调用 "
                                    "record_execution_evidence；不得继续执行代码。"
                                ),
                            }
                        )
                        continue

                    if is_record_evidence_tool and formal_subtask_id is None:
                        # A few compatible providers can emit a stale tool
                        # name that was not offered for this turn.  Treat it
                        # as an unsupported EDA action rather than sending it
                        # through the formal evidence failure/retry loop.
                        logger.warning(
                            "非正式代码阶段尝试提交正式执行证据: "
                            f"subtask_title={subtask_title!r}"
                        )
                        assistant_msg: dict = {
                            "role": "assistant", "content": response.content
                        }
                        if response.reasoning_content:
                            assistant_msg["reasoning_content"] = response.reasoning_content
                        assistant_msg["tool_calls"] = [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": tc.arguments,
                                },
                            }
                            for tc in response.tool_calls
                        ]
                        await self.append_chat_history(assistant_msg)
                        await self.append_chat_history(
                            {
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "name": tool_call.name,
                                "content": (
                                    "当前是非正式 EDA/准备阶段，不能记录 quesN 的"
                                    " execution evidence。请继续执行 EDA，或直接给出"
                                    "本阶段结论。"
                                ),
                            }
                        )
                        continue

                    if is_record_evidence_tool:
                        logger.info("代码手提交受控执行证据")
                        assistant_msg: dict = {"role": "assistant", "content": response.content}
                        if response.reasoning_content:
                            assistant_msg["reasoning_content"] = response.reasoning_content
                        assistant_msg["tool_calls"] = [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.name, "arguments": tc.arguments},
                            }
                            for tc in response.tool_calls
                        ]
                        await self.append_chat_history(assistant_msg)
                        try:
                            arguments = None
                            if isinstance(tool_call.arguments, dict):
                                arguments = tool_call.arguments
                            elif isinstance(tool_call.arguments, str):
                                try:
                                    arguments = json.loads(tool_call.arguments)
                                except Exception:
                                    arguments = json.loads(repair_json(tool_call.arguments))
                            if not isinstance(arguments, dict):
                                raise TypeError("arguments 必须是 JSON 对象")

                            submitted_subtask_id = arguments.get("subtask_id")
                            if (
                                formal_subtask_id is not None
                                and submitted_subtask_id != formal_subtask_id
                            ):
                                result = {
                                    "ok": False,
                                    "errors": [
                                        "当前 Coder 回合只能记录 "
                                        f"{formal_subtask_id}，不能改写 {submitted_subtask_id!r}。"
                                    ],
                                }
                            else:
                                source_paths = _evidence_source_paths(arguments)
                                stale_paths = source_paths - evidence_changed_paths
                                if formal_subtask_id is not None and not successful_tool_calls:
                                    result = {
                                        "ok": False,
                                        "errors": [
                                            "正式问题必须先成功执行代码并生成结果文件，才能提交执行证据。"
                                        ],
                                    }
                                elif formal_subtask_id is not None and stale_paths:
                                    result = {
                                        "ok": False,
                                        "errors": [
                                            "证据来源必须由本轮实际代码执行新建或更新；"
                                            f"当前未检测到更新：{', '.join(sorted(stale_paths))}。"
                                        ],
                                    }
                                else:
                                    allowed_keys = {"subtask_id", "constraints", "metrics", "figures"}
                                    filtered_args = {k: v for k, v in arguments.items() if k in allowed_keys}
                                    if "subtask_id" not in filtered_args:
                                        filtered_args["subtask_id"] = formal_subtask_id or ""
                                    if "constraints" not in filtered_args or not isinstance(filtered_args["constraints"], list):
                                        filtered_args["constraints"] = []
                                    if "metrics" not in filtered_args or not isinstance(filtered_args["metrics"], list):
                                        filtered_args["metrics"] = []
                                    result = record_execution_evidence(
                                        self.work_dir, **filtered_args
                                    )
                        except Exception as exc:
                            logger.warning(f"证据记录参数处理异常: {exc}")
                            result = {
                                "ok": False,
                                "errors": [f"证据记录参数无效：{exc}。请检查 subtask_id、constraints、metrics、figures 结构。"],
                            }
                        await self.append_chat_history(
                            {
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "name": tool_call.name,
                                "content": json.dumps(result, ensure_ascii=False),
                            }
                        )
                        evidence_accepted = (
                            result.get("ok") is True and result.get("feasible") is True
                        )
                        if result.get("ok") is True and result.get("feasible") is False:
                            # The manifest is intentionally retained as a failed
                            # audit record, but the Coder must not treat it as a
                            # completed question.  Route it through the focused
                            # repair path with an explicit, actionable error.
                            failed_constraints = result.get("failed_constraints", [])
                            failure_details = []
                            for constraint in failed_constraints:
                                if not isinstance(constraint, dict):
                                    continue
                                constraint_id = str(constraint.get("id", "unknown"))
                                actual = constraint.get("actual")
                                comparison = constraint.get("comparison")
                                target = constraint.get("target")
                                lower = constraint.get("lower")
                                upper = constraint.get("upper")
                                if target is not None:
                                    bound = f"{comparison} {target}"
                                elif lower is not None or upper is not None:
                                    bound = f"between [{lower}, {upper}]"
                                else:
                                    bound = str(comparison)
                                failure_details.append(
                                    f"{constraint_id}: actual={actual}, required {bound}"
                                )
                            result = {
                                **result,
                                "ok": False,
                                "errors": [
                                    "执行证据已记录，但以下硬约束未满足："
                                    + ("；".join(failure_details) if failure_details else "请检查约束表的实际数值。"),
                                ],
                            }
                        await redis_manager.publish_message(
                            self.task_id,
                            SystemMessage(
                                content=(
                                    "代码手已记录可验证执行证据"
                                    if evidence_accepted
                                    else "代码手提交的执行证据不完整，请按错误信息修正"
                                ),
                                type="error" if not evidence_accepted else "info",
                            ),
                        )
                        # The LLM receives the exact server-generated outcome and
                        # can correct only the failing source/record on its next
                        # turn.  This call never counts as code execution itself.
                        if evidence_accepted:
                            _reset_evidence_failure_count(
                                self.work_dir, formal_subtask_id, task_id=self.task_id
                            )
                            # A formal Coder turn owns one question.  Once its
                            # backend-owned evidence is persisted, stop this
                            # turn before a later model response can overwrite
                            # result files and invalidate the fresh manifest.
                            closeout_response = (response.content or "").strip()
                            if not _has_method_narration(closeout_response):
                                # 方案1+2：证据合格但模型这一轮只调了工具、未产出
                                # 方法叙述。Writer 若拿不到本题叙事，会跨题借用
                                # （历史故障：ques3 空叙述→5.3 抓 sensitivity 叙事跑题）。
                                # 追加至多一轮纯文本受控叙述；失败/超时/仍空则用
                                # 本题确定性兜底。二者都只用本题上下文。
                                closeout_response = await self._narrate_closeout_once(
                                    subtask_title=subtask_title,
                                    formal_subtask_id=formal_subtask_id,
                                    evidence_arguments=arguments,
                                 )
                            return CoderToWriter(
                                code_response=closeout_response,
                                created_images=await self.code_interpreter.get_created_images(
                                    subtask_title
                                ),
                                execution_attempted=successful_tool_calls > 0,
                                execution_succeeded=not execution_error_occurred,
                                execution_error_occurred=execution_error_occurred,
                            )
                        evidence_failure_count += 1
                        _save_evidence_failure_count(
                            self.work_dir,
                            formal_subtask_id,
                            evidence_failure_count,
                            task_id=self.task_id,
                        )
                        errors = result.get("errors") or ["未知证据错误"]

                        evidence_error = "；".join(str(error) for error in errors)
                        # 拒绝原因此前只进模型对话历史，人工排障时无从查起；
                        # 记录到日志便于诊断模型为何连续提交不合格证据。
                        logger.warning(
                            "受控执行证据被拒: "
                            f"subtask={formal_subtask_id}, "
                            f"attempt={evidence_failure_count}, "
                            f"errors={evidence_error[:500]}"
                        )
                        if evidence_failure_count >= _EVIDENCE_FAILURE_LIMIT:
                            logger.error(
                                "受控执行证据连续失败，停止正式子题: "
                                f"subtask={formal_subtask_id}, "
                                f"failures={evidence_failure_count}"
                            )
                            await redis_manager.publish_message(
                                self.task_id,
                                SystemMessage(
                                    content=(
                                        "受控执行证据连续失败，已停止当前正式子题，"
                                        "避免无界重试"
                                    ),
                                    type="error",
                                ),
                            )
                            return CoderToWriter(
                                code_response=(
                                    "任务失败，受控执行证据连续 "
                                    f"{evidence_failure_count} 次不完整：{evidence_error}"
                                ),
                                created_images=await self.code_interpreter.get_created_images(
                                    subtask_title
                                ),
                                execution_attempted=successful_tool_calls > 0,
                                execution_succeeded=False,
                                execution_error_occurred=True,
                            )
                        if evidence_commit_required:
                            # Re-open code execution for one focused repair. The
                            # next successful call reaches the cap again and
                            # therefore returns immediately to the recorder.
                            evidence_commit_required = False
                        await self.append_chat_history(
                            {
                                "role": "user",
                                "content": (
                                    f"受控执行证据第 {evidence_failure_count} 次失败："
                                    f"{evidence_error}。下一次 execute_code 只能修复或生成"
                                    "错误所指的数值来源文件；不得新增分析、诊断或图表。"
                                    "修复后立即调用 record_execution_evidence。"
                                ),
                            }
                        )
                        continue

                    if is_execute_code_tool:
                        logger.info(f"调用工具: {tool_call.name}")
                        await redis_manager.publish_message(
                            self.task_id,
                            SystemMessage(
                                content=f"代码手调用{tool_call.name}工具"
                            ),
                        )

                        code = json.loads(tool_call.arguments)["code"]
                        unsafe_path = _find_cross_task_path(code)
                        if unsafe_path is not None:
                            logger.warning("拒绝跨任务目录文件访问")
                            assistant_msg: dict = {
                                "role": "assistant",
                                "content": response.content,
                            }
                            if response.reasoning_content:
                                assistant_msg["reasoning_content"] = response.reasoning_content
                            assistant_msg["tool_calls"] = [
                                {
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {
                                        "name": tc.name,
                                        "arguments": tc.arguments,
                                    },
                                }
                                for tc in response.tool_calls
                            ]
                            await self.append_chat_history(assistant_msg)
                            await self.append_chat_history(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_id,
                                    "name": tool_call.name,
                                    "content": (
                                        "安全限制：代码不得读取当前任务目录之外的文件，"
                                        f"已拒绝路径 {unsafe_path!r}。"
                                        "请只使用当前任务目录中的文件；如果缺少模板或数据，"
                                        "请在当前目录直接创建所需输出文件。"
                                    ),
                                }
                            )
                            await redis_manager.publish_message(
                                self.task_id,
                                SystemMessage(
                                    content="代码手拒绝跨任务目录文件访问",
                                    type="error",
                                ),
                            )
                            continue

                        await redis_manager.publish_message(
                            self.task_id,
                            InterpreterMessage(
                                input={"code": code},
                            ),
                        )

                        # 更新对话历史 - 添加助手的响应
                        assistant_msg: dict = {"role": "assistant", "content": response.content}
                        if response.reasoning_content:
                            assistant_msg["reasoning_content"] = response.reasoning_content
                        if response.tool_calls:
                            assistant_msg["tool_calls"] = [
                                {
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {"name": tc.name, "arguments": tc.arguments},
                                }
                                for tc in response.tool_calls
                            ]
                        await self.append_chat_history(assistant_msg)

                        # 执行工具调用
                        logger.info("执行工具调用")
                        before_execution_files = (
                            _snapshot_task_files(self.work_dir)
                            if formal_subtask_id is not None
                            else {}
                        )
                        before_protected_snapshots = _snapshot_protected_files(self.work_dir)
                        integrity_ok = True
                        integrity_err = ""
                        try:
                            (
                                text_to_gpt,
                                error_occurred,
                                error_message,
                            ) = await self.code_interpreter.execute_code(code)
                        except Exception as exec_exc:
                            error_occurred = True
                            error_message = f"执行异常: {exec_exc}"
                            text_to_gpt = ""
                        finally:
                            # 无论执行成功、报错、超时或异常，均强制复核并原子恢复受保护系统状态文件
                            integrity_ok, integrity_err = _verify_and_restore_protected_files(
                                self.work_dir, before_protected_snapshots
                            )
                        if not integrity_ok:
                            logger.error(f"代码手执行检测到受保护文件篡改或恢复失败: {integrity_err}")
                            if "PROTECTED_FILE_RECOVERY_FAILED" in integrity_err:
                                raise ProtectedFileRecoveryError(f"PROTECTED_FILE_RECOVERY_FAILED: {integrity_err}")
                            raise ProtectedFileTamperError(f"SecurityError: {integrity_err}，禁止篡改系统状态与预算文件。")

                        # 添加工具执行结果
                        if error_occurred:
                            execution_error_occurred = True
                            # 即使发生错误也要添加tool响应
                            await self.append_chat_history(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_id,
                                    "name": tool_call.name,
                                    "content": error_message,
                                }
                            )

                            logger.warning(
                                f"代码执行错误: error_chars={len(error_message)}"
                            )
                            retry_count += 1
                            logger.info(f"当前尝试次:{retry_count} / {self.max_retries}")
                            last_error_message = error_message
                            reflection_prompt = get_reflection_prompt(error_message, code)

                            await redis_manager.publish_message(
                                self.task_id,
                                SystemMessage(content="代码手反思纠正错误", type="error"),
                            )

                            await self.append_chat_history(
                                {"role": "user", "content": reflection_prompt}
                            )
                            continue
                        else:
                            # 成功执行的tool响应
                            # Keep the historical notebook error for audit, but a
                            # later successful execution means the current tool
                            # state is no longer an unresolved interpreter error.
                            execution_error_occurred = False
                            successful_tool_calls += 1
                            if formal_subtask_id is not None:
                                after_execution_files = _snapshot_task_files(self.work_dir)
                                evidence_changed_paths.update(
                                    _changed_task_files(
                                        before_execution_files, after_execution_files
                                    )
                                )
                            await self.append_chat_history(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_id,
                                    "name": tool_call.name,
                                    "content": text_to_gpt,
                                }
                            )
                            if _looks_like_final_tool_output(text_to_gpt):
                                consecutive_final_outputs += 1
                            else:
                                consecutive_final_outputs = 0

                            if consecutive_final_outputs >= 2 and formal_subtask_id is None:
                                logger.info("连续检测到完成性工具输出，自动收束代码手任务")
                                await redis_manager.publish_message(
                                    self.task_id,
                                    SystemMessage(content="代码手检测到任务已完成，自动收束"),
                                )
                                return CoderToWriter(
                                    code_response=text_to_gpt,
                                    created_images=await self.code_interpreter.get_created_images(
                                        subtask_title
                                    ),
                                    execution_attempted=True,
                                    execution_succeeded=not execution_error_occurred,
                                    execution_error_occurred=execution_error_occurred,
                                )
                            if consecutive_final_outputs >= 2 and formal_subtask_id is not None:
                                evidence_commit_required = True
                                await self.append_chat_history(
                                    {
                                        "role": "user",
                                        "content": (
                                            "完成性文字不能替代正式题目的计算证据。现在只能调用 "
                                            "record_execution_evidence，为当前问题 "
                                            f"{formal_subtask_id} 提交本轮新生成的结果来源。"
                                        ),
                                    }
                                )
                                continue
                            if (
                                formal_subtask_id is not None
                                and self.max_successful_tool_calls is not None
                            ):
                                remaining_calls = (
                                    self.max_successful_tool_calls
                                    - successful_tool_calls
                                )
                                if (
                                    0 < remaining_calls
                                    <= _CLOSEOUT_WARNING_REMAINING_CALLS
                                    and remaining_calls
                                    != last_closeout_warning_remaining
                                ):
                                    last_closeout_warning_remaining = remaining_calls
                                    await self.append_chat_history(
                                        {
                                            "role": "user",
                                            "content": (
                                                f"当前正式问题 {formal_subtask_id} 只剩 "
                                                f"{remaining_calls} 次成功代码执行额度。"
                                                "立即进入结果落盘收口：停止新增探索、诊断和绘图；"
                                                "下一次 execute_code 必须优先一次性写出 ModelPlan "
                                                "声明的结果文件，以及全部约束、指标和图表对应的"
                                                "数值来源文件。落盘完成后立即调用 "
                                                "record_execution_evidence。"
                                            ),
                                        }
                                    )
                                    await redis_manager.publish_message(
                                        self.task_id,
                                        SystemMessage(
                                            content=(
                                                "正式子题执行额度即将耗尽，"
                                                f"剩余 {remaining_calls} 次，强制进入结果落盘收口"
                                            ),
                                            type="warning",
                                        ),
                                    )
                            if (
                                self.max_successful_tool_calls is not None
                                and successful_tool_calls >= self.max_successful_tool_calls
                            ):
                                if formal_subtask_id:
                                    evidence_commit_required = True
                                    await self.append_chat_history(
                                        {
                                            "role": "user",
                                            "content": (
                                                "已达到代码执行上限。不要再运行代码、不要导入后端函数、"
                                                "不要手写 execution_validation.json。现在请立刻调用唯一"
                                                "可用的 record_execution_evidence，为当前正式问题 "
                                                f"{formal_subtask_id} 提交刚刚生成的结果文件、约束、指标和图表数据来源。"
                                            ),
                                        }
                                    )
                                    await redis_manager.publish_message(
                                        self.task_id,
                                        SystemMessage(
                                            content="代码执行上限已到，强制提交受控执行证据",
                                            type="warning",
                                        ),
                                    )
                                    continue
                                logger.info(
                                    "成功工具调用达到上限，自动收束代码手任务: "
                                    f"{successful_tool_calls}"
                                )
                                await redis_manager.publish_message(
                                    self.task_id,
                                    SystemMessage(
                                        content=(
                                            "代码手已完成多轮成功执行，达到自动收束上限，"
                                            "进入下一阶段"
                                        ),
                                    ),
                                )
                                return CoderToWriter(
                                    code_response=text_to_gpt,
                                    created_images=await self.code_interpreter.get_created_images(
                                        subtask_title
                                    ),
                                    execution_attempted=True,
                                    execution_succeeded=not execution_error_occurred,
                                    execution_error_occurred=execution_error_occurred,
                                )
                            # 成功执行后继续循环，等待下一步指令
                            continue
                    else:
                        logger.warning(f"不支持的工具调用: {tool_call.name}")
                        assistant_msg: dict = {"role": "assistant", "content": response.content}
                        if response.reasoning_content:
                            assistant_msg["reasoning_content"] = response.reasoning_content
                        assistant_msg["tool_calls"] = [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.name, "arguments": tc.arguments},
                            }
                            for tc in response.tool_calls
                        ]
                        await self.append_chat_history(assistant_msg)
                        await self.append_chat_history(
                            {
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "name": tool_call.name,
                                "content": (
                                    f"不支持工具 {tool_call.name}。"
                                    "请使用 execute_code 执行计算，完成后使用 "
                                    "record_execution_evidence 记录该题证据；"
                                    "如无需执行代码，请直接给出最终结果，不要再调用其他工具。"
                                ),
                            }
                        )
                        continue
                else:
                    if evidence_commit_required:
                        await self.append_chat_history(
                            {
                                "role": "user",
                                "content": (
                                    "当前正式问题尚未提交受控执行证据。请调用 "
                                    "record_execution_evidence，不要只输出文字。"
                                ),
                            }
                        )
                        continue
                    if (
                        formal_subtask_id is not None
                        and successful_tool_calls == 0
                        and not saw_tool_calls
                    ):
                        # Keep a bounded recovery path for providers that
                        # still ignore ``tool_choice=required``.  Returning a
                        # successful-looking plain-text response here would
                        # make the workflow report a formal question as done
                        # without any current execution evidence.
                        no_tool_response_count += 1
                        if no_tool_response_count < _EVIDENCE_FAILURE_LIMIT:
                            await self.append_chat_history(
                                {
                                    "role": "user",
                                    "content": (
                                        f"正式问题 {formal_subtask_id} 尚未执行代码。"
                                        "必须先调用 execute_code 实际生成并更新本题结果文件；"
                                        "不要只回复文字或复用旧文件。"
                                    ),
                                }
                            )
                            continue
                    if formal_subtask_id is not None and successful_tool_calls:
                        evidence_commit_required = True
                        await self.append_chat_history(
                            {
                                "role": "user",
                                "content": (
                                    "正式问题已执行代码但尚未记录受控证据。请调用 "
                                    "record_execution_evidence；不要只输出完成说明。"
                                ),
                            }
                        )
                        continue
                    # 没有工具调用，表示任务完成
                    logger.info("没有工具调用，任务完成")
                    return CoderToWriter(
                        code_response=response.content,
                        created_images=await self.code_interpreter.get_created_images(
                            subtask_title
                        ),
                        execution_attempted=successful_tool_calls > 0,
                        execution_succeeded=(
                            successful_tool_calls > 0 and not execution_error_occurred
                        ),
                        execution_error_occurred=execution_error_occurred,
                    )
                    
            except (
                asyncio.CancelledError,
                ProtectedFileSnapshotError,
                ProtectedFileRecoveryError,
                ProtectedFileTamperError,
            ):
                # 用户主动停止任务或受保护系统状态文件安全/恢复硬错误，向上传播，绝不进入退避重试
                raise
            except Exception as exc:
                logger.error(f"执行过程中发生异常: {type(exc).__name__}")
                retry_count += 1
                consecutive_agent_exceptions += 1
                last_error_message = str(exc)
                # WHY 必须退避：内层 llm.py 每次调用已自带 3 次重试，能走到
                # 这里说明是持续性故障（欠费/断网等）。若立即 continue 会形成
                # 无限紧循环持续打 LLM API 烧钱，直到任务超时。指数退避给
                # 故障恢复留时间，也压低失败期的请求频率。
                if self.cancel_event is not None and self.cancel_event.is_set():
                    # 用户已请求停止时不再傻等退避，立即结束
                    raise asyncio.CancelledError("任务被用户停止") from exc
                if (
                    consecutive_agent_exceptions
                    >= _CONSECUTIVE_AGENT_EXCEPTION_LIMIT
                ):
                    logger.error(
                        "Coder 连续 provider/协议异常达到恢复规程上限: "
                        f"failures={consecutive_agent_exceptions}"
                    )
                    await redis_manager.publish_message(
                        self.task_id,
                        SystemMessage(
                            content=(
                                "代码手连续两次 provider 或协议调用失败，"
                                "已按恢复规程停止当前子题"
                            ),
                            type="error",
                        ),
                    )
                    return CoderToWriter(
                        code_response=(
                            "任务失败，代码手连续 "
                            f"{consecutive_agent_exceptions} 次 provider 或协议异常："
                            f"{type(exc).__name__}"
                        ),
                        created_images=await self.code_interpreter.get_created_images(
                            subtask_title
                        ),
                        execution_attempted=successful_tool_calls > 0,
                        execution_succeeded=False,
                        execution_error_occurred=True,
                    )
                await asyncio.sleep(min(2 ** min(retry_count, 6), 60.0))
                continue
            logger.info(
                f"{self.__class__.__name__}:完成执行子任务: "
                f"title_chars={len(subtask_title)}"
            )

    def _subtask_question_and_plan(
        self, formal_subtask_id: str | None
    ) -> tuple[str, str, list[str]]:
        """从对话历史里取本题的题目/计划文本与产物路径（仅本题，不跨题）。

        Coder 的首条 user 提示即本题的结构化交接（题目+Modeler 计划+产物清单），
        据此为兜底叙述提供本题上下文；取不到时返回空串，由调用方降级。
        """
        question_text = ""
        plan_summary = ""
        for message in self.chat_history:
            if message.get("role") != "user":
                continue
            content = str(message.get("content") or "")
            if formal_subtask_id and formal_subtask_id in content:
                plan_summary = content[:1200]
                question_text = content[:400]
                break
        artifact_paths = sorted(
            _subtask_artifact_paths(self.work_dir, formal_subtask_id)
        )
        return question_text, plan_summary, artifact_paths

    async def _narrate_closeout_once(
        self,
        subtask_title: str,
        formal_subtask_id: str | None,
        evidence_arguments: object,
    ) -> str:
        """方案1：证据合格但无叙述时，追加至多一轮受控纯文本叙述。

        约束：最多一轮、禁用工具、不计入 retry、不重进代码执行流；输入仅含本题
        题目/计划/冻结指标/产物清单。超时、异常或仍为空时立即进入方案2 的本题
        确定性兜底，绝不返回无信息占位符，也不卡住收束。
        """
        question_text, plan_summary, artifact_paths = self._subtask_question_and_plan(
            formal_subtask_id
        )
        fallback = _deterministic_subtask_narration(
            self.work_dir,
            str(formal_subtask_id or subtask_title),
            question_text,
            plan_summary,
            artifact_paths,
        )
        metrics = _subtask_frozen_metrics(
            self.work_dir, str(formal_subtask_id or subtask_title)
        )
        frozen_lines = "\n".join(
            f"- {m.get('label') or m.get('id')} = {m.get('value')} {m.get('unit', '')}".rstrip()
            for m in metrics
        )
        narration_prompt = (
            f"请仅为子任务 {formal_subtask_id or subtask_title} 撰写一段“方法—产物—结果”"
            "叙述，供论文写作使用。只能依据下列本题信息，不得编写或执行代码、"
            "不得修改结果文件、不得推测或新增任何数值，也不得引用其它子任务的内容。\n\n"
            f"【本题题目】{question_text}\n\n"
            f"【本题 Modeler 计划摘录】{plan_summary}\n\n"
            f"【本题产物清单】{'、'.join(artifact_paths) or '（见结果目录）'}\n\n"
            f"【本题已冻结关键结果】\n{frozen_lines or '（无，请勿杜撰数值）'}\n\n"
            "只输出纯文本叙述，不要包含任何工具调用或代码块。"
        )
        # 独立历史：不污染主对话，也不携带其它子任务响应。
        narration_history = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": narration_prompt},
        ]
        try:
            response = await self._chat(
                history=narration_history,
                tools=None,
                tool_choice=None,
                agent_name=self.__class__.__name__,
                sub_title=f"{formal_subtask_id or subtask_title}_closeout_narration",
            )
        except Exception as exc:  # noqa: BLE001 - 任何失败都降级到确定性兜底
            logger.warning(
                "收束叙述轮失败，使用本题确定性兜底: "
                f"subtask={formal_subtask_id}, error={type(exc).__name__}"
            )
            return fallback
        narration = (getattr(response, "content", "") or "").strip()
        if getattr(response, "tool_calls", None) or not _has_method_narration(narration):
            logger.warning(
                "收束叙述轮未产出可用纯文本，使用本题确定性兜底: "
                f"subtask={formal_subtask_id}"
            )
            return fallback
        return narration
