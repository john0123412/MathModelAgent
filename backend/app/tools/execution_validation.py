"""Execution and feasibility gate for generated mathematical-modeling tasks.

The workflow previously treated a natural-language Coder response as sufficient
evidence of success.  This module makes execution evidence explicit: a final
task must have a clean notebook and a machine-readable validation manifest
whose constraints can be checked without trusting the Writer's prose.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any

import nbformat


REPORT_NAME = "execution_validation_report.json"
MANIFEST_NAME = "execution_validation.json"
FREEZE_NAME = "frozen_results.json"
_UNSUPPORTED_RESULT_TERMS = ("估计", "沿用问题", "直接取")
_Q1_REQUIRED_CONTROL_METRICS = {
    "q1_steady_100_open_duration": "100 MPa 稳态开启时长",
    "q1_steady_150_open_duration": "150 MPa 稳态开启时长",
    "q1_transition_2s_open_duration": "2 秒过渡开启时长",
    "q1_transition_5s_open_duration": "5 秒过渡开启时长",
    "q1_transition_10s_open_duration": "10 秒过渡开启时长",
}
_EVIDENCE_COMPARISONS = {"abs_diff_lte", "lte", "gte", "gt", "lt", "between"}


def _issue(
    check_id: str,
    passed: bool,
    message: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "passed": passed,
        "severity": "error" if not passed else "info",
        "message": message,
        "evidence": evidence or {},
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _safe_source_path(work_dir: Path, relative_path: object) -> Path | None:
    if not isinstance(relative_path, str) or not relative_path.strip():
        return None
    candidate = (work_dir / relative_path).resolve()
    try:
        candidate.relative_to(work_dir.resolve())
    except ValueError:
        return None
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _task_relative_file(root: Path, value: object, *, field: str) -> tuple[Path | None, str | None]:
    """Resolve an evidence file without allowing a tool call to escape its task.

    The Coder only supplies task-relative *paths*.  Hashes and manifest source
    objects are created here, after the file has been written by the interpreter.
    """
    path = _safe_source_path(root, value)
    if path is None:
        return None, f"{field} 必须是当前任务目录内的相对路径。"
    if not path.is_file():
        return None, f"{field} 指向的文件不存在：{value!r}。"
    return path, None


def _normalise_metric_records(metrics: object) -> tuple[list[dict[str, Any]] | None, list[str]]:
    if not isinstance(metrics, list) or not metrics:
        return None, ["metrics 必须是非空数组。"]
    normalised: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_ids: set[str] = set()
    for index, metric in enumerate(metrics):
        if not isinstance(metric, dict):
            errors.append(f"metrics[{index}] 必须是对象。")
            continue
        error_count_before = len(errors)
        metric_id = metric.get("id")
        label = metric.get("label")
        value = _as_number(metric.get("value"))
        unit = metric.get("unit")
        explanation = metric.get("explanation")
        if not isinstance(metric_id, str) or not metric_id.strip():
            errors.append(f"metrics[{index}].id 必须是非空字符串。")
        elif metric_id in seen_ids:
            errors.append(f"metrics 中的 id 重复：{metric_id}。")
        else:
            seen_ids.add(metric_id)
        if not isinstance(label, str) or not label.strip():
            errors.append(f"metrics[{index}].label 必须是非空字符串。")
        if value is None:
            errors.append(f"metrics[{index}].value 必须是有限数值。")
        if not isinstance(unit, str):
            errors.append(f"metrics[{index}].unit 必须是字符串。")
        if not isinstance(explanation, str) or not explanation.strip():
            errors.append(f"metrics[{index}].explanation 必须是非空字符串。")
        aliases = metric.get("aliases", [])
        if not isinstance(aliases, list) or not all(isinstance(item, str) for item in aliases):
            errors.append(f"metrics[{index}].aliases 必须是字符串数组。")
            aliases = []
        if (
            len(errors) == error_count_before
            and
            isinstance(metric_id, str)
            and metric_id.strip()
            and isinstance(label, str)
            and label.strip()
            and value is not None
            and isinstance(unit, str)
            and isinstance(explanation, str)
            and explanation.strip()
        ):
            normalised.append(
                {
                    "id": metric_id,
                    "label": label,
                    "value": value,
                    "unit": unit,
                    "explanation": explanation,
                    "aliases": aliases,
                }
            )
    return (normalised if not errors else None), errors


def _normalise_constraint_records(
    root: Path, constraints: object
) -> tuple[list[dict[str, Any]] | None, list[str]]:
    if not isinstance(constraints, list) or not constraints:
        return None, ["constraints 必须是非空数组。"]
    normalised: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_ids: set[str] = set()
    for index, constraint in enumerate(constraints):
        if not isinstance(constraint, dict):
            errors.append(f"constraints[{index}] 必须是对象。")
            continue
        constraint_id = constraint.get("id")
        actual = _as_number(constraint.get("actual"))
        comparison = constraint.get("comparison")
        if not isinstance(constraint_id, str) or not constraint_id.strip():
            errors.append(f"constraints[{index}].id 必须是非空字符串。")
        elif constraint_id in seen_ids:
            errors.append(f"constraints 中的 id 重复：{constraint_id}。")
        else:
            seen_ids.add(constraint_id)
        if actual is None:
            errors.append(f"constraints[{index}].actual 必须是有限数值。")
        if comparison not in _EVIDENCE_COMPARISONS:
            errors.append(f"constraints[{index}].comparison 不受支持。")
        source_path, source_error = _task_relative_file(
            root, constraint.get("source_path"), field=f"constraints[{index}].source_path"
        )
        if source_error:
            errors.append(source_error)

        result: dict[str, Any] = {
            "id": constraint_id,
            "actual": actual,
            "comparison": comparison,
            "source": (
                {"path": str(source_path.relative_to(root)).replace("\\", "/"), "sha256": _sha256(source_path)}
                if source_path is not None
                else {}
            ),
        }
        for key in ("target", "tolerance", "lower", "upper"):
            if key in constraint and constraint.get(key) is not None:
                numeric = _as_number(constraint[key])
                if numeric is None:
                    errors.append(f"constraints[{index}].{key} 必须是有限数值。")
                else:
                    result[key] = numeric
        if "unit" in constraint and constraint.get("unit") is not None:
            if not isinstance(constraint["unit"], str):
                errors.append(f"constraints[{index}].unit 必须是字符串。")
            else:
                result["unit"] = constraint["unit"]
        normalised.append(result)
    return (normalised if not errors else None), errors


def _normalise_figure_records(
    root: Path, figures: object
) -> tuple[list[dict[str, Any]] | None, list[str]]:
    if figures is None:
        return [], []
    if not isinstance(figures, list):
        return None, ["figures 必须是数组。"]
    normalised: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, figure in enumerate(figures):
        if not isinstance(figure, dict):
            errors.append(f"figures[{index}] 必须是对象。")
            continue
        image_path, image_error = _task_relative_file(root, figure.get("path"), field=f"figures[{index}].path")
        data_path, data_error = _task_relative_file(root, figure.get("data_path"), field=f"figures[{index}].data_path")
        if image_error:
            errors.append(image_error)
        if data_error:
            errors.append(data_error)
        metric_ids = figure.get("metric_ids", [])
        if not isinstance(metric_ids, list) or not all(isinstance(item, str) and item for item in metric_ids):
            errors.append(f"figures[{index}].metric_ids 必须是非空字符串数组或空数组。")
            metric_ids = []
        if image_path is not None and data_path is not None:
            normalised.append(
                {
                    "path": str(image_path.relative_to(root)).replace("\\", "/"),
                    "data_path": str(data_path.relative_to(root)).replace("\\", "/"),
                    "data_sha256": _sha256(data_path),
                    "metric_ids": metric_ids,
                }
            )
    return (normalised if not errors else None), errors


def record_execution_evidence(
    work_dir: str | os.PathLike[str],
    *,
    subtask_id: str,
    constraints: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    figures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Record one executed subtask through a trusted manifest writer.

    This is the only path exposed to the Coder tool interface.  The model may
    report numerical facts and task-relative files, but cannot choose hashes,
    top-level manifest structure, or the final ``feasible`` flag.  Existing
    hand-written v1 manifests remain readable; when this API is used it updates
    just the requested subtask and retains other existing subtask records.
    """
    root = Path(work_dir).resolve()
    if not isinstance(subtask_id, str) or not subtask_id.strip() or not re.fullmatch(r"ques[1-9][0-9]*", subtask_id):
        return {"ok": False, "errors": ["subtask_id 必须是 quesN 形式的正式题号。"]}
    if not root.is_dir():
        return {"ok": False, "errors": ["任务工作目录不存在。"]}

    normalised_metrics, metric_errors = _normalise_metric_records(metrics)
    normalised_constraints, constraint_errors = _normalise_constraint_records(root, constraints)
    normalised_figures, figure_errors = _normalise_figure_records(root, figures)
    errors = metric_errors + constraint_errors + figure_errors
    if errors or normalised_metrics is None or normalised_constraints is None or normalised_figures is None:
        return {"ok": False, "errors": errors}

    entry = {
        "id": subtask_id,
        "executed": True,
        "feasible": False,
        "constraints": normalised_constraints,
        "metrics": normalised_metrics,
        "figures": normalised_figures,
        "recorded_by": "trusted_record_execution_evidence",
    }
    constraint_results = [_check_constraint(item, root)[0] for item in normalised_constraints]
    entry["feasible"] = all(constraint_results)

    manifest_path = root / MANIFEST_NAME
    existing = _read_json(manifest_path) if manifest_path.exists() else None
    if existing is None:
        manifest: dict[str, Any] = {"schema_version": "mathmodel.execution-validation.v1", "subtasks": []}
    else:
        existing_subtasks = existing.get("subtasks")
        if not isinstance(existing_subtasks, list):
            return {"ok": False, "errors": ["既有 execution_validation.json 的 subtasks 不是数组，拒绝覆盖。"]}
        manifest = existing

    subtasks = [
        item for item in manifest.get("subtasks", [])
        if not (isinstance(item, dict) and item.get("id") == subtask_id)
    ]
    subtasks.append(entry)
    manifest["subtasks"] = subtasks
    # Top-level metrics are a deterministic projection of evidence records, not
    # an additional LLM-authored source of truth.  Later records with the same
    # id replace older ones, matching the subtask replacement behaviour.
    projected_metrics: dict[str, dict[str, Any]] = {}
    for item in subtasks:
        if not isinstance(item, dict):
            continue
        for metric in item.get("metrics", []):
            if isinstance(metric, dict) and isinstance(metric.get("id"), str):
                projected_metrics[metric["id"]] = metric
    manifest["metrics"] = list(projected_metrics.values())
    manifest["status"] = "PASS" if subtasks and all(
        isinstance(item, dict) and item.get("feasible") is True for item in subtasks
    ) else "FAIL"
    manifest["generated_by"] = "trusted_record_execution_evidence"
    manifest["updated_at"] = datetime.datetime.now().isoformat()

    temporary_path = manifest_path.with_suffix(".json.tmp")
    with temporary_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary_path, manifest_path)

    return {
        "ok": True,
        "subtask_id": subtask_id,
        "feasible": entry["feasible"],
        "constraint_passed": constraint_results,
        "manifest_path": MANIFEST_NAME,
        "metric_count": len(normalised_metrics),
        "figure_count": len(normalised_figures),
    }


