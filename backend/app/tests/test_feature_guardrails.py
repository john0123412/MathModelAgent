"""配置型功能守卫测试。"""

import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.setting import settings
from app.routers import common_router
from app.routers.common_router import _feature_guardrail_warnings


class TestFeatureGuardrails(unittest.TestCase):
    def test_rag_enabled_reports_not_wired_warning(self):
        with (
            mock.patch.object(settings, "RAG_ENABLED", True),
            mock.patch.object(settings, "HIL_ENABLED", False),
        ):
            warnings = _feature_guardrail_warnings()

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["feature"], "RAG_ENABLED")
        self.assertEqual(warnings[0]["status"], "config_only")
        self.assertIn("尚未接入主工作流", warnings[0]["message"])

    def test_hil_enabled_points_to_model_gate_alternative(self):
        with (
            mock.patch.object(settings, "RAG_ENABLED", False),
            mock.patch.object(settings, "HIL_ENABLED", True),
        ):
            warnings = _feature_guardrail_warnings()

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["feature"], "HIL_ENABLED")
        self.assertIn("HUMAN_MODEL_GATE_ENABLED", warnings[0]["message"])

    def test_fallback_and_evaluator_extra_flags_report_warnings(self):
        with (
            mock.patch.object(settings, "RAG_ENABLED", False),
            mock.patch.object(settings, "HIL_ENABLED", False),
            mock.patch.object(settings, "FALLBACK_ENABLED", True),
            mock.patch.object(settings, "EVALUATOR_ENABLED", True),
        ):
            warnings = _feature_guardrail_warnings()

        self.assertEqual(
            [warning["feature"] for warning in warnings],
            ["FALLBACK_ENABLED", "EVALUATOR_ENABLED"],
        )

    def test_disabled_config_only_features_do_not_warn(self):
        with (
            mock.patch.object(settings, "RAG_ENABLED", False),
            mock.patch.object(settings, "HIL_ENABLED", False),
            mock.patch.object(settings, "FALLBACK_ENABLED", False),
            mock.patch.object(settings, "EVALUATOR_ENABLED", False),
        ):
            self.assertEqual(_feature_guardrail_warnings(), [])

    def test_status_response_keeps_backend_and_redis_top_level_keys(self):
        app = FastAPI()
        app.include_router(common_router.router)
        client = TestClient(app)

        with (
            mock.patch.object(settings, "RAG_ENABLED", True),
            mock.patch.object(settings, "HIL_ENABLED", False),
            mock.patch.object(settings, "FALLBACK_ENABLED", False),
            mock.patch.object(settings, "EVALUATOR_ENABLED", False),
            mock.patch("app.routers.common_router.redis_manager.get_client") as get_client,
        ):
            redis_client = mock.AsyncMock()
            get_client.return_value = redis_client
            response = client.get("/status")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data.keys()), {"backend", "redis"})
        self.assertIn("feature_warnings", data["backend"])
        self.assertEqual(data["backend"]["feature_warnings"][0]["feature"], "RAG_ENABLED")


if __name__ == "__main__":
    unittest.main()
