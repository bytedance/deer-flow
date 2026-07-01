"""Unit tests for unit_convert (新写, 8 种组合覆盖)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from unit_convert import apply_units, generate_update_sql


def _th(text, data_unit=None, is_computed=False, idx_id=None, period=None):
    @dataclass
    class T:
        text: str
        data_unit: str | None = None
        is_computed: bool = False
        idx_id: str | None = None
        period: str | None = None
    return T(text=text, data_unit=data_unit, is_computed=is_computed, idx_id=idx_id, period=period)


def _hdr_dict(text, data_unit=None, is_computed=False, idx_id=None, period=None):
    """Phase 1 headers are dicts (from asdict(Th)). apply_units consumes dicts."""
    return {"text": text, "data_unit": data_unit, "is_computed": is_computed,
            "idx_id": idx_id, "period": period}


def test_yuan_target_emits_no_update():
    headers = [[_th("col", data_unit="元", idx_id="A", period="202603")]]
    sql = "\n".join(generate_update_sql(headers, target_table="wide"))
    assert sql == ""


def test_wan_target_emits_divide_10000():
    headers = [[_th("col", data_unit="万元", idx_id="A", period="202603")]]
    sql = "\n".join(generate_update_sql(headers, target_table="wide"))
    assert "wide" in sql
    assert "/ 10000" in sql


def test_yi_target_emits_divide_100000000():
    headers = [[_th("col", data_unit="亿元", idx_id="A", period="202603")]]
    sql = "\n".join(generate_update_sql(headers, target_table="wide"))
    assert "/ 100000000" in sql


def test_percent_target_on_computed_emits_multiply_100():
    headers = [[_th("ratio", data_unit="%", is_computed=True, idx_id=None, period="202603")]]
    sql = "\n".join(generate_update_sql(headers, target_table="wide"))
    assert "* 100" in sql


def test_percent_target_on_basic_emits_no_update():
    # 基础列不应用 % 换算 (Phase 1 政策)
    headers = [[_th("col", data_unit="%", is_computed=False, idx_id="A", period="202603")]]
    sql = "\n".join(generate_update_sql(headers, target_table="wide"))
    assert sql == ""


def test_unknown_unit_emits_no_update():
    headers = [[_th("col", data_unit="千美元", idx_id="A", period="202603")]]
    sql = "\n".join(generate_update_sql(headers, target_table="wide"))
    assert sql == ""


def test_mixed_columns_emits_multiple_updates():
    headers = [
        [_th("a", data_unit="万元", idx_id="A", period="202603")],
        [_th("b", data_unit="元", idx_id="B", period="202603")],
        [_th("c", data_unit="%", is_computed=True, idx_id=None)],
    ]
    sql = "\n".join(generate_update_sql(headers, target_table="wide"))
    assert "/ 10000" in sql
    assert "* 100" in sql
    # 元 不出现在 SQL 中
    assert "B" not in sql


def test_columns_keyed_by_idx_at_period():
    headers = [[_th("a", data_unit="万元", idx_id="BAS_001", period="202603")]]
    sql = "\n".join(generate_update_sql(headers, target_table="wide"))
    # column key in wide table
    assert "BAS_001@202603" in sql


# ---- Phase 1: apply_units (Python path, Decimal precision) ---- #

def test_apply_units_wan_divides_by_10000():
    wide = [{"branch_num": "1", "A@202603": Decimal("12345678.0000")}]
    headers = [[_hdr_dict("col", data_unit="万元", idx_id="A", period="202603")]]
    out = apply_units(wide, headers)
    assert out[0]["A@202603"] == Decimal("1234.5678000000")  # 10 decimal places preserved


def test_apply_units_yi_divides_by_1e8():
    wide = [{"branch_num": "1", "A@202603": Decimal("1234567890.0000")}]
    headers = [[_hdr_dict("col", data_unit="亿元", idx_id="A", period="202603")]]
    out = apply_units(wide, headers)
    assert out[0]["A@202603"] == Decimal("12.3456789000")


def test_apply_units_percent_multiplies_100_on_computed():
    wide = [{"branch_num": "1", "利润率": Decimal("0.2")}]
    headers = [[_hdr_dict("利润率", data_unit="%", is_computed=True)]]
    out = apply_units(wide, headers)
    assert out[0]["利润率"] == Decimal("20.0000")


def test_apply_units_yuan_is_identity():
    wide = [{"branch_num": "1", "A@202603": Decimal("12345")}]
    headers = [[_hdr_dict("col", data_unit="元", idx_id="A", period="202603")]]
    out = apply_units(wide, headers)
    assert out[0]["A@202603"] == Decimal("12345")  # unchanged


def test_apply_units_unknown_unit_skipped():
    wide = [{"branch_num": "1", "A@202603": Decimal("12345")}]
    headers = [[_hdr_dict("col", data_unit="千美元", idx_id="A", period="202603")]]
    out = apply_units(wide, headers)
    assert out[0]["A@202603"] == Decimal("12345")  # unchanged


def test_apply_units_percent_on_basic_skipped():
    # 基础列不应用 % 换算 (Phase 1 政策)
    wide = [{"branch_num": "1", "A@202603": Decimal("0.2")}]
    headers = [[_hdr_dict("col", data_unit="%", is_computed=False, idx_id="A", period="202603")]]
    out = apply_units(wide, headers)
    assert out[0]["A@202603"] == Decimal("0.2")  # unchanged


def test_apply_units_non_decimal_cell_skipped():
    """If cell is None or str (e.g. sentinel), apply_units leaves it alone.

    With Phase 1 cell=None, this is the common case. Sentinel strings would
    also be skipped, but task 13 keeps sentinels out of cells.
    """
    wide = [{"branch_num": "1", "A@202603": None}]
    headers = [[_hdr_dict("col", data_unit="万元", idx_id="A", period="202603")]]
    out = apply_units(wide, headers)
    assert out[0]["A@202603"] is None  # not converted, not crashed


def test_apply_units_mixed_columns():
    wide = [
        {"branch_num": "1", "A@202603": Decimal("12345678"), "B@202603": Decimal("50000"), "利润率": Decimal("0.25")},
    ]
    headers = [
        [_hdr_dict("a", data_unit="万元", idx_id="A", period="202603")],
        [_hdr_dict("b", data_unit="元", idx_id="B", period="202603")],
        [_hdr_dict("利润率", data_unit="%", is_computed=True)],
    ]
    out = apply_units(wide, headers)
    assert out[0]["A@202603"] == Decimal("1234.5678")
    assert out[0]["B@202603"] == Decimal("50000")  # 元 identity
    assert out[0]["利润率"] == Decimal("25.00")


def test_apply_units_does_not_mutate_input():
    """Issue 5 修复: apply_units 是纯函数, 不修改原 wide 列表."""
    wide = [{"branch_num": "1", "A@202603": Decimal("12345678")}]
    headers = [[_hdr_dict("col", data_unit="万元", idx_id="A", period="202603")]]
    out = apply_units(wide, headers)
    # 原 wide 未变
    assert wide[0]["A@202603"] == Decimal("12345678")
    # 返回新 list (不是同一个对象)
    assert out is not wide
    assert out[0]["A@202603"] == Decimal("1234.5678")