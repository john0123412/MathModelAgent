"""本地手动导出 CLI：Markdown -> PDF / LaTeX sidecar。

设计目的：Docker/Linux 容器负责稳定的自动化预览（app.tools.pdf_exporter /
app.tools.tex_project_exporter 被 workflow 自动调用，检测到官方字体缺失
就静默 fallback 到开源等效字体）；而 Windows 本机通常已经装有 Times New
Roman/SimSun/SimHei/KaiTi 等正式字体，直接在本机运行这个 CLI 可以生成更
接近国赛/论文正式格式的 PDF，且可以显式覆盖字体、看到清晰的检测提示。

用法（需要在 backend/ 目录下运行，且已用 `uv sync` 装好依赖）：

    # 检查依赖（pandoc/xelatex 是否可用、官方字体是否已安装）
    uv run python -m app.tools.export_cli check

    # 直接导出 PDF，本地字体优先（Times New Roman/SimSun/... 检测缺失才回退）
    uv run python -m app.tools.export_cli pdf --input res.md --output res.pdf --profile cumcm2026 --local

    # 只导出 LaTeX sidecar 项目，供之后手动 xelatex 编译（最稳妥的方式，
    # gmcmthesis 模板自带 \\IfFontExistsTF 检测，不需要额外参数）
    uv run python -m app.tools.export_cli latex --input res.md --work-dir . --profile cumcm2026

    # 手动指定字体（用户显式指定优先，检测到缺失只警告，不会静默换成别的字体）
    uv run python -m app.tools.export_cli pdf --input res.md --output res.pdf --local `
        --mainfont "Times New Roman" --cjk-mainfont "SimSun" --cjk-sansfont "SimHei" --cjk-monofont "KaiTi"

    # 或用 JSON 配置文件批量指定
    uv run python -m app.tools.export_cli pdf --input res.md --output res.pdf --local --font-config fonts.json

详见 STARTUP.md 的"Windows 本地 PDF 导出 / 手动编译"一节。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

from app.schemas.enums import ExportProfile
from app.services.task_status import write_task_status_to_dir
from app.tools.candidate_exporter import write_candidate_manifest
from app.tools.pdf_exporter import export_markdown_to_pdf
from app.tools.pdf_visual_checker import (
    CUMCM2026_STRICT_EDITORIAL_QUALITY_POLICY,
    DEFAULT_EDITORIAL_QUALITY_POLICY,
    check_pdf_visual,
)
from app.tools.submission_audit import write_submission_audit_report
from app.tools.final_acceptance import write_final_acceptance_report
from app.tools.ai_usage_exporter import ensure_ai_usage_details
from app.tools.paper_postprocessor import prepare_paper_markdown
from app.tools.tex_project_exporter import export_markdown_to_latex_project
from app.tools.export_template_override import (
    TemplateOverrideError,
    get_editorial_policy_override,
    get_pdf_visual_constraints,
    install_export_template_override,
    load_export_template_override,
)
from app.utils.common_utils import ensure_safe_task_id, get_work_dir, md_2_docx
from app.utils.font_utils import check_font_installed

# CLI 参数名 -> pandoc/fontspec 变量名
_OVERRIDE_ARG_TO_VARIABLE = {
    "mainfont": "mainfont",
    "monofont": "monofont",
    "sansfont": "sansfont",
    "cjk_mainfont": "CJKmainfont",
    "cjk_sansfont": "CJKsansfont",
    "cjk_monofont": "CJKmonofont",
}

# Windows 本机建议优先安装/使用的官方字体（check 子命令展示用）
_WINDOWS_PREFERRED_FONTS = [
    "Times New Roman",
    "Arial",
    "Courier New",
    "SimSun",
    "SimHei",
    "KaiTi",
]


def _pdf_editorial_quality_policy(profile: str) -> str:
    """Keep manual formal re-export aligned with the workflow's quality gate."""
    return (
        CUMCM2026_STRICT_EDITORIAL_QUALITY_POLICY
        if profile in {ExportProfile.CUMCM2025.value, ExportProfile.CUMCM2026.value}
        else DEFAULT_EDITORIAL_QUALITY_POLICY
    )


