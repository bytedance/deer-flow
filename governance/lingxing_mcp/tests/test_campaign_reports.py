from unittest.mock import MagicMock, patch

from governance_lingxing_mcp.tools.campaign_reports import (
    API_PATH,
    query_campaign_reports,
)


def _make_client() -> MagicMock:
    return MagicMock()


def test_date_range_delegates_to_daily_aggregate():
    """日期范围入参走按天循环聚合，sid/show_detail/分页参数透传。"""
    client = _make_client()
    with patch(
        "governance_lingxing_mcp.tools.campaign_reports.fetch_daily_reports",
        return_value=[{"campaign_id": 1, "acos": 0.2}],
    ) as mock_fetch:
        out = query_campaign_reports(
            client, sid=1, start_date="2026-07-01", end_date="2026-07-30"
        )
    assert out == [{"campaign_id": 1, "acos": 0.2}]
    mock_fetch.assert_called_once_with(
        client,
        API_PATH,
        {"sid": 1, "show_detail": 0, "offset": 0, "length": 100},
        "2026-07-01",
        "2026-07-30",
        key_fields=("campaign_id",),
        ttl_seconds=1800,
    )


def test_campaign_id_filter_applied():
    """campaign_id 过滤在聚合后服务端侧应用。"""
    client = _make_client()
    rows = [{"campaign_id": 1}, {"campaign_id": 2}]
    with patch(
        "governance_lingxing_mcp.tools.campaign_reports.fetch_daily_reports",
        return_value=rows,
    ):
        out = query_campaign_reports(
            client, sid=1, start_date="2026-07-01", end_date="2026-07-02", campaign_id=2
        )
    assert out == [{"campaign_id": 2}]


def test_campaign_id_filter_skipped_on_error():
    """聚合出错时不再过滤，直接透传错误。"""
    client = _make_client()
    err = [{"error": "all 2 daily requests failed"}]
    with patch(
        "governance_lingxing_mcp.tools.campaign_reports.fetch_daily_reports",
        return_value=err,
    ):
        out = query_campaign_reports(
            client, sid=1, start_date="2026-07-01", end_date="2026-07-02", campaign_id=2
        )
    assert out == err
