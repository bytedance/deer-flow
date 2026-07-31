from unittest.mock import MagicMock, patch

from governance_lingxing_mcp.tools.search_term_reports import (
    API_PATH as SEARCH_TERM_API_PATH,
)
from governance_lingxing_mcp.tools.search_term_reports import (
    query_search_term_reports,
)
from governance_lingxing_mcp.tools.sp_keyword_reports import (
    API_PATH as SP_KEYWORD_API_PATH,
)
from governance_lingxing_mcp.tools.sp_keyword_reports import (
    query_sp_keyword_reports,
)


def test_search_term_reports_delegates_with_target_type():
    """搜索词报表透传 target_type，按 (query,campaign,ad_group,keyword) 聚合，TTL=21600。"""
    client = MagicMock()
    with patch(
        "governance_lingxing_mcp.tools.search_term_reports.fetch_daily_reports",
        return_value=[{"query": "yoga mat", "clicks": 10}],
    ) as mock_fetch:
        out = query_search_term_reports(
            client, sid=1, target_type="keyword",
            start_date="2026-07-01", end_date="2026-07-30",
        )
    assert out == [{"query": "yoga mat", "clicks": 10}]
    mock_fetch.assert_called_once_with(
        client,
        SEARCH_TERM_API_PATH,
        {"sid": 1, "target_type": "keyword", "show_detail": 0, "offset": 0, "length": 100},
        "2026-07-01",
        "2026-07-30",
        key_fields=("query", "campaign_id", "ad_group_id", "keyword_id"),
        ttl_seconds=21600,
    )


def test_sp_keyword_reports_delegates():
    """SP关键词报表按 keyword_id 聚合，TTL=1800。"""
    client = MagicMock()
    with patch(
        "governance_lingxing_mcp.tools.sp_keyword_reports.fetch_daily_reports",
        return_value=[{"keyword_id": 9, "keyword_text": "mat"}],
    ) as mock_fetch:
        out = query_sp_keyword_reports(
            client, sid=2, start_date="2026-07-01", end_date="2026-07-02"
        )
    assert out == [{"keyword_id": 9, "keyword_text": "mat"}]
    mock_fetch.assert_called_once_with(
        client,
        SP_KEYWORD_API_PATH,
        {"sid": 2, "show_detail": 0, "offset": 0, "length": 100},
        "2026-07-01",
        "2026-07-02",
        key_fields=("keyword_id",),
        ttl_seconds=1800,
    )
