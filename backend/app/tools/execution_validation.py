"""Execution and feasibility gate for generated mathematical-modeling tasks.

The workflow previously treated a natural-language Coder response as sufficient
evidence of success.  This module makes execution evidence explicit: a final
task must have a clean notebook and a machine-readable validation manifest
whose constraints can be checked without trusting the Writer's prose.
"""

from __future__ import annotations

import csv
import datetime
import decimal
import hashlib
import json
import math
import os
import re
import platform
import sys
from pathlib import Path
from typing import Any

import nbformat
import ast


REPORT_NAME = "execution_validation_report.json"
MANIFEST_NAME = "execution_validation.json"
FREEZE_NAME = "frozen_results.json"
REPRODUCIBILITY_NAME = "reproducibility_manifest.json"
MANIFEST_SCHEMA_V2 = "mathmodel.execution-validation.v2"
_UNSUPPORTED_RESULT_TERMS = ("估计", "沿用问题", "直接取")
_Q1_REQUIRED_CONTROL_METRICS = {
    "q1_steady_100_open_duration": "100 MPa 稳态开启时长",
    "q1_steady_150_open_duration": "150 MPa 稳态开启时长",
    "q1_transition_2s_open_duration": "2 秒过渡开启时长",
    "q1_transition_5s_open_duration": "5 秒过渡开启时长",
    "q1_transition_10s_open_duration": "10 秒过渡开启时长",
}
_Q3_TIMING_METRIC_RE = re.compile(
    r"(?:phase|timing|offset|相位|错峰|错相|同步|时序|时间差)", re.IGNORECASE
)
_Q3_ALTERNATIVE_METRIC_RE = re.compile(
    r"(?:alternate|alternative|offset[_ -]?50|另一相位|备选|错峰|错相)", re.IGNORECASE
)
_Q3_SELECTION_METRIC_RE = re.compile(
    r"(?:objective|score|selection|strategy|目标|评分|策略|权衡)", re.IGNORECASE
)
_Q3_SELECTED_METRIC_RE = re.compile(
    r"(?:selected|chosen|primary|主策略|选定|最终)", re.IGNORECASE
)
_Q3_ALTERNATE_METRIC_RE = re.compile(
    r"(?:alternate|alternative|offset[_ -]?50|另一相位|备选|错峰|错相)",
    re.IGNORECASE,
)
_EVIDENCE_COMPARISONS = {"abs_diff_lte", "lte", "gte", "gt", "lt", "between"}
_PLAN_COMPARISONS = {
    "le": "lte",
    "lt": "lt",
    "ge": "gte",
    "gt": "gt",
    "eq": "abs_diff_lte",
    "within": "lte",
}


def _canonical_evidence_comparison(comparison: object) -> object:
    """Map the ModelPlan-only exact comparator to the evidence protocol.

    ``AcceptanceMetric`` uses ``eq`` while execution evidence deliberately
    uses the more explicit ``abs_diff_lte`` form.  Keep the persisted evidence
    on the latter vocabulary, so a direct ``eq`` tool payload cannot bypass
    the normal source/hash checks or create a second comparison dialect.
    """
    return "abs_diff_lte" if comparison == "eq" else comparison


def _unsupported_comparison_hint(comparison: object) -> str:
    """Explain a rejected comparison so the next attempt can differ.

    The recorder gets three attempts per subtask.  A message that names neither
    the rejected value nor the legal set gives the model nothing to change, so
    it resubmits the same payload until the breaker fires.  The common cause is
    copying the ModelPlan comparator (``le``/``ge``) into the evidence call,
    which expects (``lte``/``gte``) — so name that translation explicitly.
    """
    allowed = "、".join(sorted(_EVIDENCE_COMPARISONS))
    received = comparison if isinstance(comparison, str) else type(comparison).__name__
    mapped = _PLAN_COMPARISONS.get(received) if isinstance(comparison, str) else None
    if mapped is not None:
        return (
            f"收到 ModelPlan 比较符 '{received}'，证据协议应改写为 '{mapped}'；"
            f"允许值为 {allowed}。"
        )
    return f"收到 '{received}'；允许值为 {allowed}。"
_SOURCE_NUMBER = re.compile(r"(?<![\w.])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
_BALANCE_REQUIREMENT_KEYS = (
    "mass_balance",
    "material_balance",
    "flow_balance",
    "energy_balance",
    "conservation_residual",
)
_BALANCE_REQUIREMENT_PATTERN = re.compile(
    r"(?:质量|物料|流量|能量).{0,8}(?:守恒|平衡)|(?:守恒|平衡).{0,8}(?:质量|物料|流量|能量)"
)
_ANGLE_VALUE_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:°|度)")
_PRESSURE_TARGET_REQUIREMENT_RE = re.compile(r"^target_pressure_[\d_]+_mpa$")
_PRESSURE_DEVIATION_LABEL_RE = re.compile(
    r"(?:峰峰值|峰-峰值|波动|偏差|超调|残差|振幅|方均根|均方根|RMS|最大\s*偏离)",
    re.IGNORECASE,
)
# Numerical-convergence quantities (difference between two step sizes, mesh
# refinement deltas, solver tolerances) describe how well the ODE was solved,
# not how much the solution's pressure actually swings.  Accepting them as
# deviation evidence lets a 0.05 MPa convergence delta stand in for a 68 MPa
# peak-to-peak oscillation, so they are excluded by name.
_PRESSURE_CONVERGENCE_LABEL_RE = re.compile(
    r"(?:收敛|convergence|dt[_\s-]|步长|网格|加密|细化|refine|tolerance|容差|离散化误差)",
    re.IGNORECASE,
)
_INCIDENT_ANGLE_PAIR_RE = re.compile(
    r"入射角(?:分别)?(?:为|是)?\s*(\d+(?:\.\d+)?)\s*(?:°|度)"
    r"\s*(?:和|与|、|及)\s*(\d+(?:\.\d+)?)\s*(?:°|度)",
    re.IGNORECASE,
)


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


def _problem_parameter_issues(work_dir: Path) -> list[dict[str, Any]]:
    """Cross-check explicit problem angles against the executed parameter audit."""
    request = _read_json(work_dir / "task_request.json")
    problem_text = str(request.get("ques_all") or "") if request else ""
    angle_pairs = _INCIDENT_ANGLE_PAIR_RE.findall(problem_text)
    expected_angles = sorted(
        {float(value) for pair in angle_pairs for value in pair}
    )
    if len(expected_angles) < 2:
        return []

    # 每道正式题写各自的 `{quesN}_input_parameter_audit.csv`，避免共享单一文件被
    # 后写题覆盖而使先写题的证据 sha256 失效。这里聚合所有 per-question 审计文件
    # （并兼容历史上的单一 input_parameter_audit.csv），只要任一文件覆盖了题面
    # 实测角度即视为通过。
    audit_paths = sorted(work_dir.glob("*_input_parameter_audit.csv"))
    legacy_audit = work_dir / "input_parameter_audit.csv"
    if legacy_audit.is_file():
        audit_paths.append(legacy_audit)
    if not audit_paths:
        return [
            _issue(
                "problem_parameter.incident_angles",
                False,
                "题面给出多个实测入射角，但缺少 *_input_parameter_audit.csv 证明算法使用了这些角度。",
                {"expected_angles_deg": expected_angles},
            )
        ]
    rows: list[dict[str, Any]] = []
    for audit_path in audit_paths:
        try:
            with audit_path.open(encoding="utf-8-sig", newline="") as handle:
                rows.extend(csv.DictReader(handle))
        except (OSError, csv.Error) as exc:
            return [
                _issue(
                    "problem_parameter.incident_angles",
                    False,
                    f"{audit_path.name} 无法解析。",
                    {"error_type": type(exc).__name__},
                )
            ]

    angle_rows = [
        row for row in rows if "入射角" in " ".join(str(value) for value in row.values())
    ]
    audited_angles: set[float] = set()
    for row in angle_rows:
        text = " ".join(str(value) for value in row.values())
        audited_angles.update(float(value) for value in _ANGLE_VALUE_RE.findall(text))
        # A numeric value column often omits the degree symbol. Preserve only
        # standalone numbers from rows explicitly labelled as incident angle.
        for value in row.values():
            if re.fullmatch(r"\s*[-+]?\d+(?:\.\d+)?\s*", str(value)):
                audited_angles.add(float(value))
    missing = [angle for angle in expected_angles if angle not in audited_angles]
    false_vertical_claims = [
        row
        for row in angle_rows
        if re.search(r"题面.{0,8}(?:垂直入射|0\s*[°度])", " ".join(str(v) for v in row.values()))
    ]
    passed = not missing and not false_vertical_claims
    return [
        _issue(
            "problem_parameter.incident_angles",
            passed,
            (
                "参数审计完整保留题面给定的实测入射角。"
                if passed
                else "参数审计遗漏或改写了题面实测入射角；相关厚度结果不得冻结。"
            ),
            {
                "expected_angles_deg": expected_angles,
                "audited_angles_deg": sorted(audited_angles),
                "missing_angles_deg": missing,
                "false_vertical_claim_count": len(false_vertical_claims),
            },
        )
    ]


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


def _source_contains_number(path: Path, expected: float) -> bool:
    """Return whether a text result file contains ``expected`` within display rounding.

    The evidence writer accepts CSV/JSON/TXT-style outputs, not opaque claims.
    A relative tolerance of 5e-4 permits normal four-significant-digit display
    rounding (for example 0.1543 versus 0.154328) without accepting a different
    result such as 10562.36 versus 2731.80.
    """
    try:
        text = path.read_bytes().decode("utf-8-sig", errors="ignore")
    except OSError:
        return False
    tolerance = max(1e-9, abs(expected) * 5e-4)
    for match in _SOURCE_NUMBER.finditer(text):
        try:
            candidate = float(match.group(0))
        except ValueError:
            continue
        if math.isfinite(candidate) and abs(candidate - expected) <= tolerance:
            return True
    return False


