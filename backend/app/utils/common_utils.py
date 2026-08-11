"""通用工具函数模块，提供任务 ID 生成、文件操作和文档转换等功能。"""

import os
import hashlib
import json
import shutil
import datetime
import secrets
import tomllib
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from app.schemas.enums import CompTemplate, ExportProfile
from app.tools.export_profiles import get_export_profile_config
from app.tools.export_template_override import load_export_template_override
from app.utils.log_util import logger
import re
import pypandoc  # type: ignore[import-unresolved]
from app.config.setting import settings

TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_INVALID_FILENAME_CHARS = {"/", "\\", ":", "\x00"}
PANDOC_DOCX_MARKDOWN_FORMAT = "markdown+tex_math_dollars+tex_math_single_backslash"
_DOCX_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_DOCX_NS = {"w": _DOCX_W_NS}
_DOCX_FORMAL_PROFILES = {ExportProfile.CUMCM2025.value, ExportProfile.CUMCM2026.value}
_DOCX_BODY_START_RE = re.compile(r"^(?:一、)?问题重述\s*$")
_DOCX_CODE_APPENDIX_RE = re.compile(r"^附录\s*[A-Z]\s*源程序代码\s*$", re.IGNORECASE)
_FORMAL_CHINESE_BASELINE_CONTRACT = {
    # This is a project/user baseline, not a claim about a future official
    # CUMCM package.  A task-local imported format contract overrides it.
    "source": "project_user_chinese_contest_baseline_non_official",
    "official_rule": False,
    "body_font_east_asia": "SimSun",
    "body_font_ascii": "Times New Roman",
    "body_font_hansi": "Times New Roman",
    "body_font_cs": "Times New Roman",
    "body_font_size_half_points": 24,
    "body_line_spacing_twips": 240,
    "body_line_rule": "auto",
    "body_start_page_break": True,
}

# 所有任务工作目录的根路径约定，供 create_work_dir/get_work_dir 及路由层复用，
# 避免各处硬编码 "project/work_dir" 字符串。
WORK_DIR_ROOT = os.path.join("project", "work_dir")


def create_task_id() -> str:
    """生成基于时间戳和随机哈希的唯一任务 ID。"""
    # 任务目录名是工作区文件的 capability URL 组成部分，使用 128 位随机后缀
    # 避免其他本机浏览器页面或进程通过枚举时间戳猜测任务产物。
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{secrets.token_hex(16)}"


def ensure_safe_task_id(task_id: str) -> str:
    """验证任务 ID 的合法性，防止路径遍历攻击。

    Args:
        task_id: 待验证的任务 ID。

    Returns:
        验证通过的任务 ID。

    Raises:
        ValueError: 任务 ID 不合法时抛出。
    """
    normalized = (task_id or "").strip()
    if not normalized or not TASK_ID_PATTERN.fullmatch(normalized):
        raise ValueError("非法 task_id")
    return normalized


def get_work_dir_root() -> str:
    """获取工作目录根路径的绝对路径。"""
    return os.path.abspath(WORK_DIR_ROOT)


def ensure_safe_filename(filename: str) -> str:
    """验证文件名安全性，防止路径遍历和跨目录写入。"""
    normalized = (filename or "").strip()
    if not normalized or normalized in {".", ".."}:
        raise ValueError("非法文件名")
    if any(char in normalized for char in _INVALID_FILENAME_CHARS):
        raise ValueError("非法文件名")
    if Path(normalized).name != normalized:
        raise ValueError("非法文件名")
    return normalized


def resolve_work_dir(task_id: str) -> str:
    """解析任务目录绝对路径，并确保位于工作目录根路径内。"""
    safe_task_id = ensure_safe_task_id(task_id)
    root = get_work_dir_root()
    work_dir = os.path.abspath(os.path.join(root, safe_task_id))
    if os.path.commonpath([root, work_dir]) != root:
        raise ValueError("非法 task_id")
    return work_dir


def safe_join_work_dir(task_id: str, filename: str) -> str:
    """安全拼接任务目录内文件路径。"""
    work_dir = resolve_work_dir(task_id)
    safe_filename = ensure_safe_filename(filename)
    file_path = os.path.abspath(os.path.join(work_dir, safe_filename))
    if os.path.commonpath([work_dir, file_path]) != work_dir:
        raise ValueError("非法文件路径")
    return file_path


