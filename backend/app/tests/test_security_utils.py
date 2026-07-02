"""路径安全工具测试。"""

import os
import tempfile
import unittest
from unittest import mock

from app.utils import common_utils


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


if __name__ == "__main__":
    unittest.main()
