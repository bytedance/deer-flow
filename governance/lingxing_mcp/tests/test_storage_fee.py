from unittest.mock import MagicMock

from governance_lingxing_mcp.tools.storage_fee import (
    LONG_TERM_API_PATH,
    MONTHLY_API_PATH,
    query_storage_fee,
)


def _make_client(result: dict) -> MagicMock:
    client = MagicMock()
    client.request.return_value = result
    return client


def test_monthly_fee_uses_month_param():
    data = [{"asin": "B1", "estimated_monthly_storage_fee": 3.2}]
    client = _make_client({"code": 0, "data": data})

    out = query_storage_fee(client, sid=1, fee_type="monthly", month="2026-07")

    assert out == data
    client.request.assert_called_once_with(
        "POST", MONTHLY_API_PATH,
        params={"sid": 1, "month": "2026-07", "offset": 0, "length": 1000},
        ttl_seconds=21600,
    )


def test_monthly_fee_requires_month():
    client = _make_client({"code": 0, "data": []})
    out = query_storage_fee(client, sid=1, fee_type="monthly")
    assert "error" in out[0]
    client.request.assert_not_called()


def test_long_term_fee_uses_date_range():
    data = [{"asin": "B1", "12_mo_long_terms_storage_fee": 9.9}]
    client = _make_client({"code": 0, "data": data})

    out = query_storage_fee(
        client, sid=1, fee_type="long_term",
        start_date="2026-01-01", end_date="2026-07-01",
    )

    assert out == data
    client.request.assert_called_once_with(
        "POST", LONG_TERM_API_PATH,
        params={"sid": 1, "start_date": "2026-01-01", "end_date": "2026-07-01",
                "offset": 0, "length": 1000},
        ttl_seconds=21600,
    )


def test_long_term_fee_requires_dates():
    client = _make_client({"code": 0, "data": []})
    out = query_storage_fee(client, sid=1, fee_type="long_term", start_date="2026-01-01")
    assert "error" in out[0]
    client.request.assert_not_called()


def test_invalid_fee_type_rejected():
    client = _make_client({"code": 0, "data": []})
    out = query_storage_fee(client, sid=1, fee_type="weekly")
    assert "error" in out[0]
    client.request.assert_not_called()
