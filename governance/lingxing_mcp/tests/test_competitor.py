from unittest.mock import MagicMock

from governance_lingxing_mcp.tools.competitor import (
    API_PATH,
    query_competitor_monitor,
)


def _make_client(result: dict) -> MagicMock:
    client = MagicMock()
    client.request.return_value = result
    return client


def test_basic_returns_competitor_rows():
    data = [{"asin": "B0C", "big_category_rank": "123", "price": "29.99"}]
    client = _make_client({"code": 0, "data": data})

    out = query_competitor_monitor(
        client, search_field="asin", search_value="B0C", levels=[1, 2],
        update_time_start="2026-07-01", update_time_end="2026-07-30",
    )

    assert out == data
    client.request.assert_called_once_with(
        "POST", API_PATH,
        params={"offset": 0, "length": 20, "search_field": "asin", "search_value": "B0C",
                "levels": [1, 2], "update_time_start": "2026-07-01",
                "update_time_end": "2026-07-30"},
        ttl_seconds=21600,
    )


def test_empty_result_returns_monitor_hint():
    """竞品为监控制：查询为空返回提示，引导用户到领星ERP网页端添加。"""
    client = _make_client({"code": 0, "data": []})
    out = query_competitor_monitor(client)
    assert out and out[0].get("info") == "no monitored competitors found"
    assert "hint" in out[0]


def test_non_zero_code_returns_error():
    client = _make_client({"code": 500, "message": "boom"})
    out = query_competitor_monitor(client)
    assert out and "error" in out[0]
