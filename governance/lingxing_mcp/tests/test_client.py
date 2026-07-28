from unittest.mock import MagicMock, patch

from governance_lingxing_mcp.client import LingXingClient
from governance_lingxing_mcp.config import LXConfig


def _make_config():
    return LXConfig(
        app_id="ak_test",
        app_secret="secret",
        api_base="https://openapi.lingxing.com",
        host="0.0.0.0",
        port=8102,
        token_cache_path=MagicMock(),
        ttl_business_seconds=21600,
        ttl_ad_seconds=1800,
        ttl_inventory_seconds=3600,
    )


@patch("governance_lingxing_mcp.client.httpx.get")
def test_request_get_with_signing(mock_get):
    """GET 请求带签名参数。"""
    mock_get.return_value.json.return_value = {"code": 0, "data": [{"sid": 1}]}
    mock_auth = MagicMock()
    mock_auth.get_access_token.return_value = "tok-123"
    client = LingXingClient(_make_config(), auth=mock_auth)
    result = client.request(
        "GET", "/erp/sc/data/seller/lists", params={}, ttl_seconds=60
    )
    assert result["code"] == 0
    # 验证 httpx.get 被调用时带了 sign 参数
    call_kwargs = mock_get.call_args
    assert "sign" in call_kwargs.kwargs.get("params", {}) or "sign" in (
        call_kwargs.args[1] if len(call_kwargs.args) > 1 else {}
    )


@patch("governance_lingxing_mcp.client.httpx.get")
def test_request_caches_within_ttl(mock_get):
    """TTL 内重复请求走缓存。"""
    mock_get.return_value.json.return_value = {"code": 0, "data": []}
    mock_auth = MagicMock()
    mock_auth.get_access_token.return_value = "tok"
    client = LingXingClient(_make_config(), auth=mock_auth)
    client.request("GET", "/test", params={}, ttl_seconds=60)
    client.request("GET", "/test", params={}, ttl_seconds=60)
    assert mock_get.call_count == 1  # 第二次走缓存


@patch("governance_lingxing_mcp.client.httpx.get")
def test_request_no_cache_when_ttl_zero(mock_get):
    """TTL=0 不缓存（评论用）。"""
    mock_get.return_value.json.return_value = {"code": 0, "data": []}
    mock_auth = MagicMock()
    mock_auth.get_access_token.return_value = "tok"
    client = LingXingClient(_make_config(), auth=mock_auth)
    client.request("GET", "/review", params={}, ttl_seconds=0)
    client.request("GET", "/review", params={}, ttl_seconds=0)
    assert mock_get.call_count == 2


@patch("governance_lingxing_mcp.client.httpx.post")
def test_request_post_uses_query_params(mock_post):
    """POST 请求把签名参数放在 query params（领星 OpenAPI 要求），而非 data body。"""
    mock_post.return_value.json.return_value = {"code": 0, "data": []}
    mock_auth = MagicMock()
    mock_auth.get_access_token.return_value = "tok"
    client = LingXingClient(_make_config(), auth=mock_auth)
    client.request("POST", "/bd/test", params={"sid": 1}, ttl_seconds=0)
    call_kwargs = mock_post.call_args
    params = call_kwargs.kwargs.get("params", {})
    assert "sign" in params
    assert "access_token" in params
    assert "app_key" in params
    assert "timestamp" in params
    # data body should not be used for non-/pb/ POST
    assert "json" not in call_kwargs.kwargs
    assert "data" not in call_kwargs.kwargs


@patch("governance_lingxing_mcp.client.httpx.post")
def test_request_post_pb_uses_json_body(mock_post):
    """/pb/ 广告 API 的业务参数走 JSON body，鉴权参数走 query params。"""
    mock_post.return_value.json.return_value = {"code": 0, "data": []}
    mock_auth = MagicMock()
    mock_auth.get_access_token.return_value = "tok"
    client = LingXingClient(_make_config(), auth=mock_auth)
    client.request(
        "POST", "/pb/openapi/newad/spCampaignReports",
        params={"sid": 1, "report_date": "2026-07-27"}, ttl_seconds=0,
    )
    call_kwargs = mock_post.call_args
    query_params = call_kwargs.kwargs.get("params", {})
    body = call_kwargs.kwargs.get("json", {})
    # 鉴权参数在 query
    assert "sign" in query_params
    assert "access_token" in query_params
    # 业务参数在 body
    assert "sid" in body
    assert "report_date" in body
    # 鉴权参数不在 body
    assert "sign" not in body


@patch("governance_lingxing_mcp.client.httpx.post")
def test_request_post_list_params_json_serialized(mock_post):
    """list 值（如 sid=[1,2]）JSON 序列化后送签，避免签验不一致。"""
    mock_post.return_value.json.return_value = {"code": 0, "data": []}
    mock_auth = MagicMock()
    mock_auth.get_access_token.return_value = "tok"
    client = LingXingClient(_make_config(), auth=mock_auth)
    client.request(
        "POST", "/bd/test", params={"sid": [1, 2]}, ttl_seconds=0,
    )
    call_kwargs = mock_post.call_args
    params = call_kwargs.kwargs.get("params", {})
    # sid 应被序列化为 JSON 字符串
    assert params["sid"] == "[1, 2]"


def test_cache_key_with_list_values():
    """cache_key 应能处理 list 参数值（原 bug: unhashable type: 'list'）。"""
    mock_auth = MagicMock()
    client = LingXingClient(_make_config(), auth=mock_auth)
    # 不应抛 TypeError
    key = client._cache_key("POST", "/test", {"sid": [1, 2], "start_date": "2026-07-20"})
    assert isinstance(key, tuple)
    # 相同参数应生成相同 key
    key2 = client._cache_key("POST", "/test", {"start_date": "2026-07-20", "sid": [1, 2]})
    assert key == key2
