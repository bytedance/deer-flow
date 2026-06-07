import json
import sqlite3
from datetime import datetime

import pytest

from tg_intel_crawler.storage.exporter import Exporter, IntelRecord
from tg_intel_crawler.storage.sqlite_store import SQLiteStore


@pytest.fixture
def store(tmp_path):
    return SQLiteStore(str(tmp_path / "intel.db"))


def _record(rec_id="msg_1"):
    return IntelRecord(
        id=rec_id,
        source_group="g",
        date=datetime(2026, 6, 7, 10, 0, 0),
        original_text="抖音账号出售",
        risk_type="账号交易",
        risk_level="high",
        entities={"accounts": ["a"], "prices": ["50"]},
        summary="出售账号",
        llm_model="ep-test",
    )


# ---------- SQLiteStore unit ----------

def test_schema_created(store, tmp_path):
    conn = sqlite3.connect(str(tmp_path / "intel.db"))
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert {"telegram_intel_raw", "telegram_intel_filtered"} <= names
    conn.close()


def test_table_names_exposed(store):
    assert store.source == "telegram"
    assert store.raw_table == "telegram_intel_raw"
    assert store.filtered_table == "telegram_intel_filtered"


def test_filtered_dedupe_same_day(store):
    rec = {"id": "msg_1", "entities": {"a": 1}, "date": "2026-06-07T10:00:00"}
    assert store.insert_filtered([rec], day="2026-06-07") == 1
    # Same (day, id) again → ignored.
    assert store.insert_filtered([rec], day="2026-06-07") == 0
    assert store.count_filtered(day="2026-06-07") == 1


def test_filtered_cross_day_kept(store):
    rec = {"id": "msg_1", "entities": {}, "date": "2026-06-07T10:00:00"}
    assert store.insert_filtered([rec], day="2026-06-07") == 1
    # Same id, different day → kept (one snapshot per day).
    assert store.insert_filtered([rec], day="2026-06-08") == 1
    assert store.count_filtered() == 2
    assert store.count_filtered(day="2026-06-07") == 1
    assert store.count_filtered(day="2026-06-08") == 1


def test_raw_dedupe_same_day_cross_day(store):
    msgs = [{"msg_id": 1, "text": "a"}, {"msg_id": 2, "text": "b"}]
    assert store.insert_raw(msgs, group_name="g", day="2026-06-07") == 2
    # Re-insert same day → all deduped.
    assert store.insert_raw(msgs, group_name="g", day="2026-06-07") == 0
    # Next day → kept again (snapshot per day).
    assert store.insert_raw(msgs, group_name="g", day="2026-06-08") == 2
    assert store.count_raw() == 4


def test_raw_without_id_not_dropped(store):
    msgs = [{"text": "no id here"}, {"text": "another"}]
    added = store.insert_raw(msgs, group_name="g", day="2026-06-07")
    assert added == 2  # synthetic identity keeps them


# ---------- Exporter dual-write ----------

def test_exporter_dual_writes_sqlite(tmp_path):
    exp = Exporter(output_dir=str(tmp_path), formats=["json", "csv"])
    exp.export_filtered([_record("msg_1")])
    exp.export_raw([{"msg_id": 10, "text": "hi"}], group_name="g")

    db = tmp_path / "intel.db"
    assert db.exists()
    conn = sqlite3.connect(str(db))
    n_intel = conn.execute("SELECT COUNT(*) FROM telegram_intel_filtered").fetchone()[0]
    n_raw = conn.execute("SELECT COUNT(*) FROM telegram_intel_raw").fetchone()[0]
    # entities stored as JSON string.
    ent = conn.execute(
        "SELECT entities FROM telegram_intel_filtered WHERE id='msg_1'"
    ).fetchone()[0]
    conn.close()
    assert n_intel == 1
    assert n_raw == 1
    assert json.loads(ent)["accounts"] == ["a"]


def test_exporter_still_writes_json_csv(tmp_path):
    exp = Exporter(output_dir=str(tmp_path), formats=["json", "csv"])
    exp.export_filtered([_record("msg_1")])
    assert list((tmp_path / "filtered").glob("*.json"))
    assert list((tmp_path / "filtered").glob("*.csv"))


def test_exporter_sqlite_can_be_disabled(tmp_path):
    exp = Exporter(output_dir=str(tmp_path), formats=["json"], sqlite=False)
    exp.export_filtered([_record("msg_1")])
    assert not (tmp_path / "intel.db").exists()
    assert list((tmp_path / "filtered").glob("*.json"))


# ---------- multi-source ----------

def test_multiple_sources_share_db_distinct_tables(tmp_path):
    db = str(tmp_path / "intel.db")
    tg = SQLiteStore(db, source="telegram")
    wb = SQLiteStore(db, source="weibo")
    tg.insert_filtered([{"id": "a", "entities": {}, "date": "2026-06-07T0:0:0"}],
                       day="2026-06-07")
    wb.insert_filtered([{"id": "a", "entities": {}, "date": "2026-06-07T0:0:0"}],
                       day="2026-06-07")
    # Same id in both sources, but separate tables → both kept.
    assert tg.count_filtered() == 1
    assert wb.count_filtered() == 1

    conn = sqlite3.connect(db)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    conn.close()
    assert {"telegram_intel_filtered", "weibo_intel_filtered",
            "telegram_intel_raw", "weibo_intel_raw"} <= names


def test_invalid_source_rejected(tmp_path):
    with pytest.raises(ValueError):
        SQLiteStore(str(tmp_path / "intel.db"), source="Weibo-Prod")  # caps/hyphen


# ---------- legacy auto-migration ----------

def test_legacy_tables_migrated_into_telegram(tmp_path):
    db = tmp_path / "intel.db"
    # Hand-craft an old-schema DB (pre multi-source naming).
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE filtered_intel (day TEXT, id TEXT, source_platform TEXT, "
        "source_group TEXT, msg_date TEXT, sender_id INTEGER, sender_name TEXT, "
        "sender_username TEXT, original_text TEXT, risk_type TEXT, risk_level TEXT, "
        "entities TEXT, summary TEXT, llm_model TEXT, source_url TEXT, suffix TEXT, "
        "inserted_at TEXT, PRIMARY KEY (day, id))"
    )
    conn.execute(
        "CREATE TABLE raw_messages (day TEXT, identity TEXT, group_name TEXT, "
        "subdir TEXT, msg_date TEXT, payload TEXT, inserted_at TEXT, "
        "PRIMARY KEY (day, identity))"
    )
    conn.execute(
        "INSERT INTO filtered_intel VALUES "
        "('2026-06-06','old1','telegram','g',NULL,0,'','','','t','high','{}','s','m','','','now')"
    )
    conn.execute(
        "INSERT INTO raw_messages VALUES "
        "('2026-06-06','msg_id:1','g','',NULL,'{}','now')"
    )
    conn.commit()
    conn.close()

    # Opening with the new store should migrate + drop legacy tables.
    store = SQLiteStore(str(db), source="telegram")
    assert store.count_filtered() == 1
    assert store.count_raw() == 1

    conn = sqlite3.connect(str(db))
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    conn.close()
    assert "filtered_intel" not in names   # legacy dropped
    assert "raw_messages" not in names
    assert "telegram_intel_filtered" in names
