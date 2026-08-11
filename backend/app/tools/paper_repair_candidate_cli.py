"""Container-only CLI for one audited post-freeze paper repair candidate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.tools.paper_repair_candidate import (
    PaperRepairCandidateError,
    run_editorial_repair_candidate,
    run_format_compliance_candidate,
    run_paper_repair_candidate,
    run_presentation_reflow,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="应用一次受控论文修复候选")
    parser.add_argument("task_id")
    parser.add_argument("candidate_path", nargs="?")
    parser.add_argument(
        "--editorial-quality",
        action="store_true",
        help="在已完成论文的编辑质量报告 FAIL 后使用独立返修预算",
    )
    parser.add_argument(
        "--presentation-reflow",
        action="store_true",
        help="仅对已预检完成论文执行一次无正文改写的版式重排并等待导出",
    )
    parser.add_argument(
        "--format-compliance",
        action="store_true",
        help="按参赛队明确格式要求应用一次受审计的完整论文候选并等待导出",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    if not Path("/.dockerenv").is_file():
        print(json.dumps({"ok": False, "error": "论文候选 CLI 只能在 backend 容器内运行"}, ensure_ascii=False))
        return 2
    args = build_parser().parse_args(argv)
    try:
        if args.presentation_reflow:
            if args.editorial_quality or args.format_compliance or args.candidate_path:
                raise PaperRepairCandidateError("版式重排不能同时携带候选文件、编辑质量或格式合规标记")
            result = run_presentation_reflow(args.task_id)
        else:
            if not args.candidate_path:
                raise PaperRepairCandidateError("论文候选文件路径不能为空")
            if args.editorial_quality and args.format_compliance:
                raise PaperRepairCandidateError("编辑质量与格式合规候选不能同时启用")
            runner = (
                run_editorial_repair_candidate
                if args.editorial_quality
                else run_format_compliance_candidate
                if args.format_compliance
                else run_paper_repair_candidate
            )
            result = runner(args.task_id, args.candidate_path)
    except PaperRepairCandidateError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
