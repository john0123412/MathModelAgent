"""程序化 JSON 容错修复工具。

纯函数实现，无外部依赖，用于修复 LLM 返回的截断/夹带文字/控制字符
等常见畸形 JSON。供 CoordinatorAgent 在 ``json.loads`` 失败后自动救回
合法 JSON，避免模型输出瑕疵直接熔断拆题流程。
"""

from __future__ import annotations

import json
import re


# 需清理的控制字符与零宽字符
_CONTROL_CHAR_RE = re.compile(
    r"[\x00-\x1f\x7f"          # ASCII 控制字符
    r"\u200b\u200c\u200d"       # 零宽空格/非连接符/连接符
    r"\ufeff"                   # BOM / 零宽无断空格
    r"\ud800-\udfff"            # 代理对（孤立时无意义）
    r"]"
)


def repair_json(raw: str) -> str | None:
    """尝试将 LLM 原始文本修复为可 ``json.loads`` 的字符串。

    修复顺序：
    1. 去包装（剥离 Markdown 代码块标记、strip）
    2. 控制字符 / 零宽字符清理
    3. 正则抽取主 JSON 块（应对前后夹带解释文字）
    4. 截断修复：补闭合引号、补 ``}`` / ``]``、去尾部逗号

    Args:
        raw: 模型原始返回文本。

    Returns:
        可被 ``json.loads`` 解析的字符串，或 ``None``（不可修复）。
    """
    if not raw or not raw.strip():
        return None

    s = _strip_markdown_fences(raw)
    s = _clean_control_chars(s)

    # 快速路径：清理后已合法
    if _try_loads(s) is not None:
        return s

    # 尝试正则抽取主 JSON 块
    extracted = _extract_json_block(s)
    if extracted is not None:
        if _try_loads(extracted) is not None:
            return extracted
        # 抽出的块仍不合法，继续截断修复
        s = extracted

    # 截断修复
    repaired = _repair_truncated(s)
    if repaired is not None:
        return repaired

    return None


# ------------------------------------------------------------------
# 内部辅助函数
# ------------------------------------------------------------------


def _strip_markdown_fences(text: str) -> str:
    """剥离 Markdown 代码块标记。"""
    s = text.strip()
    # 去除 ```json ... ``` 或 ``` ... ```
    s = re.sub(r"^```(?:json)?\s*\n?", "", s)
    s = re.sub(r"\n?\s*```\s*$", "", s)
    return s.strip()


def _clean_control_chars(text: str) -> str:
    """删除 ASCII 控制字符、零宽字符和孤立代理对。

    保留 \\n、\\r、\\t（它们在 JSON 字符串值中合法或由解析器处理）。
    """
    # 先保留常见空白字符
    def _replacer(m: re.Match) -> str:
        ch = m.group(0)
        if ch in ("\n", "\r", "\t"):
            return ch
        return ""

    return _CONTROL_CHAR_RE.sub(_replacer, text)


def _extract_json_block(text: str) -> str | None:
    """尝试用正则抽取文本中的主 JSON 对象。

    优先贪婪匹配从第一个 ``{`` 到最后一个 ``}`` 的部分（应对前后
    夹带解释文字）；若失败，退化为非贪婪匹配第一个完整块。
    """
    # 策略 1：从第一个 { 到最后一个 }（贪婪 — 适合单一 JSON 块 + 尾部文字）
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return m.group(0).strip()
    return None


def _try_loads(s: str) -> object | None:
    """尝试 json.loads，成功返回解析对象，失败返回 None。"""
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return None


def _repair_truncated(s: str) -> str | None:
    """修复因模型输出截断导致的 JSON 不完整。

    依次尝试：
    1. 闭合未结束的字符串（补 ``"``）
    2. 去除尾部悬挂逗号
    3. 按 LIFO 补充缺失的 ``}`` / ``]``

    每步修补后立即验证，成功即返回。
    """
    if not s or s[0] != "{":
        return None

    # 先尝试纯补 } / ] 不动字符串
    quick = _close_brackets(s)
    if _try_loads(quick) is not None:
        return quick

    # 尝试补闭合引号 + 去尾逗号 + 补括号
    patched = _close_unterminated_string(s)
    patched = _strip_trailing_commas(patched)
    patched = _close_brackets(patched)
    result = _try_loads(patched)
    if result is not None:
        return patched

    # 再尝试截断到最后一个完整的键值对后补括号
    truncated = _truncate_to_last_complete_pair(s)
    if truncated is not None:
        truncated = _strip_trailing_commas(truncated)
        truncated = _close_brackets(truncated)
        result = _try_loads(truncated)
        if result is not None:
            return truncated

    return None


def _close_unterminated_string(s: str) -> str:
    """如果字符串在未闭合的引号中结束，补一个 ``"``。

    简单状态机：跟踪是否处于字符串内部。
    """
    in_string = False
    escaped = False
    for ch in s:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            if in_string:
                escaped = True
            continue
        if ch == '"':
            in_string = not in_string

    if in_string:
        return s + '"'
    return s


def _strip_trailing_commas(s: str) -> str:
    """去除 ``}`` 或 ``]`` 前的多余逗号。"""
    # 清理形如 , } 或 , ] 的模式（允许中间有空白）
    s = re.sub(r",\s*([}\]])", r"\1", s)
    # 清理末尾的 ,"  或 ,
    s = re.sub(r",\s*$", "", s)
    return s


def _close_brackets(s: str) -> str:
    """统计未闭合的 ``{`` / ``[``，按 LIFO 顺序补齐。"""
    stack: list[str] = []
    in_string = False
    escaped = False

    for ch in s:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            if in_string:
                escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in ("}", "]"):
            if stack and stack[-1] == ch:
                stack.pop()

    # LIFO 补齐
    stack.reverse()
    return s + "".join(stack)


def _truncate_to_last_complete_pair(s: str) -> str | None:
    """尝试截断到最后一个看起来完整的 ``"key": value`` 对之后。

    在字符串外查找最后一个 ``,`` 或完整的值终结符（``"``、数字、
    ``true``/``false``/``null``/``}``/``]``），截断掉后面的碎片。
    """
    # 找到最后一个不在字符串内的逗号位置
    last_comma = -1
    in_string = False
    escaped = False
    for i, ch in enumerate(s):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            if in_string:
                escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == ",":
            last_comma = i

    if last_comma > 0:
        return s[:last_comma]
    return None
