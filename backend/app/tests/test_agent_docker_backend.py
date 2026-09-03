"""Roadmap F: Agent Docker backend contracts (no provider required)."""

import json
import os
import tempfile
import unittest
from unittest import mock

from app.services import agent_operations, task_budget, figure_plan
from app.services.doctor import container_doctor, template_capabilities
from app.services.paper_review import assemble_review_packet, save_review
from app.utils import common_utils


class TestIdempotency(unittest.TestCase):
    def test_same_key_same_content_replays(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(common_utils, "WORK_DIR_ROOT", tmp):
                with mock.patch("app.services.idempotency.WORK_DIR_ROOT", tmp):
                    # Need to patch where idempotency reads WORK_DIR_ROOT (imported)
                    import app.services.idempotency as im

                    orig_root = im.WORK_DIR_ROOT
                    im.WORK_DIR_ROOT = tmp
                    try:
                        os.makedirs(os.path.join(tmp, "20250101-000000-abc123"), exist_ok=True)
                        key = "test-key-12345678"
                        h = im.build_request_hash("ques", "CHINA", "Markdown", "default", [], None)
                        existing, conflict = im.check_idempotency(key, h)
                        self.assertIsNone(existing)
                        self.assertIsNone(conflict)
                        im.record_idempotency(key, h, "20250101-000000-abc123")
                        existing2, conflict2 = im.check_idempotency(key, h)
                        self.assertEqual(existing2, "20250101-000000-abc123")
                        self.assertIsNone(conflict2)
                        # Different content with same key -> conflict
                        h2 = im.build_request_hash("different ques", "CHINA", "Markdown", "default", [], None)
                        _, conflict3 = im.check_idempotency(key, h2)
                        self.assertIsNotNone(conflict3)
                    finally:
                        im.WORK_DIR_ROOT = orig_root

    def test_request_hash_includes_file_hashes(self):
        import app.services.idempotency as im

        h1 = im.build_request_hash("q", "CHINA", "Markdown", "default", ["a.txt:abc"], None)
        h2 = im.build_request_hash("q", "CHINA", "Markdown", "default", ["a.txt:def"], None)
        self.assertNotEqual(h1, h2)


class TestSingleTaskStatus(unittest.TestCase):
    def test_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(common_utils, "WORK_DIR_ROOT", tmp):
                with self.assertRaises(FileNotFoundError):
                    agent_operations.get_single_task_status("20250101-000000-abc123")

    def test_completed_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_id = "20250101-000000-abc123"
            work_dir = os.path.join(tmp, task_id)
            os.makedirs(work_dir, exist_ok=True)
            # Minimal task_status
            with open(os.path.join(work_dir, "task_status.json"), "w", encoding="utf-8") as f:
                json.dump({"task_id": task_id, "status": "completed", "message": "ok", "updated_at": "2026-09-03T00:00:00"}, f)
            with mock.patch.object(common_utils, "WORK_DIR_ROOT", tmp):
                # Also patch get_work_dir to use tmp
                with mock.patch("app.services.agent_operations.get_work_dir", return_value=work_dir):
                    with mock.patch("app.services.agent_operations.read_task_status", return_value={"task_id": task_id, "status": "completed", "message": "ok", "updated_at": "2026-09-03T00:00:00"}):
                        # Need to mock get_work_dir for internal calls
                        status = agent_operations.get_single_task_status(task_id)
                        self.assertEqual(status["task_id"], task_id)
                        self.assertEqual(status["task_status"], "completed")
                        self.assertIn("artifacts", status["allowed_actions"])


class TestEventsCursor(unittest.TestCase):
    def test_events_pagination(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_id = "20250101-000000-abc123"
            work_dir = os.path.join(tmp, task_id)
            os.makedirs(work_dir, exist_ok=True)
            # Use actual logs/messages path (relative to cwd)
            os.makedirs("logs/messages", exist_ok=True)
            msg_path = os.path.join("logs/messages", f"{task_id}.json")
            try:
                with open(msg_path, "w", encoding="utf-8") as f:
                    json.dump([{"id": f"msg-{i}", "content": f"c{i}"} for i in range(5)], f)
                with mock.patch.object(common_utils, "WORK_DIR_ROOT", tmp):
                    with mock.patch("app.services.agent_operations.get_work_dir", return_value=work_dir):
                        ev = agent_operations.get_task_events(task_id, after=None, limit=2)
                        self.assertEqual(len(ev["events"]), 2)
                        self.assertEqual(ev["next_after"], "1")
                        self.assertTrue(ev["has_more"])
                        ev2 = agent_operations.get_task_events(task_id, after="1", limit=2)
                        self.assertEqual(ev2["events"][0]["seq"], 2)
            finally:
                if os.path.exists(msg_path):
                    os.remove(msg_path)


class TestTaskBudget(unittest.TestCase):
    def test_budget_persists_and_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_id = "20250101-000000-abc123"
            work_dir = os.path.join(tmp, task_id)
            os.makedirs(work_dir, exist_ok=True)
            data = task_budget.init_budget(work_dir, task_id)
            self.assertIn("limits", data)
            allowed, _ = task_budget.check_budget_before_call(work_dir, task_id)
            self.assertTrue(allowed)
            # Exhaust calls
            for _ in range(data["limits"]["max_provider_calls"]):
                task_budget.record_provider_call(work_dir, task_id, known_tokens=10)
            allowed2, reason = task_budget.check_budget_before_call(work_dir, task_id)
            self.assertFalse(allowed2)
            self.assertIn("调用上限", reason)


class TestFigurePlan(unittest.TestCase):
    def test_figure_plan_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_id = "20250101-000000-abc123"
            work_dir = os.path.join(tmp, task_id)
            os.makedirs(work_dir, exist_ok=True)
            with mock.patch.object(common_utils, "WORK_DIR_ROOT", tmp):
                with mock.patch("app.services.figure_plan.get_work_dir", return_value=work_dir):
                    plan = figure_plan.create_figure_plan(
                        task_id,
                        [
                            {"id": "fig1", "type": "data_chart", "title": "t", "conclusion": "c", "data_source": "ques1_results.csv", "script": "plot.py", "section": "4.1"},
                            {"id": "fig2", "type": "diagram", "title": "roadmap", "conclusion": "flow", "data_source": "", "script": "", "section": "2"},
                        ],
                    )
                    self.assertEqual(len(plan["figures"]), 2)
                    # Create dummy script and output
                    Path = __import__("pathlib").Path
                    (Path(work_dir) / "plot.py").write_text("print(1)", encoding="utf-8")
                    (Path(work_dir) / "figures").mkdir(exist_ok=True)
                    (Path(work_dir) / "figures" / "fig1.png").write_bytes(b"png")
                    (Path(work_dir) / "figures" / "fig2.png").write_bytes(b"png")
                    # Adjust output paths to match created files
                    plan["figures"][0]["output"] = "plot.py"
                    plan["figures"][0]["script"] = "plot.py"
                    # Validate
                    res = figure_plan.validate_figure_artifacts(task_id)
                    self.assertIn("ok", res)


class TestDoctor(unittest.TestCase):
    def test_container_doctor_shape(self):
        res = container_doctor()
        self.assertIn("python", res)
        self.assertIn("providers", res)
        caps = template_capabilities()
        self.assertIn("backend_profiles", caps)
        self.assertIn("aliases", caps)


class TestPaperReviewPacket(unittest.TestCase):
    def test_assemble_packet_no_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_id = "20250101-000000-abc123"
            work_dir = os.path.join(tmp, task_id)
            os.makedirs(work_dir, exist_ok=True)
            with open(os.path.join(work_dir, "res.md"), "w", encoding="utf-8") as f:
                f.write("# Title\n## 摘要\ncontent")
            with mock.patch.object(common_utils, "WORK_DIR_ROOT", tmp):
                with mock.patch("app.services.paper_review.get_work_dir", return_value=work_dir):
                    pkt = assemble_review_packet(task_id)
                    self.assertEqual(pkt["task_id"], task_id)
                    self.assertIn("paper", pkt)

    def test_save_review_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_id = "20250101-000000-abc123"
            work_dir = os.path.join(tmp, task_id)
            os.makedirs(work_dir, exist_ok=True)
            with open(os.path.join(work_dir, "res.md"), "w", encoding="utf-8") as f:
                f.write("content")
            with mock.patch.object(common_utils, "WORK_DIR_ROOT", tmp):
                with mock.patch("app.services.paper_review.get_work_dir", return_value=work_dir):
                    review = {
                        "reviewer_type": "outer_agent",
                        "manuscript_sha256": "abc",
                        "scores": {"abstract": 8, "assumptions": 7, "modeling": 8, "results": 7, "figures": 6, "format": 7},
                        "findings": [
                            {"category": "model", "severity": "major", "location": "§3.2", "evidence": "method mismatch", "suggested_scope": "model"}
                        ],
                    }
                    p = save_review(task_id, review)
                    self.assertTrue(os.path.isfile(p))


if __name__ == "__main__":
    unittest.main()
