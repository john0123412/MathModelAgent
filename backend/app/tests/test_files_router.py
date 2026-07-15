"""文件路由测试。"""

import asyncio
import os
import tempfile
import unittest
import zipfile
from unittest import mock

from fastapi import HTTPException

from app.routers import files_router
from app.utils import common_utils


class TestDownloadAllUrl(unittest.TestCase):
    """验证任务工作区压缩包下载链路。"""

    def test_download_all_url_creates_archive_for_safe_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            task_dir = os.path.join(temp_dir, "task-1")
            nested_dir = os.path.join(task_dir, "figures")
            cache_dir = os.path.join(task_dir, "__pycache__")
            os.makedirs(nested_dir, exist_ok=True)
            os.makedirs(cache_dir, exist_ok=True)
            with open(os.path.join(task_dir, "res.md"), "w", encoding="utf-8") as f:
                f.write("# result")
            with open(os.path.join(nested_dir, "plot.png"), "wb") as f:
                f.write(b"png")
            with open(os.path.join(cache_dir, "ignored.pyc"), "wb") as f:
                f.write(b"cache")
            with open(os.path.join(task_dir, "all.zip"), "wb") as f:
                f.write(b"old zip")
            with open(os.path.join(task_dir, "scratch.tmp"), "w", encoding="utf-8") as f:
                f.write("temporary")

            with (
                mock.patch.object(common_utils, "WORK_DIR_ROOT", temp_dir),
                mock.patch.object(
                    files_router.settings, "SERVER_HOST", "http://localhost:9999"
                ),
            ):
                result = asyncio.run(files_router.get_download_all_url("task-1"))

            archive_path = os.path.join(task_dir, "all.zip")
            self.assertEqual(
                result["download_url"], "http://localhost:9999/static/task-1/all.zip"
            )
            self.assertTrue(os.path.isfile(archive_path))
            with zipfile.ZipFile(archive_path) as archive:
                names = sorted(archive.namelist())

        self.assertEqual(names, ["figures/plot.png", "res.md"])

    def test_download_all_url_skips_symlink_to_outside_work_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            outside_path = os.path.join(temp_dir, "outside.txt")
            with open(outside_path, "w", encoding="utf-8") as f:
                f.write("secret")

            task_dir = os.path.join(temp_dir, "task-1")
            os.makedirs(task_dir, exist_ok=True)
            with open(os.path.join(task_dir, "res.md"), "w", encoding="utf-8") as f:
                f.write("# result")
            link_path = os.path.join(task_dir, "leak.txt")
            try:
                os.symlink(outside_path, link_path)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"当前平台不支持创建 symlink: {exc}")

            with mock.patch.object(common_utils, "WORK_DIR_ROOT", temp_dir):
                asyncio.run(files_router.get_download_all_url("task-1"))

            with zipfile.ZipFile(os.path.join(task_dir, "all.zip")) as archive:
                names = sorted(archive.namelist())

        self.assertEqual(names, ["res.md"])

    def test_download_all_url_skips_internal_recovery_candidate_pdf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            task_dir = os.path.join(temp_dir, "task-1")
            os.makedirs(task_dir, exist_ok=True)
            with open(os.path.join(task_dir, "res.pdf"), "wb") as f:
                f.write(b"current pdf")
            with open(
                os.path.join(task_dir, "res_recovery_candidate.pdf"), "wb"
            ) as f:
                f.write(b"stale candidate")

            with mock.patch.object(common_utils, "WORK_DIR_ROOT", temp_dir):
                asyncio.run(files_router.get_download_all_url("task-1"))

            with zipfile.ZipFile(os.path.join(task_dir, "all.zip")) as archive:
                names = sorted(archive.namelist())

        self.assertEqual(names, ["res.pdf"])

    def test_download_all_url_rejects_oversized_single_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            task_dir = os.path.join(temp_dir, "task-1")
            os.makedirs(task_dir, exist_ok=True)
            with open(os.path.join(task_dir, "large.bin"), "wb") as f:
                f.write(b"1234")

            with (
                mock.patch.object(common_utils, "WORK_DIR_ROOT", temp_dir),
                mock.patch.object(files_router, "MAX_ARCHIVE_FILE_SIZE_BYTES", 3),
            ):
                with self.assertRaises(HTTPException) as ctx:
                    asyncio.run(files_router.get_download_all_url("task-1"))

            self.assertEqual(ctx.exception.status_code, 413)
            self.assertFalse(
                any(filename.startswith("all.zip.") for filename in os.listdir(task_dir))
            )

    def test_download_all_url_rejects_oversized_total_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            task_dir = os.path.join(temp_dir, "task-1")
            os.makedirs(task_dir, exist_ok=True)
            with open(os.path.join(task_dir, "a.txt"), "wb") as f:
                f.write(b"1234")
            with open(os.path.join(task_dir, "b.txt"), "wb") as f:
                f.write(b"5678")

            with (
                mock.patch.object(common_utils, "WORK_DIR_ROOT", temp_dir),
                mock.patch.object(files_router, "MAX_ARCHIVE_TOTAL_SIZE_BYTES", 7),
            ):
                with self.assertRaises(HTTPException) as ctx:
                    asyncio.run(files_router.get_download_all_url("task-1"))

            self.assertEqual(ctx.exception.status_code, 413)
            self.assertFalse(
                any(filename.startswith("all.zip.") for filename in os.listdir(task_dir))
            )

    def test_download_all_url_rejects_unsafe_task_id(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(files_router.get_download_all_url("../outside"))

        self.assertEqual(ctx.exception.status_code, 400)

    def test_download_all_url_returns_404_for_missing_task(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(common_utils, "WORK_DIR_ROOT", temp_dir):
                with self.assertRaises(HTTPException) as ctx:
                    asyncio.run(files_router.get_download_all_url("missing-task"))

        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
