"""Unit tests for unit_convert (新写, 8 种组合覆盖)."""

from __future__ import annotations

from dataclasses import dataclass

from unit_convert import generate_update_sql


def _th(text, data_unit=None, is_computed=False, idx_id=None, period=None):
    @dataclass
    class T:
        text: str
        data_unit: str | None = None
        is_computed: bool = False
        idx_id: str | None = None
        period: str | None = None
    return T(text=text, data_unit=data_unit, is_computed=is_computed, idx_id=idx_id, period=period)


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