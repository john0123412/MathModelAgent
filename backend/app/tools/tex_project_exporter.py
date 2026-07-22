"""LaTeX sidecar 导出工具模块。

在不改变 res.md/res.pdf/res.docx 直出结果的前提下，额外生成一份可被
math-modeling-skills 导入继续精修的 LaTeX 项目（latex_project/），
供后续人工/工具做更精细的排版和 preflight 校验。

本模块只是把 res.md 原样转换为 LaTeX 片段并包一层可编译的最小 main.tex 壳，
不会重写、润色或删减论文正文内容。
"""

import os
import shutil
# subprocess is limited to controlled Pandoc/XeLaTeX export invocations below.
import subprocess  # nosec B404
import json
import re
from app.utils.log_util import logger
from app.schemas.enums import ExportProfile
from app.tools.export_profiles import HUASHUBEI_PAGE_MARGIN, get_export_profile_config

SECTION_INPUTS_PLACEHOLDER = "% MMA_SECTION_INPUTS"
# Do not pass model-generated raw TeX through to the compiler. Math delimiters
# remain supported, while commands such as \\input and \\write18 are rendered as text.
PANDOC_LATEX_MARKDOWN_FORMAT = "markdown-raw_tex+tex_math_dollars+tex_math_single_backslash+pipe_tables"
FENCED_CODE_RE = re.compile(r"^\s*(```+|~~~+)")
NOTEBOOK_CELL_HEADING_RE = re.compile(r"^#\s+Cell\s+\d+\s*$")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
LATEX_INCLUDEGRAPHICS_RE = re.compile(
    r"\\(?:pandocbounded\s*)?\{?\s*\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}"
    r"|\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}"
)
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".pdf", ".eps", ".bmp", ".webp")
LATEX_SAFE_ASSET_BASENAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

_MAIN_TEX_TEMPLATE = r"""% !TEX program = xelatex
% =============================================================================
%  LaTeX sidecar 导出（由 MathModelAgent 自动生成）
%  正文由 pandoc 将 res.md 原样转换为 LaTeX 片段（sections/imported_body.tex），
%  本文件只提供一个可用 xelatex 编译的最小外壳，不重写论文内容。
%  可交由 math-modeling-skills 导入后继续精修排版。
%  编译方式：xelatex main.tex（或 latexmk -xelatex main.tex）
% =============================================================================
\documentclass[a4paper,12pt]{ctexart}

\usepackage[a4paper, margin=2.5cm]{geometry}
\usepackage{graphicx}
\usepackage{float}
\usepackage{booktabs}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{hyperref}
\usepackage{longtable}
\usepackage{listings}
\lstset{
  breaklines=true,
  breakatwhitespace=false,
  columns=fullflexible,
  keepspaces=true,
  showspaces=false,
  showstringspaces=false,
  showtabs=false,
  basicstyle=\ttfamily\footnotesize
}
\providecommand{\tightlist}{\setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}}

% 兼容新版 pandoc 图片片段：限制图片不超过文本区域，并定义 \pandocbounded。
\makeatletter
\def\maxwidth{\ifdim\Gin@nat@width>\linewidth\linewidth\else\Gin@nat@width\fi}
\def\maxheight{\ifdim\Gin@nat@height>\textheight\textheight\else\Gin@nat@height\fi}
\makeatother
\setkeys{Gin}{width=\maxwidth,height=\maxheight,keepaspectratio}
\providecommand{\pandocbounded}[1]{#1}
\providecommand{\passthrough}[1]{#1}

% pandoc 对无标题的 longtable 会输出 \def\LTcaptype{none}，若当前文档类/宏包
% （如 caption）未定义名为 "none" 的计数器会导致编译报错，这里兜底定义一次。
\makeatletter
\@ifundefined{c@none}{\newcounter{none}}{}
\makeatother

% 图片可能位于 latex_project 本身、其上级 work_dir，或复制后的 figures/ 目录
\graphicspath{{./}{../}{sections/}{figures/}}

\begin{document}

% MMA_SECTION_INPUTS

\end{document}
"""

