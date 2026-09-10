"""Idempotent persistence for authoritative run lifecycle events."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

from deerflow.runtime.events.catalog import RUN_END_EVENT
from deerflow.runtime.events.store.base import RunEventStore
from deerflow.runtime.user_context import reset_current_user, set_current_user

from .schemas import RunStatus

logger = logging.getLogger(__name__)

_TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.success,
        RunStatus.error,
        RunStatus.timeout,
        RunStatus.interrupted,
    }
)


async def persist_run_terminal_event(
    event_store: RunEventStore,
    *,
    thread_id: str,
    run_id: str,
    status: RunStatus,
    content: Any | None = None,
    recovered: bool = False,
    user_id: str | None = None,
) -> bool:
    """Persist the run-scoped authoritative ``run.end`` event once.

    The caller must first make ``status`` durable on the RunRow.  The event is
    intentionally limited to the terminal status and opaque graph output; it
    never copies exception text, prompts, tool arguments, or tool results into
    metadata.  Recovery binds the stored run owner while writing so database
    event stores preserve user isolation outside a request context.
    """
    if status not in _TERMINAL_RUN_STATUSES:
        raise ValueError(f"run.end requires a terminal status, got {status.value!r}")

    metadata: dict[str, Any] = {"status": status.value}
    if recovered:
        metadata["recovered"] = True

    token = set_current_user(SimpleNamespace(id=user_id)) if user_id is not None else None
    try:
        existing, created = await event_store.put_if_absent(
            thread_id=thread_id,
            run_id=run_id,
            event_type=RUN_END_EVENT.event_type,
            category=RUN_END_EVENT.category,
            content={} if content is None else content,
            metadata=metadata,
        )
    finally:
        if token is not None:
            reset_current_user(token)

    if not created:
        existing_status = (existing.get("metadata") or {}).get("status")
        if existing_status != status.value:
            logger.error(
                "Run %s already has run.end status %r but its authoritative RunRow status is %r; preserving the first event",
                run_id,
                existing_status,
                status.value,
            )
    return created
