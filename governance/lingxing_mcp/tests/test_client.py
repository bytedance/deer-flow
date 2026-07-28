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
