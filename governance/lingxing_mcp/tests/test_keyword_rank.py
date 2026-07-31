from unittest.mock import MagicMock

from governance_lingxing_mcp.tools.keyword_rank import (
    API_PATH,
    query_keyword_rank,
)


def _make_client(result: dict) -> MagicMock:
    client = MagicMock()
    client.request.return_value = result
    return client


def test_query_keyword_rank_basic_returns_data():
    """默认 offset/length 调用，返回 data 列表，TTL=21600。"""
    data = [{"id": 386, "key_word": "blender", "rank": 10, "current_page_rank": 1}]
    client = _make_client({"code": 0, "message": "success", "data": data})

    out = query_keyword_rank(client)

    assert out == data
    client.request.assert_called_once_with(
        "POST",
        API_PATH,
        params={"offset": 0, "length": 20},
        ttl_seconds=21600,
    )


def test_query_keyword_rank_with_mid_and_dates():
    """mid/start_date/end_date 透传到 params。"""
    data = [{"key_word": "blender", "rank": 10}]
    client = _make_client({"code": 0, "data": data})

    query_keyword_rank(
        client,
        offset=5,
        length=50,
        mid=1,
        start_date="2026-01-01",
        end_date="2026-01-31",
    )

    call_params = client.request.call_args.kwargs["params"]
    assert call_params["mid"] == 1
    assert call_params["start_date"] == "2026-01-01"
    assert call_params["end_date"] == "2026-01-31"
    assert call_params["offset"] == 5
    assert call_params["length"] == 50
    assert client.request.call_args.kwargs["ttl_seconds"] == 21600


def test_query_keyword_rank_with_search_params():
    """search_field/search_value 透传到 params（按关键词/ASIN 搜索）。"""
    data = [{"key_word": "yoga mat", "rank": 8, "is_sponsored": 0}]
    client = _make_client({"code": 0, "data": data})

    out = query_keyword_rank(
        client, search_field="key_word", search_value="yoga mat"
    )

    assert out == data
    call_params = client.request.call_args.kwargs["params"]
    assert call_params["search_field"] == "key_word"
    assert call_params["search_value"] == "yoga mat"


def test_query_keyword_rank_non_zero_code_returns_error():
    """code != 0（端点失效/鉴权失败）时返回 error 列表，不抛异常。"""
    client = _make_client({"code": 10001, "message": "invalid token", "data": []})
    out = query_keyword_rank(client)
    assert isinstance(out, list)
    assert out and "error" in out[0]


def test_query_keyword_rank_empty_data_returns_not_monitored_hint():
    """data 为空（关键词未监控）时返回闭环提示，引导 lx_add_keyword_monitor。"""
    client = _make_client({"code": 0, "message": "success", "data": []})
    out = query_keyword_rank(client)
    assert isinstance(out, list)
    assert out and out[0].get("info") == "keyword not monitored or no rank data"
    assert "lx_add_keyword_monitor" in out[0].get("hint", "")


def test_query_keyword_rank_missing_data_field_returns_hint():
    """code == 0 但无 data 字段时同样按未监控处理。"""
    client = _make_client({"code": 0, "message": "success"})
    out = query_keyword_rank(client)
    assert out and "hint" in out[0]
