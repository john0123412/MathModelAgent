"""Batch-4 tests: budget ledger corruption and deployment version self-proof."""

import os
import tempfile
import unittest
from pathlib import Path

from app.routers.common_router import _get_deployment_info
from app.services.task_budget import (
    BUDGET_FILENAME,
    get_budget_summary,
    init_budget,
    record_provider_call,
)


class BudgetCorruptionTest(unittest.TestCase):
    def test_corrupt_ledger_is_quarantined_not_silently_reset(self):
        with tempfile.TemporaryDirectory() as work_dir:
            path = Path(work_dir, BUDGET_FILENAME)
            path.write_text("{ broken json", encoding="utf-8")
            data = init_budget(work_dir, "task-1")
            quarantined = [n for n in os.listdir(work_dir) if ".corrupt-" in n]
            self.assertEqual(len(quarantined), 1)
            self.assertEqual(
                Path(work_dir, quarantined[0]).read_text(encoding="utf-8"),
                "{ broken json",
            )
            self.assertIn("reset_from_corrupt", data)
            summary = get_budget_summary(work_dir, "task-1")
            self.assertIsNotNone(summary["reset_from_corrupt"])

    def test_task_id_mismatch_quarantines_foreign_ledger(self):
        with tempfile.TemporaryDirectory() as work_dir:
            init_budget(work_dir, "task-other")
            before = Path(work_dir, BUDGET_FILENAME).read_text(encoding="utf-8")
            data = init_budget(work_dir, "task-1")
            self.assertIn("reset_from_corrupt", data)
            quarantined = [n for n in os.listdir(work_dir) if ".corrupt-" in n]
            self.assertEqual(len(quarantined), 1)
            self.assertEqual(Path(work_dir, quarantined[0]).read_text(encoding="utf-8"), before)

    def test_healthy_ledger_usage_survives_reload(self):
        with tempfile.TemporaryDirectory() as work_dir:
            init_budget(work_dir, "task-1")
            wd = Path(work_dir)
            record_provider_call(str(wd), "task-1", known_tokens=100, duration_seconds=1.0)
            record_provider_call(str(wd), "task-1", known_tokens=None, duration_seconds=1.0)
            summary = get_budget_summary(work_dir, "task-1")
            self.assertEqual(summary["usage"]["provider_calls"], 2)
            self.assertEqual(summary["usage"]["known_tokens"], 100)
            self.assertIsNone(summary.get("reset_from_corrupt"))

    def test_unknown_call_not_counted_as_zero_cost(self):
        with tempfile.TemporaryDirectory() as work_dir:
            init_budget(work_dir, "task-1")
            record_provider_call(work_dir, "task-1", known_tokens=None, duration_seconds=0.5)
            summary = get_budget_summary(work_dir, "task-1")
            self.assertGreaterEqual(summary["usage"].get("unknown_calls", 0), 1)
            self.assertGreaterEqual(summary.get("unknown_usage_events", 0), 1)


class DeploymentVersionTest(unittest.TestCase):
    def test_git_commit_self_proof_from_env(self):
        env = {
            "GIT_COMMIT": "",
            "MMA_GIT_COMMIT": "a9b228abc6923a71458cc819a97cf321af5f7837",
            "MMA_GIT_DIRTY": "false",
        }
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            info = _get_deployment_info()
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertEqual(info["git_commit"], "a9b228abc6923a71458cc819a97cf321af5f7837")
        self.assertFalse(info["git_dirty"])
        self.assertTrue(info["capability_version"])


if __name__ == "__main__":
    unittest.main()
