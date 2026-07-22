"""Create an auditable human/Codex review packet from frozen result tables.

The execution validator proves that code ran and declared evidence exists.  It
cannot prove that a physically absurd or explicitly failed result is suitable
for a competition paper.  This module deliberately uses only conservative,
domain-neutral signals and leaves the final mathematical judgement to a named
reviewer.
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


_RESULT_FILE = re.compile(r"^(ques\d+)_results\.csv$", re.IGNORECASE)
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


def _is_nonfinite(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _NONFINITE_VALUES:
        return True
    try:
        return not math.isfinite(float(normalized))
    except (TypeError, ValueError):
        return False


def build_execution_quality_review(work_dir: str) -> dict:
    """Inspect formal result CSVs and return a stable, reviewer-facing report."""
    root = Path(work_dir)
    findings: list[dict] = []
    sources: list[dict] = []
    failed_subtasks: set[str] = set()

    for path in sorted(root.glob("ques*_results.csv"), key=lambda item: item.name):
        match = _RESULT_FILE.fullmatch(path.name)
        if match is None:
            continue
        subtask = match.group(1).lower()
        sources.append({"path": path.name, "sha256": _file_sha256(path)})
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except (OSError, UnicodeError, csv.Error) as exc:
            findings.append(
                {
                    "id": f"{subtask}.result_table_readable",
                    "subtask_id": subtask,
                    "severity": "blocker",
                    "message": f"结果表无法读取：{type(exc).__name__}",
                    "source": path.name,
                }
            )
            failed_subtasks.add(subtask)
            continue

        for row_index, row in enumerate(rows, start=2):
            for column, raw_value in row.items():
                if raw_value is None:
                    continue
                value = str(raw_value).strip()
                normalized_column = str(column or "").strip().lower()
                if normalized_column in {item.lower() for item in _STATUS_COLUMNS} and value.lower() in _FAIL_VALUES:
                    findings.append(
                        {
                            "id": f"{subtask}.declared_failure.{row_index}.{normalized_column}",
                            "subtask_id": subtask,
                            "severity": "blocker",
                            "message": f"第 {row_index} 行在“{column}”列明确标记为“{value}”。",
                            "source": path.name,
                        }
                    )
                    failed_subtasks.add(subtask)
                elif value and _is_nonfinite(value):
                    findings.append(
                        {
                            "id": f"{subtask}.nonfinite.{row_index}.{normalized_column}",
                            "subtask_id": subtask,
                            "severity": "blocker",
                            "message": f"第 {row_index} 行“{column}”包含非有限数值“{value}”。",
                            "source": path.name,
                        }
                    )
                    failed_subtasks.add(subtask)

    identity_payload = {
        "schema_version": "mathmodel.execution-quality-review.v1",
        "sources": sources,
        "findings": findings,
    }
    review_id = hashlib.sha256(
        json.dumps(identity_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        **identity_payload,
        "generated_at": datetime.datetime.now().isoformat(),
        "review_id": review_id,
        "status": "NEEDS_REVIEW" if findings else "PASS",
        "failed_subtasks": sorted(failed_subtasks),
        "review_boundary": (
            "本报告只识别结果表中的明确失败和非有限数值；PASS 不代表模型、物理量纲、"
            "公式推导或竞赛结论正确，仍需 Codex/人工逐题复核。"
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
        f"- 待复核/返修子题：{('、'.join(report['failed_subtasks']) or '无机器命中项')}",
        "",
        "> " + report["review_boundary"],
        "",
        "## 发现",
        "",
    ]
    if report["findings"]:
        for finding in report["findings"]:
            lines.append(
                f"- [{finding['subtask_id']}] {finding['message']}（{finding['source']}）"
            )
    else:
        lines.append("- 未发现明确失败标记或非有限数值。")
    lines.extend(
        [
            "",
            "## 审查动作",
            "",
            "1. 对照题面、ModelPlan、代码、结果表检查假设、量纲、守恒、约束和关键数值。",
            "2. 有问题时调用 `POST /modeling/{task_id}/execution-review`，"
            "使用 `action=repair` 并给出子题和可执行修正意见。",
            "3. 仅在逐题复核充分时使用 `action=approve`；审批理由会写入 checkpoint 审计。",
            "",
        ]
    )
    md_path = root / "execution_quality_review.md"
    md_tmp = md_path.with_suffix(".md.tmp")
    md_tmp.write_text("\n".join(lines), encoding="utf-8")
    os.replace(md_tmp, md_path)
    return report
