from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.core.checkpoint import CheckpointManager, PhaseCheckpoint, TaskCheckpoint
from app.core.workflow import MathModelWorkFlow
from app.models.user_output import UserOutput
from app.schemas.A2A import WriterResponse
from app.schemas.enums import ExportProfile
from app.tools.paper_repair_candidate import (
    PaperRepairCandidateError,
    run_editorial_repair_candidate,
    run_paper_repair_candidate,
    run_presentation_reflow,
)


def _checkpoint(root: Path, *, state: str = "frozen") -> tuple[CheckpointManager, list[str]]:
    keys = UserOutput(str(root), 1, export_profile="cumcm2026").seq
    manager = CheckpointManager(str(root))
    manager.save(
        TaskCheckpoint(
            task_id="paper-task",
            ques_all="A题",
            comp_template="CHINA",
            format_output="Markdown",
            export_profile="cumcm2026",
            questions={"ques_count": 1, "ques1": "问题一"},
            ques_count=1,
            modeler_response={"questions_solution": {"ques1": "plan"}},
            workflow_state=state,
            completed_phases={
                key: PhaseCheckpoint(
                    key=key,
                    writer_response=WriterResponse(
                        response_content=f"old {key}", footnotes=[]
                    ).model_dump(),
                    completed_at="before",
                )
                for key in keys
            },
            updated_at="now",
        )
    )
    return manager, keys


