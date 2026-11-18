"""``RunEventStore`` over one KurrentDB stream per thread, ``deerflow.run-events-{enc(thread_id)}``.

Event schema (every event's data and metadata are JSON):

- ``deerflow.run-events.RunEvent``: data is the full record envelope (``thread_id``,
  ``run_id``, ``event_type``, ``category``, ``content``, ``metadata``, ``seq``,
  ``created_at``); metadata is ``{"user_id": <owner or null>}``. ``user_id`` is
  recorded, never used to filter: the store is not user-scoped, like memory/JSONL.
  A deletion's copies of surviving events add ``"survivor": true``
- ``deerflow.run-events.RunsCompacted`` / ``deerflow.run-events.ThreadCleared``:
  deletion boundaries, data ``{"seq_high_water": int, ...}``. Reads fold from the
  newest boundary forward; events before it are gone (written by deletions)
- ``deerflow.Fence``: written only to settle an ambiguous append; ignored by reads

Deletions are boundaries written through the crash-safe protocol in ``..deletions``
(intent in ``deerflow.kurrent-deletions``, boundary at the head the deletion read,
``$tb`` raised to the boundary's own position, ``DeletionDone``), never a stream
delete, so ``seq`` bookkeeping survives them:

- ``delete_by_run``: one append of a ``RunsCompacted{intent_id, seq_high_water, run_id,
  deleted}`` boundary followed by copies of every surviving event (same data, same
  metadata plus ``"survivor": true``)
- ``delete_by_thread``: one ``ThreadCleared{intent_id, seq_high_water, deleted}`` boundary
- ``seq_high_water`` is the newest boundary's high water and every ``seq`` since
  (``seq.seq_high_water``), so a later write gets a higher ``seq`` even when the
  deleted run owned the top numbers
- A thread with no stream, or nothing to delete, is a no-op that reads once and never
  writes an intent. Run events have no derived (sidecar) steps; canonical cleanup
  of session streams is a separate obligation, not part of this store

Reads stream the thread backwards (``read_stream``) and stop as soon as the query is
answered, and at the newest boundary at the latest, so a long thread is never sent
in full for a tail page, a lookup that resolves near the head, or the next ``seq``.
The next ``seq`` follows from the newest non-survivor event (its ``seq`` is above any
boundary's high water); only when every event since the newest boundary is a
survivor copy does the walk go down to that boundary for its ``seq_high_water``.

Writes run under a per-thread ``asyncio.Lock`` and append with the expected stream
head, so ``seq`` (``seq.next_seq``) is strictly increasing and a writer in another
process loses with a conflict (re-read, re-assign, retry) instead of duplicating a
``seq``. The guarantee is single process, like JSONL: cross-process writers stay
correct but are not coordinated beyond conflicts.

``put_batch`` outcomes: ``RunEventStoreNotCommittedError`` only when every thread group
is proven not committed (rejected before sending, or settled by a fence); otherwise a
plain exception, which ``RunJournal`` quarantines.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import uuid
import weakref
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from deerflow.runtime.events.message_identity import message_identity
from deerflow.runtime.events.store.base import RunEventLifecycleRejected, RunEventStore, RunEventStoreNotCommittedError, match_ai_message_run_id, normalize_message_ids
from deerflow.runtime.user_context import AUTO, _AutoSentinel, get_current_user
from kurrentdbclient import NewEvent, StreamState
from kurrentdbclient.exceptions import NotFoundError, WrongCurrentVersionError

from .._client import async_client_factory
from .._fence import FENCE_EVENT_TYPE, AmbiguousAppendError, asettle_append
from .._naming import RUN_EVENTS_PREFIX, run_events_stream
from .._settings import load_settings
from ..deletions import AsyncDeletionEngine, DeletionConflict, DerivedStep, Intent
from .seq import next_seq, seq_high_water

logger = logging.getLogger(__name__)

RUN_EVENT_TYPE = "deerflow.run-events.RunEvent"
RUNS_COMPACTED_EVENT_TYPE = "deerflow.run-events.RunsCompacted"
THREAD_CLEARED_EVENT_TYPE = "deerflow.run-events.ThreadCleared"
BOUNDARY_EVENT_TYPES = frozenset({RUNS_COMPACTED_EVENT_TYPE, THREAD_CLEARED_EVENT_TYPE})

#: Appends rejected by a conflicting writer are re-read and retried this many times in all.
MAX_APPEND_ATTEMPTS = 5
#: Threads whose stream head is remembered between writes (a miss costs one read).
_HEAD_CACHE_SIZE = 10_000
#: Deletion engines kept, one per client (one client per event loop).
_ENGINE_CACHE_SIZE = 8

_RECORD_FIELDS = ("thread_id", "run_id", "event_type", "category", "content", "metadata", "seq", "created_at")
_REQUIRED_EVENT_KEYS = ("thread_id", "run_id", "event_type", "category")
_VISIBLE_AI_EVENT_TYPES = frozenset({"llm.ai.response", "ai_message"})

_NOT_COMMITTED = "not_committed"
_UNKNOWN = "unknown"


class KurrentRunEventStoreCorruption(RuntimeError):
    """A run-event stream holds undecodable data, an unknown event type, or out-of-order ``seq``."""


class KurrentRunEventWriteError(RuntimeError):
    """A write whose outcome is unknown or partial; never retried (``RunJournal`` quarantines it)."""


class _GroupFailed(Exception):
    def __init__(self, outcome: str, cause: BaseException) -> None:
        super().__init__(str(cause))
        self.outcome = outcome
        self.cause = cause


@dataclass(frozen=True, slots=True)
class _Draft:
    run_id: str
    event_type: str
    category: str
    content: Any
    metadata: dict
    created_at: str
    owner: str | None


@dataclass(slots=True)
class _Walk:
    """What a newest-first walk learned besides the records it yielded."""

    head: int | StreamState | None = None  # the stream head (any event type); None until an event arrives
    missing: bool = False
    high_water: int | None = None  # set when the walk reached the newest boundary
    exhausted: bool = False  # the walk reached the boundary or the start of the readable stream
    seqs: list[int] = field(default_factory=list)


def encode_record(record: Mapping[str, Any], *, user_id: str | None, survivor: bool = False, base_metadata: Mapping[str, Any] | None = None) -> NewEvent:
    """The ``RunEvent`` for a complete record (with ``seq``).

    Deletions write their copies of surviving events with ``survivor=True`` and the
    original event's metadata as ``base_metadata``: a survivor's ``seq`` may sit below
    its boundary's high water, so it never fixes the next ``seq``.
    """
    data = {field: record[field] for field in _RECORD_FIELDS}
    metadata: dict[str, Any] = {**(base_metadata or {}), "user_id": user_id}
    if survivor:
        metadata["survivor"] = True
    return NewEvent(
        id=uuid.uuid4(),
        type=RUN_EVENT_TYPE,
        data=json.dumps(data, default=str, ensure_ascii=False).encode("utf-8"),
        metadata=json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
    )


def _corrupt(event, reason: str) -> KurrentRunEventStoreCorruption:
    return KurrentRunEventStoreCorruption(f"{event.stream_name}@{event.stream_position} ({event.type}): {reason}")


def _decode_json(event) -> Any:
    try:
        return json.loads(event.data)
    except (UnicodeDecodeError, ValueError) as exc:
        raise _corrupt(event, f"undecodable data: {exc}") from exc


def _decode_record(event) -> dict:
    data = _decode_json(event)
    if not isinstance(data, dict) or any(field not in data for field in _RECORD_FIELDS):
        raise _corrupt(event, "not a run-event record")
    seq = data["seq"]
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1 or not isinstance(data["metadata"], dict):
        raise _corrupt(event, "invalid seq or metadata")
    return {field: data[field] for field in _RECORD_FIELDS}


def _decode_boundary(event) -> int:
    data = _decode_json(event)
    high_water = data.get("seq_high_water") if isinstance(data, dict) else None
    if not isinstance(high_water, int) or isinstance(high_water, bool) or high_water < 0:
        raise _corrupt(event, "boundary without a valid seq_high_water")
    return high_water


def _decode_metadata(event) -> dict:
    if not event.metadata:
        return {}
    try:
        metadata = json.loads(event.metadata)
    except (UnicodeDecodeError, ValueError) as exc:
        raise _corrupt(event, f"undecodable metadata: {exc}") from exc
    if not isinstance(metadata, dict):
        raise _corrupt(event, "metadata is not an object")
    return metadata


def _is_survivor(metadata: Mapping[str, Any]) -> bool:
    return metadata.get("survivor") is True


async def _walk(response: Any, walk: _Walk) -> AsyncIterator[tuple[dict, dict]]:
    """Yield ``(record, event metadata)`` newest first, down to the newest boundary; fences are skipped."""
    try:
        async for event in response:
            if walk.head is None:
                walk.head = event.stream_position
            if event.type == FENCE_EVENT_TYPE:
                continue
            if event.type in BOUNDARY_EVENT_TYPES:
                walk.high_water = _decode_boundary(event)
                walk.exhausted = True
                return
            if event.type != RUN_EVENT_TYPE:
                raise _corrupt(event, "unknown event type")
            record = _decode_record(event)
            if walk.seqs and record["seq"] >= walk.seqs[-1]:
                raise _corrupt(event, "seq is not strictly increasing")
            walk.seqs.append(record["seq"])
            yield record, _decode_metadata(event)
    except NotFoundError:
        walk.missing = True
    walk.exhausted = True


async def _nothing() -> AsyncIterator[tuple[dict, dict]]:
    return
    yield


def _advance(head: int | StreamState, count: int) -> int:
    return count - 1 if head is StreamState.NO_STREAM else int(head) + count


def _derive_run_events(intent: Intent) -> list[DerivedStep] | None:
    """Run-event intents have no derived steps; other stores' intents are not ours to recover."""
    return [] if intent.primary_stream.startswith(RUN_EVENTS_PREFIX) else None


