"""Crash-safe deletions: intents in ``DELETIONS_STREAM`` and the primary side of each deletion.

Appends and ``$tb`` (truncate-before) are separate writes, and a deletion touches
up to three streams (primary, sidecar, canonical), so every deletion is first an
intent in the index stream ``deerflow.kurrent-deletions``; every later step is
derived from the intent, so any process can finish it:

1. append ``DeletionIntended{intent_id, op, criteria, primary_stream, expected_position, created_at}``
2. append the primary boundary at expected version ``expected_position``; its first
   event's JSON data carries ``intent_id``, and the boundary's position is
   ``expected_position + 1``
3. run the derived steps (the memory sidecar boundary): each is idempotent and
   returns the position of its own boundary in its stream (or ``None``)
4. canonical cleanup: not here (``CanonicalCleanup*`` events are defined for it)
5. raise ``$tb`` on every derived stream, then on the primary stream, to their
   boundaries: only ever raised, written with the metadata stream's expected version
6. append ``DeletionDone``

A caller hears success once step 2 committed. Steps 3–6 are best-effort in the
call (a failure is logged and leaves the intent open) and finished by
``recover_primary``, which runs at startup and before primary writes:

- boundary present (the event at its position carries the intent id) → finish
  steps 3, 5 and 6 idempotently
- another event at that position → the boundary can never commit → ``DeletionAbandoned``
- nothing there yet → settle with a ``deerflow.Fence`` at ``expected_position``:
  the fence lands → ``DeletionAbandoned``; it is rejected → look again. Absence
  alone never abandons an intent

A new deletion of a stream first completes every open primary side of that
stream. It refuses to start (``DeletionBlocked``) while an earlier boundary is
unsettled; an earlier intent whose boundary committed but whose derived steps
keep failing (a sidecar outage) does not block it, but every intent defers its
step 5 and 6 until the earlier intents of its stream are closed, and recovery
finishes them in index order. So ``$tb`` is raised in deletion order and never
hides an open intent's boundary or removal evidence.

Index events are keyed by intent (deterministic event ids) and commute, so they are
appended with ``StreamState.ANY``; a duplicate or a re-append is harmless.
``DeletionEngine`` and ``AsyncDeletionEngine`` share the pure logic below, as
``_fence`` does.
"""

from __future__ import annotations

import inspect
import json
import logging
import threading
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from kurrentdbclient import NewEvent, StreamState
from kurrentdbclient.exceptions import NotFoundError, WrongCurrentVersionError

from ._fence import FENCE_EVENT_TYPE, AmbiguousAppendError, _fence_event, asettle_append, settle_append
from ._naming import DELETIONS_STREAM

logger = logging.getLogger(__name__)

PREFIX = "deerflow.deletions."
DELETION_INTENDED = f"{PREFIX}DeletionIntended"
DELETION_DONE = f"{PREFIX}DeletionDone"
DELETION_ABANDONED = f"{PREFIX}DeletionAbandoned"
CANONICAL_CLEANUP_DONE = f"{PREFIX}CanonicalCleanupDone"
CANONICAL_CLEANUP_REOPENED = f"{PREFIX}CanonicalCleanupReopened"
CANONICAL_CLEANUP_VERIFIED = f"{PREFIX}CanonicalCleanupVerified"
INDEX_EVENT_TYPES = frozenset({DELETION_INTENDED, DELETION_DONE, DELETION_ABANDONED, CANONICAL_CLEANUP_DONE, CANONICAL_CLEANUP_REOPENED, CANONICAL_CLEANUP_VERIFIED})

OPS = frozenset({"delete_facts", "clear_agent", "clear_all", "delete_run", "delete_thread"})
# Attempts to raise one $tb across concurrent metadata writers.
TB_ATTEMPTS = 5

BoundaryStatus = Literal["present", "superseded", "missing", "truncated"]


class DeletionError(Exception):
    """A deletion did not reach its boundary; the caller must not report success."""


