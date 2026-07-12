"""PDF 导出工具模块，负责将 Markdown 论文转换为 PDF。"""

import os
import re
import shutil
# subprocess is limited to the controlled Pandoc export invocation below.
import subprocess  # nosec B404
import tempfile
from app.utils.log_util import logger
from app.utils import font_utils
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

PANDOC_MARKDOWN_FORMAT = "markdown-raw_tex+tex_math_dollars+tex_math_single_backslash+pipe_tables"
PDF_PAGEBREAK_FILTER = os.path.join(
    os.path.dirname(__file__), "pandoc_filters", "pdf_pagebreak.lua"
)
PDF_PAGEBREAK_MARKER = "MMA_PDF_PAGEBREAK"
PDF_CJK_BREAK_MARKER = "MMA_PDF_CJK_BREAK"
CJK_BREAK_RUN_RE = re.compile(r"[\u4e00-\u9fff，。！？；：、（）《》“”]{24,}")
FENCE_START_RE = re.compile(r"^\s*(`{3,}|~{3,})")
KEYWORDS_LINE_RE = re.compile(r"^\s*(?:\*\*)?\s*(?:关键词|关键字)\s*(?:\*\*)?\s*[：:]?")
PDF_CJK_BREAK_INTERVAL = 18


def _insert_abstract_pagebreak(markdown: str) -> tuple[str, bool]:
    """Insert a PDF-only page break after keywords and before the first body section."""
    if PDF_PAGEBREAK_MARKER in markdown:
        return markdown, False

    lines = markdown.splitlines(keepends=True)
    keyword_index: int | None = None
    for index, line in enumerate(lines):
        if KEYWORDS_LINE_RE.match(line):
            keyword_index = index
            break
    if keyword_index is None:
        return markdown, False

    body_heading_index: int | None = None
    for index in range(keyword_index + 1, len(lines)):
        stripped = lines[index].strip()
        if not stripped:
            continue
        if stripped.startswith("# "):
            body_heading_index = index
            break
    if body_heading_index is None:
        return markdown, False

    lines.insert(body_heading_index, f"\n{PDF_PAGEBREAK_MARKER}\n\n")
    return "".join(lines), True


def _insert_cjk_pdf_break_opportunities(markdown: str) -> tuple[str, bool]:
    """Add PDF-only break opportunities to long CJK runs without touching code blocks."""
    changed = False
    lines: list[str] = []
    in_fence = False
    fence_marker = ""

    def break_run(match: re.Match[str]) -> str:
        nonlocal changed
        text = match.group(0)
        chunks = [
            text[index : index + PDF_CJK_BREAK_INTERVAL]
            for index in range(0, len(text), PDF_CJK_BREAK_INTERVAL)
        ]
        if len(chunks) <= 1:
            return text
        changed = True
        return f" {PDF_CJK_BREAK_MARKER} ".join(chunks)

    for line in markdown.splitlines(keepends=True):
        fence_match = FENCE_START_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker[0]
            elif marker.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            lines.append(line)
            continue

        stripped = line.lstrip()
        if (
            in_fence
            or stripped.startswith(("#", "|", "!["))
            or re.match(r"^\s*[-*+]\s", line)
        ):
            lines.append(line)
            continue

        lines.append(CJK_BREAK_RUN_RE.sub(break_run, line))

    return "".join(lines), changed


def _prepare_pdf_markdown_source(md_path: str, work_dir: str) -> tuple[str, bool]:
    """Create a temporary PDF input when layout-only Markdown tweaks are needed."""
    with open(md_path, encoding="utf-8") as f:
        markdown = f.read()
    prepared_markdown, inserted_pagebreak = _insert_abstract_pagebreak(markdown)
    prepared_markdown, inserted_cjk_breaks = _insert_cjk_pdf_break_opportunities(
        prepared_markdown
    )
    if not inserted_pagebreak and not inserted_cjk_breaks:
        return md_path, False

    os.makedirs(work_dir, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        suffix=".pdf.md",
        prefix=".mma_pdf_",
        dir=work_dir,
        delete=False,
    ) as f:
        f.write(prepared_markdown)
        return f.name, True


