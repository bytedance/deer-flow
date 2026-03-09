"""UTF-16 标题长度计算，对应 Go pkg/xhsutil/title.go。"""

from __future__ import annotations

MAX_TITLE_LENGTH = 20


def truncate_title(s: str, max_length: int = MAX_TITLE_LENGTH) -> str:
    """将标题裁剪到 max_length 以内（逐字符从末尾去除）。

    Args:
        s: 原始标题。
        max_length: 最大允许长度（默认 20）。

    Returns:
        满足长度要求的标题字符串。
    """
    if calc_title_length(s) <= max_length:
        return s
    while s and calc_title_length(s) > max_length:
        s = s[:-1]
    return s


def calc_title_length(s: str) -> int:
    """计算小红书标题长度。

    规则（同 Go CalcTitleLength）：
    - 非 ASCII 字符（中文、全角符号、emoji 代码单元等）算 2
    - ASCII 字符算 1
    - 最终结果向上取整除以 2，上限 MAX_TITLE_LENGTH = 20

    Emoji 按 UTF-16 码元计数：
    - 基础 emoji（如 ✨ U+2728, BMP）= 1 码元 → 权重 2 → 贡献 1
    - SMP emoji（如 💇 U+1F487，surrogate pair）= 2 码元 → 权重 4 → 贡献 2
    - ZWJ 序列（如 💇‍♀️）= 5 码元 → 权重 10 → 贡献 5
    - 旗帜（如 🇨🇳，2 个 regional indicator）= 4 码元 → 权重 8 → 贡献 4

    Examples:
        >>> calc_title_length("你好世界")
        4
        >>> calc_title_length("hello")
        3
        >>> calc_title_length("OOTD穿搭分享")
        6
        >>> calc_title_length("💇\u200d♀️")
        5
    """
    byte_len = 0
    encoded = s.encode("utf-16-le")
    for i in range(0, len(encoded), 2):
        code_unit = int.from_bytes(encoded[i : i + 2], "little")
        if code_unit > 127:
            byte_len += 2
        else:
            byte_len += 1
    return (byte_len + 1) // 2
