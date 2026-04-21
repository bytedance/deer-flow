"""SQLite-backed memory storage.

Implements the storage half of RFC #2283 (single-writer memory queue).

The queue machinery (``writer_queue.py``) requires a shared database file that
every worker process can open, so switching the memory storage backend to SQLite
is a prerequisite for eliminating the last-writer-wins race described in PR
#2251.

Design notes
------------

* WAL mode is enabled so readers never block and concurrent ``enqueue`` from
  different processes does not contend with the writer loop.
* Every call opens a fresh, short-lived connection; connections are never
  shared across threads or functions.  This avoids SQLite's "same thread only"
  restriction completely and lets the OS-level WAL layer manage concurrency.
* ``seq`` is both a diagnostic counter and a hard write guard.  The writer
  calls ``load()`` immediately before ``save()``; if another writer advanced
  ``seq`` in between, ``save()`` aborts rather than silently overwriting newer
  state.  This is the correctness backstop in case the single-writer lease is
  ever bypassed (e.g. a rogue migration script).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

from deerflow.agents.memory.storage import (
    MemoryStorage,
    create_empty_memory,
    utc_now_iso_z,
)
from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_memory (
    agent_name  TEXT    NOT NULL DEFAULT '__global__',
    user_id     TEXT    NOT NULL DEFAULT '__default__',
    data        TEXT    NOT NULL,
    seq         INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT    NOT NULL,
    PRIMARY KEY (agent_name, user_id)
);
"""


_GLOBAL_KEY = "__global__"
_DEFAULT_USER = "__default__"


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a WAL-mode SQLite connection that is safe to share across threads.

    Public helper — intentionally exported so companion modules (e.g. the
    single-writer queue in :mod:`deerflow.agents.memory.writer_queue`) can
    reuse the same connection semantics without depending on private names.
    """
    conn = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# Backwards-compatible private alias; kept so existing imports elsewhere in the
# module (and any external callers still on the pre-RFC #2283 API) keep working.
_connect = connect


def init_memory_schema(db_path: Path) -> None:
    """Idempotently create the agent_memory table.

    Exposed as a module-level helper so ``writer_queue.py`` can ensure the
    schema exists even when storage has not yet been instantiated in this
    process (e.g. during migrations or tests).
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


class SQLiteMemoryStorage(MemoryStorage):
    """SQLite-backed memory storage with monotonic ``seq`` guard.

    Intended for deployments that run more than one worker process.  The
    writer queue (``writer_queue.py``) ensures only one process executes the
    ``load → LLM → save`` cycle at a time, and this storage's ``seq`` check
    catches any case where that invariant is violated.

    When ``agent_name is None`` the row is stored under ``__global__`` so
    every backend file has exactly one "global" row.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = get_paths().base_dir / "memory.db"
        self._db_path = Path(db_path)
        # Tracks the seq observed at load() time, per agent key, per thread.
        # A dict keyed by (thread_ident, agent_key) is overkill in practice —
        # the writer loop runs in a single thread and processes tasks
        # sequentially — but using the thread ident keeps reload/load/save
        # sequences in different threads (e.g. the reader side) from
        # accidentally cross-contaminating the guard.
        self._last_seen_seq: dict[tuple[int, str], int] = {}
        self._lock = threading.Lock()
        init_memory_schema(self._db_path)

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------
    @property
    def db_path(self) -> Path:
        """Absolute path to the backing SQLite file."""
        return self._db_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _key(agent_name: str | None) -> str:
        return agent_name if agent_name is not None else _GLOBAL_KEY

    def _guard_key(self, agent_key: str) -> tuple[int, str]:
        return (threading.get_ident(), agent_key)

    # ------------------------------------------------------------------
    # MemoryStorage interface
    # ------------------------------------------------------------------
    def load(self, agent_name: str | None = None) -> dict[str, Any]:
        key = self._key(agent_name)
        try:
            conn = _connect(self._db_path)
            try:
                row = conn.execute(
                    "SELECT data, seq FROM agent_memory "
                    "WHERE agent_name = ? AND user_id = ?",
                    (key, _DEFAULT_USER),
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.Error as exc:  # pragma: no cover - logged and degraded
            logger.error("Failed to load memory for agent %s: %s", key, exc)
            return create_empty_memory()

        if row is None:
            # Record seq=0 so that a subsequent save() from this thread knows
            # the row did not yet exist and can proceed unconditionally.
            with self._lock:
                self._last_seen_seq[self._guard_key(key)] = 0
            return create_empty_memory()

        try:
            data = json.loads(row["data"])
        except json.JSONDecodeError as exc:
            logger.error("Corrupt memory JSON for agent %s: %s", key, exc)
            return create_empty_memory()

        with self._lock:
            self._last_seen_seq[self._guard_key(key)] = int(row["seq"])
        return data

    def reload(self, agent_name: str | None = None) -> dict[str, Any]:
        # SQLite has no in-process cache, so reload is just load.
        return self.load(agent_name)

    def save(self, memory_data: dict[str, Any], agent_name: str | None = None) -> bool:
        key = self._key(agent_name)
        now = utc_now_iso_z()
        # Shallow copy so the caller's dict is not mutated.
        payload = {**memory_data, "lastUpdated": now}

        try:
            conn = _connect(self._db_path)
        except sqlite3.Error as exc:  # pragma: no cover
            logger.error("Failed to open memory DB for agent %s: %s", key, exc)
            return False

        try:
            conn.execute("BEGIN EXCLUSIVE")
            row = conn.execute(
                "SELECT seq FROM agent_memory "
                "WHERE agent_name = ? AND user_id = ?",
                (key, _DEFAULT_USER),
            ).fetchone()
            current_seq = int(row["seq"]) if row is not None else 0

            with self._lock:
                last_seen = self._last_seen_seq.get(self._guard_key(key))

            if last_seen is not None and current_seq != last_seen:
                logger.error(
                    "Single-writer invariant violated for agent %s: "
                    "expected seq=%d, found seq=%d. Aborting write.",
                    key,
                    last_seen,
                    current_seq,
                )
                conn.rollback()
                return False

            new_seq = current_seq + 1
            conn.execute(
                """
                INSERT INTO agent_memory (agent_name, user_id, data, seq, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(agent_name, user_id) DO UPDATE SET
                    data       = excluded.data,
                    seq        = excluded.seq,
                    updated_at = excluded.updated_at
                """,
                (
                    key,
                    _DEFAULT_USER,
                    json.dumps(payload, ensure_ascii=False),
                    new_seq,
                    now,
                ),
            )
            conn.commit()
        except sqlite3.Error as exc:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            logger.error("Failed to save memory for agent %s: %s", key, exc)
            return False
        finally:
            conn.close()

        # Keep the last-seen counter consistent with what we just wrote so that
        # a subsequent save() in the same writer iteration (rare but possible
        # during multi-stage updates) does not spuriously trip the guard.
        with self._lock:
            self._last_seen_seq[self._guard_key(key)] = new_seq
        logger.info("Memory saved for agent %s (seq=%d)", key, new_seq)
        return True
