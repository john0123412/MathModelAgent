"""Application-level HTTP security regression tests."""

import os
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app.main import app
from app.config.setting import settings
from app.utils import common_utils


class TestApplicationSecurity(unittest.TestCase):
    def test_security_headers_are_present(self):
        with TestClient(app, base_url="http://localhost") as client:
            response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertIn("default-src 'none'", response.headers["content-security-policy"])

    def test_cors_only_allows_configured_local_origin(self):
        headers = {
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        }
        with TestClient(app, base_url="http://localhost") as client:
            allowed = client.options("/status", headers=headers)
            blocked = client.options(
                "/status",
                headers={
                    "Origin": "https://untrusted.example",
                    "Access-Control-Request-Method": "GET",
                },
            )

        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.headers["access-control-allow-origin"], "http://localhost:5173")
        self.assertNotIn("access-control-allow-origin", blocked.headers)

    def test_rejects_oversized_request_before_body_processing(self):
        with mock.patch.object(settings, "MAX_REQUEST_BODY_BYTES", 4):
            with TestClient(app, base_url="http://localhost") as client:
                response = client.post("/", content=b"12345")

        self.assertEqual(response.status_code, 413)

    def test_task_html_is_forced_to_download(self):
        with tempfile.TemporaryDirectory() as work_root:
            task_dir = os.path.join(work_root, "task-1")
            os.makedirs(task_dir)
            with open(os.path.join(task_dir, "untrusted.html"), "w", encoding="utf-8") as f:
                f.write("<script>window.pwned = true</script>")

            with mock.patch.object(common_utils, "WORK_DIR_ROOT", work_root):
                with TestClient(app, base_url="http://localhost") as client:
                    response = client.get("/static/task-1/untrusted.html")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/octet-stream")
        self.assertIn("attachment", response.headers["content-disposition"])

    def test_task_raster_image_is_the_only_inline_artifact_type(self):
        with tempfile.TemporaryDirectory() as work_root:
            task_dir = os.path.join(work_root, "task-1")
            os.makedirs(task_dir)
            with open(os.path.join(task_dir, "chart.png"), "wb") as f:
                f.write(b"png")

            with mock.patch.object(common_utils, "WORK_DIR_ROOT", work_root):
                with TestClient(app, base_url="http://localhost") as client:
                    response = client.get("/static/task-1/chart.png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertNotIn("content-disposition", response.headers)

    def test_rejects_untrusted_host_header(self):
        with TestClient(app, base_url="http://localhost") as client:
            response = client.get("/", headers={"host": "untrusted.example"})

        self.assertEqual(response.status_code, 400)
