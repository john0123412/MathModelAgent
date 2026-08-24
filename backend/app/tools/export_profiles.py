"""Export profile definitions for optional competition document layouts."""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.schemas.enums import ExportProfile


TEMPLATES_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "templates", "export_profiles")
)


@dataclass(frozen=True)
class ExportProfileConfig:
    key: ExportProfile
    label: str
    description: str
    pdf_variables: list[str]
    pdf_extra_args: list[str]
    latex_template_dir: str | None = None
    latex_template_key: str = "zh/cumcm-latex"
    docx_reference_doc: str | None = None
    # PDF-only layout behavior.  Keep it on the selected export profile rather
    # than hard-coding a competition convention into every modeling task.
    pdf_appendix_pagebreak: bool = False


PDF_HEADING_STYLE = (
    r"header-includes=\ctexset{"
    r"section={format={\centering\zihao{3}\heiti}},"
    r"subsection={format={\zihao{4}\heiti}},"
    r"subsubsection={format={\normalsize\heiti}}"
    r"}"
)
PDF_CODE_BLOCK_STYLE = (
    r"header-includes=\usepackage{listings}"
    r"\lstset{"
    r"breaklines=true,"
    r"breakatwhitespace=false,"
    r"columns=fullflexible,"
    r"keepspaces=true,"
    r"showspaces=false,"
    r"showstringspaces=false,"
    r"showtabs=false,"
    r"basicstyle=\ttfamily\footnotesize"
    r"}"
)
PDF_PARAGRAPH_BREAK_STYLE = (
    r"header-includes=\sloppy"
    r"\emergencystretch=3em"
    r'\XeTeXlinebreaklocale "zh"'
    r"\XeTeXlinebreakskip=0pt plus 1pt"
)

HUASHUBEI_PAGE_MARGIN = "2.5cm"
HUASHUBEI_GEOMETRY = (
    f"geometry:left={HUASHUBEI_PAGE_MARGIN},right={HUASHUBEI_PAGE_MARGIN},"
    f"top={HUASHUBEI_PAGE_MARGIN},bottom={HUASHUBEI_PAGE_MARGIN}"
)
HUASHUBEI_PDF_HEADING_STYLE = (
    r"header-includes=\usepackage{titlesec}"
    r"\titleformat{\section}"
    r"{\centering\fontsize{14pt}{16.8pt}\heiti\bfseries}"
    r"{\chinese{section}、}{1em}{}"
    r"\titleformat{\subsection}"
    r"{\fontsize{12pt}{14.4pt}\heiti\bfseries}"
    r"{\arabic{section}.\arabic{subsection}}{1em}{}"
    r"\titleformat{\subsubsection}"
    r"{\fontsize{12pt}{14.4pt}\heiti\bfseries}"
    r"{\arabic{section}.\arabic{subsection}.\arabic{subsubsection}}{1em}{}"
)


DEFAULT_PROFILE = ExportProfileConfig(
    key=ExportProfile.DEFAULT,
    label="默认导出",
    description="保持现有 Markdown/DOCX/PDF/LaTeX sidecar 导出行为。",
    pdf_variables=[
        "documentclass=ctexart",
        "classoption=scheme=chinese",
        "papersize=a4",
        "CJKmainfont=SimSun",
        "CJKsansfont=SimHei",
        "mainfont=Times New Roman",
        "pagestyle=plain",
        PDF_HEADING_STYLE,
        PDF_CODE_BLOCK_STYLE,
        "geometry:left=3.17cm,right=3.17cm,top=2.6cm,bottom=2.6cm",
        "fontsize=12pt",
    ],
    pdf_extra_args=[],
)


CUMCM2025_TEMPLATE_DIR = os.path.join(TEMPLATES_ROOT, "cumcm2025")

# DOCX reference-doc 单独存放在 cumcm2025_docx/ 目录，避免被
# _copy_template_assets() 误当作 LaTeX sidecar 的模板资源一并复制进
# latex_project/（该函数会遍历 latex_template_dir 下的全部文件）。
#
# 来源：format2025.doc（2025 年 CUMCM 官方论文格式规范，legacy 二进制 .doc）
# 通过本机 LibreOffice（soffice --headless --convert-to docx）转换为
# format2025_reference.docx。pandoc --reference-doc 只读取其中的页面
# 设置/默认字体等样式，不会带入原文内容。
CUMCM2025_DOCX_REFERENCE = os.path.join(
    TEMPLATES_ROOT, "cumcm2025_docx", "format2025_reference.docx"
)

CUMCM2025_PROFILE = ExportProfileConfig(
    key=ExportProfile.CUMCM2025,
    label="高教社杯/CUMCM 2025 模板",
    description=(
        "参考高教社杯全国大学生数学建模竞赛（CUMCM）2025 年 LaTeX 模板和 "
        "format2025 要求，额外生成 gmcmthesis LaTeX sidecar，DOCX 导出套用 "
        "format2025 页面/字体样式。"
    ),
    pdf_variables=[
        "documentclass=ctexart",
        "classoption=scheme=chinese",
        "papersize=a4",
        "CJKmainfont=SimSun",
        "CJKsansfont=SimHei",
        "mainfont=Times New Roman",
        "pagestyle=plain",
        PDF_HEADING_STYLE,
        PDF_CODE_BLOCK_STYLE,
        "geometry:left=3.17cm,right=3.17cm,top=3cm,bottom=2.5cm",
        "fontsize=12pt",
    ],
    pdf_extra_args=["--toc", "--number-sections"],
    latex_template_dir=CUMCM2025_TEMPLATE_DIR,
    latex_template_key="zh/cumcm2025-gmcmthesis",
    docx_reference_doc=CUMCM2025_DOCX_REFERENCE,
)

