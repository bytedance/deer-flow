"""Unit tests for sqlbot_client (新写, 借鉴 chatbi-report sqlbot_client.py 接口)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from sqlbot_client import (
    MockSQLBotClient,
    OrgContext,
    QueryReportInfoResponse,
    SQLBotError,
    _rows_from_response,
    _unique_indicator_periods,
    query_from_parsed,
)


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


# --- chatbi-report-style helpers (org_ecd / org_name shape) --- #


def test_org_context_shape_matches_parse_md():
    """ai-report MD 用 org_ecd / org_name, sqlbot_client.OrgContext 必须一致."""
    org = OrgContext(org_ecd="wangyi_credit_union", org_name="王益联社")
    assert org.org_ecd == "wangyi_credit_union"
    assert org.org_name == "王益联社"


def test_rows_from_response_keeps_allowed_orgs():
    """非 org_contexts 里的 org_ecd 被过滤, 缺失 org 降级 success=False."""
    resp = QueryReportInfoResponse(
        code=0,
        data=[{
            "success": True,
            "data": [
                {"data_dt": "2026-03-31", "org_ecd": "wangyi_credit_union",
                 "idx_name": "存款余额", "value": 1234.0},
                {"data_dt": "2026-03-31", "org_ecd": "rogue_org_ignored",
                 "idx_name": "存款余额", "value": 9999.0},
            ],
        }],
    )
    rows = _rows_from_response(
        resp,
        [{"org_ecd": "wangyi_credit_union", "org_name": "王益联社"}],
    )
    assert len(rows) == 1
    assert rows[0]["org_ecd"] == "wangyi_credit_union"
    assert rows[0]["success"] is True
    assert rows[0]["raw_value"] == "1234.0"


def test_rows_from_response_marks_missing_orgs_as_failed():
    """org 在 contexts 里但 SQLBot 没返 → success=False row."""
    resp = QueryReportInfoResponse(
        code=0, data=[{"success": True, "data": []}],
    )
    rows = _rows_from_response(
        resp,
        [{"org_ecd": "wangyi_credit_union", "org_name": "王益联社"}],
    )
    assert rows[0]["success"] is False
    assert rows[0]["raw_value"] == ""


def test_unique_indicator_periods_uses_time_info():
    """没有 leaf period 的 report → 走 time_info 全展开 + 保留 header 的 None pair."""
    report = {
        "time_info": ["202603", "202604"],
        "headers": [[{"idx_id": "BAS_001", "period": None}]],
    }
    pairs = _unique_indicator_periods(report)
    # time_info expands idx × periods first, then header pair (None) is appended
    assert pairs == [
        ("BAS_001", "202603"),
        ("BAS_001", "202604"),
        ("BAS_001", None),
    ]


def test_unique_indicator_periods_prefers_leaf_periods():
    """leaf header 有 period 时优先; time_info 也要并入未覆盖的 pair."""
    report = {
        "time_info": ["202603"],
        "headers": [
            [{"idx_id": "BAS_001", "period": "202602"}],
            [{"idx_id": "BAS_001", "period": "202603"}],
        ],
    }
    pairs = _unique_indicator_periods(report)
    assert ("BAS_001", "202602") in pairs
    assert ("BAS_001", "202603") in pairs


def test_query_from_parsed_walks_all_reports():
    """解析 → query → result 携带 (section_idx, report_idx, idx_id, period)."""
    parsed = {
        "sections": [
            {
                "title": "S1",
                "reports": [{
                    "title": "R1",
                    "org_contexts": [{"org_ecd": "wangyi_credit_union",
                                      "org_name": "王益联社"}],
                    "time_info": ["202603"],
                    "headers": [[{"idx_id": "BAS_001", "period": "202603"}]],
                }],
            },
            {
                "title": "S2",
                "reports": [{
                    "title": "R2",
                    "org_contexts": [{"org_ecd": "wangyi_credit_union",
                                      "org_name": "王益联社"}],
                    "time_info": ["202603"],
                    "headers": [[{"idx_id": "BAS_010", "period": "202603"}]],
                }],
            },
        ],
    }
    client = MockSQLBotClient(
        fixture_path="tests/fixtures/mock_sqlbot/wangyi_2026_03.json",
    )
    payload = query_from_parsed(parsed, client)
    results = payload["results"]
    assert len(results) == 2
    by_key = {(r["section_idx"], r["idx_id"]): r for r in results}
    assert (0, "BAS_001") in by_key
    assert (1, "BAS_010") in by_key
    for r in results:
        assert r["results"][0]["org_ecd"] == "wangyi_credit_union"
        assert r["results"][0]["success"] is True


# --- CLI smoke --- #


def test_cli_query_writes_query_json(tmp_path):
    """`sqlbot_client.py query --parsed ... --out ... --mock` 走通 CLI."""
    parsed_path = tmp_path / "parsed.json"
    parsed_path.write_text(json.dumps({
        "sections": [{
            "title": "S1",
            "reports": [{
                "title": "R1",
                "org_contexts": [{"org_ecd": "wangyi_credit_union",
                                  "org_name": "王益联社"}],
                "time_info": ["202603"],
                "headers": [[{"idx_id": "BAS_001", "period": "202603"}]],
            }],
        }],
    }), encoding="utf-8")
    out_path = tmp_path / "query.json"
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    result = subprocess.run(
        [sys.executable, str(scripts_dir / "sqlbot_client.py"), "query",
         "--parsed", str(parsed_path), "--out", str(out_path), "--mock"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "OK: queried 1 indicator-periods via mock" in result.stdout
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(payload["results"]) == 1
    assert payload["results"][0]["idx_id"] == "BAS_001"
    assert payload["results"][0]["results"][0]["raw_value"] == "1234567890.5"