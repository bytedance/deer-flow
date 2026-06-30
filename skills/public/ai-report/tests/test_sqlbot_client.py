"""Unit tests for sqlbot_client (新写, 借鉴 chatbi-report sqlbot_client.py 接口)."""

from __future__ import annotations

import pytest

from sqlbot_client import MockSQLBotClient, SQLBotError


def test_mock_client_returns_success():
    c = MockSQLBotClient(fixture_path="tests/fixtures/mock_sqlbot/wangyi_2026_03.json")
    resp = c.query_report_info(
        org_info=[{"org_ecd": "wangyi_credit_union"}],
        index_info=[{"idx_id": "BAS_001"}],
        time_info=["202603"],
    )
    assert resp.code == 0
    assert resp.data[0]["success"] is True
    assert resp.data[0]["data"][0]["value"] == 1234567890.50


def test_mock_client_missing_idx_returns_empty():
    c = MockSQLBotClient(fixture_path="tests/fixtures/mock_sqlbot/wangyi_2026_03.json")
    resp = c.query_report_info(
        org_info=[],
        index_info=[{"idx_id": "MISSING_IDX"}],
        time_info=["202603"],
    )
    elem = resp.data[0]
    assert elem["success"] is False
    assert elem["data"] == []


def test_mock_client_rejects_empty_index_info():
    c = MockSQLBotClient(fixture_path="tests/fixtures/mock_sqlbot/wangyi_2026_03.json")
    with pytest.raises(SQLBotError, match="index_info must contain"):
        c.query_report_info(org_info=[], index_info=[], time_info=[])