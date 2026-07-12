"""路径安全工具测试。"""

import os
import socket
import tempfile
import unittest
from unittest import mock

from app.config.setting import parse_cors, parse_trusted_hosts
from app.config.setting import settings
from app.routers.ws_router import _is_allowed_websocket_origin
from app.utils import common_utils
from app.utils.security import validate_llm_base_url


class TestSafePathUtils(unittest.TestCase):
    """验证任务目录和文件名校验。"""

    def test_ensure_safe_task_id_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            common_utils.ensure_safe_task_id("../outside")

    def test_ensure_safe_filename_rejects_nested_path(self):
        with self.assertRaises(ValueError):
            common_utils.ensure_safe_filename("nested/file.csv")

    def test_safe_join_work_dir_stays_under_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(common_utils, "WORK_DIR_ROOT", temp_dir):
                path = common_utils.safe_join_work_dir("task-1", "data.csv")

            self.assertEqual(os.path.basename(path), "data.csv")
            self.assertIn("task-1", path)

    def test_create_work_dir_rejects_unsafe_task_id(self):
        with self.assertRaises(ValueError):
            common_utils.create_work_dir("../outside")

    def test_create_task_id_uses_random_hex_suffix(self):
        task_id = common_utils.create_task_id()
        self.assertRegex(task_id, r"^\d{8}-\d{6}-[0-9a-f]{32}$")


class TestNetworkSecurityUtils(unittest.TestCase):
    """验证 CORS 与外部 LLM 端点的默认安全边界。"""

    def test_parse_cors_accepts_explicit_origins(self):
        self.assertEqual(
            parse_cors("http://localhost:5173,http://127.0.0.1:5173"),
            ["http://localhost:5173", "http://127.0.0.1:5173"],
        )

    def test_parse_cors_rejects_wildcard(self):
        with self.assertRaises(ValueError):
            parse_cors("*")

    def test_parse_trusted_hosts_rejects_wildcard(self):
        with self.assertRaises(ValueError):
            parse_trusted_hosts("*")

    def test_llm_base_url_accepts_public_https_endpoint(self):
        self.assertEqual(
            validate_llm_base_url("https://8.8.8.8/v1/"),
            "https://8.8.8.8/v1",
        )

    def test_llm_base_url_rejects_private_endpoint_without_opt_in(self):
        for base_url in (
            "http://127.0.0.1:8000/v1",
            "https://localhost/v1",
            "https://service.internal/v1",
        ):
            with self.subTest(base_url=base_url), self.assertRaises(ValueError):
                validate_llm_base_url(base_url)

    def test_llm_base_url_allows_private_endpoint_with_explicit_opt_in(self):
            self.assertEqual(
            validate_llm_base_url(
                "http://127.0.0.1:8000/v1", allow_private_hosts=True
            ),
                "http://127.0.0.1:8000/v1",
            )

    def test_llm_base_url_rejects_public_name_resolving_to_private_ip(self):
        def private_resolver(*_args, **_kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))]

        with self.assertRaises(ValueError):
            validate_llm_base_url(
                "https://gateway.example.test/v1",
                resolver=private_resolver,
            )

    def test_llm_base_url_rejects_unresolvable_hostname(self):
        def failing_resolver(*_args, **_kwargs):
            raise OSError("no DNS result")

        with self.assertRaises(ValueError):
            validate_llm_base_url(
                "https://gateway.example.test/v1",
                resolver=failing_resolver,
            )

    def test_llm_base_url_retries_transient_dns_failure(self):
        calls = 0

        def flaky_resolver(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("temporary DNS failure")
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

        self.assertEqual(
            validate_llm_base_url(
                "https://gateway.example.test/v1",
                resolver=flaky_resolver,
            ),
            "https://gateway.example.test/v1",
        )
        self.assertEqual(calls, 2)


class TestWebSocketSecurityUtils(unittest.TestCase):
    def test_websocket_origin_must_be_allowlisted(self):
        with mock.patch.object(
            settings,
            "CORS_ALLOW_ORIGINS",
            ["http://localhost:5173"],
        ):
            self.assertTrue(_is_allowed_websocket_origin("http://localhost:5173"))
            self.assertFalse(_is_allowed_websocket_origin("https://untrusted.example"))
            self.assertFalse(_is_allowed_websocket_origin(None))


if __name__ == "__main__":
    unittest.main()