def _check_constraint(constraint: object, work_dir: Path) -> tuple[bool, str, dict[str, Any]]:
    if not isinstance(constraint, dict):
        return False, "约束必须是对象。", {}

    constraint_id = constraint.get("id")
    actual = _as_number(constraint.get("actual"))
    comparison = constraint.get("comparison")
    source = constraint.get("source")
    evidence: dict[str, Any] = {"id": constraint_id, "comparison": comparison}
    if not isinstance(constraint_id, str) or not constraint_id.strip():
        return False, "约束缺少 id。", evidence
    if actual is None:
        return False, f"约束 {constraint_id} 的 actual 必须是有限数值。", evidence
    if not isinstance(source, dict):
        return False, f"约束 {constraint_id} 缺少可复查 source。", evidence

    source_path = _safe_source_path(work_dir, source.get("path"))
    expected_hash = source.get("sha256")
    if source_path is None or not source_path.is_file():
        return False, f"约束 {constraint_id} 的 source.path 不存在或越出任务目录。", evidence
    if not isinstance(expected_hash, str) or _sha256(source_path) != expected_hash:
        return False, f"约束 {constraint_id} 的 source.sha256 与当前文件不一致。", evidence
    evidence["source"] = {"path": str(source_path.relative_to(work_dir)), "sha256": expected_hash}

    target = _as_number(constraint.get("target"))
    tolerance = _as_number(constraint.get("tolerance"))
    lower = _as_number(constraint.get("lower"))
    upper = _as_number(constraint.get("upper"))
    if comparison == "abs_diff_lte":
        if target is None or tolerance is None or tolerance < 0:
            return False, f"约束 {constraint_id} 的 target/tolerance 无效。", evidence
        passed = abs(actual - target) <= tolerance
        message = f"约束 {constraint_id}: |{actual} - {target}| <= {tolerance}。"
    elif comparison == "lte":
        if target is None:
            return False, f"约束 {constraint_id} 的 target 无效。", evidence
        passed = actual <= target
        message = f"约束 {constraint_id}: {actual} <= {target}。"
    elif comparison == "gte":
        if target is None:
            return False, f"约束 {constraint_id} 的 target 无效。", evidence
        passed = actual >= target
        message = f"约束 {constraint_id}: {actual} >= {target}。"
    elif comparison == "gt":
        if target is None:
            return False, f"约束 {constraint_id} 的 target 无效。", evidence
        passed = actual > target
        message = f"约束 {constraint_id}: {actual} > {target}。"
    elif comparison == "lt":
        if target is None:
            return False, f"约束 {constraint_id} 的 target 无效。", evidence
        passed = actual < target
        message = f"约束 {constraint_id}: {actual} < {target}。"
    elif comparison == "between":
        if lower is None or upper is None or lower > upper:
            return False, f"约束 {constraint_id} 的 lower/upper 无效。", evidence
        passed = lower <= actual <= upper
        message = f"约束 {constraint_id}: {lower} <= {actual} <= {upper}。"
    else:
        return False, f"约束 {constraint_id} 的 comparison 不受支持。", evidence
    evidence.update({"actual": actual, "target": target, "tolerance": tolerance, "lower": lower, "upper": upper})
    return passed, message, evidence


