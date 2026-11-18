"""Canonical cleanup (deletion step 4) and its verification pass.

A deletion's canonical side is an obligation in the deletions index, separate
from its primary side and never on a caller's path. It starts only once the
intent's primary boundary is proven present (``canonical_obligations`` lists only
those), so an intent that is later fenced off and abandoned never touches
canonical data.

**Cleanup** of the canonical stream ``C`` of an intent's primary stream
(``agent_memory_stream("deerflow", user)`` or ``agent_session_stream(thread)``):

1. read ``C`` from ``$tb`` to its head ``H``
2. select survivors: drop every event that a **primary-committed** intent of the
   same primary stream covers (its criteria, origin below its exclusive cutoff;
   ``mapping.matches``), not just this one, and keep one copy per DeerFlow
   identity (``identity``)
3. nothing readable: done. No survivors: soft-delete ``C`` conditionally,
   ``delete_stream(current_version=H)``. Survivors already the readable tail (for
   instance a retry after a failed ``$tb``, or only covered events before live
   ones): raise ``$tb`` to that tail. Otherwise append copies of the survivors at
   expected version ``H`` (fresh event ids, the original data, type and metadata
   plus ``deerflow.intent_id``) and raise ``$tb`` to the first copy
4. a conflict (a live event or another cleanup landed after the read) re-reads
   and reselects, so a valid live event is never lost
5. ``CanonicalCleanupDone{head, done_at}``: ``head`` is the stream's last position
   the cleanup accounted for

**Verification**: a stale emitter (one that passed its pre-check before the
deletion committed) can still append for ``MAX_LIFETIME_SECONDS`` after its
primary commit, and its post-append check may fail or never run. So once that
lifetime plus one ``settings.timeout`` (clock skew between processes) has passed
since ``done_at``, the stream is re-read after ``head``: an event the intent
covers means ``CanonicalCleanupReopened`` and a new cleanup; otherwise
``CanonicalCleanupVerified`` closes the obligation. Canonical reads stop returning
deleted content once the intent is verified.

Every failure is logged at WARNING and leaves the obligation open for the next
pass (recovery service, or the next deletion or write of the stream). The
global memory scope has no canonical stream: its intents are verified at once.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from kurrentdbclient import NewEvent
from kurrentdbclient.exceptions import NotFoundError, WrongCurrentVersionError

from .. import deletions
from .._naming import RUN_EVENTS_PREFIX, memory_user_of
from . import emitter, mapping

logger = logging.getLogger(__name__)

#: Reads and reselects of one cleanup across conflicting canonical writers.
CLEANUP_ATTEMPTS = 5
#: A cleanup that failed is not retried by write-triggered kicks for this long (the recovery service still retries).
KICK_BACKOFF_SECONDS = 30.0

Clock = Callable[[], float]


# --- pure -----------------------------------------------------------------------


def canonical_stream_of(intent: deletions.Intent) -> str | None:
    """The canonical stream an intent's primary stream feeds, or ``None`` (the global memory scope has none)."""
    if intent.primary_stream.startswith(RUN_EVENTS_PREFIX):
        thread_id = intent.criteria.get("thread_id")
        return mapping.session_stream(thread_id) if isinstance(thread_id, str) else None
    is_memory, user_id = memory_user_of(intent.primary_stream)
    return mapping.memory_stream(user_id) if is_memory else None


def event_metadata(recorded: Any) -> dict[str, Any]:
    try:
        metadata = json.loads(recorded.metadata) if recorded.metadata else {}
    except (UnicodeDecodeError, ValueError):
        return {}
    return metadata if isinstance(metadata, dict) else {}


def identity(metadata: Mapping[str, Any]) -> tuple[Any, ...] | None:
    """The DeerFlow identity of a canonical event, kept once across copies; ``None`` when it has none.

    A fact version (agent, fact id, revision, origin), or a session event (run id,
    seq, event type): ``SessionStarted`` has a seq and no run id, and shares its seq
    with the record it precedes, so the event type tells them apart.
    """
    if mapping.FACT_ID in metadata:
        return ("fact", metadata.get(mapping.AGENT), metadata.get(mapping.FACT_ID), metadata.get(mapping.FACT_REVISION), metadata.get(mapping.ORIGIN))
    if mapping.SEQ in metadata:
        return ("session", metadata.get(mapping.RUN_ID), metadata.get(mapping.SEQ), metadata.get(mapping.EVENT_TYPE))
    return None


def _key(recorded: Any, metadata: Mapping[str, Any]) -> tuple[Any, ...]:
    return identity(metadata) or ("id", str(recorded.id))


