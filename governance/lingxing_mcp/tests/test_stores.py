from unittest.mock import MagicMock

from governance_lingxing_mcp.tools.stores import (
    ALL_MARKETPLACE_API_PATH,
    SELLER_LISTS_API_PATH,
    query_marketplaces,
    query_stores,
)


def _make_client(result: dict) -> MagicMock:
    client = MagicMock()
    client.request.return_value = result
    return client


def test_query_stores_returns_seller_list():
    """返回店铺列表（含 sid/mid），GET 请求，TTL=86400（24小时）。"""
    data = [{"sid": 12345, "mid": 1, "name": "US Store", "country": "US"}]
    client = _make_client({"code": 0, "data": data})

    out = query_stores(client)

    assert out == data
    client.request.assert_called_once_with(
        "GET", SELLER_LISTS_API_PATH, params={}, ttl_seconds=86400
    )


def test_query_stores_non_zero_code_returns_error():
    """鉴权失败等场景返回 error 列表，Agent 可感知闭环失败原因。"""
    client = _make_client({"code": 10001, "message": "invalid token"})
    out = query_stores(client)
    assert out and "error" in out[0]


def test_query_stores_null_data_returns_empty():
    client = _make_client({"code": 0, "data": None})
    assert query_stores(client) == []


def test_query_marketplaces_returns_list():
    """返回市场列表，GET 请求，TTL=604800（7天）。"""
    data = [{"mid": 1, "name": "美国", "country": "US", "currency_code": "USD"}]
    client = _make_client({"code": 0, "data": data})

    out = query_marketplaces(client)

    assert out == data
    client.request.assert_called_once_with(
        "GET", ALL_MARKETPLACE_API_PATH, params={}, ttl_seconds=604800
    )


def test_query_marketplaces_non_zero_code_returns_error():
    client = _make_client({"code": -1, "message": "network error"})
    out = query_marketplaces(client)
    assert out and "error" in out[0]
