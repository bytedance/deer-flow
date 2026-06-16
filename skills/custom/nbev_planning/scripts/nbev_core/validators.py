"""
validators.py — 入参校验与归一化（请求发出前拦截，提升调用成功率）
"""

from __future__ import annotations

import re
from datetime import date

from .errors import ValidationError

_MONTH_RE = re.compile(r"^\d{4}-\d{2}-01$")

_DIM_ALIAS = {
    "产品": "product", "product": "product",
    "客户": "customer", "customer": "customer",
    "队伍": "team", "team": "team",
}


def normalize_month(month: str | None) -> str:
    """
    规划场景：缺省→【下个月】1号（如今天 2026-06-16 → 2026-07-01）。
    非法格式→报错（不静默猜测）。
    """
    if not month:
        today = date.today()
        year = today.year + (1 if today.month == 12 else 0)
        m = 1 if today.month == 12 else today.month + 1
        return f"{year:04d}-{m:02d}-01"
    month = month.strip()
    if not _MONTH_RE.match(month):
        raise ValidationError(
            "MONTH_FORMAT_INVALID",
            f"month='{month}' 格式不正确",
            hint="请使用 YYYY-MM-01，例如 2026-07-01",
            fields=["month"],
        )
    return month


def validate_target_nbev(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValidationError(
            "TARGET_NBEV_INVALID",
            f"target_nbev='{value}' 不是合法数值",
            hint="请提供正数，单位万元，例如 6000",
            fields=["target_nbev"],
        )
    if v <= 0:
        raise ValidationError(
            "TARGET_NBEV_NONPOSITIVE",
            f"target_nbev={v} 必须为正数",
            hint="请提供大于 0 的目标 NBEV（万元）",
            fields=["target_nbev"],
        )
    return v


def validate_ratio(name: str, value, lo: float = 0.0, hi: float = 1.0):
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValidationError(
            "RATIO_NOT_NUMBER",
            f"{name}='{value}' 不是合法数值",
            hint=f"请提供 {lo}~{hi} 之间的小数",
            fields=[name],
        )
    if not (lo <= v <= hi):
        raise ValidationError(
            "RATIO_OUT_OF_BOUND",
            f"{name}={v} 超出允许范围 [{lo}, {hi}]",
            hint=f"请将 {name} 调整到 {lo}~{hi} 之间",
            fields=[name],
        )
    return v


def validate_dimensions(dimensions) -> list[str]:
    if not dimensions:
        raise ValidationError(
            "DIMENSIONS_EMPTY",
            "未指定测算维度",
            hint="请至少选择一个：产品 / 客户 / 队伍",
            fields=["dimensions"],
        )
    out, seen = [], set()
    for d in dimensions:
        raw = str(d).strip()
        norm = _DIM_ALIAS.get(raw) or _DIM_ALIAS.get(raw.lower())
        if not norm:
            raise ValidationError(
                "DIMENSION_INVALID",
                f"无法识别的测算维度：{d}",
                hint="可选值：产品 / 客户 / 队伍",
                fields=["dimensions"],
            )
        if norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out
