"""Confirmation of the owning worker's Run terminal evidence."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from deerflow.runtime.events.catalog import RUN_TERMINAL_EVENT
from deerflow.runtime.events.store.base import RunEventStore
from deerflow.runtime.events.store.db import DbRunEventStore

TERMINAL_PROTOCOL_VERSION = 1
TERMINAL_STATUSES = frozenset({"success", "error", "interrupted", "timeout"})


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
) -> TerminalEventConfirmation:
    """Confirm a singleton without replaying any Journal batch.

    One bounded retry uses the store's atomic check/insert to resolve a lost
    ACK. Both attempts require the same final commit authority. Cancellation
    propagates to the worker's owned finalizer; it cannot authorize a receipt.
    """
    if status not in TERMINAL_STATUSES:
        raise ValueError("Terminal evidence requires a final Run status")
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
                metadata={"protocol_version": TERMINAL_PROTOCOL_VERSION, "recovered": False},
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
