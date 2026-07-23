"""Abstract interface for run event storage.

RunEventStore is the unified storage interface for run event streams.
Messages (frontend display) and execution traces (debugging/audit) go
through the same interface, distinguished by the ``category`` field.

Implementations:
- MemoryRunEventStore: in-memory dict (development, tests)
- DbRunEventStore: SQLAlchemy ORM-backed persistence
- JsonlRunEventStore: JSONL file persistence for local/debug use
"""

from __future__ import annotations

import abc

from deerflow.runtime.user_context import AUTO, _AutoSentinel


class RunEventStore(abc.ABC):
    """Run event stream storage interface.

    All implementations must guarantee:
    1. put() events are retrievable in subsequent queries
    2. seq is strictly increasing within the same thread
    3. list_messages() only returns category="message" events
    4. list_events() returns all events for the specified run
    5. Returned dicts contain the required RunEvent envelope fields; backends
       may add documented fields such as DbRunEventStore.user_id
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
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict]:
        """Return displayable messages (category=message) for a thread, ordered by seq ascending.

        Supports bidirectional cursor pagination:
        - before_seq: return the last ``limit`` records with seq < before_seq (ascending)
        - after_seq: return the first ``limit`` records with seq > after_seq (ascending)
        - neither: return the latest ``limit`` records (ascending)

        ``user_id`` may be passed explicitly by request-independent callers;
        user-scoped backends must apply it according to their isolation model.
        """

    @abc.abstractmethod
    async def list_events(
        self,
        thread_id: str,
        run_id: str,
        *,
        event_types: list[str] | None = None,
        task_id: str | None = None,
        limit: int = 500,
        after_seq: int | None = None,
    ) -> list[dict]:
        """Return the full event stream for a run, ordered by seq ascending.

        Optionally filter by ``event_types`` and/or ``task_id`` (matched against
        ``metadata["task_id"]``). ``after_seq`` is a forward cursor returning the
        first ``limit`` records with seq > after_seq, so callers can page through
        a single subagent task's events without the run-wide ``limit`` truncating
        the tail (#3779).
        """

    @abc.abstractmethod
    async def list_messages_by_run(
        self,
        thread_id: str,
        run_id: str,
        *,
        limit: int = 50,
        before_seq: int | None = None,
        after_seq: int | None = None,
    ) -> list[dict]:
        """Return displayable messages (category=message) for a specific run, ordered by seq ascending.

        Supports bidirectional cursor pagination:
        - after_seq: return the first ``limit`` records with seq > after_seq (ascending)
        - before_seq: return the last ``limit`` records with seq < before_seq (ascending)
        - neither: return the latest ``limit`` records (ascending)
        """

    @abc.abstractmethod
    async def get_last_visible_ai_seq_by_run(
        self,
        thread_id: str,
        run_ids: set[str],
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict[str, int]:
        """Return each run's last non-middleware AI message sequence.

        ``user_id`` follows the same explicit-caller semantics as
        :meth:`list_messages`.
        """

    @abc.abstractmethod
    async def count_messages(self, thread_id: str) -> int:
        """Count displayable messages (category=message) in a thread."""

    @abc.abstractmethod
    async def delete_by_thread(self, thread_id: str) -> int:
        """Delete all events for a thread. Return the number of deleted events."""

    @abc.abstractmethod
    async def delete_by_run(self, thread_id: str, run_id: str) -> int:
        """Delete all events for a specific run. Return the number of deleted events."""
