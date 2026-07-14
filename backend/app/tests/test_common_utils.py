"""通用工具函数单元测试。"""

import os
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from app.schemas.enums import ExportProfile
from app.tools.export_profiles import CUMCM2025_DOCX_REFERENCE
from app.utils.common_utils import md_2_docx, split_footnotes


class TestCommonUtils(unittest.TestCase):
    """测试 common_utils 模块的核心函数。"""

    def test_split_footnotes(self):
        """测试脚注分离功能。

        split_footnotes 只剥离末尾的脚注定义块（"\\n[^1]: ..."），
        正文中的行内引用标记（如 "[^1]"）应保留 —— 这与 app/core/llm/llm.py
        中的实际用法一致：流式展示时先隐藏脚注定义原文，但仍保留引用标记。
        """
        text = "Example[^1]\n\n[^1]: Footnote content"
        main, notes = split_footnotes(text)
        self.assertEqual(main, "Example[^1]")
        self.assertEqual(notes, [("1", "Footnote content")])


class TestMd2DocxExportProfile(unittest.TestCase):
    """验证 md_2_docx 按 export_profile 决定是否附加 --reference-doc。

    新增能力，不应影响默认 profile 的既有行为（无 --reference-doc）。
    """

    def _make_work_dir_with_md(self, tmp_dir, task_id):
        task_dir = os.path.join(tmp_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)
        with open(os.path.join(task_dir, "res.md"), "w", encoding="utf-8") as f:
            f.write("# demo\n\n正文。")
        return task_dir

    def test_default_profile_has_no_reference_doc(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_dir = self._make_work_dir_with_md(tmp_dir, "task-default")
            with (
                mock.patch(
                    "app.utils.common_utils.get_work_dir", return_value=task_dir
                ),
                mock.patch("app.utils.common_utils.pypandoc.convert_file") as convert_mock,
            ):
                convert_mock.side_effect = lambda **kwargs: Path(
                    kwargs["outputfile"]
                ).write_bytes(b"docx")
                md_2_docx("task-default", export_profile=ExportProfile.DEFAULT)

        extra_args = convert_mock.call_args.kwargs["extra_args"]
        self.assertEqual(
            convert_mock.call_args.kwargs["format"],
            "markdown+tex_math_dollars+tex_math_single_backslash",
        )
        self.assertNotIn("--reference-doc", extra_args)

    def test_cumcm2025_profile_adds_reference_doc_when_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_dir = self._make_work_dir_with_md(tmp_dir, "task-cumcm2025")
            with (
                mock.patch(
                    "app.utils.common_utils.get_work_dir", return_value=task_dir
                ),
                mock.patch("app.utils.common_utils.pypandoc.convert_file") as convert_mock,
            ):
                convert_mock.side_effect = lambda **kwargs: Path(
                    kwargs["outputfile"]
                ).write_bytes(b"docx")
                md_2_docx("task-cumcm2025", export_profile=ExportProfile.CUMCM2025)

        extra_args = convert_mock.call_args.kwargs["extra_args"]
        self.assertIn("--reference-doc", extra_args)
        ref_index = extra_args.index("--reference-doc")
        self.assertEqual(extra_args[ref_index + 1], CUMCM2025_DOCX_REFERENCE)
        # 转换出的 format2025 参考文档应确实存在于仓库中（不是空配置）。
        self.assertTrue(os.path.exists(CUMCM2025_DOCX_REFERENCE))


    def test_failed_reexport_removes_stale_docx_and_writes_status(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_dir = self._make_work_dir_with_md(tmp_dir, "task-fail")
            docx_path = os.path.join(task_dir, "res.docx")
            with open(docx_path, "wb") as handle:
                handle.write(b"stale")
            with (
                mock.patch("app.utils.common_utils.get_work_dir", return_value=task_dir),
                mock.patch(
                    "app.utils.common_utils.pypandoc.convert_file",
                    side_effect=RuntimeError("pandoc failed"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "pandoc failed"):
                    md_2_docx("task-fail", export_profile=ExportProfile.DEFAULT)

            self.assertFalse(os.path.exists(docx_path))
            with open(
                os.path.join(task_dir, "docx_export_status.json"), encoding="utf-8"
            ) as handle:
                status = __import__("json").load(handle)
            self.assertFalse(status["success"])
            self.assertIn("pandoc failed", status["reason"])


if __name__ == "__main__":
    unittest.main()