def _planned_acceptance_metrics(root: Path, subtask_id: str) -> list[dict[str, Any]]:
    plan = _read_json(root / "modeler_plan.json")
    if not plan:
        return []
    model_plan = plan.get("model_plan", plan)
    if not isinstance(model_plan, dict):
        return []
    subtasks = model_plan.get("subtasks", {})
    subtask = subtasks.get(subtask_id, {}) if isinstance(subtasks, dict) else {}
    metrics = subtask.get("acceptance_metrics", []) if isinstance(subtask, dict) else []
    return [item for item in metrics if isinstance(item, dict)] if isinstance(metrics, list) else []


def _planned_subtask(root: Path, subtask_id: str) -> dict[str, Any]:
    """Read one structured ModelPlan subtask without trusting free-form prose.

    The plan already declares which numerical artefacts and diagnostics make a
    result reviewable.  Completion used to enforce only the three selected
    acceptance constraints, allowing the Coder to omit or silently degenerate
    the rest of that promised evidence.
    """
    plan = _read_json(root / "modeler_plan.json")
    if not plan:
        return {}
    model_plan = plan.get("model_plan", plan)
    if not isinstance(model_plan, dict):
        return {}
    subtasks = model_plan.get("subtasks", {})
    subtask = subtasks.get(subtask_id, {}) if isinstance(subtasks, dict) else {}
    return subtask if isinstance(subtask, dict) else {}


def _planned_expected_artifacts(root: Path, subtask_id: str) -> list[dict[str, Any]]:
    artifacts = _planned_subtask(root, subtask_id).get("expected_artifacts", [])
    return [item for item in artifacts if isinstance(item, dict)] if isinstance(artifacts, list) else []


def _plan_requires_identifiability_evidence(root: Path, subtask_id: str) -> bool:
    """Return whether the ModelPlan explicitly promises a stability diagnosis.

    This is intentionally driven by the task-owned plan rather than a domain
    threshold: optics, curve fitting and optimisation can all have local
    branches or active-bound solutions.  The gate asks for an auditable status,
    not for a preordained conclusion or a universal error tolerance.
    """
    subtask = _planned_subtask(root, subtask_id)
    text = "\n".join(
        str(subtask.get(field, ""))
        for field in ("method", "constraints", "visualization")
    )
    for artifact in _planned_expected_artifacts(root, subtask_id):
        text += "\n" + str(artifact.get("path", "")) + "\n" + str(artifact.get("description", ""))
    lowered = text.lower()
    return any(token in text or token in lowered for token in (
        "可辨识", "多组初值", "多初值", "剖面似然", "初值分支", "bootstrap", "identifiability",
    ))


