#!/usr/bin/env python3
"""Audit a frozen modeling-result artifact without copying evidence contents."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FREEZE_SCHEMA = "mathmodel.result-freeze"
AUDIT_SCHEMA = "mathmodel.independent-audit"
VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AuditError(ValueError):
    """Raised for invalid audit input paths or reports."""


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
        raise AuditError("all paths must remain inside --workspace") from exc
    return resolved


def _relative(workspace: Path, path: Path) -> str:
    return path.relative_to(workspace).as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _check(status: str, code: str, detail: str, path: str | None = None) -> dict[str, str]:
    check = {"status": status, "code": code, "detail": detail}
    if path is not None:
        check["path"] = path
    return check


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditError("freeze artifact is unreadable JSON") from exc


def _audit_metrics(document: dict[str, Any], checks: list[dict[str, str]]) -> int:
    metrics = document.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        checks.append(_check("FAIL", "metrics_missing", "freeze artifact has no metrics array"))
        return 0
    for index, metric in enumerate(metrics):
        if not isinstance(metric, dict):
            checks.append(_check("FAIL", "metric_invalid", f"metrics[{index}] is not an object"))
            continue
        metric_id = metric.get("id", metric.get("name"))
        explanation = metric.get("explanation", metric.get("interpretation"))
        missing = [
            label
            for label, value in (
                ("id", metric_id),
                ("value", metric.get("value")),
                ("unit", metric.get("unit")),
                ("explanation", explanation),
            )
            if value is None or (isinstance(value, str) and not value.strip())
        ]
        if missing:
            checks.append(
                _check("FAIL", "metric_semantics_incomplete", f"metrics[{index}] missing: {', '.join(missing)}")
            )
        else:
            checks.append(_check("PASS", "metric_semantics_complete", f"metric {metric_id} has required semantics"))
    return len(metrics)


def _audit_sources(workspace: Path, document: dict[str, Any], checks: list[dict[str, str]]) -> int:
    sources = document.get("sources")
    if not isinstance(sources, list) or not sources:
        checks.append(_check("FAIL", "sources_missing", "freeze artifact has no source records"))
        return 0
    seen: set[str] = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            checks.append(_check("FAIL", "source_invalid", f"sources[{index}] is not an object"))
            continue
        source_path = source.get("relative_path", source.get("path"))
        expected_hash = source.get("sha256")
        if not isinstance(source_path, str) or not source_path or Path(source_path).is_absolute():
            checks.append(_check("FAIL", "source_path_invalid", f"sources[{index}] has an invalid relative path"))
            continue
        if source_path in seen:
            checks.append(_check("FAIL", "source_duplicate", "duplicate source path", source_path))
            continue
        seen.add(source_path)
        if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
            checks.append(_check("FAIL", "source_hash_invalid", "source SHA-256 is invalid", source_path))
            continue
        try:
            resolved = _resolve_inside_workspace(workspace, Path(source_path))
        except AuditError:
            checks.append(_check("FAIL", "source_path_invalid", "source path leaves workspace", source_path))
            continue
        if not resolved.is_file():
            checks.append(_check("FAIL", "source_missing", "source file is missing", source_path))
        elif _sha256(resolved) != expected_hash:
            checks.append(_check("FAIL", "source_hash_changed", "source SHA-256 changed", source_path))
        else:
            checks.append(_check("PASS", "source_hash_match", "source SHA-256 matches", source_path))
    return len(sources)


def build_report(workspace: Path, freeze: Path, paper: Path | None, figures_dir: Path | None) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    metric_count = 0
    source_count = 0
    try:
        document = _read_json(freeze)
    except AuditError as exc:
        checks.append(_check("FAIL", "freeze_unreadable", str(exc), _relative(workspace, freeze)))
        document = None
    if isinstance(document, dict):
        if document.get("schema") != FREEZE_SCHEMA or document.get("version") != VERSION:
            checks.append(_check("FAIL", "freeze_schema_invalid", "schema or version is unsupported"))
        else:
            checks.append(_check("PASS", "freeze_schema_valid", "freeze schema and version are supported"))
        metric_count = _audit_metrics(document, checks)
        source_count = _audit_sources(workspace, document, checks)
    elif document is not None:
        checks.append(_check("FAIL", "freeze_invalid", "freeze artifact must be a JSON object"))

    if paper is not None:
        if paper.is_file() and paper.stat().st_size > 0:
            checks.append(_check("PASS", "paper_present", "optional paper file is non-empty", _relative(workspace, paper)))
        else:
            checks.append(_check("FAIL", "paper_missing", "provided paper file is missing or empty", _relative(workspace, paper)))
    if figures_dir is not None:
        if not figures_dir.is_dir():
            checks.append(_check("FAIL", "figures_missing", "provided figures directory does not exist", _relative(workspace, figures_dir)))
        else:
            count = sum(1 for path in figures_dir.rglob("*") if path.is_file())
            status = "PASS" if count else "WARN"
            code = "figures_present" if count else "figures_empty"
            detail = f"figures directory contains {count} file(s)"
            checks.append(_check(status, code, detail, _relative(workspace, figures_dir)))

    status = "FAIL" if any(check["status"] == "FAIL" for check in checks) else "WARN" if any(check["status"] == "WARN" for check in checks) else "PASS"
    return {
        "schema": AUDIT_SCHEMA,
        "version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "freeze_file": _relative(workspace, freeze),
        "metric_count": metric_count,
        "source_count": source_count,
        "checks": checks,
        "scope": "Source integrity and basic traceability only; not mathematical correctness.",
    }


def _write_json(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 独立证据审计报告",
        "",
        f"## 结论\n\n{report['status']}",
        "",
        "## 检查项",
        "",
        "| 状态 | 编码 | 说明 | 路径 |",
        "| --- | --- | --- | --- |",
    ]
    for check in report["checks"]:
        lines.append(
            f"| {check['status']} | {check['code']} | {check['detail']} | {check.get('path', '')} |"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "本报告只验证来源哈希、字段完整性和基本路径可追溯性，不证明数学模型、推导或结论正确。",
            "",
        ]
    )
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("."))
    parser.add_argument("--freeze", type=Path, default=Path("reports/frozen_numbers.json"))
    parser.add_argument("--paper", type=Path)
    parser.add_argument("--figures-dir", type=Path)
    parser.add_argument("--output-json", type=Path, default=Path("reports/independent_audit_report.json"))
    parser.add_argument("--output-md", type=Path, default=Path("reports/independent_audit_report.md"))
    args = parser.parse_args(argv)
    try:
        workspace = _resolve_workspace(args.workspace)
        freeze = _resolve_inside_workspace(workspace, args.freeze)
        paper = _resolve_inside_workspace(workspace, args.paper) if args.paper else None
        figures_dir = _resolve_inside_workspace(workspace, args.figures_dir) if args.figures_dir else None
        output_json = _resolve_inside_workspace(workspace, args.output_json)
        output_md = _resolve_inside_workspace(workspace, args.output_md)
        if output_json == freeze or output_md == freeze:
            raise AuditError("audit outputs must not overwrite the freeze artifact")
        report = build_report(workspace, freeze, paper, figures_dir)
        _write_json(output_json, report)
        _write_markdown(output_md, report)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 1 if report["status"] == "FAIL" else 0
    except (OSError, AuditError) as exc:
        print(
            json.dumps(
                {
                    "schema": AUDIT_SCHEMA,
                    "version": VERSION,
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