def _resolve_pdf_variables(
    pdf_variables: list[str],
    font_overrides: dict[str, str] | None = None,
    local: bool = False,
) -> tuple[list[str], list[str], list[dict]]:
    """构建最终传给 pandoc -V 的变量列表，并可选做字体检测/覆盖。

    行为分两条路径：
      - 默认（local=False，Docker/Linux 自动化流程走这条，未传 font_overrides
        时与改动前完全一致）：对 _FONT_VARIABLE_KEYS 里的变量调用
        resolve_font()——检测缺失才 fallback，不产生面向用户的提示文案。
      - 本地手动导出（local=True，供 app.tools.export_cli 使用）：改用
        resolve_font_for_local()，未安装时的提示会收集进返回的 warnings，
        交给 CLI 打印给交互式用户。

    font_overrides（形如 {"mainfont": "Times New Roman", "CJKmainfont": "SimSun"}）
    中的值优先于 profile 自带的 pdf_variables：
      - 命中已有变量：直接替换该变量的值，不再走 resolve_font/resolve_font_for_local
        的自动 fallback（用户已经明确指定，不应被静默换成别的字体）。
      - profile 里没有对应变量（如 CJKmonofont，当前两个 profile 都未声明）：
        追加一条新的 -V 变量。
      - local=True 时会额外检测 override 的字体是否已安装，仅用于提示，
        不影响实际使用哪个字体（用户显式指定的值任何情况下都会原样使用）。

    Returns:
        (resolved_variables, warnings, font_resolution)：warnings 仅在 local=True 时可能非空。
    """
    overrides = dict(font_overrides or {})
    resolved: list[str] = []
    warnings: list[str] = []
    font_resolution: list[dict] = []

    for variable in pdf_variables:
        key, sep, value = variable.partition("=")
        if not sep:
            resolved.append(variable)
            continue

        if key in overrides:
            override_value = overrides.pop(key)
            if local:
                installed = font_utils.check_font_installed(override_value)
                if installed is False:
                    warnings.append(
                        f"你指定的字体 '{override_value}'（{key}）在本机未检测到已安装，"
                        f"仍会按你的设置使用；如编译报字体找不到，请检查拼写或先安装该字体。"
                    )
            resolved.append(f"{key}={override_value}")
            if key in _FONT_VARIABLE_KEYS:
                font_resolution.append(
                    {
                        "variable": key,
                        "preferred": value,
                        "actual": override_value,
                        "fallback": None,
                        "source": "override",
                    }
                )
        elif key in _FONT_VARIABLE_KEYS:
            if local:
                new_value, font_warnings = font_utils.resolve_font_for_local(value)
                warnings.extend(font_warnings)
            else:
                new_value = font_utils.resolve_font(value)
            resolved.append(f"{key}={new_value}")
            fallback = font_utils.FONT_FALLBACKS.get(value)
            source = "profile"
            if fallback and new_value == fallback and new_value != value:
                source = "fallback"
            elif fallback and font_utils.check_font_installed(value) is None:
                source = "unknown"
            font_resolution.append(
                {
                    "variable": key,
                    "preferred": value,
                    "actual": new_value,
                    "fallback": fallback,
                    "source": source,
                }
            )
        else:
            resolved.append(variable)

    # font_overrides 里还剩下的 key，说明 profile 原本没有这个变量
    # （例如 CJKmonofont），追加为新变量。
    for key, value in overrides.items():
        if local:
            installed = font_utils.check_font_installed(value)
            if installed is False:
                warnings.append(
                    f"你指定的字体 '{value}'（{key}）在本机未检测到已安装，"
                    f"仍会按你的设置使用；如编译报字体找不到，请检查拼写或先安装该字体。"
                )
        resolved.append(f"{key}={value}")
        if key in _FONT_VARIABLE_KEYS:
            font_resolution.append(
                {
                    "variable": key,
                    "preferred": None,
                    "actual": value,
                    "fallback": None,
                    "source": "override",
                }
            )

    return resolved, warnings, font_resolution


