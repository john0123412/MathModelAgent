#!/usr/bin/env python3
"""Freeze and verify traceable mathematical-model result summaries.

The script deliberately stores only key metrics, workspace-relative paths, and
SHA-256 hashes. It never copies the contents of evidence files into the
freeze artifact.
"""

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
VERIFY_SCHEMA = "mathmodel.result-freeze.verify"
VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|token|secret|password|credential|authorization|cookie|private[_-]?key)",
    re.IGNORECASE,
)
SENSITIVE_VALUE_RE = re.compile(
    r"(?:\b(?:api[_-]?key|token|secret|password)\s*[:=]|\bBearer\s+\S+|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:sk|pk|rk)_[A-Za-z0-9_-]{16,})",
    re.IGNORECASE,
)


class FreezeError(ValueError):
    """Raised when an input would make a freeze artifact unsafe or invalid."""


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
        raise FreezeError("all paths must remain inside --workspace") from exc
    return resolved


def _relative_path(workspace: Path, path: Path) -> str:
    return path.relative_to(workspace).as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise FreezeError(f"cannot read JSON: {_relative_or_name(path)}") from exc


def _relative_or_name(path: Path) -> str:
    return path.name


def _reject_sensitive_content(value: Any, location: str = "metrics") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise FreezeError(f"{location} contains a non-string field name")
            if SENSITIVE_KEY_RE.search(key):
                raise FreezeError(f"{location} contains a sensitive field name")
            _reject_sensitive_content(nested, f"{location}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_sensitive_content(nested, f"{location}[{index}]")
    elif isinstance(value, str) and SENSITIVE_VALUE_RE.search(value):
        raise FreezeError(f"{location} appears to contain sensitive material")


def _load_metrics(metrics_file: Path) -> list[dict[str, Any]]:
    if not metrics_file.is_file():
        raise FreezeError("the --metrics file does not exist")
    if metrics_file.stat().st_size > 1_000_000:
        raise FreezeError("the --metrics file is too large; freeze a concise summary instead")
    document = _read_json(metrics_file)
    if not isinstance(document, dict) or not isinstance(document.get("metrics"), list):
        raise FreezeError("the --metrics JSON must be an object with a metrics array")
    metrics = document["metrics"]
    for index, metric in enumerate(metrics):
        if not isinstance(metric, dict):
            raise FreezeError(f"metrics[{index}] must be an object")
    _reject_sensitive_content(metrics)
    return metrics


def _source_record(workspace: Path, path: Path, role: str) -> dict[str, str]:
    if not path.is_file():
        raise FreezeError(f"source file does not exist: {_relative_path(workspace, path)}")
    return {
        "relative_path": _relative_path(workspace, path),
        "sha256": _sha256(path),
        "role": role,
    }


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def _check(status: str, code: str, detail: str, relative_path: str | None = None) -> dict[str, str]:
    result = {"status": status, "code": code, "detail": detail}
    if relative_path is not None:
        result["relative_path"] = relative_path
    return result


def freeze(args: argparse.Namespace) -> int:
    workspace = _resolve_workspace(args.workspace)
    metrics_file = _resolve_inside_workspace(workspace, args.metrics)
    output = _resolve_inside_workspace(workspace, args.output)
    source_arguments = [_resolve_inside_workspace(workspace, source) for source in args.source]
    if not source_arguments:
        raise FreezeError("provide at least one --source evidence file")

    metrics = _load_metrics(metrics_file)
    records = [_source_record(workspace, metrics_file, "metrics")]
    seen_paths = {records[0]["relative_path"]}
    for source in source_arguments:
        record = _source_record(workspace, source, "evidence")
        if record["relative_path"] in seen_paths:
            raise FreezeError("each source path must be supplied only once")
        seen_paths.add(record["relative_path"])
        records.append(record)

    document = {
        "schema": FREEZE_SCHEMA,
        "version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "sources": records,
    }
    _write_json(output, document)
    print(
        json.dumps(
            {
                "schema": FREEZE_SCHEMA,
                "version": VERSION,
                "status": "PASS",
                "output": _relative_path(workspace, output),
                "metric_count": len(metrics),
                "source_count": len(records),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def verify(args: argparse.Namespace) -> int:
    workspace = _resolve_workspace(args.workspace)
    output = _resolve_inside_workspace(workspace, args.output)
    checks: list[dict[str, str]] = []

    try:
        document = _read_json(output)
    except FreezeError as exc:
        checks.append(_check("FAIL", "freeze_file_unreadable", str(exc)))
        document = None

    if isinstance(document, dict):
        if document.get("schema") != FREEZE_SCHEMA or document.get("version") != VERSION:
            checks.append(_check("FAIL", "freeze_schema_invalid", "schema or version is not supported"))
        sources = document.get("sources")
        if not isinstance(sources, list) or not sources:
            checks.append(_check("FAIL", "sources_invalid", "freeze file has no source records"))
        else:
            seen_paths: set[str] = set()
            for index, source in enumerate(sources):
                if not isinstance(source, dict):
                    checks.append(_check("FAIL", "source_invalid", f"sources[{index}] is not an object"))
                    continue
                relative_path = source.get("relative_path")
                expected_hash = source.get("sha256")
                if not isinstance(relative_path, str) or Path(relative_path).is_absolute():
                    checks.append(_check("FAIL", "source_path_invalid", f"sources[{index}] has an invalid path"))
                    continue
                if relative_path in seen_paths:
                    checks.append(_check("FAIL", "source_duplicate", "duplicate source path", relative_path))
                    continue
                seen_paths.add(relative_path)
                if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
                    checks.append(_check("FAIL", "source_hash_invalid", "source has an invalid SHA-256", relative_path))
                    continue
                try:
                    source_path = _resolve_inside_workspace(workspace, Path(relative_path))
                except FreezeError:
                    checks.append(_check("FAIL", "source_path_invalid", "source path leaves workspace", relative_path))
                    continue
                if not source_path.is_file():
                    checks.append(_check("FAIL", "source_missing", "source file is missing", relative_path))
                    continue
                if _sha256(source_path) != expected_hash:
                    checks.append(_check("FAIL", "source_hash_changed", "source SHA-256 changed", relative_path))
                else:
                    checks.append(_check("PASS", "source_hash_match", "source SHA-256 matches", relative_path))
    elif document is not None:
        checks.append(_check("FAIL", "freeze_file_invalid", "freeze file must contain a JSON object"))

    has_failure = any(check["status"] == "FAIL" for check in checks)
    status = "FAIL" if has_failure else "PASS"
    print(
        json.dumps(
            {
                "schema": VERIFY_SCHEMA,
                "version": VERSION,
                "status": status,
                "freeze_file": _relative_path(workspace, output),
                "checks": checks,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 1 if has_failure else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("."), help="workspace root")
    parser.add_argument("--metrics", type=Path, help="JSON file containing a metrics array")
    parser.add_argument("--source", action="append", type=Path, default=[], help="repeatable evidence file")
    parser.add_argument("--output", type=Path, required=True, help="freeze JSON path")
    parser.add_argument("--verify", action="store_true", help="verify an existing freeze JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.verify and args.metrics is None:
        parser.error("--metrics is required unless --verify is used")
    try:
        return verify(args) if args.verify else freeze(args)
    except FreezeError as exc:
        schema = VERIFY_SCHEMA if args.verify else FREEZE_SCHEMA
        print(
            json.dumps(
                {
                    "schema": schema,
                    "version": VERSION,
                    "status": "FAIL",
                    "checks": [_check("FAIL", "input_invalid", str(exc))],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