_CUMCM2025_MAIN_TEX_TEMPLATE = r"""% !TEX program = xelatex
% =============================================================================
%  CUMCM 2025 LaTeX sidecar（由 MathModelAgent 自动生成）
%  模板资源来自 2025 年 LaTeX 模板：gmcmthesis.cls、figures/logo2025.png、
%  figures/title2025.pdf。正文由 pandoc 从 res.md 转为 sections/imported_body.tex。
%  本文件只负责套用竞赛模板外壳，不重写论文内容；最终提交前请人工校对封面信息、
%  摘要/关键词位置、目录、附录和参考文献。
% =============================================================================
\documentclass[bwprint]{gmcmthesis}

\usepackage{amsmath}
\usepackage{pdfpages}
\usepackage{float}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{listings}
\lstset{
  breaklines=true,
  breakatwhitespace=false,
  columns=fullflexible,
  keepspaces=true,
  showspaces=false,
  showstringspaces=false,
  showtabs=false,
  basicstyle=\ttfamily\footnotesize
}
\providecommand{\tightlist}{\setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}}

% 兼容新版 pandoc 图片片段：限制图片不超过文本区域，并定义 \pandocbounded。
\makeatletter
\def\maxwidth{\ifdim\Gin@nat@width>\linewidth\linewidth\else\Gin@nat@width\fi}
\def\maxheight{\ifdim\Gin@nat@height>\textheight\textheight\else\Gin@nat@height\fi}
\makeatother
\setkeys{Gin}{width=\maxwidth,height=\maxheight,keepaspectratio}
\providecommand{\pandocbounded}[1]{#1}
\providecommand{\passthrough}[1]{#1}

% pandoc 对无标题的 longtable 会输出 \def\LTcaptype{none}，gmcmthesis.cls 依赖的
% caption 宏包会据此查找名为 "none" 的计数器，这里兜底定义一次避免编译报错。
\makeatletter
\@ifundefined{c@none}{\newcounter{none}}{}
\makeatother

\graphicspath{{./}{../}{sections/}{figures/}}

\numberwithin{figure}{section}
\renewcommand{\thefigure}{\arabic{section}-\arabic{figure}}

\title{数学建模论文}
\baominghao{}
\schoolname{}
\membera{}
\memberb{}
\memberc{}

\begin{document}
\maketitle
\tableofcontents

% MMA_SECTION_INPUTS

\end{document}
"""

# The official 2026 specification requires the electronic paper to start with
# the abstract and excludes the commitment letter and numbered cover page.  The
# legacy 2025 gmcmthesis class cannot be used here because its \maketitle
# unconditionally emits those cover-style identity fields.  This deliberately
# minimal ctexart shell lets the generated Markdown supply the title, abstract
# and keywords on page one, without adding a cover or a table of contents.
# If an official 2026 LaTeX package is released, replace this structure while
# preserving % MMA_SECTION_INPUTS so generated sections/*.tex remain usable.
_CUMCM2026_MAIN_TEX_TEMPLATE = r"""% !TEX program = xelatex
% =============================================================================
%  CUMCM 2026 LaTeX sidecar（由 MathModelAgent 自动生成）
%  对齐《全国大学生数学建模竞赛论文格式规范（2026年修订稿）》电子版要求：
%  不生成承诺书、编号专用页、身份封面或目录；首个输入内容应为题目、摘要和关键词。
%  正文由 pandoc 从 res.md 转为 sections/*.tex，本文件不重写论文内容。
% =============================================================================
\documentclass[a4paper,12pt]{ctexart}

% 官方规范要求各边页边距至少 2.5cm；此处沿用主 PDF 的保守边距。
\usepackage[a4paper,left=31.7mm,right=31.7mm,top=30mm,bottom=28mm]{geometry}
\usepackage{graphicx}
\usepackage{float}
\usepackage{booktabs}
\usepackage{array}
\usepackage{calc}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{hyperref}
\usepackage{longtable}
\usepackage{listings}
\lstset{
  breaklines=true,
  breakatwhitespace=false,
  columns=fullflexible,
  keepspaces=true,
  showspaces=false,
  showstringspaces=false,
  showtabs=false,
  basicstyle=\ttfamily\footnotesize
}
\providecommand{\tightlist}{\setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}}

% 兼容新版 pandoc 图片片段：限制图片不超过文本区域，并定义 \pandocbounded。
\makeatletter
\def\maxwidth{\ifdim\Gin@nat@width>\linewidth\linewidth\else\Gin@nat@width\fi}
\def\maxheight{\ifdim\Gin@nat@height>\textheight\textheight\else\Gin@nat@height\fi}
\makeatother
\setkeys{Gin}{width=\maxwidth,height=\maxheight,keepaspectratio}
\providecommand{\pandocbounded}[1]{#1}
\providecommand{\passthrough}[1]{#1}

% pandoc 对无标题的 longtable 会输出 \def\LTcaptype{none}；兜底定义计数器。
\makeatletter
\@ifundefined{c@none}{\newcounter{none}}{}
\makeatother

\graphicspath{{./}{../}{sections/}{figures/}}
\pagestyle{plain}

\begin{document}

% MMA_SECTION_INPUTS

\end{document}
"""