def create_work_dir(task_id: str) -> str:
    """为指定任务创建工作目录，并复制字体文件到工作目录。

    Args:
        task_id: 任务 ID。

    Returns:
        工作目录路径。
    """
    work_dir = resolve_work_dir(task_id)

    try:
        # 创建目录，如果目录已存在也不会报错
        os.makedirs(work_dir, exist_ok=True)
        # 复制字体文件到工作目录，确保图表中文正常显示
        _copy_fonts_to_work_dir(work_dir)
        return work_dir
    except Exception as e:
        # 捕获并记录创建目录时的异常
        logger.error(f"创建工作目录失败: {str(e)}")
        raise


# 字体源目录（backend/fonts/）
_FONTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "fonts")


def _copy_fonts_to_work_dir(work_dir: str) -> None:
    """将后端字体目录中的字体文件复制到工作目录。

    Args:
        work_dir: 目标工作目录路径。
    """
    fonts_dir = os.path.normpath(_FONTS_DIR)
    if not os.path.isdir(fonts_dir):
        logger.warning(f"字体目录不存在: {fonts_dir}")
        return

    for filename in os.listdir(fonts_dir):
        if not filename.lower().endswith((".ttf", ".otf", ".ttc")):
            continue
        src = os.path.join(fonts_dir, filename)
        dst = os.path.join(work_dir, filename)
        try:
            shutil.copy2(src, dst)
            logger.debug(f"复制字体: {filename} -> {work_dir}")
        except Exception as e:
            logger.warning(f"复制字体 {filename} 失败: {e}")


def get_work_dir(task_id: str) -> str:
    """获取指定任务的工作目录路径。

    Args:
        task_id: 任务 ID。

    Returns:
        工作目录路径。

    Raises:
        FileNotFoundError: 工作目录不存在时抛出。
    """
    work_dir = resolve_work_dir(task_id)
    if os.path.exists(work_dir):
        return work_dir
    else:
        logger.error(f"工作目录不存在: {work_dir}")
        raise FileNotFoundError(f"工作目录不存在: {work_dir}")


# TODO: 是不是应该将 Prompt 写成一个 class
def get_config_template(comp_template: CompTemplate = CompTemplate.CHINA) -> dict:
    """获取论文模板配置。

    Args:
        comp_template: 竞赛模板类型。

    Returns:
        模板配置字典。
    """
    if comp_template == CompTemplate.CHINA:
        return load_toml(os.path.join("app", "config", "md_template.toml"))
    return {}


def load_toml(path: str) -> dict:
    """加载 TOML 配置文件。

    Args:
        path: TOML 文件路径。
    """
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_markdown(path: str) -> str:
    """加载 Markdown 文件内容。

    Args:
        path: Markdown 文件路径。
    """
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_current_files(folder_path: str, type: str = "all") -> list[str]:
    """获取指定目录下的文件列表。

    Args:
        folder_path: 目录路径。
        type: 文件类型过滤（all/md/ipynb/data/image）。
    """
    files = os.listdir(folder_path)
    if type == "all":
        return files
    elif type == "md":
        return [file for file in files if file.endswith(".md")]
    elif type == "ipynb":
        return [file for file in files if file.endswith(".ipynb")]
    elif type == "data":
        return [
            file for file in files if file.endswith(".xlsx") or file.endswith(".csv")
        ]
    elif type == "image":
        return [
            file for file in files if file.endswith(".png") or file.endswith(".jpg")
        ]
    return []


def transform_link(task_id: str, content: str):
    """将 Markdown 中的图片链接转换为静态资源 URL。

    Args:
        task_id: 任务 ID，用于构建 URL 路径。
        content: 包含图片链接的 Markdown 文本。
    """
    content = re.sub(
        r"!\[(.*?)\]\((.*?\.(?:png|jpg|jpeg|gif|bmp|webp))\)",
        lambda match: f"![{match.group(1)}]({settings.SERVER_HOST}/static/{task_id}/{match.group(2)})",
        content,
    )
    return content


def _file_sha256(path: str) -> str | None:
    if not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _docx_w_tag(local_name: str) -> str:
    return f"{{{_DOCX_W_NS}}}{local_name}"


def _docx_paragraph_text(paragraph: ET.Element) -> str:
    return "".join(node.text or "" for node in paragraph.findall(".//w:t", _DOCX_NS)).strip()


def _docx_paragraph_style(paragraph: ET.Element) -> str:
    properties = paragraph.find("w:pPr", _DOCX_NS)
    style = properties.find("w:pStyle", _DOCX_NS) if properties is not None else None
    return style.get(_docx_w_tag("val"), "") if style is not None else ""


def _docx_is_heading(paragraph: ET.Element, text: str) -> bool:
    style = _docx_paragraph_style(paragraph).lower()
    if style.startswith("heading") or style in {"title", "subtitle"}:
        return True
    return bool(
        re.match(r"^(?:[一二三四五六七八九十]+、|\d+(?:\.\d+){0,3}\s|摘要$|关键词|参考文献$|附录)", text)
    )


