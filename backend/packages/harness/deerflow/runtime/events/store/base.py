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
from collections.abc import Sequence

from deerflow.runtime.user_context import AUTO, _AutoSentinel

_AI_MESSAGE_RUN_LOOKUP_PAGE_SIZE = 1000


class IncompleteMessageRunLookupError(RuntimeError):
    """Raised when a store cannot prove that a targeted lookup is complete."""


def normalize_message_ids(message_ids: set[str]) -> set[str]:
    """Return the non-empty string IDs that can participate in a lookup."""
    return {message_id for message_id in message_ids if isinstance(message_id, str) and message_id}


def match_ai_message_run_id(event: object, message_ids: set[str]) -> tuple[str, str] | None:
    """Return a target AI message ID and its valid run ID, if present."""
    if not isinstance(event, dict) or event.get("category") != "message":
        return None
    content = event.get("content")
    run_id = event.get("run_id")
    if not isinstance(content, dict) or content.get("type") != "ai" or not isinstance(run_id, str) or not run_id:
        return None
    message_id = content.get("id")
    if not isinstance(message_id, str) or message_id not in message_ids:
        return None
    return message_id, run_id


class RunEventStore(abc.ABC):
    """Run event stream storage interface.

    All implementations must guarantee:
    1. put() events are retrievable in subsequent queries
    2. seq is strictly increasing within the same thread
    3. list_messages() only returns category="message" events
    4. list_events() returns all events for the specified run
    5. Returned dicts contain the required RunEvent envelope fields; backends
       may add documented fields such as DbRunEventStore.user_id
    6. find_latest_ai_message_run_ids() returns the newest valid AI message
       event for each requested ID and performs no storage work for empty input
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
    async def put_if_absent(
        self,
        *,
        thread_id: str,
        run_id: str,
        event_type: str,
        category: str,
        content: str | dict = "",
        metadata: dict | None = None,
        created_at: str | None = None,
    ) -> tuple[dict, bool]:
        """Write one event unless this run already has the same event type.

        The check and write must be serialized with ordinary writers for the
        thread. Returns ``(record, created)``. This is the durability primitive
        used by terminal run receipts, whose recovery path may safely retry
        after a worker crash.
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

    async def find_latest_ai_message_run_ids(
        self,
        thread_id: str,
        message_ids: set[str],
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict[str, str]:
        """Map target message IDs to their newest valid AI event's run ID.

        Only ``category="message"`` events whose structured content has
        ``type="ai"`` and whose ``run_id`` is a non-empty string qualify. An
        empty target set must return immediately without storage work. The
        default implementation pages backward in bounded windows. It raises
        :class:`IncompleteMessageRunLookupError` instead of returning a
        partial result when a full page lacks a safe, progressing ``seq``
        cursor; callers may only treat an ordinary return as an exhaustive
        lookup for unresolved IDs.

        ``user_id`` follows the same explicit-caller semantics as
        :meth:`list_messages`.
        """
        pending = normalize_message_ids(message_ids)
        if not pending:
            return {}

        result: dict[str, str] = {}
        before_seq: int | None = None
        while pending:
            page = await self.list_messages(
                thread_id,
                limit=_AI_MESSAGE_RUN_LOOKUP_PAGE_SIZE,
                before_seq=before_seq,
                user_id=user_id,
            )
            if not page:
                break

            for event in reversed(page):
                match = match_ai_message_run_id(event, pending)
                if match is None:
                    continue
                message_id, run_id = match
                result[message_id] = run_id
                pending.remove(message_id)
                if not pending:
                    break

            if not pending or len(page) < _AI_MESSAGE_RUN_LOOKUP_PAGE_SIZE:
                break

            seqs: list[int] = []
            for event in page:
                seq = event.get("seq") if isinstance(event, dict) else None
                if not isinstance(seq, int) or isinstance(seq, bool):
                    raise IncompleteMessageRunLookupError("Run event lookup could not form a safe backward cursor from a full page")
                seqs.append(seq)

            next_before_seq = min(seqs)
            if before_seq is not None and next_before_seq >= before_seq:
                raise IncompleteMessageRunLookupError("Run event lookup could not form a safe backward cursor because seq did not progress")
            before_seq = next_before_seq

        return result

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
    async def get_message_seqs(
        self,
        thread_id: str,
        identities: Sequence[str],
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict[str, int]:
        """Return ``{identity: seq}`` for messages already persisted in this thread.

        A checkpoint carries no seq of its own and loses messages to
        summarization, so a client merging a checkpoint frame with this
        seq-ordered feed cannot place a surviving old message once the feed's
        loaded page window no longer reaches back to it (#4666). The seq already
        exists here; this exposes it without paging the whole feed.

        *identities* are the values produced by
        ``deerflow.runtime.events.message_identity.message_identity`` — the same
        rule the frontend applies — so both sides agree on what "same message"
        means. Identities that are not persisted (or not `category="message"`)
        are simply absent from the result: callers degrade to their own
        placement rule rather than treating a miss as an error. When one
        identity resolves to several rows, the earliest seq wins, so a message
        re-persisted later keeps the position it first occupied.
        """

    @abc.abstractmethod
    async def delete_by_thread(self, thread_id: str) -> int:
        """Delete all events for a thread. Return the number of deleted events."""

    @abc.abstractmethod
    async def delete_by_run(self, thread_id: str, run_id: str) -> int:
        """Delete all events for a specific run. Return the number of deleted events."""