def _metrics_valid(metrics: object) -> bool:
    return bool(metrics) and isinstance(metrics, list) and all(
        isinstance(metric, dict)
        and isinstance(metric.get("id"), str)
        and isinstance(metric.get("label"), str)
        and _as_number(metric.get("value")) is not None
        and isinstance(metric.get("unit"), str)
        and isinstance(metric.get("explanation"), str)
        for metric in metrics
    )


def _contract_requires_relief_validation(work_dir: Path) -> bool:
    contract = _read_json(work_dir / "problem_contract.json")
    if contract is None:
        return False
    requirements = contract.get("required_requirements", [])
    return any(
        isinstance(item, dict) and item.get("key") == "relief_valve_control"
        for item in requirements
    )


def _contract_requires_q1_valve_duration_outputs(work_dir: Path) -> bool:
    contract = _read_json(work_dir / "problem_contract.json")
    if contract is None:
        return False
    return any(
        isinstance(item, dict) and item.get("key") == "problem1_valve_duration_outputs"
        for item in contract.get("required_requirements", [])
    )


def _contract_requires_linear_programming_evidence(work_dir: Path) -> bool:
    contract = _read_json(work_dir / "problem_contract.json")
    return bool(contract) and any(
        isinstance(item, dict) and item.get("plugin") == "linear_programming"
        for item in contract.get("required_requirements", [])
    )


