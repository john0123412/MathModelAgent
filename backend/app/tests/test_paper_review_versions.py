"""A review cannot be silently rebound to evidence its author never saw."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.paper_review import assemble_review_packet, load_review, save_review


class PaperReviewVersionsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "res.md").write_text("# Paper", encoding="utf-8")
        (self.root / "frozen_results.json").write_text('{"metrics": []}', encoding="utf-8")
        (self.root / "candidate_manifest.json").write_text(
            '{"artifact_set_id": "current-artifacts"}', encoding="utf-8"
        )
        mock = patch("app.services.paper_review.get_work_dir", return_value=str(self.root))
        mock.start()
        self.addCleanup(mock.stop)
        packet = assemble_review_packet("task")
        self.review = {
            "reviewer_type": "outer_agent",
            "findings": [],
            **{key: packet[key] for key in ("manuscript_sha256", "frozen_result_id", "artifact_set_id")},
        }

    def test_current_packet_can_be_saved_and_read_without_staleness(self):
        save_review("task", dict(self.review))
        self.assertFalse(load_review("task")["_stale"])

    def test_wrong_missing_or_empty_versions_do_not_overwrite_existing_review(self):
        path = save_review("task", dict(self.review))
        before = path.read_bytes()
        for key in ("manuscript_sha256", "frozen_result_id", "artifact_set_id"):
            for value in ("stale-version", None, ""):
                with self.subTest(key=key, value=value):
                    review = dict(self.review)
                    if value is None:
                        review.pop(key)
                    else:
                        review[key] = value
                    with self.assertRaises(ValueError):
                        save_review("task", review)
                    self.assertEqual(path.read_bytes(), before)

    def test_deleted_or_changed_evidence_invalidates_review(self):
        save_review("task", dict(self.review))
        for name in ("res.md", "frozen_results.json", "candidate_manifest.json"):
            path = self.root / name
            original = path.read_bytes()
            for changed in (None, b"{}"):
                with self.subTest(name=name, changed=changed):
                    if changed is None:
                        path.unlink()
                    else:
                        path.write_bytes(changed)
                    self.assertTrue(load_review("task")["_stale"])
                    with self.assertRaises(ValueError):
                        save_review("task", dict(self.review))
                    path.write_bytes(original)

    def test_legacy_review_without_all_bindings_is_stale(self):
        review = dict(self.review)
        review.pop("artifact_set_id")
        (self.root / "paper_review.json").write_text(json.dumps(review), encoding="utf-8")
        self.assertTrue(load_review("task")["_stale"])
