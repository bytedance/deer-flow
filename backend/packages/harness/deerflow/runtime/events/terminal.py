"""Confirmation and recovery publication of authoritative Run terminal evidence."""

from __future__ import annotations

import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

from deerflow.runtime.events.catalog import RUN_TERMINAL_EVENT
from deerflow.runtime.events.store.base import RunEventLifecycleRejected, RunEventStore, SessionAwareRunEventLifecycleGuard
from deerflow.runtime.runs.store.base import RunStore

TERMINAL_PROTOCOL_VERSION = 1
TERMINAL_STATUSES = frozenset({"success", "error", "interrupted", "timeout"})

logger = logging.getLogger(__name__)

_RECOVERY_TARGET_ISSUER = object()


class RecoveryTerminalTargetConsumed(RuntimeError):
    """A one-shot recovery terminal target was published more than once."""


class _RecoveryTargetClaimState:
    __slots__ = ("_consumed", "_lock")

    def __init__(self) -> None:
        object.__setattr__(self, "_consumed", False)
        object.__setattr__(self, "_lock", threading.Lock())

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Recovery target claim state is immutable")

    def consume(self) -> None:
        with self._lock:
            if self._consumed:
                raise RecoveryTerminalTargetConsumed("Recovery terminal target was already consumed")
            object.__setattr__(self, "_consumed", True)


@dataclass(frozen=True)
class _RecoveryTargetIdentity:
    thread_id: str
    run_id: str
    user_id: str | None
    operation_kind: str
    committed_status: str


class RecoveryTerminalTarget:
    """One-shot authority to publish an error terminal after a takeover claim."""

    __slots__ = ("_claim_state", "_identity")

    def __init__(
        self,
        *,
        thread_id: str,
        run_id: str,
        user_id: str | None,
        operation_kind: str,
        committed_status: str,
        _issuer: object,
    ) -> None:
        if _issuer is not _RECOVERY_TARGET_ISSUER:
            raise TypeError("RecoveryTerminalTarget must be issued by RecoveryTerminalPublisher")
        if operation_kind != "run":
            raise ValueError("Recovery terminal evidence is limited to ordinary runs")
        if committed_status != "error":
            raise ValueError("Takeover recovery terminal evidence must be error")
        if not thread_id or not run_id:
            raise ValueError("Recovery terminal target requires thread_id and run_id")
        if user_id is not None and not isinstance(user_id, str):
            raise TypeError("Recovery terminal target user_id must be a string or None")
        self._identity = _RecoveryTargetIdentity(thread_id, run_id, user_id, operation_kind, committed_status)
        self._claim_state = _RecoveryTargetClaimState()

    def __setattr__(self, name: str, value: object) -> None:
        if name in self.__slots__ and hasattr(self, name):
            raise AttributeError("RecoveryTerminalTarget is immutable")
        object.__setattr__(self, name, value)

    @property
    def thread_id(self) -> str:
        return self._identity.thread_id

    @property
    def run_id(self) -> str:
        return self._identity.run_id

    @property
    def user_id(self) -> str | None:
        return self._identity.user_id

    @property
    def operation_kind(self) -> str:
        return self._identity.operation_kind

    @property
    def committed_status(self) -> str:
        return self._identity.committed_status

    def _consume(self) -> _RecoveryTargetIdentity:
        try:
            self._claim_state.consume()
        except RecoveryTerminalTargetConsumed:
            raise RecoveryTerminalTargetConsumed(f"Recovery terminal target for run {self.run_id} was already consumed") from None
        return self._identity


