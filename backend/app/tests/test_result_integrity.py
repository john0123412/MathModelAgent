"""Regression tests for the frozen-result writer hand-off.

The fixture mirrors the failed high-pressure fuel-pipe task: an infeasible
third subproblem was described as a genetic/Pareto optimum and paired with an
unrelated blockchain citation.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest

from app.core.flows import Flows
from app.tools.paper_postprocessor import build_preflight_report, build_result_fact_summary


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _FakeInterpreter:
    def __init__(self, work_dir: str) -> None:
        self.work_dir = work_dir

    def get_code_output(self, _section: str) -> str:
        return "grid search found mean pressure 66.08 MPa"


def _write_failed_task_freeze(work_dir: str) -> None:
    source_path = os.path.join(work_dir, "result_summary.txt")
    with open(source_path, "w", encoding="utf-8") as handle:
        handle.write("problem3 mean pressure=66.08 MPa\n")
    with open(os.path.join(work_dir, "notebook.ipynb"), "w", encoding="utf-8") as handle:
        json.dump({"cells": [{"cell_type": "code", "source": "# grid search only\n"}]}, handle)
    with open(os.path.join(work_dir, "p3.png"), "wb") as handle:
        handle.write(b"not a rendered image; existence is sufficient for this text test")

    freeze = {
        "schema": "mathmodel.result-freeze",
        "version": 1,
        "metrics": [
            {
                "id": "p3_mean_pressure",
                "label": "平均压力",
                "aliases": ["压力均值"],
                "value": 66.08,
                "unit": "MPa",
                "explanation": "问题三稳态窗口的平均高压油管压力",
            },
            {
                "id": "p3_cam_speed",
                "label": "凸轮角速度",
                "value": 80.0,
                "unit": "rad/s",
                "explanation": "问题三当前可执行方案的供油凸轮角速度",
            },
        ],
        "sources": [
            {
                "relative_path": "result_summary.txt",
                "sha256": _sha256(source_path),
                "role": "evidence",
            }
        ],
        "subtasks": [{"id": "ques3", "feasible": False}],
        "figures": [{"path": "p3.png", "metric_ids": ["p3_mean_pressure"]}],
    }
    with open(os.path.join(work_dir, "frozen_results.json"), "w", encoding="utf-8") as handle:
        json.dump(freeze, handle, ensure_ascii=False)


class ResultIntegrityTests(unittest.TestCase):
    def test_frozen_results_are_the_only_writer_number_source(self) -> None:
        with tempfile.TemporaryDirectory() as work_dir:
            _write_failed_task_freeze(work_dir)
            summary = build_result_fact_summary(work_dir)
            self.assertIn("唯一数值来源", summary)
            self.assertIn("66.08 MPa", summary)

            flows = Flows(
                {"ques_count": 1, "background": "高压油管压力控制。", "ques1": "求控制方案。"}
            )
            prompt = flows.get_writer_prompt(
                "ques1",
                "code says pressure 100.00 MPa",
                _FakeInterpreter(work_dir),
                {"eda": "EDA", "ques1": "正文", "sensitivity_analysis": "敏感性"},
            )
            self.assertIn("66.08 MPa", prompt)
            self.assertIn("[冻结数值]", prompt)
            self.assertNotIn("100.00 MPa", prompt)

    def test_failed_high_pressure_pattern_is_rejected_by_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as work_dir:
            _write_failed_task_freeze(work_dir)
            markdown = (
                "# 高压油管的压力控制方法研究\n\n"
                "## 摘要\n\n"
                "针对高压油管压力控制问题，问题三的平均压力为100.00 MPa，"
                "并确定了最优控制方案。\n\n"
                "关键词：高压油管；喷油；压力控制\n\n"
                "# 一、问题重述\n\n正文。\n\n"
                "# 二、问题分析\n\n正文。\n\n"
                "# 三、模型假设\n\n正文。\n\n"
                "# 四、符号说明\n\n正文。\n\n"
                "# 五、模型的建立与求解\n\n"
                "问题三采用遗传算法构造 Pareto 前沿，得到最优方案，平均压力为100.00 MPa。\n\n"
                "![问题三平均压力](p3.png)\n\n"
                "图中问题三的平均压力为100.00 MPa。\n\n"
                "# 六、模型的分析与检验\n\n正文。\n\n"
                "# 七、模型的评价、改进与推广\n\n正文。\n\n"
                "## 参考文献\n\n"
                "[1] Du Juan. From Buzzword to Biz World: Blockchain and International Business[J]. 2019.\n\n"
                "# 附录\n\n## 附录A 支撑材料文件列表\n\n本论文没有支撑材料。\n\n"
                "## 附录B 源程序代码\n\n```python\nprint('ok')\n```\n"
            )
            report = build_preflight_report(work_dir, markdown, ["notebook.ipynb"])
            checks = report["checks"]

            self.assertTrue(checks["freeze_integrity"]["passed"])
            self.assertFalse(checks["result_consistency"]["passed"])
            self.assertTrue(checks["result_consistency"]["abstract_conflicts"])
            self.assertFalse(checks["infeasible_optimality"]["passed"])
            self.assertFalse(checks["algorithm_evidence"]["passed"])
            self.assertFalse(checks["figure_result_consistency"]["passed"])
            self.assertFalse(checks["reference_relevance"]["passed"])

    def test_check_source_metrics_equivalence_adversarial_cases(self) -> None:
        """测试 _check_source_metrics_equivalence 的全套对抗性用例（严格 fail-closed）。"""
        from app.tools.result_integrity import _check_source_metrics_equivalence

        with tempfile.TemporaryDirectory() as work_dir:
            # 1. 成功宽表 CSV 比对
            csv_path = os.path.join(work_dir, "clean.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("metric_id,value\nobj_val,123.456\n")

            ok, msg = _check_source_metrics_equivalence(
                csv_path, [{"id": "obj_val", "value": 123.456}]
            )
            self.assertTrue(ok, msg)

            # 2. 指标缺失 / 被删除 -> FAIL
            ok_del, msg_del = _check_source_metrics_equivalence(
                csv_path, [{"id": "missing_metric", "value": 10.0}]
            )
            self.assertFalse(ok_del)
            self.assertIn("缺失或无法定位", msg_del)

            # 3. 指标改名 -> FAIL
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("metric_id,value\nrenamed_val,123.456\n")
            ok_ren, msg_ren = _check_source_metrics_equivalence(
                csv_path, [{"id": "obj_val", "value": 123.456}]
            )
            self.assertFalse(ok_ren)
            self.assertIn("缺失或无法定位", msg_ren)

            # 4. 同一 CSV 中出现两行相同 metric_id（一旧一新） -> FAIL
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("metric_id,value\nobj_val,123.456\nobj_val,999.999\n")
            ok_dup, msg_dup = _check_source_metrics_equivalence(
                csv_path, [{"id": "obj_val", "value": 123.456}]
            )
            self.assertFalse(ok_dup)
            self.assertIn("无法唯一定位", msg_dup)

            # 5. NaN / Infinity 异常值 -> FAIL
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("metric_id,value\nobj_val,NaN\n")
            ok_nan, msg_nan = _check_source_metrics_equivalence(
                csv_path, [{"id": "obj_val", "value": 123.456}]
            )
            self.assertFalse(ok_nan)
            self.assertIn("非有限数值", msg_nan)

            # 6. 不支持的格式 -> FAIL
            txt_path = os.path.join(work_dir, "data.unknown")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write("obj_val=123.456")
            ok_fmt, msg_fmt = _check_source_metrics_equivalence(
                txt_path, [{"id": "obj_val", "value": 123.456}]
            )
            self.assertFalse(ok_fmt)
            self.assertIn("unsupported_format", msg_fmt)

            # 7. 长表指标改名但标签不变 -> 严格 FAIL (不得允许标签覆盖冲突的 ID)
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("id,label,value\nrenamed_id,总成本,123.456\n")
            ok_lbl, msg_lbl = _check_source_metrics_equivalence(
                csv_path, [{"id": "target_id", "label": "总成本", "value": 123.456}]
            )
            self.assertFalse(ok_lbl)
            self.assertIn("缺失或无法定位", msg_lbl)

    def test_check_source_metrics_equivalence_nested_json(self) -> None:
        """测试 JSON 数据源递归键值定位与缺失检测。"""
        from app.tools.result_integrity import _check_source_metrics_equivalence

        with tempfile.TemporaryDirectory() as work_dir:
            json_path = os.path.join(work_dir, "nested.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({
                    "subproblem_1": {
                        "optimal_revenue": 4567.89,
                        "parameters": {"speed": 12.5},
                    }
                }, f)

            # 成功递归定位
            ok, msg = _check_source_metrics_equivalence(
                json_path, [{"id": "optimal_revenue", "value": 4567.89}]
            )
            self.assertTrue(ok, msg)

            # 递归完整路径定位
            ok_full, msg_full = _check_source_metrics_equivalence(
                json_path, [{"id": "subproblem_1.parameters.speed", "value": 12.5}]
            )
            self.assertTrue(ok_full, msg_full)

            # 缺失键值 -> FAIL
            ok_miss, msg_miss = _check_source_metrics_equivalence(
                json_path, [{"id": "non_existent_key", "value": 1.0}]
            )
            self.assertFalse(ok_miss)

    def test_refresh_frozen_results_hashes_fail_closed_cases(self) -> None:
        """测试 refresh_frozen_results_hashes 在数据源缺失、路径跨目录冲突及指标不匹配时严格 fail-closed。"""
        from app.tools.result_integrity import refresh_frozen_results_hashes

        with tempfile.TemporaryDirectory() as work_dir:
            freeze_file = os.path.join(work_dir, "frozen_results.json")
            freeze_data = {
                "schema": "mathmodel.result-freeze",
                "version": 1,
                "metrics": [
                    {
                        "id": "m1",
                        "label": "指标1",
                        "value": 100.0,
                        "source_path": "dir_a/data.csv",
                    }
                ],
                "sources": [
                    {
                        "relative_path": "dir_a/data.csv",
                        "sha256": "0" * 64,
                    }
                ],
            }
            with open(freeze_file, "w", encoding="utf-8") as f:
                json.dump(freeze_data, f)

            # 场景 1: 数据源文件缺失 -> fail-closed: has_conflicts=True, updated=False
            res_missing = refresh_frozen_results_hashes(work_dir)
            self.assertTrue(res_missing["active"])
            self.assertFalse(res_missing["updated"])
            self.assertTrue(res_missing["has_conflicts"])
            self.assertTrue(any("缺失或不存在" in c.get("reason", "") for c in res_missing["conflicts"]))

            # 场景 2: 存在同名 basename 但目录不同（dir_b/data.csv） -> 严禁跨目录错误绑定
            os.makedirs(os.path.join(work_dir, "dir_b"), exist_ok=True)
            with open(os.path.join(work_dir, "dir_b", "data.csv"), "w", encoding="utf-8") as f:
                f.write("metric_id,value\nm1,100.0\n")

            res_dir_mismatch = refresh_frozen_results_hashes(work_dir)
            self.assertFalse(res_dir_mismatch["updated"])
            self.assertTrue(res_dir_mismatch["has_conflicts"])

    def test_prepare_paper_markdown_is_strictly_read_only_on_freeze_hash(self) -> None:
        """验证 prepare_paper_markdown 纯只读，绝对不会篡改或覆写 frozen_results.json 中的哈希。"""
        from app.tools.paper_postprocessor import prepare_paper_markdown

        with tempfile.TemporaryDirectory() as work_dir:
            _write_failed_task_freeze(work_dir)
            freeze_path = os.path.join(work_dir, "frozen_results.json")

            with open(freeze_path, "rb") as f:
                initial_freeze_bytes = f.read()

            # 修改数据源文件内容（使得数据源哈希与 frozen_results.json 中记录的不一致）
            source_path = os.path.join(work_dir, "result_summary.txt")
            with open(source_path, "w", encoding="utf-8") as f:
                f.write("problem3 mean pressure=66.080 MPa (reformatted)\n")

            # 创建最简 res.md
            md_path = os.path.join(work_dir, "res.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(
                    "# 题目\n## 摘要\n摘要正文。\n关键词：数学建模；优化模型；灵敏度分析\n"
                    "# 一、问题重述\n正文。\n# 附录\n## 附录B 源程序代码\n```python\nprint('ok')\n```\n"
                )

            # 执行 prepare_paper_markdown
            prepare_paper_markdown(work_dir)

            with open(freeze_path, "rb") as f:
                after_freeze_bytes = f.read()

            # 严格断言：frozen_results.json 字节完全未变！
            self.assertEqual(
                initial_freeze_bytes,
                after_freeze_bytes,
                "prepare_paper_markdown 不得修改 frozen_results.json 任何内容！",
            )


if __name__ == "__main__":
    unittest.main()
