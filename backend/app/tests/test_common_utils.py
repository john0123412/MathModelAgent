"""通用工具函数单元测试。"""

import os
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
import unittest
from unittest import mock

from app.schemas.enums import ExportProfile
from app.tools.export_profiles import CUMCM2025_DOCX_REFERENCE
from app.tools.export_template_override import install_export_template_override
from app.utils.common_utils import (
    _enforce_formal_chinese_docx_layout,
    md_2_docx,
    split_footnotes,
)


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
                mock.patch("app.utils.common_utils._enforce_formal_chinese_docx_layout") as layout_mock,
            ):
                convert_mock.side_effect = lambda **kwargs: Path(
                    kwargs["outputfile"]
                ).write_bytes(b"docx")
                layout_mock.return_value = {"active": True}
                md_2_docx("task-cumcm2025", export_profile=ExportProfile.CUMCM2025)

        extra_args = convert_mock.call_args.kwargs["extra_args"]
        self.assertIn("--reference-doc", extra_args)
        ref_index = extra_args.index("--reference-doc")
        self.assertEqual(extra_args[ref_index + 1], CUMCM2025_DOCX_REFERENCE)
        # 转换出的 format2025 参考文档应确实存在于仓库中（不是空配置）。
        self.assertTrue(os.path.exists(CUMCM2025_DOCX_REFERENCE))
        layout_mock.assert_called_once()

    def test_task_template_override_replaces_profile_reference_doc_and_contract(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_dir = self._make_work_dir_with_md(tmp_dir, "task-template")
            source_docx = os.path.join(tmp_dir, "official.docx")
            with zipfile.ZipFile(source_docx, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types/>")
                archive.writestr(
                    "word/document.xml",
                    "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'/>",
                )
            contract_path = os.path.join(tmp_dir, "contract.json")
            with open(contract_path, "w", encoding="utf-8") as handle:
                __import__("json").dump(
                    {
                        "docx": {
                            "body_font_east_asia": "KaiTi",
                            "body_font_size_half_points": 22,
                        }
                    },
                    handle,
                )
            install_export_template_override(
                task_dir,
                "cumcm2026",
                docx_template_path=source_docx,
                format_contract_path=contract_path,
            )
            with (
                mock.patch("app.utils.common_utils.get_work_dir", return_value=task_dir),
                mock.patch("app.utils.common_utils.pypandoc.convert_file") as convert_mock,
                mock.patch("app.utils.common_utils._enforce_formal_chinese_docx_layout") as layout_mock,
            ):
                convert_mock.side_effect = lambda **kwargs: Path(
                    kwargs["outputfile"]
                ).write_bytes(b"docx")
                layout_mock.return_value = {"active": True}
                md_2_docx("task-template", export_profile=ExportProfile.CUMCM2026)

        extra_args = convert_mock.call_args.kwargs["extra_args"]
        ref_index = extra_args.index("--reference-doc")
        self.assertTrue(extra_args[ref_index + 1].endswith("cumcm2026_reference.docx"))
        effective_contract = layout_mock.call_args.args[1]
        self.assertEqual(effective_contract["body_font_east_asia"], "KaiTi")
        self.assertEqual(effective_contract["body_font_size_half_points"], 22)
        self.assertEqual(effective_contract["body_line_spacing_twips"], 240)


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


class TestFormalDocxLayout(unittest.TestCase):
    def test_layout_enforces_body_font_spacing_and_abstract_page_break(self):
        namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="{namespace}"><w:body>
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>标题</w:t></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="FirstParagraph"/></w:pPr><w:r><w:t>摘要正文</w:t></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>一、问题重述</w:t></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="FirstParagraph"/></w:pPr><w:r><w:t>正文段落</w:t></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>附录C 源程序代码</w:t></w:r></w:p>
  <w:p><w:r><w:t># Cell 1</w:t></w:r></w:p>
  <w:sectPr/>
</w:body></w:document>'''.encode("utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            path = os.path.join(temporary, "res.docx")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", xml)
            contract = _enforce_formal_chinese_docx_layout(path)
            with zipfile.ZipFile(path) as archive:
                document = ET.fromstring(archive.read("word/document.xml"))

        ns = {"w": namespace}
        paragraphs = document.findall(".//w:body/w:p", ns)
        abstract_text = paragraphs[1]
        body_start = paragraphs[2].find("w:pPr", ns)
        body_text = paragraphs[3]
        abstract_properties = abstract_text.find("w:r/w:rPr", ns)
        abstract_fonts = abstract_properties.find("w:rFonts", ns)
        abstract_spacing = abstract_text.find("w:pPr/w:spacing", ns)
        run_properties = body_text.find("w:r/w:rPr", ns)
        fonts = run_properties.find("w:rFonts", ns)
        spacing = body_text.find("w:pPr/w:spacing", ns)
        def attr(node, key):
            return node.get(f"{{{namespace}}}{key}")

        self.assertTrue(contract["body_start_page_break"])
        self.assertEqual(contract["formatted_paragraphs"], 2)
        self.assertIsNotNone(body_start.find("w:pageBreakBefore", ns))
        self.assertEqual(attr(abstract_fonts, "eastAsia"), "SimSun")
        self.assertEqual(attr(abstract_properties.find("w:sz", ns), "val"), "24")
        self.assertEqual(attr(abstract_spacing, "line"), "240")
        self.assertEqual(attr(abstract_spacing, "lineRule"), "auto")
        self.assertEqual(attr(fonts, "eastAsia"), "SimSun")
        self.assertEqual(attr(fonts, "ascii"), "Times New Roman")
        self.assertEqual(attr(fonts, "hAnsi"), "Times New Roman")
        self.assertEqual(attr(fonts, "cs"), "Times New Roman")
        self.assertEqual(attr(run_properties.find("w:sz", ns), "val"), "24")
        self.assertEqual(attr(run_properties.find("w:szCs", ns), "val"), "24")
        self.assertEqual(attr(spacing, "line"), "240")
        self.assertEqual(attr(spacing, "lineRule"), "auto")


if __name__ == "__main__":
    unittest.main()
