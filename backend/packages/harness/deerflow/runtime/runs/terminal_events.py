"""Idempotent persistence for authoritative terminal run evidence."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from inspect import Parameter, signature
from types import SimpleNamespace
from typing import Any

from deerflow.runtime.events.catalog import RUN_END_EVENT
from deerflow.runtime.events.store.base import RunEventStore
from deerflow.runtime.user_context import AUTO, _AutoSentinel, reset_current_user, set_current_user

from .schemas import RunStatus

logger = logging.getLogger(__name__)

AUTHORITATIVE_RUN_END_METADATA_KEY = "authoritative"

_TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.success,
        RunStatus.error,
        RunStatus.timeout,
        RunStatus.interrupted,
    }
)


@contextmanager
def _run_owner_context(user_id: str | None | _AutoSentinel) -> Iterator[None]:
    """Bind an out-of-request event write to the claimed RunRow owner."""
    if user_id is AUTO:
        yield
        return
    user = SimpleNamespace(id=user_id) if user_id is not None else None
    token = set_current_user(user)
    try:
        yield
    finally:
        reset_current_user(token)


async def persist_run_terminal_event(
    event_store: RunEventStore,
    *,
    thread_id: str,
    run_id: str,
    status: RunStatus,
    content: Any | None = None,
    recovered: bool = False,
    user_id: str | None | _AutoSentinel = AUTO,
) -> bool:
    """Persist the run-scoped authoritative ``run.end`` event once.

    The caller must first publish every client-visible tail frame and make
    ``status`` durable on the RunRow.  The explicit protocol marker lets a
    consumer combine this event with a matching terminal row when bridge END
    delivery fails.  The event is intentionally limited to the terminal status
    and opaque graph output; it never copies exception text, prompts, tool
    arguments, or tool results into metadata.  Recovery binds the stored run
    owner while writing so database event stores preserve user isolation
    outside a request context.
    """
    if status not in _TERMINAL_RUN_STATUSES:
        raise ValueError(f"run.end requires a terminal status, got {status.value!r}")

    metadata: dict[str, Any] = {
        "status": status.value,
        AUTHORITATIVE_RUN_END_METADATA_KEY: True,
    }
    if recovered:
        metadata["recovered"] = True

    with _run_owner_context(user_id):
        existing, created = await event_store.put_if_absent(
            thread_id=thread_id,
            run_id=run_id,
            event_type=RUN_END_EVENT.event_type,
            category=RUN_END_EVENT.category,
            content={} if content is None else content,
            metadata=metadata,
        )

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


def _supports_explicit_user_id(method: Any) -> bool:
    """Return whether a read method can accept an explicit owner scope."""
    try:
        parameters = signature(method).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(parameter.name == "user_id" and parameter.kind in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY) for parameter in parameters)


async def has_authoritative_run_terminal_event(
    event_store: RunEventStore,
    *,
    thread_id: str,
    run_id: str,
    status: RunStatus,
    user_id: str | None | _AutoSentinel = AUTO,
) -> bool:
    """Return whether the new-runtime authoritative ``run.end`` exists.

    Older runtimes also wrote ``run.end`` but could do so before all visible
    tail frames were durably ordered.  Only the explicit protocol marker, with
    a status matching the authoritative RunRow, is safe as a missing-bridge
    END outbox.
    """
    query_kwargs: dict[str, Any] = {
        "event_types": [RUN_END_EVENT.event_type],
        "limit": 1,
    }
    if user_id is not AUTO and _supports_explicit_user_id(event_store.list_events):
        query_kwargs["user_id"] = user_id

    with _run_owner_context(user_id):
        events = await event_store.list_events(
            thread_id,
            run_id,
            **query_kwargs,
        )
    return any((metadata := event.get("metadata") or {}).get(AUTHORITATIVE_RUN_END_METADATA_KEY) is True and metadata.get("status") == status.value for event in events)


async def has_run_delivery_receipt(
    event_store: RunEventStore,
    *,
    thread_id: str,
    run_id: str,
    user_id: str | None | _AutoSentinel = AUTO,
) -> bool:
    """Return whether the durable stream-tail receipt exists for one run.

    ``run.delivery`` is written idempotently after every client-visible stream
    frame and before the terminal RunRow transition.  The pair therefore forms
    a rolling-upgrade-safe durable END outbox when the later bridge END write is
    lost.  A one-row query is sufficient because the receipt is a singleton.
    """
    query_kwargs: dict[str, Any] = {
        "event_types": ["run.delivery"],
        "limit": 1,
    }
    if user_id is not AUTO:
        if _supports_explicit_user_id(event_store.list_events):
            # DbRunEventStore supports an explicit unscoped ``None``. Merely
            # clearing the ContextVar would leave its default AUTO lookup with
            # no authenticated identity and make auth-disabled receipts
            # unreadable. Older/third-party stores keep their strict signature.
            query_kwargs["user_id"] = user_id

    with _run_owner_context(user_id):
        events = await event_store.list_events(
            thread_id,
            run_id,
            **query_kwargs,
        )
    return bool(events)


async def persist_run_delivery_receipt(
    event_store: RunEventStore,
    *,
    thread_id: str,
    run_id: str,
    content: dict[str, Any],
    user_id: str | None | _AutoSentinel = AUTO,
) -> bool:
    """Persist a recovered run's delivery singleton under its stored owner."""
    with _run_owner_context(user_id):
        _, created = await event_store.put_if_absent(
            thread_id=thread_id,
            run_id=run_id,
            event_type="run.delivery",
            category="outputs",
            content=content,
        )
    return created
