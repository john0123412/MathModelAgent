"""最终结果拼接和任务列表状态测试。"""

import json
import os
import tempfile
import unittest
from unittest import mock

from app.models.user_output import UserOutput
from app.routers import common_router
from app.schemas.A2A import WriterResponse


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


if __name__ == "__main__":
    unittest.main()
