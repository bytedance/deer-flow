"""In-memory run registry with optional persistent RunStore backing."""

from __future__ import annotations

import asyncio
import logging
import random
import socket
import sqlite3
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError as SAIntegrityError

from deerflow.runtime.user_context import AUTO, _AutoSentinel, resolve_user_id
from deerflow.utils.time import is_lease_expired
from deerflow.utils.time import now_iso as _now_iso

from .schemas import DisconnectMode, RunStatus, ThreadOperationKind
from .store.base import EditReplayVisibility, RunIdempotencyConflict, StatusFinalization

if TYPE_CHECKING:
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.runtime.events.store.base import RunEventStore
    from deerflow.runtime.runs.store.base import RunStore

logger = logging.getLogger(__name__)

ORPHAN_RECOVERY_STOP_REASON = "orphan_recovered"
STARTUP_ORPHAN_RECOVERY_ERROR = "Gateway restarted before this run reached a durable final state."
LEASE_ORPHAN_RECOVERY_ERROR = "Run lease expired — owning worker is unreachable."

TERMINAL_RUN_EVICTION_DELAY_SECONDS = 300.0
TERMINAL_RUN_EVICTION_RETRY_SECONDS = 60.0
TERMINAL_RUN_EVICTION_MAX_RETRY_SECONDS = 600.0
TERMINAL_RUN_EVICTION_RETRY_JITTER_RATIO = 0.2
TERMINAL_RUN_EVICTION_SHUTDOWN_TIMEOUT_SECONDS = 0.5
RUN_SHUTDOWN_CANCEL_RESOLUTION_TIMEOUT_SECONDS = 0.5
_TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.success,
        RunStatus.error,
        RunStatus.timeout,
        RunStatus.interrupted,
    }
)
_TERMINAL_RUN_STATUS_VALUES = frozenset(status.value for status in _TERMINAL_RUN_STATUSES)
_COMPLETION_COUNT_FIELDS = frozenset(
    {
        "total_input_tokens",
        "total_output_tokens",
        "total_tokens",
        "llm_call_count",
        "lead_agent_tokens",
        "subagent_tokens",
        "middleware_tokens",
        "message_count",
    }
)

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
    operation_kind: ThreadOperationKind = ThreadOperationKind.run
    multitask_strategy: str = "reject"
    metadata: dict = field(default_factory=dict)
    kwargs: dict = field(default_factory=dict)
    user_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
    task: asyncio.Task | None = field(default=None, repr=False)
    # Serializes startup if an admitted run is ever handed to more than one worker path.
    start_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    # Serializes every owner-authorized terminal snapshot mutation for this
    # run. Store CAS fences protect against peers; this lock prevents an older
    # snapshot from the same worker overwriting a newer same-status snapshot.
    terminal_persistence_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        repr=False,
    )
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
    # Startup failed before agent execution, even if the Gateway worker task
    # was already attached while strict metadata was being resolved.
    startup_failed: bool = False
    owner_worker_id: str | None = None
    lease_expires_at: str | None = None
    # Process-local fencing signal. Once set, this worker must not perform
    # further durable run/thread finalization because its lease ownership is
    # either known to be lost or could not be confirmed before expiry.
    ownership_lost: bool = False
    # True while the RunStore holds a durable row lock that serializes a
    # checkpoint mutation with takeover and replacement-run admission.
    checkpoint_mutation_fence_active: bool = False
    # Process-local proof that this worker successfully wrote the named
    # terminal status. Once a row is terminal, takeover cannot rewrite it, so
    # this proof safely bridges a transient read failure in the post-run
    # authority gate. It is cleared whenever the local status changes.
    durable_terminal_authority_status: RunStatus | None = field(
        default=None,
        repr=False,
    )
    stop_reason: str | None = None
    idempotency_key: str | None = None
    # True only on the caller that recovered an existing idempotent admission;
    # that caller must not attach a second worker to the durable run.
    idempotency_reused: bool = False


class RunStartOutcome(StrEnum):
    """Result of the pending-to-running startup barrier."""

    started = "started"
    cancelled = "cancelled"


class RunStartupError(RuntimeError):
    """Raised when durable startup cannot be resolved safely."""