def _pressure_stability_issues(work_dir: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Reject visibly unstable controls for contracts that explicitly target 100 MPa."""
    contract = _read_json(work_dir / "problem_contract.json")
    requirements = contract.get("required_requirements", []) if contract else []
    if not any(
        isinstance(item, dict) and item.get("key") == "target_pressure_100_mpa"
        for item in requirements
    ):
        return []
    max_peak_to_peak = 15.0
    metrics = manifest.get("metrics", [])
    if not isinstance(metrics, list):
        return []
    issues: list[dict[str, Any]] = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        label = metric.get("label")
        value = _as_number(metric.get("value"))
        if not isinstance(label, str) or "压力波动" not in label or metric.get("unit") != "MPa":
            continue
        metric_id = metric.get("id", "unknown")
        passed = value is not None and value <= max_peak_to_peak
        issues.append(_issue(
            f"pressure_stability.{metric_id}",
            passed,
            (
                f"{label} {value} MPa 未超过 100 MPa 目标下的 15 MPa 稳定性上限。"
                if passed
                else f"{label} 为 {value} MPa，超过 100 MPa 目标下的 15 MPa 稳定性上限。"
            ),
            {"target_pressure_mpa": 100.0, "max_peak_to_peak_mpa": max_peak_to_peak, "actual": value},
        ))
    return issues


def _subtask_evidence_issues(
    subtask_id: str,
    item: dict[str, Any],
    *,
    relief_validation_required: bool,
    q1_valve_duration_outputs_required: bool,
    linear_programming_evidence_required: bool,
) -> list[dict[str, Any]]:
    """Reject result labels that openly admit no formal numerical solve occurred.

    A matching hash only proves that a CSV was written.  It does not turn an
    inherited estimate into a simulation/optimization result.  The Coder is
    required to record subtask metrics, including a balance residual, so this
    check remains independent of the Writer's prose.
    """
    metrics = item.get("metrics")
    if not _metrics_valid(metrics):
        return [_issue(
            f"{subtask_id}.metrics",
            False,
            f"{subtask_id} 的 metrics 必须非空且包含 id、label、有限 value、unit 和 explanation。",
        )]

    assert isinstance(metrics, list)
    descriptions = "\n".join(
        f"{metric['label']}\n{metric['explanation']}" for metric in metrics
    )
    unsupported = [term for term in _UNSUPPORTED_RESULT_TERMS if term in descriptions]
    issues = [_issue(
        f"{subtask_id}.computed_evidence",
        not unsupported,
        (
            f"{subtask_id} 的指标来自实际计算。"
            if not unsupported
            else f"{subtask_id} 的正式指标含有“{'、'.join(unsupported)}”，不能作为已执行求解的证据。"
        ),
        {"unsupported_terms": unsupported},
    )]
    has_balance_residual = any(
        "残差" in metric["label"] or "守恒" in metric["label"]
        for metric in metrics
    )
    issues.append(_issue(
        f"{subtask_id}.balance_residual",
        has_balance_residual,
        (
            f"{subtask_id} 已报告质量/流量或等价守恒残差。"
            if has_balance_residual
            else f"{subtask_id} 缺少由真实数组计算的质量/流量（或等价守恒）残差。"
        ),
    ))

    if linear_programming_evidence_required:
        metric_text = "\n".join(
            " ".join(
                [
                    str(metric.get("id", "")),
                    str(metric.get("label", "")),
                    " ".join(str(alias) for alias in metric.get("aliases", [])),
                ]
            )
            for metric in metrics
        ).lower()
        has_objective = any(token in metric_text for token in ("objective", "目标", "利润", "成本"))
        has_decision = any(
            token in metric_text
            for token in ("optimal_", "decision", "最优解", "决策变量", "最优产量", "产量", "方案")
        )
        issues.append(_issue(
            f"{subtask_id}.linear_programming_solution_metrics",
            has_objective and has_decision,
            (
                f"{subtask_id} 已记录线性规划目标值与决策变量。"
                if has_objective and has_decision
                else f"{subtask_id} 的线性规划证据必须同时记录目标值和实际最优决策变量。"
            ),
            {"has_objective": has_objective, "has_decision": has_decision},
        ))

    if q1_valve_duration_outputs_required and subtask_id == "ques1":
        metric_ids = {metric["id"] for metric in metrics}
        missing = [
            label for metric_id, label in _Q1_REQUIRED_CONTROL_METRICS.items()
            if metric_id not in metric_ids
        ]
        issues.append(_issue(
            "ques1.valve_duration_outputs",
            not missing,
            (
                "问题一已记录两种稳态与三种过渡工况的单向阀开启时长。"
                if not missing
                else "问题一缺少必答单向阀控制指标：" + "、".join(missing) + "。"
            ),
            {"missing": missing, "required_metric_ids": sorted(_Q1_REQUIRED_CONTROL_METRICS)},
        ))

    if relief_validation_required and subtask_id == "ques3":
        opening_metrics = [
            metric for metric in metrics
            if "减压阀" in metric["label"] and "开启" in metric["label"]
        ]
        opened_in_disturbance_test = any(
            _as_number(metric["value"]) is not None and float(metric["value"]) > 0
            for metric in opening_metrics
        )
        issues.append(_issue(
            "ques3.relief_disturbance_evidence",
            opened_in_disturbance_test,
            (
                "问题三已在扰动/超压工况下记录减压阀实际开启证据。"
                if opened_in_disturbance_test
                else "问题三要求验证减压阀控制；必须在独立扰动/超压工况中记录至少一次实际开启，不能仅给阈值或零开启次数。"
            ),
            {"opening_metric_count": len(opening_metrics)},
        ))
    return issues


def _notebook_issues(work_dir: Path, *, has_execution_manifest: bool) -> list[dict[str, Any]]:
    notebook_path = work_dir / "notebook.ipynb"
    if not notebook_path.is_file():
        return [_issue("notebook", False, "缺少 notebook.ipynb，无法证明代码已执行。")]
    try:
        notebook = nbformat.read(notebook_path, as_version=4)
    except Exception as exc:
        return [_issue("notebook", False, "notebook.ipynb 无法解析。", {"error_type": type(exc).__name__})]
    code_cells = [cell for cell in notebook.cells if cell.get("cell_type") == "code"]
    error_cells = [
        index
        for index, cell in enumerate(notebook.cells)
        if cell.get("cell_type") == "code"
        and any(output.get("output_type") == "error" for output in cell.get("outputs", []))
    ]
    errors_are_reconciled = bool(error_cells) and has_execution_manifest
    return [
        _issue(
            "notebook_execution",
            bool(code_cells),
            "notebook 包含代码单元。" if code_cells else "notebook 没有任何代码单元。",
            {"code_cell_count": len(code_cells)},
        ),
        _issue(
            "notebook_errors",
            not error_cells or errors_are_reconciled,
            (
                "notebook 不含执行错误。"
                if not error_cells
                else "notebook 保留了历史执行错误；最终结果仍须由 execution_validation.json 的来源哈希和约束逐项证明。"
            ),
            {
                "error_cell_indices": error_cells,
                "reconciled_by_execution_manifest": errors_are_reconciled,
            },
        ),
    ]


def _manifest_issues(
    work_dir: Path,
    required_subtasks: list[str],
) -> list[dict[str, Any]]:
    manifest_path = work_dir / MANIFEST_NAME
    manifest = _read_json(manifest_path)
    if manifest is None:
        return [_issue("execution_manifest", False, f"缺少或无法读取 {MANIFEST_NAME}。")]

    subtasks = manifest.get("subtasks")
    if not isinstance(subtasks, list):
        return [_issue("execution_manifest", False, "execution_validation.json 的 subtasks 必须为数组。")]
    by_id = {
        item.get("id"): item
        for item in subtasks
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    issues: list[dict[str, Any]] = []
    missing = [subtask for subtask in required_subtasks if subtask not in by_id]
    issues.append(
        _issue(
            "required_subtasks",
            not missing,
            "所有正式问题都有执行验证记录。" if not missing else f"缺少正式问题的执行验证记录: {', '.join(missing)}。",
            {"required_subtasks": required_subtasks, "missing": missing},
        )
    )
    relief_validation_required = _contract_requires_relief_validation(work_dir)
    q1_valve_duration_outputs_required = _contract_requires_q1_valve_duration_outputs(work_dir)
    linear_programming_evidence_required = _contract_requires_linear_programming_evidence(work_dir)
    for subtask in required_subtasks:
        item = by_id.get(subtask)
        if not isinstance(item, dict):
            continue
        executed = item.get("executed") is True
        feasible = item.get("feasible") is True
        issues.append(_issue(f"{subtask}.executed", executed, f"{subtask} 已实际执行。" if executed else f"{subtask} 未证明已实际执行。"))
        issues.append(_issue(f"{subtask}.feasible", feasible, f"{subtask} 满足声明的约束。" if feasible else f"{subtask} 不可行或未验证，不得称为完成。"))
        constraints = item.get("constraints")
        if not isinstance(constraints, list) or not constraints:
            issues.append(_issue(f"{subtask}.constraints", False, f"{subtask} 缺少可计算的约束验证。"))
            continue
        for constraint in constraints:
            passed, message, evidence = _check_constraint(constraint, work_dir)
            constraint_id = constraint.get("id", "unknown") if isinstance(constraint, dict) else "unknown"
            issues.append(_issue(f"{subtask}.constraint.{constraint_id}", passed, message, evidence))

        issues.extend(_subtask_evidence_issues(
            subtask,
            item,
            relief_validation_required=relief_validation_required,
            q1_valve_duration_outputs_required=q1_valve_duration_outputs_required,
            linear_programming_evidence_required=linear_programming_evidence_required,
        ))

        figures = item.get("figures", [])
        if not isinstance(figures, list):
            issues.append(_issue(f"{subtask}.figures", False, f"{subtask} 的 figures 必须为数组。"))
            continue
        for index, figure in enumerate(figures):
            if not isinstance(figure, dict):
                issues.append(_issue(f"{subtask}.figure.{index}", False, "图表记录必须是对象。"))
                continue
            figure_path = _safe_source_path(work_dir, figure.get("path"))
            data_path = _safe_source_path(work_dir, figure.get("data_path"))
            expected_hash = figure.get("data_sha256")
            valid = (
                figure_path is not None
                and figure_path.is_file()
                and data_path is not None
                and data_path.is_file()
                and isinstance(expected_hash, str)
                and _sha256(data_path) == expected_hash
            )
            issues.append(
                _issue(
                    f"{subtask}.figure.{index}",
                    valid,
                    "图表及其数据来源可复查。" if valid else "图表或图表数据来源缺失、越界或哈希不一致。",
                    {"path": figure.get("path"), "data_path": figure.get("data_path")},
                )
            )

    metrics = manifest.get("metrics", [])
    metrics_valid = _metrics_valid(metrics)
    issues.append(
        _issue(
            "metrics",
            metrics_valid,
            "关键指标格式有效。" if metrics_valid else "metrics 必须非空且包含 id、label、有限 value、unit 和 explanation。",
            {"metric_count": len(metrics) if isinstance(metrics, list) else 0},
        )
    )
    issues.extend(_pressure_stability_issues(work_dir, manifest))
    return issues


def write_frozen_results_from_execution_validation(
    work_dir: str | os.PathLike[str],
) -> Path:
    """Freeze the successful execution manifest for the Writer.

    This conversion is deliberately performed by trusted workflow code rather
    than the Writer.  The generated document follows ``result_integrity``'s
    strict schema and records hashes of every numerical source used by a
    constraint, plus the executed notebook itself.
    """
    root = Path(work_dir).resolve()
    manifest = _read_json(root / MANIFEST_NAME)
    if manifest is None:
        raise ValueError(f"缺少或无法读取 {MANIFEST_NAME}")

    source_entries: list[dict[str, str]] = []
    seen_sources: set[tuple[str, str]] = set()

    def add_source(relative_path: object, expected_hash: object, role: str) -> None:
        path = _safe_source_path(root, relative_path)
        if path is None or not path.is_file() or not isinstance(expected_hash, str):
            return
        relative = str(path.relative_to(root)).replace("\\", "/")
        key = (relative, expected_hash)
        if key not in seen_sources:
            seen_sources.add(key)
            source_entries.append(
                {"relative_path": relative, "sha256": expected_hash, "role": role}
            )

    for subtask in manifest.get("subtasks", []):
        if not isinstance(subtask, dict):
            continue
        for constraint in subtask.get("constraints", []):
            if isinstance(constraint, dict) and isinstance(constraint.get("source"), dict):
                source = constraint["source"]
                add_source(source.get("path"), source.get("sha256"), "constraint")
        for figure in subtask.get("figures", []):
            if isinstance(figure, dict):
                add_source(figure.get("data_path"), figure.get("data_sha256"), "figure_data")

    notebook_path = root / "notebook.ipynb"
    if notebook_path.is_file():
        add_source("notebook.ipynb", _sha256(notebook_path), "executed_code")

    # A metric name can legitimately recur across subtasks (for example each
    # scenario has a constraint residual).  The old flat projection silently
    # kept the last value, making the Writer's frozen fact block ambiguous.
    raw_metric_counts: dict[str, int] = {}
    for subtask in manifest.get("subtasks", []):
        if not isinstance(subtask, dict):
            continue
        for metric in subtask.get("metrics", []):
            if isinstance(metric, dict) and isinstance(metric.get("id"), str):
                raw_metric_counts[metric["id"]] = raw_metric_counts.get(metric["id"], 0) + 1

    metric_subtask_ids: dict[str, str] = {}
    for subtask in manifest.get("subtasks", []):
        if not isinstance(subtask, dict):
            continue
        subtask_id = str(subtask.get("id") or "")
        for metric in subtask.get("metrics", []):
            if isinstance(metric, dict) and isinstance(metric.get("id"), str):
                metric_subtask_ids.setdefault(metric["id"], subtask_id)

    metrics: list[dict[str, Any]] = []
    qualified_metric_ids: dict[tuple[str, str], str] = {}
    emitted_raw_ids: set[str] = set()
    # Preserve legacy manifest-level metrics first when they are unique.  They
    # may contain an independently computed aggregate not repeated under a
    # subtask, and this preserves backward-compatible report ordering.
    for metric in manifest.get("metrics", []):
        if not isinstance(metric, dict) or not isinstance(metric.get("id"), str):
            continue
        raw_id = metric["id"]
        if raw_metric_counts.get(raw_id, 0) > 1:
            continue
        subtask_id = metric_subtask_ids.get(raw_id, "")
        qualified_metric_ids[(subtask_id, raw_id)] = raw_id
        metrics.append(
            {
                "id": raw_id,
                "base_id": raw_id,
                "subtask_id": subtask_id or None,
                "label": metric.get("label"),
                "aliases": metric.get("aliases", []),
                "value": metric.get("value"),
                "unit": metric.get("unit"),
                "explanation": metric.get("explanation"),
            }
        )
        emitted_raw_ids.add(raw_id)

    for subtask in manifest.get("subtasks", []):
        if not isinstance(subtask, dict):
            continue
        subtask_id = str(subtask.get("id") or "")
        for metric in subtask.get("metrics", []):
            if not isinstance(metric, dict) or not isinstance(metric.get("id"), str):
                continue
            raw_id = metric["id"]
            metric_id = (
                f"{subtask_id}.{raw_id}"
                if raw_metric_counts.get(raw_id, 0) > 1 and subtask_id
                else raw_id
            )
            qualified_metric_ids[(subtask_id, raw_id)] = metric_id
            if raw_metric_counts.get(raw_id, 0) == 1 and raw_id in emitted_raw_ids:
                continue
            metrics.append(
                {
                    "id": metric_id,
                    "base_id": raw_id,
                    "subtask_id": subtask_id or None,
                    "label": metric.get("label"),
                    "aliases": metric.get("aliases", []),
                    "value": metric.get("value"),
                    "unit": metric.get("unit"),
                    "explanation": metric.get("explanation"),
                }
            )
    metric_ids = [metric["id"] for metric in metrics if isinstance(metric.get("id"), str)]
    subtasks = [
        {"id": item.get("id"), "feasible": item.get("feasible")}
        for item in manifest.get("subtasks", [])
        if isinstance(item, dict)
    ]
    figures = []
    for subtask in manifest.get("subtasks", []):
        if not isinstance(subtask, dict):
            continue
        for figure in subtask.get("figures", []):
            if isinstance(figure, dict) and isinstance(figure.get("path"), str):
                raw_figure_metric_ids = figure.get("metric_ids", [])
                figure_subtask_id = str(subtask.get("id") or "")
                figures.append(
                    {
                        "path": figure["path"],
                        "metric_ids": [
                            qualified_metric_ids.get((figure_subtask_id, str(metric_id)), str(metric_id))
                            for metric_id in raw_figure_metric_ids
                        ] if isinstance(raw_figure_metric_ids, list) else metric_ids,
                        "subtask": figure_subtask_id or None,
                    }
                )
    document = {
        "schema": "mathmodel.result-freeze",
        "version": 1,
        "metrics": metrics,
        "sources": source_entries,
        "subtasks": subtasks,
        "figures": figures,
        "executed_code_sources": ["notebook.ipynb"] if notebook_path.is_file() else [],
        "generated_from": MANIFEST_NAME,
    }
    output = root / FREEZE_NAME
    with output.open("w", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
    return output


def validate_execution_artifacts(
    work_dir: str | os.PathLike[str],
    *,
    required_subtasks: list[str] | None = None,
    require_manifest: bool = True,
) -> dict[str, Any]:
    """Check notebook execution and machine-readable feasibility evidence.

    ``require_manifest=False`` is intentionally limited to the immediate
    Coder-to-Writer handoff.  Completion and submission audit must keep the
    default strict mode.
    """
    root = Path(work_dir).resolve()
    required = required_subtasks or []
    has_execution_manifest = _read_json(root / MANIFEST_NAME) is not None
    issues = _notebook_issues(root, has_execution_manifest=has_execution_manifest)
    if require_manifest:
        issues.extend(_manifest_issues(root, required))
    passed = all(issue["passed"] for issue in issues)
    return {
        "schema_version": "mathmodel.execution-validation-report.v1",
        "generated_at": datetime.datetime.now().isoformat(),
        "work_dir": str(root),
        "status": "PASS" if passed else "FAIL",
        "required_subtasks": required,
        "checks": issues,
    }


def write_execution_validation_report(
    work_dir: str | os.PathLike[str],
    *,
    required_subtasks: list[str] | None = None,
    require_manifest: bool = True,
) -> dict[str, Any]:
    report = validate_execution_artifacts(
        work_dir,
        required_subtasks=required_subtasks,
        require_manifest=require_manifest,
    )
    report_path = Path(work_dir) / REPORT_NAME
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    return report
