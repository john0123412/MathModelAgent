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
from app.utils.log_util import logger

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

% 图片可能位于 latex_project 本身、其上级 work_dir，或 sections 子目录
\graphicspath{{./}{../}{sections/}}

\begin{document}

\input{sections/imported_body}

\end{document}
"""


def _write_status(status_path: str, result: dict) -> None:
    """将导出结果写入 tex_export_status.json。"""
    try:
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"写入 tex_export_status.json 失败: {e}")


def export_markdown_to_latex_project(
    md_path: str, work_dir: str, template_key: str = "zh/cumcm-latex"
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
    result = {
        "enabled": False,
        "success": False,
        "template_key": template_key,
        "latex_project_dir": None,
        "main_tex": None,
        "imported_body": None,
        "reason": "",
        "command": [],
        "stderr": "",
        "compile_attempted": False,
        "compile_success": False,
        "compile_reason": "",
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
    except Exception as e:
        result["reason"] = f"创建 latex_project 目录失败: {e}"
        logger.error(f"LaTeX sidecar 导出失败: {result['reason']}")
        _write_status(status_path, result)
        return result

    imported_body_path = os.path.join(sections_dir, "imported_body.tex")
    command = [
        "pandoc",
        md_path,
        "-f",
        "markdown",
        "-t",
        "latex",
        "-o",
        imported_body_path,
        "--resource-path",
        work_dir,
    ]
    result["enabled"] = True
    result["command"] = command

    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=120)
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

    main_tex_path = os.path.join(latex_project_dir, "main.tex")
    try:
        with open(main_tex_path, "w", encoding="utf-8") as f:
            f.write(_MAIN_TEX_TEMPLATE)
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
