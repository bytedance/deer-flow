from unittest.mock import MagicMock

from governance_lingxing_mcp.tools.parent_ad import (
    API_PATH,
    query_parent_ad,
)


def _make_client(result: dict) -> MagicMock:
    client = MagicMock()
    client.request.return_value = result
    return client


def test_query_parent_ad_basic_returns_data():
    """sid + start_date + end_date 默认调用，返回 data 列表，TTL=21600。"""
    data = [{"parent_asin": "B001", "acos": 0.25, "roas": 4.0, "spend": 12.3}]
    client = _make_client({"code": 0, "message": "操作成功", "data": data})

    out = query_parent_ad(
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


def test_query_parent_ad_with_search_value():
    """带 search_value：params 增加 search_field/search_value。"""
    data = [{"parent_asin": "B002", "acos": 0.10}]
    client = _make_client({"code": 0, "message": "ok", "data": data})

    out = query_parent_ad(
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


def test_query_parent_ad_custom_length_and_summary():
    """自定义 length 与 summary_field 透传到 params。"""
    client = _make_client({"code": 0, "data": []})
    query_parent_ad(
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


def test_query_parent_ad_non_zero_code_returns_empty():
    """code != 0（鉴权失败/业务错误）时返回空列表，不抛异常。"""
    client = _make_client({"code": 10001, "message": "invalid token", "data": []})
    out = query_parent_ad(
        client,
        sid=[1],
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    assert out == []


def test_query_parent_ad_missing_data_field_returns_empty():
    """响应缺少 data 字段时安全返回空列表。"""
    client = _make_client({"code": 0, "message": "操作成功"})
    out = query_parent_ad(
        client,
        sid=[1],
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    assert out == []


def test_query_parent_ad_null_data_returns_empty():
    """data 显式为 null 时返回空列表（防御 `or []` 兜底）。"""
    client = _make_client({"code": 0, "msg": "查询异常", "data": None})
    out = query_parent_ad(
        client,
        sid=[1],
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    assert out == []


def test_query_parent_ad_str_sid_passes_through():
    """sid 支持字符串传入，原样透传。"""
    client = _make_client({"code": 0, "data": []})
    query_parent_ad(
        client,
        sid="abc",
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    assert client.request.call_args.kwargs["params"]["sid"] == "abc"