def _candidate(root: Path, keys: list[str], *, complete: bool = True) -> Path:
    sections = {key: f"new {key}" for key in keys}
    if not complete:
        sections.pop(keys[-1])
    path = root / "candidate.json"
    path.write_text(
        json.dumps({"sections": sections, "comment": "以冻结结果为唯一数值事实修订正文。"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


class TestPaperRepairCandidate(unittest.TestCase):
    def test_applies_only_after_staged_preflight_and_updates_matching_phases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _manager, keys = _checkpoint(root)
            (root / "frozen_results.json").write_text("{}", encoding="utf-8")
            (root / "res.json").write_text("{}", encoding="utf-8")
            (root / "res.md").write_text("old", encoding="utf-8")
            (root / "paper_preflight_report.json").write_text(
                json.dumps({"status": "FAIL", "source_sha256": "old"}), encoding="utf-8"
            )
            candidate = _candidate(root, keys)

            staged = {"status": "CONDITIONAL_PASS", "source_sha256": "staged"}
            with (
                patch("app.tools.paper_repair_candidate.get_work_dir", return_value=str(root)),
                patch(
                    "app.tools.paper_repair_candidate.validate_result_freeze",
                    return_value={"active": True, "passed": True},
                ),
                patch(
                    "app.tools.paper_repair_candidate.prepare_paper_markdown",
                    return_value=staged,
                ),
            ):
                result = run_paper_repair_candidate("paper-task", candidate.name)

            self.assertEqual(result["status"], "paper_candidate_applied")
            checkpoint = CheckpointManager(str(root)).load()
            self.assertEqual(checkpoint.workflow_state, "paper_repair_pending_export")
            self.assertEqual(checkpoint.paper_repair_attempts, 1)
            self.assertEqual(
                checkpoint.completed_phases["ques1"].writer_response["response_content"],
                "new ques1",
            )
            self.assertIn("new ques1", (root / "res.json").read_text(encoding="utf-8"))
            self.assertTrue((root / "paper_repair_candidate_manifest.json").is_file())

    def test_rejects_incomplete_candidate_before_any_task_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _manager, keys = _checkpoint(root)
            (root / "frozen_results.json").write_text("{}", encoding="utf-8")
            (root / "res.json").write_text("old-json", encoding="utf-8")
            (root / "res.md").write_text("old-md", encoding="utf-8")
            (root / "paper_preflight_report.json").write_text(
                json.dumps({"status": "FAIL"}), encoding="utf-8"
            )
            candidate = _candidate(root, keys, complete=False)

            with (
                patch("app.tools.paper_repair_candidate.get_work_dir", return_value=str(root)),
                patch(
                    "app.tools.paper_repair_candidate.validate_result_freeze",
                    return_value={"active": True, "passed": True},
                ),
            ):
                with self.assertRaisesRegex(PaperRepairCandidateError, "完整"):
                    run_paper_repair_candidate("paper-task", candidate.name)

            checkpoint = CheckpointManager(str(root)).load()
            self.assertEqual(checkpoint.workflow_state, "frozen")
            self.assertEqual(checkpoint.paper_repair_attempts, 0)
            self.assertEqual((root / "res.md").read_text(encoding="utf-8"), "old-md")

    def test_editorial_path_is_independent_and_records_audited_export_only_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _manager, keys = _checkpoint(root, state="completed")
            (root / "frozen_results.json").write_text("{}", encoding="utf-8")
            (root / "res.json").write_text("old-json", encoding="utf-8")
            (root / "res.md").write_text("old-md", encoding="utf-8")
            (root / "paper_preflight_report.json").write_text(
                json.dumps({"status": "FAIL", "source_sha256": "quality-before"}),
                encoding="utf-8",
            )
            candidate = _candidate(root, keys)
            staged = {"status": "PASS", "source_sha256": "quality-after"}

            with (
                patch("app.tools.paper_repair_candidate.get_work_dir", return_value=str(root)),
                patch(
                    "app.tools.paper_repair_candidate.validate_result_freeze",
                    return_value={"active": True, "passed": True},
                ),
                patch(
                    "app.tools.paper_repair_candidate.prepare_paper_markdown",
                    return_value=staged,
                ),
            ):
                result = run_editorial_repair_candidate("paper-task", candidate.name)

            self.assertEqual(result["status"], "editorial_candidate_applied")
            checkpoint = CheckpointManager(str(root)).load()
            self.assertEqual(checkpoint.workflow_state, "editorial_repair_pending_export")
            self.assertEqual(checkpoint.editorial_repair_attempts, 1)
            self.assertEqual(checkpoint.paper_repair_attempts, 0)
            manifest = json.loads(
                (root / "editorial_repair_candidate_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["reason"], "editorial_quality_failure")
            self.assertEqual(manifest["pre_source_sha256"], "quality-before")
            self.assertEqual(manifest["post_source_sha256"], "quality-after")

    def test_editorial_path_rejects_repeat_without_overwriting_paper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager, keys = _checkpoint(root, state="completed")
            checkpoint = manager.load()
            checkpoint.editorial_repair_attempts = 1
            manager.save(checkpoint)
            (root / "frozen_results.json").write_text("{}", encoding="utf-8")
            (root / "res.md").write_text("old-md", encoding="utf-8")
            (root / "paper_preflight_report.json").write_text(
                json.dumps({"status": "FAIL"}), encoding="utf-8"
            )
            candidate = _candidate(root, keys)

            with patch("app.tools.paper_repair_candidate.get_work_dir", return_value=str(root)):
                with self.assertRaisesRegex(PaperRepairCandidateError, "编辑质量返修预算"):
                    run_editorial_repair_candidate("paper-task", candidate.name)

            self.assertEqual((root / "res.md").read_text(encoding="utf-8"), "old-md")

    def test_presentation_reflow_stages_export_only_without_replacing_writer_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _manager, keys = _checkpoint(root, state="completed")
            (root / "frozen_results.json").write_text("{}", encoding="utf-8")
            (root / "res.md").write_text("current manuscript", encoding="utf-8")
            source_sha = hashlib.sha256(b"current manuscript").hexdigest()
            (root / "paper_preflight_report.json").write_text(
                json.dumps({"status": "PASS", "source_sha256": source_sha}),
                encoding="utf-8",
            )

            with (
                patch("app.tools.paper_repair_candidate.get_work_dir", return_value=str(root)),
                patch(
                    "app.tools.paper_repair_candidate.validate_result_freeze",
                    return_value={"active": True, "passed": True},
                ),
            ):
                result = run_presentation_reflow("paper-task")

            self.assertEqual(result["status"], "presentation_reflow_staged")
            checkpoint = CheckpointManager(str(root)).load()
            self.assertEqual(checkpoint.workflow_state, "presentation_reflow_pending_export")
            self.assertEqual(checkpoint.presentation_reflow_attempts, 1)
            self.assertEqual(
                checkpoint.completed_phases["ques1"].writer_response["response_content"],
                "old ques1",
            )
            self.assertTrue((root / "presentation_reflow_manifest.json").is_file())

    def test_presentation_reflow_rejects_second_budget_use(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager, _keys = _checkpoint(root, state="completed")
            checkpoint = manager.load()
            checkpoint.presentation_reflow_attempts = 1
            manager.save(checkpoint)
            (root / "frozen_results.json").write_text("{}", encoding="utf-8")
            (root / "res.md").write_text("current manuscript", encoding="utf-8")
            source_sha = hashlib.sha256(b"current manuscript").hexdigest()
            (root / "paper_preflight_report.json").write_text(
                json.dumps({"status": "PASS", "source_sha256": source_sha}),
                encoding="utf-8",
            )

            with patch("app.tools.paper_repair_candidate.get_work_dir", return_value=str(root)):
                with self.assertRaisesRegex(PaperRepairCandidateError, "版式重排预算"):
                    run_presentation_reflow("paper-task")

    def test_editorial_path_rejects_missing_freeze_or_quality_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _manager, keys = _checkpoint(root, state="paper_preflight_passed")
            (root / "frozen_results.json").write_text("{}", encoding="utf-8")
            (root / "paper_preflight_report.json").write_text(
                json.dumps({"status": "PASS"}), encoding="utf-8"
            )
            candidate = _candidate(root, keys)

            with (
                patch("app.tools.paper_repair_candidate.get_work_dir", return_value=str(root)),
                patch(
                    "app.tools.paper_repair_candidate.validate_result_freeze",
                    return_value={"active": True, "passed": True},
                ),
            ):
                with self.assertRaisesRegex(PaperRepairCandidateError, "编辑质量硬失败"):
                    run_editorial_repair_candidate("paper-task", candidate.name)

            (root / "paper_preflight_report.json").write_text(
                json.dumps({"status": "FAIL"}), encoding="utf-8"
            )
            with (
                patch("app.tools.paper_repair_candidate.get_work_dir", return_value=str(root)),
                patch(
                    "app.tools.paper_repair_candidate.validate_result_freeze",
                    return_value={"active": False, "passed": False},
                ),
            ):
                with self.assertRaisesRegex(PaperRepairCandidateError, "冻结结果"):
                    run_editorial_repair_candidate("paper-task", candidate.name)

    def test_editorial_path_rejects_missing_writer_handoff_before_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager, keys = _checkpoint(root, state="completed")
            checkpoint = manager.load()
            checkpoint.completed_phases[keys[0]].writer_response = None
            manager.save(checkpoint)
            (root / "frozen_results.json").write_text("{}", encoding="utf-8")
            (root / "res.md").write_text("old-md", encoding="utf-8")
            (root / "paper_preflight_report.json").write_text(
                json.dumps({"status": "FAIL"}), encoding="utf-8"
            )
            candidate = _candidate(root, keys)

            with (
                patch("app.tools.paper_repair_candidate.get_work_dir", return_value=str(root)),
                patch(
                    "app.tools.paper_repair_candidate.validate_result_freeze",
                    return_value={"active": True, "passed": True},
                ),
            ):
                with self.assertRaisesRegex(PaperRepairCandidateError, "Writer 阶段不完整"):
                    run_editorial_repair_candidate("paper-task", candidate.name)

            self.assertEqual((root / "res.md").read_text(encoding="utf-8"), "old-md")

    def test_editorial_apply_failure_restores_existing_paper_and_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _manager, keys = _checkpoint(root, state="completed")
            (root / "frozen_results.json").write_text("{}", encoding="utf-8")
            (root / "res.json").write_text("old-json", encoding="utf-8")
            (root / "res.md").write_text("old-md", encoding="utf-8")
            (root / "editorial_repair_candidate_manifest.json").write_text(
                "old-manifest", encoding="utf-8"
            )
            (root / "paper_preflight_report.json").write_text(
                json.dumps({"status": "FAIL"}), encoding="utf-8"
            )
            candidate = _candidate(root, keys)
            with (
                patch("app.tools.paper_repair_candidate.get_work_dir", return_value=str(root)),
                patch(
                    "app.tools.paper_repair_candidate.validate_result_freeze",
                    return_value={"active": True, "passed": True},
                ),
                patch(
                    "app.tools.paper_repair_candidate.prepare_paper_markdown",
                    return_value={"status": "PASS", "source_sha256": "after"},
                ),
                patch.object(
                    CheckpointManager,
                    "apply_editorial_repair_candidate",
                    side_effect=RuntimeError("checkpoint failure"),
                ),
            ):
                with self.assertRaisesRegex(PaperRepairCandidateError, "已恢复原论文"):
                    run_editorial_repair_candidate("paper-task", candidate.name)

            self.assertEqual((root / "res.json").read_text(encoding="utf-8"), "old-json")
            self.assertEqual((root / "res.md").read_text(encoding="utf-8"), "old-md")
            self.assertEqual(
                (root / "editorial_repair_candidate_manifest.json").read_text(encoding="utf-8"),
                "old-manifest",
            )


class TestPaperRepairExportResume(unittest.IsolatedAsyncioTestCase):
    async def test_pending_paper_candidate_resumes_export_without_llm_factory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager, _keys = _checkpoint(root, state="paper_repair_pending_export")
            workflow = MathModelWorkFlow()
            workflow.task_id = "paper-task"
            workflow.work_dir = str(root)
            workflow.ques_count = 1
            events = []

            with (
                patch("app.core.workflow.redis_manager.publish_message", AsyncMock()),
                patch.object(workflow, "_export_results", AsyncMock()) as export,
            ):
                await workflow._resume_paper_repair_candidate_export(
                    manager, ExportProfile.CUMCM2026
                )

            export.assert_awaited_once()
            output = export.await_args.args[0]
            self.assertEqual(output.get_res()["ques1"]["response_content"], "old ques1")
            self.assertEqual(events, [])

    async def test_resume_short_circuits_before_llm_for_pending_paper_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _manager, _keys = _checkpoint(root, state="paper_repair_pending_export")
            workflow = MathModelWorkFlow()
            with (
                patch("app.core.workflow.get_work_dir", return_value=str(root)),
                patch.object(workflow, "_resume_paper_repair_candidate_export", AsyncMock()) as export,
                patch("app.core.workflow.LLMFactory", side_effect=AssertionError("must not initialize LLM")),
            ):
                result = await workflow.resume("paper-task")

            self.assertIsNone(result)
            export.assert_awaited_once()

    async def test_resume_short_circuits_before_llm_for_editorial_export_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _manager, _keys = _checkpoint(root, state="editorial_repair_pending_export")
            workflow = MathModelWorkFlow()
            with (
                patch("app.core.workflow.get_work_dir", return_value=str(root)),
                patch.object(workflow, "_resume_paper_repair_candidate_export", AsyncMock()) as export,
                patch("app.core.workflow.LLMFactory", side_effect=AssertionError("must not initialize LLM")),
            ):
                result = await workflow.resume("paper-task")

            self.assertIsNone(result)
            export.assert_awaited_once()

    async def test_resume_short_circuits_before_llm_for_presentation_reflow(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _manager, _keys = _checkpoint(root, state="presentation_reflow_pending_export")
            workflow = MathModelWorkFlow()
            with (
                patch("app.core.workflow.get_work_dir", return_value=str(root)),
                patch.object(workflow, "_resume_paper_repair_candidate_export", AsyncMock()) as export,
                patch("app.core.workflow.LLMFactory", side_effect=AssertionError("must not initialize LLM")),
            ):
                result = await workflow.resume("paper-task")

            self.assertIsNone(result)
            export.assert_awaited_once()
