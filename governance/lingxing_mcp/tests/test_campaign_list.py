from unittest.mock import MagicMock

from governance_lingxing_mcp.tools.campaign_list import API_PATH, query_campaign_list


def _make_client(result: dict) -> MagicMock:
    client = MagicMock()
    client.request.return_value = result
    return client


def test_basic_returns_campaign_list_with_budget():
    """返回活动列表含 daily_budget，TTL=3600。"""
    data = [{"campaign_id": 11, "name": "SP-Auto", "daily_budget": 50.0, "state": "enabled"}]
    client = _make_client({"code": 0, "data": data})

    out = query_campaign_list(client, sid=1, state="enabled")

    assert out == data
    client.request.assert_called_once_with(
        "POST", API_PATH,
        params={"sid": 1, "offset": 0, "length": 15, "state": "enabled"},
        ttl_seconds=3600,
    )


def test_optional_params_omitted():
    client = _make_client({"code": 0, "data": []})
    query_campaign_list(client, sid=1)
    call_params = client.request.call_args.kwargs["params"]
    assert "state" not in call_params
    assert "next_token" not in call_params


def test_envelope_data_extracts_list():
    """data 为信封结构时提取 list。"""
    client = _make_client({"code": 0, "data": {"total": 1, "list": [{"campaign_id": 1}]}})
    out = query_campaign_list(client, sid=1)
    assert out == [{"campaign_id": 1}]


def test_non_zero_code_returns_error():
    client = _make_client({"code": 401, "message": "unauthorized"})
    out = query_campaign_list(client, sid=1)
    assert out and "error" in out[0]
