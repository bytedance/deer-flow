from unittest.mock import MagicMock

from governance_lingxing_mcp.tools.keyword_share import (
    API_PATH,
    query_keyword_share,
)


def _make_client(result: dict) -> MagicMock:
    client = MagicMock()
    client.request.return_value = result
    return client


def test_query_keyword_share_basic_returns_data():
    """sid + report_date 默认 target_type=keyword，返回 data 列表，TTL=21600。"""
    data = [{"query": "iphone13 pro", "target_id": 257012918513585, "clicks": 3}]
    client = _make_client({"code": 0, "message": "操作成功", "data": data})

    out = query_keyword_share(client, sid=109, report_date="2026-01-01")

    assert out == data
    client.request.assert_called_once_with(
        "POST",
        API_PATH,
        params={
            "sid": 109,
            "report_date": "2026-01-01",
            "target_type": "keyword",
            "show_detail": 0,
            "offset": 0,
            "length": 100,
        },
        ttl_seconds=21600,
    )


def test_query_keyword_share_with_profile_id_and_target_type():
    """profile_id 与 target_type 透传到 params。"""
    client = _make_client({"code": 0, "data": []})

    query_keyword_share(
        client,
        sid=109,
        report_date="2026-01-01",
        profile_id=123456,
        target_type="target",
    )

    call_params = client.request.call_args.kwargs["params"]
    assert call_params["profile_id"] == 123456
    assert call_params["target_type"] == "target"
    assert client.request.call_args.kwargs["ttl_seconds"] == 21600


def test_query_keyword_share_custom_offset_length():
    """自定义 offset/length 透传。"""
    client = _make_client({"code": 0, "data": []})
    query_keyword_share(
        client,
        sid=109,
        report_date="2026-01-01",
        offset=10,
        length=30,
    )
    call_params = client.request.call_args.kwargs["params"]
    assert call_params["offset"] == 10
    assert call_params["length"] == 30


def test_query_keyword_share_non_zero_code_returns_empty():
    """code != 0 时返回空列表。"""
    client = _make_client({"code": 10001, "message": "invalid token", "data": []})
    out = query_keyword_share(client, sid=109, report_date="2026-01-01")
    assert out == []


def test_query_keyword_share_missing_data_field_returns_empty():
    """响应缺少 data 字段时安全返回空列表。"""
    client = _make_client({"code": 0, "message": "操作成功"})
    out = query_keyword_share(client, sid=109, report_date="2026-01-01")
    assert out == []