def _load_font_config(path: str) -> dict[str, str]:
    """从 JSON 配置文件读取字体覆盖。

    字段名与 pandoc 字体变量名一致：mainfont/monofont/sansfont/CJKmainfont/
    CJKsansfont/CJKmonofont。未知字段名会被忽略并给出警告，而不是静默生效
    或直接报错中断。
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    known_keys = set(_OVERRIDE_ARG_TO_VARIABLE.values())
    unknown = [k for k in data if k not in known_keys]
    if unknown:
        print(
            f"[警告] 字体配置文件 {path} 中的以下字段名不是已知的 pandoc 字体变量，"
            f"已忽略: {unknown}（可用字段: {sorted(known_keys)}）",
            file=sys.stderr,
        )
    return {k: v for k, v in data.items() if k in known_keys and v}


def _collect_font_overrides(args: argparse.Namespace) -> dict[str, str]:
    """合并 --font-config 文件与命令行单项参数，命令行参数优先级更高。"""
    overrides: dict[str, str] = {}
    if getattr(args, "font_config", None):
        try:
            overrides.update(_load_font_config(args.font_config))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[错误] 读取字体配置文件 {args.font_config} 失败: {exc}", file=sys.stderr)
            sys.exit(2)
    for arg_name, variable_name in _OVERRIDE_ARG_TO_VARIABLE.items():
        value = getattr(args, arg_name, None)
        if value:
            overrides[variable_name] = value
    return overrides


def _check_dependency(name: str, hint: str) -> bool:
    path = shutil.which(name)
    if path:
        print(f"  [OK]   {name} -> {path}")
    else:
        print(f"  [缺失] {name}（{hint}）")
    return path is not None


def _load_existing_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _refresh_task_status(
    work_dir: str,
    pdf_path: str,
    profile: str,
    pdf_result: dict,
) -> None:
    """Refresh task reports after a manual/formal PDF re-export."""
    template_audit = pdf_result.get("template_override")
    if not isinstance(template_audit, dict):
        template_audit = {"active": False}
    visual_result = (
        check_pdf_visual(
            pdf_path,
            work_dir,
            quality_policy=_pdf_editorial_quality_policy(profile),
            export_profile=profile,
            template_override_audit=template_audit,
            **get_pdf_visual_constraints(work_dir, profile),
        )
        if pdf_result["success"]
        else None
    )
    export_status_path = os.path.join(work_dir, "export_status.json")
    export_status = _load_existing_json(export_status_path)
    export_status.update(
        {
            "export_profile": profile,
            "template_override": template_audit,
            "pdf": pdf_result,
            "pdf_visual_check": visual_result,
        }
    )
    with open(export_status_path, "w", encoding="utf-8") as f:
        json.dump(export_status, f, ensure_ascii=False, indent=2)

    manifest_path = os.path.join(work_dir, "candidate_manifest.json")
    if os.path.exists(manifest_path):
        manifest = _load_existing_json(manifest_path)
        task_id = manifest.get("task_id") or os.path.basename(os.path.abspath(work_dir))
        write_candidate_manifest(work_dir, str(task_id))
        write_submission_audit_report(work_dir)
        final_report = write_final_acceptance_report(work_dir)
        write_candidate_manifest(work_dir, str(task_id))
        if final_report.get("technical_status") == "TECHNICAL_PASS":
            write_task_status_to_dir(work_dir, str(task_id), "completed", "任务处理完成")
        else:
            write_task_status_to_dir(
                work_dir,
                str(task_id),
                "failed",
                "最终技术验收未通过，请查看 final_acceptance_report.json",
            )
    else:
        write_submission_audit_report(work_dir)


def cmd_check(args: argparse.Namespace) -> int:
    print("=== 依赖检查 ===")
    pandoc_ok = _check_dependency(
        "pandoc", "请安装 Pandoc（https://pandoc.org/installing.html），装完用 `pandoc --version` 确认"
    )
    xelatex_ok = _check_dependency(
        "xelatex",
        "请安装 MiKTeX（https://miktex.org/download）或 TeX Live（https://tug.org/texlive/），"
        "装完用 `xelatex --version` 确认",
    )
    _check_dependency("latexmk", "可选，MiKTeX/TeX Live 一般自带；缺失时会退化为直接调用 xelatex")
    print(f"  [OK]   python -> {sys.executable}")

    print("\n=== 字体检查（Windows 本机官方字体） ===")
    missing_fonts: list[str] = []
    unknown_fonts: list[str] = []
    for font in _WINDOWS_PREFERRED_FONTS:
        installed = check_font_installed(font)
        if installed is True:
            print(f"  [OK]   {font}")
        elif installed is False:
            missing_fonts.append(font)
            print(f"  [缺失] {font}（导出时会自动回退到开源等效字体，或用 --mainfont 等参数手动指定其它已安装字体）")
        else:
            unknown_fonts.append(font)
            print(f"  [未知] {font}（当前环境无法自动检测字体是否安装，将乐观地按已安装处理）")

    print("\n=== 环境结论 ===")
    if not (pandoc_ok and xelatex_ok):
        print("缺 pandoc/xelatex，不能导出。")
        print("\n[错误] 关键依赖缺失，无法导出 PDF，请先安装上面标记为“缺失”的工具。", file=sys.stderr)
        return 1
    if missing_fonts:
        print(
            "可以导出但会 fallback：以下官方字体未检测到，将在未手动指定字体时回退到开源等效字体："
            f"{', '.join(missing_fonts)}。"
        )
    elif unknown_fonts:
        print(
            "可以导出，但部分字体无法自动检测；如编译报字体缺失，请安装对应字体或用 --font-config 指定："
            f"{', '.join(unknown_fonts)}。"
        )
    else:
        print("可以正式导出：关键工具可用，Windows 官方字体均已检测到。")
    print("依赖检查通过，可以执行 pdf / latex 子命令。")
    return 0


def cmd_pdf(args: argparse.Namespace) -> int:
    if shutil.which("pandoc") is None:
        print("[错误] 未检测到 pandoc，请先安装并用 `pandoc --version` 确认可用。", file=sys.stderr)
        return 1
    if shutil.which("xelatex") is None:
        print(
            "[错误] 未检测到 xelatex，请先安装 MiKTeX 或 TeX Live 并用 `xelatex --version` 确认可用。",
            file=sys.stderr,
        )
        return 1

    overrides = _collect_font_overrides(args)
    work_dir = args.work_dir or os.path.dirname(os.path.abspath(args.input)) or "."
    if args.update_status:
        canonical_md = os.path.normcase(os.path.abspath(os.path.join(work_dir, "res.md")))
        canonical_pdf = os.path.normcase(os.path.abspath(os.path.join(work_dir, "res.pdf")))
        if (
            os.path.normcase(os.path.abspath(args.input)) != canonical_md
            or os.path.normcase(os.path.abspath(args.output)) != canonical_pdf
        ):
            print(
                "[错误] --update-status 只能用于任务目录中的 res.md -> res.pdf，"
                "避免外部文件覆盖当前任务的验收状态。",
                file=sys.stderr,
            )
            return 2

    result = export_markdown_to_pdf(
        args.input,
        args.output,
        work_dir,
        export_profile=args.profile,
        font_overrides=overrides or None,
        local_fonts=args.local,
    )

    for warning in result.get("font_warnings", []):
        print(f"[字体提示] {warning}", file=sys.stderr)

    if result["success"]:
        if args.update_status:
            _refresh_task_status(
                os.path.abspath(work_dir),
                os.path.abspath(args.output),
                args.profile,
                result,
            )
            print("已刷新 export_status.json、pdf_visual_check.json、submission_audit_report.json。")
        print(f"PDF 生成成功: {result['pdf_path']}")
        return 0

    print(f"[错误] PDF 生成失败: {result['reason']}", file=sys.stderr)
    if result.get("stderr"):
        print(result["stderr"], file=sys.stderr)
    return 1


def cmd_latex(args: argparse.Namespace) -> int:
    if shutil.which("pandoc") is None:
        print("[错误] 未检测到 pandoc，请先安装并用 `pandoc --version` 确认可用。", file=sys.stderr)
        return 1

    work_dir = args.work_dir or os.path.dirname(os.path.abspath(args.input)) or "."
    result = export_markdown_to_latex_project(args.input, work_dir, export_profile=args.profile)

    if not result["success"]:
        print(f"[错误] LaTeX sidecar 导出失败: {result['reason']}", file=sys.stderr)
        return 1

    latex_project_dir = os.path.join(work_dir, result["latex_project_dir"])
    print(f"LaTeX sidecar 导出成功: {os.path.join(work_dir, result['main_tex'])}")

    if result["compile_attempted"] and result["compile_success"]:
        print("已尝试自动编译（latexmk/xelatex 都在 PATH 里），编译成功，无需再手动编译。")
        return 0

    if result["compile_attempted"]:
        print(f"已尝试自动编译，但编译失败（{result['compile_reason']}）；请按下面命令手动编译：")
    else:
        print(f"未尝试自动编译（{result['compile_reason']}）；请按下面命令手动编译：")

    print(f"\n  cd {latex_project_dir}")
    print("  xelatex -no-shell-escape -interaction=nonstopmode main.tex")
    print("  xelatex -no-shell-escape -interaction=nonstopmode main.tex   # 再跑一次以生成正确的目录/交叉引用")
    print("\n（该模板未使用 bibtex/biber，无需额外的参考文献编译步骤）")
    return 0


def cmd_template_install(args: argparse.Namespace) -> int:
    """Import a task-local official-package candidate without mutating profiles."""
    try:
        task_id = ensure_safe_task_id(args.task_id)
        work_dir = get_work_dir(task_id)
        result = install_export_template_override(
            work_dir,
            args.profile,
            docx_template_path=args.docx_template,
            format_contract_path=args.format_contract,
            label=args.label,
        )
    except (OSError, ValueError, TemplateOverrideError) as exc:
        print(f"[错误] 导入任务级模板覆盖失败: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        "模板已复制进任务目录并记录哈希。请执行 task-refresh 重建 Markdown、"
        "DOCX、PDF、LaTeX 和全部审核报告。"
    )
    return 0


def cmd_template_show(args: argparse.Namespace) -> int:
    try:
        task_id = ensure_safe_task_id(args.task_id)
        result = load_export_template_override(get_work_dir(task_id), args.profile)
    except (OSError, ValueError, TemplateOverrideError) as exc:
        print(f"[错误] 读取任务级模板覆盖失败: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_task_refresh(args: argparse.Namespace) -> int:
    """Rebuild one completed task after a task-local template import.

    This intentionally does not call a provider or rerun any numerical code.
    It only re-applies deterministic paper post-processing and rebuilds every
    delivery artifact whose hash depends on the manuscript or template.
    """
    try:
        task_id = ensure_safe_task_id(args.task_id)
        work_dir = get_work_dir(task_id)
        checkpoint = _load_existing_json(os.path.join(work_dir, "checkpoint.json"))
        checkpoint_profile = str(checkpoint.get("export_profile") or "")
        if checkpoint_profile and checkpoint_profile != args.profile:
            raise ValueError(
                f"任务检查点 export_profile={checkpoint_profile}，与 --profile={args.profile} 不一致"
            )
        declared_count = checkpoint.get("ques_count")
        if isinstance(declared_count, bool) or not isinstance(declared_count, int):
            declared_count = None
        template_override = load_export_template_override(work_dir, args.profile)
        editorial_policy = get_editorial_policy_override(work_dir, args.profile)
        visual_constraints = get_pdf_visual_constraints(work_dir, args.profile)
        ai_usage = ensure_ai_usage_details(work_dir, export_profile=args.profile)
        if ai_usage.get("enabled") and not ai_usage.get("success"):
            raise RuntimeError("AI工具使用详情导出失败，拒绝刷新正式交付物")
        preflight = prepare_paper_markdown(
            work_dir,
            "res.md",
            export_profile=args.profile,
            declared_problem_count=declared_count,
            editorial_policy=editorial_policy,
            template_override_audit=template_override["audit"],
        )
        if preflight.get("status") != "PASS":
            print(json.dumps({"ok": False, "preflight": preflight}, ensure_ascii=False, indent=2))
            return 2
        docx_result = md_2_docx(task_id, export_profile=args.profile)
        pdf_result = export_markdown_to_pdf(
            os.path.join(work_dir, "res.md"),
            os.path.join(work_dir, "res.pdf"),
            work_dir,
            export_profile=args.profile,
            local_fonts=args.local,
        )
        if not pdf_result.get("success"):
            print(json.dumps({"ok": False, "pdf": pdf_result}, ensure_ascii=False, indent=2))
            return 1
        visual_result = check_pdf_visual(
            os.path.join(work_dir, "res.pdf"),
            work_dir,
            quality_policy=_pdf_editorial_quality_policy(args.profile),
            export_profile=args.profile,
            template_override_audit=template_override["audit"],
            **visual_constraints,
        )
        tex_result = export_markdown_to_latex_project(
            os.path.join(work_dir, "res.md"), work_dir, export_profile=args.profile
        )
        export_status = {
            "export_profile": args.profile,
            "reason": "task_local_template_refresh",
            "template_override": template_override["audit"],
            "docx": docx_result,
            "pdf": pdf_result,
            "pdf_visual_check": visual_result,
            "latex": tex_result,
        }
        with open(os.path.join(work_dir, "export_status.json"), "w", encoding="utf-8") as handle:
            json.dump(export_status, handle, ensure_ascii=False, indent=2)
        write_candidate_manifest(work_dir, task_id)
        audit = write_submission_audit_report(work_dir)
        final_report = write_final_acceptance_report(work_dir)
        write_candidate_manifest(work_dir, task_id)
        technical_pass = final_report.get("technical_status") == "TECHNICAL_PASS"
        write_task_status_to_dir(
            work_dir,
            task_id,
            "completed" if technical_pass else "failed",
            "任务处理完成" if technical_pass else "最终技术验收未通过，请查看 final_acceptance_report.json",
        )
        result = {
            "ok": technical_pass,
            "task_id": task_id,
            "preflight": preflight.get("status"),
            "pdf_visual": visual_result.get("status"),
            "submission_audit": audit.get("status"),
            "technical_status": final_report.get("technical_status"),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if technical_pass else 2
    except (OSError, RuntimeError, ValueError, TemplateOverrideError) as exc:
        print(f"[错误] 模板刷新交付物失败: {exc}", file=sys.stderr)
        return 2


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.tools.export_cli",
        description=(
            "本地手动导出 Markdown -> PDF / LaTeX sidecar，"
            "供 Windows 本机使用系统已装字体生成更接近正式格式的 PDF；"
            "详见 STARTUP.md 的“Windows 本地 PDF 导出 / 手动编译”一节。"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common_font_args(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--mainfont", help="覆盖英文正文字体，如 'Times New Roman'")
        sub.add_argument("--monofont", help="覆盖等宽字体，如 'Courier New'")
        sub.add_argument("--sansfont", help="覆盖无衬线字体，如 'Arial'")
        sub.add_argument("--cjk-mainfont", dest="cjk_mainfont", help="覆盖中文正文字体，如 'SimSun'")
        sub.add_argument("--cjk-sansfont", dest="cjk_sansfont", help="覆盖中文黑体，如 'SimHei'")
        sub.add_argument("--cjk-monofont", dest="cjk_monofont", help="覆盖中文楷体，如 'KaiTi'")
        sub.add_argument(
            "--font-config",
            dest="font_config",
            help="字体覆盖配置 JSON 文件路径（字段名同上，如 mainfont/CJKmainfont），"
            "命令行参数优先级高于配置文件",
        )

    check_parser = subparsers.add_parser("check", help="检查 pandoc/xelatex/字体依赖")
    check_parser.set_defaults(func=cmd_check)

    pdf_parser = subparsers.add_parser("pdf", help="直接导出 PDF（pandoc + xelatex）")
    pdf_parser.add_argument("--input", "-i", required=True, help="输入 Markdown 文件路径")
    pdf_parser.add_argument("--output", "-o", required=True, help="输出 PDF 文件路径")
    pdf_parser.add_argument("--work-dir", dest="work_dir", help="pandoc 资源查找目录，默认取输入文件所在目录")
    pdf_parser.add_argument(
        "--profile",
        choices=[p.value for p in ExportProfile],
        default=ExportProfile.DEFAULT.value,
        help=(
            "导出排版配置，默认 default；高教社杯/国赛（CUMCM）建议使用 "
            "cumcm2026，cumcm2025 保留为 2025 格式；huashubei 仅用于华数杯"
        ),
    )
    pdf_parser.add_argument(
        "--local",
        action="store_true",
        help="本地手动导出模式：优先使用系统已安装的官方字体（Times New Roman/SimSun/...），"
        "只有检测到确实缺失时才回退到开源等效字体，并把检测结果打印出来；"
        "不加此参数时使用与 Docker/Linux 自动化流程一致的静默 fallback 策略。",
    )
    pdf_parser.add_argument(
        "--update-status",
        action="store_true",
        help="PDF 生成成功后刷新 export_status.json、pdf_visual_check.json、submission_audit_report.json；"
        "若 candidate_manifest.json 已存在，也同步刷新 manifest。",
    )
    add_common_font_args(pdf_parser)
    pdf_parser.set_defaults(func=cmd_pdf)

    latex_parser = subparsers.add_parser(
        "latex", help="导出 LaTeX sidecar 项目（不直接生成 PDF，供手动 xelatex 编译，最稳妥）"
    )
    latex_parser.add_argument("--input", "-i", required=True, help="输入 Markdown 文件路径")
    latex_parser.add_argument(
        "--work-dir", dest="work_dir", help="latex_project/ 的输出位置，默认取输入文件所在目录"
    )
    latex_parser.add_argument(
        "--profile",
        choices=[p.value for p in ExportProfile],
        default=ExportProfile.DEFAULT.value,
        help=(
            "导出排版配置，默认 default；高教社杯/国赛（CUMCM）建议使用 cumcm2026，"
            "cumcm2025 保留为 2025 gmcmthesis 格式；huashubei 仅用于华数杯"
        ),
    )
    latex_parser.set_defaults(func=cmd_latex)

    template_parser = subparsers.add_parser(
        "template",
        help="导入或检查任务级 DOCX 模板与受限 PDF/版式合同；不改公共 profile",
    )
    template_subparsers = template_parser.add_subparsers(dest="template_command", required=True)
    template_install = template_subparsers.add_parser(
        "install", help="复制用户提供的 DOCX 模板/版式合同并记录 SHA-256"
    )
    template_install.add_argument("--task-id", required=True)
    template_install.add_argument(
        "--profile",
        required=True,
        choices=[ExportProfile.CUMCM2025.value, ExportProfile.CUMCM2026.value],
    )
    template_install.add_argument(
        "--docx-template",
        help="用户从竞赛官方包取得的 .docx 参考模板；会复制进任务目录",
    )
    template_install.add_argument(
        "--format-contract",
        help="受限版式合同 JSON；只允许字体、行距、分页、页数和安全 PDF 变量",
    )
    template_install.add_argument(
        "--label", help="人工记录的模板版本/来源标签；应用不会将其宣称为官方已验证"
    )
    template_install.set_defaults(func=cmd_template_install)
    template_show = template_subparsers.add_parser(
        "show", help="校验当前任务的模板哈希并显示解析后的覆盖合同"
    )
    template_show.add_argument("--task-id", required=True)
    template_show.add_argument(
        "--profile",
        required=True,
        choices=[ExportProfile.CUMCM2025.value, ExportProfile.CUMCM2026.value],
    )
    template_show.set_defaults(func=cmd_template_show)

    refresh_parser = subparsers.add_parser(
        "task-refresh",
        help="导入任务级模板后，无 Provider 重建 Markdown/DOCX/PDF/LaTeX 与全部交付审计",
    )
    refresh_parser.add_argument("--task-id", required=True)
    refresh_parser.add_argument(
        "--profile",
        required=True,
        choices=[p.value for p in ExportProfile],
    )
    refresh_parser.add_argument(
        "--local",
        action="store_true",
        help="本机字体优先；与 pdf 子命令相同，只影响字体检测/提示策略",
    )
    refresh_parser.set_defaults(func=cmd_task_refresh)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