def _boundary_event(event_type: str, intent: Intent, **fields: Any) -> NewEvent:
    data = {"intent_id": intent.intent_id, **fields}
    return NewEvent(id=uuid.uuid4(), type=event_type, data=json.dumps(data, ensure_ascii=False).encode("utf-8"))


def _context_owner() -> str | None:
    user = get_current_user()
    return str(user.id) if user is not None else None


def _owner(user_id: str | None | _AutoSentinel) -> str | None:
    if user_id is AUTO or isinstance(user_id, _AutoSentinel):
        return _context_owner()
    return None if user_id is None else str(user_id)


def _draft(*, run_id: str, event_type: str, category: str, content: Any, metadata: dict | None, created_at: str | None, owner: str | None) -> _Draft:
    return _Draft(
        run_id=run_id,
        event_type=event_type,
        category=category,
        content=copy.deepcopy(content),
        metadata=copy.deepcopy(metadata) if metadata is not None else {},
        created_at=created_at or datetime.now(UTC).isoformat(),
        owner=owner,
    )


def _window(items: list[dict], *, limit: int, before_seq: int | None, after_seq: int | None) -> list[dict]:
    if limit <= 0:
        return []
    if after_seq is not None:
        return [item for item in items if item["seq"] > after_seq and (before_seq is None or item["seq"] < before_seq)][:limit]
    if before_seq is not None:
        items = [item for item in items if item["seq"] < before_seq]
    return items[-limit:]


