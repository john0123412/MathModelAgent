"""API 配置保存语义测试。"""

import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.setting import settings
from app.routers import modeling_router
from app.routers.modeling_router import SaveApiConfigRequest, save_api_config


class TestSaveApiConfig(unittest.IsolatedAsyncioTestCase):
    async def test_save_api_config_returns_runtime_only_metadata(self):
        request = SaveApiConfigRequest(
            coordinator={
                "apiKey": "secret-key",
                "baseUrl": "https://example.test/v1",
                "modelId": "model-a",
                "apiType": "openai-chat",
                "contextWindow": 4096,
            },
            modeler={},
            coder={},
            writer={},
            openalex_email="user@example.test",
        )

        with (
            mock.patch.object(settings, "COORDINATOR_API_KEY", "old-key"),
            mock.patch.object(settings, "COORDINATOR_BASE_URL", ""),
            mock.patch.object(settings, "COORDINATOR_MODEL", ""),
            mock.patch.object(settings, "COORDINATOR_API_TYPE", None),
            mock.patch.object(settings, "COORDINATOR_CONTEXT_WINDOW", 128000),
            mock.patch.object(settings, "OPENALEX_EMAIL", None),
        ):
            result = await save_api_config(request)

            self.assertTrue(result["success"])
            self.assertEqual(result["scope"], "runtime")
            self.assertFalse(result["persisted"])
            self.assertEqual(result["message"], "配置已保存到当前后端进程，重启后需重新配置或写入 .env.dev")
            self.assertNotIn("secret-key", str(result))
            self.assertEqual(settings.COORDINATOR_API_KEY, "secret-key")
            self.assertEqual(settings.COORDINATOR_MODEL, "model-a")
            self.assertEqual(settings.COORDINATOR_CONTEXT_WINDOW, 4096)
            self.assertEqual(settings.OPENALEX_EMAIL, "user@example.test")

    async def test_save_api_config_empty_fields_do_not_clear_existing_values(self):
        request = SaveApiConfigRequest(
            coordinator={
                "apiKey": "",
                "baseUrl": "",
                "modelId": "",
                "apiType": "",
                "contextWindow": "",
            },
            modeler={},
            coder={},
            writer={},
            openalex_email="",
        )

        with (
            mock.patch.object(settings, "COORDINATOR_API_KEY", "old-key"),
            mock.patch.object(settings, "COORDINATOR_BASE_URL", "old-url"),
            mock.patch.object(settings, "COORDINATOR_MODEL", "old-model"),
            mock.patch.object(settings, "COORDINATOR_API_TYPE", "old-type"),
            mock.patch.object(settings, "COORDINATOR_CONTEXT_WINDOW", 8192),
            mock.patch.object(settings, "OPENALEX_EMAIL", "old@example.test"),
        ):
            result = await save_api_config(request)

            self.assertTrue(result["success"])
            self.assertEqual(settings.COORDINATOR_API_KEY, "old-key")
            self.assertEqual(settings.COORDINATOR_BASE_URL, "old-url")
            self.assertEqual(settings.COORDINATOR_MODEL, "old-model")
            self.assertEqual(settings.COORDINATOR_API_TYPE, "old-type")
            self.assertEqual(settings.COORDINATOR_CONTEXT_WINDOW, 8192)
            self.assertEqual(settings.OPENALEX_EMAIL, "old@example.test")


class TestSaveApiConfigHttp(unittest.TestCase):
    def test_save_api_config_http_response_is_runtime_only_and_redacted(self):
        app = FastAPI()
        app.include_router(modeling_router.router)
        client = TestClient(app)

        payload = {
            "coordinator": {
                "apiKey": "secret-key",
                "baseUrl": "https://example.test/v1",
                "modelId": "model-a",
                "apiType": "openai-chat",
                "contextWindow": 4096,
            },
            "modeler": {},
            "coder": {},
            "writer": {},
            "openalex_email": "",
        }

        response = client.post("/save-api-config", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["scope"], "runtime")
        self.assertFalse(data["persisted"])
        self.assertNotIn("secret-key", response.text)


if __name__ == "__main__":
    unittest.main()
