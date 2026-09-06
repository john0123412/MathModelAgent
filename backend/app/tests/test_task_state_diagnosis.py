"""Batch-3 tests: state diagnosis, audited reconciliation, resume contradiction."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock

from fastapi import BackgroundTasks, HTTPException

from app.core.checkpoint import CheckpointManager, TaskCheckpoint
from app.routers import modeling_router
from app.services import task_status as task_status_service
from app.tools.task_state_diagnosis import (
    MAIN_ARTIFACTS,
    diagnose_task_state,
    reconcile_task_state,
)


def _seed(
    work_dir: str,
    *,
    external: str,
    workflow_state: str,
    quality_status: str = "not_run",
    artifacts: tuple[str, ...] = MAIN_ARTIFACTS,
    technical: str = "TECHNICAL_PASS",
) -> None:
    root = Path(work_dir)
    (root / "task_status.json").write_text(
        json.dumps({"status": external}), encoding="utf-8"
    )
    CheckpointManager(work_dir).save(
        TaskCheckpoint(
            task_id="task-x",
            ques_all="题面",
            comp_template="CHINA",
            format_output="Markdown",
            export_profile="cumcm2026",
            questions={"ques_count": 1, "ques1": "问题一"},
            ques_count=1,
            modeler_response={},
            workflow_state=workflow_state,
            quality_review_status=quality_status,
            updated_at="2026-09-05T00:00:00",
        )
    )
    for name in artifacts:
        (root / name).write_text("{}", encoding="utf-8")
    if technical:
        (root / "final_acceptance_report.json").write_text(
            json.dumps({"technical_status": technical}), encoding="utf-8"
        )


class DiagnoseTest(unittest.TestCase):
    def test_completed_with_quality_repair_is_contradiction(self):
        with tempfile.TemporaryDirectory() as work_dir:
            # 08-23 事故形态
            _seed(work_dir, external="completed", workflow_state="quality_repair",
                  quality_status="repair_requested")
            diagnosis = diagnose_task_state(work_dir)
            self.assertEqual(diagnosis["verdict"], "CONTRADICTION")
            self.assertTrue(any("quality_repair" in i for i in diagnosis["issues"]))

    def test_completed_with_terminal_state_is_consistent(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _seed(work_dir, external="completed", workflow_state="paper_preflight_passed")
            self.assertEqual(diagnose_task_state(work_dir)["verdict"], "CONSISTENT")

    def test_completed_with_pending_export_is_transitional(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _seed(work_dir, external="completed", workflow_state="paper_repair_pending_export")
            self.assertEqual(diagnose_task_state(work_dir)["verdict"], "TRANSITIONAL_EXPORT")

    def test_pending_export_with_unexecuted_repair_is_contradiction(self):
        with tempfile.TemporaryDirectory() as work_dir:
            # codex 审计场景：TRANSITIONAL_EXPORT 不得覆盖未执行返修的矛盾。
            _seed(work_dir, external="completed", workflow_state="paper_repair_pending_export",
                  quality_status="repair_requested")
            diagnosis = diagnose_task_state(work_dir)
            self.assertEqual(diagnosis["verdict"], "CONTRADICTION")
            self.assertTrue(any("repair_requested" in i for i in diagnosis["issues"]))

    def test_completed_with_missing_artifact_is_contradiction(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _seed(work_dir, external="completed", workflow_state="paper_preflight_passed",
                  artifacts=tuple(n for n in MAIN_ARTIFACTS if n != "res.pdf"))
            diagnosis = diagnose_task_state(work_dir)
            self.assertEqual(diagnosis["verdict"], "CONTRADICTION")
            self.assertTrue(any("res.pdf" in i for i in diagnosis["issues"]))

    def test_completed_with_failed_acceptance_is_contradiction(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _seed(work_dir, external="completed", workflow_state="paper_preflight_passed",
                  technical="TECHNICAL_FAIL")
            self.assertEqual(diagnose_task_state(work_dir)["verdict"], "CONTRADICTION")

    def test_waiting_quality_review_matching_is_consistent(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _seed(work_dir, external="waiting_quality_review",
                  workflow_state="waiting_quality_review", quality_status="pending")
            self.assertEqual(diagnose_task_state(work_dir)["verdict"], "CONSISTENT")


class ReconcileTest(unittest.TestCase):
    def test_converge_completed_fixes_state_with_audit(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _seed(work_dir, external="completed", workflow_state="quality_repair",
                  quality_status="approved")
            record = reconcile_task_state(
                work_dir, action="converge_completed", operator="john", reason="终版已人工导出"
            )
            self.assertEqual(record["before"]["workflow_state"], "quality_repair")
            self.assertEqual(record["after"]["workflow_state"], "paper_preflight_passed")
            checkpoint = json.loads(
                Path(work_dir, "checkpoint.json").read_text(encoding="utf-8")
            )
            self.assertEqual(checkpoint["workflow_state"], "paper_preflight_passed")
            audit = json.loads(
                Path(work_dir, "state_reconciliation.json").read_text(encoding="utf-8")
            )
            self.assertEqual(audit["history"][0]["operator"], "john")
            self.assertEqual(diagnose_task_state(work_dir)["verdict"], "CONSISTENT")

    def test_converge_refused_without_technical_pass(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _seed(work_dir, external="completed", workflow_state="quality_repair",
                  technical="TECHNICAL_FAIL")
            with self.assertRaisesRegex(RuntimeError, "downgrade_to_failed"):
                reconcile_task_state(
                    work_dir, action="converge_completed", operator="john", reason="x"
                )

    def test_converge_refused_with_pending_repair_request(self):
        with tempfile.TemporaryDirectory() as work_dir:
            # 08-23 形态：repair_requested 未执行——收敛等于吞掉返修，必须拒绝。
            _seed(work_dir, external="completed", workflow_state="quality_repair",
                  quality_status="repair_requested")
            with self.assertRaisesRegex(RuntimeError, "返修"):
                reconcile_task_state(
                    work_dir, action="converge_completed", operator="john", reason="x"
                )

    def test_downgrade_to_failed_persists_failed(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _seed(work_dir, external="completed", workflow_state="quality_repair",
                  artifacts=tuple(n for n in MAIN_ARTIFACTS if n != "res.docx"))
            reconcile_task_state(
                work_dir, action="downgrade_to_failed", operator="john", reason="产物不全"
            )
            status = json.loads(
                Path(work_dir, "task_status.json").read_text(encoding="utf-8")
            )
            self.assertEqual(status["status"], "failed")

    def test_reconcile_requires_operator_and_reason(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _seed(work_dir, external="completed", workflow_state="quality_repair")
            with self.assertRaises(ValueError):
                reconcile_task_state(work_dir, action="converge_completed", operator="", reason="x")

    def test_reconcile_refused_on_consistent_state(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _seed(work_dir, external="completed", workflow_state="paper_preflight_passed")
            with self.assertRaisesRegex(RuntimeError, "CONSISTENT"):
                reconcile_task_state(
                    work_dir, action="converge_completed", operator="john", reason="x"
                )


class ResumeContradictionEndpointTest(unittest.IsolatedAsyncioTestCase):
    async def test_resume_completed_with_inflight_state_returns_contradiction(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _seed(work_dir, external="completed", workflow_state="quality_repair",
                  quality_status="repair_requested")
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
            ):
                with self.assertRaises(HTTPException) as ctx:
                    await modeling_router.resume_task("task-x", BackgroundTasks())
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertIn("状态矛盾", ctx.exception.detail)
            self.assertIn("task_state_diagnosis", ctx.exception.detail)

    async def test_resume_completed_clean_still_says_no_need(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _seed(work_dir, external="completed", workflow_state="paper_preflight_passed")
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
            ):
                with self.assertRaises(HTTPException) as ctx:
                    await modeling_router.resume_task("task-x", BackgroundTasks())
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertIn("无需续传", ctx.exception.detail)


class FinalAcceptanceStatusDefenseTest(unittest.IsolatedAsyncioTestCase):
    async def test_completed_requires_artifact_set_on_disk(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            for name in MAIN_ARTIFACTS:
                if name != "res.pdf":
                    (root / name).write_text("{}", encoding="utf-8")
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
                mock.patch.object(
                    modeling_router.redis_manager, "publish_message", new=AsyncMock()
                ),
            ):
                ok = await modeling_router._apply_final_acceptance_status(
                    "task-x", {"technical_status": "TECHNICAL_PASS"}
                )
            self.assertFalse(ok)
            status = json.loads((root / "task_status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "failed")
            self.assertIn("res.pdf", status["message"])

    async def test_completed_written_when_artifacts_present(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            for name in MAIN_ARTIFACTS:
                (root / name).write_text("{}", encoding="utf-8")
            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=work_dir),
                mock.patch.object(task_status_service, "get_work_dir", return_value=work_dir),
                mock.patch.object(
                    modeling_router.redis_manager, "publish_message", new=AsyncMock()
                ),
            ):
                ok = await modeling_router._apply_final_acceptance_status(
                    "task-x", {"technical_status": "TECHNICAL_PASS"}
                )
            self.assertTrue(ok)
            status = json.loads((root / "task_status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "completed")


if __name__ == "__main__":
    unittest.main()
