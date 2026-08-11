"""Bounded post-freeze manuscript repair for a failed technical preflight.

This is intentionally not a general document editor.  A candidate contains a
complete replacement for the already-completed Writer sections.  The candidate
is first assembled and preflighted in an isolated copy of the frozen task; only
then are ``res.json``, ``res.md`` and the matching checkpoint writer hand-offs
updated.  A subsequent ordinary ``/resume`` performs export only and never
wakes a provider.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from app.core.checkpoint import CheckpointManager
from app.models.user_output import UserOutput
from app.schemas.A2A import WriterResponse
from app.tools.paper_postprocessor import prepare_paper_markdown
from app.tools.export_template_override import (
    TemplateOverrideError,
    get_editorial_policy_override,
    load_export_template_override,
)
from app.tools.result_integrity import validate_result_freeze
from app.utils.common_utils import ensure_safe_task_id, get_work_dir


_MAX_CANDIDATE_BYTES = 384 * 1024
_MAX_SECTION_CHARS = 64 * 1024
_STAGE_IGNORE = shutil.ignore_patterns(
    ".ipython",
    ".jupyter_runtime",
    ".matplotlib",
    "__pycache__",
    "failed_attempts",
    "latex_project",
    "res.pdf",
    "res.docx",
)


class PaperRepairCandidateError(RuntimeError):
    """The reviewed manuscript candidate cannot be applied safely."""


def _task_editorial_policy(root: Path, export_profile: str) -> str | dict:
    try:
        return get_editorial_policy_override(str(root), export_profile)
    except TemplateOverrideError as exc:
        raise PaperRepairCandidateError(f"任务级模板覆盖无效: {exc}") from exc


def _task_template_override(root: Path, export_profile: str) -> dict[str, Any]:
    try:
        return load_export_template_override(str(root), export_profile)
    except TemplateOverrideError as exc:
        raise PaperRepairCandidateError(f"任务级模板覆盖无效: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_candidate_file(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise PaperRepairCandidateError("论文候选文件路径不能为空")
    raw = Path(value.strip())
    if raw.is_absolute() or ".." in raw.parts:
        raise PaperRepairCandidateError("论文候选文件必须是任务目录内、无 .. 的相对路径")
    path = (root / raw).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise PaperRepairCandidateError("论文候选文件路径越出任务目录") from exc
    current = root.resolve()
    for component in path.relative_to(root.resolve()).parts:
        current /= component
        if current.is_symlink():
            raise PaperRepairCandidateError("论文候选文件路径不允许符号链接")
    if not path.is_file():
        raise PaperRepairCandidateError(f"论文候选文件不存在: {raw}")
    if path.stat().st_size > _MAX_CANDIDATE_BYTES:
        raise PaperRepairCandidateError("论文候选文件超过大小上限")
    return path


def _read_candidate(path: Path, expected_keys: list[str]) -> tuple[dict[str, dict], str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PaperRepairCandidateError("论文候选不是有效 JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"sections", "comment"}:
        raise PaperRepairCandidateError("论文候选只能包含 sections 和 comment")
    if not isinstance(payload["comment"], str) or not payload["comment"].strip():
        raise PaperRepairCandidateError("论文候选必须说明人工技术修复依据")
    sections = payload["sections"]
    if not isinstance(sections, dict) or set(sections) != set(expected_keys):
        raise PaperRepairCandidateError("论文候选必须完整且仅包含当前 Writer 章节")
    normalised: dict[str, dict] = {}
    for key in expected_keys:
        text = sections.get(key)
        if isinstance(text, list) and all(isinstance(line, str) for line in text):
            text = "\n".join(text)
        if not isinstance(text, str) or not text.strip():
            raise PaperRepairCandidateError(f"论文候选章节为空或非文本: {key}")
        if len(text) > _MAX_SECTION_CHARS:
            raise PaperRepairCandidateError(f"论文候选章节超过大小上限: {key}")
        normalised[key] = WriterResponse(
            response_content=text,
            footnotes=[],
        ).model_dump()
    return normalised, payload["comment"].strip()


def _load_failure_report(root: Path) -> dict[str, Any]:
    path = root / "paper_preflight_report.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PaperRepairCandidateError("未找到可审计的论文预检失败报告") from exc
    if not isinstance(payload, dict) or payload.get("status") != "FAIL":
        raise PaperRepairCandidateError("当前任务不存在论文预检硬失败，不能使用论文候选修复")
    return payload


def _load_editorial_quality_failure(root: Path) -> dict[str, Any]:
    """Load a current hard editorial failure without assuming one report schema.

    The stricter policy is deliberately allowed to reuse
    ``paper_preflight_report.json`` while it is being introduced.  Once it
    emits an explicit ``editorial_quality`` check, that check is accepted even
    if other technical checks remain PASS.
    """
    path = root / "paper_preflight_report.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PaperRepairCandidateError("未找到可审计的编辑质量失败报告") from exc
    if not isinstance(payload, dict):
        raise PaperRepairCandidateError("编辑质量报告格式无效")
    checks = payload.get("checks")
    editorial_check = checks.get("editorial_quality") if isinstance(checks, dict) else None
    explicit_failure = isinstance(editorial_check, dict) and (
        editorial_check.get("passed") is False
        or editorial_check.get("status") == "FAIL"
    )
    if payload.get("status") != "FAIL" and not explicit_failure:
        raise PaperRepairCandidateError("当前不存在编辑质量硬失败，不能使用编辑质量候选返修")
    return payload


def _write_atomic(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + ".paper-repair.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _stage_and_preflight(
    root: Path,
    sections: dict[str, dict],
    *,
    ques_count: int,
    export_profile: str,
    editorial_policy: str | dict | None = None,
    template_override_audit: dict[str, Any] | None = None,
) -> tuple[bytes, bytes, dict[str, Any]]:
    """Build a candidate manuscript in a disposable clone of the task root."""
    with tempfile.TemporaryDirectory(prefix="paper-repair-candidate-") as temporary:
        stage = Path(temporary) / "task"
        shutil.copytree(root, stage, ignore=_STAGE_IGNORE)
        output = UserOutput(
            work_dir=str(stage), ques_count=ques_count, export_profile=export_profile
        )
        for key in output.seq:
            output.set_res(key, WriterResponse.model_validate(sections[key]))
        output.save_result()
        report = prepare_paper_markdown(
            str(stage),
            "res.md",
            export_profile=export_profile,
            declared_problem_count=ques_count,
            editorial_policy=editorial_policy,
            template_override_audit=template_override_audit,
        )
        if report.get("status") != "PASS":
            failures = [
                key
                for key, value in (report.get("checks") or {}).items()
                if isinstance(value, dict)
                and value.get("passed") is False
                and value.get("severity") == "fail"
            ]
            detail = ", ".join(failures) or "未知硬门禁"
            raise PaperRepairCandidateError(f"论文候选隔离预检未通过: {detail}")
        return (
            (stage / "res.json").read_bytes(),
            (stage / "res.md").read_bytes(),
            report,
        )


def run_paper_repair_candidate(task_id: str, candidate_path: str) -> dict[str, Any]:
    """Validate and persist one human/Codex paper candidate for export-only resume."""
    try:
        task_id = ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise PaperRepairCandidateError("非法 task_id") from exc
    root = Path(get_work_dir(task_id)).resolve()
    if not root.is_dir():
        raise PaperRepairCandidateError("任务工作目录不存在")
    manager = CheckpointManager(str(root))
    checkpoint = manager.load()
    if checkpoint is None or checkpoint.task_id != task_id:
        raise PaperRepairCandidateError("未找到与 task_id 匹配的检查点")
    if checkpoint.workflow_state != "frozen":
        raise PaperRepairCandidateError("论文候选修复只允许在冻结结果状态执行")
    if checkpoint.paper_repair_attempts:
        raise PaperRepairCandidateError("本任务已使用论文预检回修预算")
    freeze = validate_result_freeze(str(root))
    if not freeze.get("active") or not freeze.get("passed"):
        raise PaperRepairCandidateError("冻结结果未通过完整性核验，不能替换论文正文")
    previous_report = _load_failure_report(root)

    expected = UserOutput(
        work_dir=str(root),
        ques_count=checkpoint.ques_count,
        export_profile=checkpoint.export_profile,
    ).seq
    candidate = _safe_candidate_file(root, candidate_path)
    sections, comment = _read_candidate(candidate, expected)
    completed = set(checkpoint.completed_phases)
    if completed != set(expected):
        raise PaperRepairCandidateError("检查点 Writer 阶段不完整，不能安全替换论文正文")

    original_res_json = (root / "res.json").read_bytes() if (root / "res.json").is_file() else b""
    original_res_md = (root / "res.md").read_bytes() if (root / "res.md").is_file() else b""
    template_override = _task_template_override(root, checkpoint.export_profile)
    staged_json, staged_md, staged_report = _stage_and_preflight(
        root,
        sections,
        ques_count=checkpoint.ques_count,
        export_profile=checkpoint.export_profile,
        editorial_policy=_task_editorial_policy(root, checkpoint.export_profile),
        template_override_audit=template_override["audit"],
    )
    audit = {
        "task_id": task_id,
        "candidate_path": str(candidate.relative_to(root)).replace("\\", "/"),
        "candidate_sha256": _sha256(candidate),
        "previous_preflight_source_sha256": previous_report.get("source_sha256", ""),
        "staged_preflight_source_sha256": staged_report.get("source_sha256", ""),
        "frozen_results_sha256": _sha256(root / "frozen_results.json"),
        "comment": comment[:2000],
        "status": "staged_preflight_passed",
    }
    try:
        _write_atomic(root / "res.json", staged_json)
        _write_atomic(root / "res.md", staged_md)
        manager.apply_paper_repair_candidate(
            sections,
            previous_preflight_report=previous_report,
            candidate_audit=audit,
        )
    except Exception as exc:
        if original_res_json:
            _write_atomic(root / "res.json", original_res_json)
        if original_res_md:
            _write_atomic(root / "res.md", original_res_md)
        if isinstance(exc, PaperRepairCandidateError):
            raise
        raise PaperRepairCandidateError("论文候选落盘失败，已恢复原论文文件") from exc

    manifest_path = root / "paper_repair_candidate_manifest.json"
    _write_atomic(
        manifest_path,
        json.dumps(audit, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    return {
        "status": "paper_candidate_applied",
        "task_id": task_id,
        "preflight_status": staged_report.get("status"),
        "source_sha256": staged_report.get("source_sha256"),
        "manifest": manifest_path.name,
    }


def run_editorial_repair_candidate(task_id: str, candidate_path: str) -> dict[str, Any]:
    """Apply one audited editorial-quality candidate after a completed paper.

    Unlike ``run_paper_repair_candidate``, this route never consumes or
    interprets the ordinary preflight-repair budget.  It is restricted to a
    still-intact frozen result and a newly recorded editorial hard failure.
    """
    try:
        task_id = ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise PaperRepairCandidateError("非法 task_id") from exc
    root = Path(get_work_dir(task_id)).resolve()
    if not root.is_dir():
        raise PaperRepairCandidateError("任务工作目录不存在")
    manager = CheckpointManager(str(root))
    checkpoint = manager.load()
    if checkpoint is None or checkpoint.task_id != task_id:
        raise PaperRepairCandidateError("未找到与 task_id 匹配的检查点")
    if checkpoint.workflow_state not in {"paper_preflight_passed", "completed"}:
        raise PaperRepairCandidateError("编辑质量候选只允许在论文预检通过或已完成状态执行")
    if checkpoint.editorial_repair_attempts:
        raise PaperRepairCandidateError("本任务已使用编辑质量返修预算")
    freeze = validate_result_freeze(str(root))
    if not freeze.get("active") or not freeze.get("passed"):
        raise PaperRepairCandidateError("冻结结果未通过完整性核验，不能替换论文正文")
    editorial_failure = _load_editorial_quality_failure(root)

    expected = UserOutput(
        work_dir=str(root),
        ques_count=checkpoint.ques_count,
        export_profile=checkpoint.export_profile,
    ).seq
    candidate = _safe_candidate_file(root, candidate_path)
    sections, comment = _read_candidate(candidate, expected)
    completed = set(checkpoint.completed_phases)
    if completed != set(expected) or any(
        checkpoint.completed_phases[key].writer_response is None for key in expected if key in checkpoint.completed_phases
    ):
        raise PaperRepairCandidateError("检查点 Writer 阶段不完整，不能安全替换论文正文")

    original_res_json = (root / "res.json").read_bytes() if (root / "res.json").is_file() else None
    original_res_md = (root / "res.md").read_bytes() if (root / "res.md").is_file() else None
    template_override = _task_template_override(root, checkpoint.export_profile)
    staged_json, staged_md, staged_report = _stage_and_preflight(
        root,
        sections,
        ques_count=checkpoint.ques_count,
        export_profile=checkpoint.export_profile,
        editorial_policy=_task_editorial_policy(root, checkpoint.export_profile),
        template_override_audit=template_override["audit"],
    )
    audit = {
        "task_id": task_id,
        "reason": "editorial_quality_failure",
        "candidate_path": str(candidate.relative_to(root)).replace("\\", "/"),
        "candidate_sha256": _sha256(candidate),
        "pre_source_sha256": editorial_failure.get("source_sha256", ""),
        "post_source_sha256": staged_report.get("source_sha256", ""),
        "frozen_results_sha256": _sha256(root / "frozen_results.json"),
        "comment": comment[:2000],
        "status": "staged_preflight_passed",
    }
    manifest_path = root / "editorial_repair_candidate_manifest.json"
    manifest_data = json.dumps(audit, ensure_ascii=False, indent=2).encode("utf-8")
    original_manifest = manifest_path.read_bytes() if manifest_path.is_file() else None
    try:
        # Write the audit atomically before changing the deliverable.  If any
        # later persistence step fails, the exception handler restores both
        # the manuscript and this manifest, so a failed candidate never leaves
        # a partially applied editorial revision behind.
        _write_atomic(manifest_path, manifest_data)
        _write_atomic(root / "res.json", staged_json)
        _write_atomic(root / "res.md", staged_md)
        manager.apply_editorial_repair_candidate(
            sections,
            editorial_quality_failure=editorial_failure,
            candidate_audit=audit,
        )
    except Exception as exc:
        if original_res_json is None:
            (root / "res.json").unlink(missing_ok=True)
        else:
            _write_atomic(root / "res.json", original_res_json)
        if original_res_md is None:
            (root / "res.md").unlink(missing_ok=True)
        else:
            _write_atomic(root / "res.md", original_res_md)
        if original_manifest is None:
            manifest_path.unlink(missing_ok=True)
        else:
            _write_atomic(manifest_path, original_manifest)
        raise PaperRepairCandidateError("编辑质量候选落盘失败，已恢复原论文文件") from exc

    return {
        "status": "editorial_candidate_applied",
        "task_id": task_id,
        "preflight_status": staged_report.get("status"),
        "source_sha256": staged_report.get("source_sha256"),
        "manifest": manifest_path.name,
    }


def run_format_compliance_candidate(task_id: str, candidate_path: str) -> dict[str, Any]:
    """Apply one participant-authorized, post-completion format candidate.

    This is not a retry loophole: it has its own one-shot checkpoint budget,
    requires an intact frozen result and a current PASS report, and accepts
    only a complete Writer-section replacement that passes isolated preflight.
    The caller must still resume the ordinary export path to rebuild hashes,
    PDF/DOCX/LaTeX sidecars, and the final acceptance report.
    """
    try:
        task_id = ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise PaperRepairCandidateError("非法 task_id") from exc
    root = Path(get_work_dir(task_id)).resolve()
    if not root.is_dir():
        raise PaperRepairCandidateError("任务工作目录不存在")
    manager = CheckpointManager(str(root))
    checkpoint = manager.load()
    if checkpoint is None or checkpoint.task_id != task_id:
        raise PaperRepairCandidateError("未找到与 task_id 匹配的检查点")
    if checkpoint.workflow_state not in {"paper_preflight_passed", "completed"}:
        raise PaperRepairCandidateError("格式合规候选只允许在论文预检通过或已完成状态执行")
    if checkpoint.format_compliance_attempts:
        raise PaperRepairCandidateError("本任务已使用格式合规候选预算")
    if checkpoint.export_profile not in {"cumcm2025", "cumcm2026"}:
        raise PaperRepairCandidateError("格式合规候选仅适用于正式 CUMCM 导出 profile")
    freeze = validate_result_freeze(str(root))
    if not freeze.get("active") or not freeze.get("passed"):
        raise PaperRepairCandidateError("冻结结果未通过完整性核验，不能替换论文正文")

    report_path = root / "paper_preflight_report.json"
    md_path = root / "res.md"
    try:
        previous_report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PaperRepairCandidateError("格式合规候选缺少当前论文预检报告") from exc
    if (
        not isinstance(previous_report, dict)
        or previous_report.get("status") != "PASS"
        or not md_path.is_file()
        or previous_report.get("source_sha256") != _sha256(md_path)
    ):
        raise PaperRepairCandidateError("当前论文与 PASS 预检报告不一致，不能应用格式合规候选")

    expected = UserOutput(
        work_dir=str(root),
        ques_count=checkpoint.ques_count,
        export_profile=checkpoint.export_profile,
    ).seq
    candidate = _safe_candidate_file(root, candidate_path)
    sections, comment = _read_candidate(candidate, expected)
    if set(checkpoint.completed_phases) != set(expected) or any(
        checkpoint.completed_phases[key].writer_response is None for key in expected
    ):
        raise PaperRepairCandidateError("检查点 Writer 阶段不完整，不能安全替换论文正文")

    original_res_json = (root / "res.json").read_bytes() if (root / "res.json").is_file() else None
    original_res_md = md_path.read_bytes()
    template_override = _task_template_override(root, checkpoint.export_profile)
    staged_json, staged_md, staged_report = _stage_and_preflight(
        root,
        sections,
        ques_count=checkpoint.ques_count,
        export_profile=checkpoint.export_profile,
        editorial_policy=_task_editorial_policy(root, checkpoint.export_profile),
        template_override_audit=template_override["audit"],
    )
    audit = {
        "task_id": task_id,
        "reason": "participant_requested_format_compliance",
        "candidate_path": str(candidate.relative_to(root)).replace("\\", "/"),
        "candidate_sha256": _sha256(candidate),
        "pre_source_sha256": previous_report.get("source_sha256", ""),
        "post_source_sha256": staged_report.get("source_sha256", ""),
        "frozen_results_sha256": _sha256(root / "frozen_results.json"),
        "comment": comment[:2000],
        "status": "staged_preflight_passed",
    }
    manifest_path = root / "format_compliance_candidate_manifest.json"
    manifest_data = json.dumps(audit, ensure_ascii=False, indent=2).encode("utf-8")
    original_manifest = manifest_path.read_bytes() if manifest_path.is_file() else None
    try:
        _write_atomic(manifest_path, manifest_data)
        _write_atomic(root / "res.json", staged_json)
        _write_atomic(md_path, staged_md)
        manager.apply_format_compliance_candidate(sections, candidate_audit=audit)
    except Exception as exc:
        if original_res_json is None:
            (root / "res.json").unlink(missing_ok=True)
        else:
            _write_atomic(root / "res.json", original_res_json)
        _write_atomic(md_path, original_res_md)
        if original_manifest is None:
            manifest_path.unlink(missing_ok=True)
        else:
            _write_atomic(manifest_path, original_manifest)
        raise PaperRepairCandidateError("格式合规候选落盘失败，已恢复原论文文件") from exc

    return {
        "status": "format_compliance_candidate_applied",
        "task_id": task_id,
        "preflight_status": staged_report.get("status"),
        "source_sha256": staged_report.get("source_sha256"),
        "manifest": manifest_path.name,
    }


def run_presentation_reflow(task_id: str) -> dict[str, Any]:
    """Stage one deterministic, export-only reflow after visual review.

    Unlike an editorial candidate this function has no prose input.  It is
    restricted to a current, preflighted completed delivery with intact frozen
    results and complete Writer hand-offs.  The resume workflow will rebuild
    the manuscript from those immutable hand-offs, apply current deterministic
    normalizers and rerun all export/acceptance checks without calling a
    provider.
    """
    try:
        task_id = ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise PaperRepairCandidateError("非法 task_id") from exc
    root = Path(get_work_dir(task_id)).resolve()
    if not root.is_dir():
        raise PaperRepairCandidateError("任务工作目录不存在")
    manager = CheckpointManager(str(root))
    checkpoint = manager.load()
    if checkpoint is None or checkpoint.task_id != task_id:
        raise PaperRepairCandidateError("未找到与 task_id 匹配的检查点")
    if checkpoint.workflow_state not in {"paper_preflight_passed", "completed"}:
        raise PaperRepairCandidateError("版式重排只允许在论文预检通过或已完成状态执行")
    if checkpoint.presentation_reflow_attempts:
        raise PaperRepairCandidateError("本任务已使用版式重排预算")
    freeze = validate_result_freeze(str(root))
    if not freeze.get("active") or not freeze.get("passed"):
        raise PaperRepairCandidateError("冻结结果未通过完整性核验，不能重排论文")

    md_path = root / "res.md"
    report_path = root / "paper_preflight_report.json"
    if not md_path.is_file() or not report_path.is_file():
        raise PaperRepairCandidateError("版式重排缺少当前论文或预检报告")
    try:
        preflight = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PaperRepairCandidateError("版式重排预检报告格式无效") from exc
    if not isinstance(preflight, dict) or preflight.get("status") != "PASS":
        raise PaperRepairCandidateError("当前论文预检未通过，不能进行仅版式重排")
    current_source_sha256 = _sha256(md_path)
    if preflight.get("source_sha256") != current_source_sha256:
        raise PaperRepairCandidateError("当前论文与预检报告哈希不一致，不能进行仅版式重排")

    expected = UserOutput(
        work_dir=str(root),
        ques_count=checkpoint.ques_count,
        export_profile=checkpoint.export_profile,
    ).seq
    if set(checkpoint.completed_phases) != set(expected):
        raise PaperRepairCandidateError("检查点 Writer 阶段不完整，不能安全重排")
    if any(
        checkpoint.completed_phases[key].writer_response is None for key in expected
    ):
        raise PaperRepairCandidateError("检查点缺少 Writer 正文，不能安全重排")

    audit = {
        "task_id": task_id,
        "reason": "deterministic_presentation_reflow",
        "pre_source_sha256": current_source_sha256,
        "preflight_source_sha256": preflight.get("source_sha256", ""),
        "frozen_results_sha256": _sha256(root / "frozen_results.json"),
        "postprocessor_sha256": _sha256(Path(__file__).with_name("paper_postprocessor.py")),
        "status": "staged_for_export_only_resume",
    }
    manager.stage_presentation_reflow(reflow_audit=audit)
    manifest_path = root / "presentation_reflow_manifest.json"
    _write_atomic(
        manifest_path,
        json.dumps(audit, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    return {
        "status": "presentation_reflow_staged",
        "task_id": task_id,
        "manifest": manifest_path.name,
    }
