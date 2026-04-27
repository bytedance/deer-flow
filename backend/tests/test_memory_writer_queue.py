"""Tests for the single-writer memory queue (RFC #2283)."""

from __future__ import annotations

import json
import sqlite3
import time
from unittest.mock import patch

import pytest

from deerflow.agents.memory import writer_queue
from deerflow.agents.memory.sqlite_storage import SQLiteMemoryStorage
from deerflow.agents.memory.writer_queue import (
    _parse_utc_iso,
    enqueue,
    init_queue_schema,
    migrate_json_to_sqlite,
    reset_stuck_tasks,
    run_writer_loop,
    schedule_memory_update,
    trim_queue,
    try_acquire_writer,
)


@pytest.fixture()
def db_path(tmp_path):
    p = tmp_path / "memory.db"
    init_queue_schema(p)
    return p


@pytest.fixture(autouse=True)
def _release_process_guard():
    """Ensure the process-local writer guard is released between tests."""
    yield
    if writer_queue._writer_running.locked():
        try:
            writer_queue._writer_running.release()
        except RuntimeError:
            pass


# --------------------------------------------------------------------------- #
#  Timestamp parser                                                            #
# --------------------------------------------------------------------------- #
class TestParseUtcIso:
    def test_round_trip_with_z_suffix(self):
        from deerflow.agents.memory.storage import utc_now_iso_z

        ts = utc_now_iso_z()
        parsed = _parse_utc_iso(ts)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0

    def test_naive_iso_string_is_treated_as_utc(self):
        parsed = _parse_utc_iso("2025-01-01T00:00:00")
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0


# --------------------------------------------------------------------------- #
#  Enqueue                                                                    #
# --------------------------------------------------------------------------- #
class TestEnqueue:
    def test_inserts_pending_row(self, db_path):
        enqueue(db_path, agent_name=None, messages=[], thread_id="t1")
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT agent_name, status, thread_id FROM memory_update_queue").fetchone()
        assert row["agent_name"] == "__global__"
        assert row["status"] == "pending"
        assert row["thread_id"] == "t1"

    def test_agent_name_none_becomes_global_sentinel(self, db_path):
        enqueue(db_path, agent_name=None, messages=[], thread_id=None)
        enqueue(db_path, agent_name="researcher", messages=[], thread_id=None)
        with sqlite3.connect(str(db_path)) as conn:
            names = sorted(r[0] for r in conn.execute("SELECT agent_name FROM memory_update_queue").fetchall())
        assert names == ["__global__", "researcher"]

    def test_serialises_messages_via_langchain(self, db_path):
        from langchain_core.messages import HumanMessage

        enqueue(
            db_path,
            agent_name=None,
            messages=[HumanMessage(content="hello")],
            thread_id="t",
        )
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT messages FROM memory_update_queue").fetchone()
        parsed = json.loads(row["messages"])
        assert parsed[0]["type"] == "human"


# --------------------------------------------------------------------------- #
#  Writer lease                                                               #
# --------------------------------------------------------------------------- #
class TestWriterLease:
    def test_first_caller_acquires(self, db_path):
        assert try_acquire_writer(db_path, "worker-A") is True

    def test_second_caller_is_rejected_while_lease_fresh(self, db_path):
        assert try_acquire_writer(db_path, "worker-A") is True
        assert try_acquire_writer(db_path, "worker-B") is False

    def test_same_worker_can_reacquire_its_own_lease(self, db_path):
        assert try_acquire_writer(db_path, "worker-A") is True
        # Same worker acquiring again is a no-op upsert, not a failure.
        assert try_acquire_writer(db_path, "worker-A") is True

    def test_stale_lease_can_be_taken_over(self, db_path):
        assert try_acquire_writer(db_path, "worker-A") is True
        # Age out the heartbeat beyond the default lock_stale window (90s).
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("UPDATE memory_writer_lock SET heartbeat_at='2000-01-01T00:00:00Z'")
            conn.commit()
        assert try_acquire_writer(db_path, "worker-B") is True


# --------------------------------------------------------------------------- #
#  reset_stuck_tasks / trim_queue                                             #
# --------------------------------------------------------------------------- #
class TestMaintenance:
    def test_reset_stuck_tasks(self, db_path):
        enqueue(db_path, agent_name=None, messages=[], thread_id="t")
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("UPDATE memory_update_queue SET status='processing', started_at='2000-01-01T00:00:00Z'")
            conn.commit()
        assert reset_stuck_tasks(db_path) == 1
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT status, started_at FROM memory_update_queue").fetchone()
        assert row["status"] == "pending"
        assert row["started_at"] is None

    def test_trim_queue_removes_only_completed(self, db_path):
        enqueue(db_path, agent_name=None, messages=[], thread_id="done")
        enqueue(db_path, agent_name=None, messages=[], thread_id="pending")
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("UPDATE memory_update_queue SET status='done', completed_at='2000-01-01T00:00:00Z' WHERE thread_id='done'")
            conn.commit()

        deleted = trim_queue(db_path, keep_days=1)
        assert deleted == 1
        with sqlite3.connect(str(db_path)) as conn:
            remaining = [r[0] for r in conn.execute("SELECT thread_id FROM memory_update_queue").fetchall()]
        assert remaining == ["pending"]

    def test_trim_queue_rejects_negative_keep_days(self, db_path):
        with pytest.raises(ValueError):
            trim_queue(db_path, keep_days=-1)


