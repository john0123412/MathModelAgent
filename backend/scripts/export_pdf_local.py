"""Export task Markdown to PDF with host pandoc/xelatex."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PDF_HEADING_STYLE = (
    r"header-includes=\ctexset{"
    r"section={format={\centering\zihao{3}\heiti}},"
    r"subsection={format={\zihao{4}\heiti}},"
    r"subsubsection={format={\normalsize\heiti}}"
    r"}"
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_work_dir(task_or_path: str) -> Path:
    candidate = Path(task_or_path)
    if candidate.exists():
        return candidate.resolve()
    task_id = task_or_path.strip()
    if not TASK_ID_PATTERN.fullmatch(task_id):
        raise ValueError("task_id 非法，或指定的任务目录不存在")
    work_dir = (repo_root() / "backend" / "project" / "work_dir" / task_id).resolve()
    if not work_dir.exists():
        raise FileNotFoundError(f"任务目录不存在: {work_dir}")
    return work_dir


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def update_export_status(work_dir: Path, pdf_result: dict[str, Any]) -> None:
    status_path = work_dir / "export_status.json"
    status = read_json(status_path)
    status["pdf"] = pdf_result
    write_json(status_path, status)


def update_candidate_manifest(work_dir: Path, pdf_name: str) -> None:
    manifest_path = work_dir / "candidate_manifest.json"
    if not manifest_path.exists():
        return
    manifest = read_json(manifest_path)
    files = manifest.setdefault("files", {})
    if isinstance(files, dict):
        files["res_pdf"] = pdf_name
    write_json(manifest_path, manifest)


def build_command(args: argparse.Namespace, work_dir: Path) -> list[str]:
    pandoc = args.pandoc or shutil.which("pandoc")
    xelatex = args.xelatex or shutil.which("xelatex")
    if pandoc is None:
        raise FileNotFoundError("本机 PATH 中未找到 pandoc")
    if xelatex is None:
        raise FileNotFoundError("本机 PATH 中未找到 xelatex")

    command = [
        pandoc,
        str(work_dir / args.markdown),
        "-o",
        str(work_dir / args.output),
        f"--pdf-engine={xelatex}",
        "--from",
        "markdown+tex_math_dollars+pipe_tables+raw_tex",
        "--standalone",
        "-V",
        "documentclass=ctexart",
        "-V",
        "classoption=scheme=chinese",
        "-V",
        "papersize=a4",
        "-V",
        f"CJKmainfont={args.cjk_font}",
        "-V",
        f"CJKsansfont={args.cjk_sans_font}",
        "-V",
        f"mainfont={args.main_font}",
        "-V",
        "pagestyle=plain",
        "-V",
        PDF_HEADING_STYLE,
        "-V",
        f"geometry:left={args.left_margin},right={args.right_margin},top={args.top_margin},bottom={args.bottom_margin}",
        "-V",
        "fontsize=12pt",
        "-V",
        "colorlinks=true",
        "-V",
        "linkcolor=blue",
        "-V",
        "urlcolor=blue",
        "--resource-path",
        str(work_dir),
    ]
    if args.toc:
        command.extend(["--toc", "--toc-depth", str(args.toc_depth)])
    return command


def export_pdf(args: argparse.Namespace) -> int:
    work_dir = resolve_work_dir(args.task)
    md_path = work_dir / args.markdown
    pdf_path = work_dir / args.output
    result: dict[str, Any] = {
        "enabled": True,
        "success": False,
        "pdf_path": None,
        "reason": "",
        "command": [],
        "stderr": "",
        "runner": "local_host",
    }

    if not md_path.exists():
        result["enabled"] = False
        result["reason"] = f"Markdown 文件不存在: {md_path}"
        update_export_status(work_dir, result)
        print(result["reason"], file=sys.stderr)
        return 1

    try:
        command = build_command(args, work_dir)
    except FileNotFoundError as exc:
        result["enabled"] = False
        result["reason"] = str(exc)
        update_export_status(work_dir, result)
        print(result["reason"], file=sys.stderr)
        return 1

    result["command"] = command
    try:
        proc = subprocess.run(
            command,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        result["reason"] = f"PDF 生成超时（{args.timeout}秒）"
        update_export_status(work_dir, result)
        print(result["reason"], file=sys.stderr)
        return 1

    result["stderr"] = proc.stderr
    if proc.returncode == 0 and pdf_path.exists():
        result["success"] = True
        result["pdf_path"] = str(pdf_path)
        result["reason"] = "PDF 生成成功"
        update_export_status(work_dir, result)
        update_candidate_manifest(work_dir, args.output)
        print(f"PDF 生成成功: {pdf_path}")
        return 0

    result["reason"] = f"pandoc 返回码非 0: {proc.returncode}"
    update_export_status(work_dir, result)
    print(result["reason"], file=sys.stderr)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="使用本机 pandoc/xelatex 为任务目录生成符合参考格式的 res.pdf。"
    )
    parser.add_argument("task", help="任务 ID，或任务工作目录路径")
    parser.add_argument("--markdown", default="res.md", help="输入 Markdown 文件名")
    parser.add_argument("--output", default="res.pdf", help="输出 PDF 文件名")
    parser.add_argument("--pandoc", default=None, help="pandoc 可执行文件路径")
    parser.add_argument("--xelatex", default=None, help="xelatex 可执行文件路径")
    parser.add_argument("--cjk-font", default="SimSun", help="中文正文字体名")
    parser.add_argument("--cjk-sans-font", default="SimHei", help="中文标题字体名")
    parser.add_argument("--main-font", default="Times New Roman", help="西文字体名")
    parser.add_argument("--left-margin", default="3.17cm", help="左边距")
    parser.add_argument("--right-margin", default="3.17cm", help="右边距")
    parser.add_argument("--top-margin", default="2.6cm", help="上边距")
    parser.add_argument("--bottom-margin", default="2.6cm", help="下边距")
    parser.add_argument("--toc-depth", type=int, default=3, help="PDF 目录层级")
    parser.add_argument("--toc", action="store_true", help="生成 PDF 目录（默认不生成，以匹配参考格式）")
    parser.add_argument("--no-toc", action="store_true", help="兼容旧参数；当前默认不生成目录")
    parser.add_argument("--timeout", type=int, default=420, help="转换超时秒数")
    return parser.parse_args()


def main() -> int:
    try:
        return export_pdf(parse_args())
    except Exception as exc:
        print(f"PDF 导出失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
