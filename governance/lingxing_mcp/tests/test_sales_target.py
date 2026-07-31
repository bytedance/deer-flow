from unittest.mock import MagicMock

from governance_lingxing_mcp.tools.sales_target import API_PATH, query_sales_target


def _make_client(result: dict) -> MagicMock:
    client = MagicMock()
    client.request.return_value = result
    return client


def test_success_code_1_returns_data():
    """目标管理接口成功码为 code=1（非常规0），需特殊适配。"""
    data = [{"sid": 1, "goalName": "2026目标", "totalCompleteRate": 0.83}]
    client = _make_client({"code": 1, "message": "success", "data": data})

    out = query_sales_target(client, "2026")

    assert out == data
    client.request.assert_called_once_with(
        "POST", API_PATH, params={"assessYear": "2026"}, ttl_seconds=21600
    )


def test_success_code_0_also_accepted():
    data = [{"sid": 1}]
    client = _make_client({"code": 0, "data": data})
    assert query_sales_target(client, "2026") == data


def test_other_code_returns_error():
    client = _make_client({"code": 400, "message": "bad year"})
    out = query_sales_target(client, "20xx")
    assert out and "error" in out[0]


def test_null_data_returns_empty():
    client = _make_client({"code": 1, "data": None})
    assert query_sales_target(client, "2026") == []
