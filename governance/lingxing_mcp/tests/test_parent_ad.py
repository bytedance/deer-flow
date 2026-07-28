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
    """sid + report_date 默认调用，返回 data 列表，TTL=1800。"""
    data = [{"ad_id": 1634667842919, "asin": "B08D3Q3TT7", "impressions": 1}]
    client = _make_client({"code": 0, "message": "操作成功", "data": data})

    out = query_parent_ad(client, sid=109, report_date="2026-01-01")

    assert out == data
    client.request.assert_called_once_with(
        "POST",
        API_PATH,
        params={
            "sid": 109,
            "report_date": "2026-01-01",
            "show_detail": 0,
            "offset": 0,
            "length": 100,
        },
        ttl_seconds=1800,
    )


def test_query_parent_ad_with_profile_id_and_show_detail():
    """profile_id 与 show_detail 透传到 params。"""
    client = _make_client({"code": 0, "data": []})

    query_parent_ad(
        client,
        sid=109,
        report_date="2026-01-01",
        profile_id=123456,
        show_detail=1,
    )

    call_params = client.request.call_args.kwargs["params"]
    assert call_params["profile_id"] == 123456
    assert call_params["show_detail"] == 1
    assert client.request.call_args.kwargs["ttl_seconds"] == 1800


def test_query_parent_ad_custom_offset_length():
    """自定义 offset/length 透传。"""
    client = _make_client({"code": 0, "data": []})
    query_parent_ad(
        client,
        sid=109,
        report_date="2026-01-01",
        offset=20,
        length=50,
    )
    call_params = client.request.call_args.kwargs["params"]
    assert call_params["offset"] == 20
    assert call_params["length"] == 50


def test_query_parent_ad_non_zero_code_returns_empty():
    """code != 0 时返回空列表，不抛异常。"""
    client = _make_client({"code": 10001, "message": "invalid token", "data": []})
    out = query_parent_ad(client, sid=109, report_date="2026-01-01")
    assert out == []


def test_query_parent_ad_missing_data_field_returns_empty():
    """响应缺少 data 字段时安全返回空列表。"""
    client = _make_client({"code": 0, "message": "操作成功"})
    out = query_parent_ad(client, sid=109, report_date="2026-01-01")
    assert out == []
