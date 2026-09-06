"""Batch-2 tests: paper content revision ledger, cross-artifact sync check.

Covers the v23 incident class: res.md rewritten by hand while res.json still
described the old method, each artifact self-consistent but mutually stale.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.tools.candidate_exporter import write_candidate_manifest
from app.tools.final_acceptance import _check_paper_revision
from app.tools.paper_postprocessor import _check_res_json_sync
from app.tools.paper_revision import (
    bump_paper_revision,
    restamp_res_md,
    verify_paper_revision,
)

_SECTION_A = (
    "问题重述与分析。本文针对算电协同调度问题建立混合整数规划模型，"
    "给出区域负载、功率平衡与储能状态的完整约束体系与求解流程说明。"
)
_SECTION_B = (
    "多目标求解采用碳价加权标量化方法，扫描影子价格获得权衡前沿候选集合，"
    "并以对偶边际定价构造任务迁移的真实边际用电成本。"
)


def _seed_content(root: Path) -> None:
    sections = {
        "ques1": {"response_content": _SECTION_A},
        "ques2": {"response_content": _SECTION_B},
    }
    (root / "res.json").write_text(
        json.dumps(sections, ensure_ascii=False, indent=4), encoding="utf-8"
    )
    (root / "res.md").write_text(
        "# 论文\n\n" + _SECTION_A + "\n\n" + _SECTION_B + "\n", encoding="utf-8"
    )
    (root / "frozen_results.json").write_text('{"metrics": []}', encoding="utf-8")


class PaperRevisionLedgerTest(unittest.TestCase):
    def test_bump_increments_and_records_hashes(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            _seed_content(root)
            first = bump_paper_revision(work_dir, origin="writer_save")
            self.assertEqual(first["revision"], 1)
            self.assertEqual(first["origin"], "writer_save")
            self.assertEqual(
                first["res_md_sha256"],
                hashlib.sha256((root / "res.md").read_bytes()).hexdigest(),
            )
            second = bump_paper_revision(work_dir, origin="paper_repair")
            self.assertEqual(second["revision"], 2)
            self.assertTrue(verify_paper_revision(work_dir)["ok"])

    def test_unknown_origin_rejected(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with self.assertRaises(ValueError):
                bump_paper_revision(work_dir, origin="hand_edit")

    def test_verify_detects_hand_edit_after_save(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            _seed_content(root)
            bump_paper_revision(work_dir, origin="writer_save")
            (root / "res.md").write_text("# 论文\n\n被手改过的正文\n", encoding="utf-8")
            verification = verify_paper_revision(work_dir)
            self.assertFalse(verification["ok"])
            self.assertTrue(any("res.md" in issue for issue in verification["issues"]))

    def test_verify_detects_frozen_change(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            _seed_content(root)
            bump_paper_revision(work_dir, origin="writer_save")
            (root / "frozen_results.json").write_text('{"metrics": [1]}', encoding="utf-8")
            self.assertFalse(verify_paper_revision(work_dir)["ok"])

    def test_missing_ledger_is_an_issue_for_existing_content(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            _seed_content(root)
            verification = verify_paper_revision(work_dir)
            self.assertFalse(verification["ok"])
            self.assertTrue(any("paper_revision.json" in i for i in verification["issues"]))


class ResJsonSyncCheckTest(unittest.TestCase):
    def test_in_sync_sections_pass(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            _seed_content(root)
            check = _check_res_json_sync(work_dir, (root / "res.md").read_text(encoding="utf-8"))
            self.assertTrue(check["passed"])
            self.assertEqual(check["desynced_sections"], [])

    def test_hand_edited_markdown_section_is_flagged(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            _seed_content(root)
            # v23 事故形态：正文已改为新表述，res.json 仍是旧分节。
            (root / "res.md").write_text(
                "# 论文\n\n" + _SECTION_A + "\n\n多目标求解改用ε-约束法与线性规划松弛取整修复。旧文本已被替换为完全不同的方法描述段落。\n",
                encoding="utf-8",
            )
            check = _check_res_json_sync(work_dir, (root / "res.md").read_text(encoding="utf-8"))
            self.assertFalse(check["passed"])
            self.assertEqual(check["desynced_sections"], ["ques2"])

    def test_footnote_marker_differences_tolerated(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            _seed_content(root)
            sections = json.loads((root / "res.json").read_text(encoding="utf-8"))
            sections["ques2"]["response_content"] = (
                _SECTION_B + "该结论来自文献[^3]的加权方法。此处补充一段足够长的说明文字以越过阈值。"
            )
            (root / "res.json").write_text(json.dumps(sections, ensure_ascii=False), encoding="utf-8")
            md = (
                "# 论文\n\n" + _SECTION_A + "\n\n"
                + _SECTION_B + "该结论来自文献[^7]的加权方法。此处补充一段足够长的说明文字以越过阈值。\n"
            )
            (root / "res.md").write_text(md, encoding="utf-8")
            check = _check_res_json_sync(work_dir, md)
            self.assertTrue(check["passed"])

    def test_postprocessed_footnote_definitions_and_numeric_markers_tolerated(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            _seed_content(root)
            sections = json.loads((root / "res.json").read_text(encoding="utf-8"))
            sections["ques2"]["response_content"] = (
                _SECTION_B
                + "该结论来自文献[^3]的加权方法。"
                + "{[^3]: 某篇足够长的参考文献条目，用于验证后处理搬移逻辑。}"
            )
            (root / "res.json").write_text(
                json.dumps(sections, ensure_ascii=False), encoding="utf-8"
            )
            md = (
                "# 论文\n\n"
                + _SECTION_A
                + "\n\n"
                + _SECTION_B
                + "该结论来自文献[1]的加权方法。\n\n"
                + "## 参考文献\n\n[1] 某篇足够长的参考文献条目，用于验证后处理搬移逻辑。\n"
            )
            (root / "res.md").write_text(md, encoding="utf-8")
            check = _check_res_json_sync(work_dir, md)
            self.assertTrue(check["passed"], check)

    def test_word_level_editorial_softening_tolerated(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            _seed_content(root)
            # 后处理合法改写：多句章节中个别词软化（完全一致→基本一致类）不应判脱节。
            long_section = (
                "本文针对算电协同调度问题建立混合整数规划模型，给出区域负载与功率平衡的约束体系。"
                "求解流程采用列生成与分支定价结合的策略，保证大规模实例可解。"
                "实验结果表明最优解在全部资源约束下均满足可行性要求。"
                "灵敏度分析进一步验证了影子价格与数值差分的一致性关系。"
            )
            softened = long_section.replace("验证了影子价格", "基本印证了影子价格").replace(
                "保证大规模实例可解", "在很大程度上保证实例可解"
            )
            sections = json.loads((root / "res.json").read_text(encoding="utf-8"))
            sections["ques1"]["response_content"] = long_section
            (root / "res.json").write_text(json.dumps(sections, ensure_ascii=False), encoding="utf-8")
            md = "# 论文\n\n" + softened + "\n\n" + _SECTION_B + "\n"
            (root / "res.md").write_text(md, encoding="utf-8")
            check = _check_res_json_sync(work_dir, md)
            self.assertTrue(check["passed"], check["desynced_sections"])

    def test_restamp_after_legit_postprocess_rewrite(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            _seed_content(root)
            first = bump_paper_revision(work_dir, origin="writer_save")
            (root / "res.md").write_text(
                "# 论文\n\n" + _SECTION_A + "\n\n" + _SECTION_B + "（归一化追加）\n",
                encoding="utf-8",
            )
            self.assertFalse(verify_paper_revision(work_dir)["ok"])
            record = restamp_res_md(work_dir)
            self.assertEqual(record["revision"], first["revision"])
            self.assertTrue(verify_paper_revision(work_dir)["ok"])

    def test_missing_res_json_skips_without_failing(self):
        with tempfile.TemporaryDirectory() as work_dir:
            check = _check_res_json_sync(work_dir, "# 论文\n正文\n")
            self.assertTrue(check["passed"])
            self.assertTrue(check["skipped"])

    def test_unparseable_res_json_fails(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            (root / "res.json").write_text("{not json", encoding="utf-8")
            check = _check_res_json_sync(work_dir, "# 论文\n正文\n")
            self.assertFalse(check["passed"])


class FinalAcceptanceRevisionBindingTest(unittest.TestCase):
    def test_missing_ledger_is_warning_not_error(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            _seed_content(root)
            check = _check_paper_revision(work_dir)
            self.assertTrue(check["passed"])
            self.assertEqual(check["severity"], "warning")

    def test_drift_after_save_is_error(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            _seed_content(root)
            bump_paper_revision(work_dir, origin="writer_save")
            (root / "res.md").write_text("改过的正文", encoding="utf-8")
            check = _check_paper_revision(work_dir)
            self.assertFalse(check["passed"])
            self.assertEqual(check["severity"], "error")

    def test_manifest_revision_mismatch_is_error(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            _seed_content(root)
            bump_paper_revision(work_dir, origin="writer_save")
            manifest_path = root / "candidate_manifest.json"
            manifest_path.write_text(
                json.dumps({"paper_revision": {"revision": 99}}), encoding="utf-8"
            )
            check = _check_paper_revision(work_dir)
            self.assertFalse(check["passed"])
            self.assertTrue(any("修订号" in m for m in check["evidence"]["mismatches"]))


class CandidateManifestRevisionTest(unittest.TestCase):
    def test_manifest_records_revision_block(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = Path(work_dir)
            _seed_content(root)
            bump_paper_revision(work_dir, origin="writer_save")
            manifest_path = write_candidate_manifest(work_dir, "task-x")
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            block = manifest["paper_revision"]
            self.assertEqual(block["revision"], 1)
            self.assertTrue(block["consistent"])
            self.assertEqual(manifest["files"]["paper_revision"], "paper_revision.json")


if __name__ == "__main__":
    unittest.main()
