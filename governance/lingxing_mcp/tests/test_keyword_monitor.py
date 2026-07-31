from unittest.mock import MagicMock

from governance_lingxing_mcp.tools.keyword_monitor import (
    API_PATH,
    add_keyword_monitor,
)


def _make_client(result: dict) -> MagicMock:
    client = MagicMock()
    client.request.return_value = result
    return client


def test_add_monitor_success():
    """添加成功返回 success=True；写操作 TTL=0 不缓存。"""
    client = _make_client({"code": 0, "message": "success"})

    out = add_keyword_monitor(
        client, mid=1, keywords=["yoga mat"], asins=["B0XXXX"],
        types=[1, 2], is_sponsors=[0, 1],
    )

    assert out["success"] is True
    client.request.assert_called_once_with(
        "POST", API_PATH,
        params={"mid": 1, "keywords": ["yoga mat"], "asins": ["B0XXXX"],
                "types": [1, 2], "is_sponsors": [0, 1]},
        ttl_seconds=0,
    )


def test_add_monitor_with_postcodes():
    client = _make_client({"code": 0, "message": "ok"})
    add_keyword_monitor(
        client, mid=1, keywords=["a"], asins=["B"],
        types=[1], is_sponsors=[1], postcodes=["10001"],
    )
    assert client.request.call_args.kwargs["params"]["postcodes"] == ["10001"]


def test_add_monitor_failure_returns_success_false():
    """失败时返回 success=False + message，Agent 可降级提示用户网页端手动添加。"""
    client = _make_client({"code": 500, "message": "endpoint deprecated"})
    out = add_keyword_monitor(
        client, mid=1, keywords=["a"], asins=["B"], types=[1], is_sponsors=[0],
    )
    assert out["success"] is False
    assert out["message"] == "endpoint deprecated"
