"""Smoke test for PDF export in Docker or a prepared local backend env.

Purpose:
    Verify that default/cumcm2025/cumcm2026 direct PDF export and LaTeX sidecar export
    can generate non-empty PDF files.

Run from backend/:
    uv run python scripts/smoke_pdf_export.py

Requires:
    pandoc and xelatex on PATH.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.enums import ExportProfile  # noqa: E402
from app.tools.pdf_exporter import export_markdown_to_pdf  # noqa: E402
from app.tools.tex_project_exporter import export_markdown_to_latex_project  # noqa: E402


SAMPLE_MARKDOWN = """# PDF Smoke Test

这是一个最小 PDF 导出测试。

目标函数：

$$
\\max z = 40x_A + 30x_B
$$

| 资源 | A | B | 上限 |
| --- | ---: | ---: | ---: |
| 机器时间 | 2 | 1 | 100 |
| 人工时间 | 1 | 2 | 80 |
"""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_nonempty_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _print_failure(label: str, result: dict) -> None:
    print(f"[FAIL] {label}: {result.get('reason') or 'unknown reason'}", file=sys.stderr)
    stderr = result.get("stderr")
    if stderr:
        print(stderr, file=sys.stderr)
    compile_reason = result.get("compile_reason")
    if compile_reason:
        print(f"[compile_reason] {compile_reason}", file=sys.stderr)


def _compile_sidecar_with_xelatex(latex_dir: Path) -> tuple[bool, str]:
    if shutil.which("xelatex") is None:
        return False, "xelatex is not available on PATH"

    last_output = ""
    for _ in range(2):
        proc = subprocess.run(
            ["xelatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
            cwd=latex_dir,
            capture_output=True,
            text=True,
            timeout=180,
        )
        last_output = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            return False, last_output
    return True, last_output


def _run_profile(profile: ExportProfile, root: Path) -> bool:
    work_dir = root / profile.value
    work_dir.mkdir(parents=True, exist_ok=True)
    md_path = work_dir / "res.md"
    pdf_path = work_dir / "res.pdf"
    md_path.write_text(SAMPLE_MARKDOWN, encoding="utf-8")

    direct_result = export_markdown_to_pdf(
        str(md_path),
        str(pdf_path),
        str(work_dir),
        export_profile=profile,
    )
    if not direct_result.get("success") or not _is_nonempty_file(pdf_path):
        _print_failure(f"{profile.value} direct PDF", direct_result)
        return False
    print(f"[OK] {profile.value} direct PDF -> {pdf_path} ({pdf_path.stat().st_size} bytes)")

    sidecar_result = export_markdown_to_latex_project(
        str(md_path),
        str(work_dir),
        export_profile=profile,
    )
    sidecar_pdf = work_dir / "latex_project" / "main.pdf"
    if not sidecar_result.get("success"):
        _print_failure(f"{profile.value} LaTeX sidecar PDF", sidecar_result)
        return False
    if not _is_nonempty_file(sidecar_pdf):
        compile_ok, compile_output = _compile_sidecar_with_xelatex(sidecar_pdf.parent)
        if not compile_ok or not _is_nonempty_file(sidecar_pdf):
            _print_failure(f"{profile.value} LaTeX sidecar PDF", sidecar_result)
            if compile_output:
                print(compile_output, file=sys.stderr)
            return False
    print(
        f"[OK] {profile.value} LaTeX sidecar PDF -> "
        f"{sidecar_pdf} ({sidecar_pdf.stat().st_size} bytes)"
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test direct PDF and LaTeX sidecar PDF export.")
    parser.parse_args()

    if shutil.which("pandoc") is None:
        print("[FAIL] pandoc is not available on PATH", file=sys.stderr)
        return 1
    if shutil.which("xelatex") is None:
        print("[FAIL] xelatex is not available on PATH", file=sys.stderr)
        return 1

    tmp_root = _repo_root() / ".agent-work" / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="pdf-smoke-", dir=tmp_root) as temp_dir:
        run_root = Path(temp_dir)
        ok = True
        for profile in (
            ExportProfile.DEFAULT,
            ExportProfile.CUMCM2025,
            ExportProfile.CUMCM2026,
        ):
            ok = _run_profile(profile, run_root) and ok
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