_HUASHUBEI_MAIN_TEX_TEMPLATE = rf"""% !TEX program = xelatex
% =============================================================================
%  华数杯 LaTeX sidecar（由 MathModelAgent 自动生成）
%  当前阶段只接入版式参数，并继续使用 sections/imported_body.tex 单正文输入。
%  不直接套用 skills/5writing/templates/zh/huashubei-latex/main.tex 的结构化
%  sections/1_restatement.tex 等输入，避免破坏现有 Harness 导出链路。
% =============================================================================
\documentclass[12pt,a4paper]{{ctexart}}

\usepackage[a4paper, top={HUASHUBEI_PAGE_MARGIN}, bottom={HUASHUBEI_PAGE_MARGIN}, left={HUASHUBEI_PAGE_MARGIN}, right={HUASHUBEI_PAGE_MARGIN}]{{geometry}}
\usepackage{{amsmath}}
\usepackage{{amssymb}}
\usepackage{{graphicx}}
\usepackage{{float}}
\usepackage{{booktabs}}
\usepackage{{array}}
\usepackage{{longtable}}
\usepackage{{xcolor}}
\usepackage{{listings}}
\usepackage{{titlesec}}
\usepackage{{enumitem}}
\usepackage{{hyperref}}
\providecommand{{\tightlist}}{{\setlength{{\itemsep}}{{0pt}}\setlength{{\parskip}}{{0pt}}}}

% 兼容新版 pandoc 图片片段：限制图片不超过文本区域，并定义 \pandocbounded。
\makeatletter
\def\maxwidth{{\ifdim\Gin@nat@width>\linewidth\linewidth\else\Gin@nat@width\fi}}
\def\maxheight{{\ifdim\Gin@nat@height>\textheight\textheight\else\Gin@nat@height\fi}}
\makeatother
\setkeys{{Gin}}{{width=\maxwidth,height=\maxheight,keepaspectratio}}
\providecommand{{\pandocbounded}}[1]{{#1}}
\providecommand{{\passthrough}}[1]{{#1}}

\IfFontExistsTF{{Times New Roman}}{{\setmainfont{{Times New Roman}}}}{{}}
\linespread{{1.6}}
\setlength{{\parindent}}{{2em}}
\pagestyle{{plain}}

\ctexset{{
  section/number       = \chinese{{section}},
  subsection/number    = \arabic{{section}}.\arabic{{subsection}},
  subsubsection/number = \arabic{{section}}.\arabic{{subsection}}.\arabic{{subsubsection}},
}}

\titleformat{{\section}}
  {{\centering\fontsize{{14pt}}{{16.8pt}}\heiti\bfseries}}
  {{\chinese{{section}}、}}{{1em}}{{}}
\titleformat{{\subsection}}
  {{\fontsize{{12pt}}{{14.4pt}}\heiti\bfseries}}
  {{\arabic{{section}}.\arabic{{subsection}}}}{{1em}}{{}}
\titleformat{{\subsubsection}}
  {{\fontsize{{12pt}}{{14.4pt}}\heiti\bfseries}}
  {{\arabic{{section}}.\arabic{{subsection}}.\arabic{{subsubsection}}}}{{1em}}{{}}
\titlespacing{{\section}}       {{0pt}}{{1.52em}}{{1.15em}}
\titlespacing{{\subsection}}    {{0pt}}{{1.18em}}{{1.18em}}
\titlespacing{{\subsubsection}} {{0pt}}{{0.9em}}{{0.75em}}

\setlist[enumerate]{{label=\arabic*、, leftmargin=2em}}
\lstset{{
  basicstyle=\ttfamily\footnotesize,
  backgroundcolor=\color{{black!3}},
  frame=single,
  framesep=6pt,
  rulecolor=\color{{black!30}},
  framerule=0.8pt,
  breaklines=true,
  showstringspaces=false,
  columns=fullflexible,
  keepspaces=true,
}}

% pandoc 对无标题的 longtable 会输出 \def\LTcaptype{{none}}，这里兜底定义一次。
\makeatletter
\@ifundefined{{c@none}}{{\newcounter{{none}}}}{{}}
\makeatother

\graphicspath{{{{./}}{{../}}{{sections/}}{{figures/}}}}

\begin{{document}}

% MMA_SECTION_INPUTS

\end{{document}}
"""


def _copy_template_assets(template_dir: str | None, latex_project_dir: str) -> list[str]:
    """Copy bundled template files into latex_project and return relative paths."""
    if not template_dir or not os.path.isdir(template_dir):
        return []

    copied: list[str] = []
    for root, dirs, files in os.walk(template_dir):
        dirs[:] = [d for d in dirs if d not in {"__MACOSX", ".git", "__pycache__"}]
        rel_root = os.path.relpath(root, template_dir)
        target_root = (
            latex_project_dir
            if rel_root == "."
            else os.path.join(latex_project_dir, rel_root)
        )
        os.makedirs(target_root, exist_ok=True)
        for filename in files:
            if filename.startswith("._") or filename == ".DS_Store":
                continue
            src = os.path.join(root, filename)
            dst = os.path.join(target_root, filename)
            shutil.copy2(src, dst)
            copied.append(os.path.relpath(dst, latex_project_dir).replace(os.sep, "/"))
    return sorted(copied)


def _clean_asset_path(path: str) -> str:
    path = path.strip().strip("<>").strip()
    path = path.split("#", 1)[0].split("?", 1)[0].strip()
    path = _unescape_latex_asset_path(path)
    return path.replace("\\", "/")


