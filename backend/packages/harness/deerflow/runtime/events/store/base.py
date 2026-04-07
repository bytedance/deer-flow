"""Abstract interface for run event storage.

RunEventStore is the unified storage interface for run event streams.
Messages (frontend display) and execution traces (debugging/audit) go
through the same interface, distinguished by the ``category`` field.

Implementations:
- MemoryRunEventStore: in-memory dict (development, tests)
- Future: DB-backed store (SQLAlchemy ORM), JSONL file store
"""

from __future__ import annotations

import abc


class RunEventStore(abc.ABC):
    """Run event stream storage interface.

    All implementations must guarantee:
    1. put() events are retrievable in subsequent queries
    2. seq is strictly increasing within the same thread
    3. list_messages() only returns category="message" events
    4. list_events() returns all events for the specified run
    5. Returned dicts match the RunEvent field structure
    """

    @abc.abstractmethod
    async def put(
        self,
        *,
        thread_id: str,
        run_id: str,
        event_type: str,
        category: str,
        content: str | dict = "",
        metadata: dict | None = None,
        created_at: str | None = None,
    ) -> dict:
        """Write an event, auto-assign seq, return the complete record."""

    @abc.abstractmethod
    async def put_batch(self, events: list[dict]) -> list[dict]:
        """Batch-write events. Used by RunJournal flush buffer.

        Each dict's keys match put()'s keyword arguments.
        Returns complete records with seq assigned.
        """

    @abc.abstractmethod
    async def list_messages(
        self,
        thread_id: str,
        *,
        limit: int = 50,
        before_seq: int | None = None,
        after_seq: int | None = None,
    ) -> list[dict]:
        """Return displayable messages (category=message) for a thread, ordered by seq ascending.

        Supports bidirectional cursor pagination:
        - before_seq: return the last ``limit`` records with seq < before_seq (ascending)
        - after_seq: return the first ``limit`` records with seq > after_seq (ascending)
        - neither: return the latest ``limit`` records (ascending)
        """

    @abc.abstractmethod
    async def list_events(
        self,
        thread_id: str,
        run_id: str,
        *,
        event_types: list[str] | None = None,
        limit: int = 500,
    ) -> list[dict]:
        """Return the full event stream for a run, ordered by seq ascending.

        Optionally filter by event_types.
        """

    @abc.abstractmethod
    async def list_messages_by_run(
        self,
        thread_id: str,
        run_id: str,
    ) -> list[dict]:
        """Return displayable messages (category=message) for a specific run, ordered by seq ascending."""

    @abc.abstractmethod
    async def count_messages(self, thread_id: str) -> int:
        """Count displayable messages (category=message) in a thread."""

    @abc.abstractmethod
    async def delete_by_thread(self, thread_id: str) -> int:
        """Delete all events for a thread. Return the number of deleted events."""

    @abc.abstractmethod
    async def delete_by_run(self, thread_id: str, run_id: str) -> int:
        """Delete all events for a specific run. Return the number of deleted events."""
