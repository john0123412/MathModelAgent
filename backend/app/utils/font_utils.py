"""字体可用性检测与 fallback 工具。

精简版 Linux 容器（Debian + xelatex）默认不包含 Times New Roman/SimSun 等
Windows/Office 专有字体，且无法通过 apt 获取同名字体；但本地 Windows/Mac
开发环境，或装有完整 Office 中文字体包的容器，通常已经装有这些正式字体。

策略是"优先正式字体，检测缺失后才 fallback"，而不是无条件把配置里的正式
字体名替换成开源字体 —— 这样才能保证：
  1. 已装有正式字体的环境（本地开发、CI 等）继续得到与官方格式规范
     完全一致的排版效果；
  2. 未装正式字体的精简容器不会因为一个字体缺失就编译失败，而是自动
     降级到 metrically 兼容或视觉近似的免费开源字体，保证可用性。
"""

from __future__ import annotations

import shutil
import subprocess

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
# 注意：fc-match 检测到字体缺失时，不能把它"命中"的替代字体直接当作
# fallback 结果使用 —— fontconfig 在找不到精确匹配时会返回它自己认为最
# 接近的默认字体（实测容器内对 SimSun/SimHei/KaiTi 等中文字体查询时，
# 都会统一命中同一个无关的 Latin 字体，如 Liberation Mono），这只能证明
# "该字体不存在"，不能作为实际使用的替代字体。真正使用哪个 fallback，
# 必须查上面 FONT_FALLBACKS 这张表——resolve_font() 也是这样实现的。


def _fc_match_family(font_name: str) -> str | None:
    """调用 fc-match 查询 font_name 实际会解析到哪个字体族。

    fontconfig 在找不到精确匹配时不会报错，而是返回某个默认替代字体，
    所以调用方必须比较返回值是否与 font_name 一致来判断字体是否真的
    安装，不能只看 fc-match 有没有成功退出。

    若 fc-match 命令本身不存在（例如本地 Windows 开发环境通常未装
    fontconfig），或调用异常/超时，返回 None，表示"无法检测"。
    """
    fc_match = shutil.which("fc-match")
    if fc_match is None:
        return None
    try:
        proc = subprocess.run(
            [fc_match, "--format=%{family}", font_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning(f"fc-match 调用异常，跳过字体检测: {exc}")
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def resolve_font(preferred: str) -> str:
    """返回实际应使用的字体名：优先 preferred，检测到缺失时回退到等效字体。

    - preferred 不在 FONT_FALLBACKS 中（没有预设 fallback）：原样返回，不检测。
    - fc-match 不可用（无法检测，如本地开发环境未装 fontconfig）：
      按乐观策略直接返回 preferred，保持原有行为，不引入新的本地回归。
    - fc-match 检测到 preferred 确实已安装（返回的 family 与 preferred 一致）：
      返回 preferred。
    - 检测到 preferred 未安装：返回 FONT_FALLBACKS 中登记的 fallback，并记录日志。

    不做进程内缓存：单次 PDF 导出请求最多调用数次，每次几毫秒，可忽略；
    避免缓存在单元测试进程（unittest discover 整个套件跑在同一进程内）
    里跨测试用例污染，用不同 mock 场景验证时互相干扰。
    """
    fallback = FONT_FALLBACKS.get(preferred)
    if fallback is None:
        return preferred

    matched = _fc_match_family(preferred)
    if matched is None:
        return preferred
    if matched.lower() == preferred.lower():
        return preferred

    logger.warning(f"字体 '{preferred}' 未安装（fc-match 命中 '{matched}'），回退为 '{fallback}'")
    return fallback