def _unescape_latex_asset_path(path: str) -> str:
    """Undo pandoc/LaTeX escaping for local file names before filesystem lookup."""
    replacements = {
        r"\%": "%",
        r"\#": "#",
        r"\&": "&",
        r"\_": "_",
        r"\$": "$",
        r"\{": "{",
        r"\}": "}",
    }
    for escaped, literal in replacements.items():
        path = path.replace(escaped, literal)
    return path


def _is_local_image_path(path: str) -> bool:
    cleaned = _clean_asset_path(path)
    if not cleaned:
        return False
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", cleaned):
        return False
    return os.path.splitext(cleaned.lower())[1] in IMAGE_EXTENSIONS


def _extract_referenced_assets(markdown: str, tex_paths: list[str]) -> list[str]:
    references: set[str] = set()
    for match in MARKDOWN_IMAGE_RE.finditer(markdown):
        path = _clean_asset_path(match.group(1))
        if _is_local_image_path(path):
            references.add(path)

    for tex_path in tex_paths:
        try:
            with open(tex_path, encoding="utf-8") as f:
                tex = f.read()
        except OSError:
            continue
        for match in LATEX_INCLUDEGRAPHICS_RE.finditer(tex):
            path = _clean_asset_path(match.group(1) or match.group(2) or "")
            if _is_local_image_path(path):
                references.add(path)

    return sorted(references)


def _asset_source_path(work_dir: str, reference: str) -> str | None:
    source = os.path.normpath(os.path.join(work_dir, reference.replace("/", os.sep)))
    work_dir_abs = os.path.abspath(work_dir)
    source_abs = os.path.abspath(source)
    try:
        if os.path.commonpath([work_dir_abs, source_abs]) != work_dir_abs:
            return None
    except ValueError:
        return None
    return source


def _copy_file_once(src: str, dst: str) -> bool:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        try:
            if os.path.samefile(src, dst):
                return False
        except OSError:
            pass
    try:
        shutil.copy2(src, dst)
    except PermissionError:
        # Windows bind mounts can accept the file bytes but reject the
        # chmod/utime metadata phase performed by copy2.  A LaTeX sidecar
        # only needs an exact byte copy; retry with copyfile and still let
        # genuine content-copy errors propagate.
        shutil.copyfile(src, dst)
    return True


def _latex_safe_asset_basename(reference: str, index: int, used: set[str]) -> str:
    basename = os.path.basename(reference.replace("\\", "/"))
    if LATEX_SAFE_ASSET_BASENAME_RE.match(basename):
        return basename

    _, ext = os.path.splitext(basename)
    if ext.lower() not in IMAGE_EXTENSIONS:
        ext = ".png"
    candidate = f"figure_{index:02d}{ext.lower()}"
    while candidate in used:
        index += 1
        candidate = f"figure_{index:02d}{ext.lower()}"
    return candidate


def _rewrite_latex_asset_references(tex_paths: list[str], rewrites: dict[str, str]) -> None:
    if not rewrites:
        return

    for tex_path in tex_paths:
        try:
            with open(tex_path, encoding="utf-8") as f:
                tex = f.read()
        except OSError:
            continue

        def replace_includegraphics(match: re.Match[str]) -> str:
            raw_path = match.group(1) or match.group(2) or ""
            replacement = rewrites.get(_clean_asset_path(raw_path))
            if not replacement:
                return match.group(0)
            return match.group(0).replace(raw_path, replacement)

        updated = LATEX_INCLUDEGRAPHICS_RE.sub(replace_includegraphics, tex)
        if updated != tex:
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(updated)


def _copy_referenced_assets(
    work_dir: str,
    latex_project_dir: str,
    markdown: str,
    tex_paths: list[str],
) -> tuple[list[str], list[str]]:
    """Copy local figures referenced by Markdown/LaTeX into latex_project."""
    copied: set[str] = set()
    missing: list[str] = []
    rewrites: dict[str, str] = {}
    used_safe_names: set[str] = set()
    figures_dir = os.path.join(latex_project_dir, "figures")

    for index, reference in enumerate(_extract_referenced_assets(markdown, tex_paths), 1):
        src = _asset_source_path(work_dir, reference)
        if not src or not os.path.exists(src):
            missing.append(reference)
            continue

        reference_parts = [
            part for part in reference.replace("\\", "/").split("/") if part and part != "."
        ]
        if not reference_parts or any(part == ".." for part in reference_parts):
            reference_parts = [os.path.basename(reference)]

        safe_basename = _latex_safe_asset_basename(reference, index, used_safe_names)
        used_safe_names.add(safe_basename)
        if safe_basename == os.path.basename(reference):
            candidate_targets = [
                os.path.join(latex_project_dir, *reference_parts),
                os.path.join(figures_dir, os.path.basename(reference)),
            ]
        else:
            safe_reference = f"figures/{safe_basename}"
            rewrites[reference] = safe_reference
            candidate_targets = [os.path.join(latex_project_dir, safe_reference)]

        for dst in candidate_targets:
            if _copy_file_once(src, dst):
                copied.add(os.path.relpath(dst, latex_project_dir).replace(os.sep, "/"))

    _rewrite_latex_asset_references(tex_paths, rewrites)
    return sorted(copied), sorted(missing)