@dataclass(frozen=True)
class _RecoveryRunLifecycleGuard(SessionAwareRunEventLifecycleGuard):
    run_store: RunStore
    thread_id: str
    run_id: str
    user_id: str | None

    def _matches(self, row: dict | None) -> bool:
        return row is not None and row.get("run_id") == self.run_id and row.get("thread_id") == self.thread_id and row.get("operation_kind", "run") == "run" and row.get("status") == "error"

    async def __call__(self) -> bool:
        return self._matches(await self.run_store.get(self.run_id, user_id=self.user_id))

    async def check_in_session(self, session) -> bool:
        # Import lazily so memory/JSONL recovery does not load SQL persistence.
        from deerflow.persistence.run.sql import RunRepository

        if isinstance(self.run_store, RunRepository):
            return self._matches(await self.run_store.get_in_session(session, self.run_id, user_id=self.user_id))
        return await self()


class RecoveryTerminalPublisher:
    """Publish one confirmed error terminal for each successful takeover claim.

    ``RunStore.claim_for_takeover()`` atomically commits ``status=error``. The
    target therefore pins that known outcome rather than deriving authority
    from a later RunRow read.
    """

    def __init__(self, store: RunEventStore, run_store: RunStore) -> None:
        self._store = store
        self._run_store = run_store

    def lifecycle_guard(self, *, thread_id: str, run_id: str, user_id: str | None) -> Callable[[], Awaitable[bool]]:
        """Return a guard that rejects publication after Run deletion or identity drift."""

        return _RecoveryRunLifecycleGuard(self._run_store, thread_id, run_id, user_id)

    def authorize_takeover(
        self,
        *,
        claimed: bool,
        thread_id: str,
        run_id: str,
        user_id: str | None,
        operation_kind: str,
    ) -> RecoveryTerminalTarget | None:
        """Issue one-shot publication authority only for a committed run takeover."""
        if claimed is not True or operation_kind != "run":
            return None
        return RecoveryTerminalTarget(
            thread_id=thread_id,
            run_id=run_id,
            user_id=user_id,
            operation_kind=operation_kind,
            committed_status="error",
            _issuer=_RECOVERY_TARGET_ISSUER,
        )

    async def publish(self, target: RecoveryTerminalTarget) -> TerminalEventConfirmation:
        """Consume *target* once, backfill delivery, then confirm terminal evidence."""
        if not isinstance(target, RecoveryTerminalTarget):
            raise TypeError("RecoveryTerminalPublisher.publish requires a RecoveryTerminalTarget")
        identity = target._consume()
        guard = self.lifecycle_guard(thread_id=identity.thread_id, run_id=identity.run_id, user_id=identity.user_id)
        await self._ensure_delivery_receipt(identity, guard)
        try:
            confirmation = await confirm_terminal_event(
                self._store,
                thread_id=identity.thread_id,
                run_id=identity.run_id,
                status=identity.committed_status,
                user_id=identity.user_id,
                recovered=True,
                authorized=lambda: True,
                lifecycle_guard=guard,
            )
        except Exception:
            # Cancellation is BaseException and must retain its independent
            # propagation semantics after the one-shot target was consumed.
            logger.warning(
                "Unexpected recovery terminal confirmation failure for run %s; preserving the committed RunRow",
                identity.run_id,
                exc_info=True,
            )
            return TerminalEventConfirmation.UNKNOWN
        if not confirmation.confirmed:
            logger.warning(
                "Recovery terminal publication for run %s returned %s; preserving the committed RunRow",
                identity.run_id,
                confirmation.value,
            )
        return confirmation

    async def _ensure_delivery_receipt(self, identity: _RecoveryTargetIdentity, lifecycle_guard: Callable[[], Awaitable[bool]]) -> None:
        """Best-effort zero-delivery receipt; terminal publication remains independent."""
        try:
            await self._store.put_if_absent(
                thread_id=identity.thread_id,
                run_id=identity.run_id,
                event_type="run.delivery",
                category="outputs",
                content={"presented": 0, "paths": [], "by_tool": {}},
                user_id=identity.user_id,
                lifecycle_guard=lifecycle_guard,
            )
        except Exception:
            logger.warning(
                "Failed to backfill delivery receipt for recovered run %s; continuing with terminal confirmation",
                identity.run_id,
                exc_info=True,
            )


