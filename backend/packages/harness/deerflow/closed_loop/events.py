"""Closure-event publisher built on top of the existing ``run_event`` channel.

Why piggyback on ``run_event``? Two reasons:

1. The frontend already has SSE/poll plumbing for the run-event stream, so a
   ``closure.<action>`` lifecycle event automatically propagates without a new
   channel.
2. ``RunEventStore`` enforces ``(thread_id, seq)`` uniqueness and durable
   ordering, which is exactly what we need for an audit-style stream.

For closures we don't have a thread/run pair. The convention adopted here:

- ``thread_id`` -- the synthetic key ``closure:<tenant_id>``
- ``run_id``    -- the ticket's ``id``
- ``category``  -- ``"lifecycle"`` (matches the ``RunEventRow`` enum)
- ``event_type`` -- ``"closure.<action>"``
- ``content``   -- structured dict (auto JSON-encoded by the store layer)

If the store is unavailable (e.g. memory backend in unit tests with no
``run_event_store`` injected), publishing is a no-op so the state machine path
never fails because of a side effect.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deerflow.runtime.events.store.base import RunEventStore

logger = logging.getLogger(__name__)


def closure_thread_id(tenant_id: str) -> str:
    """Return the synthetic ``thread_id`` used for closure lifecycle events."""
    return f"closure:{tenant_id}"


class ClosureEventPublisher:
    """Thin wrapper around :class:`RunEventStore` for ``closure.*`` events."""

    def __init__(self, run_event_store: RunEventStore | None) -> None:
        self._store = run_event_store

    async def publish(
        self,
        *,
        tenant_id: str,
        ticket_id: str,
        action: str,
        from_status: str | None,
        to_status: str | None,
        actor_id: str | None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Best-effort publish. Logs but does not raise on failure."""
        if self._store is None:
            logger.debug(
                "closure publish skipped (no run_event_store): action=%s ticket=%s", action, ticket_id
            )
            return

        body: dict[str, Any] = {
            "ticket_id": ticket_id,
            "tenant_id": tenant_id,
            "action": action,
            "from_status": from_status,
            "to_status": to_status,
            "actor_id": actor_id,
            "payload": payload or {},
        }

        try:
            await self._store.put(
                thread_id=closure_thread_id(tenant_id),
                run_id=ticket_id,
                event_type=f"closure.{action}",
                category="lifecycle",
                content=body,
                metadata={"content_is_dict": True},
            )
        except Exception:
            logger.exception(
                "Failed to publish closure event action=%s ticket=%s tenant=%s",
                action,
                ticket_id,
                tenant_id,
            )
