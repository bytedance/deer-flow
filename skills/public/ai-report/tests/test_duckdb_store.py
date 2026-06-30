"""Unit tests for duckdb_store (新写, 5 表 schema 锁定)."""

from __future__ import annotations

import time
from decimal import Decimal

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


# ---- P0-1 / P1-3: upsert_section 更新 updated_at ---- #

def test_upsert_section_updates_updated_at_on_conflict(store):
    rid = store.upsert_report("rid", "t", "/x", "h")
    sid = store.upsert_section(rid, 0, "原标题")
    before = store._conn.execute(
        "SELECT updated_at FROM report_sections WHERE section_id=?", [sid]
    ).fetchone()[0]
    time.sleep(0.05)  # now() 精度通常到 ms, 留余量
    store.upsert_section(rid, 0, "新标题")
    after = store._conn.execute(
        "SELECT updated_at FROM report_sections WHERE section_id=?", [sid]
    ).fetchone()[0]
    assert after > before, f"updated_at 应更新: before={before} after={after}"


# ---- P0-2: executemany 批量插入 ---- #

def test_insert_metric_facts_batch_inserts_all(store):
    rid = store.upsert_report("rid", "t", "/x", "h")
    sid = store.upsert_section(rid, 0, "s")
    tid = store.upsert_table(rid, sid, 0, "table", "md", "h", {})
    facts = [
        {"branch_num": str(i), "idx_id": "A", "period_alias": "202603", "numeric_value": 100 + i, "status": "ok"}
        for i in range(50)
    ]
    store.insert_metric_facts("run1", tid, rid, facts)
    rows = store.get_metric_facts("run1", tid)
    assert len(rows) == 50
    # Decimal 比对: 100 + 0..49
    values = sorted(int(r["numeric_value"]) for r in rows)
    assert values == list(range(100, 150))


def test_insert_metric_facts_empty_list_is_noop(store):
    rid = store.upsert_report("rid", "t", "/x", "h")
    sid = store.upsert_section(rid, 0, "s")
    tid = store.upsert_table(rid, sid, 0, "table", "md", "h", {})
    store.insert_metric_facts("run1", tid, rid, [])
    assert store.get_metric_facts("run1", tid) == []


# ---- P1-2: list_approved_tables 自动 decode JSON ---- #

def test_list_approved_tables_decodes_json_columns(tmp_path):
    with Store(db_path=str(tmp_path / "t.duckdb")) as s:
        s.init_schema()
        rid = s.upsert_report("rid", "t", "/x", "h")
        sid = s.upsert_section(rid, 0, "s")
        tid = s.upsert_table(rid, sid, 0, "table", "md", "h", {})
        wide = [{"branch_num": "1", "row": [{"col": 100}]}]
        computed = [{"slug": "yoy", "sql": "SELECT 1"}]
        descs = [{"slug": "yoy", "text": "YoY 增长"}]
        sents = [{"code": "QUERY_FAILED", "idx_id": "A"}]
        s.save_approved_run("run1", tid, rid, sid, wide, computed, descs, "ok", sents, "log", "/x.md")
        out = s.list_approved_tables(rid)
    assert len(out) == 1
    assert out[0]["wide_table"] == wide
    assert out[0]["computed_columns"] == computed
    assert out[0]["descriptions"] == descs
    assert out[0]["sentinels"] == sents


# ---- P2-2: context manager ---- #

def test_store_context_manager(tmp_path):
    db = str(tmp_path / "ctx.duckdb")
    with Store(db_path=db) as s:
        s.init_schema()
        assert s.conn is not None
    # closed after exit
    s2 = Store(db_path=db)
    assert s2._conn is None
    s2.open()
    s2.close()


# ---- P1-1: TIMESTAMPTZ 列存在 ---- #

def test_schema_uses_timestamptz(store):
    rows = store._conn.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema='main' AND column_name IN ('created_at', 'updated_at') "
        "ORDER BY table_name, column_name"
    ).fetchall()
    assert rows, "应有时戳列"
    bad = [(t, c, dt) for (t, c, dt) in rows if "TIMESTAMP" not in dt.upper() or "TIMESTAMP" == dt.upper()]
    # 接受 TIMESTAMP WITH TIME ZONE / TIMESTAMPTZ; 不接受裸 TIMESTAMP
    type_set = {dt.upper() for (_, _, dt) in rows}
    assert type_set, "应至少有一种时戳类型"
    assert all("WITH TIME ZONE" in dt.upper() or "TIMESTAMPTZ" in dt.upper() for (_, _, dt) in rows), \
        f"时戳列必须带时区, 实际: {type_set}"