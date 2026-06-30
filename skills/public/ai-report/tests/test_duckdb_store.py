"""Unit tests for duckdb_store (新写, 5 表 schema 锁定)."""

from __future__ import annotations

import duckdb
import pytest

from duckdb_store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(db_path=str(tmp_path / "test.duckdb"))
    s.open()
    s.init_schema()
    yield s
    s.close()


def test_init_schema_creates_5_tables(store):
    rows = store._conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name"
    ).fetchall()
    names = [r[0] for r in rows]
    assert names == ["approved_table_runs", "metric_facts", "report_sections", "report_tables", "reports"]


def test_upsert_report_and_section(store):
    rid = store.upsert_report("rid123", "title", "/tmp/x.md", "hash123")
    assert rid == "rid123"
    sid = store.upsert_section(rid, 0, "一、章")
    assert sid == "rid123_s00"


def test_upsert_table_id_naming(store):
    rid = store.upsert_report("rid", "t", "/x", "h")
    sid = store.upsert_section(rid, 0, "s")
    tid = store.upsert_table(rid, sid, 0, "table", "md", "h", {"x": 1})
    assert tid == "rid_s00_t00"


def test_list_tables_by_section_returns_ordered(store):
    rid = store.upsert_report("rid", "t", "/x", "h")
    sid = store.upsert_section(rid, 0, "s")
    store.upsert_table(rid, sid, 0, "table0", "md", "h", {})
    store.upsert_table(rid, sid, 1, "table1", "md", "h", {})
    tables = store.list_tables_by_section(sid)
    assert [t["table_id"] for t in tables] == ["rid_s00_t00", "rid_s00_t01"]
    assert [t["table_order"] for t in tables] == [0, 1]


def test_run_id_history_preserved(store):
    rid = store.upsert_report("rid", "t", "/x", "h")
    sid = store.upsert_section(rid, 0, "s")
    tid = store.upsert_table(rid, sid, 0, "table", "md", "h", {})
    # 两次 design run, 都应该保留
    store.insert_metric_facts("run1", tid, rid, [{"branch_num": "1", "idx_id": "A", "period_alias": "202603", "numeric_value": 100, "status": "ok"}])
    store.insert_metric_facts("run2", tid, rid, [{"branch_num": "1", "idx_id": "A", "period_alias": "202603", "numeric_value": 200, "status": "ok"}])
    r1 = store.get_metric_facts("run1", tid)
    r2 = store.get_metric_facts("run2", tid)
    assert len(r1) == 1 and r1[0]["numeric_value"] == 100
    assert len(r2) == 1 and r2[0]["numeric_value"] == 200


def test_approved_run_design_md_path_not_null(store):
    rid = store.upsert_report("rid", "t", "/x", "h")
    sid = store.upsert_section(rid, 0, "s")
    tid = store.upsert_table(rid, sid, 0, "table", "md", "h", {})
    store.save_approved_run("run1", tid, rid, sid, [], [], [], "ok", [], "log", "/mnt/ai-report-data/rid.design.md")
    run = store.get_approved_run(tid)
    assert run["design_md_path"] == "/mnt/ai-report-data/rid.design.md"