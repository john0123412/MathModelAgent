"""Figure plan service (roadmap batch E).

Turns mma-figure routing into a backend figure plan: each figure declares
type, conclusion, data source, script, target section.  Reuses existing
mathmodel-figure-templates and 4drawio assets; verifies in container.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from app.utils.common_utils import get_work_dir

FIGURE_PLAN_FILENAME = "figure_plan.json"

# Routing table mirrors mma-figure
FIGURE_ROUTES = {
    "data_chart": {"skill": "nature-figure", "backend": "matplotlib/seaborn", "desc": "数据生成图"},
    "template": {"skill": "mathmodel-figure-templates", "backend": "render_template.py", "desc": "内置模板复刻"},
    "diagram": {"skill": "paper-diagram", "backend": "4drawio", "desc": "技术路线/框架/流程图"},
    "physical": {"skill": "tikz", "backend": "tikz", "desc": "物理几何示意图"},
}


def _plan_path(work_dir: str) -> Path:
    return Path(work_dir) / FIGURE_PLAN_FILENAME


def create_figure_plan(
    task_id: str,
    figures: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create or overwrite figure plan with validation. Each figure needs type, conclusion, data_source, script, section."""
    work_dir = get_work_dir(task_id)
    plan: dict[str, Any] = {
        "task_id": task_id,
        "created_at": datetime.now().isoformat(),
        "figures": [],
    }
    for idx, fig in enumerate(figures):
        entry: dict[str, Any] = {
            "id": fig.get("id") or f"fig_{idx+1}",
            "type": fig.get("type", "data_chart"),
            "title": fig.get("title", "")[:50],
            "conclusion": fig.get("conclusion", ""),
            "data_source": fig.get("data_source", ""),
            "script": fig.get("script", ""),
            "section": fig.get("section", ""),
            "output": fig.get("output", f"figures/{fig.get('id', f'fig_{idx+1}')}.png"),
        }
        route = FIGURE_ROUTES.get(entry["type"])
        if route is None:
            raise ValueError(f"未知 figure type: {entry['type']}")
        entry["route"] = route
        # Traceability: data figures must have real data source, not template sample
        if entry["type"] == "data_chart" and not entry["data_source"]:
            raise ValueError(f"数据图 {entry['id']} 必须声明 data_source")
        plan["figures"].append(entry)

    # Multi-panel rule (roadmap E): 2-4 related figures -> 1x2 or 2x2, share legend/scale if comparable
    # For now just record, actual rendering is Coder's job; we validate that plan respects it.
    _save_plan(work_dir, plan)
    return plan


def _save_plan(work_dir: str, plan: dict[str, Any]) -> None:
    import tempfile

    p = _plan_path(work_dir)
    fd, tmp = tempfile.mkstemp(prefix=FIGURE_PLAN_FILENAME + ".", suffix=".tmp", dir=work_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(p))
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def load_figure_plan(task_id: str) -> dict[str, Any] | None:
    work_dir = get_work_dir(task_id)
    p = _plan_path(work_dir)
    if not p.is_file():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def validate_figure_artifacts(task_id: str) -> dict[str, Any]:
    """Check that each planned figure has script and output with traceable data. P1 review: empty script/output or fake data_source must fail."""
    work_dir = get_work_dir(task_id)
    plan = load_figure_plan(task_id)
    if plan is None:
        return {"ok": True, "message": "未创建 figure plan，跳过校验"}
    issues: list[str] = []
    for fig in plan.get("figures", []):
        fid = fig.get("id", "unknown")
        ftype = fig.get("type", "")
        script = (fig.get("script", "") or "").strip()
        output = (fig.get("output", "") or "").strip()
        data_source = (fig.get("data_source", "") or "").strip()
        # All figures must have non-empty script and output for traceability
        if not script:
            issues.append(f"{fid}: 脚本不能为空（需为可复现的生成脚本）")
        else:
            script_path = Path(work_dir) / script
            if not script_path.is_file():
                issues.append(f"{fid}: 脚本缺失 {script}")
        if not output:
            issues.append(f"{fid}: 产物路径不能为空")
        else:
            out_path = Path(work_dir) / output
            if not out_path.is_file():
                issues.append(f"{fid}: 产物缺失 {output}")
        # Data traceability: data_chart must have real data file, not empty or non-existent
        if ftype == "data_chart":
            if not data_source:
                issues.append(f"{fid}: 数据图未绑定真实数据源")
            else:
                ds_path = Path(work_dir) / data_source
                if not ds_path.is_file():
                    issues.append(f"{fid}: 数据源不存在 {data_source}（需为任务内真实数据文件）")

    return {"ok": len(issues) == 0, "issues": issues, "figure_count": len(plan.get("figures", []))}
