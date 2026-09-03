"""Container doctor (roadmap batch E).

Separates host connectivity (task_client) from container capability.
Backend reports actual interpreter, libs, Pandoc/XeLaTeX/fonts, task dir, and provider config completeness.
No live provider probing on every call; connectivity is explicit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.config.setting import settings


def _check(cmd: list[str], timeout: float = 3.0) -> dict[str, Any]:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=timeout).decode(errors="ignore").strip()  # noqa: S603
        return {"ok": True, "output": out[:500]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:500]}"}


def container_doctor() -> dict[str, Any]:
    checks: dict[str, Any] = {}

    # Interpreter
    checks["python"] = _check(["python", "--version"])
    checks["uv"] = _check(["uv", "--version"])

    # Numeric libs
    for lib in ["numpy", "pandas", "scipy", "matplotlib", "seaborn"]:
        try:
            __import__(lib)
            checks[lib] = {"ok": True}
        except ImportError as exc:  # noqa: BLE001
            checks[lib] = {"ok": False, "error": str(exc)[:200]}

    # Pandoc / XeLaTeX
    checks["pandoc"] = _check(["pandoc", "--version"])
    checks["xelatex"] = _check(["xelatex", "--version"])
    checks["latexmk"] = _check(["latexmk", "--version"])

    # Fonts: check SimSun fallback
    try:
        import matplotlib.font_manager as fm  # type: ignore[import-unresolved]

        fonts = [f.name for f in fm.fontManager.ttflist]
        has_simsun = any("SimSun" in n or "Songti" in n or "Noto Serif CJK" in n for n in fonts)
        checks["fonts"] = {"ok": True, "has_simsun_or_fallback": has_simsun, "count": len(fonts)}
    except Exception as exc:  # noqa: BLE001
        checks["fonts"] = {"ok": False, "error": str(exc)[:300]}

    # Task dir writable
    try:
        work_root = Path("project/work_dir")
        work_root.mkdir(parents=True, exist_ok=True)
        test_file = work_root / ".doctor_probe"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        checks["work_dir_writable"] = {"ok": True, "path": str(work_root.resolve())}
    except Exception as exc:  # noqa: BLE001
        checks["work_dir_writable"] = {"ok": False, "error": str(exc)[:300]}

    # Figure and layout checks
    checks["drawio_cli"] = _check(["drawio", "--version"])
    if not checks["drawio_cli"]["ok"]:
        checks["drawio_cli"] = {"ok": False, "note": "drawio CLI 未安装，.drawio 源文件不等于已导出图"}

    # Provider config completeness (no live probing)
    provider_checks: dict[str, Any] = {}
    for name in ["COORDINATOR", "MODELER", "CODER", "WRITER"]:
        key = getattr(settings, f"{name}_API_KEY", None)
        base = getattr(settings, f"{name}_BASE_URL", None)
        model = getattr(settings, f"{name}_MODEL", None)
        provider_checks[name.lower()] = {
            "has_key": bool(key),
            "has_base": bool(base),
            "has_model": bool(model),
            "complete": bool(key and base and model),
        }
    checks["providers"] = provider_checks

    # Overall
    essential_ok = all(
        checks[k].get("ok")
        for k in ["python", "pandoc", "xelatex", "work_dir_writable"]
        if k in checks
    )
    checks["overall"] = {"ok": essential_ok, "message": "容器核心能力就绪" if essential_ok else "容器有缺失能力"}

    return checks


# Template capability table (roadmap E)
TEMPLATE_ALIASES: dict[str, str] = {
    "huawei": "huaweibei",
    "huazhong": "huazhongbei",
    "wuyi": "wuyibei",
    "huawei-latex": "huaweibei-latex",
    "huazhong-latex": "huazhongbei-latex",
    "wuyi-latex": "wuyibei-latex",
}

BACKEND_PROFILES = {"default", "cumcm2025", "cumcm2026", "huashubei"}


def template_capabilities() -> dict[str, Any]:
    """Return backend export profiles vs skill template count."""
    from pathlib import Path

    # Skill templates (if skills/ exists)
    skill_templates = []
    skill_root = Path("skills/5writing/templates/zh")
    if skill_root.is_dir():
        skill_templates = sorted(p.name for p in skill_root.iterdir() if p.is_dir())
    return {
        "backend_profiles": sorted(BACKEND_PROFILES),
        "skill_templates": skill_templates,
        "aliases": TEMPLATE_ALIASES,
        "note": "桌面 14 目录 ≠ 14 赛事；本地 skills 多模板 ≠ 后端已支持对应 export profile。当前后端仅 4 个 profile。",
    }
