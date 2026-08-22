"""Submission audit report tests."""

import hashlib
import json
import os
import tempfile
import unittest
import zipfile

from app.tools.submission_audit import audit_submission, write_submission_audit_report
from app.tools.export_template_override import install_export_template_override


def _write_json(work_dir: str, filename: str, data: dict) -> None:
    with open(os.path.join(work_dir, filename), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _write_preflight(work_dir: str, status: str) -> None:
    _write_json(
        work_dir,
        "paper_preflight_report.json",
        {
            "status": status,
            "source_sha256": _sha256(os.path.join(work_dir, "res.md")),
        },
    )


def _write_minimal_docx(work_dir: str, paragraphs: list[str] | None = None) -> None:
    body = "".join(
        "<w:p><w:r><w:t>" + text + "</w:t></w:r></w:p>"
        for text in (paragraphs or ["正常正文"])
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(os.path.join(work_dir, "res.docx"), "w") as archive:
        archive.writestr("word/document.xml", document)


MINIMAL_VALID_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 595 842]/Parent 2 0 R/Resources<<>>>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n0000000101 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n178\n%%EOF\n"
)


def _write_required_success_files(work_dir: str, font_resolution: list[dict]) -> None:
    for filename in ["res.md", "res.json"]:
        with open(os.path.join(work_dir, filename), "w", encoding="utf-8") as f:
            f.write("ok")
    with open(os.path.join(work_dir, "res.pdf"), "wb") as f:
        f.write(MINIMAL_VALID_PDF)
    _write_minimal_docx(work_dir)
    _write_preflight(work_dir, "PASS")
    _write_json(work_dir, "execution_validation_report.json", {"status": "PASS"})
    _write_json(
        work_dir,
        "cross_modal_audit.json",
        {
            "status": "PASS",
            "passed": True,
            "markdown_sha256": _sha256(os.path.join(work_dir, "res.md")),
        },
    )
    _write_json(
        work_dir,
        "pdf_visual_check.json",
        {
            "status": "PASS",
            "pdf_sha256": _sha256(os.path.join(work_dir, "res.pdf")),
            "scan_scope": "all_pages",
            "pages_checked": 1,
            "page_count": 1,
        },
    )
    _write_json(
        work_dir,
        "export_status.json",
        {
            "pdf": {
                "success": True,
                "font_resolution": font_resolution,
            }
        },
    )


def _write_bound_template_chain(work_dir: str) -> dict:
    source_docx = os.path.join(work_dir, "official.docx")
    with zipfile.ZipFile(source_docx, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml",
            "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'/>",
        )
    contract_path = os.path.join(work_dir, "format.json")
    _write_json(work_dir, "format.json", {"docx": {}})
    installed = install_export_template_override(
        work_dir,
        "cumcm2026",
        docx_template_path=source_docx,
        format_contract_path=contract_path,
    )
    audit = installed["audit"]
    docx_status = {
        "success": True,
        "source_sha256": _sha256(os.path.join(work_dir, "res.md")),
        "output_sha256": _sha256(os.path.join(work_dir, "res.docx")),
        "export_profile": "cumcm2026",
        "template_override": audit,
        "format_contract": {
            "active": True,
            "template_override_format_contract_sha256": audit["format_contract_sha256"],
            "template_override_docx_contract_sha256": audit["docx_contract_sha256"],
        },
    }
    _write_json(work_dir, "docx_export_status.json", docx_status)
    export_status_path = os.path.join(work_dir, "export_status.json")
    with open(export_status_path, encoding="utf-8") as handle:
        export_status = json.load(handle)
    export_status.update(
        {
            "export_profile": "cumcm2026",
            "template_override": audit,
            "pdf": {**export_status["pdf"], "template_override": audit},
        }
    )
    _write_json(work_dir, "export_status.json", export_status)
    preflight_path = os.path.join(work_dir, "paper_preflight_report.json")
    with open(preflight_path, encoding="utf-8") as handle:
        preflight = json.load(handle)
    preflight.update({"export_profile": "cumcm2026", "template_override": audit})
    _write_json(work_dir, "paper_preflight_report.json", preflight)
    visual_path = os.path.join(work_dir, "pdf_visual_check.json")
    with open(visual_path, encoding="utf-8") as handle:
        visual = json.load(handle)
    visual.update({"export_profile": "cumcm2026", "template_override": audit})
    _write_json(work_dir, "pdf_visual_check.json", visual)
    return audit


