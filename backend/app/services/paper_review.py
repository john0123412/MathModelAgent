"""Paper review packet and six-dimensional review (roadmap batch D).

Outer Agent does the actual review; backend assembles evidence, validates
submission, persists structured result, and enforces version binding.

- Review packet: problem contract, model plan, frozen facts, key results, figure list, citation records, paper with page anchors.
- Review result: paper_review.json/md with six dimensions, findings, severity, locations, reviewer identity, manuscript_sha256, frozen_result_id, artifact_set_id.
- Invalidation: old review is stale when manuscript/frozen/artifact changes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.utils.common_utils import get_work_dir
from app.utils.log_util import logger

REVIEW_JSON = "paper_review.json"
REVIEW_MD = "paper_review.md"
PACKET_JSON = "review_packet.json"

SIX_DIMENSIONS = [
    ("abstract", "摘要"),
    ("assumptions", "假设与符号"),
    ("modeling", "模型建立与求解"),
    ("results", "结果与可信度"),
    ("figures", "图表"),
    ("format", "格式与规范"),
]


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _current_versions(work_dir: Path) -> dict[str, str | None]:
    try:
        manifest = json.loads((work_dir / "candidate_manifest.json").read_text(encoding="utf-8"))
        artifact_set_id = manifest.get("artifact_set_id")
    except (OSError, ValueError, AttributeError):
        artifact_set_id = None
    return {
        "manuscript_sha256": _file_sha256(work_dir / "res.md"),
        "frozen_result_id": _file_sha256(work_dir / "frozen_results.json"),
        "artifact_set_id": artifact_set_id,
    }


def assemble_review_packet(task_id: str) -> dict[str, Any]:
    """Collect evidence for outer Agent review. Does not call LLM."""
    work_dir = Path(get_work_dir(task_id))
    packet: dict[str, Any] = {
        "task_id": task_id,
        "assembled_at": datetime.now().isoformat(),
        "problem": {},
        "model_plan": {},
        "frozen_facts": {},
        "key_results": {},
        "figures": [],
        "citations": {},
        "paper": {},
    }

    # Problem contract
    for cand in ["problem_contract.json", "task_request.json", "questions.txt"]:
        p = work_dir / cand
        if p.is_file():
            try:
                if p.suffix == ".json":
                    packet["problem"][cand] = json.loads(p.read_text(encoding="utf-8"))
                else:
                    packet["problem"][cand] = p.read_text(encoding="utf-8")[:4000]
            except Exception as exc:  # noqa: BLE001
                packet["problem"][cand] = {"error": str(exc)}

    # Model plan
    for cand in ["modeler_plan.json", "modeling_decision.json", "checkpoint.json"]:
        p = work_dir / cand
        if p.is_file():
            try:
                packet["model_plan"][cand] = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass

    # Frozen facts
    for cand in ["frozen_results.json", "execution_validation.json", "execution_validation_report.json"]:
        p = work_dir / cand
        if p.is_file():
            try:
                packet["frozen_facts"][cand] = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass

    # Key results table (from frozen)
    try:
        frozen = packet["frozen_facts"].get("frozen_results.json", {})
        if isinstance(frozen, dict):
            packet["key_results"] = {k: v for k, v in frozen.items() if k in {"results", "metrics", "sources"}}
    except Exception:
        pass

    # Figures
    try:
        for ext in ("*.png", "*.jpg", "*.pdf"):
            for fp in work_dir.glob(f"**/{ext}"):
                if ".work" in str(fp) or "__pycache__" in str(fp):
                    continue
                rel = str(fp.relative_to(work_dir))
                packet["figures"].append({"path": rel, "size": fp.stat().st_size})
        # Paper assets manifest
        pam = work_dir / "paper_assets_manifest.json"
        if pam.is_file():
            try:
                packet["figures"].append({"paper_assets_manifest": json.loads(pam.read_text(encoding="utf-8"))})
            except Exception:
                pass
    except Exception:
        pass

    # Citations
    for cand in ["paper_search_cache.json", "citations.json", "references.json"]:
        p = work_dir / cand
        if p.is_file():
            try:
                packet["citations"][cand] = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    # Also from paper_postprocessor's bib
    bib = work_dir / "res.bib"
    if bib.is_file():
        packet["citations"]["res.bib"] = {"exists": True, "size": bib.stat().st_size}

    # Paper with page anchors
    for cand in ["res.md", "res.pdf", "res.docx"]:
        p = work_dir / cand
        if p.is_file():
            packet["paper"][cand] = {"sha256": _file_sha256(p), "size": p.stat().st_size}
            if cand == "res.md":
                try:
                    text = p.read_text(encoding="utf-8")
                    packet["paper"]["res.md_preview"] = text[:2000]
                except Exception:
                    pass
    # Return every binding that the reviewer must echo at submission time.
    packet.update(_current_versions(work_dir))

    # Persist packet for audit
    try:
        (work_dir / PACKET_JSON).write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"写入 review_packet 失败: {type(exc).__name__}")

    return packet


def _is_stale(task_id: str, review: dict[str, Any]) -> bool:
    work_dir = Path(get_work_dir(task_id))
    return any(
        not current or review.get(key) != current
        for key, current in _current_versions(work_dir).items()
    )


def save_review(task_id: str, review: dict[str, Any]) -> Path:
    """Validate and persist reviewer submission (outer Agent)."""
    work_dir = Path(get_work_dir(task_id))

    # Required fields
    required = ["reviewer_type", "manuscript_sha256", "frozen_result_id", "artifact_set_id", "findings"]
    for field in required:
        if field not in review:
            raise ValueError(f"评审缺少必需字段: {field}")

    # Six dimensions: each 0-10 or not_assessed
    scores = review.get("scores", {})
    if not isinstance(scores, dict):
        raise ValueError("scores 必须为对象")
    for dim, _ in SIX_DIMENSIONS:
        val = scores.get(dim, "not_assessed")
        if val != "not_assessed" and not (
            isinstance(val, (int, float)) and not isinstance(val, bool) and 0 <= val <= 10
        ):
            raise ValueError(f"维度 {dim} 分数必须为 0-10 或 not_assessed")

    # Findings must have location and suggested scope
    findings = review.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("findings 必须为数组")
    for idx, f in enumerate(findings):
        if not isinstance(f, dict):
            raise ValueError(f"findings[{idx}] 必须为对象")
        for req in ["category", "severity", "location", "evidence", "suggested_scope"]:
            if req not in f:
                raise ValueError(f"findings[{idx}] 缺少 {req}")
        if f["suggested_scope"] not in {"model", "numeric", "manuscript", "layout", "citation"}:
            raise ValueError(f"findings[{idx}].suggested_scope 必须为 model/numeric/manuscript/layout/citation")

    # Never fill absent bindings with the current version: that would turn an
    # old review into an apparent review of files the reviewer has not seen.
    for key, current in _current_versions(work_dir).items():
        if not current or not review.get(key) or review[key] != current:
            raise ValueError(f"评审版本不匹配或产物缺失: {key}；请重新获取 review/packet")
    if review.get("task_id", task_id) != task_id:
        raise ValueError("评审 task_id 与目标任务不匹配")
    review.setdefault("task_id", task_id)
    review.setdefault("created_at", datetime.now().isoformat())

    # Write JSON
    out_json = work_dir / REVIEW_JSON
    out_json.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    # Write MD summary
    try:
        md_lines = [f"# 论文六维评审 — {task_id}", "", f"生成时间：{review.get('created_at')}", ""]
        md_lines.append("## 评分")
        md_lines.append("| 维度 | 分数 |")
        md_lines.append("| --- | --- |")
        for dim, label in SIX_DIMENSIONS:
            md_lines.append(f"| {label} | {scores.get(dim, 'not_assessed')} |")
        md_lines.append("")
        md_lines.append("## 发现（按严重性）")
        for f in findings:
            md_lines.append(f"- **{f.get('category')}** [{f.get('severity')}] {f.get('location')}: {f.get('evidence')[:120]} → {f.get('suggested_scope')}")
        (work_dir / REVIEW_MD).write_text("\n".join(md_lines), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"写入 review MD 失败: {type(exc).__name__}")

    return out_json


def load_review(task_id: str) -> dict[str, Any] | None:
    work_dir = Path(get_work_dir(task_id))
    p = work_dir / REVIEW_JSON
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        data["_stale"] = _is_stale(task_id, data)
        return data
    except Exception:
        return None
