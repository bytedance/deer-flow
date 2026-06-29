"""Abstract interface for workflow frontdoor storage."""

from __future__ import annotations

import abc
from typing import Any


class WorkflowStore(abc.ABC):
    """Durable workflow envelope storage interface."""

    @abc.abstractmethod
    async def create_or_get(
        self,
        *,
        workflow_kind: str = "message",
        source_type: str = "api",
        source: str | None = None,
        idempotency_key: str | None = None,
        external_message_ref: str | None = None,
        conversation_ref: str | None = None,
        thread_ref: str | None = None,
        sender_ref: str | None = None,
        user_id: str | None = None,
        thread_id: str | None = None,
        run_id: str | None = None,
        checkpoint_ns: str | None = None,
        checkpoint_id: str | None = None,
        status: str = "received",
        max_attempts: int = 1,
        metadata: dict[str, Any] | None = None,
        workflow_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Create a workflow or return the existing idempotency match.

        Returns ``(row, created)``.
        """

    @abc.abstractmethod
    async def claim_next(
        self,
        *,
        lease_owner: str,
        lease_seconds: int = 300,
        statuses: tuple[str, ...] = ("received", "bound"),
        status_on_claim: str = "claimed",
    ) -> dict[str, Any] | None:
        """Lease the next eligible workflow for a worker.

        Implementations should only claim rows whose existing lease is absent or
        expired and whose ``next_attempt_at`` is due. Returns the claimed row or
        ``None`` when no workflow is eligible.
        """

    @abc.abstractmethod
    async def get(self, workflow_id: str, *, user_id: str | None = None) -> dict[str, Any] | None:
        pass

    @abc.abstractmethod
    async def update_status(
        self,
        workflow_id: str,
        status: str,
        *,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        pass

    @abc.abstractmethod
    async def bind_runtime(
        self,
        workflow_id: str,
        *,
        thread_id: str | None = None,
        run_id: str | None = None,
        checkpoint_ns: str | None = None,
        checkpoint_id: str | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        pass

    @abc.abstractmethod
    async def release_for_retry(
        self,
        workflow_id: str,
        *,
        next_attempt_at: str | None = None,
        status: str = "received",
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Clear an active lease and make a workflow eligible for retry."""
        pass

    @abc.abstractmethod
    async def append_event(
        self,
        workflow_id: str,
        *,
        event_type: str,
        category: str = "lifecycle",
        content: Any | None = None,
        metadata: dict[str, Any] | None = None,
        thread_id: str | None = None,
        run_id: str | None = None,
        checkpoint_ns: str | None = None,
        checkpoint_id: str | None = None,
        run_event_seq: int | None = None,
        idempotency_key: str | None = None,
        source_event_ref: str | None = None,
        workflow_event_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Append a durable workflow event.

        Returns the event row, or ``None`` when the workflow does not exist.
        """
        pass

    @abc.abstractmethod
    async def list_events(
        self,
        workflow_id: str,
        *,
        event_types: list[str] | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        pass

    @abc.abstractmethod
    async def list(
        self,
        *,
        status: str | None = None,
        source_type: str | None = None,
        source: str | None = None,
        thread_id: str | None = None,
        run_id: str | None = None,
        user_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        pass
