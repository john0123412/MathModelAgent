"""P0 收尾补丁验证测试：candidate_exporter / pdf_exporter / files_router 端口。

使用 stdlib unittest + tempfile，不依赖 pytest，不读写 project/work_dir 下的
真实历史任务输出。
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from app.tools.candidate_exporter import write_candidate_manifest
from app.tools.pdf_exporter import export_markdown_to_pdf


class TestCandidateExporter(unittest.TestCase):
    """验证 candidate_manifest.json 的生成内容。"""

    def test_manifest_contains_expected_fields(self):
        with tempfile.TemporaryDirectory() as work_dir:
            # 构造产物文件
            with open(os.path.join(work_dir, "res.md"), "w", encoding="utf-8") as f:
                f.write("# demo")
            with open(os.path.join(work_dir, "res.pdf"), "w", encoding="utf-8") as f:
                f.write("%PDF-1.4 fake")
            with open(os.path.join(work_dir, "modeler_plan.md"), "w", encoding="utf-8") as f:
                f.write("# 建模手方案")
            with open(os.path.join(work_dir, "modeler_plan.json"), "w", encoding="utf-8") as f:
                json.dump({"questions_solution": {"ques1": "demo"}}, f)
            with open(os.path.join(work_dir, "export_status.json"), "w", encoding="utf-8") as f:
                json.dump({"pdf": {"success": True}}, f)
            with open(
                os.path.join(work_dir, "paper_preflight_report.json"),
                "w",
                encoding="utf-8",
            ) as f:
                json.dump({"status": "pass"}, f)
            with open(
                os.path.join(work_dir, "paper_preflight_report.md"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write("# Paper Preflight Report")
            with open(
                os.path.join(work_dir, "pdf_visual_check.json"),
                "w",
                encoding="utf-8",
            ) as f:
                json.dump({"status": "PASS"}, f)
            for filename in ("paper_outline.json", "figure_usage.json"):
                with open(os.path.join(work_dir, filename), "w", encoding="utf-8") as f:
                    json.dump({"status": "PASS"}, f)
            with open(os.path.join(work_dir, "claim_trace.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "status": "PASS",
                        "claims": [
                            {
                                "claim": "最优利润为 2600 元。",
                                "paper_section": "模型的建立与求解",
                                "evidence_type": "code_output",
                                "evidence_id_file": ["problem.py"],
                                "strength": "acceptable",
                                "paper_wording_check": "ok",
                            }
                        ],
                    },
                    f,
                    ensure_ascii=False,
                )
            with open(os.path.join(work_dir, "claim_trace.md"), "w", encoding="utf-8") as f:
                f.write("# Claim Trace")

            # 顶层图片 + 子目录图片 + 应被排除的缓存目录图片
            with open(os.path.join(work_dir, "top.png"), "wb") as f:
                f.write(b"")
            sub_dir = os.path.join(work_dir, "figures")
            os.makedirs(sub_dir, exist_ok=True)
            with open(os.path.join(sub_dir, "nested.jpg"), "wb") as f:
                f.write(b"")
            cache_dir = os.path.join(work_dir, "__pycache__")
            os.makedirs(cache_dir, exist_ok=True)
            with open(os.path.join(cache_dir, "should_be_excluded.png"), "wb") as f:
                f.write(b"")

            manifest_path = write_candidate_manifest(work_dir, "unittest-task-id")
            self.assertTrue(os.path.exists(manifest_path))

            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            self.assertEqual(manifest["files"]["res_md"], "res.md")
            self.assertEqual(manifest["files"]["res_pdf"], "res.pdf")
            self.assertEqual(manifest["files"]["modeler_plan_md"], "modeler_plan.md")
            self.assertEqual(
                manifest["files"]["modeler_plan_json"], "modeler_plan.json"
            )
            self.assertEqual(manifest["files"]["export_status"], "export_status.json")
            self.assertEqual(
                manifest["files"]["paper_preflight_report"],
                "paper_preflight_report.json",
            )
            self.assertEqual(
                manifest["files"]["paper_preflight_report_md"],
                "paper_preflight_report.md",
            )
            self.assertEqual(
                manifest["files"]["pdf_visual_check"],
                "pdf_visual_check.json",
            )
            self.assertEqual(manifest["files"]["paper_outline"], "paper_outline.json")
            self.assertEqual(manifest["files"]["figure_usage"], "figure_usage.json")
            self.assertEqual(manifest["files"]["claim_trace"], "claim_trace.json")
            self.assertEqual(manifest["files"]["claim_trace_md"], "claim_trace.md")
            self.assertIsNone(manifest["files"]["res_docx"])

            figures = manifest["files"]["figures"]
            self.assertIn("top.png", figures)
            self.assertIn("figures/nested.jpg", figures)
            self.assertTrue(
                all("__pycache__" not in fig for fig in figures),
                f"缓存目录图片未被排除: {figures}",
            )

            self.assertEqual(manifest["claims"][0]["claim"], "最优利润为 2600 元。")
            self.assertEqual(manifest["claims"][0]["evidence_type"], "code_output")


class TestPdfExporterMissingTools(unittest.TestCase):
    """验证 pandoc/xelatex 缺失时不抛异常。"""

    def test_missing_md_file_returns_disabled(self):
        with tempfile.TemporaryDirectory() as work_dir:
            md_path = os.path.join(work_dir, "res.md")  # 不存在
            pdf_path = os.path.join(work_dir, "res.pdf")
            result = export_markdown_to_pdf(md_path, pdf_path, work_dir)
            self.assertFalse(result["enabled"])
            self.assertFalse(result["success"])
            self.assertTrue(result["reason"])

    def test_missing_pandoc_returns_disabled(self):
        with tempfile.TemporaryDirectory() as work_dir:
            md_path = os.path.join(work_dir, "res.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write("# demo")
            pdf_path = os.path.join(work_dir, "res.pdf")

            with mock.patch("shutil.which", return_value=None):
                result = export_markdown_to_pdf(md_path, pdf_path, work_dir)

            self.assertFalse(result["enabled"])
            self.assertFalse(result["success"])
            self.assertTrue(result["reason"])


class TestFilesRouterUsesSettingsServerHost(unittest.TestCase):
    """验证 files_router 不再硬编码 8000，而是使用 settings.SERVER_HOST。"""

    def test_source_does_not_hardcode_8000(self):
        import app.routers.files_router as files_router

        source_path = files_router.__file__
        with open(source_path, "r", encoding="utf-8") as f:
            source = f.read()

        self.assertNotIn("localhost:8000", source)
        self.assertIn("settings.SERVER_HOST", source)

    def test_download_url_uses_configured_server_host(self):
        import asyncio

        import app.routers.files_router as files_router
        from app.utils import common_utils

        with tempfile.TemporaryDirectory() as temp_dir:
            task_dir = os.path.join(temp_dir, "t1")
            os.makedirs(task_dir, exist_ok=True)
            with open(os.path.join(task_dir, "res.md"), "w", encoding="utf-8") as f:
                f.write("# demo")

            with (
                mock.patch.object(common_utils, "WORK_DIR_ROOT", temp_dir),
                mock.patch.object(
                    files_router.settings, "SERVER_HOST", "http://localhost:9999"
                ),
            ):
                result = asyncio.run(
                    files_router.get_download_url(task_id="t1", filename="res.md")
                )

        self.assertEqual(
            result["download_url"], "http://localhost:9999/static/t1/res.md"
        )


if __name__ == "__main__":
    unittest.main()