@dataclass(frozen=True)
class Selection:
    """What a cleanup read: the head, the survivors (with their metadata) and, when they already are the readable tail, where it starts."""

    head: int | None
    survivors: list[tuple[Any, dict[str, Any]]]
    tail_start: int | None


def select(recorded: Iterable[Any], intents: Sequence[Any]) -> Selection:
    readable = list(recorded)
    seen: set[tuple[Any, ...]] = set()
    survivors: list[tuple[Any, dict[str, Any]]] = []
    for event in readable:
        metadata = event_metadata(event)
        if any(mapping.matches_intent(intent, metadata) for intent in intents):
            continue
        key = _key(event, metadata)
        if key in seen:
            continue
        seen.add(key)
        survivors.append((event, metadata))
    head = readable[-1].stream_position if readable else None
    tail_start = None
    if survivors:
        tail = readable[len(readable) - len(survivors) :]
        if [_key(event, event_metadata(event)) for event in tail] == [_key(event, metadata) for event, metadata in survivors]:
            tail_start = tail[0].stream_position
    return Selection(head, survivors, tail_start)


def copies(selection: Selection, intent: deletions.Intent) -> list[NewEvent]:
    """Survivor copies: fresh ids (canonical ids are deterministic and would be deduped), original data and metadata plus ``deerflow.intent_id``."""
    return [
        NewEvent(
            id=uuid.uuid4(),
            type=event.type,
            data=event.data,
            metadata=json.dumps({**metadata, mapping.INTENT_ID: intent.intent_id}, ensure_ascii=False, default=str).encode("utf-8"),
            content_type=event.content_type or "application/json",
        )
        for event, metadata in selection.survivors
    ]


@dataclass(frozen=True)
class CleanupStep:
    """One cleanup attempt's decision, from what it read; the sync and async cleaners only perform it.

    - ``done``: nothing readable
    - ``delete``: no survivors, soft-delete at ``expected``
    - ``truncate``: the survivors already are the readable tail, raise ``$tb`` to ``first``
    - ``append``: append ``events`` (survivor copies) at ``expected``, then raise ``$tb`` to ``first``

    ``done_head`` is the ``head`` recorded in ``CanonicalCleanupDone`` once the step succeeded.
    """

    action: str
    expected: int | None = None
    first: int | None = None
    events: tuple[NewEvent, ...] = ()
    done_head: int | None = None


def plan_cleanup(recorded: Iterable[Any], intents: Sequence[Any], intent: deletions.Intent) -> CleanupStep:
    """Decide one cleanup attempt of ``intent``'s canonical stream: ``recorded`` is what it read, ``intents`` every primary-committed intent of the primary stream."""
    selection = select(recorded, intents)
    head = selection.head
    if head is None:
        return CleanupStep("done")
    if not selection.survivors:
        return CleanupStep("delete", expected=head, done_head=head)
    if selection.tail_start is not None:
        return CleanupStep("truncate", first=selection.tail_start, done_head=head)
    new_events = tuple(copies(selection, intent))
    return CleanupStep("append", expected=head, first=head + 1, events=new_events, done_head=head + len(new_events))


def verification_start(done_data: Mapping[str, Any] | None) -> int:
    """Where verification re-reads the canonical stream: right after the cleanup's recorded head (the whole stream without one)."""
    head = _done_head(done_data)
    return 0 if head is None else head + 1


def verification_due(done_data: Mapping[str, Any] | None, timeout: float) -> float:
    """When a done cleanup may be verified: its ``done_at`` plus the maximum emitter lifetime and one timeout of clock-skew margin."""
    done_at = (done_data or {}).get("done_at")
    if isinstance(done_at, bool) or not isinstance(done_at, (int, float)):
        done_at = 0.0
    return float(done_at) + emitter.MAX_LIFETIME_SECONDS + timeout


def _done_head(done_data: Mapping[str, Any] | None) -> int | None:
    head = (done_data or {}).get("head")
    return head if isinstance(head, int) and not isinstance(head, bool) else None


def _stale(recorded: Iterable[Any], intent: deletions.Intent) -> Any | None:
    return next((event for event in recorded if mapping.matches_intent(intent, event_metadata(event))), None)


@dataclass
class PassReport:
    """One pass over the canonical obligations: what happened, and when the next verification is due (``None``: none waiting)."""

    cleaned: int = 0
    verified: int = 0
    reopened: int = 0
    failed: int = 0
    next_due: float | None = None

    def wait_for(self, due: float) -> None:
        self.next_due = due if self.next_due is None else min(self.next_due, due)


