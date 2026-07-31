from unittest.mock import MagicMock

from governance_lingxing_mcp.tools.product_performance import (
    query_product_performance,
)


def _make_client(result: dict) -> MagicMock:
    client = MagicMock()
    client.request.return_value = result
    return client


def test_basic_returns_total_and_list():
    """data 为列表时包装为 {"total", "list"} 返回。"""
    rows = [{"asin": "B001", "volume": 100, "sessions_total": 500, "cvr": 0.2}]
    client = _make_client({"code": 0, "data": rows})

    out = query_product_performance(
        client, sid=[1], start_date="2026-07-01", end_date="2026-07-30"
    )

    assert out == {"total": 1, "list": rows}
    call_params = client.request.call_args.kwargs["params"]
    assert call_params["sid"] == [1]
    assert call_params["summary_field"] == "asin"
    assert call_params["start_date"] == "2026-07-01"
    assert client.request.call_args.kwargs["ttl_seconds"] == 21600


def test_envelope_data_passthrough():
    """data 本身为 {"total", "list"} 信封结构时直接透传。"""
    envelope = {"total": 200, "list": [{"asin": "B002"}]}
    client = _make_client({"code": 0, "data": envelope})

    out = query_product_performance(
        client, sid=[1], start_date="2026-07-01", end_date="2026-07-30"
    )

    assert out == envelope


def test_int_sid_wrapped_to_list():
    """单个 int sid 自动包装为列表。"""
    client = _make_client({"code": 0, "data": []})
    query_product_performance(client, sid=3, start_date="2026-07-01", end_date="2026-07-02")
    assert client.request.call_args.kwargs["params"]["sid"] == [3]


def test_str_sid_passed_through():
    """字符串 sid（官方单店铺形式 "5608"）原样透传给领星。"""
    client = _make_client({"code": 0, "data": []})
    query_product_performance(client, sid="5608", start_date="2026-07-01", end_date="2026-07-02")
    assert client.request.call_args.kwargs["params"]["sid"] == "5608"


def test_multi_sid_list_passed_through():
    """多店铺数组原样透传（上限200）。"""
    client = _make_client({"code": 0, "data": []})
    query_product_performance(client, sid=[5609, 5608], start_date="2026-07-01", end_date="2026-07-02")
    assert client.request.call_args.kwargs["params"]["sid"] == [5609, 5608]


def test_search_and_sort_params_passthrough():
    """search_field/search_value/sort/currency 参数透传。"""
    client = _make_client({"code": 0, "data": []})
    query_product_performance(
        client,
        sid=[1],
        start_date="2026-07-01",
        end_date="2026-07-30",
        search_field="asin",
        search_value="B0XXXX",
        sort_field="volume",
        sort_order="asc",
        currency_code="CNY",
    )
    call_params = client.request.call_args.kwargs["params"]
    assert call_params["search_field"] == "asin"
    assert call_params["search_value"] == "B0XXXX"
    assert call_params["sort_field"] == "volume"
    assert call_params["sort_type"] == "asc"
    assert call_params["currency_code"] == "CNY"


def test_optional_params_omitted_by_default():
    """可选参数缺省时不进入请求参数。"""
    client = _make_client({"code": 0, "data": []})
    query_product_performance(client, sid=[1], start_date="2026-07-01", end_date="2026-07-02")
    call_params = client.request.call_args.kwargs["params"]
    assert "search_field" not in call_params
    assert "sort_field" not in call_params
    assert "currency_code" not in call_params


def test_non_zero_code_returns_error_envelope():
    client = _make_client({"code": 400, "message": "date span too large"})
    out = query_product_performance(
        client, sid=[1], start_date="2026-01-01", end_date="2026-07-30"
    )
    assert out["error"] == "date span too large"
    assert out["list"] == []
