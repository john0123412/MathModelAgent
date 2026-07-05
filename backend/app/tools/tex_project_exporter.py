"""LaTeX sidecar 导出工具模块。

在不改变 res.md/res.pdf/res.docx 直出结果的前提下，额外生成一份可被
math-modeling-skills 导入继续精修的 LaTeX 项目（latex_project/），
供后续人工/工具做更精细的排版和 preflight 校验。

本模块只是把 res.md 原样转换为 LaTeX 片段并包一层可编译的最小 main.tex 壳，
不会重写、润色或删减论文正文内容。
"""

import os
import shutil
import subprocess
import json
import re
from app.utils.log_util import logger
from app.schemas.enums import ExportProfile
from app.tools.export_profiles import HUASHUBEI_PAGE_MARGIN, get_export_profile_config

SECTION_INPUTS_PLACEHOLDER = "% MMA_SECTION_INPUTS"
PANDOC_LATEX_MARKDOWN_FORMAT = "markdown+tex_math_dollars+tex_math_single_backslash+pipe_tables+raw_tex"

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
\providecommand{\tightlist}{\setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}}

% pandoc 对无标题的 longtable 会输出 \def\LTcaptype{none}，若当前文档类/宏包
% （如 caption）未定义名为 "none" 的计数器会导致编译报错，这里兜底定义一次。
\makeatletter
\@ifundefined{c@none}{\newcounter{none}}{}
\makeatother

% 图片可能位于 latex_project 本身、其上级 work_dir，或 sections 子目录
\graphicspath{{./}{../}{sections/}}

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
\providecommand{\tightlist}{\setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}}

% pandoc 对无标题的 longtable 会输出 \def\LTcaptype{none}，gmcmthesis.cls 依赖的
% caption 宏包会据此查找名为 "none" 的计数器，这里兜底定义一次避免编译报错。
\makeatletter
\@ifundefined{c@none}{\newcounter{none}}{}
\makeatother

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

_CUMCM2026_MAIN_TEX_TEMPLATE = _CUMCM2025_MAIN_TEX_TEMPLATE.replace(
    "CUMCM 2025 LaTeX sidecar",
    "CUMCM 2026 LaTeX sidecar",
).replace(
    "摘要/关键词位置、目录、附录和参考文献。",
    "摘要/关键词位置、附录和参考文献；2026 修订稿电子版不生成目录。",
).replace(
    "\\maketitle\n\\tableofcontents\n\n% MMA_SECTION_INPUTS",
    "\\maketitle\n\n% MMA_SECTION_INPUTS",
)

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
  basicstyle=\ttfamily\small,
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

\graphicspath{{{{./}}{{../}}{{sections/}}}}

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


def _write_status(status_path: str, result: dict) -> None:
    """将导出结果写入 tex_export_status.json。"""
    try:
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"写入 tex_export_status.json 失败: {e}")


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


