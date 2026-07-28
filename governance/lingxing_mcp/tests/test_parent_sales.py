from unittest.mock import MagicMock

from governance_lingxing_mcp.tools.parent_sales import (
    API_PATH,
    query_parent_sales,
)


def _make_client(result: dict) -> MagicMock:
    client = MagicMock()
    client.request.return_value = result
    return client


def test_query_parent_sales_basic_returns_data():
    """无 search_value：默认参数调用，返回 data 列表。"""
    data = [{"parent_asin": "B001", "volume": 100, "amount": 99.9}]
    client = _make_client({"code": 0, "message": "ok", "data": data})

    out = query_parent_sales(
        client,
        sid=[1, 2],
        start_date="2026-01-01",
        end_date="2026-01-31",
    )

    assert out == data
    client.request.assert_called_once_with(
        "POST",
        API_PATH,
        params={
            "offset": 0,
            "length": 100,
            "sort_field": "volume",
            "sort_type": "desc",
            "sid": [1, 2],
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "summary_field": "parent_asin",
        },
        ttl_seconds=21600,
    )


def test_query_parent_sales_with_search_value():
    """带 search_value：params 增加 search_field/search_value。"""
    data = [{"parent_asin": "B002", "volume": 50}]
    client = _make_client({"code": 0, "message": "ok", "data": data})

    out = query_parent_sales(
        client,
        sid="3",
        start_date="2026-02-01",
        end_date="2026-02-28",
        search_value=["B002"],
    )

    assert out == data
    call_params = client.request.call_args.kwargs["params"]
    assert call_params["search_field"] == "parent_asin"
    assert call_params["search_value"] == ["B002"]
    assert client.request.call_args.kwargs["ttl_seconds"] == 21600


def test_query_parent_sales_custom_length_and_summary():
    """自定义 length 与 summary_field 透传到 params。"""
    client = _make_client({"code": 0, "data": []})
    query_parent_sales(
        client,
        sid=[1],
        start_date="2026-01-01",
        end_date="2026-01-02",
        summary_field="child_asin",
        length=20,
    )
    call_params = client.request.call_args.kwargs["params"]
    assert call_params["length"] == 20
    assert call_params["summary_field"] == "child_asin"


def test_query_parent_sales_non_zero_code_returns_empty():
    """code != 0（鉴权失败/业务错误）时返回空列表，不抛异常。"""
    client = _make_client({"code": 10001, "message": "invalid token", "data": []})
    out = query_parent_sales(
        client,
        sid=[1],
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    assert out == []


def test_query_parent_sales_missing_data_field_returns_empty():
    """响应缺少 data 字段时安全返回空列表。"""
    client = _make_client({"code": 0, "message": "ok"})
    out = query_parent_sales(
        client,
        sid=[1],
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    assert out == []


def test_query_parent_sales_str_sid_passes_through():
    """sid 支持字符串传入，原样透传。"""
    client = _make_client({"code": 0, "data": []})
    query_parent_sales(
        client,
        sid="abc",
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    assert client.request.call_args.kwargs["params"]["sid"] == "abc"
