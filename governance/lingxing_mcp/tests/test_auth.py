from unittest.mock import MagicMock, patch

from governance_lingxing_mcp.auth import LingXingAuth
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


@patch("governance_lingxing_mcp.auth.httpx.post")
def test_get_token_success(mock_post):
    mock_post.return_value.json.return_value = {
        "code": "200",
        "msg": "OK",
        "data": {
            "access_token": "tok-123",
            "refresh_token": "ref-456",
            "expires_in": 7199,
        },
    }
    auth = LingXingAuth(_make_config())
    token = auth.get_access_token()
    assert token == "tok-123"


@patch("governance_lingxing_mcp.auth.httpx.post")
def test_get_token_cached_no_duplicate_call(mock_post):
    mock_post.return_value.json.return_value = {
        "code": "200",
        "data": {"access_token": "tok", "refresh_token": "ref", "expires_in": 7199},
    }
    auth = LingXingAuth(_make_config())
    auth.get_access_token()
    auth.get_access_token()
    assert mock_post.call_count == 1  # 第二次走缓存


@patch("governance_lingxing_mcp.auth.httpx.post")
def test_token_refresh_when_expired(mock_post):
    # 第一次：获取 token，已过期
    mock_post.return_value.json.return_value = {
        "code": "200",
        "data": {"access_token": "old", "refresh_token": "ref", "expires_in": 0},
    }
    auth = LingXingAuth(_make_config())
    auth.get_access_token()  # 首次获取 → "old"（expires_in=0，即刻过期）
    # 第二次：应触发 refresh
    mock_post.return_value.json.return_value = {
        "code": "200",
        "data": {"access_token": "new", "refresh_token": "ref2", "expires_in": 7199},
    }
    token = auth.get_access_token()  # 已过期 → refresh → "new"
    assert token == "new"
    assert mock_post.call_count >= 2
