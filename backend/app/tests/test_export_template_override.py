"""Regression tests for task-local competition-template overrides."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.tools.export_template_override import (
    MANIFEST_FILENAME,
    TemplateOverrideError,
    MAX_CONTRACT_BYTES,
    MAX_MANIFEST_BYTES,
    get_editorial_policy_override,
    get_pdf_visual_constraints,
    install_export_template_override,
    load_export_template_override,
    merge_pdf_variables,
    validate_pdf_font_overrides,
)


def _write_minimal_docx(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml",
            "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'/>",
        )


class TestExportTemplateOverride(unittest.TestCase):
    def _write_contract(self, root: Path) -> Path:
        path = root / "format.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": "mma.export-format-contract.v1",
                    "label": "人工下载的竞赛格式包 v1",
                    "docx": {
                        "body_font_east_asia": "SimSun",
                        "body_font_size_half_points": 24,
                        "body_line_spacing_twips": 240,
                        "body_line_rule": "auto",
                        "body_start_page_break": True,
                    },
                    "pdf": {
                        "variables": {
                            "CJKmainfont": "SimSun",
                            "geometry": "left=2.5cm,right=2.5cm,top=2.5cm,bottom=2.5cm",
                            "fontsize": "12pt",
                        },
                        "min_content_margin_cm": 2.5,
                    },
                    "preflight": {
                        "min_abstract_paragraphs": 2,
                        "require_references": True,
                        "require_reference_style": True,
                        "body_min_pages": 15,
                        "body_max_pages": 20,
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_install_copies_docx_hashes_contract_and_merges_only_safe_variables(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "task"
            root.mkdir()
            source_docx = Path(temporary) / "official.docx"
            _write_minimal_docx(source_docx)
            contract = self._write_contract(root)

            result = install_export_template_override(
                str(root),
                "cumcm2026",
                docx_template_path=str(source_docx),
                format_contract_path=str(contract),
            )
            loaded = load_export_template_override(str(root), "cumcm2026")

            self.assertEqual(result["status"], "installed")
            self.assertTrue((root / MANIFEST_FILENAME).is_file())
            self.assertTrue(loaded["active"])
            self.assertTrue(Path(loaded["docx_reference_doc"]).is_file())
            self.assertEqual(
                loaded["format_contract"]["preflight"]["body_max_pages"], 20
            )
            self.assertEqual(
                loaded["format_contract"]["preflight"]["body_min_pages"], 15
            )
            self.assertEqual(
                get_editorial_policy_override(str(root), "cumcm2026")[
                    "min_abstract_paragraphs"
                ],
                2,
            )
            self.assertEqual(
                get_pdf_visual_constraints(str(root), "cumcm2026")["body_max_pages"],
                20,
            )
            merged = merge_pdf_variables(
                [
                    "CJKmainfont=Noto Serif CJK SC",
                    "geometry:left=3cm,right=3cm",
                    "fontsize=10.5pt",
                    "header-includes=\\usepackage{listings}",
                ],
                loaded["format_contract"]["pdf"]["variables"],
            )
            self.assertIn("CJKmainfont=SimSun", merged)
            self.assertIn("geometry:left=2.5cm,right=2.5cm,top=2.5cm,bottom=2.5cm", merged)
            self.assertIn("fontsize=12pt", merged)
            self.assertIn("header-includes=\\usepackage{listings}", merged)

    def test_tampered_task_template_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "task"
            root.mkdir()
            source_docx = Path(temporary) / "official.docx"
            _write_minimal_docx(source_docx)
            contract = self._write_contract(root)
            install_export_template_override(
                str(root),
                "cumcm2026",
                docx_template_path=str(source_docx),
                format_contract_path=str(contract),
            )
            copied = root / "template_overrides" / "cumcm2026_reference.docx"
            with copied.open("ab") as handle:
                handle.write(b"tamper")

            with self.assertRaisesRegex(TemplateOverrideError, "哈希不匹配"):
                load_export_template_override(str(root), "cumcm2026")

    def test_invalid_contract_rolls_back_new_template_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "task"
            root.mkdir()
            first_docx = Path(temporary) / "first.docx"
            second_docx = Path(temporary) / "second.docx"
            _write_minimal_docx(first_docx)
            _write_minimal_docx(second_docx)
            with zipfile.ZipFile(second_docx, "a") as archive:
                archive.writestr("word/styles.xml", "<styles>new template</styles>")
            first_contract = self._write_contract(root)
            install_export_template_override(
                str(root),
                "cumcm2026",
                docx_template_path=str(first_docx),
                format_contract_path=str(first_contract),
            )
            copied = root / "template_overrides" / "cumcm2026_reference.docx"
            original_bytes = copied.read_bytes()
            invalid_contract = root / "invalid.json"
            invalid_contract.write_text('{"pdf":{"variables":{"geometry":"bad\\\\input"}}}', encoding="utf-8")

            with self.assertRaises(TemplateOverrideError):
                install_export_template_override(
                    str(root),
                    "cumcm2026",
                    docx_template_path=str(second_docx),
                    format_contract_path=str(invalid_contract),
                )

            self.assertEqual(copied.read_bytes(), original_bytes)
            self.assertTrue(load_export_template_override(str(root), "cumcm2026")["active"])

    def test_rejects_unsafe_pdf_tex_injection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "task"
            root.mkdir()
            contract = root / "unsafe.json"
            contract.write_text(
                json.dumps(
                    {
                        "pdf": {
                            "variables": {
                                "geometry": "left=2cm\\input{secret}",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(TemplateOverrideError, "geometry"):
                install_export_template_override(
                    str(root), "cumcm2026", format_contract_path=str(contract)
                )

    def test_rejects_non_docx_template(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "task"
            root.mkdir()
            source = Path(temporary) / "template.doc"
            source.write_bytes(b"legacy")
            with self.assertRaisesRegex(TemplateOverrideError, r"\.docx"):
                install_export_template_override(
                    str(root), "cumcm2026", docx_template_path=str(source)
                )

    def test_rejects_docx_with_external_relationship(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "task"
            root.mkdir()
            source = Path(temporary) / "external.docx"
            _write_minimal_docx(source)
            with zipfile.ZipFile(source, "a") as archive:
                archive.writestr(
                    "word/_rels/document.xml.rels",
                    "<Relationships><Relationship TargetMode='External' Target='https://example.com'/></Relationships>",
                )
            with self.assertRaisesRegex(TemplateOverrideError, "外部关系"):
                install_export_template_override(
                    str(root), "cumcm2026", docx_template_path=str(source)
                )

    def test_manifest_symlink_and_oversized_contract_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "task"
            root.mkdir()
            source_docx = Path(temporary) / "official.docx"
            _write_minimal_docx(source_docx)
            contract = self._write_contract(root)
            install_export_template_override(
                str(root),
                "cumcm2026",
                docx_template_path=str(source_docx),
                format_contract_path=str(contract),
            )
            manifest = root / MANIFEST_FILENAME
            outside = Path(temporary) / "outside-manifest.json"
            outside.write_bytes(manifest.read_bytes())
            manifest.unlink()
            os.symlink(outside, manifest)
            with self.assertRaisesRegex(TemplateOverrideError, "符号链接"):
                load_export_template_override(str(root), "cumcm2026")
            manifest.unlink()

            oversized = root / "oversized.json"
            oversized.write_text("{" + '"pad":"' + ("x" * MAX_CONTRACT_BYTES) + '"}', encoding="utf-8")
            with self.assertRaisesRegex(TemplateOverrideError, "大小上限"):
                install_export_template_override(
                    str(root), "cumcm2026", format_contract_path=str(oversized)
                )

    def test_oversized_manifest_font_injection_and_gate_relaxation_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "task"
            root.mkdir()
            manifest = root / MANIFEST_FILENAME
            manifest.write_text("{" + '"pad":"' + ("x" * MAX_MANIFEST_BYTES) + '"}', encoding="utf-8")
            with self.assertRaisesRegex(TemplateOverrideError, "大小上限"):
                load_export_template_override(str(root), "cumcm2026")
            manifest.unlink()

            unsafe_font = root / "unsafe-font.json"
            unsafe_font.write_text(
                json.dumps({"pdf": {"variables": {"CJKmainfont": "SimSun\\input{bad}"}}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(TemplateOverrideError, "字体名称"):
                install_export_template_override(
                    str(root), "cumcm2026", format_contract_path=str(unsafe_font)
                )
            with self.assertRaisesRegex(TemplateOverrideError, "字体名称"):
                validate_pdf_font_overrides({"CJKmainfont": "SimSun{bad}"})

            official_cap = root / "official-cap.json"
            official_cap.write_text(
                json.dumps({"preflight": {"body_min_pages": 15, "body_max_pages": 30}}),
                encoding="utf-8",
            )
            install_export_template_override(
                str(root), "cumcm2026", format_contract_path=str(official_cap)
            )
            self.assertEqual(
                get_pdf_visual_constraints(str(root), "cumcm2026")["body_max_pages"],
                30,
            )

            legacy_min = root / "legacy-min.json"
            legacy_min.write_text(
                json.dumps({"preflight": {"body_min_pages": 10, "body_max_pages": 30}}),
                encoding="utf-8",
            )
            install_export_template_override(
                str(root), "cumcm2025", format_contract_path=str(legacy_min)
            )
            self.assertEqual(
                get_pdf_visual_constraints(str(root), "cumcm2025")["body_min_pages"],
                10,
            )

            below_strict_floor = root / "below-strict-floor.json"
            below_strict_floor.write_text(
                json.dumps({"preflight": {"body_min_pages": 14, "body_max_pages": 30}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(TemplateOverrideError, "只能保持在内部范围内"):
                install_export_template_override(
                    str(root), "cumcm2026", format_contract_path=str(below_strict_floor)
                )

            relaxed = root / "relaxed.json"
            relaxed.write_text(
                json.dumps({"preflight": {"body_min_pages": 0, "body_max_pages": 31}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(TemplateOverrideError, "只能"):
                install_export_template_override(
                    str(root), "cumcm2026", format_contract_path=str(relaxed)
                )

    def test_duplicate_utf16_relationship_and_macro_member_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "task"
            root.mkdir()

            duplicate = Path(temporary) / "duplicate.docx"
            _write_minimal_docx(duplicate)
            with zipfile.ZipFile(duplicate, "a") as archive:
                archive.writestr(
                    "word/_rels/document.xml.rels",
                    "<Relationships><Relationship TargetMode='External' /></Relationships>",
                )
                archive.writestr("word/_rels/document.xml.rels", "<Relationships/>")
            with self.assertRaisesRegex(TemplateOverrideError, "重复"):
                install_export_template_override(
                    str(root), "cumcm2026", docx_template_path=str(duplicate)
                )

            utf16 = Path(temporary) / "utf16.docx"
            _write_minimal_docx(utf16)
            relationship = "<Relationships><Relationship TargetMode='External' /></Relationships>"
            with zipfile.ZipFile(utf16, "a") as archive:
                archive.writestr("word/_rels/document.xml.rels", relationship.encode("utf-16"))
            with self.assertRaisesRegex(TemplateOverrideError, "外部关系"):
                install_export_template_override(
                    str(root), "cumcm2026", docx_template_path=str(utf16)
                )

            macro = Path(temporary) / "macro.docx"
            _write_minimal_docx(macro)
            with zipfile.ZipFile(macro, "a") as archive:
                archive.writestr("word/vbaProject.bin", b"macro")
            with self.assertRaisesRegex(TemplateOverrideError, "宏"):
                install_export_template_override(
                    str(root), "cumcm2026", docx_template_path=str(macro)
                )


if __name__ == "__main__":
    unittest.main()
