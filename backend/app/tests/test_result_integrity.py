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


if __name__ == "__main__":
    unittest.main()