# --- sync -----------------------------------------------------------------------


class CanonicalCleaner:
    """Runs the canonical obligations of the intents ``engine()`` owns, over a sync client; never raises."""

    def __init__(self, client: Callable[[], Any], engine: Callable[[], Any], *, timeout: float, clock: Clock | None = None):
        self._client = client
        self._engine = engine
        self._timeout = timeout
        self._clock = clock or time.time
        self._lock = threading.Lock()
        self._failed_at: dict[str, float] = {}

    def backing_off(self, stream: str) -> bool:
        failed_at = self._failed_at.get(stream)
        return failed_at is not None and time.monotonic() - failed_at < KICK_BACKOFF_SECONDS

    def run(self, *, stream: str | None = None, verify: bool = True) -> PassReport:
        """One pass, in index order: clean pending obligations, verify done ones that are due (``verify``)."""
        report = PassReport()
        with self._lock:
            try:
                obligations = self._engine().canonical_obligations()
            except Exception:
                logger.warning("Listing canonical cleanup obligations failed; the next pass retries", exc_info=True)
                report.failed += 1
                return report
            for obligation in obligations:
                if stream is not None and obligation.intent.primary_stream != stream:
                    continue
                if obligation.state == "pending":
                    self._count(report, self._clean(obligation.intent), "cleaned")
                elif verify:
                    self._verify(obligation, report)
        return report

    def _count(self, report: PassReport, ok: bool, field: str) -> None:
        if ok:
            setattr(report, field, getattr(report, field) + 1)
        else:
            report.failed += 1

    def _clean(self, intent: deletions.Intent) -> bool:
        try:
            ok = self._clean_once(intent)
        except Exception:
            logger.warning("Canonical cleanup of deletion %s failed; it stays open", intent.intent_id, exc_info=True)
            ok = False
        if ok:
            self._failed_at.pop(intent.primary_stream, None)
        else:
            self._failed_at[intent.primary_stream] = time.monotonic()
        return ok

    def _clean_once(self, intent: deletions.Intent) -> bool:
        engine, client = self._engine(), self._client()
        canonical = canonical_stream_of(intent)
        if canonical is None:
            engine.record_canonical(deletions.CANONICAL_CLEANUP_VERIFIED, intent, reason="no canonical stream")
            return True
        for _attempt in range(CLEANUP_ATTEMPTS):
            intents = engine.committed_intents_for(intent.primary_stream)
            try:
                recorded = client.get_stream(canonical, timeout=self._timeout)
            except NotFoundError:
                recorded = ()
            step = plan_cleanup(recorded, intents, intent)
            try:
                if step.action == "delete":
                    client.delete_stream(canonical, current_version=step.expected, timeout=self._timeout)
                elif step.action == "append":
                    client.append_to_stream(canonical, events=list(step.events), current_version=step.expected, timeout=self._timeout)
            except (WrongCurrentVersionError, NotFoundError):
                continue  # a live event or another cleanup landed after the read: reselect
            if step.first is not None:
                engine.raise_truncate_before(canonical, step.first)
            engine.record_canonical(deletions.CANONICAL_CLEANUP_DONE, intent, head=step.done_head, done_at=self._clock())
            return True
        logger.warning("Canonical cleanup of deletion %s kept conflicting with other writers; it stays open", intent.intent_id)
        return False

    def _verify(self, obligation: deletions.CanonicalObligation, report: PassReport) -> None:
        intent = obligation.intent
        due = verification_due(obligation.done_data, self._timeout)
        if self._clock() < due:
            report.wait_for(due)
            return
        try:
            canonical = canonical_stream_of(intent)
            try:
                recorded = self._client().get_stream(canonical, stream_position=verification_start(obligation.done_data), timeout=self._timeout) if canonical else ()
            except NotFoundError:
                recorded = ()
            stale = _stale(recorded, intent)
            if stale is None:
                self._engine().record_canonical(deletions.CANONICAL_CLEANUP_VERIFIED, intent)
                report.verified += 1
                return
            logger.info("Verification of deletion %s found a stale canonical event in %r; reopening its cleanup", intent.intent_id, canonical)
            self._engine().reopen_canonical(intent, str(stale.id))
        except Exception:
            logger.warning("Verifying the canonical cleanup of deletion %s failed; the next pass retries", intent.intent_id, exc_info=True)
            report.failed += 1
            return
        report.reopened += 1
        self._count(report, self._clean(intent), "cleaned")


# --- async ----------------------------------------------------------------------


