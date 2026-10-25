"""Confirmation and recovery publication of authoritative Run terminal evidence."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from deerflow.runtime.events.catalog import RUN_TERMINAL_EVENT
from deerflow.runtime.events.store.base import RunEventStore

TERMINAL_PROTOCOL_VERSION = 1
TERMINAL_STATUSES = frozenset({"success", "error", "interrupted", "timeout"})

logger = logging.getLogger(__name__)

_RECOVERY_TARGET_ISSUER = object()


class RecoveryTerminalTargetConsumed(RuntimeError):
    """A one-shot recovery terminal target was published more than once."""


@dataclass
class _RecoveryTargetClaimState:
    consumed: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass(frozen=True)
class RecoveryTerminalTarget:
    """One-shot authority to publish an error terminal after a takeover claim."""

    thread_id: str
    run_id: str
    user_id: str | None
    operation_kind: str
    committed_status: str
    _claim_state: _RecoveryTargetClaimState = field(repr=False, compare=False)
    _issuer: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._issuer is not _RECOVERY_TARGET_ISSUER:
            raise TypeError("RecoveryTerminalTarget must be issued by RecoveryTerminalPublisher")
        if self.operation_kind != "run":
            raise ValueError("Recovery terminal evidence is limited to ordinary runs")
        if self.committed_status != "error":
            raise ValueError("Takeover recovery terminal evidence must be error")
        if not self.thread_id or not self.run_id:
            raise ValueError("Recovery terminal target requires thread_id and run_id")
        if self.user_id is not None and not isinstance(self.user_id, str):
            raise TypeError("Recovery terminal target user_id must be a string or None")

    def _consume(self) -> None:
        with self._claim_state.lock:
            if self._claim_state.consumed:
                raise RecoveryTerminalTargetConsumed(f"Recovery terminal target for run {self.run_id} was already consumed")
            self._claim_state.consumed = True


class RecoveryTerminalPublisher:
    """Publish one confirmed error terminal for each successful takeover claim.

    ``RunStore.claim_for_takeover()`` atomically commits ``status=error``. The
    target therefore pins that known outcome rather than deriving authority
    from a later RunRow read.
    """

    def __init__(self, store: RunEventStore) -> None:
        self._store = store

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
            _claim_state=_RecoveryTargetClaimState(),
            _issuer=_RECOVERY_TARGET_ISSUER,
        )

    async def publish(self, target: RecoveryTerminalTarget) -> TerminalEventConfirmation:
        """Consume *target* once and resolve its event confirmation."""
        target._consume()
        confirmation = await confirm_terminal_event(
            self._store,
            thread_id=target.thread_id,
            run_id=target.run_id,
            status=target.committed_status,
            user_id=target.user_id,
            recovered=True,
            authorized=lambda: True,
        )
        if not confirmation.confirmed:
            logger.warning(
                "Recovery terminal publication for run %s returned %s; preserving the committed RunRow",
                target.run_id,
                confirmation.value,
            )
        return confirmation


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
            result = await store.put_if_absent(
                thread_id=thread_id,
                run_id=run_id,
                event_type=RUN_TERMINAL_EVENT.event_type,
                category=RUN_TERMINAL_EVENT.category,
                content={"status": status},
                metadata={"protocol_version": TERMINAL_PROTOCOL_VERSION, "recovered": recovered},
                user_id=user_id,
            )
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