def _csv_numeric_columns(path: Path) -> tuple[dict[str, list[float]], str | None]:
    """Read finite numeric CSV columns for low-cost evidence sanity checks."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                return {}, "CSV 缺少表头。"
            values = {name: [] for name in reader.fieldnames if isinstance(name, str)}
            row_count = 0
            for row in reader:
                row_count += 1
                for name, raw_value in row.items():
                    value = _as_number(_parse_csv_number(raw_value))
                    if value is not None:
                        values.setdefault(name or "", []).append(value)
    except (OSError, csv.Error, UnicodeError) as exc:
        return {}, f"CSV 无法解析：{type(exc).__name__}。"
    if row_count == 0:
        return {}, "CSV 没有数据行。"
    return {name: column for name, column in values.items() if column}, None


def _parse_csv_number(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = float(value.strip())
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


_TABLE_PASS_STATUSES = {"是", "通过", "满足", "达标", "pass", "passed", "true"}
_TABLE_FAIL_STATUSES = {"否", "不通过", "未通过", "不满足", "不达标", "fail", "failed", "false"}


def _parse_table_comparison(value: object) -> tuple[str, float] | None:
    """Parse a compact human-facing threshold such as ``≤1.0``.

    These tables are ordinary Coder output, so they are not trusted as a
    feasibility declaration.  We only use their explicit numeric cells to
    cross-check the displayed pass/fail text and bind ModelPlan metrics to an
    exact source value.
    """
    if not isinstance(value, str):
        return None
    text = value.strip().replace(" ", "")
    match = re.fullmatch(r"(≤|<=|≥|>=|<|>|=|==)([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)", text)
    if not match:
        return None
    comparison = {
        "≤": "lte", "<=": "lte", "≥": "gte", ">=": "gte",
        "<": "lt", ">": "gt", "=": "eq", "==": "eq",
    }[match.group(1)]
    target = _parse_csv_number(match.group(2))
    return (comparison, target) if target is not None else None


def _table_status(value: object) -> bool | None:
    if not isinstance(value, str):
        return None
    normalised = value.strip().lower()
    if normalised in _TABLE_PASS_STATUSES:
        return True
    if normalised in _TABLE_FAIL_STATUSES:
        return False
    return None


def _deduce_float_tolerance(
    target: float | int | str | None,
    *,
    metric_kind: str | None = None,
    abs_tol: float | None = None,
    rel_tol: float | None = None,
    tolerance: float | None = None,
    precision: int | None = None,
) -> tuple[float, float]:
    """根据展示小数位数与显式精度推导严密的浮点绝对容差，防止宽松相对容差放过明显错误结果。
    默认相对容差设为 0.0，避免大数容差被无限放大。
    """
    effective_rel_tol = float(rel_tol) if rel_tol is not None and rel_tol >= 0 else 0.0
    if tolerance is not None and tolerance > 0:
        return float(tolerance), effective_rel_tol
    if abs_tol is not None and abs_tol > 0:
        return float(abs_tol), effective_rel_tol
    if metric_kind in ("integer", "discrete", "flag", "boolean") or precision == 0:
        return 1e-6, effective_rel_tol
    if precision is not None and precision > 0:
        return 0.55 * (10 ** (-precision)), effective_rel_tol
    if target is None:
        return 1e-6, effective_rel_tol

    try:
        d = decimal.Decimal(str(target).strip())
        # 若数值数学上为整数（如 2200 或 2200.0）且未显式指定正小数位数，按整数机器容差 1e-6 处理
        if d == d.to_integral():
            return 1e-6, effective_rel_tol
        exp = d.as_tuple().exponent
        if isinstance(exp, int) and exp < 0:
            decimals = -exp
            # 0.55 * 10^-d 允许合理四舍五入（例如 2366.6667 vs 2366.67 差值 0.0033 <= 0.0055）
            deduced_abs = 0.55 * (10 ** (-decimals))
            return deduced_abs, effective_rel_tol
    except Exception:
        pass

    return 1e-6, effective_rel_tol


def _evaluate_simple_comparison(
    actual: float,
    comparison: str,
    target: float,
    *,
    metric_kind: str | None = None,
    abs_tol: float | None = None,
    rel_tol: float | None = None,
    tolerance: float | None = None,
    precision: int | None = None,
) -> bool:
    effective_abs_tol, effective_rel_tol = _deduce_float_tolerance(
        target,
        metric_kind=metric_kind,
        abs_tol=abs_tol,
        rel_tol=rel_tol,
        tolerance=tolerance,
        precision=precision,
    )
    if comparison in {"eq", "abs_diff_lte"}:
        return math.isclose(actual, target, rel_tol=effective_rel_tol, abs_tol=effective_abs_tol)
    if comparison == "lte":
        return actual <= target or math.isclose(actual, target, rel_tol=effective_rel_tol, abs_tol=effective_abs_tol)
    if comparison == "gte":
        return actual >= target or math.isclose(actual, target, rel_tol=effective_rel_tol, abs_tol=effective_abs_tol)
    if comparison == "lt":
        return actual < target
    if comparison == "gt":
        return actual > target
    raise KeyError(comparison)




def _read_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str], str | None]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = [field for field in (reader.fieldnames or []) if isinstance(field, str)]
            if not fields:
                return [], [], "CSV 缺少表头。"
            return list(reader), fields, None
    except (OSError, csv.Error, UnicodeError) as exc:
        return [], [], f"CSV 无法解析：{type(exc).__name__}。"


def _validate_declared_table_statuses(root: Path, subtask_id: str) -> list[str]:
    """Reject CSV rows whose claimed status contradicts their own numbers."""
    planned = _planned_acceptance_metrics(root, subtask_id)
    planned_by_id = {
        item.get("key"): item
        for item in planned
        if isinstance(item, dict) and isinstance(item.get("key"), str)
    }
    definitions = (
        (f"{subtask_id}_acceptance_metrics.csv", "指标ID", "数值", "目标值", None, "是否达标"),
        (f"{subtask_id}_constraint_check.csv", "约束ID", "左端值", "比较", "右端值", "状态"),
    )
    errors: list[str] = []
    for filename, id_column, actual_column, comparison_column, target_column, status_column in definitions:
        path = root / filename
        if not path.is_file():
            continue
        rows, fields, read_error = _read_csv_rows(path)
        if read_error:
            errors.append(f"{filename} {read_error}")
            continue
        required = {id_column, actual_column, comparison_column, status_column}
        if target_column is not None:
            required.add(target_column)
        if not required.issubset(fields):
            continue  # A nonstandard scratch CSV is not treated as an acceptance table.
        for index, row in enumerate(rows, start=2):
            actual = _parse_csv_number(row.get(actual_column))
            status = _table_status(row.get(status_column))
            metric_id = row.get(id_column, "").strip()
            matched_plan = planned_by_id.get(metric_id)
            if target_column is None:
                parsed = _parse_table_comparison(row.get(comparison_column))
                displayed_threshold = row.get(comparison_column)
            else:
                operator = row.get(comparison_column)
                target_value = _parse_csv_number(row.get(target_column))
                parsed = (
                    _parse_table_comparison(f"{operator}{target_value}")
                    if target_value is not None
                    else None
                )
                displayed_threshold = f"{operator}{row.get(target_column)}"
            if actual is None or status is None or parsed is None:
                continue
            comparison, target = parsed
            metric_kind = matched_plan.get("metric_kind") if matched_plan else None
            precision = _as_number(matched_plan.get("precision")) if matched_plan else None
            abs_tol = _as_number(matched_plan.get("abs_tol")) if matched_plan else None
            rel_tol = _as_number(matched_plan.get("rel_tol")) if matched_plan else None
            computed = _evaluate_simple_comparison(
                actual,
                comparison,
                target,
                metric_kind=str(metric_kind) if metric_kind else None,
                precision=int(precision) if precision is not None else None,
                abs_tol=abs_tol,
                rel_tol=rel_tol,
            )
            if computed != status:
                label_id = metric_id or f"第 {index} 行"
                expected = "通过" if computed else "不通过"
                errors.append(
                    f"{filename} 中 {label_id}: 数值 {actual} 与目标 {displayed_threshold!r} "
                    f"的计算结果为{expected}，却标为 {row.get(status_column)!r}。"
                )
    return errors


def _bind_plan_constraints_from_acceptance_table(
    root: Path,
    subtask_id: str,
    constraints: object,
) -> tuple[object, list[str]]:
    """Source ModelPlan acceptance constraints from the standard result CSV.

    A model must not be able to make a constraint unverifiable merely by
    rounding a value in a tool call.  When the standard table is present, the
    backend owns the actual value, direction, target and source binding.
    """
    planned = _planned_acceptance_metrics(root, subtask_id)
    table_path = root / f"{subtask_id}_acceptance_metrics.csv"
    if not planned or not table_path.is_file() or not isinstance(constraints, list):
        return constraints, []
    rows, fields, read_error = _read_csv_rows(table_path)
    if read_error:
        return constraints, [f"{table_path.name} {read_error}"]
    required_columns = {"指标ID", "数值"}
    if not required_columns.issubset(fields):
        return constraints, []
    by_id = {
        row.get("指标ID", "").strip(): row
        for row in rows
        if isinstance(row.get("指标ID"), str) and row.get("指标ID", "").strip()
    }
    planned_ids = {
        item.get("key") for item in planned
        if isinstance(item.get("key"), str) and item.get("key")
    }
    bound = [
        dict(item) for item in constraints
        if not (isinstance(item, dict) and item.get("id") in planned_ids)
    ]
    errors: list[str] = []
    for expected in planned:
        metric_id = expected.get("key")
        if not isinstance(metric_id, str) or not metric_id:
            continue
        aliases = {metric_id}
        if metric_id.endswith("_index"):
            aliases.add(metric_id.removesuffix("_index"))
        candidates = [
            row for row_id, row in by_id.items()
            if any(row_id == alias or row_id.startswith(f"{alias}_") for alias in aliases)
        ]
        if not candidates:
            errors.append(f"{table_path.name} 缺少 ModelPlan 验收指标 {metric_id}。")
            continue
        plan_comparison = expected.get("comparator")
        comparison = _PLAN_COMPARISONS.get(str(plan_comparison))
        target = _as_number(expected.get("target"))
        metric_kind = expected.get("metric_kind")
        precision = _as_number(expected.get("precision"))
        abs_tol = _as_number(expected.get("abs_tol"))
        rel_tol = _as_number(expected.get("rel_tol"))
        deduced_abs, deduced_rel = _deduce_float_tolerance(
            target,
            metric_kind=str(metric_kind) if metric_kind else None,
            precision=int(precision) if precision is not None else None,
            abs_tol=abs_tol,
            rel_tol=rel_tol,
        )
        if comparison is None or target is None:
            errors.append(f"ModelPlan 验收指标 {metric_id} 的 comparator/target 不可机检。")
            continue
        values: list[tuple[float, dict[str, str]]] = []
        for row in candidates:
            actual_value = _parse_csv_number(row.get("数值"))
            row_id = row.get("指标ID", metric_id)
            if actual_value is None:
                errors.append(f"{table_path.name} 中 {row_id} 的数值不是有限数值。")
                continue
            displayed = _parse_table_comparison(row.get("目标值"))
            if displayed is not None:
                displayed_comparison, displayed_target = displayed
                displayed_comparison = _canonical_evidence_comparison(displayed_comparison)
                if displayed_comparison != comparison or not math.isclose(
                    displayed_target, target, rel_tol=deduced_rel, abs_tol=deduced_abs
                ):
                    errors.append(
                        f"{table_path.name} 中 {row_id} 的目标 {row.get('目标值')!r} "
                        f"与 ModelPlan 的 {plan_comparison} {target} 不一致。"
                    )
            else:
                displayed_target = _parse_csv_number(row.get("目标值"))
                if displayed_target is not None and not math.isclose(
                    displayed_target, target, rel_tol=deduced_rel, abs_tol=deduced_abs
                ):
                    errors.append(
                        f"{table_path.name} 中 {row_id} 的目标 {row.get('目标值')!r} "
                        f"与 ModelPlan 的 {target} 不一致。"
                    )
            declared_status = _table_status(row.get("是否达标"))
            if declared_status is not None:
                computed_status = _evaluate_simple_comparison(
                    actual_value,
                    {"abs_diff_lte": "eq"}.get(comparison, comparison),
                    target,
                    metric_kind=str(metric_kind) if metric_kind else None,
                    precision=int(precision) if precision is not None else None,
                    abs_tol=abs_tol,
                    rel_tol=rel_tol,
                )
                if computed_status != declared_status:
                    errors.append(
                        f"{table_path.name} 中 {row_id}: 数值 {actual_value} 按 ModelPlan "
                        f"{plan_comparison} {target} 应为{'通过' if computed_status else '不通过'}，"
                        f"却标为 {row.get('是否达标')!r}。"
                    )
            values.append((actual_value, row))
        if not values:
            continue
        if comparison in {"lte", "lt"}:
            actual, selected_row = max(values, key=lambda item: item[0])
        elif comparison in {"gte", "gt"}:
            actual, selected_row = min(values, key=lambda item: item[0])
        elif comparison == "abs_diff_lte":
            actual, selected_row = max(values, key=lambda item: abs(item[0] - target))
        else:
            actual, selected_row = values[0]
        constraint: dict[str, Any] = {
            "id": metric_id,
            "actual": actual,
            "comparison": comparison,
            "target": target,
            "source_path": table_path.name,
            "tolerance": deduced_abs,
            "abs_tol": deduced_abs,
            "rel_tol": deduced_rel,
        }
        if metric_kind is not None:
            constraint["metric_kind"] = str(metric_kind)
        if precision is not None:
            constraint["precision"] = int(precision)
        if abs_tol is not None:
            constraint["abs_tol"] = float(abs_tol)
        if rel_tol is not None:
            constraint["rel_tol"] = float(rel_tol)
        unit = selected_row.get("单位")
        if isinstance(unit, str) and unit.strip():
            constraint["unit"] = unit.strip()

        bound.append(constraint)

    return bound, errors


def _bind_records_to_acceptance_table(
    root: Path,
    subtask_id: str,
    records: object,
    *,
    value_field: str,
) -> tuple[object, list[str]]:
    """Replace LLM-typed values/sources with exact standard-table cells.

    Scenario metrics are useful paper-facing detail, but their numeric source
    must be the acceptance table that records the same row.  This removes a
    second avoidable failure mode where an LLM names the right value but cites
    an unrelated summary CSV that does not contain its full precision.
    """
    table_path = root / f"{subtask_id}_acceptance_metrics.csv"
    if not table_path.is_file() or not isinstance(records, list):
        return records, []
    rows, fields, read_error = _read_csv_rows(table_path)
    if read_error:
        return records, [f"{table_path.name} {read_error}"]
    if not {"指标ID", "数值"}.issubset(fields):
        return records, []
    values = {
        row.get("指标ID", "").strip(): _parse_csv_number(row.get("数值"))
        for row in rows
        if isinstance(row.get("指标ID"), str) and row.get("指标ID", "").strip()
    }
    bound: list[object] = []
    errors: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            bound.append(record)
            continue
        record_id = record.get("id")
        if not isinstance(record_id, str) or record_id not in values:
            bound.append(dict(record))
            continue
        actual = values[record_id]
        if actual is None:
            errors.append(f"{table_path.name} 中 {record_id} 的数值不是有限数值。")
            bound.append(dict(record))
            continue
        replacement = dict(record)
        replacement[value_field] = actual
        replacement["source_path"] = table_path.name
        bound.append(replacement)
    return bound, errors


def _response_columns(columns: dict[str, list[float]]) -> list[str]:
    """Find columns that a planned scan presents as a model response/score."""
    tokens = ("model", "predict", "response", "reflect", "loss", "rmse", "mae", "residual", "拟合", "预测", "反射", "损失", "残差")
    return [name for name in columns if any(token in name.lower() or token in name for token in tokens)]


def _scan_group_response_spans(path: Path, response_columns: list[str]) -> tuple[list[str], dict[str, dict[str, float]]]:
    """Return per-series response spans when scan rows declare scenario fields."""
    group_tokens = ("angle", "sample", "wafer", "material", "scenario", "group", "入射角", "角度", "样品", "晶圆", "材料", "场景", "类别")
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = [name for name in (reader.fieldnames or []) if isinstance(name, str)]
            group_columns = [
                name for name in fields
                if any(token in name.lower() or token in name for token in group_tokens)
            ]
            if not group_columns:
                return [], {}
            groups: dict[tuple[str, ...], dict[str, list[float]]] = {}
            for row in reader:
                key = tuple(str(row.get(name, "")).strip() for name in group_columns)
                values = groups.setdefault(key, {name: [] for name in response_columns})
                for name in response_columns:
                    value = _parse_csv_number(row.get(name))
                    if value is not None:
                        values[name].append(value)
    except (OSError, csv.Error, UnicodeError):
        return [], {}
    spans: dict[str, dict[str, float]] = {}
    for key, values in groups.items():
        group_spans = {
            name: max(series) - min(series)
            for name, series in values.items()
            if len(series) >= 2
        }
        if group_spans:
            spans[" | ".join(key)] = group_spans
    return group_columns, spans


def _expected_artifact_issues(root: Path, subtask_id: str) -> list[dict[str, Any]]:
    """Verify the numerical artefacts the ModelPlan committed to produce.

    In particular, a declared scan must contain a varying response/score.  A
    flat response can be a legitimate scientific finding, but then it is an
    identifiability result and must not be used as an unqualified fit/parameter
    scan.  This check therefore stops the automatic completion path and asks
    the workflow to preserve that distinction explicitly.
    """
    issues: list[dict[str, Any]] = []
    for index, artifact in enumerate(_planned_expected_artifacts(root, subtask_id)):
        raw_path = artifact.get("path")
        kind = str(artifact.get("kind") or "other")
        description = str(artifact.get("description") or "")
        artifact_path = _safe_source_path(root, raw_path)
        check_id = f"{subtask_id}.expected_artifact.{index}"
        if artifact_path is None or not artifact_path.is_file() or artifact_path.stat().st_size == 0:
            issues.append(_issue(
                check_id,
                False,
                f"ModelPlan 承诺的产物 {raw_path!r} 缺失或为空。",
                {"path": raw_path, "kind": kind},
            ))
            continue
        issues.append(_issue(
            check_id,
            True,
            f"ModelPlan 承诺的产物 {artifact_path.name} 存在且非空。",
            {"path": str(artifact_path.relative_to(root)), "kind": kind},
        ))

        if artifact_path.suffix.lower() != ".csv" or kind not in {"result_table", "constraint_table", "figure_data", "time_series", "parameter_audit", "dataset"}:
            continue
        columns, parse_error = _csv_numeric_columns(artifact_path)
        csv_check_id = f"{check_id}.csv"
        if parse_error:
            issues.append(_issue(csv_check_id, False, f"{artifact_path.name} {parse_error}"))
            continue
        if not columns:
            issues.append(_issue(
                csv_check_id,
                False,
                f"{artifact_path.name} 虽可解析，但没有有限数值列，不能作为数值执行证据。",
            ))
            continue
        issues.append(_issue(
            csv_check_id,
            True,
            f"{artifact_path.name} 可解析，且包含有限数值列。",
            {"numeric_columns": sorted(columns)},
        ))

        scan_text = f"{artifact_path.name}\n{description}".lower()
        is_response_scan = kind == "figure_data" and (
            "scan" in scan_text or "扫描" in scan_text
        ) and any(token in scan_text for token in ("model", "拟合", "预测", "反射", "loss", "损失", "残差", "rmse", "mae"))
        if not is_response_scan:
            continue
        responses = _response_columns(columns)
        spans = {
            name: max(values) - min(values)
            for name, values in columns.items()
            if name in responses and len(values) >= 2
        }
        # A scan curve that changes by less than 0.1% of its displayed scale is
        # visually/numerically indistinguishable from a constant response.  It
        # is not a fit-quality threshold; it only prevents a nearly flat trace
        # from being presented as evidence that a parameter sweep located an
        # informative optimum.
        tolerance = {
            name: max(1e-12, max(abs(value) for value in columns[name]) * 1e-3)
            for name in spans
        }
        varying = [name for name, span in spans.items() if span > tolerance[name]]
        group_columns, group_spans = _scan_group_response_spans(artifact_path, responses)
        degenerate_groups = [
            group for group, group_values in group_spans.items()
            if not any(
                span > tolerance.get(name, 1e-12)
                for name, span in group_values.items()
            )
        ]
        issues.append(_issue(
            f"{check_id}.response_variation",
            bool(varying) and not degenerate_groups,
            (
                f"{artifact_path.name} 的扫描响应具有可复核的非退化动态范围。"
                if varying and not degenerate_groups
                else f"{artifact_path.name} 的模型响应/评分列整体或某个声明场景内退化，不能支撑参数扫描结论。"
            ),
            {
                "response_columns": responses,
                "spans": spans,
                "tolerances": tolerance,
                "group_columns": group_columns,
                "group_spans": group_spans,
                "degenerate_groups": degenerate_groups,
            },
        ))
    return issues


def _identifiability_issues(root: Path, subtask_id: str, metrics: object) -> list[dict[str, Any]]:
    if not _plan_requires_identifiability_evidence(root, subtask_id):
        return []
    records = metrics if isinstance(metrics, list) else []
    meaningful_tokens = ("可辨识", "identifiability", "初值分支", "branch", "区间", "interval", "边界", "bound", "剖面", "profile")
    finite_only_tokens = ("有限", "finite")
    candidates = [
        item for item in records
        if isinstance(item, dict)
        and any(token in f"{item.get('id', '')} {item.get('label', '')}".lower() or token in f"{item.get('id', '')} {item.get('label', '')}" for token in meaningful_tokens)
    ]
    meaningful = [
        item for item in candidates
        if not any(token in f"{item.get('id', '')} {item.get('label', '')}".lower() or token in f"{item.get('id', '')} {item.get('label', '')}" for token in finite_only_tokens)
    ]
    return [_issue(
        f"{subtask_id}.identifiability_evidence",
        bool(meaningful),
        (
            f"{subtask_id} 已记录参数可辨识性、分支、区间、边界或剖面诊断。"
            if meaningful
            else f"{subtask_id} 的 ModelPlan 明确要求可辨识性/多初值/Bootstrap 诊断，但只记录了有限性或未记录稳定性证据。"
        ),
        {"candidate_metric_ids": [item.get("id") for item in candidates]},
    )]


_DIAGNOSTIC_TOKENS: dict[str, tuple[str, ...]] = {
    "exact": (
        "residual", "残差", "等式", "代入", "identity",
        "reproducibility", "reproducible", "复现", "验证", "check",
        "一致", "判定", "exact", "精确", "tolerance", "容差", "diff",
        "error", "误差", "coverage", "覆盖", "completeness", "完整",
        "closed_form", "解析", "analytic",
    ),
    "numerical": (
        "convergence", "收敛", "step", "步长", "grid", "网格", "refinement",
        "加密", "residual", "残差", "error", "误差", "iteration", "迭代",
        "tolerance", "容差",
    ),
    "optimization": (
        "solver", "求解器", "status", "状态", "constraint", "约束", "feasible",
        "可行", "gap", "间隙", "initial", "初值", "branch", "分支",
        "optimal", "最优", "dual", "对偶", "slack", "松弛",
    ),
    "fitting": (
        "residual", "残差", "rmse", "mae", "r2", "r²", "holdout", "验证集",
        "bootstrap", "可辨识", "identifiability", "interval", "区间",
        "fit", "拟合", "loss", "损失",
    ),
    "simulation": (
        "seed", "随机种子", "replicate", "重复", "interval", "区间", "convergence",
        "收敛", "step", "步长", "residual", "残差", "balance", "守恒",
        "mc", "monte", "蒙特", "sample", "样本", "trial", "试验",
        "error", "误差", "variance", "方差", "std", "ci", "置信",
        "reproducibility", "reproducible", "复现", "验证", "check",
    ),
}

# A simulation plan may make several independent diagnostic claims. A generic
# feasibility metric cannot also prove a separately requested mass-balance
# check simply because both belong to the same simulation profile. These
# groups apply only when the ModelPlan explicitly asks for the corresponding
# diagnostic.
_DIAGNOSTIC_REQUIREMENT_GROUPS = (
    (
        ("求解器", "solver", "状态方程", "state_equation", "state equation"),
        (
            "求解器", "solver", "状态", "status", "最优性", "optimality", "收敛", "convergence",
            "成功", "success", "linprog", "highs", "scipy", "单纯形", "simplex", "算法",
            "枚举", "enumeration", "一致性", "consistency", "核验", "验证", "verify",
        ),
    ),
    (
        ("松弛", "slack", "违反量", "violation"),
        ("松弛", "slack", "约束", "constraint", "边界", "bound", "violation", "违反量", "非负", "nonnegative", "满足"),
    ),
    (
        ("质量", "守恒", "balance", "residual"),
        ("质量", "守恒", "balance", "residual", "残差", "能量", "energy", "误差", "error"),
    ),
    (
        ("双喷嘴", "双喷油器", "injector"),
        ("双喷嘴", "双喷油器", "injector", "喷嘴", "nozzle"),
    ),
    (
        ("减压阀", "溢流阀", "relief"),
        ("减压阀", "溢流阀", "relief", "阀门", "valve"),
    ),
    (
        ("可行性", "feasible"),
        ("可行性", "feasible", "连通", "connectivity", "导通", "conduction", "相交", "intersection", "区间", "interval", "范围", "range", "bound", "边界", "有效", "valid", "影子价格", "shadow", "对偶", "dual"),
    ),
    (
        ("步长", "网格", "step", "grid", "mesh", "加密", "refinement"),
        ("步长", "网格", "step", "grid", "mesh", "加密", "refinement", "分辨率", "resolution", "采样", "sample"),
    ),
    (
        ("蒙特卡洛", "monte carlo", "mc"),
        ("蒙特卡洛", "monte carlo", "mc", "方差", "variance", "置信区间", "confidence", "采样", "sample"),
    ),
    (
        ("敏感性分析", "灵敏度分析", "sensitivity_analysis"),
        ("敏感性", "灵敏度", "sensitivity", "鲁棒性", "robustness"),
    ),
    (
        ("几何碰撞", "相交距离", "geometric_collision"),
        ("几何", "geometry", "距离", "distance", "碰撞", "collision", "截断", "truncation", "镜像", "mirror", "周期", "periodic"),
    ),
)


def _diagnostic_profile_issues(root: Path, subtask_id: str, metrics: object) -> list[dict[str, Any]]:
    """Bind ModelPlan's declared reliability diagnostic to executed evidence.

    The gate checks that a task-owned plan becomes an auditable metric; it does
    not impose a cross-domain RMSE or convergence threshold. Older plans omit
    this optional field and remain compatible, while new plans are prompted to
    declare an appropriate profile.
    """
    subtask = _planned_subtask(root, subtask_id)
    profile = str(subtask.get("diagnostic_profile") or "not_applicable")
    requirements = subtask.get("diagnostic_requirements", [])
    if profile == "not_applicable":
        return []
    tokens = _DIAGNOSTIC_TOKENS.get(profile)
    if tokens is None:
        return [_issue(
            f"{subtask_id}.diagnostic_profile",
            False,
            f"{subtask_id} 声明了不支持的 diagnostic_profile={profile!r}。",
        )]
    requirements_ok = isinstance(requirements, list) and any(
        isinstance(item, str) and item.strip() for item in requirements
    )
    records = metrics if isinstance(metrics, list) else []
    matching_metrics = []
    metric_texts: list[str] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        text = f"{item.get('id', '')} {item.get('label', '')} {item.get('explanation', '')}"
        metric_texts.append(text.lower())
        lowered = text.lower()
        if any(token in text or token in lowered for token in tokens):
            matching_metrics.append(item)
    missing_requirements: list[str] = []
    if isinstance(requirements, list):
        for requirement in requirements:
            if not isinstance(requirement, str) or not requirement.strip():
                continue
            lowered_requirement = requirement.lower()
            for requirement_tokens, metric_tokens in _DIAGNOSTIC_REQUIREMENT_GROUPS:
                if not any(
                    token in requirement or token in lowered_requirement
                    for token in requirement_tokens
                ):
                    continue
                if not any(
                    any(token in metric_text for token in metric_tokens)
                    for metric_text in metric_texts
                ):
                    missing_requirements.append(requirement)
                break
    passed = requirements_ok and bool(matching_metrics) and not missing_requirements
    return [_issue(
        f"{subtask_id}.diagnostic_profile",
        passed,
        (
            f"{subtask_id} 的 {profile} 诊断已由执行指标和计划要求共同支撑。"
            if passed
            else (
                f"{subtask_id} 声明为 {profile}，但缺少诊断要求或可复核的诊断指标。"
                + (
                    " 以下计划诊断没有对应的 source-backed metric："
                    + "；".join(missing_requirements)
                    if missing_requirements else ""
                )
            )
        ),
        {
            "profile": profile,
            "requirements": requirements if isinstance(requirements, list) else [],
            "matching_metric_ids": [item.get("id") for item in matching_metrics],
            "missing_requirements": missing_requirements,
        },
    )]


def _plan_constraint_errors(
    root: Path,
    subtask_id: str,
    constraints: list[dict[str, Any]],
) -> list[str]:
    """Bind Coder constraints to the immutable Modeler acceptance contract."""
    planned = _planned_acceptance_metrics(root, subtask_id)
    if not planned:
        return []  # Backward-compatible tasks may not own a structured plan.
    submitted = {
        item.get("id"): item
        for item in constraints
        if isinstance(item.get("id"), str)
    }
    errors: list[str] = []
    for expected in planned:
        metric_id = expected.get("key")
        if not isinstance(metric_id, str) or not metric_id:
            continue
        actual = submitted.get(metric_id)
        if actual is None:
            errors.append(f"缺少 ModelPlan 验收指标 {metric_id} 的约束证据。")
            continue
        plan_comparator = expected.get("comparator")
        evidence_comparator = _PLAN_COMPARISONS.get(str(plan_comparator))
        actual_comparison = _canonical_evidence_comparison(actual.get("comparison"))
        if actual_comparison != evidence_comparator:
            errors.append(
                f"约束 {metric_id} 的 comparison 必须保持 ModelPlan 的 {plan_comparator} "
                f"语义（应为 {evidence_comparator}），不得改为 {actual.get('comparison')}。"
            )
        expected_target = _as_number(expected.get("target"))
        submitted_target = _as_number(actual.get("target"))
        expected_kind = expected.get("metric_kind")
        expected_precision = _as_number(expected.get("precision"))
        expected_abs_tol = _as_number(expected.get("abs_tol"))
        expected_rel_tol = _as_number(expected.get("rel_tol"))
        deduced_abs, deduced_rel = _deduce_float_tolerance(
            expected_target,
            metric_kind=str(expected_kind) if expected_kind else None,
            precision=int(expected_precision) if expected_precision is not None else None,
            abs_tol=expected_abs_tol,
            rel_tol=expected_rel_tol,
        )
        if expected_target is None:
            errors.append(f"ModelPlan 验收指标 {metric_id} 的 target 不是可机检数值。")
        elif submitted_target is None or not math.isclose(
            submitted_target, expected_target, rel_tol=deduced_rel, abs_tol=deduced_abs
        ):
            errors.append(
                f"约束 {metric_id} 的 target 必须保持 ModelPlan 值 {expected_target}，"
                f"不得改为 {actual.get('target')}。"
            )
        actual_tolerance = _as_number(actual.get("tolerance"))
        if actual.get("comparison") in {"eq", "abs_diff_lte"} and actual_tolerance is None:
            actual_tolerance = 0.0
        if plan_comparator == "eq":
            if actual_tolerance is None or actual_tolerance < 0:
                errors.append(f"等值约束 {metric_id} 的 tolerance 必须为非负数值。")
            elif expected_target is not None:
                max_allowed = deduced_abs * 1.5
                if actual_tolerance > max_allowed:
                    errors.append(
                        f"等值约束 {metric_id} 的 tolerance={actual_tolerance} 超出允许范围（最大允许 {max_allowed}，要求 tolerance=0 或严格浮点精度）。"
                    )
    return errors



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


def _normalise_metric_records(
    root: Path, metrics: object
) -> tuple[list[dict[str, Any]] | None, list[str]]:
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
        source_path, source_error = _task_relative_file(
            root, metric.get("source_path"), field=f"metrics[{index}].source_path"
        )
        if source_error:
            errors.append(source_error)
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
        elif source_path is not None and not _source_contains_number(source_path, value):
            errors.append(
                f"metrics[{index}].value={value} 无法在 source_path 中复查。"
            )
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
                    "source": {
                        "path": str(source_path.relative_to(root)).replace("\\", "/"),
                        "sha256": _sha256(source_path),
                    },
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
        if not isinstance(constraint_id, str) or not constraint_id.strip():
            fallback_id = str(constraint.get("name") or constraint.get("label") or f"constraint_{index}").strip()
            constraint_id = fallback_id or f"constraint_{index}"
        actual = _as_number(constraint.get("actual"))
        # ``eq`` is the ModelPlan spelling.  Canonicalise it before the
        # evidence protocol enum check and make exactness explicit with a zero
        # tolerance when the caller omitted one.
        comparison = _canonical_evidence_comparison(constraint.get("comparison"))
        constraint_payload = constraint
        if comparison != constraint.get("comparison"):
            constraint_payload = dict(constraint)
            constraint_payload["comparison"] = comparison
            if constraint_payload.get("tolerance") is None:
                constraint_payload["tolerance"] = 0.0
        if constraint_id in seen_ids:
            constraint_id = f"{constraint_id}_{index}"
        seen_ids.add(constraint_id)
        if actual is None:
            errors.append(f"constraints[{index}].actual 必须是有限数值。")
        if comparison not in _EVIDENCE_COMPARISONS:
            errors.append(
                f"constraints[{index}].comparison 不受支持："
                f"{_unsupported_comparison_hint(comparison)}"
            )
        source_path, source_error = _task_relative_file(
            root, constraint_payload.get("source_path"), field=f"constraints[{index}].source_path"
        )
        if source_error:
            errors.append(source_error)
        if actual is not None and source_path is not None and not _source_contains_number(
            source_path, actual
        ):
            errors.append(
                f"constraints[{index}].actual={actual} 无法在 source_path 中复查。"
            )

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
        for key in ("target", "tolerance", "lower", "upper", "abs_tol", "rel_tol", "precision"):
            if key in constraint_payload and constraint_payload.get(key) is not None:
                numeric = _as_number(constraint_payload[key])
                if numeric is None:
                    errors.append(f"constraints[{index}].{key} 必须是有限数值。")
                else:
                    if key == "precision":
                        result[key] = int(numeric)
                    else:
                        result[key] = numeric
        if "metric_kind" in constraint_payload and constraint_payload.get("metric_kind") is not None:
            if not isinstance(constraint_payload["metric_kind"], str):
                errors.append(f"constraints[{index}].metric_kind 必须是字符串。")
            else:
                result["metric_kind"] = constraint_payload["metric_kind"]
        if "unit" in constraint_payload and constraint_payload.get("unit") is not None:
            if not isinstance(constraint_payload["unit"], str):
                errors.append(f"constraints[{index}].unit 必须是字符串。")
            else:
                result["unit"] = constraint_payload["unit"]
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
    constraints: list[dict[str, Any]] | None = None,
    metrics: list[dict[str, Any]] | None = None,
    figures: list[dict[str, Any]] | None = None,
    **extra_kwargs: Any,
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

    constraints = constraints if isinstance(constraints, list) else []
    metrics = metrics if isinstance(metrics, list) else []
    figures = figures if isinstance(figures, list) else []

    table_errors = _validate_declared_table_statuses(root, subtask_id)
    table_bound_metrics, metric_binding_errors = _bind_records_to_acceptance_table(
        root, subtask_id, metrics, value_field="value"
    )
    table_bound_constraints, constraint_binding_errors = _bind_records_to_acceptance_table(
        root, subtask_id, constraints, value_field="actual"
    )
    bound_constraints, plan_binding_errors = _bind_plan_constraints_from_acceptance_table(
        root, subtask_id, table_bound_constraints
    )
    normalised_metrics, metric_errors = _normalise_metric_records(root, table_bound_metrics)
    normalised_constraints, constraint_errors = _normalise_constraint_records(root, bound_constraints)
    normalised_figures, figure_errors = _normalise_figure_records(root, figures)
    plan_errors = (
        _plan_constraint_errors(root, subtask_id, normalised_constraints)
        if normalised_constraints is not None
        else []
    )
    diagnostic_errors = []
    if normalised_metrics is not None:
        diagnostic_errors = [
            str(issue.get("message", "诊断证据不完整。"))
            for issue in _diagnostic_profile_issues(root, subtask_id, normalised_metrics)
            if issue.get("passed") is False
        ]
    errors = (
        table_errors
        + metric_binding_errors
        + constraint_binding_errors
        + plan_binding_errors
        + metric_errors
        + constraint_errors
        + figure_errors
        + plan_errors
        + diagnostic_errors
    )
    if errors or normalised_metrics is None or normalised_constraints is None or normalised_figures is None:
        return {"ok": False, "errors": errors}

    # 强制将 ModelPlan 声明的精度协议绑定到对应约束中，不能被 Coder 工具调用参数篡改或放宽
    planned = _planned_acceptance_metrics(root, subtask_id)
    planned_by_id = {
        item.get("key"): item
        for item in planned
        if isinstance(item, dict) and isinstance(item.get("key"), str)
    }
    for c in normalised_constraints:
        c_id = c.get("id")
        if c_id in planned_by_id:
            p_item = planned_by_id[c_id]
            for field in ("metric_kind", "precision", "abs_tol", "rel_tol"):
                if p_item.get(field) is not None:
                    c[field] = p_item[field]
                elif field in c:
                    del c[field]
            eff_abs, eff_rel = _deduce_float_tolerance(
                c.get("target"),
                metric_kind=c.get("metric_kind"),
                precision=c.get("precision"),
                abs_tol=c.get("abs_tol"),
                rel_tol=c.get("rel_tol"),
            )
            if c.get("tolerance") != 0.0:
                c["tolerance"] = eff_abs
            c["abs_tol"] = eff_abs
            c["rel_tol"] = eff_rel

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
        manifest: dict[str, Any] = {"schema_version": MANIFEST_SCHEMA_V2, "subtasks": []}
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

    failed_constraints = [
        {
            "id": str(constraint.get("id", "unknown")),
            "actual": constraint.get("actual"),
            "comparison": constraint.get("comparison"),
            "target": constraint.get("target"),
            "tolerance": constraint.get("tolerance"),
            "lower": constraint.get("lower"),
            "upper": constraint.get("upper"),
        }
        for constraint, passed in zip(normalised_constraints, constraint_results, strict=True)
        if not passed
    ]
    return {
        "ok": True,
        "subtask_id": subtask_id,
        "feasible": entry["feasible"],
        "constraint_passed": constraint_results,
        # A failed record remains auditable in the manifest, but the Coder also
        # needs the semantic failure (not an opaque list index) to make its one
        # bounded repair attempt useful.
        "failed_constraints": failed_constraints,
        "manifest_path": MANIFEST_NAME,
        "metric_count": len(normalised_metrics),
        "figure_count": len(normalised_figures),
    }


def _check_constraint(
    constraint: object,
    work_dir: Path,
    *,
    require_source_value: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
    if not isinstance(constraint, dict):
        return False, "约束必须是对象。", {}

    constraint_id = constraint.get("id")
    actual = _as_number(constraint.get("actual"))
    comparison = _canonical_evidence_comparison(constraint.get("comparison"))
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
    if require_source_value and not _source_contains_number(source_path, actual):
        return False, f"约束 {constraint_id} 的 actual 无法在哈希源文件中复查。", evidence

    target = _as_number(constraint.get("target"))
    tolerance = _as_number(constraint.get("tolerance"))
    abs_tol = _as_number(constraint.get("abs_tol"))
    rel_tol = _as_number(constraint.get("rel_tol"))
    metric_kind = constraint.get("metric_kind")
    precision = _as_number(constraint.get("precision"))
    effective_abs_tol, effective_rel_tol = _deduce_float_tolerance(
        target,
        metric_kind=str(metric_kind) if metric_kind else None,
        precision=int(precision) if precision is not None else None,
        abs_tol=abs_tol,
        rel_tol=rel_tol,
        tolerance=tolerance,
    )
    if tolerance is None or tolerance <= 0:
        tolerance = effective_abs_tol
    lower = _as_number(constraint.get("lower"))
    upper = _as_number(constraint.get("upper"))
    if comparison in {"abs_diff_lte", "eq"}:
        if target is None:
            return False, f"约束 {constraint_id} 的 target 无效。", evidence
        passed = (
            abs(actual - target) <= tolerance
            or math.isclose(
                actual,
                target,
                rel_tol=effective_rel_tol,
                abs_tol=effective_abs_tol,
            )
        )
        message = f"约束 {constraint_id}: |{actual} - {target}| <= {tolerance}。"


    elif comparison == "lte":
        if target is None:
            return False, f"约束 {constraint_id} 的 target 无效。", evidence
        passed = actual <= target or math.isclose(actual, target, rel_tol=effective_rel_tol, abs_tol=effective_abs_tol)
        message = f"约束 {constraint_id}: {actual} <= {target}。"
    elif comparison == "gte":
        if target is None:
            return False, f"约束 {constraint_id} 的 target 无效。", evidence
        passed = actual >= target or math.isclose(actual, target, rel_tol=effective_rel_tol, abs_tol=effective_abs_tol)
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


def _check_metric_source(
    metric: object, work_dir: Path
) -> tuple[bool, str, dict[str, Any]]:
    if not isinstance(metric, dict):
        return False, "指标必须是对象。", {}
    metric_id = metric.get("id")
    value = _as_number(metric.get("value"))
    source = metric.get("source")
    evidence = {"id": metric_id, "value": value}
    if value is None or not isinstance(source, dict):
        return False, f"指标 {metric_id} 缺少有限 value 或哈希 source。", evidence
    source_path = _safe_source_path(work_dir, source.get("path"))
    expected_hash = source.get("sha256")
    if source_path is None or not source_path.is_file():
        return False, f"指标 {metric_id} 的 source.path 不存在或越出任务目录。", evidence
    if not isinstance(expected_hash, str) or _sha256(source_path) != expected_hash:
        return False, f"指标 {metric_id} 的 source.sha256 与当前文件不一致。", evidence
    evidence["source"] = {
        "path": str(source_path.relative_to(work_dir)),
        "sha256": expected_hash,
    }
    if not _source_contains_number(source_path, value):
        return False, f"指标 {metric_id} 的 value 无法在哈希源文件中复查。", evidence
    return True, f"指标 {metric_id} 的数值可在哈希源文件中复查。", evidence


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


def _contract_requires_q3_timing_comparison(work_dir: Path) -> bool:
    contract = _read_json(work_dir / "problem_contract.json")
    if contract is None:
        return False
    return any(
        isinstance(item, dict) and item.get("key") == "q3_injector_timing_comparison"
        for item in contract.get("required_requirements", [])
    )


def _contract_requires_linear_programming_evidence(work_dir: Path) -> bool:
    contract = _read_json(work_dir / "problem_contract.json")
    return bool(contract) and any(
        isinstance(item, dict) and item.get("plugin") == "linear_programming"
        for item in contract.get("required_requirements", [])
    )


def _contract_pressure_targets(work_dir: Path) -> list[float]:
    """Return pressure targets the problem statement itself declared, in MPa."""
    contract = _read_json(work_dir / "problem_contract.json")
    requirements = contract.get("required_requirements", []) if contract else []
    if not isinstance(requirements, list):
        return []
    targets: list[float] = []
    for item in requirements:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", ""))
        if not _PRESSURE_TARGET_REQUIREMENT_RE.match(key):
            continue
        raw = key[len("target_pressure_") : -len("_mpa")].replace("_", ".")
        try:
            value = float(raw)
        except ValueError:
            continue
        if math.isfinite(value):
            targets.append(value)
    return targets


def _planned_pressure_bound(
    root: Path, subtask_id: str, targets: list[float]
) -> tuple[float | None, str | None]:
    """Return a pressure deviation bound the ModelPlan declared for this subtask.

    Only an explicit upper-bound comparator carries a number we may enforce.  A
    plan that merely records a flag (``eq 1.0``) declares no threshold, so the
    caller must fall back to requiring recorded evidence instead of inventing
    a limit of its own.

    Real plans also mix in absolute pressure ceilings — ``最大压力超调 le 150 MPa``,
    ``柱塞腔峰值压力 le 200 MPa`` — whose wording matches the deviation vocabulary
    but whose magnitude is an operating limit, not a fluctuation budget.  Judging
    a 68 MPa peak-to-peak against a 150 MPa ceiling can never fail, which would
    quietly disable the gate, so a bound at or above the declared target pressure
    is rejected and the caller falls back to human review.
    """
    ceiling = min(targets) if targets else None
    for metric in _planned_acceptance_metrics(root, subtask_id):
        if not isinstance(metric, dict):
            continue
        label = " ".join(
            str(metric.get(field, "")) for field in ("key", "label", "description")
        )
        if not _PRESSURE_DEVIATION_LABEL_RE.search(label):
            continue
        if str(metric.get("unit", "")).strip().lower() not in {"mpa", "兆帕"}:
            continue
        if str(metric.get("comparator", "")).lower() not in {"le", "lt", "within"}:
            continue
        target = _as_number(metric.get("target"))
        if target is None:
            continue
        if ceiling is not None and target >= ceiling:
            # Absolute operating limit, not a deviation budget — see docstring.
            continue
        return target, str(metric.get("label") or metric.get("key") or "")
    return None, None


def _pressure_target_issues(
    work_dir: Path,
    subtask_id: str,
    metrics: object,
    targets: list[float],
) -> list[dict[str, Any]]:
    """Require auditable pressure-deviation evidence whenever the problem sets a target.

    The previous implementation hard-coded "100 MPa implies peak-to-peak <= 15
    MPa", which silently mis-judged every other problem.  Thresholds now come
    only from the problem statement or the ModelPlan, but recording the actual
    deviation stays mandatory: without it, an openly oscillating control scheme
    would pass on a bare "simulation completed" flag.
    """
    if not targets or not isinstance(metrics, list):
        return []

    deviation_metrics = [
        metric
        for metric in metrics
        if isinstance(metric, dict)
        and str(metric.get("unit", "")).strip().lower() in {"mpa", "兆帕"}
        and _PRESSURE_DEVIATION_LABEL_RE.search(
            " ".join(str(metric.get(field, "")) for field in ("id", "label", "explanation"))
        )
        and not _PRESSURE_CONVERGENCE_LABEL_RE.search(
            " ".join(str(metric.get(field, "")) for field in ("id", "label", "explanation"))
        )
        and _as_number(metric.get("value")) is not None
    ]
    target_text = "、".join(f"{target:g} MPa" for target in targets)
    if not deviation_metrics:
        return [_issue(
            f"{subtask_id}.pressure_target_evidence",
            False,
            (
                f"{subtask_id} 的题面压力目标（{target_text}）缺少实际压力偏差证据："
                "必须记录由本题时序数组计算的峰峰值、波动或偏差指标（单位 MPa），"
                "不能只登记“仿真完成”之类的标志位，也不能用步长收敛差之类的数值精度量顶替。"
            ),
            {"contract_targets_mpa": targets},
        )]

    bound, bound_label = _planned_pressure_bound(work_dir, subtask_id, targets)
    worst = max(abs(float(metric["value"])) for metric in deviation_metrics)
    recorded = {
        str(metric.get("id") or metric.get("label")): float(metric["value"])
        for metric in deviation_metrics
    }
    if bound is None:
        # No auditable threshold exists.  Recording the real number is the gate;
        # judging whether it is acceptable stays with human review.
        return [_issue(
            f"{subtask_id}.pressure_target_evidence",
            True,
            (
                f"{subtask_id} 已记录压力偏差实测值（最大 {worst:g} MPa）。"
                "题面与 ModelPlan 未给出数值上限，是否达标须人工判定。"
            ),
            {
                "contract_targets_mpa": targets,
                "recorded_metrics": recorded,
                "declared_target": None,
                "requires_human_review": True,
            },
        )]

    passed = worst <= bound
    return [_issue(
        f"{subtask_id}.pressure_target_evidence",
        passed,
        (
            f"{subtask_id} 的压力偏差实测最大 {worst:g} MPa，未超过 ModelPlan 声明的 {bound:g} MPa 上限。"
            if passed
            else f"{subtask_id} 的压力偏差实测最大 {worst:g} MPa，超过 ModelPlan 声明的 {bound:g} MPa 上限。"
        ),
        {
            "contract_targets_mpa": targets,
            "recorded_metrics": recorded,
            "declared_target": bound,
            "declared_target_label": bound_label,
        },
    )]


def _declares_balance_requirement(value: object) -> bool:
    """Return whether a structured acceptance item explicitly requires conservation.

    A generic physical-simulation profile is intentionally insufficient: optics,
    mechanics and curve fitting can all be physical models without a mass/flow
    balance equation.  The hard gate is enabled only by a specific machine key
    or by an unambiguous Chinese acceptance label/description.
    """
    if not isinstance(value, dict):
        return False
    key = str(value.get("key", value.get("id", ""))).lower()
    if any(token in key for token in _BALANCE_REQUIREMENT_KEYS):
        return True
    text = "\n".join(
        str(value.get(field, ""))
        for field in ("label", "description")
    )
    return _BALANCE_REQUIREMENT_PATTERN.search(text) is not None


def _subtask_requires_balance_residual(work_dir: Path, subtask_id: str) -> bool:
    """Read the task-owned plan/contract to decide whether this subtask needs balance evidence."""
    plan = _read_json(work_dir / "modeler_plan.json")
    if plan:
        model_plan = plan.get("model_plan", {})
        subtasks = model_plan.get("subtasks", {}) if isinstance(model_plan, dict) else {}
        subtask = subtasks.get(subtask_id, {}) if isinstance(subtasks, dict) else {}
        metrics = subtask.get("acceptance_metrics", []) if isinstance(subtask, dict) else []
        if isinstance(metrics, list) and any(_declares_balance_requirement(item) for item in metrics):
            return True

    contract = _read_json(work_dir / "problem_contract.json")
    requirements = contract.get("required_requirements", []) if contract else []
    return isinstance(requirements, list) and any(
        _declares_balance_requirement(item) for item in requirements
    )


def _subtask_evidence_issues(
    subtask_id: str,
    item: dict[str, Any],
    *,
    relief_validation_required: bool,
    q1_valve_duration_outputs_required: bool,
    q3_timing_comparison_required: bool,
    linear_programming_evidence_required: bool,
    balance_residual_required: bool,
) -> list[dict[str, Any]]:
    """Reject result labels that openly admit no formal numerical solve occurred.

    A matching hash only proves that a CSV was written.  It does not turn an
    inherited estimate into a simulation/optimization result. Tasks whose
    acceptance contract explicitly declares a conservation equation must record
    a balance residual; linear-programming tasks instead prove feasibility
    through their resource constraints plus objective and decision-variable
    evidence.
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
    if balance_residual_required:
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
                    str(metric.get("explanation", "")),
                    str(metric.get("description", "")),
                    " ".join(str(alias) for alias in metric.get("aliases", [])),
                ]
            )
            for metric in metrics
        ).lower()
        has_objective = any(token in metric_text for token in ("objective", "目标", "利润", "成本"))
        has_decision = any(
            token in metric_text
            for token in ("optimal_", "decision", "最优解", "决策变量", "最优产量", "产量", "方案", "x_a", "x_b", "x1", "x2", "xa", "xb")
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

    if q3_timing_comparison_required and subtask_id == "ques3":
        metric_records = [
            {
                "id": str(metric.get("id", "")),
                "text": " ".join(
                    [
                        str(metric.get("id", "")),
                        str(metric.get("label", "")),
                        str(metric.get("explanation", "")),
                        " ".join(str(alias) for alias in metric.get("aliases", [])),
                    ]
                ),
                "value": _as_number(metric.get("value")),
            }
            for metric in metrics
        ]
        # A single metric such as ``alternate_phase_strategy_objective`` can
        # match all three old regular expressions.  It does not prove that two
        # strategies were simulated.  Require separate selected/alternative
        # phase records plus separate selected/alternative objective records;
        # the two phase values must actually differ.
        selected_phase = [
            item
            for item in metric_records
            if _Q3_TIMING_METRIC_RE.search(item["text"])
            and not _Q3_SELECTION_METRIC_RE.search(item["text"])
            and not _Q3_ALTERNATE_METRIC_RE.search(item["text"])
        ]
        alternate_phase = [
            item
            for item in metric_records
            if _Q3_TIMING_METRIC_RE.search(item["text"])
            and not _Q3_SELECTION_METRIC_RE.search(item["text"])
            and _Q3_ALTERNATE_METRIC_RE.search(item["text"])
        ]
        selected_objective = [
            item
            for item in metric_records
            if _Q3_SELECTION_METRIC_RE.search(item["text"])
            and _Q3_SELECTED_METRIC_RE.search(item["text"])
            and not _Q3_ALTERNATE_METRIC_RE.search(item["text"])
        ]
        alternate_objective = [
            item
            for item in metric_records
            if _Q3_SELECTION_METRIC_RE.search(item["text"])
            and _Q3_ALTERNATE_METRIC_RE.search(item["text"])
        ]
        timing_pairs = [
            (selected, alternate)
            for selected in selected_phase
            for alternate in alternate_phase
            if selected["id"] != alternate["id"]
            and selected["value"] is not None
            and alternate["value"] is not None
            and not math.isclose(
                float(selected["value"]), float(alternate["value"]), abs_tol=1e-12
            )
            and (
                math.isclose(float(selected["value"]), 0.0, abs_tol=1e-12)
                or math.isclose(float(alternate["value"]), 0.0, abs_tol=1e-12)
            )
        ]
        objective_pairs = [
            (selected, alternate)
            for selected in selected_objective
            for alternate in alternate_objective
            if selected["id"] != alternate["id"]
        ]
        passed = bool(timing_pairs and objective_pairs)
        issues.append(
            _issue(
                "ques3.injector_timing_comparison",
                passed,
                (
                    "问题三已记录两种不同双喷嘴时序及各自的策略选择依据。"
                    if passed
                    else "问题三必须用不同的数值指标记录同步基线（相位为 0）和非零备选双喷嘴相位，并分别记录选定/备选策略的目标或评分；单个万能指标、同相位伪备选均不通过。"
                ),
                {
                    "selected_phase_metric_ids": [item["id"] for item in selected_phase],
                    "alternate_phase_metric_ids": [item["id"] for item in alternate_phase],
                    "selected_objective_metric_ids": [item["id"] for item in selected_objective],
                    "alternate_objective_metric_ids": [item["id"] for item in alternate_objective],
                    "distinct_timing_pair_count": len(timing_pairs),
                    "objective_pair_count": len(objective_pairs),
                },
            )
        )

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


def _code_safety_issues(root: Path) -> list[dict[str, Any]]:
    issues = []
    _disallowed_paper_files = {
        "res.md", "res.docx", "paper.md", "paper.docx",
        "firstpage.md", "repeatques.md", "analysisques.md",
        "modelassumption.md", "symbol.md", "judge.md", "references.md",
    }
    
    def _detect_anti_hack_ast(source_code: str) -> list[str]:
        hack_issues = []
        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return hack_issues
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "open":
                    if len(node.args) >= 1 and isinstance(node.args[0], ast.Constant):
                        filename = str(node.args[0].value).lower()
                        if filename in _disallowed_paper_files or re.match(r"^ques\d+(_preflight_repair)?\.md$", filename):
                            hack_issues.append(f"发现违规直接写论文文件操作: {filename}")
        return hack_issues

    notebook_path = root / "notebook.ipynb"
    if notebook_path.is_file():
        try:
            notebook = nbformat.read(notebook_path, as_version=4)
            for i, cell in enumerate(notebook.cells):
                if cell.get("cell_type") == "code":
                    hacks = _detect_anti_hack_ast(cell.get("source", ""))
                    if hacks:
                        issues.append(_issue("anti_hack.notebook", False, f"notebook.ipynb Cell {i}: " + "；".join(hacks)))
        except Exception:
            pass

    for py_file in root.glob("*.py"):
        try:
            source = py_file.read_text(encoding="utf-8")
            hacks = _detect_anti_hack_ast(source)
            if hacks:
                issues.append(_issue(f"anti_hack.py_script.{py_file.name}", False, f"{py_file.name}: " + "；".join(hacks)))
        except Exception:
            pass

    if not issues:
        issues.append(_issue("anti_hack.safety", True, "未发现违规篡改论文文件的代码。"))

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
    q3_timing_comparison_required = _contract_requires_q3_timing_comparison(work_dir)
    linear_programming_evidence_required = _contract_requires_linear_programming_evidence(work_dir)
    pressure_targets = _contract_pressure_targets(work_dir)
    strict_value_sources = manifest.get("schema_version") == MANIFEST_SCHEMA_V2
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
        plan_errors = _plan_constraint_errors(work_dir, subtask, constraints)
        issues.append(
            _issue(
                f"{subtask}.plan_acceptance_contract",
                not plan_errors,
                (
                    f"{subtask} 的约束方向和目标与 ModelPlan 一致。"
                    if not plan_errors
                    else "；".join(plan_errors)
                ),
            )
        )
        for constraint in constraints:
            passed, message, evidence = _check_constraint(
                constraint,
                work_dir,
                require_source_value=strict_value_sources,
            )
            constraint_id = constraint.get("id", "unknown") if isinstance(constraint, dict) else "unknown"
            issues.append(_issue(f"{subtask}.constraint.{constraint_id}", passed, message, evidence))

        issues.extend(_subtask_evidence_issues(
            subtask,
            item,
            relief_validation_required=relief_validation_required,
            q1_valve_duration_outputs_required=q1_valve_duration_outputs_required,
            q3_timing_comparison_required=q3_timing_comparison_required,
            linear_programming_evidence_required=linear_programming_evidence_required,
            balance_residual_required=_subtask_requires_balance_residual(work_dir, subtask),
        ))
        # The structured plan promises more than the few values chosen as
        # completion constraints.  Validate its numerical deliverables before
        # freezing results, so a blank/flat scan cannot pass merely because an
        # image path and a SHA-256 exist.
        issues.extend(_expected_artifact_issues(work_dir, subtask))
        issues.extend(_identifiability_issues(work_dir, subtask, item.get("metrics")))
        issues.extend(_diagnostic_profile_issues(work_dir, subtask, item.get("metrics")))
        issues.extend(
            _pressure_target_issues(work_dir, subtask, item.get("metrics"), pressure_targets)
        )

        if strict_value_sources:
            subtask_metrics = item.get("metrics", [])
            if not isinstance(subtask_metrics, list) or not subtask_metrics:
                issues.append(
                    _issue(
                        f"{subtask}.metric_sources",
                        False,
                        f"{subtask} 缺少带哈希来源的指标。",
                    )
                )
            else:
                for index, metric in enumerate(subtask_metrics):
                    passed, message, evidence = _check_metric_source(metric, work_dir)
                    metric_id = metric.get("id", index) if isinstance(metric, dict) else index
                    issues.append(
                        _issue(
                            f"{subtask}.metric_source.{metric_id}",
                            passed,
                            message,
                            evidence,
                        )
                    )

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
        for metric in subtask.get("metrics", []):
            if isinstance(metric, dict) and isinstance(metric.get("source"), dict):
                source = metric["source"]
                add_source(source.get("path"), source.get("sha256"), "metric")
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
    executed_code_sources = []
    if notebook_path.is_file():
        executed_code_sources.append("notebook.ipynb")
        
    for root_dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".ipynb_checkpoints", "latex_project", ".git", ".cache", "scratch", ".agent-work"}]
        for filename in sorted(files):
            if filename.endswith(".py"):
                rel_path = str((Path(root_dir) / filename).relative_to(root)).replace("\\", "/")
                executed_code_sources.append(rel_path)

    document = {
        "schema": "mathmodel.result-freeze",
        "version": 1,
        "metrics": metrics,
        "sources": source_entries,
        "subtasks": subtasks,
        "figures": figures,
        "executed_code_sources": executed_code_sources,
        "generated_from": MANIFEST_NAME,
    }
    output = root / FREEZE_NAME
    with output.open("w", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
    reproducibility = {
        "schema_version": "mathmodel.reproducibility.v1",
        "generated_at": datetime.datetime.now().isoformat(),
        "entrypoints": executed_code_sources,
        "source_artifacts": source_entries,
        "runtime": {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "byte_reproducibility": {
            "status": "NOT_RUN",
            "evidence": None,
        },
        "numerical_reproducibility": {
            "status": "NOT_RUN",
            "evidence": None,
        },
        "replay_status": "not_independently_reexecuted",
        "replay_command_hint": (
            "在隔离环境中执行 notebook.ipynb，并将生成的结果 CSV/JSON 与 source_artifacts 的 SHA-256 对照。"
        ),
        "verification_note": (
            "本清单只记录本次受控执行的入口、来源哈希与运行时信息；"
            "不声称已在独立环境重跑，也不替代人工复现。"
        ),
    }
    with (root / REPRODUCIBILITY_NAME).open("w", encoding="utf-8") as handle:
        json.dump(reproducibility, handle, ensure_ascii=False, indent=2)
    return output


def _dimensional_parameter_sanity_issues(work_dir: Path) -> list[dict[str, Any]]:
    """Validate arithmetic and dimensional sanity in input parameter audit tables."""
    audit_paths = sorted(work_dir.glob("*_input_parameter_audit.csv"))
    legacy_audit = work_dir / "input_parameter_audit.csv"
    if legacy_audit.is_file() and legacy_audit not in audit_paths:
        audit_paths.append(legacy_audit)

    if not audit_paths:
        return []

    issues: list[dict[str, Any]] = []
    for audit_path in audit_paths:
        try:
            with audit_path.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
        except Exception:
            continue

        for row in rows:
            row_text = " ".join(str(v) for v in row.values()).lower()
            # 检查微构体/正方体体积：10000 nm -> 1e12 nm^3 (1000 um^3)
            if any(k in row_text for k in ("微构体", "正方体", "体积", "volume", "10000")):
                for val_str in row.values():
                    if not isinstance(val_str, str):
                        continue
                    if re.search(r"(?:1e\+?15|10\^15|10000\^3\s*=\s*1e\+?15)", val_str, re.IGNORECASE):
                        issues.append(
                            _issue(
                                f"parameter_sanity.{audit_path.stem}.cube_volume",
                                False,
                                f"{audit_path.name} 中的微构体体积存在数量级严重笔误 (10000^3 nm³ 应为 1e12 nm³，误写为 1e15)。",
                                {"row": row, "file": audit_path.name},
                            )
                        )
                        break

    if not issues:
        return [
            _issue(
                "parameter_sanity.dimensional_consistency",
                True,
                "参数审计表中的几何尺寸与体积换算量纲自洽。",
                {"audited_files": [p.name for p in audit_paths]},
            )
        ]
    return issues


def _anti_pseudo_crosscheck_issues(work_dir: Path) -> list[dict[str, Any]]:
    """Detect trivial parameter-swap pseudo-crosschecks in crosscheck result tables."""
    crosscheck_paths = sorted(work_dir.glob("*_crosscheck.csv"))
    legacy_crosscheck = work_dir / "crosscheck.csv"
    if legacy_crosscheck.is_file() and legacy_crosscheck not in crosscheck_paths:
        crosscheck_paths.append(legacy_crosscheck)

    if not crosscheck_paths:
        return []

    issues: list[dict[str, Any]] = []
    for path in crosscheck_paths:
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
                fieldnames = reader.fieldnames or []
        except Exception:
            continue

        if len(rows) < 5 or len(fieldnames) < 3:
            continue

        dist_cols = [
            col for col in fieldnames
            if any(term in col.lower() for term in ("dist", "result", "val", "algo", "method", "解析", "数值", "算法"))
        ]
        if len(dist_cols) >= 2:
            col1, col2 = dist_cols[0], dist_cols[1]
            diffs: list[float] = []
            exact_zeros = 0
            for r in rows:
                v1_raw = r.get(col1)
                v2_raw = r.get(col2)
                try:
                    v1 = float(str(v1_raw).strip()) if v1_raw is not None else None
                    v2 = float(str(v2_raw).strip()) if v2_raw is not None else None
                except (ValueError, TypeError):
                    v1, v2 = None, None
                if v1 is not None and v2 is not None and math.isfinite(v1) and math.isfinite(v2):
                    diff = abs(v1 - v2)
                    diffs.append(diff)
                    if diff == 0.0:
                        exact_zeros += 1

            if len(diffs) >= 20 and exact_zeros == len(diffs):
                header_text = " ".join(fieldnames).lower()
                if not any(term in header_text for term in ("analytic", "numeric", "grid", "optimization", "解析", "数值", "优化", "采样")):
                    issues.append(
                        _issue(
                            f"crosscheck_authenticity.{path.stem}",
                            False,
                            f"{path.name} 的复算列 {col1} 与 {col2} 浮点逐位完全恒等且未声明真实独立机理，疑似伪复算。",
                            {"file": path.name, "cols": [col1, col2], "exact_match_ratio": 1.0},
                        )
                    )

    if not issues:
        return [
            _issue(
                "crosscheck_authenticity.independent_methods",
                True,
                "独立交叉复算表通过真实性与数值差异特征核验。",
                {"checked_files": [p.name for p in crosscheck_paths]},
            )
        ]
    return issues


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
    issues.extend(_code_safety_issues(root))
    if require_manifest:
        issues.extend(_manifest_issues(root, required))
        issues.extend(_problem_parameter_issues(root))
        issues.extend(_dimensional_parameter_sanity_issues(root))
        issues.extend(_anti_pseudo_crosscheck_issues(root))
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
