"""字体可用性检测与 fallback 工具。

精简版 Linux 容器（Debian + xelatex）默认不包含 Times New Roman/SimSun 等
Windows/Office 专有字体，且无法通过 apt 获取同名字体；但本地 Windows 开发
环境，或装有完整 Office 中文字体包的容器，通常已经装有这些正式字体。

策略是"优先正式字体，检测缺失后才 fallback"，而不是无条件把配置里的正式
字体名替换成开源字体 —— 这样才能保证：
  1. 已装有正式字体的环境（本地 Windows 开发、CI 等）继续得到与官方格式
     规范完全一致的排版效果；
  2. 未装正式字体的精简容器不会因为一个字体缺失就编译失败，而是自动
     降级到 metrically 兼容或视觉近似的免费开源字体，保证可用性。

检测方式按平台分派（见 check_font_installed()）：
  - Windows：查询字体注册表（HKEY_LOCAL_MACHINE / HKEY_CURRENT_USER 下的
    `...\\CurrentVersion\\Fonts`），不依赖 fontconfig/fc-match（Windows 默认
    不装 fontconfig）。
  - 其他平台（Linux/Docker/Mac）：使用 fc-match。

resolve_font() 供 Docker/Linux 自动化流程（app.tools.pdf_exporter 的默认
调用路径）使用，检测到缺失才 fallback，不接受用户覆盖、不打印交互式提示。
resolve_font_for_local() 供本地手动导出 CLI（app.tools.export_cli）使用，
额外支持"用户显式指定的字体优先，缺失时清晰提示而不是静默换成陌生字体"。
两者共用同一套 check_font_installed() 检测逻辑，因此 Windows 本机默认已
装有官方字体时，两条路径都会直接使用官方字体，不会被 Docker 的 fallback
策略影响。
"""

from __future__ import annotations

import platform
import re
import shutil
# subprocess is limited to the controlled fc-match probe below.
import subprocess  # nosec B404

from app.utils.log_util import logger

# 官方/正式字体 -> 免费开源等效字体（metrically 兼容或视觉近似）的
# fallback 映射。key 必须与各 export profile 中声明的"preferred"字体名
# 完全一致（大小写敏感），否则不会命中，直接原样返回 preferred。
FONT_FALLBACKS: dict[str, str] = {
    "Times New Roman": "Liberation Serif",
    "Courier New": "Liberation Mono",
    "Arial": "Liberation Sans",
    "SimSun": "Noto Serif CJK SC",
    "SimHei": "Noto Sans CJK SC",
    "KaiTi": "AR PL KaitiM GB",
    "STXinwei": "Noto Sans CJK SC",
    "LiSu": "AR PL KaitiM GB",
}
# 注意：字体检测到缺失时，不能把检测过程中"命中"的替代字体直接当作
# fallback 结果使用 —— fc-match 在找不到精确匹配时会返回它自己认为最
# 接近的默认字体（实测容器内对 SimSun/SimHei/KaiTi 等中文字体查询时，
# 都会统一命中同一个无关的 Latin 字体，如 Liberation Mono），这只能证明
# "该字体不存在"，不能作为实际使用的替代字体。真正使用哪个 fallback，
# 必须查上面 FONT_FALLBACKS 这张表——resolve_font()/resolve_font_for_local()
# 都是这样实现的。


def _fc_match_family(font_name: str) -> str | None:
    """调用 fc-match 查询 font_name 实际会解析到哪个字体族（Linux/Mac）。

    fontconfig 在找不到精确匹配时不会报错，而是返回某个默认替代字体，
    所以调用方必须比较返回值是否与 font_name 一致来判断字体是否真的
    安装，不能只看 fc-match 有没有成功退出。

    若 fc-match 命令本身不存在，或调用异常/超时，返回 None，表示
    "无法检测"。
    """
    fc_match = shutil.which("fc-match")
    if fc_match is None:
        return None
    try:
        # fc-match comes from PATH lookup and receives a single font family argument;
        # no shell is involved, so a font name cannot become a command.
        proc = subprocess.run(  # noqa: S603  # nosec B603
            [fc_match, "--format=%{family}", font_name],
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning(f"fc-match 调用异常，跳过字体检测: {exc}")
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _split_fontconfig_families(family_output: str) -> set[str]:
    """Split fontconfig family output into comparable family names.

    `fc-match --format=%{family}` can return comma-separated families for
    collection fonts, for example `SimSun,NSimSun`. Treat each family as an
    installed alias so mounted Windows `.ttc` files are detected correctly.
    """
    families: set[str] = set()
    for part in re.split(r"[,，]", family_output):
        part = part.strip()
        if part:
            families.add(part)
    return families


def _windows_installed_font_families() -> set[str] | None:
    """枚举 Windows 注册表中已安装字体的字体族名集合。

    分别读取 HKEY_LOCAL_MACHINE（系统级安装，所有用户可见）和
    HKEY_CURRENT_USER（当前用户安装，例如未取得管理员权限时手动安装的
    字体只会出现在这里）下的字体注册表项。

    注册表值名形如 "Times New Roman (TrueType)"、
    "SimSun & NSimSun (TrueType)"（一个值里登记了多个字体族，用 " & " 分隔），
    这里去掉末尾的 "(...)" 备注并按 " & " 拆分，得到干净的字体族名集合。

    返回 None 表示当前不是 Windows，或无法导入/访问注册表（理论上不应该
    发生在 Windows 上，保留作为"无法检测"的降级信号）。
    """
    if platform.system() != "Windows":
        return None
    try:
        import winreg
    except ImportError:
        return None

    registry_paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
    ]
    families: set[str] = set()
    for hive, subkey in registry_paths:
        try:
            key = winreg.OpenKey(hive, subkey)
        except OSError:
            continue
        try:
            index = 0
            while True:
                try:
                    value_name, _value, _type = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                base = re.sub(r"\s*\([^)]*\)\s*$", "", value_name).strip()
                for part in base.split(" & "):
                    part = part.strip()
                    if part:
                        families.add(part)
        finally:
            key.Close()
    return families


