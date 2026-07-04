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


PDF_HEADING_STYLE = (
    r"header-includes=\ctexset{"
    r"section={format={\centering\zihao{3}\heiti}},"
    r"subsection={format={\zihao{4}\heiti}},"
    r"subsubsection={format={\normalsize\heiti}}"
    r"}"
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
        "geometry:left=3.17cm,right=3.17cm,top=2.6cm,bottom=2.6cm",
        "fontsize=12pt",
    ],
    pdf_extra_args=[],
)


CUMCM2025_TEMPLATE_DIR = os.path.join(TEMPLATES_ROOT, "cumcm2025")

CUMCM2025_PROFILE = ExportProfileConfig(
    key=ExportProfile.CUMCM2025,
    label="CUMCM 2025 模板",
    description=(
        "参考 2025 年 LaTeX 模板和 format2025 要求，额外生成 "
        "gmcmthesis LaTeX sidecar；DOCX reference-doc 仅在配置为 .docx 时启用。"
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
        "geometry:left=3.17cm,right=3.17cm,top=3cm,bottom=2.5cm",
        "fontsize=12pt",
    ],
    pdf_extra_args=["--toc", "--number-sections"],
    latex_template_dir=CUMCM2025_TEMPLATE_DIR,
    latex_template_key="zh/cumcm2025-gmcmthesis",
)


_PROFILES = {
    ExportProfile.DEFAULT: DEFAULT_PROFILE,
    ExportProfile.CUMCM2025: CUMCM2025_PROFILE,
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
