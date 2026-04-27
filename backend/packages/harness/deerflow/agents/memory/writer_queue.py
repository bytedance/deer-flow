"""Single-writer SQLite-backed memory update queue (RFC #2283).

Every worker process may ``enqueue`` conversation contexts; exactly one
process at a time dequeues them and runs the full ``load → LLM → save`` cycle.
Because only one process executes that cycle, the stale-load race that
produced last-writer-wins in PR #2251 becomes impossible by construction.

See :mod:`deerflow.agents.memory.sqlite_storage` for the companion storage
backend and RFC #2283 in the issue tracker for the full design discussion.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from deerflow.agents.memory.sqlite_storage import connect, init_memory_schema
from deerflow.agents.memory.storage import utc_now_iso_z
from deerflow.config.memory_config import get_memory_config

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────────────
# These are module-level defaults; ``MemoryConfig`` overrides them at runtime
# via :func:`_get_timings`.  Values are in seconds.
DEFAULT_LOCK_STALE_SECONDS = 90
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 30
DEFAULT_PROCESSING_TIMEOUT_SECONDS = 300


_QUEUE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memory_update_queue (
    id                     INTEGER  PRIMARY KEY AUTOINCREMENT,
    agent_name             TEXT     NOT NULL DEFAULT '__global__',
    user_id                TEXT     NOT NULL DEFAULT '__default__',
    messages               TEXT     NOT NULL,
    thread_id              TEXT,
    correction_detected    INTEGER  NOT NULL DEFAULT 0,
    reinforcement_detected INTEGER  NOT NULL DEFAULT 0,
    enqueued_at            TEXT     NOT NULL,
    status                 TEXT     NOT NULL DEFAULT 'pending',
    started_at             TEXT,
    completed_at           TEXT
);

CREATE INDEX IF NOT EXISTS idx_queue_status_id
    ON memory_update_queue (status, id);

CREATE TABLE IF NOT EXISTS memory_writer_lock (
    id           INTEGER  PRIMARY KEY DEFAULT 1,
    worker_id    TEXT     NOT NULL,
    acquired_at  TEXT     NOT NULL,
    heartbeat_at TEXT     NOT NULL
);
"""


# Process-local guard: prevents two writer threads from starting inside the
# same process (e.g. when ``flush()`` races the debounce timer).  Acquired in
# :func:`schedule_memory_update`, released inside :func:`run_writer_loop`.
_writer_running = threading.Lock()

# Per-path schema-init cache.  ``CREATE TABLE IF NOT EXISTS`` is cheap, but
# each call still opens/closes a fresh SQLite connection; caching keeps the
# hot path (``enqueue`` → ``try_acquire_writer``) from paying that cost on
# every queue event.  The cache key is the resolved absolute path so
# different DBs used in the same process are tracked independently.
_SCHEMA_INITIALISED: set[str] = set()
_SCHEMA_INIT_LOCK = threading.Lock()


# ── Internal helpers ────────────────────────────────────────────────────────
def _worker_id() -> str:
    return f"{os.getpid()}@{socket.gethostname()}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_minus_seconds(seconds: int) -> str:
    return (_utc_now() - timedelta(seconds=seconds)).isoformat().removesuffix("+00:00") + "Z"