class TestSubmissionAudit(unittest.TestCase):
    def test_fallback_fonts_warn_for_preview_mode(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [
                    {
                        "variable": "mainfont",
                        "preferred": "Times New Roman",
                        "actual": "Liberation Serif",
                        "fallback": "Liberation Serif",
                        "source": "fallback",
                    }
                ],
            )

            report = audit_submission(work_dir)

        self.assertEqual(report["status"], "WARN")
        font_check = next(item for item in report["checks"] if item["id"] == "pdf_fonts")
        self.assertEqual(font_check["severity"], "warning")
        self.assertIn("MMA_OFFICIAL_FONTS_DIR", font_check["evidence"]["remediation"][0])

    def test_fallback_fonts_fail_when_official_fonts_are_required(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [
                    {
                        "variable": "CJKmainfont",
                        "preferred": "SimSun",
                        "actual": "Noto Serif CJK SC",
                        "fallback": "Noto Serif CJK SC",
                        "source": "fallback",
                    }
                ],
            )

            report = audit_submission(work_dir, require_official_fonts=True)

        self.assertEqual(report["status"], "FAIL")
        font_check = next(item for item in report["checks"] if item["id"] == "pdf_fonts")
        self.assertEqual(font_check["severity"], "error")

    def test_conditional_preflight_warns_instead_of_failing_submission_audit(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [
                    {
                        "variable": "mainfont",
                        "preferred": "Times New Roman",
                        "actual": "Times New Roman",
                        "fallback": "Liberation Serif",
                        "source": "profile",
                    }
                ],
            )
            _write_preflight(work_dir, "CONDITIONAL_PASS")

            report = audit_submission(work_dir)

        self.assertEqual(report["status"], "WARN")
        preflight_check = next(item for item in report["checks"] if item["id"] == "paper_preflight")
        self.assertFalse(preflight_check["passed"])
        self.assertEqual(preflight_check["severity"], "warning")

    def test_failed_preflight_still_fails_submission_audit(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [
                    {
                        "variable": "mainfont",
                        "preferred": "Times New Roman",
                        "actual": "Times New Roman",
                        "fallback": "Liberation Serif",
                        "source": "profile",
                    }
                ],
            )
            _write_preflight(work_dir, "FAIL")

            report = audit_submission(work_dir)

        self.assertEqual(report["status"], "FAIL")
        preflight_check = next(item for item in report["checks"] if item["id"] == "paper_preflight")
        self.assertFalse(preflight_check["passed"])
        self.assertEqual(preflight_check["severity"], "error")

    def test_failed_execution_validation_fails_submission_audit(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [
                    {
                        "variable": "mainfont",
                        "preferred": "Times New Roman",
                        "actual": "Times New Roman",
                        "fallback": "Liberation Serif",
                        "source": "profile",
                    }
                ],
            )
            _write_json(work_dir, "execution_validation_report.json", {"status": "FAIL"})

            report = audit_submission(work_dir)

        self.assertEqual(report["status"], "FAIL")
        check = next(item for item in report["checks"] if item["id"] == "execution_validation")
        self.assertFalse(check["passed"])

    def test_literal_markdown_heading_in_docx_fails_submission_audit(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            _write_minimal_docx(work_dir, ["正常正文", "### 6.1 未渲染标题"])

            report = audit_submission(work_dir)

        check = next(item for item in report["checks"] if item["id"] == "docx_markdown_heading_leakage")
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(check["passed"])
        self.assertIn("### 6.1", check["evidence"]["issues"][0])

    def test_docx_code_appendix_heading_like_source_is_ignored(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            _write_minimal_docx(
                work_dir,
                ["正常正文", "附录 B 源程序代码", "# Cell 1", "### code literal"],
            )

            report = audit_submission(work_dir)

        check = next(item for item in report["checks"] if item["id"] == "docx_markdown_heading_leakage")
        self.assertTrue(check["passed"])


    def test_stale_preflight_hash_fails_submission_audit(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            with open(os.path.join(work_dir, "res.md"), "a", encoding="utf-8") as handle:
                handle.write(" changed")

            report = audit_submission(work_dir)

        check = next(item for item in report["checks"] if item["id"] == "paper_preflight")
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(check["passed"])

    def test_partial_or_stale_pdf_visual_report_fails_submission_audit(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            visual_path = os.path.join(work_dir, "pdf_visual_check.json")
            with open(visual_path, encoding="utf-8") as handle:
                visual = json.load(handle)
            visual["scan_scope"] = "partial_pages"
            _write_json(work_dir, "pdf_visual_check.json", visual)

            report = audit_submission(work_dir)

        check = next(item for item in report["checks"] if item["id"] == "pdf_visual_check")
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(check["passed"])

    def test_official_fonts_pass_and_report_files_are_written(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [
                    {
                        "variable": "mainfont",
                        "preferred": "Times New Roman",
                        "actual": "Times New Roman",
                        "fallback": "Liberation Serif",
                        "source": "profile",
                    }
                ],
            )

            report = write_submission_audit_report(work_dir, require_official_fonts=True)

            self.assertEqual(report["status"], "PASS")
            self.assertTrue(os.path.exists(os.path.join(work_dir, "submission_audit_report.json")))
            self.assertTrue(os.path.exists(os.path.join(work_dir, "submission_audit_report.md")))

    def test_tampered_task_template_override_fails_submission_audit(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            source_docx = os.path.join(work_dir, "official.docx")
            with zipfile.ZipFile(source_docx, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types/>")
                archive.writestr(
                    "word/document.xml",
                    "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'/>",
                )
            contract_path = os.path.join(work_dir, "format.json")
            _write_json(contract_path.rsplit(os.sep, 1)[0], "format.json", {"docx": {}})
            installed = install_export_template_override(
                work_dir,
                "cumcm2026",
                docx_template_path=source_docx,
                format_contract_path=contract_path,
            )
            _write_json(
                work_dir,
                "docx_export_status.json",
                {"export_profile": "cumcm2026", "template_override": installed["audit"]},
            )
            with open(
                os.path.join(work_dir, "template_overrides", "cumcm2026_reference.docx"),
                "ab",
            ) as handle:
                handle.write(b"tamper")

            report = audit_submission(work_dir)

        check = next(item for item in report["checks"] if item["id"] == "template_override_integrity")
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(check["passed"])
        self.assertEqual(check["severity"], "error")

    def test_template_override_must_bind_all_current_export_reports(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            _write_bound_template_chain(work_dir)

            report = audit_submission(work_dir)

        check = next(item for item in report["checks"] if item["id"] == "template_override_integrity")
        self.assertTrue(check["passed"], check["evidence"])

    def test_template_override_rejects_stale_visual_binding(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            _write_bound_template_chain(work_dir)
            visual_path = os.path.join(work_dir, "pdf_visual_check.json")
            with open(visual_path, encoding="utf-8") as handle:
                visual = json.load(handle)
            visual["template_override"] = {"active": False}
            _write_json(work_dir, "pdf_visual_check.json", visual)

            report = audit_submission(work_dir)

        check = next(item for item in report["checks"] if item["id"] == "template_override_integrity")
        self.assertFalse(check["passed"])
        self.assertIn("pdf_visual_check", check["evidence"]["mismatched_records"])

    def test_docx_audit_checks_all_font_slots_and_complex_size(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            xml = (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:pPr><w:spacing w:line=\"240\" w:lineRule=\"auto\"/>"
                "</w:pPr><w:r><w:rPr><w:rFonts w:eastAsia=\"SimSun\" w:ascii=\"Times New Roman\" "
                "w:hAnsi=\"Wrong Font\" w:cs=\"Times New Roman\"/><w:sz w:val=\"24\"/>"
                "<w:szCs w:val=\"24\"/></w:rPr><w:t>正文段落</w:t></w:r></w:p></w:body></w:document>"
            )
            _write_minimal_docx(work_dir, [])
            with zipfile.ZipFile(os.path.join(work_dir, "res.docx"), "w") as archive:
                archive.writestr("word/document.xml", xml)
            _write_json(
                work_dir,
                "docx_export_status.json",
                {
                    "export_profile": "cumcm2026",
                    "format_contract": {
                        "active": True,
                        "body_font_east_asia": "SimSun",
                        "body_font_ascii": "Times New Roman",
                        "body_font_hansi": "Times New Roman",
                        "body_font_cs": "Times New Roman",
                        "body_font_size_half_points": 24,
                        "body_line_spacing_twips": 240,
                        "body_line_rule": "auto",
                        "body_start_page_break": False,
                    },
                },
            )

            report = audit_submission(work_dir)

        check = next(item for item in report["checks"] if item["id"] == "docx_format_contract")
        self.assertFalse(check["passed"])

    def test_submission_anonymity_detects_identity_leak(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            # Inject identity leak in docx
            _write_minimal_docx(work_dir, ["本文由参赛队员：张三 编写，指导教师：李教授"])
            report = audit_submission(work_dir, strict_anonymity=True)
            check = next(item for item in report["checks"] if item["id"] == "submission_anonymity")
            self.assertFalse(check["passed"])
            self.assertEqual(check["severity"], "error")
            self.assertGreater(check["evidence"]["high_confidence_count"], 0)

    def test_submission_anonymity_exempts_daxuesheng(self):
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            # Safe term: 大学生数学建模竞赛
            _write_minimal_docx(work_dir, ["全国大学生数学建模竞赛参赛论文，本文建立优化模型"])
            report = audit_submission(work_dir, strict_anonymity=True)
            check = next(item for item in report["checks"] if item["id"] == "submission_anonymity")
            self.assertTrue(check["passed"])

    def test_submission_anonymity_references_university_warn_not_fail(self):
        """测试参考文献中的 University 仅作为预警（warning），不触发阻断（FAIL）。"""
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            _write_minimal_docx(work_dir, [
                "本文构建了整数规划模型求解。",
                "参考文献：",
                "[1] John D. Graph Theory[M]. Oxford University Press, 2020.",
            ])
            report = audit_submission(work_dir, strict_anonymity=True)
            check = next(item for item in report["checks"] if item["id"] == "submission_anonymity")
            self.assertTrue(check["passed"])
            self.assertEqual(check["severity"], "warning")
            self.assertGreater(check["evidence"]["low_confidence_count"], 0)

    def test_submission_anonymity_split_xml_runs_email_and_phone(self):
        """测试 XML 中被拆分为多个 <w:t> run 的邮箱与手机号均能被成功还原并拦截。"""
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            # 构造拆分的 XML run
            split_xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p>'
                '<w:r><w:t>联系邮箱: my_team</w:t></w:r>'
                '<w:r><w:t>@</w:t></w:r>'
                '<w:r><w:t>163.com</w:t></w:r>'
                '</w:p></w:body></w:document>'
            )
            with zipfile.ZipFile(os.path.join(work_dir, "res.docx"), "w") as archive:
                archive.writestr("word/document.xml", split_xml)

            report = audit_submission(work_dir, strict_anonymity=True)
            check = next(item for item in report["checks"] if item["id"] == "submission_anonymity")
            self.assertFalse(check["passed"])
            self.assertEqual(check["severity"], "error")
            # 严格脱敏检查：原始邮箱不得明文出现在 message 中
            self.assertNotIn("my_team@163.com", check["message"])
            self.assertIn("my***@163.com", check["message"])

    def test_submission_anonymity_docx_metadata_and_header(self):
        """测试 DOCX 元数据属性 (core.xml, app.xml) 及页眉 header 中泄露的作者信息。"""
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            # 写入带作者的 core.xml 和带学校的 header1.xml
            core_xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/">'
                '<dc:creator>张三丰</dc:creator>'
                '</cp:coreProperties>'
            )
            header_xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:p><w:r><w:t>学校名称：清华大学计算机系</w:t></w:r></w:p>'
                '</w:hdr>'
            )
            with zipfile.ZipFile(os.path.join(work_dir, "res.docx"), "w") as archive:
                archive.writestr("word/document.xml", "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body><w:p><w:r><w:t>正文</w:t></w:r></w:p></w:body></w:document>")
                archive.writestr("docProps/core.xml", core_xml)
                archive.writestr("word/header1.xml", header_xml)

            report = audit_submission(work_dir, strict_anonymity=True)
            check = next(item for item in report["checks"] if item["id"] == "submission_anonymity")
            self.assertFalse(check["passed"])
            self.assertEqual(check["severity"], "error")
            self.assertGreaterEqual(check["evidence"]["high_confidence_count"], 1)

    def test_submission_audit_cross_modal_integrity_gate(self):
        """测试 submission_audit 对 cross_modal_audit 结果的门禁核验。"""
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            # 写入失败的 cross_modal_audit.json
            _write_json(
                work_dir,
                "cross_modal_audit.json",
                {"status": "FAIL", "passed": False, "issues": [{"type": "private_repo_import"}]},
            )

            report = audit_submission(work_dir)
            check = next(item for item in report["checks"] if item["id"] == "cross_modal_integrity")
            self.assertFalse(check["passed"])
            self.assertEqual(check["severity"], "error")

    def test_submission_audit_cross_modal_freshness_and_tampering(self):
        """测试 cross_modal_audit 时效性检查：缺少报告或修改 res.md 后旧报告被拒。"""
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )

            # 1. 初始状态：报告哈希与 res.md 完全匹配 -> PASS
            report_before = audit_submission(work_dir)
            check_before = next(item for item in report_before["checks"] if item["id"] == "cross_modal_integrity")
            self.assertTrue(check_before["passed"])

            # 2. 修改 res.md 内容，造成当前哈希与 cross_modal_audit.json 中记录的哈希不匹配
            with open(os.path.join(work_dir, "res.md"), "w", encoding="utf-8") as f:
                f.write("modified markdown content")

            report_after = audit_submission(work_dir)
            check_after = next(item for item in report_after["checks"] if item["id"] == "cross_modal_integrity")
            self.assertFalse(check_after["passed"])
            self.assertEqual(check_after["severity"], "error")
            self.assertIn("已过期", check_after["message"])

            # 探针结果核验：修改前为 True，修改后为 False（彻底杜绝 [true, true] 的 fail-open）
            self.assertEqual([check_before["passed"], check_after["passed"]], [True, False])

            # 3. 删除 cross_modal_audit.json -> 缺失直接 FAIL
            os.remove(os.path.join(work_dir, "cross_modal_audit.json"))
            report_missing = audit_submission(work_dir)
            check_missing = next(item for item in report_missing["checks"] if item["id"] == "cross_modal_integrity")
            self.assertFalse(check_missing["passed"])
            self.assertEqual(check_missing["severity"], "error")

    def test_submission_anonymity_title_not_misidentified_as_author(self):
        """验证文档标题 Optimization Study 在 core.xml 中不会被误判为作者元数据。"""
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            core_xml_title = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/">'
                '<dc:title>Optimization Study</dc:title>'
                '<dc:subject>Mathematical Modeling</dc:subject>'
                '</cp:coreProperties>'
            )
            with zipfile.ZipFile(os.path.join(work_dir, "res.docx"), "w") as archive:
                archive.writestr("word/document.xml", "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body><w:p><w:r><w:t>正文</w:t></w:r></w:p></w:body></w:document>")
                archive.writestr("docProps/core.xml", core_xml_title)

            report = audit_submission(work_dir, strict_anonymity=True)
            check = next(item for item in report["checks"] if item["id"] == "submission_anonymity")
            self.assertTrue(check["passed"], f"标题 Optimization Study 不得造成误报: {check}")

    def test_submission_anonymity_custom_xml_and_damaged_docx(self):
        """测试 docProps/custom.xml 泄露检测与损坏 DOCX 文件 fail-closed。"""
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )

            # 1. custom.xml 泄露作者 -> FAIL
            custom_xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
                'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
                '<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="Author">'
                '<vt:lpwstr>李四同学</vt:lpwstr>'
                '</property>'
                '</Properties>'
            )
            with zipfile.ZipFile(os.path.join(work_dir, "res.docx"), "w") as archive:
                archive.writestr("word/document.xml", "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body><w:p><w:r><w:t>正文</w:t></w:r></w:p></w:body></w:document>")
                archive.writestr("docProps/custom.xml", custom_xml)

            report_custom = audit_submission(work_dir, strict_anonymity=True)
            check_custom = next(item for item in report_custom["checks"] if item["id"] == "submission_anonymity")
            self.assertFalse(check_custom["passed"])
            self.assertEqual(check_custom["severity"], "error")

            # 2. 损坏的 DOCX（非有效 ZIP） -> 严格 fail-closed
            with open(os.path.join(work_dir, "res.docx"), "wb") as f:
                f.write(b"corrupted binary docx not a zip")

            report_corrupt = audit_submission(work_dir, strict_anonymity=True)
            check_corrupt = next(item for item in report_corrupt["checks"] if item["id"] == "submission_anonymity")
            self.assertFalse(check_corrupt["passed"])
            self.assertEqual(check_corrupt["severity"], "error")

    def test_submission_anonymity_candidate_manifest_filenames(self):
        """测试候选清单 candidate_manifest.json 中文件名携带学号/姓名的泄露拦截。"""
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            # 候选清单包含带有学号与姓名的文件名
            _write_json(
                work_dir,
                "candidate_manifest.json",
                {
                    "files": [
                        {"path": "20240101_作者_张三_res.pdf"},
                        {"path": "support_materials.zip"},
                    ]
                },
            )
            report = audit_submission(work_dir, strict_anonymity=True)
            check = next(item for item in report["checks"] if item["id"] == "submission_anonymity")
            self.assertFalse(check["passed"])
            self.assertEqual(check["severity"], "error")

    def test_cross_modal_hash_windows_crlf_parity(self):
        """测试 Windows CRLF 换行符下跨模态报告哈希计算与 submission_audit 一致性。"""
        from app.tools.cross_modal_validator import audit_cross_modal

        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            # 写入 Windows CRLF 文本
            crlf_content = "# 题目一：鲁棒优化模型\r\n\r\n本文建立了鲁棒优化模型，求解结果如下：\r\n\r\n```python\r\nimport numpy as np\r\nx = 1\r\n```\r\n"
            with open(os.path.join(work_dir, "res.md"), "wb") as f:
                f.write(crlf_content.encode("utf-8"))

            # 生成跨模态审计报告
            cross_report = audit_cross_modal(work_dir)
            self.assertTrue(cross_report["passed"])

            # 执行 submission_audit
            audit_rep = audit_submission(work_dir)
            check = next(item for item in audit_rep["checks"] if item["id"] == "cross_modal_integrity")
            self.assertTrue(check["passed"], f"CRLF 下跨模态哈希不得失配: {check}")

            # 修改 res.md 之后必须判定过期 FAIL
            with open(os.path.join(work_dir, "res.md"), "wb") as f:
                f.write(b"# Modified content\r\n")
            audit_rep2 = audit_submission(work_dir)
            check2 = next(item for item in audit_rep2["checks"] if item["id"] == "cross_modal_integrity")
            self.assertFalse(check2["passed"], "res.md 被修改后必须判定过期 FAIL")

    def test_submission_anonymity_schema12_manifest_and_unmasked_findings(self):
        """测试 candidate_manifest.json schema 1.2 顶层 submission_file 与 files 字典匿名扫描及脱敏回显。"""
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            # schema 1.2: submission_file 泄露作者
            _write_json(
                work_dir,
                "candidate_manifest.json",
                {
                    "schema": "1.2",
                    "submission_file": "20240101_作者_王五_res.pdf",
                    "files": {
                        "paper_pdf": "20240101_作者_王五_res.pdf",
                        "paper_md": "res.md",
                    },
                },
            )
            report = audit_submission(work_dir, strict_anonymity=True)
            check = next(item for item in report["checks"] if item["id"] == "submission_anonymity")
            self.assertFalse(check["passed"], "schema 1.2 顶层 submission_file 泄露必须被拦截")

            # 验证报告中未二次泄露明文作者全名（王五）
            report_str = json.dumps(check, ensure_ascii=False)
            self.assertNotIn("王五", report_str, "审计报告中不得出现敏感人名明文")
            self.assertIn("王*", report_str, "审计报告中必须为脱敏掩码")

    def test_submission_anonymity_normal_paper_sentences_not_flagged(self):
        """测试普通论文自然语言陈述不被误报为作者泄露，而真实作者字段严格拦截。"""
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )

            # 1. 正常论述句子 -> 必须 PASS
            normal_docx_xml = (
                "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body>"
                "<w:p><w:r><w:t>本文作者提出一种鲁棒优化模型。</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>作者认为该算法具有较好稳定性。</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>指导教师建议采用灵敏度分析。</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>在建模过程中，作者结合了物理守恒定律。</w:t></w:r></w:p>"
                "</w:body></w:document>"
            )
            with zipfile.ZipFile(os.path.join(work_dir, "res.docx"), "w") as archive:
                archive.writestr("word/document.xml", normal_docx_xml)

            report_normal = audit_submission(work_dir, strict_anonymity=True)
            check_normal = next(item for item in report_normal["checks"] if item["id"] == "submission_anonymity")
            self.assertTrue(check_normal["passed"], f"正常论文句子不得触发误报: {check_normal}")

            # 2. 真实作者字段泄露 -> 必须 FAIL
            leak_docx_xml = (
                "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body>"
                "<w:p><w:r><w:t>作者：王强</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>指导教师：李教授</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>学校名称：清华大学</w:t></w:r></w:p>"
                "</w:body></w:document>"
            )
            with zipfile.ZipFile(os.path.join(work_dir, "res.docx"), "w") as archive:
                archive.writestr("word/document.xml", leak_docx_xml)

            report_leak = audit_submission(work_dir, strict_anonymity=True)
            check_leak = next(item for item in report_leak["checks"] if item["id"] == "submission_anonymity")
            self.assertFalse(check_leak["passed"], "真实作者/导师/学校元数据必须拦截")

    def test_cross_modal_audit_code_source_deletion_fail_closed(self):
        """测试已登记求解器源码被删除后，跨模态门禁严格 fail-closed。"""
        from app.tools.cross_modal_validator import audit_cross_modal

        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            # 创建 master_solver.py 并登记
            solver_path = os.path.join(work_dir, "master_solver.py")
            with open(solver_path, "w", encoding="utf-8") as f:
                f.write("import numpy as np\nprint('solve')\n")

            _write_json(
                work_dir,
                "frozen_results.json",
                {
                    "schema": "1.1",
                    "executed_code_sources": ["master_solver.py"],
                    "metrics": {},
                },
            )

            # 生成报告
            cross_rep = audit_cross_modal(work_dir)
            self.assertTrue(cross_rep["passed"])

            # 删除 master_solver.py
            os.remove(solver_path)

            # 再次运行 submission_audit -> 必须 FAIL
            report = audit_submission(work_dir)
            check = next(item for item in report["checks"] if item["id"] == "cross_modal_integrity")
            self.assertFalse(check["passed"], "源码被删除后跨模态审计必须判定失效 FAIL")

    def test_submission_anonymity_corrupted_docx_internal_xml_fail_closed(self):
        """测试 DOCX 内部 XML (word/document.xml) 语法损坏时匿名门禁严格 fail-closed。"""
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            # 写入损坏的 XML
            with zipfile.ZipFile(os.path.join(work_dir, "res.docx"), "w") as archive:
                archive.writestr("word/document.xml", "<w:document corrupted unclosed xml tag")

            report = audit_submission(work_dir, strict_anonymity=True)
            check = next(item for item in report["checks"] if item["id"] == "submission_anonymity")
            self.assertFalse(check["passed"], "DOCX 内部 XML 损坏必须导致匿名门禁 FAIL")
            self.assertEqual(check["severity"], "error")

    def test_cross_modal_audit_text_disk_mismatch_fails(self):
        """测试显式传入的内存正文与磁盘 res.md 不一致时，跨模态门禁严格阻断 FAIL（防止哈希被违规磁盘文件替换）。"""
        from app.tools.cross_modal_validator import audit_cross_modal

        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            # 磁盘写入包含私有依赖的违规正文
            unsafe_disk_md = "# 题目\n```python\nfrom app.core import evil\n```\n"
            with open(os.path.join(work_dir, "res.md"), "w", encoding="utf-8") as f:
                f.write(unsafe_disk_md)

            # 内存传入干净正文
            clean_mem_md = "# 题目\n```python\nimport numpy as np\nx = 1\n```\n"

            # 跨模态审计必须判定 FAIL
            report = audit_cross_modal(work_dir, markdown_text=clean_mem_md)
            self.assertFalse(report["passed"], "内存正文与磁盘正文不一致必须判定 FAIL")
            self.assertEqual(report["status"], "FAIL")

            # submission_audit 接入核验也必须 FAIL
            sub_rep = audit_submission(work_dir)
            check = next(item for item in sub_rep["checks"] if item["id"] == "cross_modal_integrity")
            self.assertFalse(check["passed"])

    def test_submission_anonymity_chinese_prefix_and_explicit_metadata_values(self):
        """测试前置中文字符（本文作者/本队参赛队员）及包含常用谓词的真实机构/院系/班级均被精准拦截。"""
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )

            leak_xml = (
                "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body>"
                "<w:p><w:r><w:t>本文作者：王强</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>论文指导教师：李教授</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>本队参赛队员：张三</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>院系：计算机学院</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>学校名称：研究院</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>班级：设计二班</w:t></w:r></w:p>"
                "</w:body></w:document>"
            )
            with zipfile.ZipFile(os.path.join(work_dir, "res.docx"), "w") as archive:
                archive.writestr("word/document.xml", leak_xml)

            report = audit_submission(work_dir, strict_anonymity=True)
            check = next(item for item in report["checks"] if item["id"] == "submission_anonymity")
            self.assertFalse(check["passed"], "中文字符前缀及明确元数据赋值必须被匿名门禁拦截")

    def test_cross_modal_audit_sibling_directory_traversal_fails(self):
        """测试同前缀兄弟目录目录穿越 (task/../task_evil/solver.py) 无法绕过路径安全校验。"""
        with tempfile.TemporaryDirectory() as base_dir:
            task_dir = os.path.join(base_dir, "task")
            evil_dir = os.path.join(base_dir, "task_evil")
            os.makedirs(task_dir)
            os.makedirs(evil_dir)

            _write_required_success_files(
                task_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )

            # 在兄弟目录创建 solver.py
            evil_solver = os.path.join(evil_dir, "evil_solver.py")
            with open(evil_solver, "w", encoding="utf-8") as f:
                f.write("print('evil')\n")

            with open(os.path.join(task_dir, "res.md"), "rb") as f:
                md_hash = hashlib.sha256(f.read()).hexdigest()
            # 跨模态报告记录穿越路径
            _write_json(
                task_dir,
                "cross_modal_audit.json",
                {
                    "status": "PASS",
                    "passed": True,
                    "markdown_sha256": md_hash,
                    "code_source_hashes": {
                        "../task_evil/evil_solver.py": "dummy_hash",
                    },
                },
            )

            report = audit_submission(task_dir)
            check = next(item for item in report["checks"] if item["id"] == "cross_modal_integrity")
            self.assertFalse(check["passed"], "同前缀兄弟目录穿越必须被安全阻断 FAIL")

    def test_cross_modal_audit_missing_code_hashes_with_executed_sources_fails(self):
        """测试 frozen_results 声明了执行源码，但跨模态报告缺少 code_source_hashes 字段时严格阻断 FAIL。"""
        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )
            # frozen_results 声明了 master_solver.py
            _write_json(
                work_dir,
                "frozen_results.json",
                {
                    "schema": "1.1",
                    "executed_code_sources": ["master_solver.py"],
                    "metrics": {},
                },
            )
            with open(os.path.join(work_dir, "res.md"), "rb") as f:
                md_hash = hashlib.sha256(f.read()).hexdigest()
            # 报告未提供 code_source_hashes
            _write_json(
                work_dir,
                "cross_modal_audit.json",
                {
                    "status": "PASS",
                    "passed": True,
                    "markdown_sha256": md_hash,
                },
            )

            report = audit_submission(work_dir)
            check = next(item for item in report["checks"] if item["id"] == "cross_modal_integrity")
            self.assertFalse(check["passed"], "声明源码后缺少 code_source_hashes 必须阻断 FAIL")

    def test_submission_anonymity_pdf_attachment_raw_filename_not_leaked_in_json(self):
        """测试 PDF 内嵌附件名泄露作者时，报告 JSON 中不会出现原始敏感文件名，且使用脱敏位置与掩码。"""
        from unittest.mock import MagicMock, patch

        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )

            # mock PyMuPDF 返回带有作者姓名的附件
            mock_doc = MagicMock()
            mock_doc.metadata = {}
            mock_doc.embfile_names.return_value = ["Author_JohnDoe.txt"]
            mock_doc.__iter__.return_value = []

            with patch("fitz.open", return_value=mock_doc):
                report = audit_submission(work_dir, strict_anonymity=True)

            check = next(item for item in report["checks"] if item["id"] == "submission_anonymity")
            self.assertFalse(check["passed"], "PDF 内嵌附件作者泄露必须被拦截")

            # 验证整个审计报告 JSON 中绝不含 Author_JohnDoe.txt 原文字符串
            report_str = json.dumps(check, ensure_ascii=False)
            self.assertNotIn("Author_JohnDoe.txt", report_str, "报告 JSON 中不得出现原始附件名")
            self.assertIn("pdf:attachment:1", report_str, "报告必须使用位置索引代替原始附件名")

    def test_submission_anonymity_real_pymupdf_attachment_metadata_and_mojibake(self):
        """测试真实 PyMuPDF 内嵌附件元数据 (filename, ufilename, desc) 泄露时被精准拦截，且 Mojibake 编码被修复。"""
        import fitz

        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )

            # 1. 创建包含足够文本的真实 PDF
            pdf_path = os.path.join(work_dir, "res.pdf")
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text(
                (50, 50),
                "本文针对数学建模问题开展研究。基于约束优化理论建立目标函数，并通过数值仿真验证模型的有效性与稳健性。" * 5,
            )

            # 2. 添加普通键 attachment-1，但设置 filename, ufilename, desc
            doc.embfile_add(
                "attachment-1",
                b"sample attachment content",
                filename="Author_JohnDoe.txt",
                ufilename="作者_王五.txt",
                desc="学校名称：清华大学",
            )
            doc.save(pdf_path)
            doc.close()

            # 3. 运行严格匿名审计
            report = audit_submission(work_dir, strict_anonymity=True)
            check = next(item for item in report["checks"] if item["id"] == "submission_anonymity")

            # 4. 断言：passed=False，且至少存在一个 high-confidence finding
            self.assertFalse(check["passed"], "PDF 内嵌附件元数据泄露必须导致匿名门禁 FAIL")
            findings = check.get("evidence", {}).get("high_confidence_findings", [])
            self.assertGreater(len(findings), 0)

            # 5. 断言：整个 JSON 不含原始敏感值，不含 mojibake，part 只含抽象位置
            report_str = json.dumps(check, ensure_ascii=False)
            self.assertNotIn("Author_JohnDoe.txt", report_str)
            self.assertNotIn("作者_王五.txt", report_str)
            self.assertNotIn("学校名称：清华大学", report_str)
            self.assertNotIn("ä½\x9cè\x80\x85_ç\x8e\x8bäº\x94.txt", report_str)

            # 验证 part 格式只包含抽象索引与字段标识
            for f in findings:
                part = f.get("part", "")
                if part.startswith("pdf:attachment:"):
                    self.assertRegex(
                        part,
                        r"^pdf:attachment:\d+:(key|filename|ufilename|description)$",
                        f"附件 part 必须为规范的抽象位置标识，实际为: {part}",
                    )

    def test_submission_anonymity_real_pymupdf_chinese_attachment_key_repaired(self):
        """测试中文附件键 (作者_王五.txt) 在经过 PyMuPDF Latin-1 误解码后仍被成功修复并拦截。"""
        import fitz

        with tempfile.TemporaryDirectory() as work_dir:
            _write_required_success_files(
                work_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )

            pdf_path = os.path.join(work_dir, "res.pdf")
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((50, 50), "基于优化算法的数学建模论文正文内容测试。" * 10)
            doc.embfile_add("作者_王五.txt", b"dummy")
            doc.save(pdf_path)
            doc.close()

            report = audit_submission(work_dir, strict_anonymity=True)
            check = next(item for item in report["checks"] if item["id"] == "submission_anonymity")
            self.assertFalse(check["passed"], "中文附件键泄露必须被拦截")

            report_str = json.dumps(check, ensure_ascii=False)
            self.assertNotIn("作者_王五.txt", report_str)
            self.assertNotIn("ä½\x9cè\x80\x85_ç\x8e\x8bäº\x94.txt", report_str)

    def test_submission_anonymity_corrupted_pdf_in_sensitive_path_no_leak(self):
        """测试敏感路径下的损坏 PDF 导致门禁 FAIL 时，报告 JSON 绝不回显绝对路径或敏感目录名。"""
        with tempfile.TemporaryDirectory() as base_dir:
            secret_dir = os.path.join(base_dir, "Secret_Author_JohnDoe_University")
            os.makedirs(secret_dir)

            _write_required_success_files(
                secret_dir,
                [{"preferred": "Times New Roman", "actual": "Times New Roman", "source": "profile"}],
            )

            # 写入损坏的 PDF 字节
            corrupted_pdf = os.path.join(secret_dir, "res.pdf")
            with open(corrupted_pdf, "wb") as f:
                f.write(b"%PDF-1.4 corrupted invalid binary header and body \xff\xfe")

            report = audit_submission(secret_dir, strict_anonymity=True)
            check = next(item for item in report["checks"] if item["id"] == "submission_anonymity")
            self.assertFalse(check["passed"], "损坏 PDF 必须触发匿名审计严格 fail-closed")

            report_str = json.dumps(check, ensure_ascii=False)
            self.assertNotIn("Secret_Author_JohnDoe_University", report_str, "报告 JSON 中绝不能泄露敏感目录名或绝对路径")
            self.assertNotIn(base_dir, report_str, "报告 JSON 中绝不能泄露基础路径")


if __name__ == "__main__":
    unittest.main()
