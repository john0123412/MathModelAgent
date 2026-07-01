"""LaTeX sidecar 导出（tex_project_exporter）单元测试。

使用 stdlib unittest + tempfile，不依赖 pytest，不读写 project/work_dir 下的
真实历史任务输出，也不强制要求本机安装 pandoc/latexmk（未安装时自动跳过
需要真实 pandoc 转换的用例）。
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from app.tools.candidate_exporter import write_candidate_manifest
from app.tools.tex_project_exporter import export_markdown_to_latex_project


class TestTexProjectExporterMissingInputs(unittest.TestCase):
    """验证 res.md 或 pandoc 缺失时返回结构化失败结果，而不是抛异常。"""

    def test_missing_md_file_returns_failure(self):
        with tempfile.TemporaryDirectory() as work_dir:
            md_path = os.path.join(work_dir, "res.md")  # 不存在
            result = export_markdown_to_latex_project(md_path, work_dir)

            self.assertFalse(result["enabled"])
            self.assertFalse(result["success"])
            self.assertTrue(result["reason"])

            status_path = os.path.join(work_dir, "tex_export_status.json")
            self.assertTrue(os.path.exists(status_path))
            with open(status_path, "r", encoding="utf-8") as f:
                status = json.load(f)
            self.assertFalse(status["success"])

    def test_missing_pandoc_returns_disabled_without_raising(self):
        with tempfile.TemporaryDirectory() as work_dir:
            md_path = os.path.join(work_dir, "res.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write("# demo\n\n正文内容。")

            with mock.patch(
                "app.tools.tex_project_exporter.shutil.which", return_value=None
            ):
                result = export_markdown_to_latex_project(md_path, work_dir)

            self.assertFalse(result["enabled"])
            self.assertFalse(result["success"])
            self.assertTrue(result["reason"])
            # latex_project 目录不应被创建（pandoc 缺失时应尽早跳过）
            self.assertFalse(os.path.exists(os.path.join(work_dir, "latex_project")))


@unittest.skipUnless(shutil.which("pandoc"), "本机未安装 pandoc，跳过真实转换用例")
class TestTexProjectExporterHappyPath(unittest.TestCase):
    """在 pandoc 存在的正常条件下验证 latex_project/main.tex 被创建。"""

    def test_creates_main_tex_and_imported_body(self):
        real_which = shutil.which

        def which_side_effect(cmd, *args, **kwargs):
            # 保留真实 pandoc 检测，但禁用编译步骤（latexmk/xelatex），
            # 避免测试环境下真实调用 xelatex 编译导致耗时过长。
            if cmd == "pandoc":
                return real_which(cmd)
            return None

        with tempfile.TemporaryDirectory() as work_dir:
            md_path = os.path.join(work_dir, "res.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write("# 标题\n\n这是正文，包含公式 $E=mc^2$。")

            with mock.patch(
                "app.tools.tex_project_exporter.shutil.which",
                side_effect=which_side_effect,
            ):
                result = export_markdown_to_latex_project(md_path, work_dir)

            self.assertTrue(result["enabled"])
            self.assertTrue(result["success"], msg=result)
            self.assertFalse(result["compile_attempted"])

            main_tex_path = os.path.join(work_dir, "latex_project", "main.tex")
            imported_body_path = os.path.join(
                work_dir, "latex_project", "sections", "imported_body.tex"
            )
            self.assertTrue(os.path.exists(main_tex_path))
            self.assertTrue(os.path.exists(imported_body_path))

            with open(main_tex_path, "r", encoding="utf-8") as f:
                main_tex_content = f.read()
            self.assertIn(r"\input{sections/imported_body}", main_tex_content)
            self.assertIn("ctexart", main_tex_content)

            status_path = os.path.join(work_dir, "tex_export_status.json")
            self.assertTrue(os.path.exists(status_path))
            with open(status_path, "r", encoding="utf-8") as f:
                status = json.load(f)
            self.assertTrue(status["success"])


class TestCandidateManifestIncludesTexFields(unittest.TestCase):
    """验证 candidate_manifest.json 中包含 latex_main / tex_export_status 字段。"""

    def test_manifest_contains_latex_fields_when_present(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "res.md"), "w", encoding="utf-8") as f:
                f.write("# demo")

            latex_dir = os.path.join(work_dir, "latex_project")
            os.makedirs(latex_dir, exist_ok=True)
            with open(os.path.join(latex_dir, "main.tex"), "w", encoding="utf-8") as f:
                f.write(r"\documentclass{ctexart}")
            with open(
                os.path.join(work_dir, "tex_export_status.json"), "w", encoding="utf-8"
            ) as f:
                json.dump({"success": True}, f)

            manifest_path = write_candidate_manifest(work_dir, "unittest-task-id")
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            self.assertEqual(manifest["files"]["latex_main"], "latex_project/main.tex")
            self.assertEqual(manifest["files"]["latex_project"], "latex_project")
            self.assertEqual(
                manifest["files"]["tex_export_status"], "tex_export_status.json"
            )
            self.assertIn(
                "LaTeX project is a candidate sidecar export and must be verified before final submission.",
                manifest["known_risks"],
            )

    def test_manifest_fields_none_when_absent(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "res.md"), "w", encoding="utf-8") as f:
                f.write("# demo")

            manifest_path = write_candidate_manifest(work_dir, "unittest-task-id")
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            self.assertIsNone(manifest["files"]["latex_main"])
            self.assertIsNone(manifest["files"]["latex_project"])
            self.assertIsNone(manifest["files"]["tex_export_status"])


if __name__ == "__main__":
    unittest.main()