def _docx_properties(paragraph: ET.Element) -> ET.Element:
    properties = paragraph.find("w:pPr", _DOCX_NS)
    if properties is None:
        properties = ET.Element(_docx_w_tag("pPr"))
        paragraph.insert(0, properties)
    return properties


def _docx_run_properties(run: ET.Element) -> ET.Element:
    properties = run.find("w:rPr", _DOCX_NS)
    if properties is None:
        properties = ET.Element(_docx_w_tag("rPr"))
        run.insert(0, properties)
    return properties


def _set_docx_body_paragraph_format(
    paragraph: ET.Element, format_contract: dict
) -> bool:
    """Apply the checked task format contract to a rendered prose paragraph."""
    properties = _docx_properties(paragraph)
    spacing = properties.find("w:spacing", _DOCX_NS)
    if spacing is None:
        spacing = ET.SubElement(properties, _docx_w_tag("spacing"))
    spacing.set(_docx_w_tag("before"), "0")
    spacing.set(_docx_w_tag("after"), "0")
    spacing.set(_docx_w_tag("line"), str(format_contract["body_line_spacing_twips"]))
    spacing.set(_docx_w_tag("lineRule"), str(format_contract["body_line_rule"]))

    formatted = False
    for run in paragraph.findall("w:r", _DOCX_NS):
        if not run.findall(".//w:t", _DOCX_NS):
            continue
        run_properties = _docx_run_properties(run)
        fonts = run_properties.find("w:rFonts", _DOCX_NS)
        if fonts is None:
            fonts = ET.SubElement(run_properties, _docx_w_tag("rFonts"))
        fonts.set(_docx_w_tag("ascii"), str(format_contract["body_font_ascii"]))
        fonts.set(_docx_w_tag("hAnsi"), str(format_contract["body_font_hansi"]))
        fonts.set(_docx_w_tag("cs"), str(format_contract["body_font_cs"]))
        fonts.set(_docx_w_tag("eastAsia"), str(format_contract["body_font_east_asia"]))
        for size_tag in ("sz", "szCs"):
            size = run_properties.find(f"w:{size_tag}", _DOCX_NS)
            if size is None:
                size = ET.SubElement(run_properties, _docx_w_tag(size_tag))
            size.set(_docx_w_tag("val"), str(format_contract["body_font_size_half_points"]))
        formatted = True
    return formatted


