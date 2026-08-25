#!/usr/bin/env python3
"""doctor 结构化环境检查脚本（纯标准库，只检查不安装）。

对数学建模工作流依赖做分级体检，输出机器可读的 JSON 或人类可读文本：
  - required    缺失即核心工作流不可用
  - recommended 缺失时部分场景受限（如中文 LaTeX）
  - optional    仅影响导出质量或体验

安装动作永远不由本脚本执行；安装命令（含中国大陆镜像方案）仅作为建议字段输出，
是否执行由用户在 doctor SKILL.md 的确认门禁中决定。

用法：
  python check_env.py                 # 文本报告
  python check_env.py --format json   # JSON 报告
退出码：0 必须项全部就绪；1 存在缺失必须项；2 参数错误。
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform as py_platform
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# 中国大陆镜像与加速方案（按平台给出可执行命令）
PYPI_CHINA = "https://pypi.tuna.tsinghua.edu.cn/simple"
TEXLIVE_TUNA = "https://mirrors.tuna.tsinghua.edu.cn/CTAN/systems/texlive/tlnet"


class Check:
    """单条检查项定义。"""

    def __init__(
        self,
        id_: str,
        name: str,
        level: str,
        probe,
        install_default: str,
        install_china: str,
        detail_ok: str = "",
    ) -> None:
        self.id = id_
        self.name = name
        self.level = level  # required | recommended | optional
        self.probe = probe  # () -> tuple[bool, str]
        self.install_default = install_default
        self.install_china = install_china
        self.detail_ok = detail_ok


def _cmd_ok(cmd: str) -> bool:
    try:
        return subprocess.run(
            ["bash", "-lc", f"command -v {cmd} >/dev/null 2>&1"], check=False
        ).returncode == 0 or _shutil_which(cmd)
    except OSError:
        return _shutil_which(cmd)


def _shutil_which(cmd: str) -> bool:
    import shutil

    return shutil.which(cmd) is not None


def _probe_cmd(*cmds: str):
    def probe() -> tuple[bool, str]:
        for c in cmds:
            if _shutil_which(c):
                return True, f"found: {c}"
        return False, f"none of {', '.join(cmds)} found"

    return probe


def _probe_pip(pkg: str, import_name: str | None = None):
    def probe() -> tuple[bool, str]:
        try:
            ver = importlib.metadata.version(pkg)
            return True, f"{pkg}=={ver}"
        except importlib.metadata.PackageNotFoundError:
            # 版本元数据缺失但模块可导入也算可用（罕见发行版）
            mod = import_name or pkg.replace("-", "_")
            try:
                __import__(mod)
                return True, f"{pkg} (module import ok, metadata missing)"
            except ImportError:
                return False, f"{pkg} not installed"
        return False, ""

    return probe


def _probe_fixed_venv() -> tuple[bool, str]:
    """AGENTS.md 固定虚拟环境规则：backend/.venv 必须存在且可运行。"""
    candidates = [
        REPO_ROOT / "backend" / ".venv" / "Scripts" / "python.exe",
        REPO_ROOT / "backend" / ".venv" / "bin" / "python",
    ]
    found = [c for c in candidates if c.is_file()]
    if not found:
        return (
            False,
            f"backend/.venv 不存在（查找于 {candidates[0].parent.parent}）；"
            "后端验证必须使用该虚拟环境，禁止系统全局 Python",
        )
    try:
        out = subprocess.run(
            [str(found[0]), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        version_line = (out.stdout or out.stderr).strip()
        match = re.search(r"3\.(\d+)\.", version_line)
        if not match or int(match.group(1)) < 10:
            return False, f"backend/.venv Python 版本过低: {version_line}（要求 3.10+，仓库约定 3.12+）"
        return True, f"backend/.venv 就绪 ({version_line})"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"backend/.venv 解释器无法执行: {exc}"


def build_checks() -> list[Check]:
    """构造全部检查项（含平台相关的安装建议）。"""
    system = py_platform.system()

    typst_install = {
        "Windows": 'winget install Typst.Typst（备用 scoop install typst）',
        "Darwin": "brew install typst",
        "Linux": "snap install typst 或从 GitHub Releases 下载二进制",
    }.get(system, "cargo install --locked typst-cli")
    tex_install = {
        "Windows": "winget install MiKTeX.MiKTeX（精简方案见 SKILL.md）",
        "Darwin": "brew install --cask mactex",
        "Linux": "sudo apt install texlive-full（精简: texlive-xetex + texlive-lang-chinese）",
    }.get(system, "安装 TeX Live")
    drawio_install = {
        "Windows": "winget install JGraph.Draw",
        "Darwin": "brew install --cask drawio",
        "Linux": "从 github.com/jgraph/drawio-desktop/releases 下载 AppImage/deb",
    }.get(system, "下载 drawio-desktop")
    poppler_install = {
        "Windows": "winget install oschwartz10612.poppler",
        "Darwin": "brew install poppler",
        "Linux": "sudo apt install poppler-utils",
    }.get(system, "安装 poppler")

    def pip_cmds(pkgs: list[str]) -> tuple[str, str]:
        joined = " ".join(pkgs)
        return (
            f"pip install {joined}",
            f"pip install -i {PYPI_CHINA} {joined}",
        )

    def pkg_check(pid: str, name: str, level: str, pkgs: list[str], extra_note: str = "") -> Check:
        dflt, china = pip_cmds(pkgs)
        probes = [_probe_pip(p) for p in pkgs]

        def combined() -> tuple[bool, str]:
            oks, misses = [], []
            for p, pr in zip(pkgs, probes):
                ok, detail = pr()
                (oks if ok else misses).append(f"{p}: {detail}" if ok else p)
            return (not misses), "; ".join(oks + misses)

        return Check(pid, name, level, combined, dflt, china + extra_note)

    compiler_probe_cmds = ("typst", "xelatex")

    def probe_compiler() -> tuple[bool, str]:
        for c in compiler_probe_cmds:
            if _shutil_which(c):
                return True, f"found: {c}"
        return False, "typst 与 xelatex 均未找到（论文编译不可用）"

    checks: list[Check] = [
        Check(
            "paper-compiler",
            "论文编译器（typst 或 xelatex 至少其一）",
            "required",
            probe_compiler,
            f"{typst_install}；或 {tex_install}",
            f"TeX 系统可用清华 TUNA 镜像安装/换源：{TEXLIVE_TUNA}；typst 单二进制从 GitHub Releases 下载",
        ),
        Check("python-runtime", "Python 3.10+", "required", lambda: _probe_python(), "winget install Python.Python.3", "官网或华为镜像下载 Windows 安装包"),
        Check("venv-fixed", "固定虚拟环境 backend/.venv（AGENTS.md 规则）", "required", _probe_fixed_venv, "cd backend && uv sync", "uv 可通过 pip install uv -i " + PYPI_CHINA + " 安装"),
        pkg_check("pkg-numpy", "numpy 数值计算", "required", ["numpy"]),
        pkg_check("pkg-pandas", "pandas 数据处理", "required", ["pandas"]),
        pkg_check("pkg-matplotlib", "matplotlib 图表", "required", ["matplotlib"]),
        pkg_check("pkg-scipy", "scipy 科学计算/优化求解", "recommended", ["scipy"]),
        pkg_check("pkg-sklearn", "scikit-learn 机器学习建模", "recommended", ["scikit-learn"], "；导入名为 sklearn"),
        pkg_check("pkg-openpyxl", "openpyxl 读写 Excel 附件", "recommended", ["openpyxl"]),
        Check("xelatex-cjk", "xelatex 中文 LaTeX 编译", "recommended", _probe_cmd("xelatex"), tex_install, f"TUNA CTAN 镜像：{TEXLIVE_TUNA}"),
        Check("drawio", "drawio 流程图 PDF 导出", "optional", _probe_cmd("drawio", "draw.io"), drawio_install, "GitHub Releases 可经镜像加速"),
        Check("pdftoppm", "pdftoppm PDF 转 PNG（视觉检查首选）", "optional", _probe_cmd("pdftoppm"), poppler_install, "scoop install poppler（bucket: extras）"),
        Check("mutool", "mutool PDF 转 PNG 备用", "optional", _probe_cmd("mutool"), "brew install mupdf / apt install mupdf-tools", "scoop install mupdf"),
        Check("magick", "magick PDF 转 PNG 备用", "optional", _probe_cmd("magick"), "winget install ImageMagick.ImageMagick", "国内可通过 scoop/choco 安装"),
        Check("typstyle", "typstyle Typst 格式化（typst-author 后置检查用）", "optional", _probe_cmd("typstyle"), "cargo install typstyle 或 npm i -g @myriad-dreamin/typst-ts-webcontrib", "GitHub Releases 下载二进制"),
    ]
    return checks


def _probe_python() -> tuple[bool, str]:
    version = sys.version_info
    ok = version >= (3, 10)
    return ok, f"python {'.'.join(map(str, version[:3]))}" + ("" if ok else "（低于 3.10）")


def detect_platform() -> dict:
    """识别操作系统与本机可用的包管理器。"""
    system = {"Windows": "windows", "Darwin": "macos"}.get(py_platform.system(), "linux")
    managers = []
    import shutil

    for pm in ("winget", "scoop", "choco", "brew", "apt", "dnf", "pacman"):
        if shutil.which(pm):
            managers.append(pm)
    return {"os": system, "package_managers": managers}


def run_checks(checks: list[Check]) -> list[dict]:
    results = []
    for chk in checks:
        try:
            ok, detail = chk.probe()
        except Exception as exc:  # noqa: BLE001 —— 探针异常视为未就绪而非崩溃
            ok, detail = False, f"probe error: {exc}"
        results.append(
            {
                "id": chk.id,
                "name": chk.name,
                "level": chk.level,
                "ok": ok,
                "detail": detail,
                "install": {
                    "default": chk.install_default,
                    "china_mirror": chk.install_china,
                },
            }
        )
    return results


def summarize(results: list[dict]) -> dict:
    summary: dict[str, dict[str, int]] = {}
    for level in ("required", "recommended", "optional"):
        subset = [r for r in results if r["level"] == level]
        summary[level] = {
            "total": len(subset),
            "ok": sum(1 for r in subset if r["ok"]),
        }
    return summary


def render_text(report: dict) -> str:
    lines = [
        f"Doctor 环境检查 — 平台: {report['platform']['os']} "
        f"(包管理器: {', '.join(report['platform']['package_managers']) or '未检测到'})",
        "",
    ]
    marks = {True: "OK ", False: "MISS"}
    order = {"required": 0, "recommended": 1, "optional": 2}
    for item in sorted(report["checks"], key=lambda x: (order[x["level"]], x["id"])):
        lines.append(f"[{marks[item['ok']].strip():>4}] ({item['level']:<11}) {item['name']}")
        lines.append(f"        {item['detail']}")
        if not item["ok"]:
            lines.append(f"        安装(默认): {item['install']['default']}")
            lines.append(f"        安装(国内): {item['install']['china_mirror']}")
    s = report["summary"]
    lines += [
        "",
        f"汇总: required {s['required']['ok']}/{s['required']['total']} | "
        f"recommended {s['recommended']['ok']}/{s['recommended']['total']} | "
        f"optional {s['optional']['ok']}/{s['optional']['total']}",
        "安装前必须经用户确认（SKILL.md 门禁）；本脚本自身从不执行安装。",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """执行检查并输出报告。

    Args:
        argv: 命令行参数（默认 sys.argv）。

    Returns:
        0 必须项全部就绪；1 有缺失必须项；2 参数错误。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)

    report = {
        "platform": detect_platform(),
        "repo_root": str(REPO_ROOT),
        "checks": run_checks(build_checks()),
    }
    report["summary"] = summarize(report["checks"])

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))

    return 0 if report["summary"]["required"]["ok"] == report["summary"]["required"]["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
