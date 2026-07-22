"""容器内受控修复候选 CLI。

示例（在 backend 容器中）：
``uv run python -m app.tools.repair_candidate_cli TASK_ID ques1 REVIEW_ID candidate.py evidence.json``

CLI 不提供任意代码片段参数，也不开放 HTTP；候选脚本和证据 JSON 都必须是
目标任务目录内的现有文件。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.tools.repair_candidate import RepairCandidateError, run_repair_candidate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行一次受控 Coder 修复候选")
    parser.add_argument("task_id")
    parser.add_argument("subtask_id")
    parser.add_argument("review_id")
    parser.add_argument("script_path")
    parser.add_argument("evidence_path")
    return parser


async def _run(args: argparse.Namespace) -> int:
    try:
        result = await run_repair_candidate(
            args.task_id,
            args.subtask_id,
            args.review_id,
            args.script_path,
            args.evidence_path,
        )
    except RepairCandidateError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    # This entry point is deliberately not a host-side arbitrary execution
    # helper.  Codex/human operators guide it from outside, but execution stays
    # inside the hardened backend container.
    if not Path("/.dockerenv").is_file():
        print(json.dumps({"ok": False, "error": "受控候选 CLI 只能在 backend 容器内运行"}, ensure_ascii=False))
        return 2
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print(json.dumps({"ok": False, "error": "候选执行已中断"}, ensure_ascii=False))
        return 130


if __name__ == "__main__":
    sys.exit(main())
