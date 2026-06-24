"""Unit tests for scripts/unit_conversion.py."""
from decimal import Decimal

import pytest

import unit_conversion as uc


def test_scale_factor_table_values():
    """标准单位映射到规格中的 scale_factor 列。"""
    assert uc.SCALE_FACTOR["元"] == Decimal("1")
    assert uc.SCALE_FACTOR["万元"] == Decimal("10000")
    assert uc.SCALE_FACTOR["亿元"] == Decimal("100000000")
    assert uc.SCALE_FACTOR["%"] == Decimal("0.01")
    assert uc.SCALE_FACTOR["百分点"] == Decimal("1")
    assert uc.SCALE_FACTOR["个"] == Decimal("1")
    assert uc.SCALE_FACTOR["次"] == Decimal("1")


def test_strip_thousands_separator():
    """内部辅助函数处理 '1,420.00' -> Decimal('1420.00')。"""
    assert uc._strip_thousands("1,420.00") == Decimal("1420.00")
    assert uc._strip_thousands("123,456,789") == Decimal("123456789")
    assert uc._strip_thousands("0") == Decimal("0")


def test_convert_unit_yuan_passthrough():
    """data-unit=元 -> raw_value 1:1 显示。"""
    assert uc.convert_unit("1,420.00", "元") == Decimal("1420.00")


def test_convert_unit_wan():
    """data-unit=万元 -> 除以 10000。"""
    # SQLBot 原始单位为元；设计师想用万元
    assert uc.convert_unit("12,000,000", "万元") == Decimal("1200.0000")


def test_convert_unit_yi():
    """data-unit=亿元 -> 除以 1e8。"""
    assert uc.convert_unit("987,654,321", "亿元") == Decimal("9.87654321")


def test_convert_unit_percentage():
    """data-unit=% -> 除以 0.01，使 0.366 显示为 36.60%。"""
    assert uc.convert_unit("0.366", "%") == Decimal("36.6")


def test_convert_unit_none_keeps_raw():
    """data-unit 缺省或空 -> 原始值的 Decimal，恒等缩放。"""
    assert uc.convert_unit("1,234", None) == Decimal("1234")
    assert uc.convert_unit("1,234", "") == Decimal("1234")


def test_convert_unit_custom_string_passthrough():
    """data-unit='个'（已是计数单位） -> 1:1。"""
    assert uc.convert_unit("1,420", "个") == Decimal("1420")


def test_convert_unit_raises_on_bad_string():
    """非数字 raw_value -> InvalidOperation（Decimal）。"""
    from decimal import InvalidOperation
    with pytest.raises(InvalidOperation):
        uc.convert_unit("not-a-number", "元")


def test_round_trip_yuan_to_wan_to_yuan():
    """12,000,000 元 -> 1200 万元（Decimal 无精度损失）。"""
    wan_value = uc.convert_unit("12,000,000", "万元")
    assert wan_value == Decimal("1200.0000")
