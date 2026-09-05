"""Paper content revision ledger (batch 2 of the stable-release program).

One auditable content version exists per formal save of the manuscript.  Every
controlled write of ``res.json`` + ``res.md`` (Writer save, paper/editorial/
format repair candidates, sanctioned manual re-save) bumps the revision and
records the exact hashes of the content pair plus the frozen-results version
they were built against.  Exports and the candidate manifest bind to this
revision, so "new Markdown shipped with a stale JSON / stale frozen facts"
becomes detectable instead of silent.

The ledger never rewrites content; it only records what is on disk at publish
time.  ``verify_paper_revision`` answers whether the current files still match
the last recorded save (i.e. nobody hand-edited one side afterwards).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any

PAPER_REVISION_FILENAME = "paper_revision.json"
_SCHEMA_VERSION = "mathmodel.paper-revision.v1"

_ALLOWED_ORIGINS = {
    "writer_save",
    "paper_repair",
    "editorial_repair",
    "format_compliance",
    "manual_save",
}


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_paper_revision(work_dir: str | os.PathLike[str]) -> dict[str, Any] | None:
    """Return the current revision ledger, or None when absent/unreadable."""
    path = Path(work_dir) / PAPER_REVISION_FILENAME
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def bump_paper_revision(
    work_dir: str | os.PathLike[str], *, origin: str
) -> dict[str, Any]:
    """Record a new content revision from the files just published to disk.

    ``origin`` must be one of the controlled save paths; it is written into the
    audit trail so reviewers can see who produced each revision.
    """
    if origin not in _ALLOWED_ORIGINS:
        raise ValueError(f"未知保存来源：{origin}")
    root = Path(work_dir)
    previous = read_paper_revision(root) or {}
    try:
        previous_revision = int(previous.get("revision", 0))
    except (TypeError, ValueError):
        previous_revision = 0
    record = {
        "schema_version": _SCHEMA_VERSION,
        "revision": previous_revision + 1,
        "origin": origin,
        "res_json_sha256": _sha256_file(root / "res.json"),
        "res_md_sha256": _sha256_file(root / "res.md"),
        "frozen_sha256": _sha256_file(root / "frozen_results.json"),
        "updated_at": datetime.datetime.now().isoformat(),
    }
    path = root / PAPER_REVISION_FILENAME
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return record


def verify_paper_revision(work_dir: str | os.PathLike[str]) -> dict[str, Any]:
    """Check that res.json/res.md/frozen still match the last recorded save."""
    root = Path(work_dir)
    record = read_paper_revision(root)
    issues: list[str] = []
    if record is None:
        if (root / "res.md").is_file():
            issues.append(
                "缺少 paper_revision.json：正式内容未经统一保存入口登记，无法证明 res.json/res.md 同源。"
            )
        return {"ok": False, "revision": None, "issues": issues}
    pairs = {
        "res.json": record.get("res_json_sha256"),
        "res.md": record.get("res_md_sha256"),
        "frozen_results.json": record.get("frozen_sha256"),
    }
    for name, expected in pairs.items():
        actual = _sha256_file(root / name)
        if expected is None and actual is None:
            continue
        if expected != actual:
            label = "缺失" if actual is None else "内容与登记修订不一致"
            issues.append(f"{name} {label}（修订号 {record.get('revision')} 之后被改动或从未登记）。")
    return {"ok": not issues, "revision": record.get("revision"), "issues": issues}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="论文内容修订号台账：手工重存后登记（bump）或校验（--verify）。"
    )
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--origin", default="manual_save", choices=sorted(_ALLOWED_ORIGINS))
    parser.add_argument("--verify", action="store_true", help="只校验台账与盘上一致性，不登记")
    cli_args = parser.parse_args()
    cli_result = (
        verify_paper_revision(cli_args.work_dir)
        if cli_args.verify
        else bump_paper_revision(cli_args.work_dir, origin=cli_args.origin)
    )
    print(json.dumps(cli_result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if cli_result.get("ok", True) else 1)
