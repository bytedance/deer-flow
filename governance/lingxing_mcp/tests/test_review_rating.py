from unittest.mock import MagicMock

from governance_lingxing_mcp.tools.review_rating import (
    API_PATH,
    query_review_rating,
)


def _make_client(result: dict) -> MagicMock:
    client = MagicMock()
    client.request.return_value = result
    return client


def test_query_review_rating_basic_returns_data():
    """date_field + 日期范围默认调用，返回 data 列表，TTL=0（不缓存）。"""
    data = [{"review_id": "R1KKLEHWNZWH05", "asin": "B07XKHF683", "last_star": 5}]
    client = _make_client({"code": 0, "message": "success", "data": data})

    out = query_review_rating(
        client,
        date_field="review_time",
        start_date="2026-01-01",
        end_date="2026-01-31",
    )

    assert out == data
    client.request.assert_called_once_with(
        "POST",
        API_PATH,
        params={
            "date_field": "review_time",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "sort_field": "review_date",
            "sort_type": "desc",
            "offset": 0,
            "length": 20,
        },
        ttl_seconds=0,
    )


def test_query_review_rating_with_sids_and_search():
    """sids/search_field/search_value 透传到 params。"""
    client = _make_client({"code": 0, "data": []})

    query_review_rating(
        client,
        date_field="review_time",
        start_date="2026-01-01",
        end_date="2026-01-31",
        sids="1,2",
        search_field="asin",
        search_value="B07XKHF683",
    )

    call_params = client.request.call_args.kwargs["params"]
    assert call_params["sids"] == "1,2"
    assert call_params["search_field"] == "asin"
    assert call_params["search_value"] == "B07XKHF683"
    assert client.request.call_args.kwargs["ttl_seconds"] == 0


def test_query_review_rating_with_status_and_star():
    """status/star 透传到 params。"""
    client = _make_client({"code": 0, "data": []})
    query_review_rating(
        client,
        date_field="review_time",
        start_date="2026-01-01",
        end_date="2026-01-31",
        status="0,1",
        star="1,2,3",
    )
    call_params = client.request.call_args.kwargs["params"]
    assert call_params["status"] == "0,1"
    assert call_params["star"] == "1,2,3"


def test_query_review_rating_custom_offset_length():
    """自定义 offset/length 透传。"""
    client = _make_client({"code": 0, "data": []})
    query_review_rating(
        client,
        date_field="review_time",
        start_date="2026-01-01",
        end_date="2026-01-31",
        offset=40,
        length=200,
    )
    call_params = client.request.call_args.kwargs["params"]
    assert call_params["offset"] == 40
    assert call_params["length"] == 200


def test_query_review_rating_non_zero_code_returns_empty():
    """code != 0 时返回空列表。"""
    client = _make_client({"code": 10001, "message": "invalid token", "data": []})
    out = query_review_rating(
        client,
        date_field="review_time",
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    assert out == []


def test_query_review_rating_missing_data_field_returns_empty():
    """响应缺少 data 字段时安全返回空列表。"""
    client = _make_client({"code": 0, "message": "success"})
    out = query_review_rating(
        client,
        date_field="review_time",
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    assert out == []