def _is_family_in_set(font_name: str, families: set[str]) -> bool:
    """判断 font_name 是否命中 families 中的某个字体族（不区分大小写）。

    既接受精确匹配（"Times New Roman" == "Times New Roman"），也接受
    "<font_name> <字重/样式>" 形式的变体（如注册表里 "Arial Bold" 也算
    Arial 已安装），但不会把 "SimSun-ExtB" 这类不同字体误判为 SimSun
    的变体（因为中间没有空格分隔）。
    """
    target = font_name.strip().lower()
    for family in families:
        family_lower = family.lower()
        if family_lower == target or family_lower.startswith(target + " "):
            return True
    return False


def check_font_installed(font_name: str) -> bool | None:
    """跨平台检测 font_name 是否已安装，供 resolve_font 系列函数和 CLI 使用。

    - Windows：查询字体注册表。
    - 其他平台：使用 fc-match。
    - 无法判断（当前平台没有对应的检测手段，或查询本身失败）：返回 None，
      调用方应按"无法确定，不强行下结论"处理，通常是乐观地假设已安装。
    """
    if platform.system() == "Windows":
        families = _windows_installed_font_families()
        if families is None:
            return None
        return _is_family_in_set(font_name, families)

    matched = _fc_match_family(font_name)
    if matched is None:
        return None
    return _is_family_in_set(font_name, _split_fontconfig_families(matched))


def resolve_font(preferred: str) -> str:
    """返回实际应使用的字体名：优先 preferred，检测到缺失时回退到等效字体。

    供 Docker/Linux 自动化导出路径（app.tools.pdf_exporter 的默认调用）
    使用，不接受用户覆盖，也不面向交互式用户打印提示（只记录日志）。
    本地手动导出场景请用 resolve_font_for_local()。

    - preferred 不在 FONT_FALLBACKS 中（没有预设 fallback）：原样返回，不检测。
    - 无法检测（如当前平台既不是 Windows 也没装 fontconfig）：
      按乐观策略直接返回 preferred，保持原有行为，不引入新的回归。
    - 检测到 preferred 确实已安装：返回 preferred。这也是 Windows 本机默认
      装有 Times New Roman/SimSun 等正式字体时的结果——不会被这里的
      fallback 逻辑影响，满足"不把 Docker fallback 强加给 Windows"的要求。
    - 检测到 preferred 未安装：返回 FONT_FALLBACKS 中登记的 fallback，并记录日志。

    不做进程内缓存：单次 PDF 导出请求最多调用数次，每次几毫秒，可忽略；
    避免缓存在单元测试进程（unittest discover 整个套件跑在同一进程内）
    里跨测试用例污染，用不同 mock 场景验证时互相干扰。
    """
    fallback = FONT_FALLBACKS.get(preferred)
    if fallback is None:
        return preferred

    installed = check_font_installed(preferred)
    if installed is None or installed:
        return preferred

    logger.warning(f"字体 '{preferred}' 未安装，回退为 '{fallback}'")
    return fallback


def resolve_font_for_local(preferred: str, override: str | None = None) -> tuple[str, list[str]]:
    """本地手动导出（如 Windows 本机 CLI）场景下的字体解析。

    与 resolve_font() 的区别：
      1. 支持用户显式覆盖（override）：只要用户给了值就原样使用，绝不
         静默替换成别的字体；如果检测到这个字体本机没装，只追加一条
         warning 文案，交给调用方（CLI）打印给用户看，而不是自己决定换掉。
      2. 未覆盖时走 check_font_installed() 的检测结果，缺失时给出的
         warning 文案更详细（面向交互式用户，而不是只写日志）。

    Returns:
        (font_to_use, warnings)：warnings 是给终端用户看的提示文案列表，
        为空表示没有需要提醒的情况。
    """
    warnings: list[str] = []

    if override:
        installed = check_font_installed(override)
        if installed is False:
            warnings.append(
                f"你指定的字体 '{override}' 在本机未检测到已安装，仍会按你的设置使用；"
                f"如果编译时 xelatex/fontspec 报字体找不到，请检查拼写，或先安装该字体，"
                f"或换成本机已安装的字体。"
            )
        elif installed is None:
            warnings.append(
                f"当前环境无法自动检测字体 '{override}' 是否已安装，将直接按你的设置使用。"
            )
        return override, warnings

    installed = check_font_installed(preferred)
    if installed is True:
        return preferred, warnings
    if installed is None:
        warnings.append(
            f"当前环境无法自动检测字体 '{preferred}' 是否已安装，"
            f"将乐观地按官方字体 '{preferred}' 处理；如编译报字体缺失错误，"
            f"请确认已安装该字体，或用 --mainfont 等参数手动指定替代字体。"
        )
        return preferred, warnings

    fallback = FONT_FALLBACKS.get(preferred, preferred)
    if fallback != preferred:
        warnings.append(
            f"官方字体 '{preferred}' 在本机未检测到已安装，已回退为开源等效字体 "
            f"'{fallback}'；建议安装 '{preferred}'（Windows 一般自带，或案例要求安装）后"
            f"重新导出，以获得更接近正式格式的效果。"
        )
    else:
        warnings.append(
            f"字体 '{preferred}' 在本机未检测到已安装，且没有预设的开源等效字体可回退，"
            f"编译可能会失败；请先安装 '{preferred}'，或用 --mainfont 等参数手动指定替代字体。"
        )
    return fallback, warnings
