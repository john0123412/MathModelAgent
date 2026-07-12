"""Upload streaming and size-limit regression tests."""

import io
import os
import tempfile
import unittest
from unittest import mock

from fastapi import HTTPException, UploadFile

from app.config.setting import settings
from app.routers.modeling_router import _save_uploaded_file


class TestUploadLimits(unittest.IsolatedAsyncioTestCase):
    async def test_upload_is_streamed_to_disk(self):
        with tempfile.TemporaryDirectory() as work_dir:
            destination = os.path.join(work_dir, "data.csv")
            upload = UploadFile(filename="data.csv", file=io.BytesIO(b"a,b\n1,2\n"))

            size = await _save_uploaded_file(
                upload,
                destination,
                total_uploaded_bytes=0,
            )

            self.assertEqual(size, 8)
            with open(destination, "rb") as saved:
                self.assertEqual(saved.read(), b"a,b\n1,2\n")

    async def test_oversized_upload_is_removed(self):
        with tempfile.TemporaryDirectory() as work_dir, mock.patch.object(
            settings, "MAX_UPLOAD_FILE_SIZE_BYTES", 4
        ):
            destination = os.path.join(work_dir, "data.csv")
            upload = UploadFile(filename="data.csv", file=io.BytesIO(b"12345"))

            with self.assertRaises(HTTPException) as context:
                await _save_uploaded_file(
                    upload,
                    destination,
                    total_uploaded_bytes=0,
                )

            self.assertEqual(context.exception.status_code, 413)
            self.assertFalse(os.path.exists(destination))
