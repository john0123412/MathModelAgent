"""受控的本机 Coder 修复候选执行通道。

该模块不是通用代码执行 API。候选只能绑定到一次已经授权的
``quality_repair`` 子题，且仍须通过现有 ``record_execution_evidence``。
候选代码不能直接写入 execution manifest、冻结结果或检查点。
"""

from __future__ import annotations

import asyncio
import ast
import datetime as _datetime
import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Callable

from app.core.checkpoint import CheckpointManager
from app.schemas.A2A import CoderToWriter
from app.tools.execution_validation import record_execution_evidence
from app.tools.interpreter_factory import create_interpreter
from app.tools.notebook_serializer import NotebookSerializer
from app.utils.common_utils import ensure_safe_task_id, get_work_dir


_SUBTASK_RE = re.compile(r"^ques[1-9][0-9]*$")
_MAX_SCRIPT_BYTES = 512 * 1024
_MAX_EVIDENCE_BYTES = 256 * 1024
_DEFAULT_TIMEOUT_SECONDS = 120
_PROTECTED_FILES = frozenset(
    {
        "checkpoint.json",
        "execution_validation.json",
        "execution_validation_report.json",
        "frozen_results.json",
        "candidate_manifest.json",
        "repair_candidate_manifest.json",
        "repair_candidate_audit.jsonl",
        "reproducibility_manifest.json",
        "task_status.json",
        "modeler_plan.json",
        "modeling_decision.json",
        "modeling_decision.md",
    }
)
_RUNTIME_PATHS = frozenset({"notebook.ipynb"})
_PARENT_PATH_RE = re.compile(r"(^|[\\/])\.\.([\\/]|$)")