# --------------------------------------------------------------------------- #
#  run_writer_loop (end-to-end with mocked LLM)                               #
# --------------------------------------------------------------------------- #
class TestRunWriterLoop:
    def test_processes_all_pending_tasks(self, db_path):
        for i in range(3):
            enqueue(db_path, agent_name=None, messages=[], thread_id=f"t{i}")
        try_acquire_writer(db_path, "worker-1")

        # Hold the process-local guard as schedule_memory_update would.
        writer_queue._writer_running.acquire()

        calls = []

        def fake_update(*, messages, thread_id, agent_name, **kwargs):
            calls.append(thread_id)
            return True

        with patch(
            "deerflow.agents.memory.updater.update_memory_from_conversation",
            side_effect=fake_update,
        ):
            run_writer_loop(db_path, "worker-1")

        assert calls == ["t0", "t1", "t2"]
        with sqlite3.connect(str(db_path)) as conn:
            statuses = [r[0] for r in conn.execute("SELECT status FROM memory_update_queue ORDER BY id").fetchall()]
        assert statuses == ["done", "done", "done"]

        # Lease released.
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute("SELECT id FROM memory_writer_lock").fetchone()
        assert row is None

    def test_failed_llm_marks_task_failed_not_done(self, db_path):
        enqueue(db_path, agent_name=None, messages=[], thread_id="t-fail")
        try_acquire_writer(db_path, "worker-1")
        writer_queue._writer_running.acquire()

        def fake_update(**kwargs):
            return False

        with patch(
            "deerflow.agents.memory.updater.update_memory_from_conversation",
            side_effect=fake_update,
        ):
            run_writer_loop(db_path, "worker-1")

        with sqlite3.connect(str(db_path)) as conn:
            status = conn.execute("SELECT status FROM memory_update_queue").fetchone()[0]
        assert status == "failed"

    def test_exception_in_update_is_caught(self, db_path):
        enqueue(db_path, agent_name=None, messages=[], thread_id="t-boom")
        try_acquire_writer(db_path, "worker-1")
        writer_queue._writer_running.acquire()

        def boom(**kwargs):
            raise RuntimeError("LLM exploded")

        with patch(
            "deerflow.agents.memory.updater.update_memory_from_conversation",
            side_effect=boom,
        ):
            run_writer_loop(db_path, "worker-1")

        with sqlite3.connect(str(db_path)) as conn:
            status = conn.execute("SELECT status FROM memory_update_queue").fetchone()[0]
        assert status == "failed"

    def test_agent_name_sentinel_round_trip(self, db_path):
        """A global task enqueued as '__global__' must be delivered back as None."""
        enqueue(db_path, agent_name=None, messages=[], thread_id="t")
        try_acquire_writer(db_path, "worker-1")
        writer_queue._writer_running.acquire()

        received: list[str | None] = []

        def fake_update(*, messages, thread_id, agent_name, **kwargs):
            received.append(agent_name)
            return True

        with patch(
            "deerflow.agents.memory.updater.update_memory_from_conversation",
            side_effect=fake_update,
        ):
            run_writer_loop(db_path, "worker-1")

        assert received == [None]


# --------------------------------------------------------------------------- #
#  schedule_memory_update + migrate_json_to_sqlite                            #
# --------------------------------------------------------------------------- #
class TestScheduleMemoryUpdate:
    def test_schedules_and_drains(self, db_path):
        calls = []

        def fake_update(*, messages, thread_id, agent_name, **kwargs):
            calls.append(thread_id)
            return True

        with patch(
            "deerflow.agents.memory.updater.update_memory_from_conversation",
            side_effect=fake_update,
        ):
            schedule_memory_update(
                db_path,
                agent_name=None,
                messages=[],
                thread_id="t-1",
            )
            # schedule_memory_update spawns a daemon thread; give it a moment.
            for _ in range(50):
                with sqlite3.connect(str(db_path)) as conn:
                    row = conn.execute("SELECT status FROM memory_update_queue WHERE thread_id='t-1'").fetchone()
                if row is not None and row[0] in {"done", "failed"}:
                    break
                time.sleep(0.05)

        assert calls == ["t-1"]


class TestMigrateJsonToSqlite:
    def test_imports_global_memory(self, tmp_path):
        src = tmp_path / "memory.json"
        src.write_text(json.dumps({"version": "1.0", "facts": [{"content": "x"}]}))
        db = tmp_path / "memory.db"

        migrate_json_to_sqlite(src, db)

        storage = SQLiteMemoryStorage(db)
        assert storage.load()["facts"] == [{"content": "x"}]

    def test_imports_per_agent_memory(self, tmp_path):
        src = tmp_path / "planner.json"
        src.write_text(json.dumps({"version": "1.0", "facts": [{"content": "p"}]}))
        db = tmp_path / "memory.db"

        migrate_json_to_sqlite(src, db, agent_name="planner")

        storage = SQLiteMemoryStorage(db)
        assert storage.load(agent_name="planner")["facts"] == [{"content": "p"}]
        # Global row is untouched.
        assert storage.load()["facts"] == []
