"""Decimal-based unit conversion. No float, no LLM dependency."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


# 展示单位 -> scale_factor。依规格 §"列级单位声明 data-unit"。
SCALE_FACTOR: dict[str, Decimal] = {
    "元": Decimal("1"),
    "万元": Decimal("10000"),
    "亿元": Decimal("100000000"),
    "%": Decimal("0.01"),
    "百分点": Decimal("1"),
    "个": Decimal("1"),
    "次": Decimal("1"),
}


def _strip_thousands(raw_value: str) -> Decimal:
    """去掉千分位分隔符（'1,420.00' -> Decimal('1420.00')）。"""
    return Decimal(raw_value.replace(",", "").strip())


def convert_unit(raw_value: str, data_unit: str | None) -> Decimal:
    """将 SQLBot 原始值（带千分位）换算为设计师指定的展示单位。

    规格公式：display_value = raw * raw_unit_scale / display_unit_scale。
    Phase 1 的 raw_unit_scale = 1（我们尚未接入 get_indicator 的 unit 字段，
    因此假定 SQLBot 返回的原始值单位为元 / 原生单位）。

    返回 Decimal，全程不使用 float。
    """
    raw = _strip_thousands(raw_value)
    raw_unit_scale = Decimal("1")      # Phase 1 默认；见规格 §"⚠️ Phase 1 已知缺口"
    display_unit_scale = SCALE_FACTOR.get(data_unit or "", Decimal("1"))
    return raw * raw_unit_scale / display_unit_scale


__all__ = ["SCALE_FACTOR", "convert_unit"]
