"""Tests for the container-only deterministic repair-candidate channel."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import nbformat
from app.core.checkpoint import CheckpointManager, TaskCheckpoint
from app.tools.repair_candidate import RepairCandidateError, run_repair_candidate
from app.tools import repair_candidate_cli
from app.tools.notebook_serializer import NotebookSerializer


class _FakeInterpreter:
    def __init__(self, root: Path, *, delay: float = 0.0):
        self.root = root
        self.delay = delay
        self.cleaned = False

    async def execute_code(self, code: str):
        if self.delay:
            await asyncio.sleep(self.delay)
        namespace = {"__name__": "__main__", "__file__": str(self.root / "candidate.py")}
        previous = os.getcwd()
        os.chdir(self.root)
        try:
            exec(compile(code, str(self.root / "candidate.py"), "exec"), namespace, namespace)
        finally:
            os.chdir(previous)
        return "candidate ok", False, ""

    async def cleanup(self):
        self.cleaned = True


def _prepare(root: Path) -> None:
    manager = CheckpointManager(str(root))
    manager.save(
        TaskCheckpoint(
            task_id="unit-task",
            ques_all="题面",
            comp_template="CHINA",
            format_output="Markdown",
            questions={"ques1": "问题一"},
            ques_count=1,
            modeler_response={"questions_solution": {"ques1": "修复数组计算"}},
            updated_at="2026-07-22T00:00:00",
        )
    )
    manager.record_quality_review_pending({"review_id": "review-a"})
    manager.request_quality_repair("review-a", ["ques1"], "修复数组错误并重新计算")


def _write_candidate(root: Path, code: str, evidence: dict) -> None:
    (root / "candidate.py").write_text(code, encoding="utf-8")
    (root / "evidence.json").write_text(json.dumps(evidence), encoding="utf-8")


def _write_expected_artifacts(root: Path, subtask_id: str, *paths: str) -> None:
    (root / "modeler_plan.json").write_text(
        json.dumps(
            {
                "model_plan": {
                    "subtasks": {
                        subtask_id: {
                            "expected_artifacts": [
                                {"path": path} for path in paths
                            ]
                        }
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _evidence() -> dict:
    return {
        "subtask_id": "ques1",
        "constraints": [
            {
                "id": "result_nonnegative",
                "actual": 42,
                "comparison": "gte",
                "target": 0,
                "source_path": "ques1_results.csv",
            }
        ],
        "metrics": [
            {
                "id": "result",
                "label": "结果",
                "value": 42,
                "unit": "",
                "explanation": "由候选脚本重新计算。",
                "source_path": "ques1_results.csv",
            }
        ],
        "figures": [],
    }


class TestRepairCandidate(unittest.TestCase):
    def test_cli_rejects_host_execution(self):
        with patch("app.tools.repair_candidate_cli.Path.is_file", return_value=False):
            self.assertEqual(repair_candidate_cli.main([]), 2)

    def test_candidate_receives_standard_script_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare(root)
            _write_candidate(
                root,
                "import sys\n"
                "from pathlib import Path\n"
                "assert __name__ == '__main__'\n"
                "assert Path(__file__).name == 'candidate.py'\n"
                "assert sys.argv == [__file__]\n"
                "Path('ques1_results.csv').write_text('value\\n42\\n', encoding='utf-8')",
                _evidence(),
            )

            async def factory(**kwargs):
                return _FakeInterpreter(root)

            with patch("app.tools.repair_candidate.get_work_dir", return_value=str(root)):
                result = asyncio.run(
                    run_repair_candidate(
                        "unit-task", "ques1", "review-a", "candidate.py", "evidence.json",
                        interpreter_factory=factory,
                    )
                )

            self.assertEqual(result["status"], "evidence_passed")

    def test_candidate_can_take_over_persisted_full_validation_repair(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare(root)
            manager = CheckpointManager(str(root))
            manager.load()
            manager.record_validation_failure(
                ["ques1"],
                {"status": "FAIL", "checks": [{"id": "ques1.required_diagnostic"}]},
            )
            _write_candidate(
                root,
                "from pathlib import Path\nPath('ques1_results.csv').write_text('value\\n42\\n', encoding='utf-8')",
                _evidence(),
            )

            async def factory(**kwargs):
                return _FakeInterpreter(root)

            with patch("app.tools.repair_candidate.get_work_dir", return_value=str(root)):
                result = asyncio.run(
                    run_repair_candidate(
                        "unit-task", "ques1", "review-a", "candidate.py", "evidence.json",
                        interpreter_factory=factory,
                    )
                )

            self.assertEqual(result["status"], "evidence_passed")
            checkpoint = CheckpointManager(str(root)).load()
            self.assertEqual(checkpoint.workflow_state, "repairing")
            self.assertTrue(checkpoint.solution_coder_responses["ques1"]["execution_succeeded"])

    def test_candidate_executes_records_evidence_and_marks_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare(root)
            _write_candidate(
                root,
                "from pathlib import Path\nPath('ques1_results.csv').write_text('value\\n42\\n', encoding='utf-8')",
                _evidence(),
            )
            fake = _FakeInterpreter(root)

            async def factory(**kwargs):
                return fake

            with patch("app.tools.repair_candidate.get_work_dir", return_value=str(root)):
                result = asyncio.run(
                    run_repair_candidate(
                        "unit-task", "ques1", "review-a", "candidate.py", "evidence.json",
                        interpreter_factory=factory,
                    )
                )

            self.assertEqual(result["status"], "evidence_passed")
            self.assertTrue(fake.cleaned)
            manifest = json.loads((root / "execution_validation.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "PASS")
            checkpoint = CheckpointManager(str(root)).load()
            self.assertTrue(checkpoint.solution_coder_responses["ques1"]["execution_succeeded"])
            self.assertTrue((root / "repair_candidate_manifest.json").is_file())
            self.assertFalse((root / "frozen_results.json").exists())

    def test_first_candidate_prepares_clean_source_and_archives_old_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare(root)
            serializer = NotebookSerializer(work_dir=str(root))
            serializer.add_code_cell_to_notebook("stale = 1")
            (root / "variable_snapshot.pkl").write_bytes(b"stale snapshot")
            (root / "variable_snapshot_meta.json").write_text("{}", encoding="utf-8")
            _write_candidate(
                root,
                "from pathlib import Path\n"
                "Path('ques1_results.csv').write_text('value\\n42\\n', encoding='utf-8')",
                _evidence(),
            )

            async def factory(**kwargs):
                return _FakeInterpreter(root)

            with patch("app.tools.repair_candidate.get_work_dir", return_value=str(root)):
                result = asyncio.run(
                    run_repair_candidate(
                        "unit-task", "ques1", "review-a", "candidate.py", "evidence.json",
                        interpreter_factory=factory,
                    )
                )

            self.assertEqual(result["status"], "evidence_passed")
            checkpoint = CheckpointManager(str(root)).load()
            self.assertTrue(checkpoint.quality_repair_source_prepared)
            self.assertFalse((root / "variable_snapshot.pkl").exists())
            self.assertFalse((root / "variable_snapshot_meta.json").exists())
            archived = list((root / "failed_attempts" / "quality_repair").glob("*/notebook.ipynb"))
            self.assertEqual(len(archived), 1)
            self.assertEqual(
                [cell.source for cell in nbformat.read(archived[0], as_version=4).cells],
                ["stale = 1"],
            )
            self.assertTrue(
                any(cell.cell_type == "code" for cell in nbformat.read(root / "notebook.ipynb", as_version=4).cells)
            )

    def test_followup_candidate_appends_to_same_clean_source_chain(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare(root)

            async def factory(**kwargs):
                return _FakeInterpreter(root)

            def run_candidate(value: int):
                evidence = _evidence()
                evidence["metrics"][0]["value"] = value
                evidence["constraints"][0]["actual"] = value
                _write_candidate(
                    root,
                    "from pathlib import Path\n"
                    f"Path('ques1_results.csv').write_text('value\\n{value}\\n', encoding='utf-8')",
                    evidence,
                )
                with patch("app.tools.repair_candidate.get_work_dir", return_value=str(root)):
                    return asyncio.run(
                        run_repair_candidate(
                            "unit-task", "ques1", "review-a", "candidate.py", "evidence.json",
                            interpreter_factory=factory,
                        )
                    )

            self.assertEqual(run_candidate(42)["status"], "evidence_passed")
            archives_after_first = list(
                (root / "failed_attempts" / "quality_repair").glob("*")
            )
            self.assertEqual(run_candidate(43)["status"], "evidence_passed")
            archives = list((root / "failed_attempts" / "quality_repair").glob("*"))
            self.assertEqual(archives, archives_after_first)
            notebook = nbformat.read(root / "notebook.ipynb", as_version=4)
            self.assertEqual(sum(cell.cell_type == "code" for cell in notebook.cells), 2)

    def test_declared_template_artifact_can_be_updated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare(root)
            _write_expected_artifacts(root, "ques1", "result1.xlsx")
            _write_candidate(
                root,
                "from pathlib import Path\n"
                "Path('result1.xlsx').write_bytes(b'updated template')\n"
                "Path('ques1_results.csv').write_text('value\\n42\\n', encoding='utf-8')",
                _evidence(),
            )

            async def factory(**kwargs):
                return _FakeInterpreter(root)

            with patch("app.tools.repair_candidate.get_work_dir", return_value=str(root)):
                result = asyncio.run(
                    run_repair_candidate(
                        "unit-task", "ques1", "review-a", "candidate.py", "evidence.json",
                        interpreter_factory=factory,
                    )
                )

            self.assertEqual(result["status"], "evidence_passed")
            self.assertEqual((root / "result1.xlsx").read_bytes(), b"updated template")
            self.assertIn("result1.xlsx", result["changed_outputs"])

    def test_undeclared_other_question_artifact_is_rejected_and_rolled_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare(root)
            _write_expected_artifacts(root, "ques1", "result1.xlsx")
            _write_candidate(
                root,
                "from pathlib import Path\n"
                "Path('result2.xlsx').write_bytes(b'wrong question template')\n"
                "Path('ques1_results.csv').write_text('value\\n42\\n', encoding='utf-8')",
                _evidence(),
            )

            async def factory(**kwargs):
                return _FakeInterpreter(root)

            with patch("app.tools.repair_candidate.get_work_dir", return_value=str(root)):
                with self.assertRaisesRegex(RepairCandidateError, "只能更新"):
                    asyncio.run(
                        run_repair_candidate(
                            "unit-task", "ques1", "review-a", "candidate.py", "evidence.json",
                            interpreter_factory=factory,
                        )
                    )

            self.assertFalse((root / "result2.xlsx").exists())
            self.assertFalse((root / "ques1_results.csv").exists())

    def test_undeclared_attachment_is_rejected_even_with_expected_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare(root)
            _write_expected_artifacts(root, "ques1", "result1.xlsx")
            attachment = root / "附件1.csv"
            attachment.write_text("original\n", encoding="utf-8")
            _write_candidate(
                root,
                "from pathlib import Path\n"
                "Path('附件1.csv').write_text('tampered\\n', encoding='utf-8')\n"
                "Path('ques1_results.csv').write_text('value\\n42\\n', encoding='utf-8')",
                _evidence(),
            )

            async def factory(**kwargs):
                return _FakeInterpreter(root)

            with patch("app.tools.repair_candidate.get_work_dir", return_value=str(root)):
                with self.assertRaisesRegex(RepairCandidateError, "只能更新"):
                    asyncio.run(
                        run_repair_candidate(
                            "unit-task", "ques1", "review-a", "candidate.py", "evidence.json",
                            interpreter_factory=factory,
                        )
                    )

            self.assertEqual(attachment.read_text(encoding="utf-8"), "original\n")
            self.assertFalse((root / "ques1_results.csv").exists())

    def test_wrong_review_or_state_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare(root)
            _write_candidate(root, "pass", _evidence())
            with patch("app.tools.repair_candidate.get_work_dir", return_value=str(root)):
                with self.assertRaisesRegex(RepairCandidateError, "review_id"):
                    asyncio.run(
                        run_repair_candidate(
                            "unit-task", "ques1", "wrong", "candidate.py", "evidence.json"
                        )
                    )

    def test_protected_file_mutation_is_rejected_and_restored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare(root)
            original = (root / "checkpoint.json").read_bytes()
            _write_candidate(
                root,
                "from pathlib import Path\nPath('ques1_results.csv').write_text('value\\n42\\n', encoding='utf-8')\nPath('checkpoint.json').write_text('tampered')",
                _evidence(),
            )

            async def factory(**kwargs):
                return _FakeInterpreter(root)

            with patch("app.tools.repair_candidate.get_work_dir", return_value=str(root)):
                with self.assertRaisesRegex(RepairCandidateError, "受保护文件"):
                    asyncio.run(
                        run_repair_candidate(
                            "unit-task", "ques1", "review-a", "candidate.py", "evidence.json",
                            interpreter_factory=factory,
                        )
                    )
            self.assertEqual((root / "checkpoint.json").read_bytes(), original)
            self.assertFalse((root / "execution_validation.json").exists())

    def test_stale_evidence_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare(root)
            (root / "ques1_results.csv").write_text("value\n42\n", encoding="utf-8")
            _write_candidate(root, "pass", _evidence())

            async def factory(**kwargs):
                return _FakeInterpreter(root)

            with patch("app.tools.repair_candidate.get_work_dir", return_value=str(root)):
                with self.assertRaisesRegex(RepairCandidateError, "新生成/更新"):
                    asyncio.run(
                        run_repair_candidate(
                            "unit-task", "ques1", "review-a", "candidate.py", "evidence.json",
                            interpreter_factory=factory,
                        )
                    )

    def test_timeout_does_not_freeze_or_mark_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare(root)
            _write_candidate(root, "pass", _evidence())

            async def factory(**kwargs):
                return _FakeInterpreter(root, delay=0.05)

            with patch("app.tools.repair_candidate.get_work_dir", return_value=str(root)):
                with self.assertRaises(RepairCandidateError):
                    asyncio.run(
                        run_repair_candidate(
                            "unit-task", "ques1", "review-a", "candidate.py", "evidence.json",
                            timeout_seconds=1,
                            interpreter_factory=factory,
                        )
                    )
            self.assertFalse((root / "frozen_results.json").exists())

    def test_failed_candidate_rolls_back_outputs_and_writes_failure_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare(root)
            (root / "ques1_results.csv").write_text("value\n1\n", encoding="utf-8")
            _write_candidate(
                root,
                "from pathlib import Path\n"
                "Path('ques1_results.csv').write_text('value\\n99\\n', encoding='utf-8')\n"
                "Path('ques1_new.csv').write_text('value\\n100\\n', encoding='utf-8')\n"
                "raise RuntimeError('array shape mismatch')",
                _evidence(),
            )

            async def factory(**kwargs):
                return _FakeInterpreter(root)

            with patch("app.tools.repair_candidate.get_work_dir", return_value=str(root)):
                with self.assertRaisesRegex(RepairCandidateError, "候选执行失败"):
                    asyncio.run(
                        run_repair_candidate(
                            "unit-task", "ques1", "review-a", "candidate.py", "evidence.json",
                            interpreter_factory=factory,
                        )
                    )
            self.assertEqual((root / "ques1_results.csv").read_text(encoding="utf-8"), "value\n1\n")
            self.assertFalse((root / "ques1_new.csv").exists())
            audit = json.loads((root / "repair_candidate_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["status"], "candidate_rejected")
            self.assertNotIn("array shape mismatch", audit["error"])

    def test_attachment_tampering_is_rolled_back_on_invalid_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare(root)
            attachment = root / "附件1.csv"
            attachment.write_text("original\n", encoding="utf-8")
            _write_candidate(
                root,
                "from pathlib import Path\n"
                "Path('ques1_results.csv').write_text('value\\n42\\n', encoding='utf-8')\n"
                "Path('附件1.csv').write_text('tampered\\n', encoding='utf-8')",
                _evidence(),
            )

            async def factory(**kwargs):
                return _FakeInterpreter(root)

            with patch("app.tools.repair_candidate.get_work_dir", return_value=str(root)):
                with self.assertRaisesRegex(RepairCandidateError, "只能更新"):
                    asyncio.run(
                        run_repair_candidate(
                            "unit-task", "ques1", "review-a", "candidate.py", "evidence.json",
                            interpreter_factory=factory,
                        )
                    )
            self.assertEqual(attachment.read_text(encoding="utf-8"), "original\n")
            self.assertFalse((root / "ques1_results.csv").exists())
            audit = json.loads((root / "repair_candidate_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["status"], "candidate_rejected")

    def test_evidence_failure_rolls_back_candidate_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare(root)
            bad_evidence = _evidence()
            bad_evidence["metrics"][0]["value"] = 99
            bad_evidence["constraints"][0]["actual"] = 99
            _write_candidate(
                root,
                "from pathlib import Path\nPath('ques1_results.csv').write_text('value\\n42\\n', encoding='utf-8')",
                bad_evidence,
            )

            async def factory(**kwargs):
                return _FakeInterpreter(root)

            with patch("app.tools.repair_candidate.get_work_dir", return_value=str(root)):
                with self.assertRaisesRegex(RepairCandidateError, "证据"):
                    asyncio.run(
                        run_repair_candidate(
                            "unit-task", "ques1", "review-a", "candidate.py", "evidence.json",
                            interpreter_factory=factory,
                        )
                    )
            self.assertFalse((root / "ques1_results.csv").exists())
            audit = json.loads((root / "repair_candidate_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["status"], "candidate_rejected")


if __name__ == "__main__":
    unittest.main()
