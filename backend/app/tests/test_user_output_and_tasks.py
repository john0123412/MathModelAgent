"""最终结果拼接和任务列表状态测试。"""

import inspect
import json
import os
import tempfile
import unittest
from unittest import mock

from app.models.user_output import UserOutput
from app.routers import common_router, modeling_router
from app.schemas.A2A import WriterResponse
from app.schemas.enums import ExportProfile
from app.schemas.request import DEFAULT_MODELING_EXPORT_PROFILE, Problem


class TestUserOutputReferences(unittest.TestCase):
    """验证空格分隔引用不会导致未编号脚注。"""

    def test_reference_without_colon_is_numbered(self):
        with tempfile.TemporaryDirectory() as work_dir:
            output = UserOutput(work_dir=work_dir, ques_count=1)
            required_keys = [
                "firstPage",
                "RepeatQues",
                "analysisQues",
                "modelAssumption",
                "symbol",
                "eda",
                "ques1",
                "sensitivity_analysis",
                "judge",
            ]
            for key in required_keys:
                output.set_res(
                    key,
                    WriterResponse(
                        response_content=f"{key} content",
                        footnotes=[],
                    ),
                )

            output.set_res(
                "ques1",
                WriterResponse(
                    response_content="引用测试{[^1] Example reference}",
                    footnotes=[],
                ),
            )

            result = output.get_result_to_save()

        self.assertIn("[^1]", result)
        self.assertIn("[1] Example reference.", result)
        self.assertNotIn("{[^1]", result)

    def test_embedded_reference_section_does_not_swallow_later_sections(self):
        with tempfile.TemporaryDirectory() as work_dir:
            output = UserOutput(work_dir=work_dir, ques_count=1)
            sections = {
                "firstPage": "## 摘要\n\n摘要正文。\n\n关键词：线性规划；生产优化；敏感性分析",
                "RepeatQues": "# 一、问题重述\n\n正文。",
                "analysisQues": "# 二、问题分析\n\n正文。",
                "modelAssumption": "# 三、模型假设\n\n正文。",
                "symbol": (
                    "# 四、符号说明\n\n正文引用{[^1] Example reference}。\n\n"
                    "## 参考文献\n\n[1] Writer 不应在分段中生成的局部参考文献。"
                ),
                "eda": "",
                "ques1": (
                    "# 五、模型的建立与求解\n\n模型正文。\n\n"
                    "[1] Writer 也不应在分段末尾生成裸编号参考文献。"
                ),
                "sensitivity_analysis": "# 六、模型的分析与检验\n\n检验正文。",
                "judge": "# 七、模型的评价、改进与推广\n\n评价正文。",
            }
            for key, content in sections.items():
                output.set_res(key, WriterResponse(response_content=content, footnotes=[]))

            result = output.get_result_to_save()

        self.assertIn("# 五、模型的建立与求解", result)
        self.assertIn("# 六、模型的分析与检验", result)
        self.assertIn("# 七、模型的评价、改进与推广", result)
        self.assertNotIn("Writer 不应在分段中生成的局部参考文献", result)
        self.assertNotIn("Writer 也不应在分段末尾生成裸编号参考文献", result)
        self.assertIn("[1] Example reference.", result)


class TestTaskListStatus(unittest.TestCase):
    """验证失败任务不会被空 res.md 误判为完成。"""

    def test_failed_status_wins_over_empty_result_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            work_root = os.path.join(temp_dir, "work_dir")
            task_id = "task-1"
            task_dir = os.path.join(work_root, task_id)
            os.makedirs(task_dir, exist_ok=True)
            open(os.path.join(task_dir, "res.md"), "w", encoding="utf-8").close()
            with open(os.path.join(task_dir, "checkpoint.json"), "w", encoding="utf-8") as f:
                f.write("{}")
            with open(os.path.join(task_dir, "task_status.json"), "w", encoding="utf-8") as f:
                json.dump({"status": "failed", "message": "'number'"}, f)

            with mock.patch.object(common_router, "WORK_DIR_ROOT", work_root):
                tasks = self._run_async(common_router.list_tasks())

        self.assertEqual(tasks[0]["status"], "failed")
        self.assertFalse(tasks[0]["has_result"])
        self.assertFalse(tasks[0]["files"]["res_md"])

    @staticmethod
    def _run_async(coro):
        import asyncio

        return asyncio.run(coro)


class TestTaskFinalization(unittest.TestCase):
    """验证任务最终收尾会在 DOCX 生成后刷新候选清单。"""

    def test_docx_conversion_refreshes_candidate_manifest(self):
        import app.routers.modeling_router as modeling_router
        from app.tools.candidate_exporter import write_candidate_manifest

        with tempfile.TemporaryDirectory() as temp_dir:
            task_id = "task-1"
            task_dir = os.path.join(temp_dir, task_id)
            os.makedirs(task_dir, exist_ok=True)
            with open(os.path.join(task_dir, "res.md"), "w", encoding="utf-8") as f:
                f.write("# demo")
            write_candidate_manifest(task_dir, task_id)

            def fake_md_2_docx(_task_id, export_profile=None):
                with open(os.path.join(task_dir, "res.docx"), "wb") as f:
                    f.write(b"docx")

            with (
                mock.patch.object(modeling_router, "get_work_dir", return_value=task_dir),
                mock.patch.object(modeling_router, "md_2_docx", side_effect=fake_md_2_docx),
            ):
                modeling_router._finalize_docx_and_manifest(task_id)

            with open(os.path.join(task_dir, "candidate_manifest.json"), encoding="utf-8") as f:
                manifest = json.load(f)

        self.assertEqual(manifest["files"]["res_docx"], "res.docx")


class TestModelingExportProfileDefaults(unittest.TestCase):
    """验证新建建模任务默认使用高教社杯/国赛 2026 profile。"""

    def test_problem_schema_defaults_to_cumcm2026(self):
        problem = Problem(task_id="task-1")

        self.assertEqual(DEFAULT_MODELING_EXPORT_PROFILE, ExportProfile.CUMCM2026)
        self.assertEqual(problem.export_profile, ExportProfile.CUMCM2026)

    def test_modeling_form_default_is_cumcm2026(self):
        signature = inspect.signature(modeling_router.modeling)
        form_default = signature.parameters["export_profile"].default

        self.assertEqual(form_default.default, ExportProfile.CUMCM2026)


if __name__ == "__main__":
    unittest.main()
