"""Regression tests for bounded Modeler JSON repair."""

import json
import unittest

from app.core.agents.modeler_agent import (
    _apply_acceptance_metric_description_patch,
    _normalize_acceptance_metric_keys,
    repair_json,
)
from app.schemas.A2A import ModelPlan


class ModelerJsonRepairTest(unittest.TestCase):
    def test_repairs_bare_quotes_embedded_in_chinese_prose(self):
        raw = (
            '```json\n{"schema_version":"mathmodel.model-plan.v1",'
            '"method":"滤波后得到"纯"双光束干涉光谱，再计算厚度",'
            '"items":["附件3","附件4"]}\n```'
        )

        repaired = repair_json(raw)

        self.assertIsNotNone(repaired)
        self.assertEqual(
            repaired["method"],
            '滤波后得到"纯"双光束干涉光谱，再计算厚度',
        )
        self.assertEqual(repaired["items"], ["附件3", "附件4"])

    def test_preserves_valid_structural_and_escaped_quotes(self):
        payload = {
            "method": '保留已转义的"术语"',
            "flags": [True, False, None, 3],
            "nested": {"status": "ok"},
        }
        raw = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(repair_json(raw), payload)

    def test_repairs_inner_quote_before_ascii_comma_in_object_prose(self):
        raw = '{"method":"call it "clean", then fit", "status":"ok"}'

        repaired = repair_json(raw)

        self.assertIsNotNone(repaired)
        self.assertEqual(repaired["method"], 'call it "clean", then fit')
        self.assertEqual(repaired["status"], "ok")

    def test_normalizes_human_readable_metric_keys_before_model_plan_validation(self):
        payload = {
            "schema_version": "mathmodel.model-plan.v1",
            "eda": "Verify the resource inputs and feasible region.",
            "subtasks": {
                "ques1": {
                    "inputs": ["machine time", "labor time"],
                    "method": "Solve the linear program and independently verify constraints.",
                    "constraints": ["production is nonnegative"],
                    "expected_artifacts": [
                        {
                            "path": "ques1_results.csv",
                            "kind": "result_table",
                            "description": "Optimal plan and objective value.",
                        }
                    ],
                    "acceptance_metrics": [
                        {
                            "key": "prob_0.50",
                            "label": "Probability threshold",
                            "comparator": "ge",
                            "target": 0.5,
                            "description": "Probability must reach the threshold.",
                        },
                        {
                            "key": "search_range_nA",
                            "label": "Search range",
                            "comparator": "ge",
                            "target": 1,
                            "description": "Record the search range and step size.",
                        },
                    ],
                    "visualization": "Feasible-region chart",
                    "diagnostic_profile": "optimization",
                    "diagnostic_requirements": [],
                }
            },
            "sensitivity_analysis": "Increase machine capacity and compare the objective.",
        }

        _normalize_acceptance_metric_keys(payload)

        keys = [metric["key"] for metric in payload["subtasks"]["ques1"]["acceptance_metrics"]]
        self.assertEqual(keys, ["prob_0_50", "search_range_na"])
        ModelPlan.model_validate(payload)

    def test_targeted_description_patch_preserves_the_rest_of_a_valid_plan(self):
        payload = {
            "schema_version": "mathmodel.model-plan.v1",
            "eda": "Verify inputs.",
            "subtasks": {
                "ques2": {
                    "inputs": ["paired observations"],
                    "method": "Compare paired samples.",
                    "constraints": ["pairs align by index"],
                    "expected_artifacts": [
                        {
                            "path": "ques2_results.csv",
                            "kind": "result_table",
                            "description": "Paired comparison results.",
                        }
                    ],
                    "acceptance_metrics": [
                        {
                            "key": "n_consistency",
                            "label": "样本一致性偏差",
                            "comparator": "eq",
                            "target": 1,
                            "description": "两组样本量一致时记为 1。",
                        },
                        {
                            "key": "result_finite",
                            "label": "结果有限标志",
                            "comparator": "eq",
                            "target": 1,
                            "description": "结果均为有限数值时记为 1。",
                        },
                    ],
                    "visualization": "Paired-sample comparison chart.",
                    "diagnostic_profile": "exact",
                    "diagnostic_requirements": [],
                }
            },
            "sensitivity_analysis": "Compare paired samples after perturbation.",
        }

        patched, errors = _apply_acceptance_metric_description_patch(
            payload,
            {
                "description_updates": [
                    {
                        "subtask": "ques2",
                        "key": "n_consistency",
                        "description": (
                            "n_consistency=1 的目标值依据：题目原文规定样本必须一一对应。"
                        ),
                    }
                ]
            },
        )

        self.assertEqual(errors, [])
        self.assertIsNotNone(patched)
        self.assertEqual(
            payload["subtasks"]["ques2"]["acceptance_metrics"][0]["description"],
            "两组样本量一致时记为 1。",
        )
        self.assertEqual(
            patched["subtasks"]["ques2"]["acceptance_metrics"][0]["description"],
            "n_consistency=1 的目标值依据：题目原文规定样本必须一一对应。",
        )
        self.assertEqual(
            patched["subtasks"]["ques2"]["acceptance_metrics"][1]["description"],
            "结果均为有限数值时记为 1。",
        )
        ModelPlan.model_validate(patched)


if __name__ == "__main__":
    unittest.main()
