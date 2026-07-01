"""Unit tests for report_md.build_runtime_payload (新写, runtime 拼版 wrapper).

CLI main() tested in task 16 (runtime_pipeline E2E). This file covers the
logic-only function: pull approved tables from DuckDB → render_payload dict.
"""

from __future__ import annotations

import json

import pytest

from duckdb_store import Store
from report_md import build_runtime_payload


@pytest.fixture
def store(tmp_path):
    s = Store(db_path=str(tmp_path / "test.duckdb"))
    s.open()  # auto-inits schema
    rid = s.upsert_report("rid", "Test Report", "/x.md", "h")
    sid1 = s.upsert_section(rid, 0, "存款")
    sid2 = s.upsert_section(rid, 1, "贷款")
    # Table 1: section 0, table 0
    tid1 = s.upsert_table(rid, sid1, 0, "存款余额", "<table/>", "h",
                          {"headers_2d": [[{"text": "机构"}, {"text": "存款", "data_unit": "万元", "idx_id": "BAS_001", "period": "202603"}]]})
    # Table 2: section 1, table 0
    tid2 = s.upsert_table(rid, sid2, 0, "贷款余额", "<table/>", "h",
                          {"headers_2d": [[{"text": "机构"}, {"text": "贷款", "data_unit": "亿元", "idx_id": "LOAN_001", "period": "202603"}]]})
    s.save_approved_run(
        "run1", tid1, rid, sid1,
        [{"branch_num": "1", "BAS_001@202603": 12345}],
        [], [{"text": "本表展示存款余额"}], "ok",
        ["BAS_001@202603"], "log1", "/x.design.md",
    )
    s.save_approved_run(
        "run2", tid2, rid, sid2,
        [{"branch_num": "1", "LOAN_001@202603": 67890}],
        [], [], "ok",
        [], "log2", "/x.design.md",
    )
    yield s
    s.close()


def test_build_runtime_payload_orders_sections_by_section_order(store):
    """2 sections with different orders, payload must be sorted by section_order."""
    payload = build_runtime_payload(store, "rid")
    assert payload["title"] == "Test Report"
    assert len(payload["sections"]) == 2
    assert payload["sections"][0]["title"] == "存款"
    assert payload["sections"][1]["title"] == "贷款"


def test_build_runtime_payload_extracts_headers_from_parsed_payload(store):
    """Headers come from report_tables.parsed_payload.headers_2d (auto-decoded)."""
    payload = build_runtime_payload(store, "rid")
    headers = payload["sections"][0]["reports"][0]["headers"]
    assert headers[0][0] == {"text": "机构"}
    assert headers[0][1]["idx_id"] == "BAS_001"
    assert headers[0][1]["data_unit"] == "万元"
    assert headers[0][1]["period"] == "202603"


def test_build_runtime_payload_extracts_rows_from_wide_table(store):
    """Rows come from approved_table_runs.wide_table (auto-decoded JSON)."""
    payload = build_runtime_payload(store, "rid")
    rows = payload["sections"][0]["reports"][0]["rows"]
    assert rows == [{"branch_num": "1", "BAS_001@202603": 12345}]


def test_build_runtime_payload_extracts_sentinels(store):
    """Sentinels list passed through as-is."""
    payload = build_runtime_payload(store, "rid")
    sentinels = payload["sections"][0]["reports"][0]["sentinels"]
    assert sentinels == ["BAS_001@202603"]


def test_build_runtime_payload_picks_first_description(store):
    """Multiple descriptions — take first (Phase 1: 1 description per table)."""
    payload = build_runtime_payload(store, "rid")
    desc = payload["sections"][0]["reports"][0]["description"]
    assert desc == "本表展示存款余额"


def test_build_runtime_payload_empty_report_id_returns_no_sections(store):
    """Unknown report_id → empty sections list (caller handles 'no approved tables')."""
    payload = build_runtime_payload(store, "unknown_rid")
    assert payload["title"] == "unknown_rid"  # falls back to report_id
    assert payload["sections"] == []