def _write_status(status_path: str, result: dict) -> None:
    """将导出结果写入 tex_export_status.json。"""
    try:
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"写入 tex_export_status.json 失败: {e}")


def _clear_stale_latex_build_files(latex_project_dir: str) -> None:
    """Remove only known transient files that can poison a fresh compile."""
    for filename in (
        "main.aux",
        "main.toc",
        "main.out",
        "main.fls",
        "main.fdb_latexmk",
        "main.xdv",
        "main.log",
        "main.synctex.gz",
    ):
        path = os.path.join(latex_project_dir, filename)
        if os.path.isfile(path):
            os.remove(path)


def _section_filename(index: int, title: str) -> str:
    lowered = title.lower()
    if "摘要" in title or "关键词" in title:
        suffix = "abstract"
    elif "参考文献" in title:
        suffix = "references"
    elif "附录" in title:
        suffix = "appendix"
    elif "问题重述" in title:
        suffix = "problem"
    elif "问题分析" in title:
        suffix = "analysis"
    elif "模型假设" in title:
        suffix = "assumptions"
    elif "符号说明" in title:
        suffix = "symbols"
    elif "模型" in title and ("建立" in title or "求解" in title):
        suffix = "model"
    elif "检验" in title or "分析" in title or "敏感性" in title or "灵敏度" in title:
        suffix = "validation"
    elif "评价" in title or "推广" in title:
        suffix = "evaluation"
    else:
        suffix = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_") or "section"
    return f"{index:02d}_{suffix}.tex"


def _normalize_markdown_for_latex_sidecar(markdown: str) -> str:
    """Fence raw notebook cell blocks before handing Markdown to pandoc."""
    lines = markdown.splitlines(keepends=True)
    output: list[str] = []
    in_cell = False
    cell_fence_open = False
    in_source_fence = False
    source_fence_marker = ""

    for line in lines:
        fence_match = FENCED_CODE_RE.match(line)
        if fence_match and not cell_fence_open:
            marker = fence_match.group(1)
            if not in_source_fence:
                in_source_fence = True
                source_fence_marker = marker[:3]
            elif marker.startswith(source_fence_marker):
                in_source_fence = False
                source_fence_marker = ""
            output.append(line)
            continue

        if in_source_fence:
            output.append(line)
            continue

        if NOTEBOOK_CELL_HEADING_RE.match(line.strip()):
            if cell_fence_open:
                output.append("\n````\n")
                cell_fence_open = False
            output.append(line)
            in_cell = True
            continue

        if in_cell:
            if not cell_fence_open and line.strip():
                output.append("````python\n")
                cell_fence_open = True
            output.append(line)
            continue

        output.append(line)

    if cell_fence_open:
        output.append("\n````\n")

    return "".join(output)


def _iter_top_level_headings(markdown: str) -> list[tuple[int, int, str]]:
    headings: list[tuple[int, int, str]] = []
    in_fence = False
    fence_marker = ""
    position = 0

    for line in markdown.splitlines(keepends=True):
        fence_match = FENCED_CODE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker[:3]
            elif marker.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
        elif not in_fence:
            heading_match = re.match(r"^#\s+(.+?)\s*$", line)
            if heading_match:
                headings.append(
                    (
                        position,
                        position + len(line),
                        heading_match.group(1).strip(),
                    )
                )
        position += len(line)

    return headings


def _split_markdown_sections(markdown: str) -> list[dict]:
    """按 Markdown 顶层标题拆分为结构化 LaTeX sections 输入。"""
    matches = _iter_top_level_headings(markdown)
    sections: list[dict] = []
    if not matches:
        return sections

    front_matter = markdown[: matches[0][0]].strip()
    if front_matter:
        sections.append(
            {
                "title": "front_matter",
                "filename": "00_front_matter.tex",
                "markdown": front_matter + "\n",
            }
        )

    for index, match in enumerate(matches, 1):
        end = matches[index][0] if index < len(matches) else len(markdown)
        title = match[2]
        chunk = markdown[match[0] : end].strip()
        if not chunk:
            continue
        sections.append(
            {
                "title": title,
                "filename": _section_filename(index, title),
                "markdown": chunk + "\n",
            }
        )
    return sections


