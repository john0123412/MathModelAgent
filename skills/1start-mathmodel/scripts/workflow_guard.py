#!/usr/bin/env python3
"""Report the next experimental math-modeling skill from workspace artifacts.

This guard deliberately inspects only the current task workspace.  It does not
look at the WebUI task directory and it does not decide whether a model is
mathematically sound; it only makes missing hand-off artifacts explicit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STAGES = (
    (
        "analysis-modeling",
        "2analysis-modeling",
        ("reports/ANALYSIS_MODELING_REPORT.md",),
    ),
    (
        "method-validation",
        "2a-method-validation",
        ("reports/METHOD_VALIDATION.md", "reports/METHOD_SELECTION.md"),
    ),
    (
        "coding-visual",
        "3coding-visual",
        ("reports/RESULTS_REPORT.md",),
    ),
    (
        "result-freeze",
        "3a-result-freeze",
        ("reports/frozen_numbers.json",),
    ),
    (
        "drawio",
        "4drawio",
        ("reports/DRAWIO_REPORT.md",),
    ),
    (
        "writing",
        "5writing",
        ("paper/main.typ|paper/main.tex",),
    ),
    (
        "independent-audit",
        "6a-independent-audit",
        ("reports/independent_audit_report.json",),
    ),
    (
        "verification",
        "6verity",
        ("reports/VERIFY_REPORT.md",),
    ),
)


def _resolve_workspace(path: Path) -> Path:
    return path.expanduser().resolve()


def _resolve_inside_workspace(workspace: Path, path: Path) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise ValueError("--output must remain inside --workspace") from exc
    return resolved


def _artifact_exists(workspace: Path, artifact: str) -> bool:
    return any((workspace / option).is_file() for option in artifact.split("|"))


def _missing(workspace: Path, artifacts: tuple[str, ...]) -> list[str]:
    return [artifact for artifact in artifacts if not _artifact_exists(workspace, artifact)]


def build_report(workspace: Path) -> dict[str, Any]:
    evidence_chain_active = any(
        (workspace / path).is_file()
        for path in (
            "reports/METHOD_VALIDATION.md",
            "reports/METHOD_SELECTION.md",
            "reports/frozen_numbers.json",
            "reports/independent_audit_report.json",
        )
    )
    completed: list[str] = []
    for stage, skill, artifacts in STAGES:
        missing = _missing(workspace, artifacts)
        if missing:
            return {
                "schema": "mathmodel.experimental-workflow-guard",
                "version": 1,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "workspace": ".",
                "status": "WARN",
                "evidence_chain": "active" if evidence_chain_active else "not_enabled",
                "current_stage": stage,
                "recommended_skill": skill,
                "completed_stages": completed,
                "missing_prerequisites": missing,
            }
        completed.append(stage)
    return {
        "schema": "mathmodel.experimental-workflow-guard",
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "workspace": ".",
        "status": "PASS",
        "evidence_chain": "active" if evidence_chain_active else "not_enabled",
        "current_stage": "complete",
        "recommended_skill": None,
        "completed_stages": completed,
        "missing_prerequisites": [],
    }


def _write_json(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("."))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/workflow_guard_report.json"),
    )
    args = parser.parse_args(argv)
    try:
        workspace = _resolve_workspace(args.workspace)
        output = _resolve_inside_workspace(workspace, args.output)
        report = build_report(workspace)
        _write_json(output, report)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema": "mathmodel.experimental-workflow-guard",
                    "version": 1,
                    "status": "FAIL",
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
