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
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from deerflow.runtime.user_context import AUTO, _AutoSentinel

_AI_MESSAGE_RUN_LOOKUP_PAGE_SIZE = 1000


class IncompleteMessageRunLookupError(RuntimeError):
    """Raised when a store cannot prove that a targeted lookup is complete."""


class RunEventStoreNotCommittedError(RuntimeError):
    """A batch write definitely did not commit any of its events.

    ``RunEventStore.put_batch()`` implementations may raise this only when they
    can prove that none of the batch was persisted (for example, the write was
    rejected before reaching storage). ``RunJournal`` may then deliberately
    retry the batch. Any other exception from ``put_batch`` is treated as an
    ambiguous/UNKNOWN outcome: the batch is quarantined and is never replayed,
    because a store that committed and then lost its acknowledgement would
    otherwise produce duplicate events.
    """


class RunEventLifecycleRejected(RuntimeError):
    """A guarded singleton write was rejected because its Run is no longer live."""


class SessionAwareRunEventLifecycleGuard(abc.ABC):
    """A lifecycle guard that can reuse a DB event writer's active session.

    Other stores call it normally. DB stores call ``check_in_session`` under
    their mutation fence; implementations must fall back to their ordinary
    read when that session does not belong to the guarded store's database.
    Neither entry point may re-enter the event store or commit the session.
    """

    @abc.abstractmethod
    async def __call__(self) -> bool: ...

    @abc.abstractmethod
    async def check_in_session(self, session: AsyncSession) -> bool: ...


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
    7. Mutable inputs and returned records are isolated from store-owned state,
       including nested content and metadata. Mutating a write input, receipt,
       or dict-returning list result cannot change stored records or later reads.
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
        """Write an event, assign seq, and return a detached record snapshot.

        Mutating input content/metadata or the returned record, including nested
        values, must not mutate stored state.
        """

    @abc.abstractmethod
    async def put_batch(self, events: list[dict]) -> list[dict]:
        """Batch-write events. Used by RunJournal flush buffer.

        Each dict's keys match put()'s keyword arguments. Returned records
        are detached snapshots, and mutable inputs must not alias stored rows.
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
        user_id: str | None | _AutoSentinel = AUTO,
        lifecycle_guard: Callable[[], Awaitable[bool]] | None = None,
    ) -> tuple[dict, bool]:
        """Write one event unless this run already has the same event type.

        The check and write must be serialized with ordinary writers for the
        thread. Returns ``(record, created)``. This is the durability primitive
        used by terminal run receipts, whose recovery path may safely retry
        after a worker crash. Both newly created and existing event receipts
        are detached snapshots.

        Explicit ``user_id`` stamps the owner for contextless worker writes.
        Stores without user isolation accept it for interface parity. Existing
        events retain their original owner and must be validated by the caller.

        When ``lifecycle_guard`` is provided, stores evaluate it while holding
        the same store mutation fence used by event deletion. A false
        result raises :class:`RunEventLifecycleRejected` without writing.
        That fence is non-reentrant: the guard must not call back into this
        event store or acquire locks in an order that can invert the fence's
        lock ordering, as doing so may deadlock. The built-in recovery guard
        only reads the RunStore. DB stores evaluate
        :class:`SessionAwareRunEventLifecycleGuard` with their active session
        to avoid a nested connection checkout from the same pool.
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

        When both cursors are supplied, return the first ``limit`` records in
        the exclusive window ``after_seq < seq < before_seq`` (ascending).
        Each returned record is a detached snapshot; mutating nested values must
        not alter stored state or later reads.

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
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict]:
        """Return the full event stream for a run, ordered by seq ascending.

        Optionally filter by ``event_types`` and/or ``task_id`` (matched against
        ``metadata["task_id"]``). ``after_seq`` is a forward cursor returning the
        first ``limit`` records with seq > after_seq, so callers can page through
        a single subagent task's events without the run-wide ``limit`` truncating
        the tail (#3779). Returned records are detached snapshots, including nested
        content and metadata. ``user_id`` follows the same explicit-caller semantics
        as :meth:`list_messages`.
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
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict]:
        """Return displayable messages (category=message) for a specific run, ordered by seq ascending.

        Supports bidirectional cursor pagination:
        - after_seq: return the first ``limit`` records with seq > after_seq (ascending)
        - before_seq: return the last ``limit`` records with seq < before_seq (ascending)
        - neither: return the latest ``limit`` records (ascending)

        When both cursors are supplied, return the first ``limit`` records in
        the exclusive window ``after_seq < seq < before_seq`` (ascending).
        Returned records are detached snapshots, including nested content and
        metadata. ``user_id`` follows the same explicit-caller semantics as
        :meth:`list_messages`.
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
    async def delete_by_thread(
        self,
        thread_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> int:
        """Delete all events for a thread. Return the number of deleted events.

        ``user_id`` follows the same three-state convention as the read methods:
        ``AUTO`` resolves the caller's context, an explicit id scopes the delete
        to that owner, and ``None`` removes every owner's rows. Backends whose
        storage is not user-scoped (memory, JSONL) accept the parameter for
        interface parity and ignore it, so callers can delete uniformly.
        """

    @abc.abstractmethod
    async def delete_by_run(
        self,
        thread_id: str,
        run_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> int:
        """Delete all events for a specific run. Return the number of deleted events.

        ``user_id`` follows the same convention as :meth:`delete_by_thread`.
        """
