"""Unit tests for session_store.py — async persistence and file operations."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from session_store import SessionStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_session_json(sessions_dir: Path, session_id: str, title="Test Session"):
    """Write a well-formed session JSON to disk for load-on-startup tests."""
    data = {
        "session_id": session_id,
        "info": {
            "created_at": 1000000.0,
            "last_active": 1000001.0,
            "title": title,
            "last_checkpoint_id": None,
        },
        "metrics": {"total_tokens": 42, "tool_calls": 3, "turns": 1},
    }
    path = sessions_dir / f"{session_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


def _join_worker(store: SessionStore, timeout=2.0):
    """Signal the worker thread to stop and join it."""
    store.shutdown()
    store._write_thread.join(timeout=timeout)


# ---------------------------------------------------------------------------
# __init__ and disk loading
# ---------------------------------------------------------------------------

class TestInitAndDiskLoading:
    """Startup behavior: directory creation, session loading from disk."""

    def test_creates_directories(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        archive_dir = tmp_path / "archive"
        store = SessionStore(sessions_dir, archive_dir)
        try:
            assert sessions_dir.exists()
            assert archive_dir.exists()
        finally:
            _join_worker(store)

    def test_loads_valid_sessions_from_disk(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        archive_dir = tmp_path / "archive"
        _write_session_json(sessions_dir, "abc123", "Hello")

        store = SessionStore(sessions_dir, archive_dir)
        try:
            assert "abc123" in store.sessions
            assert store.sessions["abc123"]["title"] == "Hello"
            assert store.session_metrics["abc123"]["total_tokens"] == 42
        finally:
            _join_worker(store)

    def test_skips_corrupted_json_files(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        archive_dir = tmp_path / "archive"
        bad_file = sessions_dir / "bad.json"
        bad_file.parent.mkdir(parents=True, exist_ok=True)
        bad_file.write_text("not json at all {{{")

        store = SessionStore(sessions_dir, archive_dir)
        try:
            assert "bad" not in store.sessions
        finally:
            _join_worker(store)

    def test_empty_sessions_dir_starts_clean(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        archive_dir = tmp_path / "archive"
        store = SessionStore(sessions_dir, archive_dir)
        try:
            assert store.sessions == {}
        finally:
            _join_worker(store)


# ---------------------------------------------------------------------------
# save_async — enqueue writes
# ---------------------------------------------------------------------------

class TestSaveAsync:
    """Asynchronous save behaviour."""

    def test_queues_write_for_known_session(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        archive_dir = tmp_path / "archive"
        store = SessionStore(sessions_dir, archive_dir)
        try:
            store.sessions["s1"] = {
                "created_at": 1.0,
                "last_active": 2.0,
                "title": "T",
                "last_checkpoint_id": None,
            }
            store.session_metrics["s1"] = {"total_tokens": 0, "tool_calls": 0, "turns": 0}

            store.save_async("s1")

            # The pending-writes dict holds the coalesced data
            with store._lock:
                assert "s1" in store._pending_writes

            # Let the worker flush
            _join_worker(store)
            assert (sessions_dir / "s1.json").exists()
        finally:
            _join_worker(store)

    def test_noop_for_unknown_session(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        archive_dir = tmp_path / "archive"
        store = SessionStore(sessions_dir, archive_dir)
        try:
            store.save_async("nonexistent")
            with store._lock:
                assert "nonexistent" not in store._pending_writes
        finally:
            _join_worker(store)

    def test_coalesces_multiple_rapid_calls(self, tmp_path: Path):
        """Multiple save_async calls for the same session produce one write."""
        sessions_dir = tmp_path / "sessions"
        archive_dir = tmp_path / "archive"
        store = SessionStore(sessions_dir, archive_dir)
        try:
            store.sessions["s2"] = {
                "created_at": 1.0,
                "last_active": 2.0,
                "title": "Before",
                "last_checkpoint_id": None,
            }
            store.session_metrics["s2"] = {"total_tokens": 0, "tool_calls": 0, "turns": 0}

            store.save_async("s2")
            # Mutate after first enqueue — the pending write snapshot is stale
            store.sessions["s2"]["title"] = "After"
            store.save_async("s2")

            _join_worker(store)

            # The second call overwrote the pending write, so disk gets "After"
            data = json.loads((sessions_dir / "s2.json").read_text())
            assert data["info"]["title"] == "After"
        finally:
            _join_worker(store)


# ---------------------------------------------------------------------------
# _write_worker — background thread behavior
# ---------------------------------------------------------------------------

class TestWriteWorker:
    """Background thread lifecycle and error handling."""

    def test_exits_on_none_sentinel(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        archive_dir = tmp_path / "archive"
        store = SessionStore(sessions_dir, archive_dir)
        store.shutdown()
        store._write_thread.join(timeout=3)
        assert not store._write_thread.is_alive()

    def test_drains_queue_on_shutdown(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        archive_dir = tmp_path / "archive"
        store = SessionStore(sessions_dir, archive_dir)
        store.sessions["s3"] = {
            "created_at": 1.0,
            "last_active": 2.0,
            "title": "Q",
            "last_checkpoint_id": None,
        }
        store.session_metrics["s3"] = {"total_tokens": 0, "tool_calls": 0, "turns": 0}

        for _ in range(5):
            store.save_async("s3")

        _join_worker(store)

        # All queued items were consumed (queue is empty) and file was written
        assert (sessions_dir / "s3.json").exists()
        # Queue should be empty after successful shutdown
        assert store._write_queue.empty()


# ---------------------------------------------------------------------------
# delete_session_files
# ---------------------------------------------------------------------------

class TestDeleteSessionFiles:
    """Session file deletion and in-memory cleanup."""

    def test_removes_file_and_memory_state(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        archive_dir = tmp_path / "archive"
        store = SessionStore(sessions_dir, archive_dir)
        try:
            # Prime session in memory and on disk
            store.sessions["d1"] = {
                "created_at": 1.0,
                "last_active": 2.0,
                "title": "D",
                "last_checkpoint_id": None,
            }
            store.session_metrics["d1"] = {"total_tokens": 0, "tool_calls": 0, "turns": 0}
            store.save_async("s1")  # Just to exercise queue
            (sessions_dir / "d1.json").write_text("{}")

            store.delete_session_files("d1")

            assert "d1" not in store.sessions
            assert "d1" not in store.session_metrics
            assert not (sessions_dir / "d1.json").exists()
        finally:
            _join_worker(store)

    def test_clears_pending_write(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        archive_dir = tmp_path / "archive"
        store = SessionStore(sessions_dir, archive_dir)
        try:
            store.sessions["d2"] = {
                "created_at": 1.0,
                "last_active": 2.0,
                "title": "D2",
                "last_checkpoint_id": None,
            }
            store.session_metrics["d2"] = {"total_tokens": 0, "tool_calls": 0, "turns": 0}
            store.save_async("d2")

            store.delete_session_files("d2")

            with store._lock:
                assert "d2" not in store._pending_writes
        finally:
            _join_worker(store)


# ---------------------------------------------------------------------------
# archive_session_files
# ---------------------------------------------------------------------------

class TestArchiveSessionFiles:
    """Moving sessions to the archive directory."""

    def test_moves_existing_file_to_archive(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        archive_dir = tmp_path / "archive"
        store = SessionStore(sessions_dir, archive_dir)
        try:
            store.sessions["a1"] = {
                "created_at": 1.0,
                "last_active": 2.0,
                "title": "A",
                "last_checkpoint_id": None,
            }
            store.session_metrics["a1"] = {"total_tokens": 1, "tool_calls": 0, "turns": 1}
            # Write to disk first so the file exists
            store.save_async("a1")
            # Drain so it's on disk
            _join_worker(store)
            # Recreate store with a fresh worker (the old one is now dead)
            store = SessionStore(sessions_dir, archive_dir)
            store.sessions["a1"] = {
                "created_at": 1.0,
                "last_active": 2.0,
                "title": "A",
                "last_checkpoint_id": None,
            }
            store.session_metrics["a1"] = {"total_tokens": 1, "tool_calls": 0, "turns": 1}

            assert (sessions_dir / "a1.json").exists()

            store.archive_session_files("a1")

            assert "a1" not in store.sessions
            assert "a1" not in store.session_metrics
            assert not (sessions_dir / "a1.json").exists()
            assert (archive_dir / "a1.json").exists()
        finally:
            _join_worker(store)

    def test_handles_unflushed_pending_write(self, tmp_path: Path):
        """When archiving a session that was saved but not yet flushed to disk."""
        sessions_dir = tmp_path / "sessions"
        archive_dir = tmp_path / "archive"
        store = SessionStore(sessions_dir, archive_dir)
        try:
            store.sessions["a2"] = {
                "created_at": 1.0,
                "last_active": 3.0,
                "title": "Unflushed",
                "last_checkpoint_id": None,
            }
            store.session_metrics["a2"] = {"total_tokens": 5, "tool_calls": 1, "turns": 1}
            store.save_async("a2")
            # Do NOT drain — the file isn't on disk yet

            store.archive_session_files("a2")

            assert "a2" not in store.sessions
            assert not (sessions_dir / "a2.json").exists()
            # Archive file was written directly from pending data
            assert (archive_dir / "a2.json").exists()

            data = json.loads((archive_dir / "a2.json").read_text())
            assert data["info"]["title"] == "Unflushed"
        finally:
            _join_worker(store)


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    """Concurrent access to SessionStore from multiple threads."""

    def test_concurrent_saves_from_multiple_threads(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        archive_dir = tmp_path / "archive"
        store = SessionStore(sessions_dir, archive_dir)
        errors: list[Exception] = []

        def writer(sid: str):
            try:
                store.sessions[sid] = {
                    "created_at": time.time(),
                    "last_active": time.time(),
                    "title": f"Thread-{sid}",
                    "last_checkpoint_id": None,
                }
                store.session_metrics[sid] = {"total_tokens": 0, "tool_calls": 0, "turns": 0}
                for _ in range(10):
                    store.save_async(sid)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            t = threading.Thread(target=writer, args=(f"t{i}",))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        _join_worker(store)

        assert len(errors) == 0
        for i in range(5):
            assert (sessions_dir / f"t{i}.json").exists()