# `cumcm2026` is a provisional implementation based on the 2026 revised
# formatting specification. The official site currently publishes a formatting
# specification, not a 2026 LaTeX source package.  Do not reuse the 2025
# gmcmthesis resources here: its \maketitle emits the legacy cover with school,
# team-number and member fields, which must not appear in the electronic paper.
# The DOCX reference remains a temporary 2025 compatibility resource until an
# official 2026 Word/DOCX template is published.  When official templates
# appear, replace these paths following docs/md/CUMCM2026模板替换指南.md.
CUMCM2026_PROFILE = ExportProfileConfig(
    key=ExportProfile.CUMCM2026,
    label="高教社杯/CUMCM 2026 模板",
    description=(
        "对齐高教社杯全国大学生数学建模竞赛（CUMCM）论文格式规范（2026 年修订稿）："
        "电子版从摘要页开始，不生成目录；正文页边距满足至少 2.5cm，"
        "主 PDF 底边距使用 2.8cm 保守留白以避免字形 bbox 侵入保护区。"
    ),
    pdf_variables=[
        "documentclass=ctexart",
        "classoption=scheme=chinese",
        "papersize=a4",
        "CJKmainfont=SimSun",
        "CJKsansfont=SimHei",
        "mainfont=Times New Roman",
        "pagestyle=plain",
        PDF_HEADING_STYLE,
        PDF_CODE_BLOCK_STYLE,
        PDF_PARAGRAPH_BREAK_STYLE,
        "geometry:left=3.17cm,right=3.17cm,top=3cm,bottom=2.8cm",
        "fontsize=12pt",
    ],
    pdf_extra_args=[],
    latex_template_key="zh/cumcm2026-ctexart",
    docx_reference_doc=CUMCM2025_DOCX_REFERENCE,
    pdf_appendix_pagebreak=True,
)

HUASHUBEI_PROFILE = ExportProfileConfig(
    key=ExportProfile.HUASHUBEI,
    label="华数杯模板",
    description=(
        "按现有 Huashubei 模板做版式参数级接入：A4、12pt、2.5cm 页边距、"
        "1.6 倍行距和 14pt 居中一级标题；官方规范发布后需复核。"
    ),
    pdf_variables=[
        "documentclass=ctexart",
        "classoption=scheme=chinese",
        "papersize=a4",
        "CJKmainfont=SimSun",
        "CJKsansfont=SimHei",
        "mainfont=Times New Roman",
        "pagestyle=plain",
        HUASHUBEI_PDF_HEADING_STYLE,
        PDF_CODE_BLOCK_STYLE,
        HUASHUBEI_GEOMETRY,
        "fontsize=12pt",
        "linestretch=1.6",
        # 图形随文定位：禁止浮动体漂移到下一页顶端插断句子（评审反馈的版式问题）。
        "header-includes=\\usepackage{float}\\floatplacement{figure}{H}",
        # 孤行/寡行治理：避免整句仅一两字被拆到下一页页首（评审反馈 p9→p10）。
        (
            "header-includes=\\widowpenalty=10000 \\clubpenalty=10000 "
            "\\displaywidowpenalty=10000"
        ),
        # 图片高度上限：过高图形在 [H] 下会留下大段页尾空白（评审反馈 p6），
        # 统一限高 60% 文本区并保持纵横比；\linewidth 无需模板前置定义，宽图
        # 同时收敛到行宽，杜绝溢出。
        (
            "header-includes=\\setkeys{Gin}{width=\\linewidth,"
            "height=0.60\\textheight,keepaspectratio}"
        ),
    ],
    pdf_extra_args=[],
    latex_template_key="zh/huashubei-latex",
)


_PROFILES = {
    ExportProfile.DEFAULT: DEFAULT_PROFILE,
    ExportProfile.CUMCM2025: CUMCM2025_PROFILE,
    ExportProfile.CUMCM2026: CUMCM2026_PROFILE,
    ExportProfile.HUASHUBEI: HUASHUBEI_PROFILE,
}


def normalize_export_profile(profile: ExportProfile | str | None) -> ExportProfile:
    """Return a valid export profile enum, falling back to default."""
    if isinstance(profile, ExportProfile):
        return profile
    if not profile:
        return ExportProfile.DEFAULT
    try:
        return ExportProfile(str(profile))
    except ValueError:
        return ExportProfile.DEFAULT


def get_export_profile_config(
    profile: ExportProfile | str | None,
) -> ExportProfileConfig:
    """Get export profile configuration."""
    return _PROFILES[normalize_export_profile(profile)]


def list_export_profiles() -> list[dict]:
    """Return metadata suitable for API/UI display."""
    return [
        {
            "key": config.key.value,
            "label": config.label,
            "description": config.description,
        }
        for config in _PROFILES.values()
    ]
