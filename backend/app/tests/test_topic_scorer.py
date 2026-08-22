"""Unit tests for topic_scorer tool."""

from __future__ import annotations

import unittest
from app.tools.topic_scorer import score_topics_payload


class TestTopicScorer(unittest.TestCase):
    def setUp(self) -> None:
        self.sample_payload = {
            "contest": "2026 CUMCM Problem Selection",
            "team_profile": {
                "strengths": ["continuous_optimization", "numerical_simulation"],
                "team_fit_blend": {"model_score_weight": 0.75, "team_fit_weight": 0.25},
            },
            "topics": [
                {
                    "name": "Problem A (Microstructure Optimization)",
                    "team_fit_score": 4.5,
                    "scores": {
                        "feasibility": 4.5,
                        "data_or_parameter_access": 4.0,
                        "differentiation": 4.5,
                        "validation_strength": 4.5,
                        "method_fit": 4.5,
                        "narrative_power": 4.0,
                        "risk_control": 4.0,
                    },
                    "evidence": "3D geometric broadphase simulation validated with Wilson 95% CI.",
                    "flip_condition": "If 27-image MIC solver cannot finish within 120s.",
                    "routes": [
                        {
                            "name": "Monte Carlo + Uniform Grid",
                            "main_model": "Wilson 95% CI Percolation Model",
                            "why_chosen": "Avoids heuristic shortcuts, offers verifiable confidence lower bounds",
                            "scores": {
                                "route_problem_fit": 4.5,
                                "engineering_solvability": 4.5,
                                "data_parameter_control": 4.0,
                                "validation_design": 4.5,
                                "route_differentiation": 4.5,
                                "paper_explainability": 4.0,
                                "implementation_cost_control": 4.0,
                                "route_risk_control": 4.0,
                            },
                            "evidence": "27-image periodic boundary conditions implemented.",
                            "flip_condition": "If memory exceeds 4GB during 5000 runs.",
                            "question_chain": [
                                {
                                    "name": "Q1",
                                    "scores": {
                                        "question_deliverable_fit": 4.5,
                                        "question_model_fit": 4.5,
                                        "question_validation_design": 4.5,
                                        "question_engineering_risk": 4.5,
                                        "question_chain_synergy": 4.5,
                                    },
                                },
                                {
                                    "name": "Q2",
                                    "scores": {
                                        "question_deliverable_fit": 4.0,
                                        "question_model_fit": 4.0,
                                        "question_validation_design": 4.0,
                                        "question_engineering_risk": 4.0,
                                        "question_chain_synergy": 4.0,
                                    },
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Problem B (Supply Chain Logistics)",
                    "team_fit_score": 3.0,
                    "scores": {
                        "feasibility": 3.5,
                        "data_or_parameter_access": 3.0,
                        "differentiation": 2.5,
                        "validation_strength": 3.0,
                        "method_fit": 3.5,
                        "narrative_power": 3.0,
                        "risk_control": 3.0,
                    },
                    "routes": [
                        {
                            "name": "Generic Integer Programming",
                            "scores": {
                                "route_problem_fit": 3.5,
                                "engineering_solvability": 3.5,
                                "data_parameter_control": 3.0,
                                "validation_design": 3.0,
                                "route_differentiation": 2.5,
                                "paper_explainability": 3.0,
                                "implementation_cost_control": 3.0,
                                "route_risk_control": 3.0,
                            },
                        }
                    ],
                },
            ],
        }

    def test_score_topics_payload_ranking(self) -> None:
        result = score_topics_payload(self.sample_payload)
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["top_topic"], "Problem A (Microstructure Optimization)")
        self.assertTrue(result["team_fit_applied"])
        self.assertIn("Problem A", result["markdown_report"])
        self.assertIn("Score Gap Note", result["markdown_report"])

    def test_invalid_payload(self) -> None:
        with self.assertRaises(ValueError):
            score_topics_payload({"topics": []})

        # 缺少必要评分字段 -> 确定性抛错
        with self.assertRaises(ValueError):
            score_topics_payload({"topics": [{"name": "A", "scores": {"feasibility": 4.0}}]})

        # 包含未知评分字段 -> 确定性抛错
        full_scores_with_extra = dict(self.sample_payload["topics"][0]["scores"])
        full_scores_with_extra["unknown_criterion"] = 4.0
        with self.assertRaises(ValueError):
            score_topics_payload({"topics": [{"name": "A", "scores": full_scores_with_extra}]})

        # 分值越界 (> 5.0) -> 确定性抛错
        full_scores_out_of_bounds = dict(self.sample_payload["topics"][0]["scores"])
        full_scores_out_of_bounds["feasibility"] = 6.0
        with self.assertRaises(ValueError):
            score_topics_payload({"topics": [{"name": "A", "scores": full_scores_out_of_bounds}]})

        # 非有限数分数 (NaN / Infinity) 必须确定性报错
        full_scores_nan = dict(self.sample_payload["topics"][0]["scores"])
        full_scores_nan["feasibility"] = float("nan")
        with self.assertRaises(ValueError):
            score_topics_payload({"topics": [{"name": "A", "scores": full_scores_nan}]})

        full_scores_inf = dict(self.sample_payload["topics"][0]["scores"])
        full_scores_inf["feasibility"] = float("inf")
        with self.assertRaises(ValueError):
            score_topics_payload({"topics": [{"name": "A", "scores": full_scores_inf}]})

        # 非有限数权重 必须报错
        with self.assertRaises(ValueError):
            score_topics_payload({
                "topics": self.sample_payload["topics"],
                "blend": {"topic_weight": float("nan"), "route_weight": 0.5},
            })

    def test_evidence_and_flip_condition_preservation(self) -> None:
        """验证 evidence 与 flip_condition 在最终报告及输出中完整保留。"""
        result = score_topics_payload(self.sample_payload)
        ranked = result["ranked_topics"]
        top = ranked[0]
        self.assertEqual(top["evidence"], "3D geometric broadphase simulation validated with Wilson 95% CI.")
        self.assertEqual(top["flip_condition"], "If 27-image MIC solver cannot finish within 120s.")
        self.assertIn("3D geometric broadphase", result["markdown_report"])
        self.assertIn("If 27-image MIC solver", result["markdown_report"])


if __name__ == "__main__":
    unittest.main()