class TerminalEventConfirmation(StrEnum):
    CONFIRMED_NEW = "CONFIRMED_NEW"
    CONFIRMED_EXISTING = "CONFIRMED_EXISTING"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"

    @property
    def confirmed(self) -> bool:
        return self in (self.CONFIRMED_NEW, self.CONFIRMED_EXISTING)


def _matches(event: object, *, thread_id: str, run_id: str, status: str, user_id: str | None, owner_required: bool) -> bool:
    if not isinstance(event, dict):
        return False
    metadata = event.get("metadata")
    return (
        event.get("thread_id") == thread_id
        and event.get("run_id") == run_id
        and event.get("event_type") == RUN_TERMINAL_EVENT.event_type
        and event.get("category") == RUN_TERMINAL_EVENT.category
        and event.get("content") == {"status": status}
        and isinstance(metadata, dict)
        and type(metadata.get("protocol_version")) is int
        and metadata["protocol_version"] == TERMINAL_PROTOCOL_VERSION
        and type(metadata.get("recovered")) is bool
        and type(event.get("seq")) is int
        and event["seq"] > 0
        and (not owner_required or "user_id" in event)
        and ("user_id" not in event or event["user_id"] == user_id)
    )


async def confirm_terminal_event(
    store: RunEventStore,
    *,
    thread_id: str,
    run_id: str,
    status: str,
    user_id: str | None,
    authorized: Callable[[], bool],
    recovered: bool = False,
    lifecycle_guard: Callable[[], Awaitable[bool]] | None = None,
) -> TerminalEventConfirmation:
    """Confirm a singleton without replaying any Journal batch.

    One bounded retry uses the store's atomic check/insert to resolve a lost
    ACK. Both attempts require the same final commit authority. Cancellation
    propagates to the worker's owned finalizer; it cannot authorize a receipt.
    ``recovered`` marks only a newly inserted recovery event; a matching
    existing event retains its original source marker.
    """
    if status not in TERMINAL_STATUSES:
        raise ValueError("Terminal evidence requires a final Run status")
    if type(recovered) is not bool:
        raise ValueError("Terminal evidence recovered marker must be a boolean")
    from deerflow.runtime.events.store.db import DbRunEventStore

    for attempt in range(2):
        if not authorized():
            raise RuntimeError("Terminal event lacks an attributable final commit ACK")
        try:
            put_kwargs = {
                "thread_id": thread_id,
                "run_id": run_id,
                "event_type": RUN_TERMINAL_EVENT.event_type,
                "category": RUN_TERMINAL_EVENT.category,
                "content": {"status": status},
                "metadata": {"protocol_version": TERMINAL_PROTOCOL_VERSION, "recovered": recovered},
                "user_id": user_id,
            }
            if lifecycle_guard is not None:
                put_kwargs["lifecycle_guard"] = lifecycle_guard
            result = await store.put_if_absent(**put_kwargs)
        except RunEventLifecycleRejected:
            return TerminalEventConfirmation.CONFLICT
        except Exception:
            if attempt == 0:
                continue
            return TerminalEventConfirmation.UNKNOWN
        if not authorized():
            raise RuntimeError("Terminal event confirmation lost its final commit authority")
        if not isinstance(result, tuple) or len(result) != 2 or type(result[1]) is not bool:
            return TerminalEventConfirmation.UNKNOWN
        event, created = result
        if not _matches(event, thread_id=thread_id, run_id=run_id, status=status, user_id=user_id, owner_required=isinstance(store, DbRunEventStore)):
            return TerminalEventConfirmation.CONFLICT
        return TerminalEventConfirmation.CONFIRMED_NEW if created else TerminalEventConfirmation.CONFIRMED_EXISTING
    return TerminalEventConfirmation.UNKNOWN
