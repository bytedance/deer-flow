"""
validators.py — 画像入参校验与归一化

与规划的关键差异：画像月份缺省取【当前月】1号（如今天 2026-06-16 → 2026-06-01）；
规划取下月1号。
"""

from __future__ import annotations

import re
from datetime import date

from .errors import ValidationError

_MONTH_RE = re.compile(r"^\d{4}-\d{2}-01$")

_DIM_ALIAS = {
    "队伍": "team", "team": "team", "人力": "team",
    "客户": "customer", "customer": "customer",
    "产品": "product", "product": "product",
    "全部": "all", "所有": "all", "完整": "all", "all": "all",
}


def normalize_month(month: str | None) -> str:
    """
    画像场景：缺省→【当前月】1号（如今天 2026-06-16 → 2026-06-01）。
    （业务口径：取当前月初作为画像数据月份。）
    非法格式→报错（不静默猜测）。
    """
    if not month:
        today = date.today()
        return f"{today.year:04d}-{today.month:02d}-01"
    month = month.strip()
    if not _MONTH_RE.match(month):
        raise ValidationError(
            "MONTH_FORMAT_INVALID",
            f"month='{month}' 格式不正确",
            hint="请使用 YYYY-MM-01，例如 2026-06-01",
            fields=["month"],
        )
    return month


def normalize_dimensions(dimensions) -> list[str]:
    """
    归一化画像维度。支持 队伍/客户/产品/全部(all)。
    缺省（None/空）→ 全部三个维度（画像无强制澄清需求，给出全景更友好）。
    'all' 展开为三个维度。
    """
    if not dimensions:
        return ["team", "customer", "product"]
    norm, seen = [], set()
    for d in dimensions:
        raw = str(d).strip()
        key = _DIM_ALIAS.get(raw) or _DIM_ALIAS.get(raw.lower())
        if not key:
            raise ValidationError(
                "DIMENSION_INVALID",
                f"无法识别的画像维度：{d}",
                hint="可选值：队伍 / 客户 / 产品 / 全部",
                fields=["dimensions"],
            )
        if key == "all":
            return ["team", "customer", "product"]
        if key not in seen:
            seen.add(key)
            norm.append(key)
    return norm