class DeletionConflict(DeletionError):
    """The boundary definitively did not commit (the stream moved, or it was fenced off)."""


class DeletionOutcomeUnknown(DeletionError):
    """Whether the boundary committed is unknown; the intent stays open for recovery."""


class DeletionBlocked(DeletionError):
    """An earlier deletion of the same stream is open and its boundary could not be settled."""


class DeletionIndexError(DeletionError):
    """The deletions index could not be read or written (step 1)."""


@dataclass(frozen=True)
class Intent:
    intent_id: str
    op: str
    criteria: dict[str, Any]
    primary_stream: str
    expected_position: int
    created_at: str

    @classmethod
    def new(cls, op: str, criteria: Mapping[str, Any], primary_stream: str, expected_position: int) -> Intent:
        if op not in OPS:
            raise ValueError(f"unknown deletion op {op!r}")
        if isinstance(expected_position, bool) or not isinstance(expected_position, int) or expected_position < 0:
            raise ValueError("a deletion needs the primary stream's head as expected_position")
        created_at = datetime.now(UTC).isoformat().removesuffix("+00:00") + "Z"
        return cls(str(uuid.uuid4()), op, dict(criteria), primary_stream, expected_position, created_at)

    @property
    def boundary_position(self) -> int:
        return self.expected_position + 1

    def payload(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "op": self.op,
            "criteria": self.criteria,
            "primary_stream": self.primary_stream,
            "expected_position": self.expected_position,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class DerivedStep:
    """One idempotent primary-side step in ``stream``: ``run(intent)`` returns its boundary's position (for ``$tb``) or ``None``."""

    stream: str
    run: Callable[[Intent], int | None | Awaitable[int | None]]


# ``derive(intent)``: the derived steps of an intent this engine may recover, ``None`` for an intent it does not own.
Deriver = Callable[[Intent], list[DerivedStep] | None]


def _owns_nothing(intent: Intent) -> None:
    return None


# --- pure logic shared by both engines ------------------------------------------------


def index_event(event_type: str, intent_id: str, **extra: Any) -> NewEvent:
    """An index event; its id is derived from the intent and type, so re-appends are recognisable."""
    data = {"intent_id": intent_id, **extra}
    return NewEvent(id=uuid.uuid5(uuid.UUID(intent_id), event_type), type=event_type, data=json.dumps(data, ensure_ascii=False).encode("utf-8"), content_type="application/json")


def intended_event(intent: Intent) -> NewEvent:
    return NewEvent(id=uuid.uuid5(uuid.UUID(intent.intent_id), DELETION_INTENDED), type=DELETION_INTENDED, data=json.dumps(intent.payload(), ensure_ascii=False).encode("utf-8"), content_type="application/json")


def _decode(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return None


def _parse_intent(data: Any) -> Intent | None:
    if not isinstance(data, dict):
        return None
    try:
        intent = Intent(str(data["intent_id"]), str(data["op"]), dict(data["criteria"]), str(data["primary_stream"]), int(data["expected_position"]), str(data.get("created_at") or ""))
        uuid.UUID(intent.intent_id)
    except (KeyError, TypeError, ValueError):
        return None
    return intent


@dataclass
class IndexState:
    """The fold of the deletions index: every intent in index order, and which are closed."""

    position: int | None = None
    intents: dict[str, Intent] = field(default_factory=dict)
    closed: set[str] = field(default_factory=set)
    canonical: dict[str, list[str]] = field(default_factory=dict)

    def apply(self, recorded: Any) -> None:
        if self.position is not None and recorded.stream_position <= self.position:
            return
        self.position = recorded.stream_position
        if recorded.type == FENCE_EVENT_TYPE:
            return
        data = _decode(recorded.data)
        if recorded.type not in INDEX_EVENT_TYPES or not isinstance(data, dict) or not isinstance(data.get("intent_id"), str):
            logger.warning("Ignoring unreadable deletion index event %r at position %s", recorded.type, recorded.stream_position)
            return
        intent_id = data["intent_id"]
        if recorded.type == DELETION_INTENDED:
            intent = _parse_intent(data)
            if intent is None:
                logger.warning("Ignoring malformed DeletionIntended at position %s", recorded.stream_position)
                return
            self.intents.setdefault(intent_id, intent)
        elif recorded.type in (DELETION_DONE, DELETION_ABANDONED):
            self.closed.add(intent_id)
        else:
            self.canonical.setdefault(intent_id, []).append(recorded.type)

    def open(self, stream: str | None = None) -> list[Intent]:
        return [intent for intent_id, intent in self.intents.items() if intent_id not in self.closed and (stream is None or intent.primary_stream == stream)]

    def open_before(self, intent: Intent) -> list[Intent]:
        """The open intents of ``intent``'s stream recorded before it."""
        earlier = []
        for other in self.open(intent.primary_stream):
            if other.intent_id == intent.intent_id:
                break
            earlier.append(other)
        return earlier


def boundary_status(recorded: Iterable[Any], intent: Intent) -> BoundaryStatus:
    """What a read of one event at the boundary's position says about the boundary."""
    events = list(recorded)
    if not events:
        return "missing"
    first = events[0]
    if first.stream_position != intent.boundary_position:
        return "truncated" if first.stream_position > intent.boundary_position else "missing"
    data = _decode(first.data)
    return "present" if isinstance(data, dict) and data.get("intent_id") == intent.intent_id else "superseded"


def check_boundary(boundary: list[NewEvent], intent: Intent) -> None:
    if not boundary:
        raise ValueError("a deletion boundary needs at least one event")
    data = _decode(boundary[0].data)
    if not isinstance(data, dict) or data.get("intent_id") != intent.intent_id:
        raise ValueError("the first boundary event's data must carry the intent's intent_id")


def tb_update(metadata: Mapping[str, Any], position: int) -> dict[str, Any] | None:
    """The metadata with ``$tb`` raised to ``position``, or ``None`` when it is already there or higher."""
    current = metadata.get("$tb")
    if isinstance(current, int) and not isinstance(current, bool) and current >= position:
        return None
    return {**metadata, "$tb": position}


def _head_of(head: Any) -> int | None:
    return None if isinstance(head, StreamState) else int(head)


# --- sync engine ---------------------------------------------------------------------


class DeletionEngine:
    """Steps 1–3 and 5–6 of a deletion, and primary-side recovery, over a sync client."""

    def __init__(self, client: Any, *, timeout: float, derive: Deriver | None = None):
        self._client = client
        self._timeout = timeout
        self._derive = derive or _owns_nothing
        self._lock = threading.RLock()
        self._index = IndexState()
        self._committed: set[str] = set()

    # --- index -------------------------------------------------------------------

    def _refresh_index(self) -> IndexState:
        with self._lock:
            try:
                head = _head_of(self._client.get_current_version(DELETIONS_STREAM, timeout=self._timeout))
            except NotFoundError:
                head = None
            if head is None or head == self._index.position:
                return self._index
            start = 0 if self._index.position is None else self._index.position + 1
            try:
                recorded = self._client.get_stream(DELETIONS_STREAM, stream_position=start, timeout=self._timeout)
            except NotFoundError:
                recorded = ()
            for event in recorded:
                self._index.apply(event)
            return self._index

    def _open(self, stream: str | None = None) -> list[Intent]:
        """The open intents after a head-checked refresh; computed under the lock (threads share the index)."""
        with self._lock:
            return self._refresh_index().open(stream)

    def _open_before(self, intent: Intent) -> list[Intent]:
        with self._lock:
            return self._refresh_index().open_before(intent)

    def _append_index(self, event: NewEvent) -> None:
        self._client.append_to_stream(DELETIONS_STREAM, events=[event], current_version=StreamState.ANY, timeout=self._timeout)

    def _close(self, event_type: str, intent: Intent) -> None:
        self._append_index(index_event(event_type, intent.intent_id))
        with self._lock:
            self._index.closed.add(intent.intent_id)

    def _abandon(self, intent: Intent) -> None:
        try:
            self._close(DELETION_ABANDONED, intent)
        except Exception:
            logger.warning("Recording deletion %s as abandoned failed; recovery will do it", intent.intent_id, exc_info=True)

    # --- boundary ----------------------------------------------------------------

    def _status(self, intent: Intent) -> BoundaryStatus:
        if intent.intent_id in self._committed:
            return "present"
        try:
            recorded = self._client.get_stream(intent.primary_stream, stream_position=intent.boundary_position, limit=1, timeout=self._timeout)
        except NotFoundError:
            recorded = ()
        status = boundary_status(recorded, intent)
        if status == "present":
            self._committed.add(intent.intent_id)
        return status

    def open_intents_for(self, stream: str) -> list[Intent]:
        """The open intents of ``stream`` whose primary boundary is committed, in index order."""
        return [intent for intent in self._open(stream) if self._status(intent) == "present"]

    # --- $tb -----------------------------------------------------------------------

    def raise_truncate_before(self, stream: str, position: int) -> None:
        """Raise ``stream``'s ``$tb`` to ``position``; never lowers it."""
        for _ in range(TB_ATTEMPTS):
            metadata, version = self._client.get_stream_metadata(stream, timeout=self._timeout)
            updated = tb_update(metadata, position)
            if updated is None:
                return
            try:
                self._client.set_stream_metadata(stream, metadata=updated, current_version=version, timeout=self._timeout)
                return
            except WrongCurrentVersionError:
                continue
        raise RuntimeError(f"raising $tb of {stream!r} kept conflicting with concurrent metadata writes")

    # --- protocol ------------------------------------------------------------------

    def _finish(self, intent: Intent, steps: list[DerivedStep]) -> bool:
        """Steps 3, 5 and 6, idempotently; ``False`` (logged) when one failed and the intent stays open.

        Steps 5 and 6 wait until every earlier intent of the stream is closed.
        """
        try:
            boundaries = [(step.stream, step.run(intent)) for step in steps]
            if self._open_before(intent):
                logger.info("Deletion %s of %r waits for earlier deletions of the stream", intent.intent_id, intent.primary_stream)
                return False
            for stream, position in boundaries:
                if position is not None:
                    self.raise_truncate_before(stream, position)
            self.raise_truncate_before(intent.primary_stream, intent.boundary_position)
            self._close(DELETION_DONE, intent)
        except Exception:
            logger.warning("Completing the primary side of deletion %s of %r failed; it stays open", intent.intent_id, intent.primary_stream, exc_info=True)
            return False
        return True

    def _recover(self, intent: Intent, steps: list[DerivedStep]) -> bool:
        try:
            status = self._status(intent)
            if status == "missing":
                try:
                    self._client.append_to_stream(intent.primary_stream, events=[_fence_event()], current_version=intent.expected_position, timeout=self._timeout)
                    status = "superseded"
                except WrongCurrentVersionError:
                    status = self._status(intent)
        except Exception:
            logger.warning("Settling deletion %s of %r failed; it stays open", intent.intent_id, intent.primary_stream, exc_info=True)
            return False
        if status == "present":
            return self._finish(intent, steps)
        if status == "superseded":
            self._abandon(intent)
            return True
        logger.warning("Deletion %s of %r: its boundary position is truncated or still unsettled; it stays open", intent.intent_id, intent.primary_stream)
        return False

    def recover_primary(self, stream: str | None = None) -> list[Intent]:
        """Finish or abandon the open intents of ``stream`` (every stream for ``None``); returns those still open."""
        remaining: list[Intent] = []
        for intent in self._open(stream):
            steps = self._derive(intent)
            if steps is None:
                if stream is not None:
                    remaining.append(intent)
                continue
            if not self._recover(intent, steps):
                remaining.append(intent)
        return remaining

    def run(self, intent: Intent, build_boundary: Callable[[], list[NewEvent]], derived_steps: list[DerivedStep]) -> None:
        """Delete: returns once the boundary committed; raises ``DeletionError`` when it did not (or may not have)."""
        try:
            if any(self._status(earlier) != "present" for earlier in self.recover_primary(intent.primary_stream)):
                raise DeletionBlocked(f"an earlier deletion of {intent.primary_stream!r} is still unsettled")
            self._append_index(intended_event(intent))
        except DeletionError:
            raise
        except Exception as exc:
            raise DeletionIndexError(f"recording deletion {intent.intent_id} failed: {exc}") from exc
        boundary = list(build_boundary())
        try:
            check_boundary(boundary, intent)
        except ValueError:
            # Nothing reached the primary stream: the intent can never commit.
            self._abandon(intent)
            raise
        try:
            self._client.append_to_stream(intent.primary_stream, events=boundary, current_version=intent.expected_position, timeout=self._timeout)
        except WrongCurrentVersionError as exc:
            self._abandon(intent)
            raise DeletionConflict(f"{intent.primary_stream!r} moved past {intent.expected_position}") from exc
        except Exception as exc:
            try:
                outcome = settle_append(self._client, intent.primary_stream, expected_version=intent.expected_position, own_event_ids={event.id for event in boundary}, timeout=self._timeout)
            except AmbiguousAppendError as ambiguous:
                raise DeletionOutcomeUnknown(f"boundary of deletion {intent.intent_id}: {ambiguous}") from exc
            if outcome == "not_committed":
                self._abandon(intent)
                raise DeletionConflict(f"boundary of deletion {intent.intent_id} did not commit and was fenced off") from exc
        self._committed.add(intent.intent_id)
        self._finish(intent, derived_steps)


# --- async engine --------------------------------------------------------------------


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class AsyncDeletionEngine:
    """``DeletionEngine`` over an async client; derived steps may be sync or async."""

    def __init__(self, client: Any, *, timeout: float, derive: Deriver | None = None):
        self._client = client
        self._timeout = timeout
        self._derive = derive or _owns_nothing
        self._index = IndexState()
        self._committed: set[str] = set()

    async def _refresh_index(self) -> IndexState:
        try:
            head = _head_of(await self._client.get_current_version(DELETIONS_STREAM, timeout=self._timeout))
        except NotFoundError:
            head = None
        if head is None or head == self._index.position:
            return self._index
        start = 0 if self._index.position is None else self._index.position + 1
        try:
            recorded = await self._client.get_stream(DELETIONS_STREAM, stream_position=start, timeout=self._timeout)
        except NotFoundError:
            recorded = ()
        for event in recorded:
            self._index.apply(event)
        return self._index

    async def _append_index(self, event: NewEvent) -> None:
        await self._client.append_to_stream(DELETIONS_STREAM, events=[event], current_version=StreamState.ANY, timeout=self._timeout)

    async def _close(self, event_type: str, intent: Intent) -> None:
        await self._append_index(index_event(event_type, intent.intent_id))
        self._index.closed.add(intent.intent_id)

    async def _abandon(self, intent: Intent) -> None:
        try:
            await self._close(DELETION_ABANDONED, intent)
        except Exception:
            logger.warning("Recording deletion %s as abandoned failed; recovery will do it", intent.intent_id, exc_info=True)

    async def _status(self, intent: Intent) -> BoundaryStatus:
        if intent.intent_id in self._committed:
            return "present"
        try:
            recorded = await self._client.get_stream(intent.primary_stream, stream_position=intent.boundary_position, limit=1, timeout=self._timeout)
        except NotFoundError:
            recorded = ()
        status = boundary_status(recorded, intent)
        if status == "present":
            self._committed.add(intent.intent_id)
        return status

    async def open_intents_for(self, stream: str) -> list[Intent]:
        index = await self._refresh_index()
        return [intent for intent in index.open(stream) if await self._status(intent) == "present"]

    async def raise_truncate_before(self, stream: str, position: int) -> None:
        for _ in range(TB_ATTEMPTS):
            metadata, version = await self._client.get_stream_metadata(stream, timeout=self._timeout)
            updated = tb_update(metadata, position)
            if updated is None:
                return
            try:
                await self._client.set_stream_metadata(stream, metadata=updated, current_version=version, timeout=self._timeout)
                return
            except WrongCurrentVersionError:
                continue
        raise RuntimeError(f"raising $tb of {stream!r} kept conflicting with concurrent metadata writes")

    async def _finish(self, intent: Intent, steps: list[DerivedStep]) -> bool:
        try:
            boundaries = [(step.stream, await _maybe_await(step.run(intent))) for step in steps]
            if (await self._refresh_index()).open_before(intent):
                logger.info("Deletion %s of %r waits for earlier deletions of the stream", intent.intent_id, intent.primary_stream)
                return False
            for stream, position in boundaries:
                if position is not None:
                    await self.raise_truncate_before(stream, position)
            await self.raise_truncate_before(intent.primary_stream, intent.boundary_position)
            await self._close(DELETION_DONE, intent)
        except Exception:
            logger.warning("Completing the primary side of deletion %s of %r failed; it stays open", intent.intent_id, intent.primary_stream, exc_info=True)
            return False
        return True

    async def _recover(self, intent: Intent, steps: list[DerivedStep]) -> bool:
        try:
            status = await self._status(intent)
            if status == "missing":
                try:
                    await self._client.append_to_stream(intent.primary_stream, events=[_fence_event()], current_version=intent.expected_position, timeout=self._timeout)
                    status = "superseded"
                except WrongCurrentVersionError:
                    status = await self._status(intent)
        except Exception:
            logger.warning("Settling deletion %s of %r failed; it stays open", intent.intent_id, intent.primary_stream, exc_info=True)
            return False
        if status == "present":
            return await self._finish(intent, steps)
        if status == "superseded":
            await self._abandon(intent)
            return True
        logger.warning("Deletion %s of %r: its boundary position is truncated or still unsettled; it stays open", intent.intent_id, intent.primary_stream)
        return False

    async def recover_primary(self, stream: str | None = None) -> list[Intent]:
        remaining: list[Intent] = []
        for intent in (await self._refresh_index()).open(stream):
            steps = self._derive(intent)
            if steps is None:
                if stream is not None:
                    remaining.append(intent)
                continue
            if not await self._recover(intent, steps):
                remaining.append(intent)
        return remaining

    async def run(self, intent: Intent, build_boundary: Callable[[], list[NewEvent]], derived_steps: list[DerivedStep]) -> None:
        try:
            for earlier in await self.recover_primary(intent.primary_stream):
                if await self._status(earlier) != "present":
                    raise DeletionBlocked(f"an earlier deletion of {intent.primary_stream!r} is still unsettled")
            await self._append_index(intended_event(intent))
        except DeletionError:
            raise
        except Exception as exc:
            raise DeletionIndexError(f"recording deletion {intent.intent_id} failed: {exc}") from exc
        boundary = list(build_boundary())
        try:
            check_boundary(boundary, intent)
        except ValueError:
            await self._abandon(intent)
            raise
        try:
            await self._client.append_to_stream(intent.primary_stream, events=boundary, current_version=intent.expected_position, timeout=self._timeout)
        except WrongCurrentVersionError as exc:
            await self._abandon(intent)
            raise DeletionConflict(f"{intent.primary_stream!r} moved past {intent.expected_position}") from exc
        except Exception as exc:
            try:
                outcome = await asettle_append(self._client, intent.primary_stream, expected_version=intent.expected_position, own_event_ids={event.id for event in boundary}, timeout=self._timeout)
            except AmbiguousAppendError as ambiguous:
                raise DeletionOutcomeUnknown(f"boundary of deletion {intent.intent_id}: {ambiguous}") from exc
            if outcome == "not_committed":
                await self._abandon(intent)
                raise DeletionConflict(f"boundary of deletion {intent.intent_id} did not commit and was fenced off") from exc
        self._committed.add(intent.intent_id)
        await self._finish(intent, derived_steps)
