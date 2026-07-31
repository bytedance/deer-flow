from unittest.mock import MagicMock

from governance_lingxing_mcp.tools.sales_trend import (
    API_PATH,
    aggregate_to_day,
    query_sales_trend,
)


def _make_client(result: dict) -> MagicMock:
    client = MagicMock()
    client.request.return_value = result
    return client


def test_aggregate_to_day_sums_hourly_rows():
    """24个小时段聚合为天：绝对值求和，price 重算，sales_rank 取最后非空值。"""
    rows = [
        {"r_date": "2026-07-01 00", "volume": 2, "order_items": 1, "amount": 20.0, "sales_rank": 100},
        {"r_date": "2026-07-01 12", "volume": 3, "order_items": 2, "amount": 40.0, "sales_rank": 80},
        {"r_date": "2026-07-02 08", "volume": 1, "order_items": 1, "amount": 15.0, "sales_rank": None},
    ]
    out = aggregate_to_day(rows)
    assert len(out) == 2
    assert out[0]["r_date"] == "2026-07-01"
    assert out[0]["volume"] == 5
    assert out[0]["order_items"] == 3
    assert out[0]["amount"] == 60.0
    assert out[0]["price"] == 12.0
    assert out[0]["sales_rank"] == 80
    assert out[1]["r_date"] == "2026-07-02"
    assert out[1]["sales_rank"] is None


def test_aggregate_to_day_handles_string_numerics():
    """领星数值字段可能是字符串（回归：原实现 += 字符串报 TypeError）。"""
    rows = [
        {"r_date": "2026-07-01 00", "volume": "2", "order_items": "1", "amount": "20.50", "sales_rank": 100},
        {"r_date": "2026-07-01 12", "volume": "3", "order_items": "2", "amount": "40.50", "sales_rank": 80},
    ]
    out = aggregate_to_day(rows)
    assert out[0]["volume"] == 5
    assert out[0]["order_items"] == 3
    assert out[0]["amount"] == 61.0
    assert out[0]["price"] == 12.2


def test_aggregate_to_day_zero_volume_price_is_none():
    rows = [{"r_date": "2026-07-01 00", "volume": 0, "order_items": 0, "amount": 0.0}]
    out = aggregate_to_day(rows)
    assert out[0]["price"] is None


def test_query_sales_trend_day_granularity_aggregates():
    """granularity=day 时按天聚合；参数透传 sids/summary_field 等。"""
    hourly = [
        {"r_date": "2026-07-01 00", "volume": 1, "order_items": 1, "amount": 10.0, "sales_rank": 50},
        {"r_date": "2026-07-01 01", "volume": 2, "order_items": 1, "amount": 25.0, "sales_rank": 40},
    ]
    client = _make_client({"code": 0, "data": hourly, "total": {"volume": 3}})

    out = query_sales_trend(
        client,
        sids="12345",
        date_start="2026-07-01",
        date_end="2026-07-30",
        summary_field="asin",
        summary_field_value="B0XXXX",
    )

    assert out["total"] == {"volume": 3}
    assert len(out["data"]) == 1
    assert out["data"][0]["volume"] == 3
    client.request.assert_called_once_with(
        "POST",
        API_PATH,
        params={
            "sids": "12345",
            "date_start": "2026-07-01",
            "date_end": "2026-07-30",
            "summary_field": "asin",
            "summary_field_value": "B0XXXX",
        },
        ttl_seconds=21600,
    )


def test_query_sales_trend_hour_granularity_passthrough():
    """granularity=hour 时保留原始小时段。"""
    hourly = [{"r_date": "2026-07-01 00", "volume": 1}, {"r_date": "2026-07-01 01", "volume": 2}]
    client = _make_client({"code": 0, "data": hourly})

    out = query_sales_trend(
        client, sids="1", date_start="2026-07-01", date_end="2026-07-01",
        summary_field="asin", summary_field_value="B0", granularity="hour",
    )

    assert out["data"] == hourly


def test_query_sales_trend_error_returns_error_envelope():
    client = _make_client({"code": 400, "message": "bad params"})
    out = query_sales_trend(
        client, sids="1", date_start="2026-07-01", date_end="2026-07-01",
        summary_field="asin", summary_field_value="B0",
    )
    assert "error" in out
    assert out["data"] == []
