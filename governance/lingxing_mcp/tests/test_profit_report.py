from unittest.mock import MagicMock

from governance_lingxing_mcp.tools.profit_report import (
    API_PATH,
    query_profit_report_asin,
)


def _make_client(result: dict) -> MagicMock:
    client = MagicMock()
    client.request.return_value = result
    return client


def test_basic_camelcase_params():
    """领星利润报表接口使用 camelCase 参数名，需原样透传。"""
    data = [{"asin": "B001", "fbaDeliveryFee": 123.4, "grossProfit": 56.7}]
    client = _make_client({"code": 0, "data": data})

    out = query_profit_report_asin(
        client, sids=[1, 2], start_date="2026-07-01", end_date="2026-07-30"
    )

    assert out == data
    client.request.assert_called_once_with(
        "POST", API_PATH,
        params={"sids": [1, 2], "startDate": "2026-07-01", "endDate": "2026-07-30",
                "offset": 0, "length": 100},
        ttl_seconds=21600,
    )


def test_optional_params_passthrough():
    client = _make_client({"code": 0, "data": []})
    query_profit_report_asin(
        client, sids=[1], start_date="2026-07-01", end_date="2026-07-30",
        search_field="asin", search_value=["B0X"], mids=[1],
        monthly_query=True, currency_code="CNY", order_status="Disbursed",
    )
    call_params = client.request.call_args.kwargs["params"]
    assert call_params["searchField"] == "asin"
    assert call_params["searchValue"] == ["B0X"]
    assert call_params["mids"] == [1]
    assert call_params["monthlyQuery"] is True
    assert call_params["currencyCode"] == "CNY"
    assert call_params["orderStatus"] == "Disbursed"


def test_int_sid_wrapped_to_list():
    client = _make_client({"code": 0, "data": []})
    query_profit_report_asin(client, sids=5, start_date="2026-07-01", end_date="2026-07-02")
    assert client.request.call_args.kwargs["params"]["sids"] == [5]


def test_str_sid_wrapped_to_list():
    """字符串 sid "5608" 规范化为单元素数组。"""
    client = _make_client({"code": 0, "data": []})
    query_profit_report_asin(client, sids="5608", start_date="2026-07-01", end_date="2026-07-02")
    assert client.request.call_args.kwargs["params"]["sids"] == [5608]


def test_envelope_data_extracts_list():
    client = _make_client({"code": 0, "data": {"total": 1, "list": [{"asin": "B1"}]}})
    out = query_profit_report_asin(client, sids=[1], start_date="2026-07-01", end_date="2026-07-02")
    assert out == [{"asin": "B1"}]


def test_non_zero_code_returns_error():
    client = _make_client({"code": 400, "message": "bad request"})
    out = query_profit_report_asin(client, sids=[1], start_date="2026-07-01", end_date="2026-07-02")
    assert out and "error" in out[0]
