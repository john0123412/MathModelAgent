"""PDF 导出工具模块，负责将 Markdown 论文转换为 PDF。"""

import os
import shutil
import subprocess
from app.utils.log_util import logger
from app.utils.font_utils import resolve_font
from app.schemas.enums import ExportProfile
from app.tools.export_profiles import get_export_profile_config

# pdf_variables 中需要做字体可用性检测/fallback 的 pandoc 变量名
# （对应 fontspec 的 mainfont/CJKmainfont 等，值缺失时无法通过 apt 补装
# 同名字体，只能替换成等效字体，见 app.utils.font_utils）。
_FONT_VARIABLE_KEYS = {
    "mainfont",
    "monofont",
    "sansfont",
    "CJKmainfont",
    "CJKsansfont",
    "CJKmonofont",
}


def _resolve_pdf_variables(pdf_variables: list[str]) -> list[str]:
    """对 pdf_variables 中的字体相关变量应用 resolve_font 检测/fallback。"""
    resolved = []
    for variable in pdf_variables:
        key, sep, value = variable.partition("=")
        if sep and key in _FONT_VARIABLE_KEYS:
            variable = f"{key}={resolve_font(value)}"
        resolved.append(variable)
    return resolved


def export_markdown_to_pdf(
    md_path: str,
    pdf_path: str,
    work_dir: str,
    export_profile: ExportProfile | str | None = ExportProfile.DEFAULT,
) -> dict:
    """将 Markdown 文件转换为 PDF（通过 pandoc + xelatex）。

    检查 md_path、pandoc、xelatex 是否可用，任一缺失则跳过转换并说明原因，
    不会抛出异常中断调用方流程。

    Args:
        md_path: 待转换的 Markdown 文件路径。
        pdf_path: 输出 PDF 文件路径。
        work_dir: 工作目录，用作 pandoc 的资源查找路径（图片等）。

    Returns:
        结构化结果字典，包含 enabled/success/pdf_path/reason/command/stderr。
    """
    result = {
        "enabled": False,
        "success": False,
        "pdf_path": None,
        "reason": "",
        "command": [],
        "stderr": "",
        "export_profile": get_export_profile_config(export_profile).key.value,
    }

    if not os.path.exists(md_path):
        result["reason"] = f"Markdown 文件不存在: {md_path}"
        logger.warning(f"PDF 导出跳过: {result['reason']}")
        return result

    if shutil.which("pandoc") is None:
        result["reason"] = "未检测到 pandoc 可执行文件，跳过 PDF 生成"
        logger.warning(f"PDF 导出跳过: {result['reason']}")
        return result

    if shutil.which("xelatex") is None:
        result["reason"] = "未检测到 xelatex 可执行文件（TeX 发行版未安装或未加入 PATH），跳过 PDF 生成"
        logger.warning(f"PDF 导出跳过: {result['reason']}")
        return result

    profile_config = get_export_profile_config(export_profile)

    command = [
        "pandoc",
        md_path,
        "-o",
        pdf_path,
        "--pdf-engine=xelatex",
        "--from",
        "markdown+tex_math_dollars+pipe_tables+raw_tex",
        "--standalone",
        "--resource-path",
        work_dir,
    ]
    for variable in _resolve_pdf_variables(profile_config.pdf_variables):
        command.extend(["-V", variable])
    command.extend(profile_config.pdf_extra_args)
    result["enabled"] = True
    result["command"] = command

    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        result["reason"] = "PDF 生成超时（120秒）"
        logger.error(f"PDF 导出超时: {md_path}")
        return result
    except Exception as e:
        result["reason"] = f"PDF 生成异常: {e}"
        logger.error(f"PDF 导出异常: {e}")
        return result

    if proc.returncode == 0 and os.path.exists(pdf_path):
        result["success"] = True
        result["pdf_path"] = pdf_path
        logger.info(f"PDF 生成成功: {pdf_path}")
    else:
        result["reason"] = f"pandoc 返回码非 0: {proc.returncode}"
        result["stderr"] = proc.stderr
        logger.error(f"PDF 生成失败: returncode={proc.returncode}, stderr={proc.stderr}")

    return result
