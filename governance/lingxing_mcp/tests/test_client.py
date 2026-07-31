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
def test_request_post_uses_json_body_with_auth_in_query(mock_post):
    """POST 统一：业务参数走 JSON body，鉴权参数走 query params（2026-07-30 全端点探测确认）。"""
    mock_post.return_value.json.return_value = {"code": 0, "data": []}
    mock_auth = MagicMock()
    mock_auth.get_access_token.return_value = "tok"
    client = LingXingClient(_make_config(), auth=mock_auth)
    client.request("POST", "/bd/test", params={"sid": 1}, ttl_seconds=0)
    call_kwargs = mock_post.call_args
    query_params = call_kwargs.kwargs.get("params", {})
    body = call_kwargs.kwargs.get("json", {})
    # 鉴权参数在 query
    assert "sign" in query_params
    assert "access_token" in query_params
    assert "app_key" in query_params
    assert "timestamp" in query_params
    # 业务参数在 body，鉴权参数不在 body
    assert body == {"sid": 1}
    assert "sign" not in body


@patch("governance_lingxing_mcp.client.httpx.post")
def test_request_post_pb_uses_json_body(mock_post):
    """/pb/ 广告 API 同样业务参数走 JSON body，鉴权参数走 query params。"""
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
def test_sign_serializes_list_params_with_compact_json(mock_post):
    """签名串中 list/dict 参数用紧凑 JSON（无空格），否则领星多元素数组签验失败
    （回归：json.dumps 默认分隔符产生 "[8074, 8075]" → api sign not correct）。"""
    mock_post.return_value.json.return_value = {"code": 0, "data": []}
    mock_auth = MagicMock()
    mock_auth.get_access_token.return_value = "tok"
    client = LingXingClient(_make_config(), auth=mock_auth)
    with patch("governance_lingxing_mcp.client.sign_request", return_value="SIGN") as mock_sign:
        client.request("POST", "/bd/test", params={"sid": [8074, 8075]}, ttl_seconds=0)
    sign_params = mock_sign.call_args.args[0]
    assert sign_params["sid"] == "[8074,8075]"


@patch("governance_lingxing_mcp.client.httpx.post")
def test_request_post_list_params_keep_raw_type_in_body(mock_post):
    """list 值（如 sid=[1,2]）在 body 中保持原始类型；签名侧才 JSON 序列化。"""
    mock_post.return_value.json.return_value = {"code": 0, "data": []}
    mock_auth = MagicMock()
    mock_auth.get_access_token.return_value = "tok"
    client = LingXingClient(_make_config(), auth=mock_auth)
    client.request(
        "POST", "/bd/test", params={"sid": [1, 2]}, ttl_seconds=0,
    )
    call_kwargs = mock_post.call_args
    body = call_kwargs.kwargs.get("json", {})
    assert body["sid"] == [1, 2]


@patch("governance_lingxing_mcp.client.time.sleep")
@patch("governance_lingxing_mcp.client.httpx.get")
def test_request_retries_on_429_with_backoff(mock_get, mock_sleep):
    """429 限流时指数退避重试（0.5s/1s），第三次成功则返回结果。"""
    resp_429 = MagicMock(status_code=429)
    resp_ok = MagicMock(status_code=200)
    resp_ok.json.return_value = {"code": 0, "data": [{"sid": 1}]}
    mock_get.side_effect = [resp_429, resp_429, resp_ok]
    mock_auth = MagicMock()
    mock_auth.get_access_token.return_value = "tok"
    client = LingXingClient(_make_config(), auth=mock_auth)

    result = client.request("GET", "/test", params={}, ttl_seconds=0)

    assert result["code"] == 0
    assert mock_get.call_count == 3
    # 指数退避：0.5s, 1s
    assert [c.args[0] for c in mock_sleep.call_args_list] == [0.5, 1.0]


@patch("governance_lingxing_mcp.client.time.sleep")
@patch("governance_lingxing_mcp.client.httpx.get")
def test_request_gives_up_after_3_retries_on_429(mock_get, mock_sleep):
    """连续 429 超过 3 次后返回限流错误，不再重试。"""
    mock_get.return_value = MagicMock(status_code=429)
    mock_auth = MagicMock()
    mock_auth.get_access_token.return_value = "tok"
    client = LingXingClient(_make_config(), auth=mock_auth)

    result = client.request("GET", "/test", params={}, ttl_seconds=0)

    assert result["code"] == 429
    assert mock_get.call_count == 3


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