OrphanRecoveryCallback = Callable[[list[RunRecord]], Awaitable[None]]


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
        event_store: RunEventStore | None = None,
        on_orphans_recovered: OrphanRecoveryCallback | None = None,
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
        self._event_store = event_store
        self._on_orphans_recovered = on_orphans_recovered
        self._heartbeat_task: asyncio.Task | None = None
        self._heartbeat_stop: asyncio.Event | None = None
        self._orphan_recovery_task: asyncio.Task[None] | None = None
        # Shutdown may need a bounded store round-trip to establish the
        # durable first-writer cancellation action before touching a worker.
        # Keep timed-out calls supervised until their callbacks observe them.
        self._shutdown_cancel_tasks: set[asyncio.Task[str | None]] = set()
        # Keying delayed eviction tasks by run ID both keeps them strongly
        # referenced and prevents duplicate timers for the same terminal run.
        self._terminal_eviction_tasks: dict[str, asyncio.Task[None]] = {}
        self._shutting_down = False

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

    def _has_local_execution_authority(self, record: RunRecord | None) -> bool:
        """Return whether *record* represents work owned by this manager.

        Store-hydrated records are read-only snapshots, even when their durable
        owner id names another live worker.  Treating one as a local run would
        let this process present the peer's owner id to fenced store methods and
        terminalize work it never executed.
        """
        return bool(record is not None and not record.store_only and not record.ownership_lost and record.owner_worker_id == self._worker_id)

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
            "operation_kind": record.operation_kind.value,
            "multitask_strategy": record.multitask_strategy,
            "metadata": record.metadata or {},
            "kwargs": record.kwargs or {},
            "error": error if error is not None else record.error,
            "created_at": record.created_at,
            "model_name": record.model_name,
            "owner_worker_id": record.owner_worker_id,
            "lease_expires_at": record.lease_expires_at,
            "idempotency_key": record.idempotency_key,
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

    async def _remember_durable_terminal_authority(
        self,
        record: RunRecord,
        status: RunStatus,
        *,
        verified_stored: dict[str, Any] | None = None,
    ) -> None:
        """Remember a successful local terminal write for read-failure fallback."""
        if status not in _TERMINAL_RUN_STATUSES:
            return
        async with self._lock:
            if (
                self._runs.get(record.run_id) is record
                and record.status == status
                and self._has_local_execution_authority(record)
                and (
                    verified_stored is None
                    or self._stored_completion_matches(
                        verified_stored,
                        self._completion_payload(record),
                    )
                )
            ):
                record.durable_terminal_authority_status = status

    async def _mutate_current_terminal_snapshot(
        self,
        record: RunRecord,
        completion_payload: dict[str, Any],
        operation: Callable[[], Awaitable[Any]],
    ) -> tuple[bool, Any]:
        """Serialize one terminal mutation and reject stale local snapshots."""
        async with record.terminal_persistence_lock:
            async with self._lock:
                current = self._runs.get(record.run_id)
                snapshot_is_current = current is record and self._has_local_execution_authority(record) and self._completion_payload(record) == completion_payload
            if not snapshot_is_current:
                logger.info(
                    "Skipped stale terminal snapshot mutation for run %s",
                    record.run_id,
                )
                return False, None
            return True, await operation()

    async def _persist_status(
        self,
        record: RunRecord,
        status: RunStatus,
        *,
        error: str | None = None,
        stop_reason: str | None = None,
        row_snapshot: dict[str, Any] | None = None,
        completion_snapshot: dict[str, Any] | None = None,
    ) -> bool:
        """Best-effort persist a status transition to the backing store."""
        if not self._has_local_execution_authority(record):
            logger.warning(
                "Skipped status update to %s for run %s without local execution authority",
                status.value,
                record.run_id,
            )
            return False
        if self._store is None:
            return True
        async with self._lock:
            if self._runs.get(record.run_id) is record and status == RunStatus.interrupted and record.abort_action == "rollback" and record.status == RunStatus.error:
                # The worker already advanced this rollback to its final error
                # state. A slower cancel() persistence call must not treat that
                # newer locally-owned terminal outcome as a peer conflict.
                return True
        if row_snapshot is None or completion_snapshot is None:
            async with self._lock:
                if self._runs.get(record.run_id) is not record:
                    return False
                row_recovery_payload = self._store_put_payload(
                    record,
                    error=error,
                    stop_reason=stop_reason,
                )
                completion_payload = self._completion_payload(record)
        else:
            row_recovery_payload = dict(row_snapshot)
            completion_payload = dict(completion_snapshot)
        # ``set_status`` releases the registry lock before durable I/O. A
        # competing cancellation/completion may mutate the shared record in
        # that gap, so pin both snapshots to the transition this call was
        # asked to persist instead of leaking a later in-memory status into an
        # earlier owner/action-fenced write.
        row_recovery_payload["status"] = status.value
        if status in _TERMINAL_RUN_STATUSES:
            completion_payload["status"] = status.value
            completion_payload["error"] = error if error is not None else completion_payload.get("error")
            completion_payload["stop_reason"] = stop_reason if stop_reason is not None else completion_payload.get("stop_reason")
            durable, stored_status = await self._ensure_terminal_completion_durable(
                record,
                local_status=status,
                completion_payload=completion_payload,
                run_payload=row_recovery_payload,
            )
            return durable and stored_status == status.value and not record.ownership_lost
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
                    if existing_status == status.value:
                        logger.info(
                            "Run %s status update to %s was already persisted",
                            record.run_id,
                            status.value,
                        )
                        return True
                    if existing_status == "error":
                        logger.warning(
                            "Run %s status update to %s skipped: store row already at error (peer takeover)",
                            record.run_id,
                            status.value,
                        )
                        if self.heartbeat_enabled and not record.store_only:
                            await self._mark_ownership_lost(
                                record,
                                reason="A peer terminalized the run before this worker could persist its outcome.",
                                require_active=False,
                            )
                    else:
                        logger.info(
                            "Run %s status update to %s skipped: store row already at %s (local cancel/completion race)",
                            record.run_id,
                            status.value,
                            existing_status,
                        )
                    return False
                if status in _TERMINAL_RUN_STATUSES:
                    recovered = await self._insert_terminal_completion_if_absent(
                        record,
                        self._completion_payload(record),
                        row_recovery_payload,
                    )
                    if recovered is None:
                        if self.heartbeat_enabled:
                            return False
                        recovered = await self._persist_snapshot_to_store(
                            record.run_id,
                            row_recovery_payload,
                        )
                else:
                    recovered = await self._persist_snapshot_to_store(
                        record.run_id,
                        row_recovery_payload,
                    )
                if recovered:
                    await self._remember_durable_terminal_authority(record, status)
                return bool(recovered)
            if updated is True or not self.heartbeat_enabled:
                await self._remember_durable_terminal_authority(record, status)
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
            operation_kind=ThreadOperationKind(row.get("operation_kind") or ThreadOperationKind.run.value),
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
            idempotency_key=row.get("idempotency_key"),
        )

    async def update_run_completion(self, run_id: str, **kwargs) -> None:
        """Persist token usage and completion data to the backing store."""
        await self._update_run_completion(run_id, **kwargs)

    async def _update_run_completion(self, run_id: str, **kwargs) -> bool:
        """Persist completion data and report whether the write is durable."""
        completion_kwargs = dict(kwargs)
        row_recovery_payload: dict[str, Any] | None = None
        terminal_completion_payload: dict[str, Any] | None = None
        terminal_status: RunStatus | None = None
        record: RunRecord | None = None
        async with self._lock:
            record = self._runs.get(run_id)
            if record is not None and record.ownership_lost:
                logger.warning("Skipped completion persistence for run %s after lease ownership was lost", run_id)
                return False
            if record is not None:
                for key, value in kwargs.items():
                    if key == "status":
                        continue
                    if hasattr(record, key) and value is not None:
                        setattr(record, key, value)
                record.updated_at = _now_iso()
                # Terminal identity is part of the completion snapshot even
                # when the caller supplies only token/message fields. This
                # closes the status-write-failed/completion-write-succeeded
                # window without a later ownerless terminal-row repair.
                completion_kwargs.setdefault("error", record.error)
                completion_kwargs.setdefault("stop_reason", record.stop_reason)
                row_recovery_payload = self._store_put_payload(
                    record,
                    error=completion_kwargs.get("error"),
                    stop_reason=completion_kwargs.get("stop_reason"),
                )
                if record.status in _TERMINAL_RUN_STATUSES and completion_kwargs.get("status") == record.status.value:
                    terminal_completion_payload = self._completion_payload(record)
                    terminal_status = record.status
        if self._store is None:
            return True
        if record is not None and terminal_status is not None and terminal_completion_payload is not None and row_recovery_payload is not None:
            durable, _ = await self._ensure_terminal_completion_durable(
                record,
                local_status=terminal_status,
                completion_payload=terminal_completion_payload,
                run_payload=row_recovery_payload,
            )
            return durable
        try:
            updated = await self._call_store_with_retry(
                "update_run_completion",
                run_id,
                lambda: self._store.update_run_completion(run_id, **completion_kwargs),
            )
            if updated is False:
                existing = await self._store.get(run_id)
                requested_status = completion_kwargs.get("status")
                if existing is not None and existing.get("status") != requested_status:
                    existing_status = existing.get("status")
                    logger.warning(
                        "Run completion update for %s skipped because store row is already at %s",
                        run_id,
                        existing_status,
                    )
                    if existing_status == "error" and record is not None and self.heartbeat_enabled:
                        await self._mark_ownership_lost(
                            record,
                            reason="A peer terminalized the run before completion data was persisted.",
                            require_active=False,
                        )
                    return existing_status not in (RunStatus.pending.value, RunStatus.running.value)
                if row_recovery_payload is None:
                    logger.warning("Failed to recreate missing run %s for completion persistence", run_id)
                    return False
                if not await self._persist_snapshot_to_store(run_id, row_recovery_payload):
                    return False
                recovered = await self._call_store_with_retry(
                    "update_run_completion",
                    run_id,
                    lambda: self._store.update_run_completion(run_id, **completion_kwargs),
                )
                if recovered is False:
                    logger.warning("Run completion update for %s affected no rows after row recreation", run_id)
                    return False
            return True
        except Exception:
            logger.warning("Failed to persist run completion for %s", run_id, exc_info=True)
            return False

    async def update_run_progress(self, run_id: str, **kwargs) -> None:
        """Persist a running token/message snapshot without changing status."""
        should_persist = True
        async with self._lock:
            record = self._runs.get(run_id)
            if record is not None:
                should_persist = record.status == RunStatus.running and not record.ownership_lost
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

    async def update_finalizing_progress(self, run_id: str, **kwargs) -> None:
        """Persist final fields while the durable row is deliberately active."""
        should_persist = False
        async with self._lock:
            record = self._runs.get(run_id)
            if record is not None and not record.ownership_lost:
                should_persist = record.status not in (RunStatus.pending, RunStatus.running)
                if should_persist:
                    for key, value in kwargs.items():
                        if hasattr(record, key) and value is not None:
                            setattr(record, key, value)
                    record.updated_at = _now_iso()
        if should_persist and self._store is not None:
            try:
                # The local status is already staged as terminal, but the store
                # row intentionally remains running until checkpoint finalization.
                await self._store.update_run_progress(run_id, **kwargs)
            except Exception:
                logger.warning("Failed to persist finalizing progress for %s", run_id, exc_info=True)

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
        ``create_thread_operation_atomic`` primitive, so a concurrent insert for the
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

    async def get(
        self,
        run_id: str,
        *,
        user_id: str | None = None,
        raise_on_store_error: bool = False,
    ) -> RunRecord | None:
        """Return a run record by ID, or ``None``.

        Args:
            run_id: The run ID to look up.
            user_id: Optional user ID for permission filtering when hydrating from store.
            raise_on_store_error: Propagate store hydration/mapping failures so
                lifecycle callers can distinguish them from a missing run.
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
            if raise_on_store_error:
                raise
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
            if raise_on_store_error:
                raise
            logger.warning("Failed to map store row for run %s", run_id, exc_info=True)
            return None

    async def aget(
        self,
        run_id: str,
        *,
        user_id: str | None = None,
        raise_on_store_error: bool = False,
    ) -> RunRecord | None:
        """Return a run record by ID, checking the persistent store as fallback.

        Alias for :meth:`get` for backward compatibility.
        """
        return await self.get(
            run_id,
            user_id=user_id,
            raise_on_store_error=raise_on_store_error,
        )

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
            memory_records = [record for record in self._thread_records_locked(thread_id) if record.operation_kind == ThreadOperationKind.run]
        if self._store is None:
            return sorted(memory_records, key=lambda r: r.created_at, reverse=True)[:limit]
        records_by_id = {record.run_id: record for record in memory_records}
        # Query enough rows to cover both the requested page and every possible
        # in-memory/store duplicate. Local records can be older than persisted
        # rows, so subtracting them from the store limit can hide the actual
        # newest run before the merge; querying only ``limit`` can still lose a
        # distinct row when that page is occupied by duplicate local records.
        store_limit = limit + len(memory_records)
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
            memory_records = [record for record in self._thread_records_locked(thread_id) if record.operation_kind == ThreadOperationKind.run and (resolved_user_id is None or record.user_id == resolved_user_id)]

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

    @staticmethod
    def _record_status_value(record: RunRecord) -> str:
        status = record.status
        return status.value if isinstance(status, RunStatus) else str(status)

    @staticmethod
    def _compute_edit_replay_visibility(records: list[RunRecord]) -> EditReplayVisibility:
        latest_attempt_by_source: dict[str, tuple[str, str]] = {}
        failed_attempts: set[str] = set()
        for record in sorted(records, key=lambda item: item.created_at):
            metadata = record.metadata or {}
            if metadata.get("replay_kind") != "edit":
                continue
            source = metadata.get("regenerate_from_run_id")
            if not isinstance(source, str) or not source:
                continue
            status = RunManager._record_status_value(record)
            latest_attempt_by_source[source] = (record.run_id, status)
            if status in {RunStatus.error.value, RunStatus.timeout.value, RunStatus.interrupted.value}:
                failed_attempts.add(record.run_id)

        hidden_sources: set[str] = set()
        for source, (_, status) in latest_attempt_by_source.items():
            if status in {RunStatus.pending.value, RunStatus.running.value, RunStatus.success.value}:
                hidden_sources.add(source)
        return EditReplayVisibility(
            hidden_source_run_ids=hidden_sources,
            hidden_attempt_run_ids=failed_attempts,
        )

    async def list_edit_replay_visibility(
        self,
        thread_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> EditReplayVisibility:
        """Return run-id visibility rules for edit-and-rerun attempts.

        Store rows cover reload/multi-worker history. Current-process records
        override the same run ids because they may have newer terminal status
        than the persisted snapshot visible when this query started.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="RunManager.list_edit_replay_visibility")
        records_by_id: dict[str, RunRecord] = {}
        if self._store is not None:
            rows = await self._store.list_edit_regenerate_runs(thread_id, user_id=resolved_user_id)
            for row in rows:
                try:
                    record = self._record_from_store(row)
                except Exception:
                    logger.warning("Failed to map edit replay run row for %s", row.get("run_id"), exc_info=True)
                    continue
                records_by_id[record.run_id] = record

        async with self._lock:
            memory_records = [record for record in self._thread_records_locked(thread_id) if resolved_user_id is None or record.user_id == resolved_user_id]
        for record in memory_records:
            records_by_id[record.run_id] = record

        return self._compute_edit_replay_visibility(list(records_by_id.values()))

    async def try_start(self, run_id: str) -> RunStartOutcome:
        """Transition an uncancelled pending run to running before building the agent."""
        async with self._lock:
            record = self._runs.get(run_id)
        if not self._has_local_execution_authority(record):
            raise RunStartupError(f"Cannot start unknown run {run_id}")

        async with record.start_lock:
            async with self._lock:
                if record.abort_event.is_set() or record.status != RunStatus.pending:
                    return RunStartOutcome.cancelled

            if self._store is not None:
                try:
                    updated = await self._call_store_with_retry(
                        "start_run",
                        run_id,
                        lambda: self._store.start_run(run_id),
                    )
                except Exception as exc:
                    raise RunStartupError(f"Failed to start run {run_id}: {exc}") from exc
                if updated is False:
                    async with self._lock:
                        if record.status == RunStatus.pending:
                            record.status = RunStatus.interrupted
                            record.abort_event.set()
                            record.updated_at = _now_iso()
                    return RunStartOutcome.cancelled

            async with self._lock:
                if record.abort_event.is_set() or record.status != RunStatus.pending:
                    restore_status = record.status
                    restore_error = record.error
                    restore_stop_reason = record.stop_reason
                else:
                    record.status = RunStatus.running
                    record.updated_at = _now_iso()
                    logger.info("Run %s -> %s", run_id, RunStatus.running.value)
                    return RunStartOutcome.started

            if self._store is not None:
                await self._persist_status(
                    record,
                    restore_status,
                    error=restore_error,
                    stop_reason=restore_stop_reason,
                )
            return RunStartOutcome.cancelled

    async def fail_start_if_pending(self, run_id: str, *, error: str) -> bool:
        """Mark an admitted run as failed if its worker task could not be attached."""
        async with self._lock:
            record = self._runs.get(run_id)
            if not self._has_local_execution_authority(record) or record.status != RunStatus.pending:
                return False
            record.status = RunStatus.error
            record.error = error
            record.abort_event.set()
            record.startup_failed = True
            record.updated_at = _now_iso()

        # No worker task exists to reach run_agent's normal terminal cleanup.
        # Register the supervisor before the first store await so heartbeat
        # keeps the lease alive even if persistence blocks or this coroutine
        # is cancelled midway through the attach-failure path.
        self.schedule_terminal_eviction(run_id)
        persisted = await self._persist_status(
            record,
            RunStatus.error,
            error=error,
        )
        if not persisted and self.heartbeat_enabled and self._store is not None:
            try:
                stored = await self._store.get(
                    run_id,
                    user_id=record.user_id,
                )
            except Exception:
                stored = None
            cancel_action = self._owned_durable_cancel_action(
                record,
                stored,
                require_live_active_lease=True,
            )
            if cancel_action is not None:
                await self._adopt_unstarted_durable_cancel(
                    record,
                    action=cancel_action,
                )
        return True

    async def _adopt_unstarted_durable_cancel(
        self,
        record: RunRecord,
        *,
        action: str,
    ) -> bool:
        """Converge a durable cancel after startup failed before agent execution."""
        if action not in ("interrupt", "rollback"):
            return False
        async with self._lock:
            if (
                self._runs.get(record.run_id) is not record
                or not self._has_local_execution_authority(record)
                or not record.startup_failed
                or record.status not in _TERMINAL_RUN_STATUSES
                or record.durable_terminal_authority_status == record.status
            ):
                return False
            record.abort_action = action
            record.abort_event.set()
            record.status = RunStatus.interrupted if action == "interrupt" else RunStatus.error
            record.error = None if action == "interrupt" else "Rolled back by user"
            record.updated_at = _now_iso()
        await self.persist_current_status(record.run_id)
        return True

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
            records_by_id = {
                record.run_id: record for record in self._thread_records_locked(thread_id) if record.operation_kind == ThreadOperationKind.run and record.run_id in run_ids and (resolved_user_id is None or record.user_id == resolved_user_id)
            }
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

    async def set_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        error: str | None = None,
        stop_reason: str | None = None,
        persist: bool = True,
    ) -> None:
        """Transition a run to a new status."""
        async with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                logger.warning("set_status called for unknown run %s", run_id)
                return
            if not self._has_local_execution_authority(record):
                logger.warning(
                    "Skipped local status transition to %s for run %s without execution authority",
                    status.value,
                    run_id,
                )
                return
            if record.durable_terminal_authority_status != status:
                record.durable_terminal_authority_status = None
            record.status = status
            record.updated_at = _now_iso()
            if error is not None:
                record.error = error
            if stop_reason is not None:
                record.stop_reason = stop_reason
            row_snapshot = self._store_put_payload(
                record,
                error=record.error,
                stop_reason=record.stop_reason,
            )
            completion_snapshot = self._completion_payload(record)
        if persist:
            persisted = await self._persist_status(
                record,
                status,
                error=error,
                stop_reason=stop_reason,
                row_snapshot=row_snapshot,
                completion_snapshot=completion_snapshot,
            )
            if not persisted and self.heartbeat_enabled and status == RunStatus.success and not record.ownership_lost:
                await self._mark_ownership_lost(
                    record,
                    reason="Successful completion could not be confirmed in the durable run store.",
                    require_active=False,
                )
        if record.ownership_lost:
            return
        logger.info("Run %s -> %s", run_id, status.value)

    async def persist_current_status(self, run_id: str) -> bool:
        """Persist the status already staged on the in-memory run record."""
        async with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                logger.warning("persist_current_status called for unknown run %s", run_id)
                return False
            if not self._has_local_execution_authority(record):
                logger.warning(
                    "persist_current_status skipped for run %s without execution authority",
                    run_id,
                )
                return False
            status = record.status
            error = record.error
            stop_reason = record.stop_reason
            row_snapshot = self._store_put_payload(
                record,
                error=error,
                stop_reason=stop_reason,
            )
            completion_snapshot = self._completion_payload(record)
        persisted = await self._persist_status(
            record,
            status,
            error=error,
            stop_reason=stop_reason,
            row_snapshot=row_snapshot,
            completion_snapshot=completion_snapshot,
        )
        if not persisted and self.heartbeat_enabled and status == RunStatus.success and not record.ownership_lost:
            await self._mark_ownership_lost(
                record,
                reason="Successful completion could not be confirmed in the durable run store.",
                require_active=False,
            )
        return persisted

    async def verify_terminal_authority(self, run_id: str) -> bool:
        """Converge and confirm this worker's durable terminal outcome.

        This gate runs before post-run side effects even when no event journal
        exists. It first attempts the same owner-fenced full-snapshot repair as
        terminal eviction, so an interrupted rollback intermediate cannot make
        lifecycle callbacks disappear. If durability is still incomplete, a
        final read-only authority check may allow the locally-owned outcome
        while the supervised eviction task continues repairing convenience
        fields.
        """
        async with self._lock:
            record = self._runs.get(run_id)
            if record is None or record.ownership_lost:
                return False
            local_status = record.status
            if local_status not in _TERMINAL_RUN_STATUSES:
                return False
            completion_payload = self._completion_payload(record)
            run_payload = self._store_put_payload(
                record,
                error=record.error,
                stop_reason=record.stop_reason,
            )
        if self._store is None:
            return True

        durable, stored_status = await self._ensure_terminal_completion_durable(
            record,
            local_status=local_status,
            completion_payload=completion_payload,
            run_payload=run_payload,
        )
        if not durable and not record.ownership_lost:
            # The worker is about to make one-shot lifecycle side effects.
            # Give a just-failed final CAS one immediate convergence retry so
            # a transient response/store failure does not defer durability to
            # the five-minute eviction supervisor and permanently suppress
            # scheduler completion bookkeeping.
            await asyncio.sleep(0)
            durable, stored_status = await self._ensure_terminal_completion_durable(
                record,
                local_status=local_status,
                completion_payload=completion_payload,
                run_payload=run_payload,
            )
        if durable:
            async with self._lock:
                return self._runs.get(run_id) is record and not record.ownership_lost and record.status == local_status and stored_status == local_status.value and record.durable_terminal_authority_status == local_status

        try:
            stored = await self._call_store_with_retry(
                "verify terminal authority",
                run_id,
                lambda: self._store.get(run_id, user_id=record.user_id),
            )
        except Exception:
            async with self._lock:
                locally_confirmed = self._runs.get(run_id) is record and not record.ownership_lost and record.status == local_status and record.durable_terminal_authority_status == local_status
            if locally_confirmed:
                logger.warning(
                    "Failed to re-read terminal authority for run %s; using the locally confirmed %s write",
                    run_id,
                    local_status.value,
                    exc_info=True,
                )
                return True
            logger.warning(
                "Failed to verify terminal authority for run %s; skipping local post-run side effects",
                run_id,
                exc_info=True,
            )
            return False

        stored_status = stored.get("status") if stored is not None else None
        if stored_status not in _TERMINAL_RUN_STATUS_VALUES:
            logger.warning(
                "Run %s has no durable terminal authority (stored status=%s); skipping local post-run side effects",
                run_id,
                stored_status or "missing",
            )
            return False
        if self._stored_cancelled_transition_is_repairable(
            record,
            stored,
            local_status,
        ):
            logger.warning(
                "Run %s still has an owned rollback intermediate; skipping local post-run side effects until repair",
                run_id,
            )
            return False
        if stored_status != local_status.value:
            await self._fence_terminal_authority_loss(
                record,
                reason=(f"Durable terminal outcome {stored_status} superseded the local {local_status.value} outcome."),
                expected_status=local_status,
            )
            return False
        if not self._stored_terminal_cancel_identity_matches(
            record,
            stored,
            local_status,
        ):
            await self._fence_terminal_authority_loss(
                record,
                reason=("The durable cancellation identity does not match the local terminal outcome."),
                expected_status=local_status,
            )
            return False
        if self.heartbeat_enabled and not self._stored_terminal_authority_is_local(
            record,
            stored,
        ):
            await self._fence_terminal_authority_loss(
                record,
                reason=(f"Worker {stored.get('owner_worker_id') if stored is not None else None} owns the durable {stored_status} terminal snapshot."),
                expected_status=local_status,
            )
            return False
        await self._remember_durable_terminal_authority(record, local_status)
        return True

    async def set_status_if_not_cancelled(
        self,
        run_id: str,
        status: RunStatus,
        *,
        error: str | None = None,
        stop_reason: str | None = None,
        persist: bool = True,
    ) -> str | None:
        """Set a terminal status unless a durable cancellation won first."""
        async with self._lock:
            record = self._runs.get(run_id)
            if not self._has_local_execution_authority(record):
                logger.warning(
                    "set_status_if_not_cancelled skipped for run %s without execution authority",
                    run_id,
                )
                return None
        if not persist or not self.heartbeat_enabled or self._store is None:
            await self.set_status(
                run_id,
                status,
                error=error,
                stop_reason=stop_reason,
                persist=persist,
            )
            return None

        # Stage the local result first so the heartbeat keeps renewing the
        # still-active durable row until the owner/lease-fenced CAS commits.
        await self.set_status(
            run_id,
            status,
            error=error,
            stop_reason=stop_reason,
            persist=False,
        )
        async with self._lock:
            record = self._runs.get(run_id)
            if not self._has_local_execution_authority(record):
                return None
            completion_payload = self._completion_payload(record)
            run_payload = self._store_put_payload(
                record,
                error=record.error,
                stop_reason=record.stop_reason,
            )

        finalize = getattr(
            self._store,
            "finalize_completion_if_owned_and_not_cancelled",
            None,
        )
        try:
            if finalize is None:
                raise RuntimeError("RunStore does not support owner-fenced terminal finalization")
            invoked, result = await self._mutate_current_terminal_snapshot(
                record,
                completion_payload,
                lambda: self._call_store_with_retry(
                    "owner-fenced terminal finalization",
                    run_id,
                    lambda: finalize(
                        run_id,
                        expected_owner_worker_id=self._worker_id,
                        require_unexpired_lease=True,
                        **completion_payload,
                    ),
                ),
            )
            if not invoked:
                return None
        except Exception:
            logger.warning(
                "Owner-fenced terminal finalization for run %s returned an unknown outcome; reconciling before fencing",
                run_id,
                exc_info=True,
            )
            durable, stored_status = await self._ensure_terminal_completion_durable(
                record,
                local_status=status,
                completion_payload=completion_payload,
                run_payload=run_payload,
            )
            if durable and stored_status == status.value and not record.ownership_lost:
                return None
            try:
                stored = await self._store.get(run_id, user_id=record.user_id)
            except Exception:
                stored = None
            cancel_action = self._owned_durable_cancel_action(
                record,
                stored,
                require_live_active_lease=True,
            )
            if cancel_action is not None:
                async with self._lock:
                    if self._runs.get(run_id) is record and not record.ownership_lost:
                        record.abort_action = cancel_action
                        record.abort_event.set()
                return cancel_action
            if not record.ownership_lost:
                await self._fence_terminal_authority_loss(
                    record,
                    reason=("The durable store could not confirm whether cancellation or completion won."),
                    expected_status=status,
                )
            return None

        if not isinstance(result, StatusFinalization):
            await self._fence_terminal_authority_loss(
                record,
                reason="RunStore did not return a valid owner-fenced finalization result.",
                expected_status=status,
            )
            return None
        if result.cancel_action is not None:
            if result.cancel_action not in ("interrupt", "rollback"):
                await self._fence_terminal_authority_loss(
                    record,
                    reason="RunStore returned an invalid durable cancellation action.",
                    expected_status=status,
                )
                return None
            async with self._lock:
                if self._runs.get(run_id) is record and not record.ownership_lost:
                    record.abort_action = result.cancel_action
                    record.abort_event.set()
            return result.cancel_action

        if result.finalized:
            if result.durable_write_confirmed:
                await self._remember_durable_terminal_authority(record, status)
                return None
            if await self.verify_terminal_authority(run_id):
                return None
        else:
            # Missing rows can still be recovered by atomic insert; a CAS miss
            # against a peer/expired lease is fenced by the same convergence
            # gate without ever falling back to ownerless ``update_status``.
            durable, stored_status = await self._ensure_terminal_completion_durable(
                record,
                local_status=status,
                completion_payload=completion_payload,
                run_payload=run_payload,
            )
            if durable and stored_status == status.value and not record.ownership_lost:
                return None

        if not record.ownership_lost:
            await self._fence_terminal_authority_loss(
                record,
                reason="The owner-fenced terminal finalization could not be confirmed.",
                expected_status=status,
            )
        return None

    async def _ensure_delivery_receipt(self, record: RunRecord) -> bool:
        """Idempotently persist a zero-delivery receipt during recovery."""
        if self._event_store is None:
            return True
        try:
            await self._event_store.put_if_absent(
                thread_id=record.thread_id,
                run_id=record.run_id,
                event_type="run.delivery",
                category="outputs",
                content={"presented": 0, "paths": [], "by_tool": {}},
            )
            return True
        except Exception:
            logger.warning(
                "Failed to backfill delivery receipt for recovered run %s; preserving its terminal status",
                record.run_id,
                exc_info=True,
            )
            return False

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
        abort_event: asyncio.Event | None = None,
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

            if abort_event is None:
                await asyncio.sleep(poll_interval)
                continue
            try:
                await asyncio.wait_for(abort_event.wait(), timeout=poll_interval)
            except TimeoutError:
                continue
            return

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

    async def _request_durable_cancel(
        self,
        run_id: str,
        *,
        action: str,
    ) -> tuple[CancelOutcome, str | None]:
        """Record cancellation and return the first action that won."""
        if self._store is None:
            return CancelOutcome.unknown, None
        try:
            winning_action = await self._call_store_with_retry(
                "request_cancel",
                run_id,
                lambda: self._store.request_cancel(run_id, action=action),
            )
        except NotImplementedError:
            # Keep third-party stores that predate durable cancellation on the
            # old safe behavior instead of pretending the owner was notified.
            logger.info(
                "Run store does not support cross-worker cancellation for run %s",
                run_id,
            )
            return CancelOutcome.lease_valid_elsewhere, None
        except Exception:
            logger.warning(
                "Failed to persist cancellation request for run %s",
                run_id,
                exc_info=True,
            )
            # The store may have committed the first cancellation action and
            # then lost the response.  Re-read before falling back to the
            # caller's action: executing rollback locally after a durable
            # interrupt won would violate the first-writer-wins contract even
            # though the later terminal CAS correctly refuses to overwrite
            # the row.
            try:
                fresh = await self._store.get(run_id)
            except Exception:
                fresh = None
            if fresh is not None:
                fresh_status = fresh.get("status")
                winning_action = fresh.get("cancel_action")
                if fresh_status in (RunStatus.pending.value, RunStatus.running.value) and winning_action in ("interrupt", "rollback"):
                    logger.info(
                        "Run %s cancellation response was lost; adopting durable winner %s",
                        run_id,
                        winning_action,
                    )
                    return CancelOutcome.requested, winning_action
                if fresh_status not in (RunStatus.pending.value, RunStatus.running.value):
                    return CancelOutcome.not_cancellable, None
            return CancelOutcome.unknown, None

        if winning_action is not None:
            logger.info(
                "Run %s cancellation requested (requested=%s,winner=%s)",
                run_id,
                action,
                winning_action,
            )
            return CancelOutcome.requested, winning_action

        # Completion may have won the race between the caller's read and the
        # guarded cancellation UPDATE. Re-read so the API reports that precise
        # terminal result rather than claiming the request was accepted.
        try:
            fresh = await self._store.get(run_id)
        except Exception:
            fresh = None
        if fresh is None:
            return CancelOutcome.unknown, None
        if fresh.get("status") not in ("pending", "running"):
            return CancelOutcome.not_cancellable, None
        # A legacy/partial store implementation may decline the request while
        # the owner is still live. Preserve the former lease-conflict signal.
        return CancelOutcome.lease_valid_elsewhere, None

    async def _request_remote_cancel(
        self,
        run_id: str,
        *,
        action: str,
    ) -> CancelOutcome:
        """Record cancellation for a run whose task belongs to another worker."""
        outcome, _ = await self._request_durable_cancel(
            run_id,
            action=action,
        )
        return outcome

    async def _signal_local_cancel(
        self,
        run_id: str,
        *,
        action: str,
    ) -> bool:
        """Set process-local abort state without status persistence or cleanup."""
        async with self._lock:
            record = self._runs.get(run_id)
            if not self._has_local_execution_authority(record):
                return False
            if record.abort_event.is_set():
                return True
            task_active = record.task is not None and not record.task.done()
            active_or_staged_terminal = record.status in (
                RunStatus.pending,
                RunStatus.running,
            ) or (record.status in _TERMINAL_RUN_STATUSES and record.durable_terminal_authority_status != record.status and task_active)
            if not active_or_staged_terminal:
                return False

            record.abort_action = action
            record.abort_event.set()
            record.finalizing = task_active
            # Running work is interrupted through the outer worker's
            # CancelledError handler. A staged terminal result is already in
            # run_agent's ``finally`` block; cancelling that task there would
            # skip the remaining durability/END/eviction cleanup. It observes
            # the event at the late-cancellation gate before terminal CAS.
            if task_active and record.status == RunStatus.running:
                record.task.cancel()
        logger.info("Run %s cancellation signalled locally (action=%s)", run_id, action)
        return True

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

        - **Lease still valid** — durably records the cancellation action.
          The owner observes it on its next heartbeat and performs the same
          local abort/finalization path as a directly-routed request.

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
            if not self._has_local_execution_authority(record):
                record = None
            if record is not None:
                if record.status == RunStatus.interrupted:
                    return CancelOutcome.cancelled  # idempotent
                if record.status not in (RunStatus.pending, RunStatus.running) and (not self.heartbeat_enabled or self._store is None):
                    return CancelOutcome.not_cancellable

        durable_cancel_won = False
        if record is not None and self.heartbeat_enabled and self._store is not None:
            outcome, winning_action = await self._request_durable_cancel(
                run_id,
                action=action,
            )
            if outcome == CancelOutcome.requested:
                # A durable action alone is not execution authority. Confirm
                # that this local worker still owns a live lease before
                # signalling or running a destructive rollback. request_cancel
                # may succeed after the lease expired, and legacy stores may
                # report an action without any owner fence.
                try:
                    durable_row = await self._store.get(
                        run_id,
                        user_id=record.user_id,
                    )
                except Exception:
                    durable_row = None
                confirmed_action = self._owned_durable_cancel_action(
                    record,
                    durable_row,
                    require_live_active_lease=True,
                )
                if confirmed_action is None:
                    if durable_row is not None and durable_row.get("status") in (
                        RunStatus.pending.value,
                        RunStatus.running.value,
                    ):
                        await self._mark_ownership_lost(
                            record,
                            reason=("Local cancellation could not confirm a live owned lease after the durable request."),
                        )
                    logger.warning(
                        "Deferring local cancellation for run %s because its owner/lease authority could not be confirmed",
                        run_id,
                    )
                    return CancelOutcome.unknown
                action = confirmed_action
                durable_cancel_won = True
            elif outcome == CancelOutcome.unknown:
                logger.warning(
                    "Deferring local cancellation for run %s because the durable winning action could not be confirmed",
                    run_id,
                )
                # A timeout/error can happen after the store committed.  Do
                # not execute the caller's action locally while the durable
                # first-writer winner is unknown: in particular, a rollback
                # here could destroy work after an interrupt already won.
                # The heartbeat will observe and apply a committed action; if
                # nothing committed, the caller can safely retry.
                return CancelOutcome.unknown
            else:
                return outcome

        staged_terminal_cancel = False
        terminal_cancel_without_worker = False
        cancel_status_to_persist: RunStatus | None = None
        async with self._lock:
            record = self._runs.get(run_id)
            if not self._has_local_execution_authority(record):
                record = None
            if record is not None:
                if record.status == RunStatus.interrupted or record.abort_event.is_set():
                    return CancelOutcome.cancelled
                if record.status not in (RunStatus.pending, RunStatus.running):
                    task_active = record.task is not None and not record.task.done()
                    if durable_cancel_won and record.status in _TERMINAL_RUN_STATUSES and record.durable_terminal_authority_status != record.status:
                        if task_active:
                            record.abort_action = action
                            record.abort_event.set()
                            record.finalizing = True
                            staged_terminal_cancel = True
                        else:
                            terminal_cancel_without_worker = True
                    else:
                        return CancelOutcome.cancelled if durable_cancel_won else CancelOutcome.not_cancellable
                if staged_terminal_cancel or terminal_cancel_without_worker:
                    pass
                else:
                    was_running = record.status == RunStatus.running
                    record.abort_action = action
                    record.abort_event.set()
                    task_active = record.task is not None and not record.task.done()
                    record.finalizing = task_active
                    if task_active and was_running:
                        record.task.cancel()
                    if action == "rollback" and not was_running:
                        # No agent work has started, so there is no checkpoint
                        # mutation to undo. Persist the final rollback outcome
                        # directly instead of creating an interrupted
                        # intermediate with no worker able to advance it.
                        record.status = RunStatus.error
                        record.error = "Rolled back by user"
                        cancel_status_to_persist = RunStatus.error
                    else:
                        record.status = RunStatus.interrupted
                        # A running rollback must keep the durable row active
                        # until checkpoint restoration completes. Releasing
                        # the cross-worker admission fence first would let a
                        # new run write checkpoints that this stale rollback
                        # then rewinds.
                        cancel_status_to_persist = None if action == "rollback" else RunStatus.interrupted
                    record.updated_at = _now_iso()

        if staged_terminal_cancel:
            logger.info(
                "Run %s cancellation won while terminal finalization was staged (action=%s)",
                run_id,
                action,
            )
            return CancelOutcome.cancelled
        if terminal_cancel_without_worker and record is not None:
            await self._fence_terminal_authority_loss(
                record,
                reason=("A durable cancellation won after the local worker had already returned."),
            )
            return CancelOutcome.cancelled

        # Persist outside the lock so store calls don't block other mutations.
        if record is not None:
            if cancel_status_to_persist is None:
                logger.info(
                    "Run %s rollback cancellation staged pending checkpoint restoration",
                    run_id,
                )
                return CancelOutcome.cancelled
            persisted = await self._persist_status(
                record,
                cancel_status_to_persist,
                error=record.error,
            )
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
                    if existing.get("owner_worker_id") == self._worker_id and existing.get("cancel_action") == "rollback" and record.abort_action == "rollback":
                        logger.info(
                            "Run %s rollback completed locally before the interrupt marker persisted",
                            run_id,
                        )
                        return CancelOutcome.cancelled
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

        if durable_cancel_won:
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
        if store_status == "interrupted":
            return CancelOutcome.requested
        if store_status not in ("pending", "running"):
            return CancelOutcome.not_cancellable

        grace_seconds = self.grace_seconds
        lease_expires_at: str | None = row.get("lease_expires_at")

        if not is_lease_expired(lease_expires_at, grace_seconds=grace_seconds):
            return await self._request_remote_cancel(run_id, action=action)

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
        #   (a) the owner renewed the lease → persist a cancellation request.
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
        # Row is still active — lease was renewed by the owner while the
        # takeover raced. Notify that owner instead of exposing routing as 409.
        return await self._request_remote_cancel(run_id, action=action)

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
        idempotency_key: str | None = None,
    ) -> RunRecord:
        """Atomically admit a normal agent run for a thread."""
        return await self._admit_thread_operation(
            thread_id,
            assistant_id,
            operation_kind=ThreadOperationKind.run,
            on_disconnect=on_disconnect,
            metadata=metadata,
            kwargs=kwargs,
            multitask_strategy=multitask_strategy,
            model_name=model_name,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )

    async def _close_cancelled_admission(self, record: RunRecord) -> None:
        """Terminalize an unseen replacement and confirm its durable state."""
        await self.cancel(record.run_id)
        if self._store is None:
            return

        stored = await self._call_store_with_retry(
            "verify cancelled admission",
            record.run_id,
            lambda: self._store.get(record.run_id, user_id=record.user_id),
        )
        active_statuses = (RunStatus.pending.value, RunStatus.running.value)
        if stored is not None and stored.get("status") in active_statuses:
            # `_persist_status` is deliberately best-effort. This compensation
            # path needs a strict second CAS attempt because the caller never
            # receives the record and no worker can attach after it returns.
            # A peer terminal transition wins the CAS and is preserved below.
            await self._call_store_with_retry(
                "terminalize cancelled admission",
                record.run_id,
                lambda: self._store.update_status(record.run_id, RunStatus.interrupted.value),
            )
            stored = await self._call_store_with_retry(
                "verify terminal cancelled admission",
                record.run_id,
                lambda: self._store.get(record.run_id, user_id=record.user_id),
            )
            if stored is not None and stored.get("status") in active_statuses:
                raise RuntimeError(f"Cancelled admission {record.run_id} remains active in the run store")

        if stored is None:
            async with self._lock:
                if self._runs.get(record.run_id) is record:
                    self._runs.pop(record.run_id, None)
                    self._unindex_run_locked(record.run_id, record.thread_id)
            return

        stored_status = RunStatus(stored.get("status") or RunStatus.pending.value)
        async with self._lock:
            if self._runs.get(record.run_id) is record:
                record.status = stored_status
                record.error = stored.get("error")
                record.stop_reason = stored.get("stop_reason")
                record.updated_at = _now_iso()

    async def _admit_thread_operation(
        self,
        thread_id: str,
        assistant_id: str | None = None,
        *,
        operation_kind: ThreadOperationKind,
        on_disconnect: DisconnectMode = DisconnectMode.cancel,
        metadata: dict | None = None,
        kwargs: dict | None = None,
        multitask_strategy: str = "reject",
        model_name: str | None = None,
        user_id: str | None = None,
        idempotency_key: str | None = None,
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
            operation_kind=operation_kind,
            multitask_strategy=multitask_strategy,
            metadata=metadata or {},
            kwargs=kwargs or {},
            user_id=user_id,
            created_at=now,
            updated_at=now,
            model_name=model_name,
            owner_worker_id=self._worker_id,
            lease_expires_at=lease_expires_at,
            idempotency_key=idempotency_key,
        )

        async with self._lock:
            claimed_durable_rows: dict[str, dict[str, Any]] = {}
            if idempotency_key is not None:
                for existing in self._runs.values():
                    if existing.idempotency_key != idempotency_key:
                        continue
                    if existing.store_only or existing.ownership_lost:
                        # A hydrated peer snapshot or a fenced local loser is
                        # not an execution-authoritative idempotency result.
                        # Let the durable uniqueness check return the current
                        # store-owned row instead.
                        continue
                    if existing.thread_id != thread_id or existing.user_id != user_id:
                        raise RuntimeError("Run idempotency key resolved to a different thread or user")
                    existing.idempotency_reused = True
                    return existing

            def reuse_idempotent_run(conflict: RunIdempotencyConflict) -> RunRecord:
                existing = self._record_from_store(conflict.existing)
                if existing.thread_id != thread_id or existing.user_id != user_id:
                    raise RuntimeError("Run idempotency key resolved to a different thread or user") from conflict
                current = self._runs.get(existing.run_id)
                if current is not None and current.store_only:
                    self._runs.pop(existing.run_id, None)
                    self._unindex_run_locked(existing.run_id, current.thread_id)
                    current = None
                if current is None or current.store_only or current.ownership_lost:
                    # Every conflict-hydrated record is a one-shot, read-only
                    # response.  It has no worker, heartbeat, or eviction task
                    # in this process, so indexing even an active peer row
                    # would leave a permanently stale registry entry and could
                    # make cancel/reconciliation impersonate the peer owner.
                    current = existing
                current.idempotency_reused = True
                return current

            # 1) Local inflight check (same-worker guard; cross-worker is the
            #    store's partial unique index below).
            local_inflight = [r for r in self._thread_records_locked(thread_id) if self._has_local_execution_authority(r) and (r.status in (RunStatus.pending, RunStatus.running) or r.finalizing)]

            if multitask_strategy in ("interrupt", "rollback") and any(record.operation_kind != ThreadOperationKind.run for record in local_inflight):
                raise ConflictError(f"Thread {thread_id} has an active checkpoint write")

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
                    create_kwargs = {
                        "run_id": run_id,
                        "thread_id": thread_id,
                        "owner_worker_id": self._worker_id,
                        "lease_expires_at": lease_expires_at,
                        "operation_kind": operation_kind.value,
                        "multitask_strategy": "reject",
                        "assistant_id": assistant_id,
                        "user_id": user_id,
                        "model_name": model_name,
                        "metadata": metadata,
                        "kwargs": kwargs,
                        "created_at": now,
                        "grace_seconds": grace_seconds,
                    }
                    if idempotency_key is not None:
                        create_kwargs["idempotency_key"] = idempotency_key
                    try:
                        await self._call_store_with_retry(
                            "create_thread_operation_atomic",
                            run_id,
                            lambda: self._store.create_thread_operation_atomic(**create_kwargs),
                        )
                    except RunIdempotencyConflict as exc:
                        return reuse_idempotent_run(exc)
                    except ConflictError:
                        raise
                    except Exception as exc:
                        if _is_unique_violation(exc):
                            raise ConflictError(f"Thread {thread_id} already has an active run") from exc
                        raise
                else:
                    create_kwargs = {
                        "run_id": run_id,
                        "thread_id": thread_id,
                        "owner_worker_id": self._worker_id,
                        "lease_expires_at": lease_expires_at,
                        "operation_kind": operation_kind.value,
                        "multitask_strategy": multitask_strategy,
                        "assistant_id": assistant_id,
                        "user_id": user_id,
                        "model_name": model_name,
                        "metadata": metadata,
                        "kwargs": kwargs,
                        "created_at": now,
                        "grace_seconds": grace_seconds,
                    }
                    if idempotency_key is not None:
                        create_kwargs["idempotency_key"] = idempotency_key
                    # Interrupt / rollback: store-side claim + insert in one
                    # transaction. Retry on IntegrityError in case another
                    # worker races us between our SELECT FOR UPDATE and INSERT.
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            _, claimed_rows = await self._call_store_with_retry(
                                "create_thread_operation_atomic",
                                run_id,
                                lambda: self._store.create_thread_operation_atomic(**create_kwargs),
                            )
                            claimed_durable_rows = {claimed["run_id"]: claimed for claimed in claimed_rows if isinstance(claimed.get("run_id"), str)}
                            break
                        except RunIdempotencyConflict as exc:
                            return reuse_idempotent_run(exc)
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
                    # ``create_thread_operation_atomic`` already marked any claimed store
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
                    claimed_row = claimed_durable_rows.get(r.run_id)
                    durable_cancel_action = claimed_row.get("cancel_action") if claimed_row is not None else None
                    r.abort_action = durable_cancel_action if durable_cancel_action in ("interrupt", "rollback") else multitask_strategy
                    r.abort_event.set()
                    task_active = r.task is not None and not r.task.done()
                    r.finalizing = task_active
                    if task_active:
                        r.task.cancel()
                    r.status = RunStatus.interrupted
                    r.updated_at = now
                    interrupted_records.append(r)

        # Outside the lock: persist interrupted status for locally-cancelled
        # runs. Store-side claimed rows are already finalised. Cancellation at
        # this point happens after the replacement was admitted, so close that
        # new run before propagating cancellation to the caller.
        try:
            for interrupted_record in interrupted_records:
                await self._persist_status(interrupted_record, RunStatus.interrupted)
        except asyncio.CancelledError:
            cleanup = asyncio.create_task(self._close_cancelled_admission(record))
            cleanup.set_name(f"deerflow-close-cancelled-admission-{record.run_id}")
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    pass
                except Exception:
                    break
            try:
                cleanup.result()
            except asyncio.CancelledError:
                logger.error("Cancelled admission cleanup task was itself cancelled for run %s", record.run_id)
            except Exception:
                logger.exception("Failed to close run %s after admission was cancelled", record.run_id)
            raise

        logger.info("Run created: run_id=%s thread_id=%s", run_id, thread_id)
        return record

    @asynccontextmanager
    async def reserve_thread_operation(
        self,
        thread_id: str,
        *,
        kind: ThreadOperationKind,
        user_id: str | None = None,
    ) -> AsyncIterator[None]:
        """Hold exclusive durable admission for a non-run thread operation.

        The reservation is a short-lived pending row, so the same durable
        uniqueness constraint used by ``create_or_reject`` closes both sides of
        the race across Gateway workers.
        """
        if kind == ThreadOperationKind.run:
            raise ValueError("Normal runs must be admitted with create_or_reject()")
        record = await self._admit_thread_operation(
            thread_id,
            operation_kind=kind,
            multitask_strategy="reject",
            user_id=user_id,
        )
        try:
            reservation_task = asyncio.current_task()
            if reservation_task is None:
                raise RuntimeError("Thread operation reservation requires an active asyncio task")
            lease_lost = True
            async with self._lock:
                if self._runs.get(record.run_id) is record:
                    record.task = reservation_task
                    lease_lost = record.abort_event.is_set()
            if lease_lost:
                raise asyncio.CancelledError()
            yield
        except asyncio.CancelledError:
            if record.abort_event.is_set():
                raise ConflictError(f"Thread {thread_id} reservation lease was lost") from None
            raise
        finally:
            try:
                if self._store is not None:
                    try:
                        await self._call_store_with_retry(
                            "release thread operation",
                            record.run_id,
                            lambda: self._store.delete_thread_operation(record.run_id, user_id=record.user_id),
                        )
                    except Exception:
                        logger.warning(
                            "Failed to release persisted thread operation %s; leaving it for orphan reconciliation",
                            record.run_id,
                            exc_info=True,
                        )
            finally:
                async with self._lock:
                    removed = self._runs.pop(record.run_id, None)
                    if removed is not None:
                        self._unindex_run_locked(record.run_id, removed.thread_id)

    @asynccontextmanager
    async def fence_checkpoint_mutation(
        self,
        run_id: str,
    ) -> AsyncIterator[bool]:
        """Hold durable execution ownership across one checkpoint mutation.

        In heartbeat mode the store scope locks the active run row, which is
        the same row takeover and interrupt/rollback admission must retire
        before a replacement lineage can be admitted.  The process-local flag
        only tells heartbeat not to contend with that lock; it is not the
        authority fence itself.
        """
        async with self._lock:
            record = self._runs.get(run_id)
            if record is None or record.store_only or not self._has_local_execution_authority(record):
                record = None
            elif record.checkpoint_mutation_fence_active:
                raise RuntimeError(f"Run {run_id} already holds a checkpoint mutation fence")
            else:
                record.checkpoint_mutation_fence_active = True

        if record is None:
            yield False
            return

        if not self.heartbeat_enabled:
            try:
                yield True
            finally:
                record.checkpoint_mutation_fence_active = False
            return

        if self._store is None or self._run_ownership_config is None:
            record.checkpoint_mutation_fence_active = False
            yield False
            return

        acquired = False
        fence_result = None
        try:
            async with self._store.checkpoint_mutation_fence(
                run_id,
                expected_owner_worker_id=self._worker_id,
                lease_seconds=self._run_ownership_config.lease_seconds,
            ) as fence_result:
                acquired = fence_result.acquired
                if not acquired:
                    await self._mark_ownership_lost(
                        record,
                        reason="Durable checkpoint mutation authority could not be acquired.",
                        require_active=False,
                    )
                    yield False
                    return
                yield True
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Run %s failed to hold its durable checkpoint mutation fence",
                run_id,
                exc_info=True,
            )
            await self._mark_ownership_lost(
                record,
                reason="Durable checkpoint mutation authority failed while held.",
                require_active=False,
            )
            raise
        finally:
            async with self._lock:
                if self._runs.get(run_id) is record:
                    if acquired and not record.ownership_lost and fence_result is not None and fence_result.lease_expires_at is not None:
                        record.lease_expires_at = fence_result.lease_expires_at
                    record.checkpoint_mutation_fence_active = False

    async def reconcile_orphaned_inflight_runs(
        self,
        *,
        error: str,
        before: str | None = None,
        stop_reason: str | None = None,
    ) -> list[RunRecord]:
        """Mark persisted active runs as failed when their lease has expired.

        In multi-worker deployments (Postgres), a run owned by Worker A that
        still shows ``pending`` / ``running`` after its lease expired means
        Worker A crashed or was partitioned. This worker (B) can safely claim
        and error it out because the lease was not renewed.

        Rows with a still-valid lease are skipped — they belong to another live
        worker. Rows with a NULL lease (pre-ownership data) are reclaimed as
        well, matching the original single-worker recovery behaviour. The
        candidate scan is only an optimization: each row is claimed with a
        lease-aware conditional update so a heartbeat renewal after the scan
        always wins over reconciliation.
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
                if self._has_local_execution_authority(live_record) and live_record.status in (RunStatus.pending, RunStatus.running):
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
                        stop_reason=stop_reason,
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
            record.stop_reason = stop_reason
            record.updated_at = now
            if record.operation_kind == ThreadOperationKind.run:
                # The atomic takeover above must win before writing a zero-delivery
                # receipt; otherwise a stale scan could race a heartbeat renewal and
                # permanently overwrite a live run's later detailed receipt. The
                # receipt remains best-effort, matching normal terminal delivery
                # when its event store is unavailable.
                await self._ensure_delivery_receipt(record)
                recovered.append(record)

        if recovered:
            logger.warning("Recovered %d orphaned inflight run(s) as error", len(recovered))
        return recovered

    async def has_inflight(self, thread_id: str) -> bool:
        """Return ``True`` if *thread_id* has a pending or running run."""
        async with self._lock:
            return any(self._has_local_execution_authority(r) and r.operation_kind == ThreadOperationKind.run and (r.status in (RunStatus.pending, RunStatus.running) or r.finalizing) for r in self._thread_records_locked(thread_id))

    async def cleanup(self, run_id: str, *, delay: float = 300) -> None:
        """Remove a run record after an optional delay."""
        if delay > 0:
            await asyncio.sleep(delay)
        async with self._lock:
            record = self._runs.pop(run_id, None)
            if record is not None:
                self._unindex_run_locked(run_id, record.thread_id)
        logger.debug("Run record %s cleaned up", run_id)

    @staticmethod
    def _completion_payload(record: RunRecord) -> dict[str, Any]:
        """Return the final fields that must survive terminal-record eviction."""
        return {
            "status": record.status.value,
            "total_input_tokens": record.total_input_tokens,
            "total_output_tokens": record.total_output_tokens,
            "total_tokens": record.total_tokens,
            "llm_call_count": record.llm_call_count,
            "lead_agent_tokens": record.lead_agent_tokens,
            "subagent_tokens": record.subagent_tokens,
            "middleware_tokens": record.middleware_tokens,
            "token_usage_by_model": {model: dict(usage) for model, usage in record.token_usage_by_model.items()},
            "message_count": record.message_count,
            "last_ai_message": record.last_ai_message,
            "first_human_message": record.first_human_message,
            "error": record.error,
            "stop_reason": record.stop_reason,
        }

    @staticmethod
    def _stored_completion_matches(stored: dict[str, Any], completion_payload: dict[str, Any]) -> bool:
        """Return whether *stored* already contains the local completion snapshot.

        RunStore completion writes are snapshot-shaped rather than sparse
        patches. Nullable values are therefore ignored here because store
        implementations deliberately do not clear an existing value when the
        corresponding completion argument is ``None``. SQL-backed stores also
        bound convenience text fields to 2,000 characters.
        """
        for key, expected in completion_payload.items():
            if key == "status" or expected is None:
                continue
            actual = stored.get(key)
            if key == "token_usage_by_model":
                if (actual or {}) != (expected or {}):
                    return False
                continue
            if key in _COMPLETION_COUNT_FIELDS and expected == 0 and actual is None:
                # Memory/legacy rows may omit never-incremented counters; they
                # are semantically identical to the hydrated default of zero.
                continue
            if key in {"last_ai_message", "first_human_message"} and isinstance(expected, str):
                if actual not in {expected, expected[:2000]}:
                    return False
                continue
            if actual != expected:
                return False
        return True

    def _stored_terminal_identity_is_repairable(
        self,
        record: RunRecord,
        stored: dict[str, Any],
        completion_payload: dict[str, Any],
    ) -> bool:
        """Return whether an incomplete same-status row is still locally owned."""
        if stored.get("stop_reason") == ORPHAN_RECOVERY_STOP_REASON:
            return False
        if self.heartbeat_enabled and not self._has_local_execution_authority(record):
            return False
        for key in ("error", "stop_reason"):
            durable_value = stored.get(key)
            if durable_value is not None and durable_value != completion_payload.get(key):
                return False
        durable_cancel_action = stored.get("cancel_action")
        if durable_cancel_action is not None:
            expected_cancelled_status = {
                "interrupt": RunStatus.interrupted.value,
                "rollback": RunStatus.error.value,
            }.get(durable_cancel_action)
            if durable_cancel_action == "rollback" and completion_payload.get("status") == RunStatus.interrupted.value:
                expected_cancelled_status = RunStatus.interrupted.value
            if durable_cancel_action != record.abort_action or stored.get("status") != expected_cancelled_status:
                return False
        durable_owner = stored.get("owner_worker_id")
        if durable_owner == self._worker_id and self._has_local_execution_authority(record):
            return True
        # Legacy single-worker stores may not persist owner metadata. They can
        # use the compatibility path because no peer takeover exists there.
        return not self.heartbeat_enabled and durable_owner is None

    def _stored_terminal_authority_is_local(
        self,
        record: RunRecord,
        stored: dict[str, Any] | None,
    ) -> bool:
        """Return whether a terminal row still belongs to this worker."""
        if stored is None or stored.get("stop_reason") == ORPHAN_RECOVERY_STOP_REASON:
            return False
        durable_owner = stored.get("owner_worker_id")
        return self._has_local_execution_authority(record) and durable_owner == self._worker_id

    def _stored_cancelled_transition_is_repairable(
        self,
        record: RunRecord,
        stored: dict[str, Any] | None,
        local_status: RunStatus,
    ) -> bool:
        """Return whether a durable cancel row is a safe terminal intermediate."""
        if stored is None:
            return False
        durable_owner = stored.get("owner_worker_id")
        owner_matches = self._has_local_execution_authority(record) and durable_owner == self._worker_id
        if not self.heartbeat_enabled and durable_owner is None:
            owner_matches = True
        return record.abort_action == "rollback" and local_status == RunStatus.error and stored.get("cancel_action") in (None, "rollback") and stored.get("status") == RunStatus.interrupted.value and owner_matches

    @staticmethod
    def _stored_terminal_cancel_identity_matches(
        record: RunRecord,
        stored: dict[str, Any],
        local_status: RunStatus,
    ) -> bool:
        """Return whether a durable cancellation agrees with local terminal state."""
        durable_action = stored.get("cancel_action")
        if durable_action is None:
            return True
        expected_status = {
            "interrupt": RunStatus.interrupted.value,
            "rollback": RunStatus.error.value,
        }.get(durable_action)
        if durable_action == "rollback" and local_status == RunStatus.interrupted:
            expected_status = RunStatus.interrupted.value
        return durable_action == record.abort_action and expected_status == local_status.value

    def _owned_durable_cancel_action(
        self,
        record: RunRecord,
        stored: dict[str, Any] | None,
        *,
        require_live_active_lease: bool,
    ) -> str | None:
        """Return a cancellation action only while this worker is authoritative."""
        if not self._has_local_execution_authority(record) or stored is None or stored.get("owner_worker_id") != self._worker_id:
            return None
        action = stored.get("cancel_action")
        if action not in ("interrupt", "rollback"):
            return None
        status = stored.get("status")
        if status in (RunStatus.pending.value, RunStatus.running.value):
            if require_live_active_lease:
                deadline = self._parse_lease_deadline(stored.get("lease_expires_at"))
                if deadline is None or deadline <= datetime.now(UTC):
                    return None
            return action
        if status == RunStatus.interrupted.value:
            return action
        if status == RunStatus.error.value and action == "rollback":
            return action
        return None

    async def _ensure_terminal_completion_durable(
        self,
        record: RunRecord,
        *,
        local_status: RunStatus,
        completion_payload: dict[str, Any],
        run_payload: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """Safely converge one local terminal snapshot with the durable row.

        A different terminal outcome is authoritative. An incomplete
        same-status row is repaired only while owner and terminal identity
        still match; missing and active rows use the same optional atomic store
        capabilities.
        """
        if self._store is None:
            return True, local_status.value
        try:
            stored = await self._call_store_with_retry(
                "verify terminal completion",
                record.run_id,
                lambda: self._store.get(record.run_id, user_id=record.user_id),
            )
        except Exception:
            logger.warning(
                "Failed to verify terminal completion for run %s; retaining it in memory",
                record.run_id,
                exc_info=True,
            )
            return False, None

        stored_status = stored.get("status") if stored is not None else None
        async with self._lock:
            current_local_status = record.status if self._runs.get(record.run_id) is record and not record.ownership_lost else None
        if (
            current_local_status in _TERMINAL_RUN_STATUSES
            and current_local_status != local_status
            and stored_status == current_local_status.value
            and self._stored_terminal_authority_is_local(record, stored)
            and self._stored_terminal_cancel_identity_matches(
                record,
                stored,
                current_local_status,
            )
        ):
            # A newer local transition (notably rollback interrupted→error)
            # completed while this older persistence call was in flight. The
            # durable row confirms the newer owner/action identity, so the
            # stale call must neither repair nor fence it.  Do not mint a
            # process-local completion proof from this older call: it did not
            # capture the newer status's full counters/error snapshot.  The
            # current transition (or the post-run authority gate) performs
            # its own full-snapshot verification.
            return True, stored_status
        durable_terminal = stored_status in _TERMINAL_RUN_STATUS_VALUES
        completion_matches = bool(stored is not None and stored_status == local_status.value and self._stored_completion_matches(stored, completion_payload))
        transition_requires_live_lease = stored is None or stored_status in (RunStatus.pending.value, RunStatus.running.value)
        if self.heartbeat_enabled and transition_requires_live_lease:
            confirmed_deadline = self._parse_lease_deadline(record.lease_expires_at)
            if confirmed_deadline is None or confirmed_deadline <= datetime.now(UTC):
                await self._fence_terminal_authority_loss(
                    record,
                    reason="The last confirmed run lease expired before terminal persistence.",
                    expected_status=local_status,
                )
                return False, stored_status

        # A different terminal result belongs to a competing terminalization
        # path (for example peer takeover) and remains authoritative. Repair a
        # missing row from the only remaining local snapshot; repair an active
        # row only through the optional owner+cancel CAS so eviction can never
        # overwrite a live peer or a cancellation that won during verification.
        repair_attempted = False
        repair_confirmed = False
        if not record.ownership_lost and stored is None:
            repair_attempted = True
            repaired = await self._insert_terminal_completion_if_absent(
                record,
                completion_payload,
                run_payload,
            )
            if repaired is None and not self.heartbeat_enabled:
                repaired = await self._legacy_terminal_completion_repair(
                    record,
                    completion_payload,
                    run_payload,
                    row_missing=True,
                )
            elif repaired is None:
                await self._fence_terminal_authority_loss(
                    record,
                    reason=("RunStore does not support atomic terminal-row recovery in ownership mode."),
                    expected_status=local_status,
                )
            repair_confirmed = repaired is True
        elif not record.ownership_lost and (
            stored_status in (RunStatus.pending.value, RunStatus.running.value)
            or self._stored_cancelled_transition_is_repairable(
                record,
                stored,
                local_status,
            )
        ):
            repair_attempted = True
            cancel_action = stored.get("cancel_action") if stored is not None else None
            if cancel_action is not None:
                repaired = await self._finalize_cancelled_completion_if_owned(
                    record,
                    completion_payload,
                    expected_cancel_action=cancel_action,
                    require_unexpired_lease=True,
                )
            else:
                repaired = await self._finalize_completion_if_owned_and_not_cancelled(
                    record,
                    completion_payload,
                    require_unexpired_lease=True,
                )
            if repaired is None and not self.heartbeat_enabled:
                repaired = await self._legacy_terminal_completion_repair(
                    record,
                    completion_payload,
                    run_payload,
                    row_missing=False,
                    observed_row=stored,
                )
            elif repaired is None:
                await self._fence_terminal_authority_loss(
                    record,
                    reason=("RunStore does not support owner-fenced terminal completion in ownership mode."),
                    expected_status=local_status,
                )
            repair_confirmed = repaired is True
        elif (
            not record.ownership_lost
            and stored is not None
            and stored_status == local_status.value
            and not completion_matches
            and self._stored_terminal_identity_is_repairable(
                record,
                stored,
                completion_payload,
            )
        ):
            repair_attempted = True
            repaired = await self._finalize_completion_if_owned_and_not_cancelled(
                record,
                completion_payload,
            )
            if repaired is None and not self.heartbeat_enabled:
                repaired = await self._legacy_terminal_completion_repair(
                    record,
                    completion_payload,
                    run_payload,
                    row_missing=False,
                    observed_row=stored,
                )
            elif repaired is None:
                # A same-status terminal row is immutable to takeover. Once
                # owner/cancel/error identity has been verified above, the
                # legacy snapshot API is safe even in heartbeat mode and
                # avoids permanently retaining third-party-store records that
                # predate the optional owner-CAS capability.
                repaired = await self._legacy_terminal_completion_repair(
                    record,
                    completion_payload,
                    run_payload,
                    row_missing=False,
                    observed_row=stored,
                    allow_owned_terminal_in_heartbeat=True,
                )
            repair_confirmed = repaired is True

        if repair_attempted:
            if repair_confirmed:
                await self._remember_durable_terminal_authority(
                    record,
                    local_status,
                )
            try:
                stored = await self._call_store_with_retry(
                    "verify repaired terminal completion",
                    record.run_id,
                    lambda: self._store.get(record.run_id, user_id=record.user_id),
                )
            except Exception:
                if repair_confirmed:
                    logger.warning(
                        "Failed to re-read terminal completion for run %s after a confirmed owner-fenced write; using local durability proof",
                        record.run_id,
                        exc_info=True,
                    )
                    return True, local_status.value
                logger.warning(
                    "Failed to verify repaired terminal completion for run %s; retaining it in memory",
                    record.run_id,
                    exc_info=True,
                )
                return False, None
            stored_status = stored.get("status") if stored is not None else None
            durable_terminal = stored_status in _TERMINAL_RUN_STATUS_VALUES
            completion_matches = bool(stored is not None and stored_status == local_status.value and self._stored_completion_matches(stored, completion_payload))

        if self.heartbeat_enabled and stored is not None and stored_status in (RunStatus.pending.value, RunStatus.running.value) and (not self._has_local_execution_authority(record) or stored.get("owner_worker_id") != self._worker_id):
            await self._fence_terminal_authority_loss(
                record,
                reason=(f"Worker {stored.get('owner_worker_id')} owns the durable active row."),
                expected_status=local_status,
            )
            return False, stored_status
        if not durable_terminal:
            logger.warning(
                "Run %s is terminal in memory but durable status is %s; retaining it for persistence retry",
                record.run_id,
                stored_status or "missing",
            )
            return False, stored_status
        if self._stored_cancelled_transition_is_repairable(
            record,
            stored,
            local_status,
        ):
            logger.warning(
                "Run %s still has an owned rollback intermediate in durable storage; retaining it for persistence retry",
                record.run_id,
            )
            return False, stored_status
        if (
            stored_status == local_status.value
            and stored is not None
            and not self._stored_terminal_cancel_identity_matches(
                record,
                stored,
                local_status,
            )
        ):
            await self._fence_terminal_authority_loss(
                record,
                reason=("The durable cancellation identity does not match the local terminal outcome."),
                expected_status=local_status,
            )
            return True, stored_status
        if self.heartbeat_enabled and not self._stored_terminal_authority_is_local(
            record,
            stored,
        ):
            await self._fence_terminal_authority_loss(
                record,
                reason=(f"Worker {stored.get('owner_worker_id') if stored is not None else None} owns the durable {stored_status} terminal snapshot."),
                expected_status=local_status,
            )
            return True, stored_status
        if stored_status != local_status.value:
            await self._fence_terminal_authority_loss(
                record,
                reason=(f"Durable terminal outcome {stored_status} superseded the local {local_status.value} outcome."),
                expected_status=local_status,
            )
            return True, stored_status
        if stored_status == local_status.value and not completion_matches:
            if (
                record.ownership_lost
                or stored is None
                or not self._stored_terminal_identity_is_repairable(
                    record,
                    stored,
                    completion_payload,
                )
            ):
                await self._fence_terminal_authority_loss(
                    record,
                    reason=(f"A different finalization path owns the durable {stored_status} snapshot."),
                    expected_status=local_status,
                )
                logger.info(
                    "Run %s has an authoritative terminal snapshot from another finalization path; evicting the stale local record",
                    record.run_id,
                )
                return True, stored_status
            logger.warning(
                "Run %s terminal status is durable but its final snapshot is incomplete; retaining it for persistence retry",
                record.run_id,
            )
            return False, stored_status
        await self._remember_durable_terminal_authority(record, local_status)
        return True, stored_status

    async def _evict_if_durable_terminal(self, run_id: str) -> bool:
        """Evict *run_id* only after its complete terminal snapshot is durable.

        Returns ``True`` when no further retry is needed: either the record was
        evicted or another path already removed it. Store failures and active
        persisted rows return ``False`` so the supervising task retries later.
        """
        if self._store is None:
            return True

        async with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                return True
            if record.finalizing or record.status not in _TERMINAL_RUN_STATUSES:
                return False
            local_status = record.status
            completion_payload = self._completion_payload(record)
            run_payload = self._store_put_payload(
                record,
                error=record.error,
                stop_reason=record.stop_reason,
            )

        durable, _ = await self._ensure_terminal_completion_durable(
            record,
            local_status=local_status,
            completion_payload=completion_payload,
            run_payload=run_payload,
        )
        if not durable:
            return False

        async with self._lock:
            current = self._runs.get(run_id)
            if current is None:
                return True
            if current is not record or current.finalizing or current.status != local_status:
                return False
            self._runs.pop(run_id, None)
            self._unindex_run_locked(run_id, current.thread_id)
        logger.debug("Terminal run record %s evicted after durable verification", run_id)
        return True

    async def _finalize_completion_if_owned_and_not_cancelled(
        self,
        record: RunRecord,
        completion_payload: dict[str, Any],
        *,
        require_unexpired_lease: bool = False,
    ) -> bool | None:
        """Repair an active or same-status row only while still owned."""
        if self._store is None or not self._has_local_execution_authority(record):
            return None
        finalize = getattr(self._store, "finalize_completion_if_owned_and_not_cancelled", None)
        if finalize is None:
            logger.warning(
                "RunStore does not support owner-fenced completion repair for run %s; retaining it in memory",
                record.run_id,
            )
            return None
        try:
            invoked, result = await self._mutate_current_terminal_snapshot(
                record,
                completion_payload,
                lambda: self._call_store_with_retry(
                    "owner-fenced terminal completion repair",
                    record.run_id,
                    lambda: finalize(
                        record.run_id,
                        expected_owner_worker_id=self._worker_id,
                        require_unexpired_lease=(require_unexpired_lease and self.heartbeat_enabled),
                        **completion_payload,
                    ),
                ),
            )
            if not invoked:
                return False
        except Exception:
            logger.warning("Owner-fenced completion repair failed for run %s", record.run_id, exc_info=True)
            return False
        if result is None:
            logger.warning(
                "RunStore does not implement owner-fenced completion repair for run %s; retaining it in memory",
                record.run_id,
            )
            return None
        if not isinstance(result, StatusFinalization):
            logger.warning(
                "RunStore returned an invalid owner-fenced completion result for run %s; retaining it in memory",
                record.run_id,
            )
            return False
        if result.finalized and result.durable_write_confirmed:
            return True
        if result.finalized:
            logger.warning(
                "RunStore reported owner-fenced completion for run %s without confirming the durable write",
                record.run_id,
            )
            return False
        if result.cancel_action is not None:
            logger.info(
                "Owner-fenced completion repair for run %s lost to cancellation action %s",
                record.run_id,
                result.cancel_action,
            )
        else:
            logger.info(
                "Owner-fenced completion repair for run %s lost its active ownership fence",
                record.run_id,
            )
        return False

    async def _finalize_cancelled_completion_if_owned(
        self,
        record: RunRecord,
        completion_payload: dict[str, Any],
        *,
        expected_cancel_action: str,
        require_unexpired_lease: bool = False,
    ) -> bool | None:
        """Finish a durable cancellation whose status write was interrupted."""
        allowed_statuses = {
            "interrupt": {RunStatus.interrupted.value},
            "rollback": {
                RunStatus.interrupted.value,
                RunStatus.error.value,
            },
        }.get(expected_cancel_action, set())
        if completion_payload.get("status") not in allowed_statuses or record.abort_action != expected_cancel_action or self._store is None or not self._has_local_execution_authority(record):
            logger.info(
                "Cancelled completion repair for run %s lacks matching local action proof; retaining it in memory",
                record.run_id,
            )
            return False
        finalize = getattr(
            self._store,
            "finalize_cancelled_completion_if_owned",
            None,
        )
        if finalize is None:
            logger.warning(
                "RunStore does not support owner-fenced cancelled completion repair for run %s; retaining it in memory",
                record.run_id,
            )
            return None
        try:
            invoked, result = await self._mutate_current_terminal_snapshot(
                record,
                completion_payload,
                lambda: self._call_store_with_retry(
                    "owner-fenced cancelled completion repair",
                    record.run_id,
                    lambda: finalize(
                        record.run_id,
                        expected_owner_worker_id=self._worker_id,
                        expected_cancel_action=expected_cancel_action,
                        require_unexpired_lease=(require_unexpired_lease and self.heartbeat_enabled),
                        **completion_payload,
                    ),
                ),
            )
            if not invoked:
                return False
        except Exception:
            logger.warning(
                "Owner-fenced cancelled completion repair failed for run %s",
                record.run_id,
                exc_info=True,
            )
            return False
        if result is None:
            logger.warning(
                "RunStore does not implement owner-fenced cancelled completion repair for run %s; retaining it in memory",
                record.run_id,
            )
            return None
        if not isinstance(result, StatusFinalization):
            logger.warning(
                "RunStore returned an invalid cancelled completion result for run %s; retaining it in memory",
                record.run_id,
            )
            return False
        if result.finalized and result.durable_write_confirmed:
            return True
        if result.finalized:
            logger.warning(
                "RunStore reported cancelled completion for run %s without confirming the durable write",
                record.run_id,
            )
            return False
        logger.info(
            "Owner-fenced cancelled completion repair for run %s lost its action or ownership fence (durable action=%s)",
            record.run_id,
            result.cancel_action,
        )
        return False

    async def _insert_terminal_completion_if_absent(
        self,
        record: RunRecord,
        completion_payload: dict[str, Any],
        run_payload: dict[str, Any],
    ) -> bool | None:
        """Recreate a missing row without a read-then-upsert race."""
        if self._store is None or not self._has_local_execution_authority(record):
            return None
        insert = getattr(self._store, "insert_terminal_completion_if_absent", None)
        if insert is None:
            logger.warning(
                "RunStore does not support atomic missing terminal-row recovery for run %s; retaining it in memory",
                record.run_id,
            )
            return None
        try:
            invoked, result = await self._mutate_current_terminal_snapshot(
                record,
                completion_payload,
                lambda: self._call_store_with_retry(
                    "insert missing terminal completion",
                    record.run_id,
                    lambda: insert(
                        record.run_id,
                        run_payload=run_payload,
                        completion_payload=completion_payload,
                    ),
                ),
            )
            if not invoked:
                return False
        except Exception:
            logger.warning(
                "Atomic missing terminal-row recovery failed for run %s",
                record.run_id,
                exc_info=True,
            )
            return False
        if result is None:
            logger.warning(
                "RunStore does not implement atomic missing terminal-row recovery for run %s; retaining it in memory",
                record.run_id,
            )
            return None
        if not isinstance(result, bool):
            logger.warning(
                "RunStore returned an invalid missing terminal-row recovery result for run %s; retaining it in memory",
                record.run_id,
            )
            return False
        return result

    async def _legacy_terminal_completion_repair(
        self,
        record: RunRecord,
        completion_payload: dict[str, Any],
        run_payload: dict[str, Any],
        *,
        row_missing: bool,
        observed_row: dict[str, Any] | None = None,
        allow_owned_terminal_in_heartbeat: bool = False,
    ) -> bool:
        """Preserve legacy repair only where peer overwrite is impossible."""
        if self._store is None or not self._has_local_execution_authority(record) or (self.heartbeat_enabled and not allow_owned_terminal_in_heartbeat):
            return False
        durable_owner = observed_row.get("owner_worker_id") if observed_row else None
        if not row_missing and durable_owner not in (None, self._worker_id):
            logger.warning(
                "Refusing single-worker compatibility repair for run %s because the durable row belongs to %s",
                record.run_id,
                durable_owner,
            )
            return False
        logger.info(
            "Using verified compatibility repair for terminal run %s",
            record.run_id,
        )
        try:

            async def legacy_repair() -> bool | None:
                if row_missing:
                    await self._call_store_with_retry(
                        "legacy insert missing terminal run",
                        record.run_id,
                        lambda: self._store.put(record.run_id, **run_payload),
                    )
                return await self._call_store_with_retry(
                    "legacy terminal completion repair",
                    record.run_id,
                    lambda: self._store.update_run_completion(
                        record.run_id,
                        **completion_payload,
                    ),
                )

            invoked, updated = await self._mutate_current_terminal_snapshot(
                record,
                completion_payload,
                legacy_repair,
            )
            if not invoked:
                return False
            return updated is not False
        except Exception:
            logger.warning(
                "Single-worker compatibility repair failed for terminal run %s",
                record.run_id,
                exc_info=True,
            )
            return False

    async def _evict_terminal_when_safe(
        self,
        run_id: str,
        *,
        delay: float,
        retry_delay: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        if delay > 0:
            await sleep(delay)
        retry_count = 0
        nominal_retry_delay = min(
            TERMINAL_RUN_EVICTION_MAX_RETRY_SECONDS,
            max(0.0, retry_delay),
        )
        while not self._shutting_down:
            if await self._evict_if_durable_terminal(run_id):
                return
            retry_count += 1
            jitter_width = nominal_retry_delay * TERMINAL_RUN_EVICTION_RETRY_JITTER_RATIO
            next_retry_delay = min(
                TERMINAL_RUN_EVICTION_MAX_RETRY_SECONDS,
                max(
                    0.0,
                    jitter(
                        nominal_retry_delay - jitter_width,
                        nominal_retry_delay + jitter_width,
                    ),
                ),
            )
            logger.debug(
                "Terminal run %s retained pending durable terminal state; retry=%d nominal_retry_seconds=%.1f next_retry_seconds=%.1f",
                run_id,
                retry_count,
                nominal_retry_delay,
                next_retry_delay,
            )
            await sleep(next_retry_delay)
            nominal_retry_delay = min(
                TERMINAL_RUN_EVICTION_MAX_RETRY_SECONDS,
                nominal_retry_delay * 2.0,
            )

    def _terminal_eviction_done(self, run_id: str, task: asyncio.Task[None]) -> None:
        if self._terminal_eviction_tasks.get(run_id) is task:
            self._terminal_eviction_tasks.pop(run_id, None)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            logger.warning("Terminal eviction task failed for run %s", run_id, exc_info=True)

    def schedule_terminal_eviction(
        self,
        run_id: str,
        *,
        delay: float = TERMINAL_RUN_EVICTION_DELAY_SECONDS,
        retry_delay: float = TERMINAL_RUN_EVICTION_RETRY_SECONDS,
    ) -> asyncio.Task[None] | None:
        """Schedule one persistence-gated terminal eviction for *run_id*.

        Memory-only managers preserve their existing in-process history. Once
        shutdown starts no new delayed work is accepted.
        """
        if self._store is None or self._shutting_down:
            return None
        existing = self._terminal_eviction_tasks.get(run_id)
        if existing is not None and not existing.done():
            return existing
        task = asyncio.create_task(
            self._evict_terminal_when_safe(run_id, delay=delay, retry_delay=retry_delay),
            name=f"run-terminal-eviction-{run_id}",
        )
        self._terminal_eviction_tasks[run_id] = task
        task.add_done_callback(lambda done, run_id=run_id: self._terminal_eviction_done(run_id, done))
        return task

    async def _stop_terminal_evictions(self, *, timeout: float) -> None:
        """Reject new eviction work and boundedly cancel existing timers."""
        self._shutting_down = True
        tasks = list(self._terminal_eviction_tasks.values())
        if not tasks:
            return
        for task in tasks:
            task.cancel()
        _, pending = await asyncio.wait(tasks, timeout=max(0.0, timeout))
        if pending:
            # A task may catch the first CancelledError while unwinding a store
            # call. Re-issue cancellation after the bounded wait, but keep the
            # task strongly referenced until its done callback observes it.
            for task in pending:
                task.cancel()
            logger.warning("Terminal eviction shutdown exceeded %.1fs; %d task(s) remain pending", timeout, len(pending))

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

    @staticmethod
    def _parse_lease_deadline(lease_expires_at: str | None) -> datetime | None:
        """Parse the last durably confirmed lease expiry.

        Missing or malformed deadlines are unsafe in heartbeat mode: the local
        worker has no bounded interval during which it can prove ownership.
        """
        if lease_expires_at is None:
            return None
        try:
            deadline = datetime.fromisoformat(lease_expires_at)
        except (TypeError, ValueError):
            return None
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        return deadline

    @staticmethod
    def _checkpoint_fence_superseded_lease_attempt(
        record: RunRecord,
        confirmed_lease_expires_at: str | None,
    ) -> bool:
        """Return whether a checkpoint fence now owns lease confirmation.

        A heartbeat selected immediately before ``fence_checkpoint_mutation``
        can block behind the durable row lock until its old timeout expires.
        The timeout/rejection belongs to that stale renewal attempt, not to the
        checkpoint mutation that still holds the ownership fence.  While the
        fence is active, defer to it; after release, its returned deadline
        changes ``record.lease_expires_at`` and proves the old attempt stale.
        """
        return record.checkpoint_mutation_fence_active or record.lease_expires_at != confirmed_lease_expires_at

    async def _mark_ownership_lost(
        self,
        record: RunRecord,
        *,
        reason: str,
        require_active: bool = True,
    ) -> bool:
        """Fence one local run and cancel its execution task.

        No store write is attempted here: once the last confirmed lease has
        expired, this worker is no longer authorized to publish a terminal
        outcome. A peer reconciler owns durable terminalization.
        """
        task_to_cancel: asyncio.Task | None = None
        async with self._lock:
            current = self._runs.get(record.run_id)
            if current is not record:
                return False
            if require_active:
                if record.status not in (RunStatus.pending, RunStatus.running):
                    return False
                if record.task is not None and record.task.done():
                    return False
            if record.ownership_lost:
                return True
            record.ownership_lost = True
            record.durable_terminal_authority_status = None
            record.abort_event.set()
            record.status = RunStatus.error
            record.error = reason
            record.updated_at = _now_iso()
            if record.task is not None and not record.task.done() and record.task is not asyncio.current_task():
                task_to_cancel = record.task

        if task_to_cancel is not None:
            task_to_cancel.cancel()
        logger.error("Run %s lost lease ownership; local execution was fenced: %s", record.run_id, reason)
        return True

    async def _fence_terminal_authority_loss(
        self,
        record: RunRecord,
        *,
        reason: str,
        expected_status: RunStatus | None = None,
    ) -> bool:
        """Fence post-run side effects after another terminal result wins.

        Unlike active lease loss, preserve the local terminal fields until the
        stale record is evicted. The durable row is already authoritative; the
        flag prevents title/thread metadata and lifecycle callbacks from using
        the losing local snapshot.
        """
        if not self.heartbeat_enabled:
            return False
        async with self._lock:
            current = self._runs.get(record.run_id)
            if current is not record:
                return False
            if expected_status is not None and record.status != expected_status:
                # This decision was based on an older terminal snapshot. A
                # newer local transition (notably rollback interrupted→error)
                # must perform its own convergence and must not be fenced by
                # the stale caller after an awaited store operation.
                return False
            if record.ownership_lost:
                return True
            record.ownership_lost = True
            record.durable_terminal_authority_status = None
            record.abort_event.set()
            record.updated_at = _now_iso()
        logger.error(
            "Run %s lost terminal finalization authority; local post-run side effects were fenced: %s",
            record.run_id,
            reason,
        )
        return True

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
        task.add_done_callback(self._heartbeat_done)
        logger.info("Run lease heartbeat started for worker %s", self._worker_id)

    def _heartbeat_done(self, task: asyncio.Task[None]) -> None:
        """Clear and observe the supervised heartbeat task."""
        if self._heartbeat_task is task:
            self._heartbeat_task = None
            self._heartbeat_stop = None
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            logger.warning("Run lease heartbeat failed", exc_info=True)

    async def stop_heartbeat(self, *, timeout: float = 5.0) -> None:
        """Stop the background heartbeat task within ``timeout`` seconds."""
        if self._heartbeat_stop is not None:
            self._heartbeat_stop.set()
        task = self._heartbeat_task
        if task is not None and not task.done():
            _, pending = await asyncio.wait(
                (task,),
                timeout=max(0.0, timeout),
            )
            if pending:
                task.cancel()
                await asyncio.sleep(0)
                logger.warning(
                    "Run lease heartbeat stop exceeded %.1fs; cancellation remains supervised",
                    timeout,
                )
                return
        if self._heartbeat_task is task:
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
                self._schedule_orphan_reconciliation()

    async def _renew_leases(self) -> None:
        """Renew locally-owned leases, failing closed at their deadlines.

        ``RunRecord.lease_expires_at`` advances only after a successful durable
        renewal, so it is the last confirmed ownership deadline. Transient
        exceptions are tolerated before that deadline; a call that blocks or
        keeps failing through it fences the local run.
        """
        if self._store is None or self._run_ownership_config is None:
            return
        lease_seconds = self._run_ownership_config.lease_seconds
        cancellations: list[tuple[str, str]] = []

        async with self._lock:
            # Renew any pending/running run owned by this worker unless its
            # background task has already completed. Also keep renewing while
            # a terminal result is staged locally but has no confirmed durable
            # terminal write: journal-backed finalization deliberately keeps
            # the durable row active through receipt, progress, and duration
            # writes, and normal success/error paths do not set ``finalizing``.
            # After the worker returns, the strongly supervised terminal
            # eviction task retains that renewal responsibility until it can
            # verify/repair the durable snapshot or is cancelled at shutdown.
            # A pending run whose task
            # has not been spawned yet (``task is None``) is still live from
            # this worker's perspective — between ``create_thread_operation_atomic``
            # inserting the row and the worker layer spawning the agent task
            # there is a brief window. If we drop those records here and the
            # window stretches past ``lease_seconds`` (e.g. event-loop
            # saturation, slow checkpoint hydrate on a fresh worker), peer
            # reconciliation will reclaim the run as an orphan and mark it
            # ``error`` even though this worker still intends to execute it.
            active_runs = [
                (rid, record)
                for rid, record in self._runs.items()
                if (
                    (record.status in (RunStatus.pending, RunStatus.running) and (record.task is None or not record.task.done()))
                    or (
                        record.status in _TERMINAL_RUN_STATUSES
                        and record.durable_terminal_authority_status != record.status
                        and ((record.task is not None and not record.task.done()) or ((eviction_task := self._terminal_eviction_tasks.get(rid)) is not None and not eviction_task.done()))
                    )
                )
                and self._has_local_execution_authority(record)
                and not record.checkpoint_mutation_fence_active
            ]

        for run_id, record in active_runs:
            confirmed_lease_expires_at = record.lease_expires_at
            confirmed_deadline = self._parse_lease_deadline(
                confirmed_lease_expires_at,
            )
            if confirmed_deadline is None or confirmed_deadline <= datetime.now(UTC):
                if self._checkpoint_fence_superseded_lease_attempt(
                    record,
                    confirmed_lease_expires_at,
                ):
                    continue
                if record.status in _TERMINAL_RUN_STATUSES:
                    await self._fence_terminal_authority_loss(
                        record,
                        reason="Terminal finalization began after the last confirmed lease expired.",
                    )
                else:
                    await self._mark_ownership_lost(
                        record,
                        reason="Lease ownership could not be confirmed before the last confirmed lease expired.",
                    )
                continue

            remaining = (confirmed_deadline - datetime.now(UTC)).total_seconds()
            new_expiry = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()
            try:
                async with asyncio.timeout(remaining):
                    renewal = await self._call_store_with_retry(
                        "renew_lease",
                        run_id,
                        lambda: self._store.renew_lease(
                            run_id,
                            owner_worker_id=self._worker_id,
                            lease_expires_at=new_expiry,
                        ),
                    )
                if self._checkpoint_fence_superseded_lease_attempt(
                    record,
                    confirmed_lease_expires_at,
                ):
                    continue
                if renewal.renewed:
                    if confirmed_deadline <= datetime.now(UTC):
                        if record.status in _TERMINAL_RUN_STATUSES:
                            await self._fence_terminal_authority_loss(
                                record,
                                reason="Terminal lease renewal completed after its prior authority expired.",
                            )
                        else:
                            await self._mark_ownership_lost(
                                record,
                                reason="Lease renewal completed after the last confirmed lease had already expired.",
                            )
                        continue
                    # Unsynced write is benign: ``lease_expires_at`` is the
                    # only field on an existing record this path mutates, so
                    # there is no concurrent writer to race against
                    # (``set_status`` / ``_persist_status`` touch other
                    # fields). Re-acquiring ``self._lock`` here would
                    # serialise against unrelated run mutations for no gain.
                    record.lease_expires_at = new_expiry
                    if renewal.cancel_action is not None:
                        action = renewal.cancel_action
                        if action not in ("interrupt", "rollback"):
                            logger.error(
                                "Run %s has invalid durable cancel action %r; fencing the local worker",
                                run_id,
                                action,
                            )
                            if record.status in _TERMINAL_RUN_STATUSES:
                                await self._fence_terminal_authority_loss(
                                    record,
                                    reason="The durable row contains an invalid cancellation action.",
                                )
                            else:
                                await self._mark_ownership_lost(
                                    record,
                                    reason="The durable row contains an invalid cancellation action.",
                                )
                            continue
                        cancellations.append((run_id, action))
                else:
                    # ``renew_lease`` returned False — the row was claimed
                    # by another worker (status is no longer pending/running,
                    # or ``owner_worker_id`` changed). Stop the local task so
                    # we don't waste CPU or overwrite the takeover status on
                    # finalisation.
                    async with self._lock:
                        still_candidate = (
                            self._runs.get(run_id) is record
                            and (
                                (record.status in (RunStatus.pending, RunStatus.running) and (record.task is None or not record.task.done()))
                                or (
                                    record.status in _TERMINAL_RUN_STATUSES
                                    and record.durable_terminal_authority_status != record.status
                                    and ((record.task is not None and not record.task.done()) or ((eviction_task := self._terminal_eviction_tasks.get(run_id)) is not None and not eviction_task.done()))
                                )
                            )
                            and self._has_local_execution_authority(record)
                        )
                    if still_candidate:
                        stored_after_rejection = await self._call_store_with_retry(
                            "verify rejected lease renewal",
                            run_id,
                            lambda: self._store.get(
                                run_id,
                                user_id=record.user_id,
                            ),
                        )
                        if self._checkpoint_fence_superseded_lease_attempt(
                            record,
                            confirmed_lease_expires_at,
                        ):
                            continue
                        stored_status = stored_after_rejection.get("status") if stored_after_rejection is not None else None
                        if (
                            record.status in _TERMINAL_RUN_STATUSES
                            and stored_status == record.status.value
                            and self._stored_terminal_authority_is_local(
                                record,
                                stored_after_rejection,
                            )
                            and self._stored_terminal_cancel_identity_matches(
                                record,
                                stored_after_rejection,
                                record.status,
                            )
                        ):
                            # The terminal CAS committed between candidate
                            # selection and renewal. A terminal row no longer
                            # needs a lease; cache that confirmed authority
                            # instead of fencing the successful owner.
                            await self._remember_durable_terminal_authority(
                                record,
                                record.status,
                                verified_stored=stored_after_rejection,
                            )
                            continue
                        logger.warning(
                            "Run %s lease renewal failed (status=%s,owner=%s) – worker likely taken over; aborting local task",
                            run_id,
                            record.status.value,
                            record.owner_worker_id,
                        )
                        if record.status in _TERMINAL_RUN_STATUSES:
                            await self._fence_terminal_authority_loss(
                                record,
                                reason="The durable store rejected lease renewal for this terminal finalizer.",
                            )
                        else:
                            await self._mark_ownership_lost(
                                record,
                                reason="The durable store rejected lease renewal for this worker.",
                            )
            except Exception:
                if self._checkpoint_fence_superseded_lease_attempt(
                    record,
                    confirmed_lease_expires_at,
                ):
                    continue
                if confirmed_deadline <= datetime.now(UTC):
                    if record.status in _TERMINAL_RUN_STATUSES:
                        await self._fence_terminal_authority_loss(
                            record,
                            reason="Terminal finalization authority could not be confirmed before the lease expired.",
                        )
                    else:
                        await self._mark_ownership_lost(
                            record,
                            reason="Lease ownership could not be confirmed before the last confirmed lease expired.",
                        )
                else:
                    logger.warning(
                        "Failed to renew lease for run %s before its confirmed deadline; will retry",
                        run_id,
                        exc_info=True,
                    )

        # Keep cancellation status writes and cleanup out of the sole renewal
        # loop. After every local lease has had a chance to renew, only signal
        # the owning worker task; that task performs normal terminal handling.
        for run_id, action in cancellations:
            async with self._lock:
                record = self._runs.get(run_id)
                startup_failed_terminal = bool(record is not None and record.startup_failed and record.status in _TERMINAL_RUN_STATUSES and record.durable_terminal_authority_status != record.status)
            if (
                startup_failed_terminal
                and record is not None
                and await self._adopt_unstarted_durable_cancel(
                    record,
                    action=action,
                )
            ):
                continue
            signalled = await self._signal_local_cancel(
                run_id,
                action=action,
            )
            if signalled:
                continue
            async with self._lock:
                record = self._runs.get(run_id)
                terminal_without_worker = bool(record is not None and record.status in _TERMINAL_RUN_STATUSES and record.durable_terminal_authority_status != record.status and (record.task is None or record.task.done()))
            if terminal_without_worker and record is not None:
                await self._fence_terminal_authority_loss(
                    record,
                    reason=("A durable cancellation won after the local worker had already returned."),
                )

    async def _reconcile_orphans_periodic(self) -> None:
        """Sweep for expired leases owned by dead peers.

        Scheduled as a single-flight background task by ``_heartbeat_loop``.
        This keeps both the store scan/status writes and the Gateway callback
        off the lease-renewal loop. Startup reconciliation handles the initial
        sweep; this periodic pass catches orphans whose lease expires between
        restarts.
        """
        recovered = await self.reconcile_orphaned_inflight_runs(
            error=LEASE_ORPHAN_RECOVERY_ERROR,
            stop_reason=ORPHAN_RECOVERY_STOP_REASON,
        )
        if recovered:
            logger.warning(
                "Periodic reconciliation recovered %d orphaned run(s) as error",
                len(recovered),
            )
            if self._on_orphans_recovered is not None:
                try:
                    await self._on_orphans_recovered(recovered)
                except Exception:
                    logger.warning(
                        "Periodic orphan recovery callback failed for %d run(s): run_ids=%s",
                        len(recovered),
                        [record.run_id for record in recovered],
                        exc_info=True,
                    )

    def _schedule_orphan_reconciliation(self) -> None:
        """Start one supervised recovery pass unless one is already running."""
        if self._shutting_down:
            return
        task = self._orphan_recovery_task
        if task is not None and not task.done():
            logger.debug("Skipping periodic orphan reconciliation: previous pass is still running")
            return
        task = asyncio.create_task(self._reconcile_orphans_periodic())
        task.set_name("deerflow-periodic-orphan-recovery")
        self._orphan_recovery_task = task
        task.add_done_callback(self._orphan_reconciliation_done)

    def _orphan_reconciliation_done(self, task: asyncio.Task[None]) -> None:
        """Clear and inspect the supervised single-flight recovery task."""
        if self._orphan_recovery_task is task:
            self._orphan_recovery_task = None
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            logger.warning("Periodic orphan reconciliation failed", exc_info=True)

    async def _drain_orphan_recovery_task(self, *, timeout: float) -> None:
        """Boundedly await the supervised recovery pass during shutdown."""
        task = self._orphan_recovery_task
        if task is None or task.done():
            return
        _, pending = await asyncio.wait((task,), timeout=max(0.0, timeout))
        if pending:
            task.cancel()
            await asyncio.sleep(0)
            logger.warning(
                "Orphan recovery drain exceeded %.1fs on shutdown; cancellation remains supervised",
                timeout,
            )

    async def _resolve_shutdown_cancel_action(
        self,
        record: RunRecord,
    ) -> str | None:
        """Atomically establish and verify shutdown's cancellation winner."""
        if not self.heartbeat_enabled or self._store is None:
            return "interrupt"
        outcome, _ = await self._request_durable_cancel(
            record.run_id,
            action="interrupt",
        )
        if outcome is not CancelOutcome.requested:
            return None
        try:
            stored = await self._store.get(
                record.run_id,
                user_id=record.user_id,
            )
        except Exception:
            logger.warning(
                "Shutdown could not verify the durable cancellation winner for run %s",
                record.run_id,
                exc_info=True,
            )
            return None
        return self._owned_durable_cancel_action(
            record,
            stored,
            require_live_active_lease=True,
        )

    def _shutdown_cancel_resolution_done(
        self,
        task: asyncio.Task[str | None],
    ) -> None:
        """Release and observe one bounded shutdown cancellation lookup."""
        self._shutdown_cancel_tasks.discard(task)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            logger.warning(
                "Shutdown cancellation resolution failed",
                exc_info=True,
            )

    async def _drain_shutdown_cancel_tasks(self, *, timeout: float) -> None:
        """Boundedly drain cancellation lookups before the store is closed."""
        tasks = [task for task in self._shutdown_cancel_tasks if not task.done()]
        if not tasks:
            return
        _, pending = await asyncio.wait(
            tasks,
            timeout=max(0.0, timeout),
        )
        if pending:
            for task in pending:
                task.cancel()
            await asyncio.sleep(0)
            logger.warning(
                "Shutdown cancellation resolution drain exceeded %.1fs; %d task(s) remain supervised",
                timeout,
                len(pending),
            )

    async def shutdown(self, *, timeout: float = 5.0) -> None:
        """Cancel and bounded-await all in-flight runs on process shutdown.

        Signals active runs first so their cancellation/cleanup can overlap a
        bounded heartbeat stop. The heartbeat may perform one final benign
        lease renewal before it observes the stop event.

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
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        # Set the shutdown fence before draining workers: a worker that reaches
        # its finalizer during the drain must not create a fresh five-minute
        # timer after the existing timers have been cancelled.
        eviction_budget = min(
            TERMINAL_RUN_EVICTION_SHUTDOWN_TIMEOUT_SECONDS,
            max(0.0, deadline - loop.time()),
        )
        await self._stop_terminal_evictions(timeout=eviction_budget)

        async with self._lock:
            inflight = [record for record in self._runs.values() if record.task is not None and not record.task.done()]
            needs_cancel_resolution = [record for record in inflight if self._has_local_execution_authority(record) and record.status in (RunStatus.pending, RunStatus.running) and not record.abort_event.is_set()]

        if not inflight:
            await self._drain_shutdown_cancel_tasks(
                timeout=max(0.0, deadline - loop.time()),
            )
            await self.stop_heartbeat(timeout=max(0.0, deadline - loop.time()))
            await self._drain_orphan_recovery_task(timeout=max(0.0, deadline - loop.time()))
            return

        resolved_actions: dict[str, str | None] = {}
        resolution_tasks: dict[asyncio.Task[str | None], RunRecord] = {}
        for record in needs_cancel_resolution:
            task = asyncio.create_task(
                self._resolve_shutdown_cancel_action(record),
                name=f"run-shutdown-cancel-resolution-{record.run_id}",
            )
            self._shutdown_cancel_tasks.add(task)
            task.add_done_callback(self._shutdown_cancel_resolution_done)
            resolution_tasks[task] = record
        if resolution_tasks:
            resolution_budget = min(
                RUN_SHUTDOWN_CANCEL_RESOLUTION_TIMEOUT_SECONDS,
                max(0.0, deadline - loop.time()),
            )
            done, unresolved = await asyncio.wait(
                resolution_tasks,
                timeout=resolution_budget,
            )
            for task in done:
                record = resolution_tasks[task]
                if task.cancelled():
                    resolved_actions[record.run_id] = None
                    continue
                try:
                    resolved_actions[record.run_id] = task.result()
                except Exception:
                    resolved_actions[record.run_id] = None
            for task in unresolved:
                resolved_actions[resolution_tasks[task].run_id] = None
                task.cancel()
            if unresolved:
                # Deliver cancellation before teardown continues. Tasks that
                # suppress it remain strongly referenced and done-observed.
                await asyncio.sleep(0)

        cancel_once: list[asyncio.Task] = []
        async with self._lock:
            for record in needs_cancel_resolution:
                task = record.task
                if self._runs.get(record.run_id) is not record or task is None or task.done() or not self._has_local_execution_authority(record) or record.status not in (RunStatus.pending, RunStatus.running) or record.abort_event.is_set():
                    # A concurrent heartbeat/cancel already delivered the
                    # winner. Never inject a second CancelledError into its
                    # cancellation cleanup/finally path.
                    continue
                action = resolved_actions.get(record.run_id)
                if action in ("interrupt", "rollback"):
                    was_running = record.status == RunStatus.running
                    record.abort_action = action
                    record.abort_event.set()
                    record.finalizing = True
                    if was_running:
                        cancel_once.append(task)
                else:
                    # An ambiguous response may follow a committed rollback.
                    # Do not guess an action. Fence checkpoint and RunStore
                    # side effects, then cancel once so resources can unwind.
                    record.ownership_lost = True
                    record.durable_terminal_authority_status = None
                    record.abort_event.set()
                    record.status = RunStatus.error
                    record.error = "Shutdown could not confirm the durable cancellation winner."
                    record.updated_at = _now_iso()
                    cancel_once.append(task)
        for task in cancel_once:
            task.cancel()

        tasks = [record.task for record in inflight]
        _, pending = await asyncio.wait(tasks, timeout=max(0.0, deadline - loop.time()))

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
                if self._has_local_execution_authority(record) and record.status in (RunStatus.pending, RunStatus.running):
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
        # Keep renewing locally-owned leases until worker finalizers have had
        # their bounded chance to commit terminal snapshots. Stopping the
        # heartbeat before this drain can expire a short lease while the task
        # is still flushing checkpointer/store work.
        await self._drain_shutdown_cancel_tasks(
            timeout=max(0.0, deadline - loop.time()),
        )
        await self.stop_heartbeat(timeout=max(0.0, deadline - loop.time()))
        await self._drain_orphan_recovery_task(timeout=max(0.0, deadline - loop.time()))


class CancelOutcome(StrEnum):
    """Result of a :meth:`RunManager.cancel` call."""

    cancelled = "cancelled"
    requested = "requested"
    taken_over = "taken_over"
    lease_valid_elsewhere = "lease_valid_elsewhere"
    not_cancellable = "not_cancellable"
    not_active_locally = "not_active_locally"
    unknown = "unknown"


class ConflictError(Exception):
    """Raised when multitask_strategy=reject and thread has inflight runs."""


class UnsupportedStrategyError(Exception):
    """Raised when a multitask_strategy value is not yet implemented."""
