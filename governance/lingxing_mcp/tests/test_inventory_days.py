from unittest.mock import MagicMock

from governance_lingxing_mcp.tools.inventory_days import (
    FBA_STOCK_API_PATH,
    SALES_FORECAST_API_PATH,
    query_inventory_days,
)


def _stock_result(rows: list) -> dict:
    return {"code": 0, "message": "success", "data": rows, "total": len(rows)}


def _sales_result(day_list: dict) -> dict:
    return {"code": 0, "message": "success", "data": {"list": day_list}}


def _make_two_call_client(stock: dict, sales: dict) -> MagicMock:
    """FBA 库存端点与销量预测端点分别返回不同结果。"""
    client = MagicMock()

    def _request(method, path, params, ttl_seconds):
        if path == FBA_STOCK_API_PATH:
            return stock
        if path == SALES_FORECAST_API_PATH:
            return sales
        raise AssertionError(f"unexpected path: {path}")

    client.request.side_effect = _request
    return client


def test_query_inventory_days_merges_stock_and_sales():
    """合并 FBA 库存与销量预测，TTL=3600，返回 in_stock/in_transit/daily_sales/available_days。"""
    stock = _stock_result(
        [
            {
                "asin": "B0XXX",
                "afn_fulfillable_quantity": 100,
                "afn_inbound_shipped_quantity": 30,
            }
        ]
    )
    # 最近一天日销 = 5；available_days = 100/5 = 20.0
    sales = _sales_result(
        {
            "2026-01-30": [0, 4, 96],
            "2026-01-31": [0, 5, 91],
        }
    )
    client = _make_two_call_client(stock, sales)

    out = query_inventory_days(client, sid=136, asin="B0XXX")

    assert out == {
        "asin": "B0XXX",
        "in_stock": 100,
        "in_transit": 30,
        "daily_sales": 5,
        "available_days": 20.0,
    }
    # 两个端点 TTL 均为 3600
    calls = client.request.call_args_list
    assert all(c.kwargs["ttl_seconds"] == 3600 for c in calls)
    # FBA 库存按 asin 检索
    stock_call = next(c for c in calls if c.args[1] == FBA_STOCK_API_PATH)
    assert stock_call.kwargs["params"]["search_field"] == "asin"
    assert stock_call.kwargs["params"]["search_value"] == "B0XXX"
    # 销量预测传 sid/asin/sug_type
    sales_call = next(c for c in calls if c.args[1] == SALES_FORECAST_API_PATH)
    assert sales_call.kwargs["params"]["sid"] == 136
    assert sales_call.kwargs["params"]["asin"] == "B0XXX"
    assert sales_call.kwargs["params"]["sug_type"] == 3


def test_query_inventory_days_zero_daily_sales_available_days_none():
    """日销为 0 时 available_days 为 None，避免除零。"""
    stock = _stock_result(
        [
            {
                "asin": "B0XXX",
                "afn_fulfillable_quantity": 50,
                "afn_inbound_shipped_quantity": 0,
            }
        ]
    )
    sales = _sales_result({"2026-01-31": [0, 0, 50]})
    client = _make_two_call_client(stock, sales)

    out = query_inventory_days(client, sid=136, asin="B0XXX")

    assert out["in_stock"] == 50
    assert out["in_transit"] == 0
    assert out["daily_sales"] == 0
    assert out["available_days"] is None


def test_query_inventory_days_stock_failure_returns_zero_stock():
    """FBA 库存端点 code != 0 时 in_stock/in_transit 归零，仍返回销量。"""
    stock = {"code": 10001, "message": "invalid", "data": []}
    sales = _sales_result({"2026-01-31": [0, 5, 0]})
    client = _make_two_call_client(stock, sales)

    out = query_inventory_days(client, sid=136, asin="B0XXX")

    assert out["in_stock"] == 0
    assert out["in_transit"] == 0
    assert out["daily_sales"] == 5
    assert out["available_days"] == 0.0


def test_query_inventory_days_sales_failure_returns_zero_daily_sales():
    """销量预测端点 code != 0 时 daily_sales=0，available_days=None。"""
    stock = _stock_result(
        [
            {
                "asin": "B0XXX",
                "afn_fulfillable_quantity": 80,
                "afn_inbound_shipped_quantity": 10,
            }
        ]
    )
    sales = {"code": 10001, "message": "invalid", "data": {}}
    client = _make_two_call_client(stock, sales)

    out = query_inventory_days(client, sid=136, asin="B0XXX")

    assert out["in_stock"] == 80
    assert out["in_transit"] == 10
    assert out["daily_sales"] == 0
    assert out["available_days"] is None


def test_query_inventory_days_empty_stock_data_returns_zero():
    """FBA 库存返回空 data 列表时 in_stock/in_transit 归零。"""
    stock = _stock_result([])
    sales = _sales_result({"2026-01-31": [0, 10, 0]})
    client = _make_two_call_client(stock, sales)

    out = query_inventory_days(client, sid=136, asin="B0XXX")

    assert out["in_stock"] == 0
    assert out["in_transit"] == 0
    assert out["daily_sales"] == 10
    assert out["available_days"] == 0.0


def test_query_inventory_days_mode_passed_through():
    """mode 参数透传到销量预测端点。"""
    stock = _stock_result(
        [
            {
                "asin": "B0XXX",
                "afn_fulfillable_quantity": 100,
                "afn_inbound_shipped_quantity": 0,
            }
        ]
    )
    sales = _sales_result({"2026-01-31": [0, 10, 90]})
    client = _make_two_call_client(stock, sales)

    query_inventory_days(client, sid=136, asin="B0XXX", mode=1)

    sales_call = next(
        c for c in client.request.call_args_list if c.args[1] == SALES_FORECAST_API_PATH
    )
    assert sales_call.kwargs["params"]["mode"] == 1
