from unittest.mock import MagicMock

from governance_lingxing_mcp.tools.return_analysis import (
    API_PATH,
    query_return_analysis,
)


def _make_client(result: dict) -> MagicMock:
    client = MagicMock()
    client.request.return_value = result
    return client


def test_records_structure_extracted():
    """响应 data.records 结构被正确提取。"""
    records = [{"asin": "B1", "curReturnGoodsVolumeRatio": "5.2%"}]
    client = _make_client({"code": 0, "data": {"records": records, "total": 1}})

    out = query_return_analysis(
        client, start_date="2026-07-01", end_date="2026-07-30",
        asin_type="asin", date_type=0,
    )

    assert out == records
    client.request.assert_called_once_with(
        "POST", API_PATH,
        params={"startDate": "2026-07-01", "endDate": "2026-07-30",
                "asinType": "asin", "dateType": 0, "offset": 0, "length": 100},
        ttl_seconds=21600,
    )


def test_optional_params_passthrough():
    client = _make_client({"code": 0, "data": {"records": []}})
    query_return_analysis(
        client, start_date="2026-07-01", end_date="2026-07-30",
        asin_type="parentAsin", date_type=1, store_id=[1, 2], mids=[1],
        search_field="asin", search_value=["B1"], sort_field="curVolume",
    )
    call_params = client.request.call_args.kwargs["params"]
    assert call_params["storeId"] == [1, 2]
    assert call_params["mids"] == [1]
    assert call_params["searchField"] == "asin"
    assert call_params["searchValue"] == ["B1"]
    assert call_params["sortField"] == "curVolume"


def test_non_zero_code_returns_error():
    client = _make_client({"code": 400, "message": "bad asinType"})
    out = query_return_analysis(
        client, start_date="2026-07-01", end_date="2026-07-30",
        asin_type="bad", date_type=0,
    )
    assert out and "error" in out[0]
