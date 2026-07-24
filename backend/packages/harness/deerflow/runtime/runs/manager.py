"""In-memory run registry with optional persistent RunStore backing."""

from __future__ import annotations

import asyncio
import logging
import socket
import sqlite3
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError as SAIntegrityError

from deerflow.runtime.user_context import AUTO, _AutoSentinel, resolve_user_id
from deerflow.utils.time import is_lease_expired
from deerflow.utils.time import now_iso as _now_iso

from .schemas import DisconnectMode, RunStatus

if TYPE_CHECKING:
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.runtime.runs.store.base import RunStore

logger = logging.getLogger(__name__)

_RETRYABLE_SQLITE_MESSAGES = (
    "database is locked",
    "database table is locked",
    "database is busy",
)

_RETRYABLE_SQLITE_ERROR_CODES = {
    sqlite3.SQLITE_BUSY,
    sqlite3.SQLITE_LOCKED,
}

# Driver-native unique-constraint signals. These are stable across driver and
# SQLAlchemy versions — message text is not (SQLite says "UNIQUE constraint
# failed", Postgres says "duplicate key value violates unique constraint").
_UNIQUE_PGCODE = "23505"
_SQLITE_UNIQUE_ERRORCODE = sqlite3.SQLITE_CONSTRAINT_UNIQUE


def _generate_worker_id() -> str:
    """Generate a unique worker identifier: ``hostname:hex_uuid``."""
    return f"{socket.gethostname()}:{uuid.uuid4().hex}"


def _is_unique_violation(exc: BaseException) -> bool:
    """Return True when *exc* (or its cause chain) is a unique-constraint violation.

    SQLAlchemy wraps the driver's IntegrityError; the wrapped driver exception is
    reachable via ``exc.orig`` (and ``__cause__`` / ``__context__``). Prefer
    driver-native signals — psycopg ``pgcode`` / ``sqlcode`` = "23505" and
    sqlite3 ``sqlite_errorcode`` = ``SQLITE_CONSTRAINT_UNIQUE`` — over message
    matching, then fall back to message substrings for cases where the driver
    exception isn't reachable through the chain.

    Message text drifts across drivers and locales (SQLite raises
    ``UNIQUE constraint failed: <table>.<index>``; Postgres raises
    ``duplicate key value violates unique constraint``), so the code/attribute
    checks are the load-bearing path.
    """
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))

        if getattr(current, "pgcode", None) == _UNIQUE_PGCODE:
            return True
        if getattr(current, "sqlcode", None) == _UNIQUE_PGCODE:
            return True
        if getattr(current, "sqlstate", None) == _UNIQUE_PGCODE:
            return True
        if getattr(current, "sqlite_errorcode", None) == _SQLITE_UNIQUE_ERRORCODE:
            return True

        # Message fallbacks are belt-and-suspenders for drivers whose
        # native code attribute isn't reachable through the chain. Gate on
        # an IntegrityError-typed node so an unrelated application
        # exception whose ``str()`` happens to contain "duplicate key" /
        # "unique" + "violat" (CHECK constraint message, validation error,
        # arbitrary subsystem string) cannot be misclassified as a unique
        # violation and silently surface as HTTP 409 instead of 500.
        if isinstance(current, (SAIntegrityError, sqlite3.IntegrityError)):
            message = str(current).lower()
            if "unique constraint failed" in message:
                return True
            if "unique" in message and "violat" in message:
                return True
            if "duplicate key" in message:
                return True

        for attr in ("orig", "__cause__", "__context__"):
            inner = getattr(current, attr, None)
            if isinstance(inner, BaseException):
                pending.append(inner)
    return False


def _is_retryable_persistence_error(exc: BaseException) -> bool:
    """Return True for transient SQLite persistence failures.

    SQLite lock contention normally surfaces through either sqlite3 exceptions
    or SQLAlchemy wrappers.  The short bounded retry here protects run status
    finalization from transient writer pressure without hiding permanent
    failures forever.
    """

    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))

        message = str(current).lower()
        if any(fragment in message for fragment in _RETRYABLE_SQLITE_MESSAGES):
            return True
        if isinstance(current, (sqlite3.OperationalError, sqlite3.DatabaseError)):
            error_code = getattr(current, "sqlite_errorcode", None)
            if error_code in _RETRYABLE_SQLITE_ERROR_CODES:
                return True
        for chained in (getattr(current, "orig", None), current.__cause__, current.__context__):
            if isinstance(chained, BaseException):
                pending.append(chained)
    return False


@dataclass(frozen=True)
class PersistenceRetryPolicy:
    """Bounded retry policy for short run-store writes."""

    max_attempts: int = 5
    initial_delay: float = 0.05
    max_delay: float = 1.0
    backoff_factor: float = 2.0


@dataclass
class RunRecord:
    """Mutable record for a single run."""

    run_id: str
    thread_id: str
    assistant_id: str | None
    status: RunStatus
    on_disconnect: DisconnectMode
    multitask_strategy: str = "reject"
    metadata: dict = field(default_factory=dict)
    kwargs: dict = field(default_factory=dict)
    user_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
    task: asyncio.Task | None = field(default=None, repr=False)
    abort_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    abort_action: str = "interrupt"
    error: str | None = None
    model_name: str | None = None
    store_only: bool = False
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    llm_call_count: int = 0
    lead_agent_tokens: int = 0
    subagent_tokens: int = 0
    middleware_tokens: int = 0
    # Per-model token breakdown
    token_usage_by_model: dict[str, dict[str, int]] = field(default_factory=dict)
    message_count: int = 0
    last_ai_message: str | None = None
    first_human_message: str | None = None
    finalizing: bool = False
    owner_worker_id: str | None = None
    lease_expires_at: str | None = None
    stop_reason: str | None = None