class AsyncCanonicalCleaner:
    """``CanonicalCleaner`` over an async client; ``engine(client)`` is the owning store's ``AsyncDeletionEngine``."""

    def __init__(self, client: Callable[[], Any], engine: Callable[[Any], Any], *, timeout: float, clock: Clock | None = None):
        self._client = client
        self._engine = engine
        self._timeout = timeout
        self._clock = clock or time.time
        self._locks: dict[int, asyncio.Lock] = {}
        self._failed_at: dict[str, float] = {}

    def backing_off(self, stream: str) -> bool:
        failed_at = self._failed_at.get(stream)
        return failed_at is not None and time.monotonic() - failed_at < KICK_BACKOFF_SECONDS

    def _lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        lock = self._locks.get(id(loop))
        if lock is None:
            for key in [key for key in self._locks if key != id(loop)]:
                self._locks.pop(key)
            lock = self._locks[id(loop)] = asyncio.Lock()
        return lock

    async def run(self, *, stream: str | None = None, verify: bool = True) -> PassReport:
        report = PassReport()
        async with self._lock():
            try:
                client = await self._client()
                engine = self._engine(client)
                obligations = await engine.canonical_obligations()
            except Exception:
                logger.warning("Listing canonical cleanup obligations failed; the next pass retries", exc_info=True)
                report.failed += 1
                return report
            for obligation in obligations:
                if stream is not None and obligation.intent.primary_stream != stream:
                    continue
                if obligation.state == "pending":
                    self._count(report, await self._clean(client, engine, obligation.intent), "cleaned")
                elif verify:
                    await self._verify(client, engine, obligation, report)
        return report

    _count = CanonicalCleaner._count

    async def _clean(self, client: Any, engine: Any, intent: deletions.Intent) -> bool:
        try:
            ok = await self._clean_once(client, engine, intent)
        except Exception:
            logger.warning("Canonical cleanup of deletion %s failed; it stays open", intent.intent_id, exc_info=True)
            ok = False
        if ok:
            self._failed_at.pop(intent.primary_stream, None)
        else:
            self._failed_at[intent.primary_stream] = time.monotonic()
        return ok

    async def _clean_once(self, client: Any, engine: Any, intent: deletions.Intent) -> bool:
        canonical = canonical_stream_of(intent)
        if canonical is None:
            await engine.record_canonical(deletions.CANONICAL_CLEANUP_VERIFIED, intent, reason="no canonical stream")
            return True
        for _attempt in range(CLEANUP_ATTEMPTS):
            intents = await engine.committed_intents_for(intent.primary_stream)
            try:
                recorded = await client.get_stream(canonical, timeout=self._timeout)
            except NotFoundError:
                recorded = ()
            step = plan_cleanup(recorded, intents, intent)
            try:
                if step.action == "delete":
                    await client.delete_stream(canonical, current_version=step.expected, timeout=self._timeout)
                elif step.action == "append":
                    await client.append_to_stream(canonical, events=list(step.events), current_version=step.expected, timeout=self._timeout)
            except (WrongCurrentVersionError, NotFoundError):
                continue  # a live event or another cleanup landed after the read: reselect
            if step.first is not None:
                await engine.raise_truncate_before(canonical, step.first)
            await engine.record_canonical(deletions.CANONICAL_CLEANUP_DONE, intent, head=step.done_head, done_at=self._clock())
            return True
        logger.warning("Canonical cleanup of deletion %s kept conflicting with other writers; it stays open", intent.intent_id)
        return False

    async def _verify(self, client: Any, engine: Any, obligation: deletions.CanonicalObligation, report: PassReport) -> None:
        intent = obligation.intent
        due = verification_due(obligation.done_data, self._timeout)
        if self._clock() < due:
            report.wait_for(due)
            return
        try:
            canonical = canonical_stream_of(intent)
            try:
                recorded = await client.get_stream(canonical, stream_position=verification_start(obligation.done_data), timeout=self._timeout) if canonical else ()
            except NotFoundError:
                recorded = ()
            stale = _stale(recorded, intent)
            if stale is None:
                await engine.record_canonical(deletions.CANONICAL_CLEANUP_VERIFIED, intent)
                report.verified += 1
                return
            logger.info("Verification of deletion %s found a stale canonical event in %r; reopening its cleanup", intent.intent_id, canonical)
            await engine.reopen_canonical(intent, str(stale.id))
        except Exception:
            logger.warning("Verifying the canonical cleanup of deletion %s failed; the next pass retries", intent.intent_id, exc_info=True)
            report.failed += 1
            return
        report.reopened += 1
        self._count(report, await self._clean(client, engine, intent), "cleaned")