def _split_markdown_sections(markdown: str) -> list[dict]:
    """按 Markdown 顶层标题拆分为结构化 LaTeX sections 输入。"""
    heading_re = re.compile(r"(?m)^#\s+(.+?)\s*$")
    matches = list(heading_re.finditer(markdown))
    sections: list[dict] = []
    if not matches:
        return sections

    front_matter = markdown[: matches[0].start()].strip()
    if front_matter:
        sections.append(
            {
                "title": "front_matter",
                "filename": "00_front_matter.tex",
                "markdown": front_matter + "\n",
            }
        )

    for index, match in enumerate(matches, 1):
        end = matches[index].start() if index < len(matches) else len(markdown)
        title = match.group(1).strip()
        chunk = markdown[match.start() : end].strip()
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
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


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
        "reason": "",
        "command": [],
        "stderr": "",
        "compile_attempted": False,
        "compile_success": False,
        "compile_reason": "",
        "compile_stdout_tail": "",
        "compile_stderr_tail": "",
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
    except Exception as e:
        result["reason"] = f"准备 latex_project 失败: {e}"
        logger.error(f"LaTeX sidecar 导出失败: {result['reason']}")
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
        proc = _run_pandoc_to_latex(md_path, imported_body_path, work_dir)
    except subprocess.TimeoutExpired:
        result["reason"] = "LaTeX 正文转换超时（120秒）"
        logger.error(f"LaTeX sidecar 导出超时: {md_path}")
        _write_status(status_path, result)
        return result
    except Exception as e:
        result["reason"] = f"LaTeX 正文转换异常: {e}"
        logger.error(f"LaTeX sidecar 导出异常: {e}")
        _write_status(status_path, result)
        return result

    if proc.returncode != 0 or not os.path.exists(imported_body_path):
        result["reason"] = f"pandoc 转换返回码非 0: {proc.returncode}"
        result["stderr"] = proc.stderr
        logger.error(
            f"LaTeX sidecar 正文转换失败: returncode={proc.returncode}, stderr={proc.stderr}"
        )
        _write_status(status_path, result)
        return result

    result["imported_body"] = "latex_project/sections/imported_body.tex"

    try:
        structured_sections, section_inputs = _write_structured_sections(
            markdown, sections_dir, work_dir
        )
    except Exception as e:
        result["reason"] = str(e)
        logger.error(f"LaTeX sidecar 结构化章节导出失败: {e}")
        _write_status(status_path, result)
        return result
    result["structured_sections"] = structured_sections
    result["structured_section_count"] = len(structured_sections)
    result["main_uses_structured_sections"] = bool(structured_sections)

    try:
        result["template_assets"] = _copy_template_assets(
            profile_config.latex_template_dir, latex_project_dir
        )
    except Exception as e:
        result["reason"] = f"复制 LaTeX 模板资源失败: {e}"
        logger.error(f"LaTeX sidecar 导出失败: {result['reason']}")
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
        logger.error(f"LaTeX sidecar 导出失败: {result['reason']}")
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
        if compiler == "latexmk":
            compile_cmd = [
                "latexmk",
                "-xelatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "main.tex",
            ]
        else:
            compile_cmd = [
                "xelatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "main.tex",
            ]
        try:
            compile_proc = subprocess.run(
                compile_cmd,
                cwd=latex_project_dir,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if compile_proc.returncode == 0:
                result["compile_success"] = True
                logger.info(f"LaTeX sidecar 编译成功: {main_tex_path}")
            else:
                result["compile_reason"] = f"编译返回码非 0: {compile_proc.returncode}"
                result["compile_stdout_tail"] = compile_proc.stdout[-2000:]
                result["compile_stderr_tail"] = compile_proc.stderr[-2000:]
                if compiler == "latexmk" and shutil.which("xelatex"):
                    fallback_cmd = [
                        "xelatex",
                        "-interaction=nonstopmode",
                        "-halt-on-error",
                        "main.tex",
                    ]
                    fallback_proc = subprocess.run(
                        fallback_cmd,
                        cwd=latex_project_dir,
                        capture_output=True,
                        text=True,
                        timeout=180,
                    )
                    if fallback_proc.returncode == 0:
                        result["compile_success"] = True
                        result["compile_reason"] = "latexmk 失败，已用 xelatex 编译成功"
                        result["compile_stdout_tail"] = fallback_proc.stdout[-2000:]
                        result["compile_stderr_tail"] = fallback_proc.stderr[-2000:]
                        logger.info(f"LaTeX sidecar xelatex fallback 编译成功: {main_tex_path}")
                    else:
                        result["compile_reason"] = (
                            "latexmk/xelatex 编译均失败: "
                            f"latexmk={compile_proc.returncode}, xelatex={fallback_proc.returncode}"
                        )
                        result["compile_stdout_tail"] = fallback_proc.stdout[-2000:]
                        result["compile_stderr_tail"] = fallback_proc.stderr[-2000:]
                if not result["compile_success"]:
                    logger.warning(
                        f"LaTeX sidecar 编译失败（不阻断主任务）: returncode={compile_proc.returncode}"
                    )
        except subprocess.TimeoutExpired:
            result["compile_reason"] = "LaTeX 编译超时（180秒）"
            logger.warning(f"LaTeX sidecar 编译超时（不阻断主任务）: {main_tex_path}")
        except Exception as e:
            result["compile_reason"] = f"LaTeX 编译异常: {e}"
            logger.warning(f"LaTeX sidecar 编译异常（不阻断主任务）: {e}")

    _write_status(status_path, result)
    return result