class RepairCandidateError(RuntimeError):
    """候选未通过绑定、执行或证据门禁。"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_task_file(root: Path, value: object, *, allow_absolute: bool = False) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise RepairCandidateError("候选文件路径不能为空")
    raw = Path(value.strip())
    if raw.is_absolute() and not allow_absolute:
        raise RepairCandidateError("证据文件必须使用任务目录内的相对路径")
    if ".." in raw.parts:
        raise RepairCandidateError("候选文件路径不允许 .. 路径穿越")
    path = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise RepairCandidateError("候选文件路径越出任务目录") from exc
    # Do not follow a symlink supplied by a local client.  Check every existing
    # component, including the file itself, rather than only ``Path.is_symlink``.
    current = root.resolve()
    for component in path.relative_to(root.resolve()).parts:
        current /= component
        if current.is_symlink():
            raise RepairCandidateError("候选文件路径不允许符号链接")
    if not path.is_file():
        raise RepairCandidateError(f"候选文件不存在: {path.name}")
    return path


def _relative(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    result: dict[str, tuple[int, int, str]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            stat = path.stat()
            result[_relative(root, path)] = (stat.st_size, stat.st_mtime_ns, _sha256(path))
        except OSError:
            continue
    return result


def _changed(before: dict[str, tuple[int, int, str]], after: dict[str, tuple[int, int, str]]) -> set[str]:
    return {
        name
        for name in set(before) | set(after)
        if before.get(name) != after.get(name)
    }


def _symlink_paths(root: Path) -> set[str]:
    paths: set[str] = set()
    for path in root.rglob("*"):
        try:
            if path.is_symlink():
                paths.add(_relative(root, path))
        except OSError:
            continue
    return paths


def _is_runtime_path(name: str) -> bool:
    return name in _RUNTIME_PATHS or name.startswith((".jupyter_runtime/", ".ipython/", ".matplotlib/"))


def _evidence_paths(evidence: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    for item in evidence.get("metrics", []):
        if isinstance(item, dict) and isinstance(item.get("source_path"), str):
            paths.add(item["source_path"].replace("\\", "/"))
    for item in evidence.get("constraints", []):
        if isinstance(item, dict) and isinstance(item.get("source_path"), str):
            paths.add(item["source_path"].replace("\\", "/"))
    for item in evidence.get("figures", []):
        if isinstance(item, dict):
            for key in ("path", "data_path"):
                if isinstance(item.get(key), str):
                    paths.add(item[key].replace("\\", "/"))
    return paths


def _read_json(path: Path, *, limit: int) -> dict[str, Any]:
    try:
        if path.stat().st_size > limit:
            raise RepairCandidateError(f"文件超过大小上限: {path.name}")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except RepairCandidateError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RepairCandidateError(f"无法读取 JSON: {path.name}") from exc
    if not isinstance(payload, dict):
        raise RepairCandidateError(f"JSON 顶层必须是对象: {path.name}")
    return payload


def _expected_artifact_paths(root: Path, subtask_id: str) -> set[str]:
    """Return safe, exact artifact paths declared for one formal subtask.

    The ModelPlan is immutable from the candidate's perspective.  A declaration
    can therefore widen the output allowlist only for that exact relative path;
    malformed, absolute, traversal, symlinked, or protected paths are ignored
    and never become an implicit write permission.
    """
    try:
        plan = _read_json(root / "modeler_plan.json", limit=_MAX_EVIDENCE_BYTES)
    except RepairCandidateError:
        return set()

    model_plan = plan.get("model_plan", plan)
    if not isinstance(model_plan, dict):
        return set()
    subtasks = model_plan.get("subtasks")
    if not isinstance(subtasks, dict):
        return set()
    subtask = subtasks.get(subtask_id)
    if not isinstance(subtask, dict):
        return set()
    artifacts = subtask.get("expected_artifacts")
    if not isinstance(artifacts, list):
        return set()

    root = root.resolve()
    allowed: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        raw_path = artifact.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        raw_path = raw_path.strip()
        normalised = raw_path.replace("\\", "/")
        try:
            posix_path = PurePosixPath(normalised)
            windows_path = PureWindowsPath(raw_path)
        except (TypeError, ValueError):
            continue
        # Reject both POSIX and Windows absolute/drive-relative spellings even
        # when this process runs on the other platform.
        if (
            posix_path.is_absolute()
            or windows_path.is_absolute()
            or bool(windows_path.drive)
            or not posix_path.parts
            or any(part in {"", ".."} for part in posix_path.parts)
        ):
            continue

        candidate_path = (root / Path(*posix_path.parts)).resolve()
        try:
            relative_path = candidate_path.relative_to(root)
        except ValueError:
            continue

        # Existing symlink components are never an allowed destination.  A
        # newly-created symlink is caught by the post-execution symlink gate.
        current = root
        unsafe = False
        for component in relative_path.parts:
            current /= component
            if current.is_symlink():
                unsafe = True
                break
        if unsafe or relative_path.name in _PROTECTED_FILES:
            continue
        allowed.add(str(relative_path).replace("\\", "/"))
    return allowed


def _has_path_escape(code: str) -> bool:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    return any(
        isinstance(node.value, str)
        and _PARENT_PATH_RE.search(node.value.replace("\\", "/"))
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
    )


def _validate_evidence(evidence: dict[str, Any], subtask_id: str) -> None:
    required = {"subtask_id", "constraints", "metrics", "figures"}
    if set(evidence) != required:
        raise RepairCandidateError("evidence JSON 只能包含 subtask_id/constraints/metrics/figures")
    if evidence.get("subtask_id") != subtask_id:
        raise RepairCandidateError("evidence.subtask_id 与候选子题不一致")
    if not isinstance(evidence.get("constraints"), list) or not isinstance(evidence.get("metrics"), list):
        raise RepairCandidateError("evidence 的 constraints/metrics 必须是数组")
    if not isinstance(evidence.get("figures"), list):
        raise RepairCandidateError("evidence.figures 必须是数组")


def _validate_checkpoint(task_id: str, subtask_id: str, review_id: str, manager: CheckpointManager):
    checkpoint = manager.load()
    if checkpoint is None or checkpoint.task_id != task_id:
        raise RepairCandidateError("未找到与 task_id 匹配的检查点")
    if checkpoint.quality_review_status != "repair_requested":
        raise RepairCandidateError("任务没有有效的执行质量返修授权")
    if checkpoint.quality_review_id != review_id:
        raise RepairCandidateError("review_id 与当前冻结结果不匹配")
    history = checkpoint.quality_review_history
    if not history or history[-1].get("action") != "repair_requested":
        raise RepairCandidateError("缺少当前质量返修授权记录")
    quality_failed = history[-1].get("failed_subtasks", [])
    if checkpoint.workflow_state == "quality_repair":
        failed = quality_failed
    elif checkpoint.workflow_state == "repairing":
        # A full execution-validation failure may occur after one or more
        # operator candidates have passed their per-subtask evidence.  Bind a
        # follow-up candidate to that persisted failure instead of forcing the
        # unstable model Coder to overwrite the reviewed result.
        failure = checkpoint.last_validation_failure
        report = failure.get("report", {}) if isinstance(failure, dict) else {}
        failed = failure.get("failed_subtasks", []) if isinstance(failure, dict) else []
        if (
            checkpoint.targeted_repair_attempts < 1
            or not isinstance(report, dict)
            or report.get("status") != "FAIL"
        ):
            raise RepairCandidateError("repairing 状态缺少持久化的全量验证失败证据")
        if subtask_id not in quality_failed:
            raise RepairCandidateError("候选子题不在原执行质量返修授权范围")
    else:
        raise RepairCandidateError("任务不在已授权的 quality_repair/repairing 状态")
    if subtask_id not in failed:
        raise RepairCandidateError("候选子题不在当前失败清单")
    return checkpoint


class _TaskBackup:
    """临时目录中的任务文件快照，失败时恢复整个任务目录。"""

    def __init__(self, root: Path):
        self.root = root
        self.temp_dir = tempfile.TemporaryDirectory(prefix="repair-candidate-")
        self.files: set[str] = set()
        self.directories: set[str] = set()
        try:
            for path in root.rglob("*"):
                if path.is_dir() and not path.is_symlink():
                    self.directories.add(str(path.relative_to(root)).replace("\\", "/"))
                    continue
                if not path.is_file() or path.is_symlink():
                    continue
                relative = _relative(root, path)
                destination = Path(self.temp_dir.name) / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
                self.files.add(relative)
        except Exception:
            self.cleanup()
            raise

    def restore(self) -> None:
        # Remove files and symlinks created by the candidate first.  Only paths
        # below this exact task root are considered.
        for path in sorted(self.root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if not path.is_file() and not path.is_symlink():
                continue
            relative = str(path.relative_to(self.root)).replace("\\", "/")
            if relative not in self.files:
                path.unlink()
        for relative in self.files:
            source = Path(self.temp_dir.name) / relative
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.is_symlink():
                destination.unlink()
            elif destination.is_dir():
                shutil.rmtree(destination)
            temporary = destination.with_name(destination.name + ".restore.tmp")
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)

        # Prune empty directories that were created by the candidate, without
        # touching the task root itself.
        for path in sorted(self.root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if path.is_dir() and not path.is_symlink():
                relative = str(path.relative_to(self.root)).replace("\\", "/")
                if relative in self.directories:
                    continue
                try:
                    path.rmdir()
                except OSError:
                    pass

    def cleanup(self) -> None:
        self.temp_dir.cleanup()


def _write_audit(root: Path, payload: dict[str, Any]) -> None:
    payload = {**payload, "recorded_at": _datetime.datetime.now().isoformat()}
    audit = root / "repair_candidate_audit.jsonl"
    with audit.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    (root / "repair_candidate_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _sanitized_failure(message: object) -> str:
    text = " ".join(str(message).split())[:500]
    text = re.sub(
        r"(?i)(api[_-]?key|token|password|secret|cookie)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        text,
    )
    return text


async def run_repair_candidate(
    task_id: str,
    subtask_id: str,
    review_id: str,
    script_path: str,
    evidence_path: str,
    *,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    interpreter_factory: Callable[..., Any] = create_interpreter,
) -> dict[str, Any]:
    """执行一次本机候选并提交后端受控证据。

    该函数只允许由容器内 CLI 调用；它不被 FastAPI 路由注册。候选失败时
    保留任务现场但不会写冻结结果或把工作流推进到 Writer。
    """
    try:
        task_id = ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise RepairCandidateError("非法 task_id") from exc
    if not _SUBTASK_RE.fullmatch(subtask_id):
        raise RepairCandidateError("subtask_id 必须为 quesN")
    if not isinstance(review_id, str) or not review_id.strip():
        raise RepairCandidateError("review_id 不能为空")
    if timeout_seconds <= 0 or timeout_seconds > 600:
        raise RepairCandidateError("候选超时必须在 1..600 秒")

    root = Path(get_work_dir(task_id)).resolve()
    if not root.is_dir():
        raise RepairCandidateError("任务工作目录不存在")
    manager = CheckpointManager(str(root))
    checkpoint = _validate_checkpoint(task_id, subtask_id, review_id.strip(), manager)
    script = _safe_task_file(root, script_path, allow_absolute=True)
    evidence_file = _safe_task_file(root, evidence_path, allow_absolute=True)
    if script.suffix.lower() != ".py":
        raise RepairCandidateError("候选脚本必须是 .py 文件")
    if script.stat().st_size > _MAX_SCRIPT_BYTES:
        raise RepairCandidateError("候选脚本超过大小上限")
    evidence = _read_json(evidence_file, limit=_MAX_EVIDENCE_BYTES)
    _validate_evidence(evidence, subtask_id)

    # Keep a pre-preparation snapshot for rollback.  Once the durable clean
    # source boundary is established below, ``before`` is reset so the archive
    # itself is not mistaken for a candidate output.
    before = _snapshot(root)
    backup = _TaskBackup(root)
    checkpoint_path = root / "checkpoint.json"
    checkpoint_sha256 = _sha256(checkpoint_path)
    script_sha256 = _sha256(script)
    evidence_sha256 = _sha256(evidence_file)
    candidate_id = secrets.token_hex(12)
    started = _datetime.datetime.now().isoformat()
    interpreter = None
    execution_error = ""
    output = ""
    execution_failure: str | None = None

    def fail(message: object) -> None:
        """Rollback every candidate mutation, then append a redacted failure audit."""
        changed_now = sorted(_changed(before, _snapshot(root)))
        rollback_error = ""
        try:
            backup.restore()
        except Exception as exc:  # pragma: no cover - defensive filesystem failure
            rollback_error = type(exc).__name__
        finally:
            backup.cleanup()
        failure = {
            "candidate_id": candidate_id,
            "task_id": task_id,
            "subtask_id": subtask_id,
            "review_id": review_id,
            "candidate_sha256": script_sha256,
            "evidence_sha256": evidence_sha256,
            "checkpoint_sha256": checkpoint_sha256,
            "started_at": started,
            "finished_at": _datetime.datetime.now().isoformat(),
            "changed_outputs": changed_now,
            "status": "candidate_rejected",
            "error": _sanitized_failure(message),
        }
        if rollback_error:
            failure["rollback_error"] = rollback_error
        try:
            _write_audit(root, failure)
        except Exception:
            # The original failure is the useful result; a filesystem audit
            # failure must not turn into a false success or a traceback leak.
            pass
        raise RepairCandidateError(failure["error"])

    try:
        prepared_now = manager.prepare_quality_repair_source(
            str(root / "notebook.ipynb")
        )
        serializer = NotebookSerializer(work_dir=str(root))
        if prepared_now:
            # Establish an explicit empty source file before execution.  The
            # controlled interpreter appends the actual candidate cell(s) to
            # this serializer; a later resume therefore sees the same chain.
            serializer.write_to_notebook()
        before = _snapshot(root)
        interpreter = await interpreter_factory(
            task_id=task_id,
            work_dir=str(root),
            notebook_serializer=serializer,
            timeout=timeout_seconds,
        )
        # LocalCodeInterpreter keeps its own watchdog on the instance; the
        # factory's timeout argument is an E2B initialization timeout there.
        # Override the per-candidate limit explicitly so a repair cannot inherit
        # the much longer normal Coder budget.
        if hasattr(interpreter, "execution_timeout"):
            interpreter.execution_timeout = timeout_seconds
        source_code = script.read_text(encoding="utf-8")
        if _has_path_escape(source_code):
            raise RepairCandidateError("候选代码包含 .. 路径穿越")
        # LocalCodeInterpreter executes a notebook cell rather than invoking a
        # file.  Restore the two standard script invariants explicitly so a
        # normal ``if __name__ == '__main__'``/argparse entry point behaves the
        # same in the controlled channel.  Discard CLI argv to prevent the
        # repair-channel arguments from leaking into the candidate parser.
        code = (
            "__name__ = '__main__'\n"
            f"__file__ = {json.dumps(str(script), ensure_ascii=False)}\n"
            "import sys as __repair_candidate_sys\n"
            "__repair_candidate_sys.argv = [__file__]\n"
            + source_code
        )
        output, failed, execution_error = await asyncio.wait_for(
            interpreter.execute_code(code), timeout=timeout_seconds + 5
        )
        if failed:
            execution_failure = execution_error or "候选脚本执行失败"
        elif not any(
            cell.get("cell_type") == "code" and cell.get("source") == code
            for cell in serializer.nb.get("cells", [])
        ):
            # The production interpreters append the executed cell themselves.
            # Keep the contract explicit for compatible/custom factories too:
            # a successful candidate always leaves its runnable source in the
            # clean chain before evidence is accepted.
            serializer.add_code_cell_to_notebook(code)
    except asyncio.TimeoutError:
        execution_error = "候选脚本超过受控超时，未生成冻结结果"
        execution_failure = execution_error
    except RepairCandidateError:
        execution_failure = "候选代码校验失败"
    except Exception as exc:
        execution_error = f"候选执行失败: {type(exc).__name__}"
        execution_failure = execution_error
    finally:
        if interpreter is not None:
            try:
                await interpreter.cleanup()
            except Exception:
                pass
    if execution_failure:
        fail(execution_failure)

    after = _snapshot(root)
    changed = _changed(before, after)
    new_symlinks = _symlink_paths(root)
    if new_symlinks:
        fail("候选执行后任务目录存在符号链接: " + ", ".join(sorted(new_symlinks)))
    protected_changed = sorted(name for name in changed if name in _PROTECTED_FILES)
    if protected_changed:
        fail("候选改写了受保护文件: " + ", ".join(protected_changed))

    expected_artifacts = _expected_artifact_paths(root, subtask_id)
    invalid_outputs = sorted(
        name
        for name in changed
        if not _is_runtime_path(name)
        and name not in {"repair_candidate_manifest.json", "repair_candidate_audit.jsonl"}
        and name not in {_relative(root, script), _relative(root, evidence_file)}
        and not name.startswith(f"{subtask_id}_")
        and name not in expected_artifacts
    )
    immutable_inputs = {_relative(root, script), _relative(root, evidence_file)}
    if immutable_inputs & changed:
        fail("候选不得改写脚本或 evidence JSON")
    if invalid_outputs:
        fail(
            "候选只能更新当前子题 quesN_* 文件或 ModelPlan 声明的预期产物: "
            + ", ".join(invalid_outputs)
        )

    source_paths = _evidence_paths(evidence)
    if not source_paths or any(
        not path.startswith(f"{subtask_id}_") or path not in changed for path in source_paths
    ):
        fail("证据来源必须是本轮新生成/更新的当前子题 quesN_* 文件")

    try:
        evidence_result = record_execution_evidence(str(root), **evidence)
    except Exception as exc:
        fail(f"候选执行证据处理失败: {type(exc).__name__}")
    if evidence_result.get("ok") is not True or evidence_result.get("feasible") is not True:
        fail(
            "候选执行证据未通过: " + "; ".join(map(str, evidence_result.get("errors", [])))
        )

    created_images = sorted(
        name for name in changed if name.startswith(f"{subtask_id}_") and name.lower().endswith((".png", ".jpg", ".jpeg"))
    )
    response = CoderToWriter(
        code_response=f"受控候选 {candidate_id} 已执行并记录后端证据。",
        created_images=created_images,
        execution_attempted=True,
        execution_succeeded=True,
        execution_error_occurred=False,
    )
    try:
        manager.mark_solution_coder_completed(subtask_id, response.model_dump())
    except Exception as exc:
        fail(f"候选成功后检查点写入失败: {type(exc).__name__}")
    audit = {
        "candidate_id": candidate_id,
        "task_id": task_id,
        "subtask_id": subtask_id,
        "review_id": review_id,
        "candidate_sha256": script_sha256,
        "evidence_sha256": evidence_sha256,
        "checkpoint_sha256": checkpoint_sha256,
        "started_at": started,
        "finished_at": _datetime.datetime.now().isoformat(),
        "checkpoint_updated_at": checkpoint.updated_at,
        "changed_outputs": sorted(changed),
        "execution_error": execution_error,
        "output_chars": len(output or ""),
        "evidence_result": evidence_result,
        "status": "evidence_passed",
    }
    _write_audit(root, audit)
    backup.cleanup()
    return {**audit, "response": response.model_dump()}
