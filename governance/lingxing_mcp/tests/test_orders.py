from unittest.mock import MagicMock

from governance_lingxing_mcp.tools.orders import API_PATH, query_orders


def _make_client(result: dict) -> MagicMock:
    client = MagicMock()
    client.request.return_value = result
    return client


def test_basic_returns_total_and_data():
    rows = [{"amazon_order_id": "111-222", "order_status": "Shipped"}]
    client = _make_client({"code": 0, "total": 1, "data": rows})

    out = query_orders(client, sid=1, start_date="2026-07-01", end_date="2026-07-30")

    assert out == {"total": 1, "data": rows}
    client.request.assert_called_once_with(
        "POST", API_PATH,
        params={"sid": 1, "start_date": "2026-07-01", "end_date": "2026-07-30",
                "offset": 0, "length": 100},
        ttl_seconds=21600,
    )


def test_filters_passthrough():
    client = _make_client({"code": 0, "data": []})
    query_orders(
        client, sid=1, start_date="2026-07-01", end_date="2026-07-30",
        date_type=1, order_status="Shipped", fulfillment_channel=1,
    )
    call_params = client.request.call_args.kwargs["params"]
    assert call_params["date_type"] == 1
    assert call_params["order_status"] == "Shipped"
    assert call_params["fulfillment_channel"] == 1


def test_envelope_data_extracts():
    client = _make_client({"code": 0, "data": {"total": 5, "list": [{"id": 1}]}})
    out = query_orders(client, sid=1, start_date="2026-07-01", end_date="2026-07-02")
    assert out == {"total": 5, "data": [{"id": 1}]}


def test_non_zero_code_returns_error_envelope():
    client = _make_client({"code": 400, "message": "date span too large"})
    out = query_orders(client, sid=1, start_date="2025-01-01", end_date="2026-07-30")
    assert out["error"] == "date span too large"
    assert out["data"] == []
