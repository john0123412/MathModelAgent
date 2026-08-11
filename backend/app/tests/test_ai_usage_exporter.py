"""Tests for the backend-managed CUMCM AI usage support document."""

import json
import os
import tempfile
import unittest
from unittest import mock

from app.tools.ai_usage_exporter import ensure_ai_usage_details


class TestAiUsageExporter(unittest.TestCase):
    def test_non_cumcm_profile_does_not_create_files(self):
        with tempfile.TemporaryDirectory() as work_dir:
            result = ensure_ai_usage_details(work_dir, export_profile="default")

            self.assertTrue(result["success"])
            self.assertFalse(result["enabled"])
            self.assertEqual(os.listdir(work_dir), [])

    @mock.patch("app.tools.ai_usage_exporter.export_markdown_to_pdf")
    def test_cumcm_profile_writes_managed_details_and_exports_pdf(self, export_pdf):
        export_pdf.return_value = {"success": True, "output": "AI工具使用详情.pdf"}
        with tempfile.TemporaryDirectory() as work_dir:
            for filename in ("task_request.json", "modeler_plan.json", "res.md"):
                with open(os.path.join(work_dir, filename), "w", encoding="utf-8") as handle:
                    handle.write("{}")

            result = ensure_ai_usage_details(work_dir, export_profile="cumcm2026")

            self.assertTrue(result["success"])
            self.assertTrue(result["enabled"])
            with open(
                os.path.join(work_dir, "ai_usage_details.json"), encoding="utf-8"
            ) as handle:
                details = json.load(handle)
            with open(
                os.path.join(work_dir, "AI工具使用详情.md"), encoding="utf-8"
            ) as handle:
                markdown = handle.read()

        self.assertEqual(details["schema_version"], "mathmodel.ai-usage-details.v1")
        self.assertEqual(details["human_review"]["status"], "pending_participant_confirmation")
        self.assertIn("题目拆解", details["tools"][0]["stages"])
        self.assertIn("## 二、AI工具使用记录", markdown)
        self.assertIn("关键交互记录（提示与回复摘要）", markdown)
        self.assertIn("采纳和人工修改情况", markdown)
        self.assertIn("最终建模假设", markdown)
        self.assertNotIn("API密钥或账号凭据正文", markdown)
        export_pdf.assert_called_once()

    @mock.patch("app.tools.ai_usage_exporter.export_markdown_to_pdf")
    def test_existing_verified_contest_rule_is_preserved_in_markdown(self, export_pdf):
        export_pdf.return_value = {"success": True}
        with tempfile.TemporaryDirectory() as work_dir:
            with open(
                os.path.join(work_dir, "ai_usage_details.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    {
                        "tools": [{"name": "MathModelAgent", "stages": ["建模"]}],
                        "contest_rule": {
                            "title": "2026年试行规定",
                            "url": "https://example.invalid/official-rule",
                        },
                    },
                    handle,
                    ensure_ascii=False,
                )

            ensure_ai_usage_details(work_dir, export_profile="cumcm2026")
            with open(
                os.path.join(work_dir, "AI工具使用详情.md"), encoding="utf-8"
            ) as handle:
                markdown = handle.read()

        self.assertIn("适用规定：2026年试行规定", markdown)
        self.assertIn("官方页面：https://example.invalid/official-rule", markdown)


if __name__ == "__main__":
    unittest.main()