def export_markdown_to_pdf(
    md_path: str,
    pdf_path: str,
    work_dir: str,
    export_profile: ExportProfile | str | None = ExportProfile.DEFAULT,
    font_overrides: dict[str, str] | None = None,
    local_fonts: bool = False,
) -> dict:
    """将 Markdown 文件转换为 PDF（通过 pandoc + xelatex）。

    检查 md_path、pandoc、xelatex 是否可用，任一缺失则跳过转换并说明原因，
    不会抛出异常中断调用方流程。

    Args:
        md_path: 待转换的 Markdown 文件路径。
        pdf_path: 输出 PDF 文件路径。
        work_dir: 工作目录，用作 pandoc 的资源查找路径（图片等）。
        font_overrides: 用户显式指定的字体覆盖（pandoc 变量名 -> 字体名，
            如 {"mainfont": "Times New Roman", "CJKmainfont": "SimSun"}），
            优先于 profile 默认值，且不会被自动 fallback 替换。默认调用方
            （Docker/Linux 自动化流程）不传，行为不变。
        local_fonts: True 时使用本地手动导出场景的字体检测/提示策略
            （resolve_font_for_local，检测缺失时把提示收集进返回结果的
            font_warnings，供交互式 CLI 打印）；默认 False 保持 Docker/Linux
            自动化流程原有行为（resolve_font，仅记录日志，不产生提示列表）。

    Returns:
        结构化结果字典，包含 enabled/success/pdf_path/reason/command/stderr/
        font_warnings（local_fonts=True 时可能非空的字体提示列表）。
    """
    result = {
        "enabled": False,
        "success": False,
        "pdf_path": None,
        "reason": "",
        "command": [],
        "stderr": "",
        "export_profile": get_export_profile_config(export_profile).key.value,
        "font_warnings": [],
        "font_resolution": [],
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
    pdf_md_path = md_path
    cleanup_pdf_md = False
    try:
        pdf_md_path, cleanup_pdf_md = _prepare_pdf_markdown_source(md_path, work_dir)
    except Exception as e:
        result["reason"] = f"PDF 输入预处理失败: {e}"
        logger.error(f"PDF 导出异常: {result['reason']}")
        return result

    command = [
        "pandoc",
        pdf_md_path,
        "-o",
        pdf_path,
        "--pdf-engine=xelatex",
        "--pdf-engine-opt=-no-shell-escape",
        "--from",
        PANDOC_MARKDOWN_FORMAT,
        "--standalone",
        "--listings",
        "--resource-path",
        work_dir,
    ]
    if os.path.exists(PDF_PAGEBREAK_FILTER):
        command.extend(["--lua-filter", PDF_PAGEBREAK_FILTER])
    resolved_variables, font_warnings, font_resolution = _resolve_pdf_variables(
        profile_config.pdf_variables, font_overrides, local_fonts
    )
    result["font_warnings"] = font_warnings
    result["font_resolution"] = font_resolution
    for variable in resolved_variables:
        command.extend(["-V", variable])
    command.extend(profile_config.pdf_extra_args)
    result["enabled"] = True
    result["command"] = command

    try:
        # 命令、引擎和选项均由本模块固定构造，任务路径已由工作目录边界约束。
        proc = subprocess.run(  # noqa: S603  # nosec B603
            command,
            capture_output=True,
            text=True,
            timeout=120,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        result["reason"] = "PDF 生成超时（120秒）"
        logger.error(f"PDF 导出超时: {md_path}")
        return result
    except Exception as e:
        result["reason"] = f"PDF 生成异常: {e}"
        logger.error(f"PDF 导出异常: {e}")
        return result
    finally:
        if cleanup_pdf_md:
            try:
                os.remove(pdf_md_path)
            except OSError:
                logger.warning(f"PDF 临时 Markdown 清理失败: {pdf_md_path}")

    if proc.returncode == 0 and os.path.exists(pdf_path):
        result["success"] = True
        result["pdf_path"] = pdf_path
        logger.info(f"PDF 生成成功: {pdf_path}")
    else:
        result["reason"] = f"pandoc 返回码非 0: {proc.returncode}"
        result["stderr"] = proc.stderr
        logger.error(f"PDF 生成失败: returncode={proc.returncode}, stderr={proc.stderr}")

    return result
