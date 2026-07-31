from unittest.mock import MagicMock

from governance_lingxing_mcp.tools.fba_inventory import (
    API_PATH,
    add_redundancy_fields,
    query_fba_inventory,
)


def _make_client(result: dict) -> MagicMock:
    client = MagicMock()
    client.request.return_value = result
    return client


def _age_row():
    return {
        "asin": "B001",
        "inv_age_0_to_30_days": 10,
        "inv_age_31_to_60_days": 20,
        "inv_age_61_to_90_days": 30,
        "inv_age_91_to_180_days": 40,
        "inv_age_181_to_270_days": 50,
        "inv_age_271_to_365_days": 60,
        "inv_age_365_plus_days": 70,
        "cost": 2.5,
    }


def test_redundancy_default_90_days():
    """阈值90天：冗余 = 91-180 + 181-270 + 271-365 + 365+。"""
    row = _age_row()
    add_redundancy_fields(row)
    assert row["redundant_quantity"] == 40 + 50 + 60 + 70
    assert row["redundant_cost"] == round((40 + 50 + 60 + 70) * 2.5, 2)
    assert row["redundant_threshold_days"] == 90


def test_redundancy_threshold_180():
    row = _age_row()
    add_redundancy_fields(row, threshold_days=180)
    assert row["redundant_quantity"] == 50 + 60 + 70


def test_redundancy_threshold_365():
    row = _age_row()
    add_redundancy_fields(row, threshold_days=365)
    assert row["redundant_quantity"] == 70


def test_redundancy_handles_string_numerics():
    """库龄与成本字段为字符串时也能正确计算（回归：round(str) 报 TypeError）。"""
    row = {
        "asin": "B003",
        "inv_age_91_to_180_days": "40",
        "inv_age_365_plus_days": "10",
        "cost": "2.50",
    }
    add_redundancy_fields(row)
    assert row["redundant_quantity"] == 50
    assert row["redundant_cost"] == 125.0


def test_redundancy_missing_fields_treated_as_zero():
    row = {"asin": "B002", "cost": 10.0}
    add_redundancy_fields(row)
    assert row["redundant_quantity"] == 0
    assert row["redundant_cost"] == 0.0


def test_query_fba_inventory_adds_redundancy_to_each_row():
    """每行库存数据都附加冗余计算字段，sid 转字符串，TTL=3600。"""
    client = _make_client({"code": 0, "data": [_age_row()]})

    out = query_fba_inventory(client, sid=123, search_field="asin", search_value="B001")

    assert out[0]["redundant_quantity"] == 220
    client.request.assert_called_once_with(
        "POST", API_PATH,
        params={"sid": "123", "offset": 0, "length": 100,
                "search_field": "asin", "search_value": "B001"},
        ttl_seconds=3600,
    )


def test_query_fba_inventory_custom_threshold():
    client = _make_client({"code": 0, "data": [_age_row()]})
    out = query_fba_inventory(client, sid="1", redundant_threshold_days=180)
    assert out[0]["redundant_quantity"] == 180


def test_non_zero_code_returns_error():
    client = _make_client({"code": 500, "message": "boom"})
    out = query_fba_inventory(client, sid="1")
    assert out and "error" in out[0]
