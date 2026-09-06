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

    def test_runtime_seconds_accumulate_and_survive_reload(self):
        """codex 审计：duration_seconds 必须真正入账且续传后继续累计。"""
        with tempfile.TemporaryDirectory() as work_dir:
            init_budget(work_dir, "task-1")
            record_provider_call(work_dir, "task-1", known_tokens=100, duration_seconds=5.5)
            record_provider_call(work_dir, "task-1", known_tokens=200, duration_seconds=7.5)
            # 模拟中断续传：重新走 load 路径（init_budget 无 overrides 不重置用量）
            init_budget(work_dir, "task-1")
            record_provider_call(work_dir, "task-1", known_tokens=50, duration_seconds=2.0)
            summary = get_budget_summary(work_dir, "task-1")
            self.assertAlmostEqual(summary["usage"]["runtime_seconds"], 15.0)
            self.assertEqual(summary["usage"]["known_tokens"], 350)

    def test_token_usage_passes_duration_to_budget(self):
        """record_token_usage 的 duration_seconds 必须透传到预算账本。"""
        import unittest.mock as mock

        from app.core.llm.types import Usage
        from app.services import token_usage as token_usage_service
        from app.services.token_usage import record_token_usage

        with tempfile.TemporaryDirectory() as work_dir:
            init_budget(work_dir, "task-9")
            with mock.patch.object(
                token_usage_service.common_utils, "get_work_dir", return_value=work_dir
            ):
                record_token_usage(
                    "task-9", "CoderAgent", "m",
                    Usage(prompt_tokens=10, completion_tokens=5, reasoning_tokens=0),
                    duration_seconds=42.0,
                )
            summary = get_budget_summary(work_dir, "task-9")
            self.assertAlmostEqual(summary["usage"]["runtime_seconds"], 42.0)


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
