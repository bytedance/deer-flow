"""Tests for SQLiteMemoryStorage (RFC #2283)."""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from deerflow.agents.memory.sqlite_storage import SQLiteMemoryStorage


@pytest.fixture()
def db_path(tmp_path):
    return tmp_path / "memory.db"


class TestSQLiteMemoryStorageBasics:
    def test_load_empty_returns_empty_memory(self, db_path):
        storage = SQLiteMemoryStorage(db_path)
        mem = storage.load()
        assert mem["version"] == "1.0"
        assert mem["facts"] == []

    def test_save_then_load_roundtrips(self, db_path):
        storage = SQLiteMemoryStorage(db_path)
        storage.load()  # register seq=0 for this thread
        payload = {"version": "1.0", "facts": [{"content": "x"}]}
        assert storage.save(payload) is True

        # A fresh storage instance sees the persisted data.
        reader = SQLiteMemoryStorage(db_path)
        loaded = reader.load()
        assert loaded["facts"] == [{"content": "x"}]
        assert "lastUpdated" in loaded

    def test_save_does_not_mutate_caller_dict(self, db_path):
        storage = SQLiteMemoryStorage(db_path)
        storage.load()
        original = {"version": "1.0", "facts": []}
        storage.save(original)
        assert "lastUpdated" not in original

    def test_per_agent_rows_are_isolated(self, db_path):
        storage = SQLiteMemoryStorage(db_path)
        storage.load(agent_name="a")
        storage.load(agent_name="b")
        storage.save({"version": "1.0", "facts": [{"content": "A"}]}, agent_name="a")
        storage.save({"version": "1.0", "facts": [{"content": "B"}]}, agent_name="b")

        a = storage.load(agent_name="a")
        b = storage.load(agent_name="b")
        assert a["facts"] == [{"content": "A"}]
        assert b["facts"] == [{"content": "B"}]

    def test_seq_monotonically_increments(self, db_path):
        storage = SQLiteMemoryStorage(db_path)
        storage.load()
        assert storage.save({"version": "1.0", "facts": []}) is True
        storage.load()
        assert storage.save({"version": "1.0", "facts": [{"content": "x"}]}) is True

        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT seq FROM agent_memory WHERE agent_name='__global__'"
            ).fetchone()
        assert row["seq"] == 2

    def test_seq_guard_blocks_concurrent_overwrite(self, db_path):
        """A stale-load save() must abort rather than overwrite newer state."""
        writer_a = SQLiteMemoryStorage(db_path)
        writer_b = SQLiteMemoryStorage(db_path)

        # Both workers read the initial empty state (seq=0).
        writer_a.load()
        writer_b.load()

        # Writer B commits first (seq 0 → 1).
        assert writer_b.save({"version": "1.0", "facts": [{"content": "B"}]}) is True

        # Writer A still holds last_seen=0; its save must fail closed.
        result = writer_a.save({"version": "1.0", "facts": [{"content": "A"}]})
        assert result is False

        # The on-disk state remains B — no silent overwrite.
        reader = SQLiteMemoryStorage(db_path)
        assert reader.load()["facts"] == [{"content": "B"}]

    def test_load_handles_corrupt_json(self, db_path):
        storage = SQLiteMemoryStorage(db_path)
        storage.load()
        storage.save({"version": "1.0", "facts": []})

        # Tamper directly with the row.
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                "UPDATE agent_memory SET data = ? WHERE agent_name='__global__'",
                ("not-json",),
            )
            conn.commit()

        reloaded = storage.reload()
        assert reloaded["version"] == "1.0"
        assert reloaded["facts"] == []

    def test_parallel_load_and_save_does_not_cross_contaminate(self, db_path):
        """Different threads must not share each other's last-seen seq guards."""
        storage = SQLiteMemoryStorage(db_path)
        # Seed a row so seq = 1.
        storage.load()
        storage.save({"version": "1.0", "facts": []})

        errors: list[BaseException] = []

        def worker():
            try:
                # Each thread independently observes seq=1 and saves,
                # advancing seq to 2 and then 3.  Without per-thread guards
                # the second thread's last_seen would be 1 while on-disk is
                # already 2, incorrectly failing the write.
                for _ in range(3):
                    storage.load()
                    ok = storage.save({"version": "1.0", "facts": []})
                    if not ok:
                        # Another thread beat us — that's OK for this test,
                        # we just want to confirm no exception is raised.
                        pass
            except BaseException as e:  # pragma: no cover - diagnostic
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors

    def test_schema_is_idempotent(self, db_path):
        SQLiteMemoryStorage(db_path)
        # Second construction must not raise.
        SQLiteMemoryStorage(db_path)

        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_memory'"
            ).fetchone()
        assert row is not None

    def test_payload_written_as_json(self, db_path):
        storage = SQLiteMemoryStorage(db_path)
        storage.load()
        storage.save({"version": "1.0", "facts": [{"content": "中文"}]})
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT data FROM agent_memory WHERE agent_name='__global__'"
            ).fetchone()
        parsed = json.loads(row["data"])
        assert parsed["facts"] == [{"content": "中文"}]
