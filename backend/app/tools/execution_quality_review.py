"""Create an auditable human/Codex review packet from registered frozen evidence.

The execution validator proves that code ran and declared evidence exists.  It
cannot prove that a physically absurd or explicitly failed result is suitable
for a competition paper.  This module deliberately uses only conservative,
domain-neutral signals and leaves the final mathematical judgement to a named
reviewer.

Review sources are taken from the execution-evidence manifest
(``execution_validation.json``), never from filename guessing: every formal
subtask must register readable numeric sources (constraint/metric CSVs), and
each registered file is re-hashed on disk.  The three outcomes are strictly
separated:

* ``PASS``         - every formal subtask had registered, un-drifted sources
                     and no content finding was hit.
* ``NEEDS_REVIEW`` - evidence is intact but a conservative content signal fired
                     (declared failure, non-finite value, infeasible subtask).
* ``BLOCKED``      - the evidence chain itself is unusable (missing manifest,
                     subtask without numeric sources, missing file, or a file
                     whose current hash differs from the registered one).

``BLOCKED`` must never be approved; only ``PASS``/``NEEDS_REVIEW`` packets are
approvable, and even then machine PASS does not mean the mathematics is right.
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import json
import math
import os
import re
from pathlib import Path

REVIEW_RULES_VERSION = "2026-09-05.1"
_SCHEMA_VERSION = "mathmodel.execution-quality-review.v2"

_MANIFEST_NAME = "execution_validation.json"
_FROZEN_NAME = "frozen_results.json"
_PROBLEM_CONTRACT_NAME = "problem_contract.json"
_MODELER_PLAN_NAME = "modeler_plan.json"
_NOTEBOOK_NAME = "notebook.ipynb"

_FORMAL_SUBTASK = re.compile(r"^ques\d+$", re.IGNORECASE)
_STATUS_COLUMNS = {
    "是否达标",
    "是否通过",
    "达标",
    "通过",
    "passed",
    "pass",
    "status",
    "feasible",
}
_FAIL_VALUES = {
    "否",
    "不通过",
    "未通过",
    "不达标",
    "失败",
    "false",
    "fail",
    "failed",
    "no",
    "infeasible",
}
_NONFINITE_VALUES = {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity"}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_if_file(root: Path, relative: str) -> str | None:
    path = _safe_join(root, relative)
    if path is None or not path.is_file():
        return None
    return _file_sha256(path)


def _safe_join(root: Path, relative: object) -> Path | None:
    if not isinstance(relative, str) or not relative.strip():
        return None
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _is_nonfinite(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _NONFINITE_VALUES:
        return True
    try:
        return not math.isfinite(float(normalized))
    except (TypeError, ValueError):
        return False


def _read_json(path: Path) -> dict | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _subtask_sources(subtask: dict) -> list[dict]:
    """Registered result sources of one formal subtask, in stable order."""
    entries: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(path: object, sha256: object, role: str) -> None:
        if not isinstance(path, str) or not isinstance(sha256, str):
            return
        key = (path, sha256)
        if key not in seen:
            seen.add(key)
            entries.append({"path": path, "sha256": sha256, "role": role})

    for kind, field in (("constraint", "constraints"), ("metric", "metrics")):
        for item in subtask.get(field) or []:
            if isinstance(item, dict) and isinstance(item.get("source"), dict):
                add(item["source"].get("path"), item["source"].get("sha256"), kind)
    for figure in subtask.get("figures") or []:
        if isinstance(figure, dict):
            add(figure.get("data_path"), figure.get("data_sha256"), "figure_data")
    return entries


def _scan_csv(path: Path, subtask_id: str, findings: list[dict]) -> set[str]:
    """Conservative content scan; returns subtasks with a hit."""
    hits: set[str] = set()
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error) as exc:
        findings.append(
            {
                "id": f"{subtask_id}.result_table_readable",
                "subtask_id": subtask_id,
                "severity": "review",
                "message": f"结果表无法读取：{type(exc).__name__}",
                "source": path.name,
            }
        )
        hits.add(subtask_id)
        return hits
    for row_index, row in enumerate(rows, start=2):
        for column, raw_value in row.items():
            if raw_value is None:
                continue
            value = str(raw_value).strip()
            normalized_column = str(column or "").strip().lower()
            if normalized_column in {item.lower() for item in _STATUS_COLUMNS} and value.lower() in _FAIL_VALUES:
                findings.append(
                    {
                        "id": f"{subtask_id}.declared_failure.{row_index}.{normalized_column}",
                        "subtask_id": subtask_id,
                        "severity": "review",
                        "message": f"第 {row_index} 行在“{column}”列明确标记为“{value}”。",
                        "source": path.name,
                    }
                )
                hits.add(subtask_id)
            elif value and _is_nonfinite(value):
                findings.append(
                    {
                        "id": f"{subtask_id}.nonfinite.{row_index}.{normalized_column}",
                        "subtask_id": subtask_id,
                        "severity": "review",
                        "message": f"第 {row_index} 行“{column}”包含非有限数值“{value}”。",
                        "source": path.name,
                    }
                )
                hits.add(subtask_id)
    return hits


def build_execution_quality_review(work_dir: str) -> dict:
    """Inspect registered evidence per formal subtask; never guess by filename."""
    root = Path(work_dir)
    findings: list[dict] = []
    sources_payload: list[dict] = []
    subtasks_payload: list[dict] = []
    failed_subtasks: set[str] = set()
    blocked = False

    manifest = _read_json(root / _MANIFEST_NAME)
    if manifest is None:
        findings.append(
            {
                "id": "registry.missing",
                "subtask_id": "",
                "severity": "blocker",
                "message": f"缺少或无法读取执行证据清单 {_MANIFEST_NAME}，质量审批没有可核对的登记来源。",
                "source": _MANIFEST_NAME,
            }
        )
        blocked = True
        formal: list[dict] = []
    else:
        formal = [
            item
            for item in manifest.get("subtasks") or []
            if isinstance(item, dict) and _FORMAL_SUBTASK.match(str(item.get("id") or ""))
        ]
        if not formal:
            findings.append(
                {
                    "id": "registry.no_formal_subtasks",
                    "subtask_id": "",
                    "severity": "blocker",
                    "message": "执行证据清单中没有正式子题（quesN），没有检查对象不等于通过。",
                    "source": _MANIFEST_NAME,
                }
            )
            blocked = True

    for subtask in formal:
        subtask_id = str(subtask.get("id")).lower()
        feasible = bool(subtask.get("feasible"))
        subtasks_payload.append({"id": subtask_id, "feasible": feasible})
        if not feasible:
            findings.append(
                {
                    "id": f"{subtask_id}.declared_infeasible",
                    "subtask_id": subtask_id,
                    "severity": "review",
                    "message": "执行证据声明该子题不可行，需人工确认是否可进入论文。",
                    "source": _MANIFEST_NAME,
                }
            )
            failed_subtasks.add(subtask_id)

        entries = _subtask_sources(subtask)
        numeric = [entry for entry in entries if entry["role"] in ("constraint", "metric")]
        if not numeric:
            findings.append(
                {
                    "id": f"{subtask_id}.no_numeric_source",
                    "subtask_id": subtask_id,
                    "severity": "blocker",
                    "message": "正式子题没有登记任何数值结果来源（constraints/metrics 均无 source），审批依据不成立。",
                    "source": _MANIFEST_NAME,
                }
            )
            blocked = True
            continue

        seen: set[tuple[str, str]] = set()
        for entry in entries:
            key = (subtask_id, entry["path"], entry["sha256"])
            if key in seen:
                continue
            seen.add(key)
            path = _safe_join(root, entry["path"])
            actual = _hash_if_file(root, entry["path"])
            if path is None or actual is None:
                findings.append(
                    {
                        "id": f"{subtask_id}.source_missing",
                        "subtask_id": subtask_id,
                        "severity": "blocker",
                        "message": f"登记的来源文件不存在或不可读：{entry['path']}",
                        "source": str(entry["path"]),
                    }
                )
                blocked = True
                continue
            if actual != entry["sha256"]:
                findings.append(
                    {
                        "id": f"{subtask_id}.source_drift",
                        "subtask_id": subtask_id,
                        "severity": "blocker",
                        "message": (
                            f"来源文件当前哈希与执行证据登记不一致（{entry['path']}），"
                            "证据在登记后被改动，需重新执行并登记。"
                        ),
                        "source": str(entry["path"]),
                    }
                )
                blocked = True
                sources_payload.append(
                    {
                        "subtask_id": subtask_id,
                        "path": entry["path"],
                        "sha256": actual,
                        "registered_sha256": entry["sha256"],
                        "role": entry["role"],
                        "drift": True,
                    }
                )
                continue
            sources_payload.append(
                {
                    "subtask_id": subtask_id,
                    "path": entry["path"],
                    "sha256": actual,
                    "role": entry["role"],
                    "drift": False,
                }
            )
            if entry["path"].lower().endswith(".csv"):
                failed_subtasks |= _scan_csv(path, subtask_id, findings)

    identity_payload = {
        "schema_version": _SCHEMA_VERSION,
        "rules_version": REVIEW_RULES_VERSION,
        "problem_contract_sha256": _hash_if_file(root, _PROBLEM_CONTRACT_NAME),
        "modeler_plan_sha256": _hash_if_file(root, _MODELER_PLAN_NAME),
        "frozen_registry_sha256": _hash_if_file(root, _FROZEN_NAME),
        "executed_code_sha256": _hash_if_file(root, _NOTEBOOK_NAME),
        "subtasks": sorted(subtasks_payload, key=lambda item: item["id"]),
        "sources": sorted(
            sources_payload, key=lambda item: (item["subtask_id"], item["path"], item["role"])
        ),
        "findings": findings,
    }
    review_id = hashlib.sha256(
        json.dumps(identity_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if blocked:
        status = "BLOCKED"
    elif findings:
        status = "NEEDS_REVIEW"
    else:
        status = "PASS"
    return {
        **identity_payload,
        "generated_at": datetime.datetime.now().isoformat(),
        "review_id": review_id,
        "status": status,
        "failed_subtasks": sorted(failed_subtasks),
        "blocked_subtasks": sorted(
            {item["subtask_id"] for item in findings if item["severity"] == "blocker" and item["subtask_id"]}
        ),
        "review_boundary": (
            "本报告只识别登记证据的完整性与结果表中的明确失败/非有限数值；"
            "PASS 不代表模型、物理量纲、公式推导或竞赛结论正确，仍需 Codex/人工逐题复核。"
        ),
    }


def write_execution_quality_review(work_dir: str) -> dict:
    """Write JSON/Markdown review artifacts atomically and return the report."""
    report = build_execution_quality_review(work_dir)
    root = Path(work_dir)
    json_path = root / "execution_quality_review.json"
    tmp_path = json_path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp_path, json_path)

    lines = [
        "# 执行结果质量复核",
        "",
        f"- 机器筛查状态：`{report['status']}`",
        f"- 复核编号：`{report['review_id']}`",
        f"- 检查规则版本：`{report['rules_version']}`",
        f"- 待复核子题：{('、'.join(report['failed_subtasks']) or '无机器命中项')}",
        f"- 阻断子题：{('、'.join(report['blocked_subtasks']) or ('全链阻断' if report['status'] == 'BLOCKED' else '无'))}",
        "",
        "> " + report["review_boundary"],
        "",
        "## 来源覆盖（按执行证据登记）",
        "",
    ]
    coverage: dict[str, list[str]] = {}
    for source in report["sources"]:
        coverage.setdefault(source["subtask_id"], []).append(
            f"{source['path']}（{source['role']}{'，哈希漂移' if source.get('drift') else ''}）"
        )
    for subtask in report["subtasks"]:
        files = coverage.get(subtask["id"], [])
        mark = "✔" if files else "✘ 无数值来源"
        lines.append(f"- `{subtask['id']}` feasible={subtask['feasible']} {mark}")
        for name in files:
            lines.append(f"  - {name}")
    lines.extend(["", "## 发现", ""])
    if report["findings"]:
        for finding in report["findings"]:
            lines.append(
                f"- [{finding['severity']}][{finding['subtask_id'] or '-'}] "
                f"{finding['message']}（{finding['source']}）"
            )
    else:
        lines.append("- 未发现明确失败标记或非有限数值。")
    lines.extend(
        [
            "",
            "## 审查动作",
            "",
            "1. 对照题面、ModelPlan、代码、结果表检查假设、量纲、守恒、约束和关键数值。",
            "   - **特别检查（Audit-on-Write 机制）**：必须将代码中的核心变量（如 `dist_sq`）显式映射到文档推导的物理量（如表面距 $d_{surface}$），一旦发现诸如“把 3D 圆柱体退化为质点进行轴心距比较”等代码与数学模型脱节的硬伤，立即打回并判定为物理失效。",
            "2. 有问题时调用 `POST /modeling/{task_id}/execution-review`，"
            "使用 `action=repair` 并给出子题和可执行修正意见。",
            "3. 仅在逐题复核充分时使用 `action=approve`；审批理由会写入 checkpoint 审计。",
            "4. `BLOCKED` 状态禁止 approve：证据链本身不完整或已漂移，只能返修重建。",
            "",
        ]
    )
    md_path = root / "execution_quality_review.md"
    md_tmp = md_path.with_suffix(".md.tmp")
    md_tmp.write_text("\n".join(lines), encoding="utf-8")
    os.replace(md_tmp, md_path)
    return report