class KurrentRunEventStore(RunEventStore):
    def __init__(self, config: Any, *, client_factory: Callable[[], Awaitable[Any]] | None = None) -> None:
        self._config = config
        settings = load_settings()
        self._timeout = settings.timeout
        self._client_factory = client_factory if client_factory is not None else async_client_factory(settings)
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
        self._heads: dict[str, tuple[int, int]] = {}
        self._engines: dict[int, tuple[Any, AsyncDeletionEngine]] = {}

    def _lock_for(self, thread_id: str) -> asyncio.Lock:
        lock = self._locks.get(thread_id)
        if lock is None:
            lock = self._locks[thread_id] = asyncio.Lock()
        return lock

    def _remember_head(self, thread_id: str, head: int, upcoming_seq: int) -> None:
        self._heads.pop(thread_id, None)
        if len(self._heads) >= _HEAD_CACHE_SIZE:
            self._heads.pop(next(iter(self._heads)))
        self._heads[thread_id] = (head, upcoming_seq)

    # --- reads -----------------------------------------------------------

    @asynccontextmanager
    async def _scan(self, thread_id: str, client: Any = None) -> AsyncIterator[tuple[AsyncIterator[tuple[dict, dict]], _Walk]]:
        """One streaming backwards read; leaving the block stops it, so nothing older is sent."""
        if client is None:
            client = await self._client_factory()
        walk = _Walk()
        try:
            response = await client.read_stream(run_events_stream(thread_id), backwards=True, timeout=self._timeout)
        except NotFoundError:
            walk.missing = walk.exhausted = True
            yield _nothing(), walk
            return
        async with response:
            async with aclosing(_walk(response, walk)) as records:
                yield records, walk

    async def _tail(self, thread_id: str, keep: Callable[[dict], bool], *, limit: int, before_seq: int | None, after_seq: int | None, first: bool) -> list[dict]:
        """Records ``keep`` accepts in ``(after_seq, before_seq)``: the first ``limit`` when ``first``, else the last ``limit``."""
        if limit <= 0:
            return []
        picked: list[dict] = []
        async with self._scan(thread_id) as (records, _walk_state):
            async for record, _metadata in records:
                seq = record["seq"]
                if after_seq is not None and seq <= after_seq:
                    break  # seq only decreases from here
                if before_seq is not None and seq >= before_seq:
                    continue
                if not keep(record):
                    continue
                picked.append(record)
                if not first and len(picked) >= limit:
                    break
        picked.reverse()
        return picked[:limit] if first else picked

    async def _head(self, client: Any, thread_id: str, existing: Callable[[dict], bool] | None) -> tuple[int | StreamState, int, dict | None]:
        """``(head, next seq, existing record)`` from one walk that stops as early as it can."""
        fresh_top: int | None = None
        async with self._scan(thread_id, client) as (records, walk):
            async for record, metadata in records:
                if existing is not None and existing(record):
                    return walk.head, 0, record
                if not _is_survivor(metadata) and fresh_top is None:
                    fresh_top = record["seq"]
                    if existing is None:
                        break  # a non-survivor's seq is above every boundary's high water
        if fresh_top is not None:
            upcoming = fresh_top + 1
        else:
            upcoming = next_seq(walk.high_water or 0, walk.seqs)
        if walk.head is not None:
            return walk.head, upcoming, None
        if walk.missing:
            return StreamState.NO_STREAM, 1, None
        stream = run_events_stream(thread_id)
        try:
            head = await client.get_current_version(stream, timeout=self._timeout)
        except NotFoundError:
            head = StreamState.NO_STREAM
        if head is StreamState.NO_STREAM:
            return head, 1, None
        raise KurrentRunEventStoreCorruption(f"{stream}: the stream exists but nothing is readable, so the next seq is unknown")

    # --- writes ------------------------------------------------------------

    async def _write(self, thread_id: str, drafts: list[_Draft], *, existing: Callable[[dict], bool] | None = None) -> tuple[list[dict], dict | None]:
        """Append ``drafts`` as one atomic append; the caller holds the thread's lock.

        With ``existing``, the stream is read on every attempt and the newest record it
        accepts is handed back instead of writing. Raises ``_GroupFailed`` with the proven outcome.
        """
        stream = run_events_stream(thread_id)
        try:
            client = await self._client_factory()
        except Exception as exc:
            raise _GroupFailed(_NOT_COMMITTED, exc) from exc
        conflict: BaseException | None = None
        for _attempt in range(MAX_APPEND_ATTEMPTS):
            try:
                cached = None if existing is not None else self._heads.get(thread_id)
                if cached is None:
                    head, upcoming, found = await self._head(client, thread_id, existing)
                    if found is not None:
                        return [], found
                else:
                    head, upcoming = cached
            except Exception as exc:
                raise _GroupFailed(_NOT_COMMITTED, exc) from exc

            records = [
                {"thread_id": thread_id, "run_id": d.run_id, "event_type": d.event_type, "category": d.category, "content": d.content, "metadata": d.metadata, "seq": upcoming + offset, "created_at": d.created_at}
                for offset, d in enumerate(drafts)
            ]
            events = [encode_record(record, user_id=d.owner) for record, d in zip(records, drafts)]
            try:
                await client.append_to_stream(stream, events=events, current_version=head, timeout=self._timeout)
            except WrongCurrentVersionError as exc:
                # Definitively rejected: another writer moved the head. Re-read and re-assign.
                self._heads.pop(thread_id, None)
                conflict = exc
                continue
            except Exception as exc:
                self._heads.pop(thread_id, None)
                try:
                    outcome = await asettle_append(client, stream, expected_version=head, own_event_ids={event.id for event in events}, timeout=self._timeout)
                except AmbiguousAppendError as fence_exc:
                    raise _GroupFailed(_UNKNOWN, exc) from fence_exc
                if outcome == "not_committed":
                    raise _GroupFailed(_NOT_COMMITTED, exc) from exc
                return [json.loads(event.data) for event in events], None
            except BaseException:
                self._heads.pop(thread_id, None)
                raise
            self._remember_head(thread_id, _advance(head, len(events)), upcoming + len(events))
            return [json.loads(event.data) for event in events], None
        raise _GroupFailed(_NOT_COMMITTED, RuntimeError(f"{stream}: append conflicted {MAX_APPEND_ATTEMPTS} times with other writers")) from conflict

    async def _after_commit(self, thread_id: str, records: list[dict]) -> None:
        """Seam for live canonical session events; nothing canonical is written yet."""

    async def _notify(self, thread_id: str, records: list[dict]) -> None:
        if not records:
            return
        try:
            await self._after_commit(thread_id, copy.deepcopy(records))
        except Exception:
            logger.warning("Post-commit hook for %d run event(s) of thread %s failed", len(records), thread_id, exc_info=True)

    async def _write_group(self, thread_id: str, drafts: list[_Draft]) -> list[dict]:
        async with self._lock_for(thread_id):
            records, _ = await self._write(thread_id, drafts)
            await self._notify(thread_id, records)
            return records

    @staticmethod
    def _raise_single(failure: _GroupFailed, what: str) -> None:
        if failure.outcome == _NOT_COMMITTED:
            raise RunEventStoreNotCommittedError(f"{what} did not commit: {failure.cause}") from failure.cause
        raise KurrentRunEventWriteError(f"{what} has an unknown outcome: {failure.cause}") from failure.cause

    async def put(self, *, thread_id, run_id, event_type, category, content="", metadata=None, created_at=None):
        draft = _draft(run_id=run_id, event_type=event_type, category=category, content=content, metadata=metadata, created_at=created_at, owner=_context_owner())
        try:
            records = await self._write_group(thread_id, [draft])
        except _GroupFailed as failure:
            self._raise_single(failure, f"run event for {thread_id}/{run_id}")
        return records[0]

    async def put_batch(self, events):
        if not events:
            return []
        groups: dict[str, list[tuple[int, _Draft]]] = {}
        for index, event in enumerate(events):
            missing = [key for key in _REQUIRED_EVENT_KEYS if key not in event]
            if missing:
                raise ValueError(f"put_batch event {index} lacks {', '.join(missing)}")
            draft = _draft(
                run_id=event["run_id"],
                event_type=event["event_type"],
                category=event["category"],
                content=event.get("content", ""),
                metadata=event.get("metadata"),
                created_at=event.get("created_at"),
                owner=_owner(event["user_id"]) if "user_id" in event else _context_owner(),
            )
            groups.setdefault(event["thread_id"], []).append((index, draft))

        results: list[dict | None] = [None] * len(events)
        committed: list[str] = []
        for thread_id, group in groups.items():
            try:
                records = await self._write_group(thread_id, [draft for _, draft in group])
            except _GroupFailed as failure:
                if failure.outcome == _NOT_COMMITTED and not committed:
                    raise RunEventStoreNotCommittedError(f"run-event batch did not commit (thread {thread_id}): {failure.cause}") from failure.cause
                state = "did not commit" if failure.outcome == _NOT_COMMITTED else "has an unknown outcome"
                logger.warning("Run-event batch partially written: threads %s committed, thread %s %s", committed, thread_id, state)
                raise KurrentRunEventWriteError(f"run-event batch partially written: threads {committed} committed, thread {thread_id} {state}: {failure.cause}") from failure.cause
            for (index, _), record in zip(group, records):
                results[index] = record
            committed.append(thread_id)
        return results

    async def put_if_absent(
        self,
        *,
        thread_id,
        run_id,
        event_type,
        category,
        content="",
        metadata=None,
        created_at=None,
        user_id: str | None | _AutoSentinel = AUTO,
        lifecycle_guard=None,
    ):
        draft = _draft(run_id=run_id, event_type=event_type, category=category, content=content, metadata=metadata, created_at=created_at, owner=_owner(user_id))

        def existing(record: dict) -> bool:
            return record["run_id"] == run_id and record["event_type"] == event_type

        async with self._lock_for(thread_id):
            if lifecycle_guard is not None and not await lifecycle_guard():
                raise RunEventLifecycleRejected(f"Run lifecycle no longer admits terminal evidence for {thread_id}/{run_id}")
            try:
                records, found = await self._write(thread_id, [draft], existing=existing)
            except _GroupFailed as failure:
                self._raise_single(failure, f"run event {event_type} for {thread_id}/{run_id}")
            if found is not None:
                return found, False
            await self._notify(thread_id, records)
            return records[0], True

    # --- read API ------------------------------------------------------------

    async def list_messages(self, thread_id, *, limit=50, before_seq=None, after_seq=None, user_id: str | None | _AutoSentinel = AUTO):
        return await self._tail(thread_id, lambda record: record["category"] == "message", limit=limit, before_seq=before_seq, after_seq=after_seq, first=after_seq is not None)

    async def find_latest_ai_message_run_ids(self, thread_id: str, message_ids: set[str], *, user_id: str | None | _AutoSentinel = AUTO) -> dict[str, str]:
        pending = normalize_message_ids(message_ids)
        if not pending:
            return {}
        result: dict[str, str] = {}
        async with self._scan(thread_id) as (records, _walk_state):
            async for record, _metadata in records:
                match = match_ai_message_run_id(record, pending)
                if match is None:
                    continue
                message_id, run_id = match
                result[message_id] = run_id
                pending.discard(message_id)
                if not pending:
                    break
        return result

    async def list_events(self, thread_id, run_id, *, event_types=None, task_id=None, limit=500, after_seq=None, user_id: str | None | _AutoSentinel = AUTO):
        def keep(record: dict) -> bool:
            if record["run_id"] != run_id or (event_types is not None and record["event_type"] not in event_types):
                return False
            return task_id is None or (record.get("metadata") or {}).get("task_id") == task_id

        return await self._tail(thread_id, keep, limit=limit, before_seq=None, after_seq=after_seq, first=True)

    async def list_messages_by_run(self, thread_id, run_id, *, limit=50, before_seq=None, after_seq=None, user_id: str | None | _AutoSentinel = AUTO):
        return await self._tail(thread_id, lambda record: record["run_id"] == run_id and record["category"] == "message", limit=limit, before_seq=before_seq, after_seq=after_seq, first=after_seq is not None)

    async def get_last_visible_ai_seq_by_run(self, thread_id, run_ids, *, user_id: str | None | _AutoSentinel = AUTO):
        wanted = set(run_ids)
        if not wanted:
            return {}
        result: dict[str, int] = {}
        async with self._scan(thread_id) as (records, _walk_state):
            async for record, _metadata in records:
                run_id = record["run_id"]
                if run_id not in wanted or run_id in result:
                    continue
                caller = str((record.get("metadata") or {}).get("caller", ""))
                if record["category"] == "message" and record["event_type"] in _VISIBLE_AI_EVENT_TYPES and not caller.startswith("middleware:"):
                    result[run_id] = record["seq"]
                    if len(result) == len(wanted):
                        break
        return result

    async def count_messages(self, thread_id):
        count = 0
        async with self._scan(thread_id) as (records, _walk_state):
            async for record, _metadata in records:
                count += record["category"] == "message"
        return count

    async def get_message_seqs(self, thread_id, identities, *, user_id: str | None | _AutoSentinel = AUTO):
        wanted = set(identities)
        if not wanted:
            return {}
        found: dict[str, int] = {}
        async with self._scan(thread_id) as (records, _walk_state):
            async for record, _metadata in records:
                if record["category"] != "message" or not isinstance(record["content"], dict):
                    continue
                identity = message_identity(record["content"])
                # Earliest seq wins: walking newest first, an older copy overwrites a newer one.
                if identity in wanted:
                    found[identity] = record["seq"]
        return found

    # --- deletions -----------------------------------------------------------

    def _engine(self, client: Any) -> AsyncDeletionEngine:
        """One deletion engine per client (the engine caches the index fold it read through that client)."""
        known = self._engines.get(id(client))
        if known is not None and known[0] is client:
            return known[1]
        if len(self._engines) >= _ENGINE_CACHE_SIZE:
            self._engines.pop(next(iter(self._engines)))
        engine = AsyncDeletionEngine(client, timeout=self._timeout, derive=_derive_run_events)
        self._engines[id(client)] = (client, engine)
        return engine

    async def _live(self, client: Any, thread_id: str) -> tuple[int, int, list[tuple[dict, dict]]] | None:
        """``(head, seq high water, live (record, metadata) oldest first)``, or ``None`` when the stream is missing."""
        items: list[tuple[dict, dict]] = []
        async with self._scan(thread_id, client) as (records, walk):
            async for item in records:
                items.append(item)
        if walk.head is None:
            if walk.missing:
                return None
            stream = run_events_stream(thread_id)
            try:
                head = await client.get_current_version(stream, timeout=self._timeout)
            except NotFoundError:
                return None
            if head is StreamState.NO_STREAM:
                return None
            raise KurrentRunEventStoreCorruption(f"{stream}: the stream exists but nothing is readable, so the seq high water is unknown")
        items.reverse()
        return int(walk.head), seq_high_water(walk.high_water or 0, walk.seqs), items

    async def _head_moved(self, client: Any, thread_id: str, head: int) -> bool:
        try:
            current = await client.get_current_version(run_events_stream(thread_id), timeout=self._timeout)
        except NotFoundError:
            return True
        return current != head

    async def _delete(self, thread_id: str, op: str, criteria: dict[str, Any], doomed: Callable[[dict], bool], boundary_type: str, boundary_fields: dict[str, Any]) -> int:
        """Write one deletion boundary (plus survivor copies) through the deletion engine; returns the count removed."""
        stream = run_events_stream(thread_id)
        async with self._lock_for(thread_id):
            client = await self._client_factory()
            live = await self._live(client, thread_id)
            if live is None or not any(doomed(record) for record, _ in live[2]):
                return 0  # nothing to delete: no intent, no write
            engine = self._engine(client)
            self._heads.pop(thread_id, None)
            # Settle earlier open deletions first; a recovery fence moves the head, so re-read then.
            await engine.recover_primary(stream)
            conflict: DeletionConflict | None = None
            for attempt in range(MAX_APPEND_ATTEMPTS):
                if attempt or await self._head_moved(client, thread_id, live[0]):
                    live = await self._live(client, thread_id)
                    if live is None or not any(doomed(record) for record, _ in live[2]):
                        return 0
                head, high_water, items = live
                removed = [record for record, _ in items if doomed(record)]
                survivors = [encode_record(record, user_id=metadata.get("user_id"), survivor=True, base_metadata=metadata) for record, metadata in items if not doomed(record)]
                intent = Intent.new(op, {**criteria, "seq_high_water": high_water, "cutoff": high_water + 1}, stream, head)
                events = [_boundary_event(boundary_type, intent, seq_high_water=high_water, deleted=len(removed), **boundary_fields), *survivors]
                try:
                    await engine.run(intent, lambda: events, [])
                except DeletionConflict as exc:
                    # Another writer (or a recovery fence) took the position; the intent is abandoned.
                    conflict = exc
                    continue
                self._remember_head(thread_id, head + len(events), high_water + 1)
                return len(removed)
            assert conflict is not None
            raise conflict

    async def delete_by_thread(self, thread_id, *, user_id: str | None | _AutoSentinel = AUTO):
        """Clear the thread with a ``ThreadCleared`` boundary; returns the number of live events removed.

        The store is not user-scoped (like memory/JSONL): ``user_id`` is accepted in
        all three states for interface parity and every owner's events are removed.
        """
        return await self._delete(thread_id, "delete_thread", {"thread_id": thread_id}, lambda record: True, THREAD_CLEARED_EVENT_TYPE, {})

    async def delete_by_run(self, thread_id, run_id, *, user_id: str | None | _AutoSentinel = AUTO):
        """Remove one run with a ``RunsCompacted`` boundary plus survivor copies; ``user_id`` as in ``delete_by_thread``."""
        return await self._delete(thread_id, "delete_run", {"thread_id": thread_id, "run_id": run_id}, lambda record: record["run_id"] == run_id, RUNS_COMPACTED_EVENT_TYPE, {"run_id": run_id})

    async def recover_deletions(self) -> list[Intent]:
        """Finish or abandon every open run-event deletion (startup); returns the intents still open."""
        client = await self._client_factory()
        try:
            return await self._engine(client).recover_primary()
        finally:
            self._heads.clear()  # a recovery fence may have moved a cached head