class RunManager:
    """In-memory run registry with optional persistent RunStore backing.

    All mutations are protected by an asyncio lock. When a ``store`` is
    provided, serializable metadata is also persisted to the store so
    that run history survives process restarts.
    """

    def __init__(
        self,
        store: RunStore | None = None,
        *,
        persistence_retry_policy: PersistenceRetryPolicy | None = None,
        worker_id: str | None = None,
        run_ownership_config: RunOwnershipConfig | None = None,
    ) -> None:
        self._runs: dict[str, RunRecord] = {}
        # Secondary index: thread_id -> insertion-ordered run_id set (a dict is
        # used as an ordered set), maintained in lockstep with ``_runs`` so
        # per-thread queries avoid O(total in-memory runs) full scans while
        # preserving ``_runs`` iteration order (see ``_thread_records_locked``).
        self._runs_by_thread: dict[str, dict[str, None]] = {}
        self._lock = asyncio.Lock()
        self._store = store
        self._persistence_retry_policy = persistence_retry_policy or PersistenceRetryPolicy()
        self._worker_id = worker_id or _generate_worker_id()
        self._run_ownership_config = run_ownership_config
        self._heartbeat_task: asyncio.Task | None = None
        self._heartbeat_stop: asyncio.Event | None = None

    def _index_run_locked(self, record: RunRecord) -> None:
        """Register *record* in the thread index. Caller must hold ``self._lock``."""
        self._runs_by_thread.setdefault(record.thread_id, {})[record.run_id] = None

    def _unindex_run_locked(self, run_id: str, thread_id: str) -> None:
        """Drop *run_id* from the thread index. Caller must hold ``self._lock``."""
        bucket = self._runs_by_thread.get(thread_id)
        if bucket is not None:
            bucket.pop(run_id, None)
            if not bucket:
                self._runs_by_thread.pop(thread_id, None)

    def _thread_records_locked(self, thread_id: str) -> list[RunRecord]:
        """Return live in-memory records for *thread_id*. Caller must hold ``self._lock``.

        Uses the ``_runs_by_thread`` index for O(runs-in-thread) lookup instead of
        scanning every in-memory run. Correctness rests on the index and ``_runs``
        being mutated in lockstep under ``self._lock`` (no ``await`` between the two
        writes), so any holder of the lock sees them agree. The ``self._runs.get``
        filter is defense-in-depth, not reconciliation: it drops a stale id still in
        the index but already gone from ``_runs``, yet it cannot recover a run that is
        in ``_runs`` but missing from the index (such a run would be silently
        omitted). It guards only that one direction, should a future refactor ever
        break the lockstep invariant.
        """
        run_ids = self._runs_by_thread.get(thread_id)
        if not run_ids:
            return []
        return [record for run_id in run_ids if (record := self._runs.get(run_id)) is not None]

    @staticmethod
    def _store_put_payload(record: RunRecord, *, error: str | None = None, stop_reason: str | None = None) -> dict[str, Any]:
        payload = {
            "thread_id": record.thread_id,
            "assistant_id": record.assistant_id,
            "status": record.status.value,
            "multitask_strategy": record.multitask_strategy,
            "metadata": record.metadata or {},
            "kwargs": record.kwargs or {},
            "error": error if error is not None else record.error,
            "created_at": record.created_at,
            "model_name": record.model_name,
            "owner_worker_id": record.owner_worker_id,
            "lease_expires_at": record.lease_expires_at,
        }
        if record.user_id is not None:
            payload["user_id"] = record.user_id
        if record.stop_reason is not None:
            payload["stop_reason"] = record.stop_reason
        return payload

    async def _call_store_with_retry(
        self,
        operation_name: str,
        run_id: str,
        operation: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Run a short store operation with bounded retries for SQLite pressure."""
        policy = self._persistence_retry_policy
        attempt = 1
        delay = policy.initial_delay
        while True:
            try:
                return await operation()
            except Exception as exc:
                retryable = _is_retryable_persistence_error(exc)
                if attempt >= policy.max_attempts or not retryable:
                    raise
                logger.warning(
                    "Transient persistence failure during %s for run %s (attempt %d/%d); retrying",
                    operation_name,
                    run_id,
                    attempt,
                    policy.max_attempts,
                    exc_info=True,
                )
                if delay > 0:
                    await asyncio.sleep(delay)
                delay = min(policy.max_delay, delay * policy.backoff_factor if delay else policy.initial_delay)
                attempt += 1

    async def _persist_snapshot_to_store(self, run_id: str, payload: dict[str, Any]) -> bool:
        """Best-effort persist a previously captured run snapshot."""
        if self._store is None:
            return True
        try:
            await self._call_store_with_retry(
                "put",
                run_id,
                lambda: self._store.put(run_id, **payload),
            )
            return True
        except Exception:
            logger.warning("Failed to persist run %s to store", run_id, exc_info=True)
            return False

    async def _persist_new_run_to_store(self, record: RunRecord) -> None:
        """Persist a newly created run record to the backing store.

        Initial run creation is part of the run visibility boundary: callers
        should not observe a run in memory unless its backing store row exists.
        Unlike follow-up status/model updates, failures are propagated so the
        caller can treat creation as failed. Rollback is the caller's
        responsibility after inserting the record into ``_runs``.
        """
        if self._store is None:
            return
        await self._call_store_with_retry(
            "put",
            record.run_id,
            lambda: self._store.put(record.run_id, **self._store_put_payload(record)),
        )

    async def _persist_to_store(self, record: RunRecord, *, error: str | None = None) -> bool:
        """Best-effort persist run record to backing store."""
        return await self._persist_snapshot_to_store(
            record.run_id,
            self._store_put_payload(record, error=error),
        )

    async def _persist_status(self, record: RunRecord, status: RunStatus, *, error: str | None = None, stop_reason: str | None = None) -> bool:
        """Best-effort persist a status transition to the backing store."""
        if self._store is None:
            return True
        row_recovery_payload = self._store_put_payload(record, error=error, stop_reason=stop_reason)
        try:
            updated = await self._call_store_with_retry(
                "update_status",
                record.run_id,
                lambda: self._store.update_status(record.run_id, status.value, error=error, stop_reason=stop_reason),
            )
            if updated is False:
                # ``update_status`` is now guarded by ``status IN ('pending','running')``.
                # False can mean either:
                #   (a) the row was never persisted (initial ``put()`` failed) → recreate.
                #   (b) the row is terminal — either a peer takeover (``error``)
                #       or a local cancel/completion race (``interrupted`` /
                #       ``success``). The log severity branches on which.
                existing = await self._store.get(record.run_id)
                if existing is not None:
                    existing_status = existing.get("status")
                    if existing_status == "error":
                        logger.warning(
                            "Run %s status update to %s skipped: store row already at error (peer takeover)",
                            record.run_id,
                            status.value,
                        )
                    else:
                        logger.info(
                            "Run %s status update to %s skipped: store row already at %s (local cancel/completion race)",
                            record.run_id,
                            status.value,
                            existing_status,
                        )
                    return False
                return await self._persist_snapshot_to_store(record.run_id, row_recovery_payload)
            return True
        except Exception:
            logger.warning("Failed to persist status update for run %s", record.run_id, exc_info=True)
            return False

    @staticmethod
    def _record_from_store(row: dict[str, Any]) -> RunRecord:
        """Build a read-only runtime record from a serialized store row.

        NULL status/on_disconnect columns (e.g. from rows written before those
        columns were added) default to ``pending`` and ``cancel`` respectively.
        """
        return RunRecord(
            run_id=row["run_id"],
            thread_id=row["thread_id"],
            assistant_id=row.get("assistant_id"),
            status=RunStatus(row.get("status") or RunStatus.pending.value),
            on_disconnect=DisconnectMode(row.get("on_disconnect") or DisconnectMode.cancel.value),
            multitask_strategy=row.get("multitask_strategy") or "reject",
            metadata=row.get("metadata") or {},
            kwargs=row.get("kwargs") or {},
            created_at=row.get("created_at") or "",
            updated_at=row.get("updated_at") or "",
            user_id=row.get("user_id"),
            error=row.get("error"),
            model_name=row.get("model_name"),
            store_only=True,
            total_input_tokens=row.get("total_input_tokens") or 0,
            total_output_tokens=row.get("total_output_tokens") or 0,
            total_tokens=row.get("total_tokens") or 0,
            llm_call_count=row.get("llm_call_count") or 0,
            lead_agent_tokens=row.get("lead_agent_tokens") or 0,
            subagent_tokens=row.get("subagent_tokens") or 0,
            middleware_tokens=row.get("middleware_tokens") or 0,
            token_usage_by_model=row.get("token_usage_by_model") or {},
            message_count=row.get("message_count") or 0,
            last_ai_message=row.get("last_ai_message"),
            first_human_message=row.get("first_human_message"),
            owner_worker_id=row.get("owner_worker_id"),
            lease_expires_at=row.get("lease_expires_at"),
            stop_reason=row.get("stop_reason"),
        )

    async def update_run_completion(self, run_id: str, **kwargs) -> None:
        """Persist token usage and completion data to the backing store."""
        row_recovery_payload: dict[str, Any] | None = None
        async with self._lock:
            record = self._runs.get(run_id)
            if record is not None:
                for key, value in kwargs.items():
                    if key == "status":
                        continue
                    if hasattr(record, key) and value is not None:
                        setattr(record, key, value)
                record.updated_at = _now_iso()
                row_recovery_payload = self._store_put_payload(record, error=kwargs.get("error"))
        if self._store is None:
            return
        try:
            updated = await self._call_store_with_retry(
                "update_run_completion",
                run_id,
                lambda: self._store.update_run_completion(run_id, **kwargs),
            )
            if updated is False:
                if row_recovery_payload is None:
                    logger.warning("Failed to recreate missing run %s for completion persistence", run_id)
                    return
                if not await self._persist_snapshot_to_store(run_id, row_recovery_payload):
                    return
                recovered = await self._call_store_with_retry(
                    "update_run_completion",
                    run_id,
                    lambda: self._store.update_run_completion(run_id, **kwargs),
                )
                if recovered is False:
                    logger.warning("Run completion update for %s affected no rows after row recreation", run_id)
        except Exception:
            logger.warning("Failed to persist run completion for %s", run_id, exc_info=True)

    async def update_run_progress(self, run_id: str, **kwargs) -> None:
        """Persist a running token/message snapshot without changing status."""
        should_persist = True
        async with self._lock:
            record = self._runs.get(run_id)
            if record is not None:
                should_persist = record.status == RunStatus.running
            if record is not None and should_persist:
                for key, value in kwargs.items():
                    if hasattr(record, key) and value is not None:
                        setattr(record, key, value)
                record.updated_at = _now_iso()
        if should_persist and self._store is not None:
            try:
                await self._store.update_run_progress(run_id, **kwargs)
            except Exception:
                logger.warning("Failed to persist run progress for %s", run_id, exc_info=True)

    async def create(
        self,
        thread_id: str,
        assistant_id: str | None = None,
        *,
        on_disconnect: DisconnectMode = DisconnectMode.cancel,
        metadata: dict | None = None,
        kwargs: dict | None = None,
        multitask_strategy: str = "reject",
        user_id: str | None = None,
    ) -> RunRecord:
        """Create a new pending run and register it.

        Note: this method assumes no active run exists for the thread. It
        persists via ``store.put`` (upsert) rather than the atomic
        ``create_run_atomic`` primitive, so a concurrent insert for the
        same thread will hit the partial unique index and surface as a
        raw ``IntegrityError`` instead of a ``ConflictError``. Production
        callers should use :meth:`create_or_reject`.
        """
        run_id = str(uuid.uuid4())
        now = _now_iso()
        lease_expires_at = self._compute_lease_expires_at()
        record = RunRecord(
            run_id=run_id,
            thread_id=thread_id,
            assistant_id=assistant_id,
            status=RunStatus.pending,
            on_disconnect=on_disconnect,
            multitask_strategy=multitask_strategy,
            metadata=metadata or {},
            kwargs=kwargs or {},
            user_id=user_id,
            created_at=now,
            updated_at=now,
            owner_worker_id=self._worker_id,
            lease_expires_at=lease_expires_at,
        )
        async with self._lock:
            self._runs[run_id] = record
            self._index_run_locked(record)
            persisted = False
            try:
                await self._persist_new_run_to_store(record)
                persisted = True
            except Exception:
                logger.warning("Failed to persist run %s; rolled back in-memory record", run_id, exc_info=True)
                raise
            finally:
                # Also covers cancellation, which bypasses ``except Exception``.
                if not persisted:
                    self._runs.pop(run_id, None)
                    self._unindex_run_locked(run_id, record.thread_id)
        logger.info("Run created: run_id=%s thread_id=%s", run_id, thread_id)
        return record

    async def get(self, run_id: str, *, user_id: str | None = None) -> RunRecord | None:
        """Return a run record by ID, or ``None``.

        Args:
            run_id: The run ID to look up.
            user_id: Optional user ID for permission filtering when hydrating from store.
        """
        async with self._lock:
            record = self._runs.get(run_id)
        if record is not None:
            return record
        if self._store is None:
            return None
        try:
            row = await self._store.get(run_id, user_id=user_id)
        except Exception:
            logger.warning("Failed to hydrate run %s from store", run_id, exc_info=True)
            return None
        # Re-check after store await: a concurrent create() may have inserted the
        # in-memory record while the store call was in flight.
        async with self._lock:
            record = self._runs.get(run_id)
        if record is not None:
            return record
        if row is None:
            return None
        try:
            return self._record_from_store(row)
        except Exception:
            logger.warning("Failed to map store row for run %s", run_id, exc_info=True)
            return None

    async def aget(self, run_id: str, *, user_id: str | None = None) -> RunRecord | None:
        """Return a run record by ID, checking the persistent store as fallback.

        Alias for :meth:`get` for backward compatibility.
        """
        return await self.get(run_id, user_id=user_id)

    async def list_by_thread(self, thread_id: str, *, user_id: str | None = None, limit: int = 100) -> list[RunRecord]:
        """Return runs for a given thread, newest first, at most ``limit`` records.

        In-memory runs take precedence only when the same ``run_id`` exists in both
        memory and the backing store. The merged result is then sorted newest-first
        by ``created_at`` and trimmed to ``limit`` (default 100).

        Args:
            thread_id: The thread ID to filter by.
            user_id: Optional user ID for permission filtering when hydrating from store.
            limit: Maximum number of runs to return.
        """
        async with self._lock:
            memory_records = self._thread_records_locked(thread_id)
        if self._store is None:
            return sorted(memory_records, key=lambda r: r.created_at, reverse=True)[:limit]
        records_by_id = {record.run_id: record for record in memory_records}
        store_limit = max(0, limit - len(memory_records))
        try:
            rows = await self._store.list_by_thread(thread_id, user_id=user_id, limit=store_limit)
        except Exception:
            logger.warning("Failed to hydrate runs for thread %s from store", thread_id, exc_info=True)
            return sorted(memory_records, key=lambda r: r.created_at, reverse=True)[:limit]
        for row in rows:
            run_id = row.get("run_id")
            if run_id and run_id not in records_by_id:
                try:
                    records_by_id[run_id] = self._record_from_store(row)
                except Exception:
                    logger.warning("Failed to map store row for run %s", run_id, exc_info=True)
        return sorted(records_by_id.values(), key=lambda record: record.created_at, reverse=True)[:limit]

    async def list_successful_regenerate_sources(
        self,
        thread_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> set[str]:
        """Return all source runs superseded by successful regenerations.

        Unlike :meth:`list_by_thread`, this query is intentionally unbounded.
        Current-process records override matching persisted status: a latest
        in-memory failure must not inherit an older successful store snapshot.
        Store failures propagate because supersession filtering is required for
        correct pagination.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="RunManager.list_successful_regenerate_sources")
        async with self._lock:
            memory_records = [record for record in self._thread_records_locked(thread_id) if resolved_user_id is None or record.user_id == resolved_user_id]

        sources = set(await self._store.list_successful_regenerate_sources(thread_id, user_id=resolved_user_id)) if self._store is not None else set()
        # _thread_records_locked preserves the insertion order of the thread
        # index. Applying records oldest-to-newest makes the latest in-memory
        # regeneration attempt authoritative when several attempts reference
        # the same source run (for example, a failed retry after a success).
        for record in memory_records:
            source = record.metadata.get("regenerate_from_run_id")
            if not isinstance(source, str) or not source:
                continue
            sources.discard(source)
            if record.status == RunStatus.success:
                sources.add(source)
        return sources

    async def get_many_by_thread(
        self,
        thread_id: str,
        run_ids: set[str],
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict[str, RunRecord]:
        """Batch-load selected thread runs with in-memory records preferred."""
        if not run_ids:
            return {}
        resolved_user_id = resolve_user_id(user_id, method_name="RunManager.get_many_by_thread")
        async with self._lock:
            records_by_id = {record.run_id: record for record in self._thread_records_locked(thread_id) if record.run_id in run_ids and (resolved_user_id is None or record.user_id == resolved_user_id)}
        if self._store is None:
            return records_by_id

        remaining = run_ids - records_by_id.keys()
        if not remaining:
            return records_by_id
        try:
            rows = await self._store.get_many_by_thread(thread_id, set(remaining), user_id=resolved_user_id)
        except Exception:
            logger.warning("Failed to batch-hydrate runs for thread %s", thread_id, exc_info=True)
            return records_by_id
        for run_id, row in rows.items():
            if run_id in records_by_id:
                continue
            try:
                records_by_id[run_id] = self._record_from_store(row)
            except Exception:
                logger.warning("Failed to map store row for run %s", run_id, exc_info=True)
        return records_by_id

    async def set_status(self, run_id: str, status: RunStatus, *, error: str | None = None, stop_reason: str | None = None) -> None:
        """Transition a run to a new status."""
        async with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                logger.warning("set_status called for unknown run %s", run_id)
                return
            record.status = status
            record.updated_at = _now_iso()
            if error is not None:
                record.error = error
            if stop_reason is not None:
                record.stop_reason = stop_reason
        await self._persist_status(record, status, error=error, stop_reason=stop_reason)
        logger.info("Run %s -> %s", run_id, status.value)

    async def set_finalizing(self, run_id: str, finalizing: bool) -> None:
        """Mark whether a run is performing post-cancel cleanup."""
        async with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                logger.warning("set_finalizing called for unknown run %s", run_id)
                return
            record.finalizing = finalizing
            record.updated_at = _now_iso()

    async def wait_for_prior_finalizing(
        self,
        thread_id: str,
        run_id: str,
        *,
        poll_interval: float = 0.01,
    ) -> None:
        """Wait until older same-thread runs have finished post-cancel cleanup."""
        while True:
            async with self._lock:
                found_current = False
                prior_finalizing = False
                for record in self._thread_records_locked(thread_id):
                    if record.run_id == run_id:
                        found_current = True
                        break
                    if record.finalizing:
                        prior_finalizing = True

                if not found_current or not prior_finalizing:
                    return

            await asyncio.sleep(poll_interval)

    async def has_later_run(self, thread_id: str, run_id: str) -> bool:
        """Return whether a newer in-memory run has been admitted for the thread."""
        async with self._lock:
            seen_current = False
            for record in self._thread_records_locked(thread_id):
                if record.run_id == run_id:
                    seen_current = True
                    continue
                if seen_current:
                    return True
        return False

    async def has_later_started_run(self, thread_id: str, run_id: str) -> bool:
        """Return whether a newer same-thread run may have already advanced state."""
        async with self._lock:
            seen_current = False
            for record in self._thread_records_locked(thread_id):
                if record.run_id == run_id:
                    seen_current = True
                    continue
                if seen_current and (record.status != RunStatus.pending or record.finalizing):
                    return True
        return False

    async def _persist_model_name(self, run_id: str, model_name: str | None) -> None:
        """Best-effort persist model_name update to the backing store."""
        if self._store is None:
            return
        try:
            await self._call_store_with_retry(
                "update_model_name",
                run_id,
                lambda: self._store.update_model_name(run_id, model_name),
            )
        except Exception:
            logger.warning("Failed to persist model_name update for run %s", run_id, exc_info=True)

    async def update_model_name(self, run_id: str, model_name: str | None) -> None:
        """Update the model name for a run."""
        async with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                logger.warning("update_model_name called for unknown run %s", run_id)
                return
            record.model_name = model_name
            record.updated_at = _now_iso()
        await self._persist_model_name(run_id, model_name)
        logger.info("Run %s model_name=%s", run_id, model_name)

    async def cancel(self, run_id: str, *, action: str = "interrupt") -> CancelOutcome:
        """Request cancellation of a run.

        When the call lands on the owning worker the run is cancelled
        locally as before (in-memory abort + status persisted to store).

        When the call lands on a non-owning worker in a multi-worker
        deployment with heartbeat enabled:

        - **Lease expired** — the run's lease has passed the grace
          threshold, so this worker takes ownership and marks it as
          ``error``.  The owning worker is assumed dead (its heartbeat
          stopped renewing).

        - **Lease still valid** — returns ``lease_valid_elsewhere`` so
          the caller can return HTTP 409 + ``Retry-After`` to tell the
          client when to retry.

        In single-worker mode (``heartbeat_enabled=False``) store-only
        hydrated runs that aren't in-memory return ``not_active_locally``,
        preserving the original 409 behaviour.

        Args:
            run_id: The run ID to cancel.
            action: ``"interrupt"`` keeps checkpoint, ``"rollback"``
                    reverts to pre-run state.

        Returns:
            A :class:`CancelOutcome` enum describing what happened.
        """
        # ------------------------------------------------------------------
        # Local path — this worker owns the run in-memory.
        # ------------------------------------------------------------------
        async with self._lock:
            record = self._runs.get(run_id)
            if record is not None:
                if record.status == RunStatus.interrupted:
                    return CancelOutcome.cancelled  # idempotent
                if record.status not in (RunStatus.pending, RunStatus.running):
                    return CancelOutcome.not_cancellable
                record.abort_action = action
                record.abort_event.set()
                task_active = record.task is not None and not record.task.done()
                record.finalizing = task_active
                if task_active:
                    record.task.cancel()
                record.status = RunStatus.interrupted
                record.updated_at = _now_iso()

        # Persist outside the lock so store calls don't block other mutations.
        if record is not None:
            persisted = await self._persist_status(record, RunStatus.interrupted)
            if not persisted and self._store is not None:
                # ``_persist_status`` already fetched ``existing`` internally;
                # re-check the store to see if a peer takeover flipped the
                # row to ``error`` between our in-memory cancel and the
                # guarded ``update_status``. If so, surface ``taken_over``
                # so the client sees a status consistent with the store.
                try:
                    existing = await self._store.get(run_id)
                except Exception:
                    existing = None
                if existing is not None and existing.get("status") == "error":
                    # The in-memory ``record.status`` is still ``interrupted``
                    # (set under the lock above) while the store row is now
                    # ``error``.  This transient staleness is harmless: the
                    # ``_persist_status`` guard prevents the late finalisation
                    # write from overwriting the takeover, and the store is the
                    # authoritative source for subsequent reads.
                    logger.info("Run %s local cancel superseded by peer takeover", run_id)
                    return CancelOutcome.taken_over
            logger.info("Run %s cancelled (action=%s)", run_id, action)
            return CancelOutcome.cancelled

        # ------------------------------------------------------------------
        # Non-local path — no in-memory record, must consult the store.
        # ------------------------------------------------------------------

        if not self.heartbeat_enabled:
            return CancelOutcome.not_active_locally

        if self._store is None:
            return CancelOutcome.unknown

        try:
            row = await self._store.get(run_id)
        except Exception:
            logger.warning("Failed to fetch run %s from store during cancel", run_id, exc_info=True)
            return CancelOutcome.unknown

        if row is None:
            return CancelOutcome.unknown

        store_status = row.get("status")
        if store_status not in ("pending", "running"):
            return CancelOutcome.not_cancellable

        grace_seconds = self.grace_seconds
        lease_expires_at: str | None = row.get("lease_expires_at")

        if not is_lease_expired(lease_expires_at, grace_seconds=grace_seconds):
            return CancelOutcome.lease_valid_elsewhere

        take_over_msg = f"Run reclaimed by worker {self._worker_id}: the owning worker ({row.get('owner_worker_id') or 'unknown'}) stopped renewing its lease and is presumed dead."
        try:
            taken = await self._call_store_with_retry(
                "claim_for_takeover",
                run_id,
                lambda: self._store.claim_for_takeover(
                    run_id,
                    grace_seconds=grace_seconds,
                    error=take_over_msg,
                ),
            )
        except Exception:
            logger.warning("Take-over claim for run %s failed with exception", run_id, exc_info=True)
            return CancelOutcome.unknown

        if taken:
            logger.warning("Run %s taken over by worker %s (action=%s)", run_id, self._worker_id, action)
            return CancelOutcome.taken_over

        # The conditional UPDATE matched 0 rows. Two causes:
        #   (a) the owner renewed the lease → lease_valid_elsewhere.
        #   (b) the row went terminal between our read and the claim
        #       (run finished, or another worker already took it over)
        #       → not_cancellable or taken_over.
        # Re-read to distinguish.
        try:
            fresh = await self._store.get(run_id)
        except Exception:
            fresh = None
        if fresh is None:
            return CancelOutcome.unknown
        fresh_status = fresh.get("status")
        if fresh_status not in ("pending", "running"):
            if fresh_status == "error":
                logger.info("Run %s takeover lost to another worker already at error", run_id)
                return CancelOutcome.taken_over
            return CancelOutcome.not_cancellable
        # Row is still active — lease must have been renewed by the owner.
        return CancelOutcome.lease_valid_elsewhere

    def _compute_lease_expires_at(self) -> str | None:
        """Return the lease expiry ISO timestamp for a freshly created run.

        Returns ``None`` when heartbeat is disabled (single-worker mode) so
        reconciliation treats crashed runs as orphans (NULL lease) and
        reclaims them immediately, preserving pre-ownership behaviour.
        Multi-worker deployments enable heartbeat, which opts in to leases.
        """
        if self._run_ownership_config is None:
            return None
        if not self._run_ownership_config.heartbeat_enabled:
            return None
        lease_seconds = self._run_ownership_config.lease_seconds
        return (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()

    async def create_or_reject(
        self,
        thread_id: str,
        assistant_id: str | None = None,
        *,
        on_disconnect: DisconnectMode = DisconnectMode.cancel,
        metadata: dict | None = None,
        kwargs: dict | None = None,
        multitask_strategy: str = "reject",
        model_name: str | None = None,
        user_id: str | None = None,
    ) -> RunRecord:
        """Atomically check for inflight runs and create a new one.

        For ``reject`` strategy, raises ``ConflictError`` if thread
        already has a pending/running run.  For ``interrupt``/``rollback``,
        cancels inflight runs before creating.

        Lock ordering invariant: the local ``self._lock`` is held across
        the local check, the store insert, and the local register, so the
        store insert can never succeed while a same-worker ConflictError
        is about to fire (which would leak a pending row in the store).
        Cross-process contention is resolved at the store level via a
        partial unique index on ``(thread_id) WHERE status IN
        ('pending','running')``.
        """
        run_id = str(uuid.uuid4())
        now = _now_iso()

        _supported_strategies = ("reject", "interrupt", "rollback")
        if multitask_strategy not in _supported_strategies:
            raise UnsupportedStrategyError(f"Multitask strategy '{multitask_strategy}' is not yet supported. Supported strategies: {', '.join(_supported_strategies)}")

        lease_expires_at = self._compute_lease_expires_at()
        grace_seconds = self._run_ownership_config.grace_seconds if self._run_ownership_config else 10

        interrupted_records: list[RunRecord] = []
        record = RunRecord(
            run_id=run_id,
            thread_id=thread_id,
            assistant_id=assistant_id,
            status=RunStatus.pending,
            on_disconnect=on_disconnect,
            multitask_strategy=multitask_strategy,
            metadata=metadata or {},
            kwargs=kwargs or {},
            user_id=user_id,
            created_at=now,
            updated_at=now,
            model_name=model_name,
            owner_worker_id=self._worker_id,
            lease_expires_at=lease_expires_at,
        )

        async with self._lock:
            # 1) Local inflight check (same-worker guard; cross-worker is the
            #    store's partial unique index below).
            local_inflight = [r for r in self._thread_records_locked(thread_id) if r.status in (RunStatus.pending, RunStatus.running) or r.finalizing]

            if multitask_strategy == "reject" and local_inflight:
                raise ConflictError(f"Thread {thread_id} already has an active run")

            if multitask_strategy in ("interrupt", "rollback") and local_inflight:
                logger.info(
                    "Preparing to cancel %d inflight run(s) on thread %s (strategy=%s)",
                    len(local_inflight),
                    thread_id,
                    multitask_strategy,
                )

            # 2) Persist to store while still holding the local lock. The
            #    store is the source of truth for cross-process atomicity.
            if self._store is not None:
                if multitask_strategy == "reject":
                    try:
                        await self._call_store_with_retry(
                            "create_run_atomic",
                            run_id,
                            lambda: self._store.create_run_atomic(
                                run_id=run_id,
                                thread_id=thread_id,
                                owner_worker_id=self._worker_id,
                                lease_expires_at=lease_expires_at,
                                multitask_strategy="reject",
                                assistant_id=assistant_id,
                                user_id=user_id,
                                model_name=model_name,
                                metadata=metadata,
                                kwargs=kwargs,
                                created_at=now,
                                grace_seconds=grace_seconds,
                            ),
                        )
                    except ConflictError:
                        raise
                    except Exception as exc:
                        if _is_unique_violation(exc):
                            raise ConflictError(f"Thread {thread_id} already has an active run") from exc
                        raise
                else:
                    # Interrupt / rollback: store-side claim + insert in one
                    # transaction. Retry on IntegrityError in case another
                    # worker races us between our SELECT FOR UPDATE and INSERT.
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            await self._call_store_with_retry(
                                "create_run_atomic",
                                run_id,
                                lambda: self._store.create_run_atomic(
                                    run_id=run_id,
                                    thread_id=thread_id,
                                    owner_worker_id=self._worker_id,
                                    lease_expires_at=lease_expires_at,
                                    multitask_strategy=multitask_strategy,
                                    assistant_id=assistant_id,
                                    user_id=user_id,
                                    model_name=model_name,
                                    metadata=metadata,
                                    kwargs=kwargs,
                                    created_at=now,
                                    grace_seconds=grace_seconds,
                                ),
                            )
                            break
                        except Exception as exc:
                            is_unique = _is_unique_violation(exc)
                            if is_unique and attempt + 1 < max_retries:
                                continue
                            if is_unique:
                                # Exhausted retries on unique violation — surface
                                # as ConflictError to match the reject branch's
                                # contract (409, not 500). Same root cause: another
                                # worker won the race for this thread.
                                raise ConflictError(f"Thread {thread_id} already has an active run") from exc
                            raise
                    # ``create_run_atomic`` already marked any claimed store
                    # rows as interrupted in the same transaction; no extra
                    # store write is needed for them.

            # 3) Only now safe to register locally — store insert succeeded.
            self._runs[run_id] = record
            self._index_run_locked(record)

            # 4) Cancel local in-memory inflight (interrupt/rollback). The
            #    store-side counterparts were already cancelled in step 2.
            if multitask_strategy in ("interrupt", "rollback"):
                for r in local_inflight:
                    if r.finalizing:
                        continue
                    r.abort_action = multitask_strategy
                    r.abort_event.set()
                    task_active = r.task is not None and not r.task.done()
                    r.finalizing = task_active
                    if task_active:
                        r.task.cancel()
                    r.status = RunStatus.interrupted
                    r.updated_at = now
                    interrupted_records.append(r)

        # Outside the lock: persist interrupted status for locally-cancelled
        # runs. Store-side claimed rows are already finalised.
        for interrupted_record in interrupted_records:
            await self._persist_status(interrupted_record, RunStatus.interrupted)

        logger.info("Run created: run_id=%s thread_id=%s", run_id, thread_id)
        return record

    async def reconcile_orphaned_inflight_runs(
        self,
        *,
        error: str,
        before: str | None = None,
    ) -> list[RunRecord]:
        """Mark persisted active runs as failed when their lease has expired.

        In multi-worker deployments (Postgres), a run owned by Worker A that
        still shows ``pending`` / ``running`` after its lease expired means
        Worker A crashed or was partitioned. This worker (B) can safely claim
        and error it out because the lease was not renewed.

        Rows with a still-valid lease are skipped — they belong to another live
        worker. Rows with a NULL lease (pre-ownership data) are reclaimed as
        well, matching the original single-worker recovery behaviour.
        """
        if self._store is None:
            return []
        grace_seconds = self._run_ownership_config.grace_seconds if self._run_ownership_config else 10
        try:
            rows = await self._call_store_with_retry(
                "list_inflight_with_expired_lease",
                "*",
                lambda: self._store.list_inflight_with_expired_lease(before=before, grace_seconds=grace_seconds),
            )
        except Exception:
            logger.warning("Failed to list orphaned inflight runs for reconciliation", exc_info=True)
            return []

        recovered: list[RunRecord] = []
        now = _now_iso()
        for row in rows:
            try:
                record = self._record_from_store(row)
            except Exception:
                logger.warning("Failed to map orphaned run row during reconciliation", exc_info=True)
                continue

            async with self._lock:
                live_record = self._runs.get(record.run_id)
                if live_record is not None and live_record.status in (RunStatus.pending, RunStatus.running):
                    # Still owned by a local task — skip
                    continue

            try:
                claimed = await self._call_store_with_retry(
                    "claim_for_takeover",
                    record.run_id,
                    lambda: self._store.claim_for_takeover(
                        record.run_id,
                        grace_seconds=grace_seconds,
                        error=error,
                    ),
                )
            except Exception:
                logger.warning("Failed to claim orphaned run %s for reconciliation", record.run_id, exc_info=True)
                continue
            if not claimed:
                logger.info(
                    "Skipped orphaned run %s recovery because the takeover claim no longer matched",
                    record.run_id,
                )
                continue
            record.status = RunStatus.error
            record.error = error
            record.updated_at = now
            recovered.append(record)

        if recovered:
            logger.warning("Recovered %d orphaned inflight run(s) as error", len(recovered))
        return recovered

    async def has_inflight(self, thread_id: str) -> bool:
        """Return ``True`` if *thread_id* has a pending or running run."""
        async with self._lock:
            return any(r.status in (RunStatus.pending, RunStatus.running) or r.finalizing for r in self._thread_records_locked(thread_id))

    async def cleanup(self, run_id: str, *, delay: float = 300) -> None:
        """Remove a run record after an optional delay."""
        if delay > 0:
            await asyncio.sleep(delay)
        async with self._lock:
            record = self._runs.pop(run_id, None)
            if record is not None:
                self._unindex_run_locked(run_id, record.thread_id)
        logger.debug("Run record %s cleaned up", run_id)

    # ------------------------------------------------------------------
    # Lease heartbeat
    # ------------------------------------------------------------------

    @property
    def worker_id(self) -> str:
        """Return this worker's unique identifier."""
        return self._worker_id

    @property
    def heartbeat_enabled(self) -> bool:
        """Return ``True`` when the heartbeat background task should run."""
        if self._run_ownership_config is None:
            return False
        return self._run_ownership_config.heartbeat_enabled

    @property
    def grace_seconds(self) -> int:
        """Return the configured grace seconds.

        All current callers are downstream of ``heartbeat_enabled``, which
        is False whenever ``_run_ownership_config`` is None.  The fallback
        matches the Pydantic model default and is defensive against future
        callers that might reach this property without that guard.
        """
        return self._run_ownership_config.grace_seconds if self._run_ownership_config else 10

    async def start_heartbeat(self) -> None:
        """Start the background lease-renewal task.

        No-op when ``heartbeat_enabled`` is ``False`` or the task is already running.
        """
        if not self.heartbeat_enabled:
            return
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            return
        self._heartbeat_stop = asyncio.Event()
        task = asyncio.create_task(self._heartbeat_loop())
        task.set_name("deerflow-run-lease-heartbeat")
        self._heartbeat_task = task
        logger.info("Run lease heartbeat started for worker %s", self._worker_id)

    async def stop_heartbeat(self) -> None:
        """Stop the background heartbeat task."""
        if self._heartbeat_stop is not None:
            self._heartbeat_stop.set()
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            try:
                await asyncio.wait_for(self._heartbeat_task, timeout=5.0)
            except TimeoutError:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass
        self._heartbeat_task = None
        self._heartbeat_stop = None
        logger.info("Run lease heartbeat stopped for worker %s", self._worker_id)

    async def _heartbeat_loop(self) -> None:
        """Periodically renew leases and reclaim orphaned runs from dead peers.

        Lease renewal runs every ``lease_seconds / 3``. Reconciliation
        (sweeping for expired leases owned by dead workers) runs every
        ``lease_seconds`` (every 3rd cycle) so orphaned runs are recovered
        without waiting for a pod restart.

        Both operations are guarded so a transient failure cannot take the
        heartbeat task down — a dead heartbeat means no lease is renewed
        again, and every active run eventually looks orphaned to peers.
        """
        if self._run_ownership_config is None or self._heartbeat_stop is None:
            return
        lease_seconds = self._run_ownership_config.lease_seconds
        interval = max(1, lease_seconds // 3)
        stop = self._heartbeat_stop
        cycle = 0

        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                break  # stop event was set
            except TimeoutError:
                pass  # interval elapsed

            cycle += 1
            try:
                await self._renew_leases()
            except Exception:
                logger.warning("Heartbeat renewal cycle failed", exc_info=True)

            # Reconcile every 3rd cycle (= every lease_seconds). Startup
            # reconciliation (in langgraph_runtime) covers the initial
            # sweep; this periodic pass catches orphans whose lease
            # expires between restarts — e.g. Worker A crashes, its
            # replacement starts before the lease expires, and the
            # startup pass skips the still-valid lease.
            if cycle % 3 == 0:
                try:
                    await self._reconcile_orphans_periodic()
                except Exception:
                    logger.warning("Periodic orphan reconciliation failed", exc_info=True)

    async def _renew_leases(self) -> None:
        """Renew the lease on every locally-owned active run."""
        if self._store is None or self._run_ownership_config is None:
            return
        lease_seconds = self._run_ownership_config.lease_seconds
        new_expiry = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()

        async with self._lock:
            # Renew any pending/running run owned by this worker unless its
            # background task has already completed. A pending run whose task
            # has not been spawned yet (``task is None``) is still live from
            # this worker's perspective — between ``create_run_atomic``
            # inserting the row and the worker layer spawning the agent task
            # there is a brief window. If we drop those records here and the
            # window stretches past ``lease_seconds`` (e.g. event-loop
            # saturation, slow checkpoint hydrate on a fresh worker), peer
            # reconciliation will reclaim the run as an orphan and mark it
            # ``error`` even though this worker still intends to execute it.
            active_runs = [(rid, record) for rid, record in self._runs.items() if record.status in (RunStatus.pending, RunStatus.running) and record.owner_worker_id == self._worker_id and (record.task is None or not record.task.done())]

        for run_id, record in active_runs:
            try:
                updated = await self._call_store_with_retry(
                    "update_lease",
                    run_id,
                    lambda: self._store.update_lease(
                        run_id,
                        owner_worker_id=self._worker_id,
                        lease_expires_at=new_expiry,
                    ),
                )
                if updated:
                    # Unsynced write is benign: ``lease_expires_at`` is the
                    # only field on an existing record this path mutates, so
                    # there is no concurrent writer to race against
                    # (``set_status`` / ``_persist_status`` touch other
                    # fields). Re-acquiring ``self._lock`` here would
                    # serialise against unrelated run mutations for no gain.
                    record.lease_expires_at = new_expiry
                else:
                    # ``update_lease`` returned False — the row was claimed
                    # by another worker (status is no longer pending/running,
                    # or ``owner_worker_id`` changed). Stop the local task so
                    # we don't waste CPU or overwrite the takeover status on
                    # finalisation.
                    logger.warning(
                        "Run %s lease renewal failed (status=%s,owner=%s) – worker likely taken over; aborting local task",
                        run_id,
                        record.status.value,
                        record.owner_worker_id,
                    )
                    record.abort_event.set()
                    task_active = record.task is not None and not record.task.done()
                    if task_active:
                        record.task.cancel()
            except Exception:
                logger.warning("Failed to renew lease for run %s", run_id, exc_info=True)

    async def _reconcile_orphans_periodic(self) -> None:
        """Sweep for expired leases owned by dead peers.

        Called from ``_heartbeat_loop`` every ``lease_seconds``. Startup
        reconciliation handles the initial sweep; this periodic pass
        catches orphans whose lease expires between restarts.
        """
        error_msg = "Run lease expired — owning worker is unreachable."
        recovered = await self.reconcile_orphaned_inflight_runs(error=error_msg)
        if recovered:
            logger.warning(
                "Periodic reconciliation recovered %d orphaned run(s) as error",
                len(recovered),
            )

    async def shutdown(self, *, timeout: float = 5.0) -> None:
        """Cancel and bounded-await all in-flight runs on process shutdown.

        Stops the lease heartbeat first so no renewal races against the drain.

        Chat runs execute in fire-and-forget background ``asyncio`` tasks that
        write checkpoints through a shared checkpointer. On shutdown the
        checkpointer's resources (e.g. the postgres connection pool owned by the
        gateway's ``AsyncExitStack``) are torn down; if a run task is still
        mid-graph at that point, langgraph's
        ``AsyncPregelLoop._checkpointer_put_after_previous`` runs its
        ``finally: await checkpointer.aput(...)`` against the closed pool. Because
        that put runs in a langgraph-internal task (not on ``run_agent``'s call
        stack), the resulting ``psycopg_pool.PoolClosed`` is not catchable by the
        worker and surfaces as an unhandled exception during ``asyncio.run()``
        shutdown (bytedance/deer-flow issue #3373).

        Draining in-flight runs *before* the checkpointer is closed lets each
        run that settles within ``timeout`` flush its final checkpoint while
        resources are still open. Only runs that do **not** settle on their own
        are marked ``interrupted`` — a run that completes (e.g. ``success``)
        during the drain keeps its real terminal status instead of being
        blanket-overwritten. The whole drain, including the trailing status
        persistence, is bounded by ``timeout`` so a run stuck in cleanup (or a
        slow store under DB pressure) cannot hang worker shutdown — the
        precondition for the signal-reentrancy deadlock guarded by
        ``app.gateway.app._SHUTDOWN_HOOK_TIMEOUT_SECONDS``. Runs still active
        after ``timeout`` are logged and may still race teardown.
        """
        await self.stop_heartbeat()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        async with self._lock:
            inflight = [record for record in self._runs.values() if record.status in (RunStatus.pending, RunStatus.running) and record.task is not None and not record.task.done()]
            for record in inflight:
                record.abort_action = "interrupt"
                record.abort_event.set()
                record.task.cancel()  # type: ignore[union-attr]  # filtered above
                # Status is decided AFTER the drain (below), not here: a run that
                # completes on its own during the drain must keep its real status.

        if not inflight:
            return

        tasks = [record.task for record in inflight]
        _, pending = await asyncio.wait(tasks, timeout=timeout)

        # Only mark/persist ``interrupted`` for runs that did not settle on their
        # own (still pending after the timeout, or ended cancelled). A run that
        # finished normally during the drain keeps the status it set for itself.
        to_persist: list[RunRecord] = []
        async with self._lock:
            for record in inflight:
                task = record.task
                if task not in pending and not task.cancelled():
                    # Completed on its own — retrieve any surfaced exception so it
                    # is not reported as "never retrieved", and keep its status.
                    task.exception()  # type: ignore[union-attr]  # done & not cancelled
                    continue
                if record.status in (RunStatus.pending, RunStatus.running):
                    record.status = RunStatus.interrupted
                    record.updated_at = _now_iso()
                to_persist.append(record)

        # Bound the trailing status persistence within the remaining budget so a
        # slow store (``_call_store_with_retry`` can back off under DB pressure)
        # cannot push shutdown past ``timeout``.
        if to_persist:
            remaining = deadline - loop.time()
            if remaining <= 0:
                logger.warning("Run drain budget exhausted before persisting %d interrupted run(s) on shutdown", len(to_persist))
            else:
                try:
                    results = await asyncio.wait_for(
                        asyncio.gather(*(self._persist_status(record, RunStatus.interrupted) for record in to_persist), return_exceptions=True),
                        timeout=remaining,
                    )
                except TimeoutError:
                    logger.warning("Run drain status persistence exceeded the %.1fs budget; %d record(s) may not be persisted", timeout, len(to_persist))
                else:
                    # ``_persist_status`` is best-effort: it catches and logs its
                    # own failures, returning ``False``. Inspect the aggregate so a
                    # partial failure is surfaced at shutdown level (with the
                    # run_id) instead of being silently swallowed by the gather.
                    for record, result in zip(to_persist, results):
                        if isinstance(result, Exception):
                            logger.warning("Unexpected error persisting interrupted status for run %s during shutdown: %r", record.run_id, result)
                        elif result is False:
                            logger.warning("Could not persist interrupted status for run %s during shutdown", record.run_id)

        if pending:
            logger.warning("Run drain exceeded %.1fs on shutdown; %d run task(s) still active and may race checkpointer teardown", timeout, len(pending))
        logger.info("Drained %d in-flight run(s) on shutdown (%d settled within %.1fs)", len(inflight), len(inflight) - len(pending), timeout)


class CancelOutcome(StrEnum):
    """Result of a :meth:`RunManager.cancel` call."""

    cancelled = "cancelled"
    taken_over = "taken_over"
    lease_valid_elsewhere = "lease_valid_elsewhere"
    not_cancellable = "not_cancellable"
    not_active_locally = "not_active_locally"
    unknown = "unknown"


class ConflictError(Exception):
    """Raised when multitask_strategy=reject and thread has inflight runs."""


class UnsupportedStrategyError(Exception):
    """Raised when a multitask_strategy value is not yet implemented."""
