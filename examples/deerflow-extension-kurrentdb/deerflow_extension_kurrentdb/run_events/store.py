"""``RunEventStore`` over one KurrentDB stream per thread, ``deerflow.run-events-{enc(thread_id)}``.

Event schema (every event's data and metadata are JSON):

- ``deerflow.run-events.RunEvent``: data is the full record envelope (``thread_id``,
  ``run_id``, ``event_type``, ``category``, ``content``, ``metadata``, ``seq``,
  ``created_at``); metadata is ``{"user_id": <owner or null>}``. ``user_id`` is
  recorded, never used to filter: the store is not user-scoped, like memory/JSONL
- ``deerflow.run-events.RunsCompacted`` / ``deerflow.run-events.ThreadCleared``:
  deletion boundaries, data ``{"seq_high_water": int, ...}``. Reads fold from the
  newest boundary forward; events before it are gone (written by deletions)
- ``deerflow.Fence``: written only to settle an ambiguous append; ignored by reads

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
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from deerflow.runtime.events.message_identity import message_identity
from deerflow.runtime.events.store.base import RunEventLifecycleRejected, RunEventStore, RunEventStoreNotCommittedError, match_ai_message_run_id, normalize_message_ids
from deerflow.runtime.user_context import AUTO, _AutoSentinel, get_current_user
from kurrentdbclient import NewEvent, StreamState
from kurrentdbclient.exceptions import NotFoundError, WrongCurrentVersionError

from .._client import async_client_factory
from .._fence import FENCE_EVENT_TYPE, AmbiguousAppendError, asettle_append
from .._naming import run_events_stream
from .._settings import load_settings
from .seq import next_seq

logger = logging.getLogger(__name__)

RUN_EVENT_TYPE = "deerflow.run-events.RunEvent"
RUNS_COMPACTED_EVENT_TYPE = "deerflow.run-events.RunsCompacted"
THREAD_CLEARED_EVENT_TYPE = "deerflow.run-events.ThreadCleared"
BOUNDARY_EVENT_TYPES = frozenset({RUNS_COMPACTED_EVENT_TYPE, THREAD_CLEARED_EVENT_TYPE})

#: Appends rejected by a conflicting writer are re-read and retried this many times in all.
MAX_APPEND_ATTEMPTS = 5
#: Threads whose stream head is remembered between writes (a miss costs one read).
_HEAD_CACHE_SIZE = 10_000

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


@dataclass(frozen=True, slots=True)
class _Snapshot:
    records: list[dict]
    head: int | StreamState
    next_seq: int | None  # None: the stream exists but nothing is readable, so the high water is unknown


def encode_record(record: Mapping[str, Any], *, user_id: str | None) -> NewEvent:
    """The ``RunEvent`` for a complete record (with ``seq``); deletions reuse it for survivors."""
    data = {field: record[field] for field in _RECORD_FIELDS}
    return NewEvent(
        id=uuid.uuid4(),
        type=RUN_EVENT_TYPE,
        data=json.dumps(data, default=str, ensure_ascii=False).encode("utf-8"),
        metadata=json.dumps({"user_id": user_id}, ensure_ascii=False).encode("utf-8"),
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


def _fold(recorded: Sequence[Any]) -> _Snapshot:
    """Fold a backwards read (newest first) down to the newest boundary."""
    newest_first: list[dict] = []
    high_water = 0
    for event in recorded:
        if event.type == FENCE_EVENT_TYPE:
            continue
        if event.type in BOUNDARY_EVENT_TYPES:
            high_water = _decode_boundary(event)
            break
        if event.type != RUN_EVENT_TYPE:
            raise _corrupt(event, "unknown event type")
        newest_first.append(_decode_record(event))
    records = newest_first[::-1]
    seqs = [record["seq"] for record in records]
    if any(later <= earlier for earlier, later in zip(seqs, seqs[1:])):
        raise KurrentRunEventStoreCorruption(f"{recorded[0].stream_name}: seq is not strictly increasing")
    return _Snapshot(records=records, head=recorded[0].stream_position, next_seq=next_seq(high_water, seqs))


def _advance(head: int | StreamState, count: int) -> int:
    return count - 1 if head is StreamState.NO_STREAM else int(head) + count


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

    async def _read(self, client: Any, thread_id: str) -> _Snapshot:
        """One backwards read of the whole stream (down to ``$tb``), folded from the newest boundary."""
        stream = run_events_stream(thread_id)
        try:
            recorded = await client.get_stream(stream, backwards=True, timeout=self._timeout)
        except NotFoundError:
            return _Snapshot(records=[], head=StreamState.NO_STREAM, next_seq=1)
        if recorded:
            return _fold(recorded)
        head = await client.get_current_version(stream, timeout=self._timeout)
        return _Snapshot(records=[], head=head, next_seq=1 if head is StreamState.NO_STREAM else None)

    async def _records(self, thread_id: str) -> list[dict]:
        client = await self._client_factory()
        return (await self._read(client, thread_id)).records

    # --- writes ------------------------------------------------------------

    async def _write(self, thread_id: str, drafts: list[_Draft], *, existing: Callable[[list[dict]], dict | None] | None = None) -> tuple[list[dict], dict | None]:
        """Append ``drafts`` as one atomic append; the caller holds the thread's lock.

        With ``existing``, the stream is read on every attempt and a record it returns
        is handed back instead of writing. Raises ``_GroupFailed`` with the proven outcome.
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
                    snapshot = await self._read(client, thread_id)
                    if existing is not None:
                        found = existing(snapshot.records)
                        if found is not None:
                            return [], found
                    if snapshot.next_seq is None:
                        raise KurrentRunEventStoreCorruption(f"{stream}: the stream exists but nothing is readable, so the next seq is unknown")
                    head, upcoming = snapshot.head, snapshot.next_seq
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

        def existing(records: list[dict]) -> dict | None:
            return next((record for record in records if record["run_id"] == run_id and record["event_type"] == event_type), None)

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
        messages = [record for record in await self._records(thread_id) if record["category"] == "message"]
        return _window(messages, limit=limit, before_seq=before_seq, after_seq=after_seq)

    async def find_latest_ai_message_run_ids(self, thread_id: str, message_ids: set[str], *, user_id: str | None | _AutoSentinel = AUTO) -> dict[str, str]:
        pending = normalize_message_ids(message_ids)
        if not pending:
            return {}
        result: dict[str, str] = {}
        for record in reversed(await self._records(thread_id)):
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
        events = [record for record in await self._records(thread_id) if record["run_id"] == run_id]
        if event_types is not None:
            events = [record for record in events if record["event_type"] in event_types]
        if task_id is not None:
            events = [record for record in events if (record.get("metadata") or {}).get("task_id") == task_id]
        if after_seq is not None:
            events = [record for record in events if record["seq"] > after_seq]
        return events[:limit] if limit > 0 else []

    async def list_messages_by_run(self, thread_id, run_id, *, limit=50, before_seq=None, after_seq=None, user_id: str | None | _AutoSentinel = AUTO):
        messages = [record for record in await self._records(thread_id) if record["run_id"] == run_id and record["category"] == "message"]
        return _window(messages, limit=limit, before_seq=before_seq, after_seq=after_seq)

    async def get_last_visible_ai_seq_by_run(self, thread_id, run_ids, *, user_id: str | None | _AutoSentinel = AUTO):
        wanted = set(run_ids)
        if not wanted:
            return {}
        result: dict[str, int] = {}
        for record in reversed(await self._records(thread_id)):
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
        return sum(1 for record in await self._records(thread_id) if record["category"] == "message")

    async def get_message_seqs(self, thread_id, identities, *, user_id: str | None | _AutoSentinel = AUTO):
        wanted = set(identities)
        if not wanted:
            return {}
        found: dict[str, int] = {}
        for record in await self._records(thread_id):
            if record["category"] != "message" or not isinstance(record["content"], dict):
                continue
            identity = message_identity(record["content"])
            # Earliest seq wins: a message re-persisted later keeps its first position.
            if identity in wanted and identity not in found:
                found[identity] = record["seq"]
                if len(found) == len(wanted):
                    break
        return found

    # --- deletions -----------------------------------------------------------

    async def delete_by_thread(self, thread_id, *, user_id: str | None | _AutoSentinel = AUTO):
        raise NotImplementedError("KurrentRunEventStore.delete_by_thread is not implemented yet")

    async def delete_by_run(self, thread_id, run_id, *, user_id: str | None | _AutoSentinel = AUTO):
        raise NotImplementedError("KurrentRunEventStore.delete_by_run is not implemented yet")