def _parse_utc_iso(value: str) -> datetime:
    """Parse a ``utc_now_iso_z`` timestamp back into an aware UTC datetime.

    The storage helper writes values like ``2025-01-01T00:00:00.000000Z``.
    Python's ``fromisoformat`` handles the trailing ``Z`` natively on 3.11+;
    we normalise manually to stay compatible with earlier parsers that would
    otherwise return a naive datetime interpreted as local time — a subtle
    source of false lease-stale conclusions.
    """
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _get_timings() -> tuple[int, int, int]:
    """Return ``(lock_stale, heartbeat_interval, processing_timeout)`` seconds.

    Reads overrides from :class:`MemoryConfig`; falls back to module defaults
    when a field is absent (older configs that pre-date these knobs).
    Enforces ``heartbeat_interval < lock_stale / 2`` to preserve a
    stale-lease safety margin.
    """
    cfg = get_memory_config()
    lock_stale = int(getattr(cfg, "lock_stale_seconds", DEFAULT_LOCK_STALE_SECONDS))
    heartbeat = int(getattr(cfg, "heartbeat_interval_seconds", DEFAULT_HEARTBEAT_INTERVAL_SECONDS))
    processing_timeout = int(getattr(cfg, "processing_timeout_seconds", DEFAULT_PROCESSING_TIMEOUT_SECONDS))

    if heartbeat <= 0 or lock_stale <= 0 or processing_timeout <= 0:
        logger.warning(
            "Non-positive writer-queue timing (%s/%s/%s); falling back to defaults",
            heartbeat,
            lock_stale,
            processing_timeout,
        )
        return (
            DEFAULT_LOCK_STALE_SECONDS,
            DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
            DEFAULT_PROCESSING_TIMEOUT_SECONDS,
        )

    if heartbeat * 2 >= lock_stale:
        logger.warning(
            "heartbeat_interval_seconds=%d is not < lock_stale_seconds=%d / 2; clamping heartbeat to keep a safety margin",
            heartbeat,
            lock_stale,
        )
        heartbeat = max(1, lock_stale // 3)

    return lock_stale, heartbeat, processing_timeout


def init_queue_schema(db_path: Path) -> None:
    """Idempotently create the queue + lock tables (and the storage table).

    Exposed so callers that bootstrap the writer queue before ever calling
    :class:`SQLiteMemoryStorage` still get a usable ``memory.db``.  The
    companion storage schema is delegated to
    :func:`deerflow.agents.memory.sqlite_storage.init_memory_schema` so the
    queue module no longer has to know the ``agent_memory`` DDL.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    init_memory_schema(db_path)
    conn = connect(db_path)
    try:
        conn.executescript(_QUEUE_SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()
    with _SCHEMA_INIT_LOCK:
        _SCHEMA_INITIALISED.add(str(db_path.resolve()))


def _ensure_schema(db_path: Path) -> None:
    """Fast-path wrapper around :func:`init_queue_schema`.

    ``init_queue_schema`` is idempotent but opens two short-lived SQLite
    connections and runs ``CREATE TABLE IF NOT EXISTS`` scripts, which is
    measurable overhead on the hot enqueue path.  We track paths already
    initialised in this process and skip the work on subsequent calls.
    """
    key = str(db_path.resolve())
    with _SCHEMA_INIT_LOCK:
        if key in _SCHEMA_INITIALISED:
            return
    init_queue_schema(db_path)


# ── Heartbeat thread ────────────────────────────────────────────────────────
class _HeartbeatThread(threading.Thread):
    """Continuously renew the writer lease while the writer loop runs."""

    def __init__(self, db_path: Path, worker_id: str, interval_seconds: int) -> None:
        super().__init__(daemon=True, name="memory-writer-heartbeat")
        self._db_path = db_path
        self._worker_id = worker_id
        self._interval = interval_seconds
        # NOTE: must not be named ``_stop`` — that shadows ``threading.Thread._stop``
        # and breaks ``Thread.join``'s finalization path (raises TypeError at
        # the end of the thread's life).
        self._stop_event = threading.Event()

    def run(self) -> None:  # pragma: no cover - exercised indirectly
        while not self._stop_event.wait(timeout=self._interval):
            try:
                conn = connect(self._db_path)
                try:
                    conn.execute(
                        "UPDATE memory_writer_lock SET heartbeat_at = ? WHERE id = 1 AND worker_id = ?",
                        (utc_now_iso_z(), self._worker_id),
                    )
                    conn.commit()
                finally:
                    conn.close()
            except Exception:
                logger.warning(
                    "Heartbeat renewal failed; writer lease may expire",
                    exc_info=True,
                )

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=self._interval + 5)


# ── Queue operations ────────────────────────────────────────────────────────
def enqueue(
    db_path: Path,
    agent_name: str | None,
    messages: list,
    thread_id: str | None,
    correction_detected: bool = False,
    reinforcement_detected: bool = False,
) -> None:
    """Append a conversation context to the pending queue."""
    from langchain_core.messages import messages_to_dict

    _ensure_schema(db_path)
    serialised = messages_to_dict(messages) if messages else []
    name = agent_name if agent_name is not None else "__global__"

    conn = connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO memory_update_queue
                (agent_name, user_id, messages, thread_id,
                 correction_detected, reinforcement_detected,
                 enqueued_at, status)
            VALUES (?, '__default__', ?, ?, ?, ?, ?, 'pending')
            """,
            (
                name,
                json.dumps(serialised, ensure_ascii=False),
                thread_id,
                int(correction_detected),
                int(reinforcement_detected),
                utc_now_iso_z(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def reset_stuck_tasks(db_path: Path) -> int:
    """Move tasks that have been ``'processing'`` too long back to ``'pending'``."""
    _ensure_schema(db_path)
    _, _, processing_timeout = _get_timings()
    cutoff = _utc_minus_seconds(processing_timeout)
    conn = connect(db_path)
    try:
        cursor = conn.execute(
            """
            UPDATE memory_update_queue
            SET status = 'pending', started_at = NULL
            WHERE status = 'processing' AND started_at IS NOT NULL AND started_at < ?
            """,
            (cutoff,),
        )
        reset_count = cursor.rowcount or 0
        conn.commit()
    finally:
        conn.close()

    if reset_count > 0:
        logger.warning("Reset %d stuck memory tasks back to pending", reset_count)
    return reset_count


def try_acquire_writer(db_path: Path, worker_id: str) -> bool:
    """Attempt to take the single-writer lease.  Returns True on success."""
    _ensure_schema(db_path)
    lock_stale, _, _ = _get_timings()
    now = utc_now_iso_z()
    conn = connect(db_path)
    try:
        conn.execute("BEGIN EXCLUSIVE")
        row = conn.execute("SELECT worker_id, heartbeat_at FROM memory_writer_lock WHERE id = 1").fetchone()

        if row is not None:
            held_by = row["worker_id"]
            try:
                heartbeat = _parse_utc_iso(row["heartbeat_at"])
            except ValueError:
                heartbeat = _utc_now() - timedelta(seconds=lock_stale + 1)
            age = (_utc_now() - heartbeat).total_seconds()
            if held_by != worker_id and age < lock_stale:
                conn.rollback()
                return False

        conn.execute(
            """
            INSERT INTO memory_writer_lock (id, worker_id, acquired_at, heartbeat_at)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                worker_id    = excluded.worker_id,
                acquired_at  = excluded.acquired_at,
                heartbeat_at = excluded.heartbeat_at
            """,
            (worker_id, now, now),
        )
        conn.commit()
        return True
    except sqlite3.Error:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        logger.exception("Failed to acquire writer lease")
        return False
    finally:
        conn.close()


def _release_writer(db_path: Path, worker_id: str) -> None:
    try:
        conn = connect(db_path)
        try:
            conn.execute(
                "DELETE FROM memory_writer_lock WHERE id = 1 AND worker_id = ?",
                (worker_id,),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        logger.exception("Failed to release writer lease for worker %s", worker_id)


def run_writer_loop(db_path: Path, worker_id: str) -> None:
    """Consume every pending queue item, sequentially, until the queue empties.

    Always releases the writer lease and the process-local guard on exit, even
    on exception.  Designed to be invoked in a daemon thread.
    """
    from langchain_core.messages import messages_from_dict

    # Imported lazily to avoid a circular import at module load time (updater
    # imports from storage, storage imports are resolved via init, etc.).
    from deerflow.agents.memory.updater import update_memory_from_conversation

    _, heartbeat_interval, _ = _get_timings()
    heartbeat = _HeartbeatThread(db_path, worker_id, heartbeat_interval)
    heartbeat.start()

    try:
        conn = connect(db_path)
        try:
            while True:
                task = None
                try:
                    conn.execute("BEGIN EXCLUSIVE")
                    row = conn.execute(
                        """
                        SELECT id, agent_name, messages, thread_id,
                               correction_detected, reinforcement_detected
                        FROM memory_update_queue
                        WHERE status = 'pending'
                        ORDER BY id ASC LIMIT 1
                        """
                    ).fetchone()

                    if row is None:
                        conn.commit()
                        break

                    task = {
                        "id": row["id"],
                        "agent_name": row["agent_name"],
                        "messages": row["messages"],
                        "thread_id": row["thread_id"],
                        "correction_detected": bool(row["correction_detected"]),
                        "reinforcement_detected": bool(row["reinforcement_detected"]),
                    }
                    conn.execute(
                        "UPDATE memory_update_queue SET status = 'processing', started_at = ? WHERE id = ?",
                        (utc_now_iso_z(), task["id"]),
                    )
                    conn.commit()
                except sqlite3.Error:
                    try:
                        conn.rollback()
                    except sqlite3.Error:
                        pass
                    logger.exception("Failed to claim next queue item; stopping writer loop")
                    break

                # Run the load → LLM → save cycle with NO db lock held.
                try:
                    agent_name: str | None
                    agent_name = None if task["agent_name"] == "__global__" else task["agent_name"]
                    messages = messages_from_dict(json.loads(task["messages"]))
                    success = update_memory_from_conversation(
                        messages=messages,
                        thread_id=task["thread_id"],
                        agent_name=agent_name,
                        correction_detected=task["correction_detected"],
                        reinforcement_detected=task["reinforcement_detected"],
                    )
                    final_status = "done" if success else "failed"
                except Exception:
                    logger.exception("Memory update failed for queue item %d", task["id"])
                    final_status = "failed"

                try:
                    conn.execute(
                        "UPDATE memory_update_queue SET status = ?, completed_at = ? WHERE id = ?",
                        (final_status, utc_now_iso_z(), task["id"]),
                    )
                    conn.commit()
                except sqlite3.Error:
                    logger.exception(
                        "Failed to record terminal status for queue item %d",
                        task["id"],
                    )
        finally:
            conn.close()
    finally:
        heartbeat.stop()
        _release_writer(db_path, worker_id)
        # Only release the process-local guard if we actually hold it.
        if _writer_running.locked():
            try:
                _writer_running.release()
            except RuntimeError:  # pragma: no cover - defensive
                pass


def schedule_memory_updates(
    db_path: Path,
    contexts: list[dict],
) -> None:
    """Enqueue a batch of conversation contexts and, if possible, become the writer.

    Each item in *contexts* is a mapping with the keys ``agent_name``,
    ``messages``, ``thread_id`` and the optional flags
    ``correction_detected`` / ``reinforcement_detected``.  Missing flags
    default to ``False``.

    This is the preferred entry point when the debounced in-memory queue
    drains several conversation contexts in one tick (RFC #2283): the
    schema bootstrap, stuck-task reset and writer-lease acquisition each
    run exactly once per batch instead of once per queued item — the
    per-item form repeatedly opened short-lived SQLite connections for
    work that is trivially batchable.
    """
    if not contexts:
        return

    _ensure_schema(db_path)
    reset_stuck_tasks(db_path)

    for ctx in contexts:
        enqueue(
            db_path,
            ctx.get("agent_name"),
            ctx.get("messages") or [],
            ctx.get("thread_id"),
            correction_detected=bool(ctx.get("correction_detected", False)),
            reinforcement_detected=bool(ctx.get("reinforcement_detected", False)),
        )

    if not _writer_running.acquire(blocking=False):
        return  # a writer thread is already active in this process

    worker_id = _worker_id()
    if try_acquire_writer(db_path, worker_id):
        threading.Thread(
            target=run_writer_loop,
            args=(db_path, worker_id),
            daemon=True,
            name="memory-writer",
        ).start()
    else:
        # Did not become the writer; another live process owns the lease and
        # will process our enqueued tasks.  Release the in-process guard.
        try:
            _writer_running.release()
        except RuntimeError:  # pragma: no cover - defensive
            pass


def schedule_memory_update(
    db_path: Path,
    agent_name: str | None,
    messages: list,
    thread_id: str | None,
    correction_detected: bool = False,
    reinforcement_detected: bool = False,
) -> None:
    """Enqueue a single conversation context and, if possible, become the writer.

    Thin wrapper around :func:`schedule_memory_updates`.  Safe to call from
    ``threading.Timer`` callbacks: no event loop required.
    """
    schedule_memory_updates(
        db_path,
        [
            {
                "agent_name": agent_name,
                "messages": messages,
                "thread_id": thread_id,
                "correction_detected": correction_detected,
                "reinforcement_detected": reinforcement_detected,
            }
        ],
    )


def trim_queue(db_path: Path, keep_days: int = 7) -> int:
    """Delete ``done`` / ``failed`` tasks older than *keep_days*.

    Returns the number of rows deleted.  Can be called from a periodic
    maintenance job; never blocks the writer loop because each call uses its
    own short-lived connection and WAL mode permits concurrent reads.
    """
    _ensure_schema(db_path)
    if keep_days < 0:
        raise ValueError("keep_days must be non-negative")
    cutoff = _utc_minus_seconds(keep_days * 86400)
    conn = connect(db_path)
    try:
        cursor = conn.execute(
            "DELETE FROM memory_update_queue WHERE status IN ('done', 'failed') AND completed_at IS NOT NULL AND completed_at < ?",
            (cutoff,),
        )
        deleted = cursor.rowcount or 0
        conn.commit()
    finally:
        conn.close()
    return deleted


def migrate_json_to_sqlite(
    json_path: Path,
    db_path: Path,
    agent_name: str | None = None,
) -> None:
    """Import an existing ``memory.json`` (or per-agent file) into SQLite.

    Raises :class:`RuntimeError` if the import fails; the original JSON file
    is never deleted.
    """
    from deerflow.agents.memory.sqlite_storage import SQLiteMemoryStorage

    _ensure_schema(db_path)
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    storage = SQLiteMemoryStorage(db_path)
    if not storage.save(data, agent_name=agent_name):
        raise RuntimeError(f"Migration failed for {json_path}; original file unchanged")
    logger.info(
        "Migrated %s into %s (agent=%s); original file preserved",
        json_path,
        db_path,
        agent_name if agent_name is not None else "__global__",
    )


# Test hook: ``queue._process_queue`` checks ``hasattr(memory_queue_module,
# "schedule_memory_update")`` when wiring up the SQLite backend, so any future
# rename here must keep ``schedule_memory_update`` as the public entry point.
__all__ = [
    "DEFAULT_HEARTBEAT_INTERVAL_SECONDS",
    "DEFAULT_LOCK_STALE_SECONDS",
    "DEFAULT_PROCESSING_TIMEOUT_SECONDS",
    "enqueue",
    "init_queue_schema",
    "migrate_json_to_sqlite",
    "reset_stuck_tasks",
    "run_writer_loop",
    "schedule_memory_update",
    "schedule_memory_updates",
    "trim_queue",
    "try_acquire_writer",
]