def _run_pandoc_to_latex(
    md_path: str,
    tex_path: str,
    work_dir: str,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    command = [
        "pandoc",
        md_path,
        "-f",
        PANDOC_LATEX_MARKDOWN_FORMAT,
        "-t",
        "latex",
        "-o",
        tex_path,
        "--listings",
        "--resource-path",
        work_dir,
    ]
    # Command is fixed; task paths are created under the controlled work directory.
    return subprocess.run(  # noqa: S603  # nosec B603
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )


def _run_pandoc_markdown_to_latex(
    markdown: str,
    tex_path: str,
    sections_dir: str,
    work_dir: str,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    temp_md_path = os.path.join(sections_dir, "_pandoc_input.md")
    try:
        with open(temp_md_path, "w", encoding="utf-8") as f:
            f.write(markdown)
        return _run_pandoc_to_latex(temp_md_path, tex_path, work_dir, timeout=timeout)
    finally:
        try:
            if os.path.exists(temp_md_path):
                os.remove(temp_md_path)
        except OSError:
            pass


def _latex_output_tail(proc: subprocess.CompletedProcess[str]) -> dict[str, str]:
    return {
        "stdout": proc.stdout[-2000:],
        "stderr": proc.stderr[-2000:],
    }


def _extract_latex_failure_summary(stdout: str, stderr: str) -> str:
    """Extract a compact human-readable LaTeX error summary for status JSON."""
    combined = "\n".join(part for part in [stdout, stderr] if part)
    summary_lines: list[str] = []
    for line in combined.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if (
            stripped.startswith("!")
            or "LaTeX Warning: File `" in stripped
            or stripped.startswith("l.")
        ):
            summary_lines.append(stripped)
        if len(summary_lines) >= 8:
            break
    return "\n".join(summary_lines)


def _run_xelatex_twice(
    latex_project_dir: str,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    """Run xelatex twice so references/toc-like side effects can settle."""
    cmd = [
        "xelatex",
        "-no-shell-escape",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "main.tex",
    ]
    first_proc = subprocess.run(  # noqa: S603  # nosec B603
        cmd,
        cwd=latex_project_dir,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    if first_proc.returncode != 0:
        return first_proc
    second_proc = subprocess.run(  # noqa: S603  # nosec B603
        cmd,
        cwd=latex_project_dir,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    if second_proc.returncode != 0:
        second_proc.stdout = first_proc.stdout + "\n" + second_proc.stdout
        second_proc.stderr = first_proc.stderr + "\n" + second_proc.stderr
    return second_proc


def _write_structured_sections(
    markdown: str,
    sections_dir: str,
    work_dir: str,
) -> tuple[list[dict], str]:
    """生成结构化 sections/*.tex，并返回可写入 main.tex 的 input 列表。"""
    section_specs = _split_markdown_sections(markdown)
    if not section_specs:
        return [], r"\input{sections/imported_body}"

    generated: list[dict] = []
    for spec in section_specs:
        filename = spec["filename"]
        md_section_path = os.path.join(sections_dir, filename.replace(".tex", ".md"))
        tex_section_path = os.path.join(sections_dir, filename)
        proc: subprocess.CompletedProcess[str] | None = None
        try:
            with open(md_section_path, "w", encoding="utf-8") as f:
                f.write(spec["markdown"])
            proc = _run_pandoc_to_latex(md_section_path, tex_section_path, work_dir)
        finally:
            try:
                if os.path.exists(md_section_path):
                    os.remove(md_section_path)
            except OSError:
                pass
        if proc is None or proc.returncode != 0 or not os.path.exists(tex_section_path):
            raise RuntimeError(
                "结构化章节转换失败: "
                f"{filename}, returncode={None if proc is None else proc.returncode}, "
                f"stderr={'' if proc is None else proc.stderr}"
            )
        generated.append(
            {
                "title": spec["title"],
                "path": f"latex_project/sections/{filename}",
            }
        )

    section_inputs = "\n".join(
        rf"\input{{sections/{os.path.basename(item['path'])}}}" for item in generated
    )
    return generated, section_inputs


def _render_main_tex(template: str, section_inputs: str) -> str:
    return template.replace(SECTION_INPUTS_PLACEHOLDER, section_inputs)


def export_markdown_to_latex_project(
    md_path: str,
    work_dir: str,
    template_key: str | None = None,
    export_profile: ExportProfile | str | None = ExportProfile.DEFAULT,
) -> dict:
    """将 res.md 导出为一个可被外部继续精修的 LaTeX sidecar 项目。

    产出：
        work_dir/latex_project/sections/imported_body.tex （pandoc 转换的正文片段）
        work_dir/latex_project/main.tex                    （最小可编译外壳）
        work_dir/tex_export_status.json                    （结构化导出结果）

    任何环境缺失（文件不存在、未安装 pandoc）或转换失败都不会抛出异常，
    仅在返回结果和 tex_export_status.json 中说明原因，不中断调用方（workflow）流程。

    Args:
        md_path: 待转换的 res.md 路径。
        work_dir: 任务工作目录路径。
        template_key: 预留的目标模板标识（供下游 math-modeling-skills 参考使用），
            当前实现不会据此重写正文内容，仅记录在返回结果和状态文件中。

    Returns:
        结构化结果字典，包含 enabled/success/template_key/latex_project_dir/
        main_tex/imported_body/reason/command/stderr/compile_attempted/
        compile_success/compile_reason。
    """
    profile_config = get_export_profile_config(export_profile)
    effective_template_key = template_key or profile_config.latex_template_key

    result = {
        "enabled": False,
        "success": False,
        "export_profile": profile_config.key.value,
        "template_key": effective_template_key,
        "latex_project_dir": None,
        "main_tex": None,
        "imported_body": None,
        "structured_sections": [],
        "structured_section_count": 0,
        "main_uses_structured_sections": False,
        "template_assets": [],
        "copied_assets": [],
        "missing_assets": [],
        "reason": "",
        "command": [],
        "stderr": "",
        "compile_attempted": False,
        "compile_success": False,
        "compile_reason": "",
        "compile_stdout_tail": "",
        "compile_stderr_tail": "",
        "compile_failure_summary": "",
        "compile_command": [],
        "compile_fallback_command": [],
    }

    status_path = os.path.join(work_dir, "tex_export_status.json")
    latex_project_dir = os.path.join(work_dir, "latex_project")
    sections_dir = os.path.join(latex_project_dir, "sections")

    if not os.path.exists(md_path):
        result["reason"] = f"Markdown 文件不存在: {md_path}"
        logger.warning(f"LaTeX sidecar 导出跳过: {result['reason']}")
        _write_status(status_path, result)
        return result

    if shutil.which("pandoc") is None:
        result["reason"] = "未检测到 pandoc 可执行文件，跳过 LaTeX sidecar 导出"
        logger.warning(f"LaTeX sidecar 导出跳过: {result['reason']}")
        _write_status(status_path, result)
        return result

    try:
        os.makedirs(sections_dir, exist_ok=True)
        with open(md_path, encoding="utf-8") as f:
            markdown = f.read()
        latex_markdown = _normalize_markdown_for_latex_sidecar(markdown)
    except Exception as e:
        result["reason"] = f"准备 latex_project 失败: {e}"
        logger.error(f"LaTeX sidecar 导出失败: {type(e).__name__}")
        _write_status(status_path, result)
        return result

    imported_body_path = os.path.join(sections_dir, "imported_body.tex")
    command = [
        "pandoc",
        md_path,
        "-f",
        PANDOC_LATEX_MARKDOWN_FORMAT,
        "-t",
        "latex",
        "-o",
        imported_body_path,
        "--listings",
        "--resource-path",
        work_dir,
    ]
    result["enabled"] = True
    result["command"] = command

    try:
        proc = _run_pandoc_markdown_to_latex(
            latex_markdown, imported_body_path, sections_dir, work_dir
        )
    except subprocess.TimeoutExpired:
        result["reason"] = "LaTeX 正文转换超时（120秒）"
        logger.error(f"LaTeX sidecar 导出超时: {md_path}")
        _write_status(status_path, result)
        return result
    except Exception as e:
        result["reason"] = f"LaTeX 正文转换异常: {e}"
        logger.error(f"LaTeX sidecar 导出异常: {type(e).__name__}")
        _write_status(status_path, result)
        return result

    if proc.returncode != 0 or not os.path.exists(imported_body_path):
        result["reason"] = f"pandoc 转换返回码非 0: {proc.returncode}"
        result["stderr"] = proc.stderr
        logger.error(
            "LaTeX sidecar 正文转换失败: "
            f"returncode={proc.returncode}, stderr_chars={len(proc.stderr or '')}"
        )
        _write_status(status_path, result)
        return result

    result["imported_body"] = "latex_project/sections/imported_body.tex"

    try:
        structured_sections, section_inputs = _write_structured_sections(
            latex_markdown, sections_dir, work_dir
        )
    except Exception as e:
        result["reason"] = str(e)
        logger.error(f"LaTeX sidecar 结构化章节导出失败: {type(e).__name__}")
        _write_status(status_path, result)
        return result
    result["structured_sections"] = structured_sections
    result["structured_section_count"] = len(structured_sections)
    result["main_uses_structured_sections"] = bool(structured_sections)

    try:
        tex_paths = [imported_body_path] + [
            os.path.join(work_dir, item["path"].replace("/", os.sep))
            for item in structured_sections
        ]
        copied_assets, missing_assets = _copy_referenced_assets(
            work_dir, latex_project_dir, latex_markdown, tex_paths
        )
        result["copied_assets"] = copied_assets
        result["missing_assets"] = missing_assets
    except Exception as e:
        result["reason"] = f"复制 LaTeX 引用资源失败: {e}"
        logger.error(f"LaTeX sidecar 导出失败: {type(e).__name__}")
        _write_status(status_path, result)
        return result

    try:
        result["template_assets"] = _copy_template_assets(
            profile_config.latex_template_dir, latex_project_dir
        )
    except Exception as e:
        result["reason"] = f"复制 LaTeX 模板资源失败: {e}"
        logger.error(f"LaTeX sidecar 导出失败: {type(e).__name__}")
        _write_status(status_path, result)
        return result

    main_tex_path = os.path.join(latex_project_dir, "main.tex")
    try:
        with open(main_tex_path, "w", encoding="utf-8") as f:
            if profile_config.key == ExportProfile.CUMCM2025:
                f.write(_render_main_tex(_CUMCM2025_MAIN_TEX_TEMPLATE, section_inputs))
            elif profile_config.key == ExportProfile.CUMCM2026:
                f.write(_render_main_tex(_CUMCM2026_MAIN_TEX_TEMPLATE, section_inputs))
            elif profile_config.key == ExportProfile.HUASHUBEI:
                f.write(_render_main_tex(_HUASHUBEI_MAIN_TEX_TEMPLATE, section_inputs))
            else:
                f.write(_render_main_tex(_MAIN_TEX_TEMPLATE, section_inputs))
    except Exception as e:
        result["reason"] = f"写入 main.tex 失败: {e}"
        logger.error(f"LaTeX sidecar 导出失败: {type(e).__name__}")
        _write_status(status_path, result)
        return result

    result["latex_project_dir"] = "latex_project"
    result["main_tex"] = "latex_project/main.tex"
    result["success"] = True
    logger.info(f"LaTeX sidecar 导出成功: {main_tex_path}")

    # 可选：尝试编译，失败不影响 success（sidecar 本身已生成）
    compiler = "latexmk" if shutil.which("latexmk") else ("xelatex" if shutil.which("xelatex") else None)
    if compiler is None:
        result["compile_reason"] = "未检测到 latexmk/xelatex，跳过编译尝试"
        logger.info(f"LaTeX sidecar 编译跳过: {result['compile_reason']}")
    else:
        result["compile_attempted"] = True
        _clear_stale_latex_build_files(latex_project_dir)
        if compiler == "latexmk":
            compile_cmd = [
                "latexmk",
                "-xelatex",
                "-latexoption=-no-shell-escape",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "main.tex",
            ]
        else:
            compile_cmd = [
                "xelatex",
                "-no-shell-escape",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "main.tex",
            ]
        result["compile_command"] = compile_cmd
        try:
            if compiler == "xelatex":
                compile_proc = _run_xelatex_twice(latex_project_dir)
            else:
                compile_proc = subprocess.run(  # noqa: S603  # nosec B603
                    compile_cmd,
                    cwd=latex_project_dir,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    shell=False,
                )
            if compile_proc.returncode == 0:
                result["compile_success"] = True
                logger.info(f"LaTeX sidecar 编译成功: {main_tex_path}")
            else:
                result["compile_reason"] = f"编译返回码非 0: {compile_proc.returncode}"
                tails = _latex_output_tail(compile_proc)
                result["compile_stdout_tail"] = tails["stdout"]
                result["compile_stderr_tail"] = tails["stderr"]
                result["compile_failure_summary"] = _extract_latex_failure_summary(
                    compile_proc.stdout, compile_proc.stderr
                )
                if compiler == "latexmk" and shutil.which("xelatex"):
                    fallback_cmd = [
                        "xelatex",
                        "-no-shell-escape",
                        "-interaction=nonstopmode",
                        "-halt-on-error",
                        "main.tex",
                    ]
                    result["compile_fallback_command"] = fallback_cmd
                    fallback_proc = _run_xelatex_twice(latex_project_dir)
                    if fallback_proc.returncode == 0:
                        result["compile_success"] = True
                        result["compile_reason"] = "latexmk 失败，已用 xelatex 连续编译两次成功"
                        tails = _latex_output_tail(fallback_proc)
                        result["compile_stdout_tail"] = tails["stdout"]
                        result["compile_stderr_tail"] = tails["stderr"]
                        result["compile_failure_summary"] = ""
                        logger.info(f"LaTeX sidecar xelatex fallback 编译成功: {main_tex_path}")
                    else:
                        result["compile_reason"] = (
                            "latexmk/xelatex 编译均失败: "
                            f"latexmk={compile_proc.returncode}, xelatex={fallback_proc.returncode}"
                        )
                        tails = _latex_output_tail(fallback_proc)
                        result["compile_stdout_tail"] = tails["stdout"]
                        result["compile_stderr_tail"] = tails["stderr"]
                        result["compile_failure_summary"] = _extract_latex_failure_summary(
                            fallback_proc.stdout, fallback_proc.stderr
                        )
                if not result["compile_success"]:
                    logger.warning(
                        f"LaTeX sidecar 编译失败（不阻断主任务）: returncode={compile_proc.returncode}"
                    )
        except subprocess.TimeoutExpired:
            result["compile_reason"] = "LaTeX 编译超时（180秒）"
            logger.warning(f"LaTeX sidecar 编译超时（不阻断主任务）: {main_tex_path}")
        except Exception as e:
            result["compile_reason"] = f"LaTeX 编译异常: {e}"
            logger.warning(
                "LaTeX sidecar 编译异常（不阻断主任务）: "
                f"{type(e).__name__}"
            )

    _write_status(status_path, result)
    return result