def _enforce_formal_chinese_docx_layout(
    docx_path: str, format_contract: dict | None = None
) -> dict:
    """Post-process a Pandoc DOCX without changing manuscript text.

    The bundled historical reference document leaves body style inheritance at
    10.5 pt and cannot express the user-selected body contract.  This narrowly
    patches generated prose paragraphs in ``word/document.xml`` and records
    measurable evidence for submission audit; headings, tables, and source-code
    appendices remain governed by their own styles.
    """
    try:
        with zipfile.ZipFile(docx_path) as archive:
            document_xml = archive.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise RuntimeError("无法读取 Pandoc 生成的 DOCX 主文档") from exc

    try:
        document = ET.fromstring(document_xml)
    except ET.ParseError as exc:
        raise RuntimeError("DOCX 主文档 XML 无法解析") from exc
    body = document.find("w:body", _DOCX_NS)
    if body is None:
        raise RuntimeError("DOCX 缺少正文节点")

    effective_contract = dict(_FORMAL_CHINESE_BASELINE_CONTRACT)
    effective_contract.update(format_contract or {})
    formatted_paragraphs = 0
    body_start_found = False
    code_appendix_started = False
    for paragraph in body.findall("w:p", _DOCX_NS):
        text = _docx_paragraph_text(paragraph)
        if not text:
            continue
        if _DOCX_CODE_APPENDIX_RE.fullmatch(text):
            code_appendix_started = True
            continue
        if _DOCX_BODY_START_RE.fullmatch(text):
            body_start_found = True
            if effective_contract["body_start_page_break"]:
                properties = _docx_properties(paragraph)
                if properties.find("w:pageBreakBefore", _DOCX_NS) is None:
                    ET.SubElement(properties, _docx_w_tag("pageBreakBefore"))
        if code_appendix_started or _docx_is_heading(paragraph, text):
            continue
        if _set_docx_body_paragraph_format(paragraph, effective_contract):
            formatted_paragraphs += 1

    if not body_start_found:
        raise RuntimeError("DOCX 未找到“问题重述”正文起始标题，无法核验摘要后分页")

    ET.register_namespace("w", _DOCX_W_NS)
    rendered_xml = ET.tostring(document, encoding="utf-8", xml_declaration=True)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix="mma-docx-layout-", suffix=".docx", dir=os.path.dirname(docx_path)
    )
    os.close(descriptor)
    try:
        with zipfile.ZipFile(docx_path) as source, zipfile.ZipFile(
            temporary_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as target:
            for item in source.infolist():
                target.writestr(
                    item,
                    rendered_xml if item.filename == "word/document.xml" else source.read(item.filename),
                )
        os.replace(temporary_path, docx_path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)

    return {
        "active": True,
        **effective_contract,
        "formatted_paragraphs": formatted_paragraphs,
    }


def md_2_docx(
    task_id: str,
    export_profile: ExportProfile | str | None = ExportProfile.DEFAULT,
) -> dict:
    """将 Markdown 论文转换为 DOCX，并记录当前源文件与输出哈希。"""
    work_dir = get_work_dir(task_id)
    md_path = os.path.join(work_dir, "res.md")
    docx_path = os.path.join(work_dir, "res.docx")
    status_path = os.path.join(work_dir, "docx_export_status.json")
    status = {
        "generated_at": datetime.datetime.now().isoformat(),
        "success": False,
        "source_sha256": _file_sha256(md_path),
        "output_sha256": None,
        "reason": "",
        "export_profile": get_export_profile_config(export_profile).key.value,
    }

    try:
        if os.path.exists(docx_path):
            os.remove(docx_path)

        extra_args = [
            "--resource-path",
            str(work_dir),
            "--standalone",
        ]
        profile_config = get_export_profile_config(export_profile)
        template_override = load_export_template_override(
            work_dir, profile_config.key.value
        )
        reference_doc = (
            template_override.get("docx_reference_doc")
            or profile_config.docx_reference_doc
        )
        if reference_doc and os.path.exists(reference_doc):
            extra_args.extend(["--reference-doc", reference_doc])

        pypandoc.convert_file(
            source_file=md_path,
            to="docx",
            outputfile=docx_path,
            format=PANDOC_DOCX_MARKDOWN_FORMAT,
            extra_args=extra_args,
        )
        if not os.path.isfile(docx_path) or os.path.getsize(docx_path) <= 0:
            raise RuntimeError("Pandoc 未生成有效 DOCX 文件")
        status["template_override"] = template_override["audit"]
        if profile_config.key.value in _DOCX_FORMAL_PROFILES:
            override_contract = template_override.get("format_contract", {}).get("docx", {})
            contract = dict(_FORMAL_CHINESE_BASELINE_CONTRACT)
            contract.update(override_contract)
            if template_override.get("active"):
                contract["source"] = "user_supplied_unverified"
                contract["official_rule"] = False
            rendered_contract = _enforce_formal_chinese_docx_layout(
                docx_path, contract
            )
            if template_override.get("active"):
                template_audit = template_override["audit"]
                rendered_contract["template_override_format_contract_sha256"] = (
                    template_audit["format_contract_sha256"]
                )
                rendered_contract["template_override_docx_contract_sha256"] = (
                    template_audit["docx_contract_sha256"]
                )
            status["format_contract"] = rendered_contract
        else:
            status["format_contract"] = {
                "active": False,
                "reason": "当前导出 profile 未启用宋体小四单倍行距与摘要后正文分页合同",
            }
        status["success"] = True
        status["output_sha256"] = _file_sha256(docx_path)
        print(f"转换完成: {docx_path}")
        logger.info(f"转换完成: {docx_path}")
        return status
    except Exception as exc:
        status["reason"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        try:
            with open(status_path, "w", encoding="utf-8") as handle:
                json.dump(status, handle, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.error(f"docx_export_status.json 写入失败: {exc}")


def split_footnotes(text: str) -> tuple[str, list[tuple[str, str]]]:
    """从文本中分离正文和脚注。

    Args:
        text: 包含脚注的完整文本。

    Returns:
        (正文, 脚注列表) 的元组，脚注格式为 (编号, 内容)。
    """
    main_text = re.sub(
        r"\n\[\^\d+\]:.*?(?=\n\[\^|\n\n|\Z)", "", text, flags=re.DOTALL
    ).strip()

    # 匹配脚注定义
    footnotes = re.findall(r"\[\^(\d+)\]:\s*(.+?)(?=\n\[\^|\n\n|\Z)", text, re.DOTALL)
    logger.info(
        "脚注已拆分: "
        f"main_text_chars={len(main_text)}, footnotes_count={len(footnotes)}"
    )
    return main_text, footnotes
