"""``KurrentdbMemoryStorage``: DeerMem's ``MemoryStorage`` as an event-sourced KurrentDB stream.

Configure it with ``memory.backend_config.storage_class:
deerflow_extension_kurrentdb.memory.KurrentdbMemoryStorage``. DeerMem constructs it
from that dotted path, so its settings come only from the environment (see
``_settings``); missing settings fail at construction, which never connects.

One stream per user scope (``_naming.memory_stream``) holds the global summaries
and every agent's facts, so its position is the scope's single manifest revision:
``revision`` = last stream position + 1, 0 when the stream does not exist. A save
is one append with ``current_version`` = revision - 1 (``NO_STREAM`` for 0); a
wrong expected version is ``MemoryManifestRevisionConflict``, and an append whose
outcome is unknown is settled by ``_fence.settle_append`` and never re-appended.

``save``, ``apply_changes`` and ``clear_all`` are planned against the fold
(``changes``) and written as one append each; a no-op appends nothing. Plans that
delete facts or clear a scope are deletions (``deletions.DeletionEngine``): an
intent in the deletions index, then one ``MemorySnapshot`` boundary of the
resulting state carrying the intent id, then the sidecar boundary and ``$tb`` on
the sidecar and primary streams. Sidecar-only clears (``clear_fact_metadata``,
``clear_all`` of an already-empty scope) are
``clear_metadata`` deletions whose boundary keeps the state. Before every primary
write the open deletions of that scope are completed (``recover_deletions`` does the same at startup).

``load()`` and ``reload()`` serve a per-scope cache but check the stream head on
every call and fold only the new events; a head behind the cache or a truncation
re-reads from the newest snapshot. DeerMem calls storage from timer threads, so
each scope's cache and writes are guarded by a per-scope lock; reads wait at most
one timeout for it, so a write stuck on an unreachable server cannot hold them.

The sidecars (fact usage, eviction evidence, extraction watermarks; see
``sidecars``) live in the scope's memory-meta stream and are best-effort, as in
the file storage: a sidecar failure is logged and never fails a memory read or
write. Usage is one ``StreamState.ANY`` append per call, never read first.
Deletions replace the sidecar stream's state with a ``MetadataSnapshot`` boundary
without the removed records, and reads drop every record a primary-committed
deletion intent's criteria match below its cutoff (``intents_provider``, by default
the engine's ``committed_intents_for``: open or done, never abandoned). So a
cleanup interrupted after the primary boundary never resurrects removed records,
and neither does a sidecar append from another process that read the primary
revision before the deletion and landed after its cleanup closed it (sidecar
appends are ``StreamState.ANY``, and scope locks are process-local). The intent
index is cached incrementally, so this costs no read beyond its head check, and
intents whose cutoff is at or below every record's revision are skipped; the
filtered view is reused while neither the sidecar fold nor the intents change. Usage is
also dropped for ids that are not facts in the current fold.
"""

from __future__ import annotations

import contextlib
import copy
import logging
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import UTC, datetime
from typing import Any, NamedTuple

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.eviction import FactEvictionDecision
from deerflow.agents.memory.backends.deermem.deermem.core.paths import DEFAULT_AGENT_BUCKET, validate_agent_name
from deerflow.agents.memory.backends.deermem.deermem.core.storage import DOCUMENT_VERSION, MemoryManifestRevisionConflict, MemoryStorage, MemoryStorageCorruption
from deerflow.agents.memory.manager import MemoryReadError
from kurrentdbclient import NewEvent, StreamState
from kurrentdbclient.exceptions import NotFoundError, WrongCurrentVersionError

from .._client import sync_client_factory
from .._fence import AmbiguousAppendError, settle_append
from .._naming import memory_meta_stream, memory_meta_stream_of, memory_stream
from .._settings import load_settings
from ..canonical import cleanup as canonical_cleanup
from ..canonical import emitter as canonical_emitter
from ..canonical import mapping as canonical_mapping
from ..deletions import DeletionConflict, DeletionEngine, DeletionError, DerivedStep, Intent
from . import changes, events, sidecars
from .changes import Plan
from .fold import MemoryState
from .sidecars import SidecarState

logger = logging.getLogger(__name__)

# Events per backwards page when looking for the newest snapshot.
READ_PAGE_SIZE = 256
# Attempts of one change set across manifest conflicts it may retry (as the file storage).
CHANGE_SET_ATTEMPTS = 3
# Sidecar events after the newest snapshot at which a write compacts the stream into a new snapshot.
SIDECAR_SNAPSHOT_EVERY = 256
# Attempts of one sidecar snapshot across concurrent sidecar appends.
SIDECAR_SNAPSHOT_ATTEMPTS = 3

IntentsProvider = Callable[[str], Iterable[Mapping[str, Any]]]


@contextlib.contextmanager
def _no_lock() -> Iterator[None]:
    yield


class KurrentdbMemoryReadError(MemoryReadError):
    """KurrentDB could not be read (transport, timeout), or a write's outcome is unknown."""


class _Recorded(NamedTuple):
    type: str
    data: bytes
    stream_position: int


class KurrentdbMemoryStorage(MemoryStorage):
    def __init__(self, config: DeerMemConfig, *, client_factory: Callable[[], Any] | None = None, intents_provider: IntentsProvider | None = None, clock: Callable[[], float] | None = None):
        """``intents_provider(primary_stream)`` returns the criteria of the primary-committed
        deletion intents of that memory stream, open or done; sidecar reads drop every
        record they match. It defaults to the deletion engine's ``committed_intents_for``. ``clock`` (wall-clock
        seconds, default ``time.time``) times canonical cleanup verification.
        """
        self._config = config
        self._intents_provider = intents_provider if intents_provider is not None else self._committed_intent_criteria
        self._engine_instance: DeletionEngine | None = None
        self._meta_states: dict[str, SidecarState] = {}
        # Per meta stream: the folded state and intents of the last filtered view, and that view.
        self._meta_views: dict[str, tuple[SidecarState, list[Mapping[str, Any]], SidecarState]] = {}
        self._settings = load_settings()
        self._timeout = self._settings.timeout
        self._client_factory = client_factory if client_factory is not None else sync_client_factory(self._settings)
        self._locks_guard = threading.Lock()
        self._scope_locks: dict[str, threading.RLock] = {}
        self._states: dict[str, MemoryState] = {}
        self._canonical_enabled = self._settings.canonical_events
        self._canonical_queue = canonical_emitter.BackgroundQueue()
        self._canonical = canonical_emitter.CanonicalEmitter(self._client, self._engine, timeout=self._timeout)
        self._cleaner = canonical_cleanup.CanonicalCleaner(self._client, self._engine, timeout=self._timeout, clock=clock)

    # --- scope ------------------------------------------------------------------

    def _stream(self, agent_name: str | None, user_id: str | None) -> str:
        if user_id is None and getattr(self._config, "strict_user_scope", False):
            raise ValueError("user_id is required when strict_user_scope is enabled.")
        if user_id is not None and not user_id:
            raise ValueError("user_id must be a non-empty string.")
        if agent_name is not None:
            validate_agent_name(agent_name)
        return memory_stream(user_id)

    def _scope_lock(self, stream: str) -> threading.RLock:
        with self._locks_guard:
            return self._scope_locks.setdefault(stream, threading.RLock())

    @contextlib.contextmanager
    def _read_lock(self, stream: str) -> Iterator[None]:
        """The scope lock for a read, waited for at most the timeout.

        A writer holds the lock across several sequential calls, each with its own
        deadline; a read must not queue behind all of them while KurrentDB is
        unreachable, so it gives up with ``KurrentdbMemoryReadError`` instead.
        """
        lock = self._scope_lock(stream)
        if not lock.acquire(timeout=self._timeout):
            raise KurrentdbMemoryReadError(f"Timed out after {self._timeout}s waiting for a write to {stream!r} to finish")
        try:
            yield
        finally:
            lock.release()

    # --- deletions ----------------------------------------------------------------

    def _engine(self) -> DeletionEngine:
        with self._locks_guard:
            if self._engine_instance is None:
                self._engine_instance = DeletionEngine(self._client(), timeout=self._timeout, derive=self._derive)
            return self._engine_instance

    def _derive(self, intent: Intent) -> list[DerivedStep] | None:
        """The memory sidecar step of an intent on a memory stream; ``None`` for other streams."""
        meta = memory_meta_stream_of(intent.primary_stream)
        return None if meta is None else [DerivedStep(meta, self._sidecar_cleanup)]

    def _committed_intent_criteria(self, primary: str) -> list[dict[str, Any]]:
        return [intent.criteria for intent in self._engine().committed_intents_for(primary)]

    def recover_deletions(self, stream: str | None = None) -> list[Intent]:
        """Finish or abandon open memory deletions (all scopes for ``None``); returns those still open."""
        with self._scope_lock(stream) if stream is not None else _no_lock():
            return self._engine().recover_primary(stream)

    def _recover_before_write(self, stream: str) -> None:
        """Complete the scope's open deletions before a primary write; best-effort. Caller holds the scope lock."""
        try:
            self._engine().recover_primary(stream)
        except Exception:
            logger.warning("Completing open deletions of %r before a write failed", stream, exc_info=True)

    def _sidecar_cleanup(self, intent: Intent) -> int | None:
        """Step 3: the sidecar boundary without the records the intent's criteria match; idempotent.

        Returns the position of the sidecar stream's newest snapshot (for ``$tb``),
        ``None`` when it has none and nothing to remove. Raises when the cleanup
        could not be written, so the intent stays open.
        """
        meta = memory_meta_stream_of(intent.primary_stream)
        if meta is None:
            return None
        with self._scope_lock(intent.primary_stream), self._scope_lock(meta):
            for _ in range(SIDECAR_SNAPSHOT_ATTEMPTS):
                state = self._refresh_meta(meta)
                survivors = state.without(intent.criteria).snapshot_state()
                if survivors == state.snapshot_state():
                    return state.snapshot_position
                snapshot = sidecars.new_event(sidecars.METADATA_SNAPSHOT, {"agent": None, "revision": None, "intent_id": intent.intent_id, "state": survivors})
                if self._meta_snapshot(meta, state.position, snapshot):
                    return 0 if state.position is None else state.position + 1
        raise RuntimeError(f"sidecar cleanup of {meta!r} kept conflicting with concurrent writes")

    # --- reads ------------------------------------------------------------------

    def _client(self) -> Any:
        try:
            return self._client_factory()
        except Exception as exc:
            raise KurrentdbMemoryReadError(f"KurrentDB client unavailable: {exc}") from exc

    def _head(self, client: Any, stream: str) -> int | None:
        try:
            head = client.get_current_version(stream, timeout=self._timeout)
        except NotFoundError:
            return None
        except Exception as exc:
            raise KurrentdbMemoryReadError(f"Reading the head of {stream!r} failed: {exc}") from exc
        return None if isinstance(head, StreamState) else int(head)

    def _get_stream(self, client: Any, stream: str, **kwargs: Any) -> tuple[Any, ...]:
        try:
            return tuple(client.get_stream(stream, timeout=self._timeout, **kwargs))
        except NotFoundError:
            return ()
        except Exception as exc:
            raise KurrentdbMemoryReadError(f"Reading {stream!r} failed: {exc}") from exc

    def _since_newest_snapshot(self, client: Any, stream: str, boundary: str = events.MEMORY_SNAPSHOT) -> list[Any]:
        """The stream's events from its newest ``boundary`` event (or its first event) forward."""
        collected: list[Any] = []
        position: int | None = None
        while True:
            page = self._get_stream(client, stream, stream_position=position, backwards=True, limit=READ_PAGE_SIZE)
            for event in page:
                collected.append(event)
                if event.type == boundary:
                    return collected[::-1]
            if len(page) < READ_PAGE_SIZE or page[-1].stream_position == 0:
                return collected[::-1]
            position = page[-1].stream_position - 1

    @staticmethod
    def _fold(state: MemoryState, recorded: list[Any] | tuple[Any, ...]) -> MemoryState:
        for event in recorded:
            state.apply(event)
        return state

    def _full_read(self, client: Any, stream: str) -> MemoryState:
        return self._fold(MemoryState(), self._since_newest_snapshot(client, stream))

    def _refresh(self, stream: str) -> MemoryState:
        """The scope's current state: cached when the head has not moved. Caller holds the scope lock."""
        client = self._client()
        cached = self._states.get(stream)
        if cached is None:
            state = self._full_read(client, stream)
        else:
            head = self._head(client, stream)
            if head is None:
                state = cached if cached.position is None else MemoryState()
            elif head == cached.position:
                return cached
            elif cached.position is None or head > cached.position:
                start = 0 if cached.position is None else cached.position + 1
                new = self._get_stream(client, stream, stream_position=start)
                if new and new[0].stream_position != start and new[0].type != events.MEMORY_SNAPSHOT:
                    # Truncated past the cache without a snapshot first: re-read from scratch.
                    state = self._full_read(client, stream)
                else:
                    state = self._fold(cached.copy(), new)
            else:
                state = self._full_read(client, stream)
        self._states[stream] = state
        return state

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        stream = self._stream(agent_name, user_id)
        with self._read_lock(stream):
            return self._refresh(stream).to_document(agent_name)

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Same as ``load``: the cache is checked against the stream head on every call, so it is
        never stale, and a head behind the cache or a truncation re-reads from the newest snapshot."""
        return self.load(agent_name, user_id=user_id)

    # --- writes -----------------------------------------------------------------

    def save(
        self,
        memory_data: dict[str, Any],
        agent_name: str | None = None,
        *,
        user_id: str | None = None,
        expected_revision: int | None = None,
    ) -> bool:
        """Full-replacement save, diffed into one change set (one append).

        As in ``FileMemoryStorage``: summaries persist only on ``agent_name=None``
        saves, an agent save replaces that agent's facts (omitted facts are
        deleted), invalid input or corrupt state returns ``False``, and revision
        conflicts raise. Read failures and unknown append outcomes raise
        ``KurrentdbMemoryReadError``.
        """
        try:
            facts_raw = self._validate_save(memory_data, agent_name)
            stream = self._stream(agent_name, user_id)
            with self._scope_lock(stream):
                self._recover_before_write(stream)
                state = self._refresh(stream)
                if expected_revision is not None and expected_revision != state.revision:
                    raise MemoryManifestRevisionConflict(f"Expected user-memory revision {expected_revision}, found {state.revision}")
                self._commit(stream, state, changes.plan_save(state, memory_data, facts_raw, agent_name=agent_name, user_id=user_id), user_id=user_id)
        except (ValueError, MemoryStorageCorruption) as exc:
            logger.error("Failed to save KurrentDB memory scope (user=%r, agent=%r): %s", user_id, agent_name, exc)
            return False
        return True

    @staticmethod
    def _validate_save(memory_data: Any, agent_name: str | None) -> list[dict[str, Any]]:
        if not isinstance(memory_data, dict):
            raise ValueError("memory_data must be an object")
        if agent_name is not None and "facts" not in memory_data:
            raise ValueError("memory_data.facts is required for an agent full save")
        facts_raw = memory_data.get("facts", [])
        if not isinstance(facts_raw, list):
            raise ValueError("memory_data.facts must be a list")
        if any(not isinstance(fact, dict) for fact in facts_raw):
            raise ValueError("memory_data.facts must contain only fact objects")
        if agent_name is None and facts_raw:
            raise ValueError("agent_name is required to persist facts")
        return copy.deepcopy(facts_raw)

    def _append(self, stream: str, state: MemoryState, new_events: list[NewEvent]) -> MemoryState | None:
        """One atomic append at the folded head; settles unknown outcomes by fencing. Caller holds the scope lock.

        Returns the committed state, or ``None`` when the append created the
        stream (its positions are only known after a read).
        """
        expected: int | StreamState = StreamState.NO_STREAM if state.position is None else state.position
        client = self._client()
        try:
            client.append_to_stream(stream, events=new_events, current_version=expected, timeout=self._timeout)
        except WrongCurrentVersionError as exc:
            raise MemoryManifestRevisionConflict(f"User-memory revision moved past {state.revision}") from exc
        except Exception as exc:
            try:
                outcome = settle_append(client, stream, expected_version=expected, own_event_ids={event.id for event in new_events}, timeout=self._timeout)
            except AmbiguousAppendError as ambiguous:
                raise KurrentdbMemoryReadError(f"Outcome of a memory append to {stream!r} is unknown: {ambiguous}") from exc
            if outcome == "not_committed":
                raise MemoryManifestRevisionConflict(f"Memory append to {stream!r} did not commit and was fenced off") from exc
            logger.info("Memory append to %r committed despite a lost acknowledgement (%s)", stream, exc)
        if state.position is None:
            # A stream recreated after a soft delete continues its old positions: read them back.
            self._states.pop(stream, None)
            return None
        committed = self._fold(state.copy(), self._recorded(state, new_events))
        self._states[stream] = committed
        return committed

    @staticmethod
    def _recorded(state: MemoryState, new_events: list[NewEvent]) -> list[_Recorded]:
        """``new_events`` as if recorded right after ``state``'s position."""
        start = 0 if state.position is None else state.position + 1
        return [_Recorded(event.type, event.data, start + index) for index, event in enumerate(new_events)]

    def _commit(self, stream: str, state: MemoryState, plan: Plan, *, user_id: str | None) -> MemoryState | None:
        """Write one plan as one append (nothing for a no-op); returns the committed state as ``_append`` does. Caller holds the scope lock."""
        if not plan.changes:
            return state
        if plan.criteria is None:
            new_events = events.new_change_set(plan.changes)
            committed = self._append(stream, state, new_events)
        else:
            new_events = []
            committed = self._commit_destructive(stream, state, plan, user_id=user_id)
        self._schedule_canonical(stream, state, plan, committed, new_events, user_id=user_id)
        self._kick_canonical_cleanup(stream, deleted=plan.criteria is not None)
        return committed

    # --- canonical events ---------------------------------------------------------

    def _schedule_canonical(self, stream: str, before: MemoryState, plan: Plan, committed: MemoryState | None, new_events: list[NewEvent], *, user_id: str | None) -> None:
        """Queue ``FactRetained`` for the plan's created facts and content changes, off the caller's thread; never raises.

        Upserts that keep a fact's content (confidence, category, topics,
        confirmations) emit nothing: ``FactRetained`` carries only the content.
        Caller holds the scope lock.

        Jobs are queued under the scope lock, so the worker emits in commit order.
        The global scope has no canonical stream and emits nothing. After the append
        that created the stream (``committed`` is ``None``, once per scope) the
        commit's revision is read back here, by its event ids, before ``$tb`` can hide it.
        """
        if not self._canonical_enabled or not plan.upserted:
            return
        try:
            canonical = canonical_mapping.memory_stream(user_id)
            if canonical is None:
                return
            agent = next((data.get("agent") for event_type, data in plan.changes if event_type == events.FACT_UPSERTED), None)
            previous = before.agent_facts(agent) if agent is not None else {}
            upserted = [copy.deepcopy(fact) for fact in plan.upserted if (previous.get(str(fact.get("id"))) or {}).get("content") != fact.get("content")]
            if not upserted:
                return
            origin = committed.revision if committed is not None else self._revision_after(stream, {event.id for event in new_events})
            if origin is None:
                logger.warning("Canonical emission for %r skipped: the commit's revision could not be found", stream)
                return
            deadline = canonical_emitter.deadline_from_now()

            def emit() -> None:
                canonical_events = canonical_mapping.memory_events(upserted, user_id=user_id, agent=agent, origin=origin)
                self._canonical.emit(canonical, canonical_events, primary=stream, deadline=deadline)

            self._canonical_queue.submit(emit)
        except Exception:
            logger.warning("Scheduling canonical memory events for %r failed", stream, exc_info=True)

    def _revision_after(self, stream: str, own_ids: set[Any]) -> int | None:
        """The revision a commit produced, from its event ids (after an append that created the stream)."""
        if not own_ids:
            return None
        for event in self._get_stream(self._client(), stream, backwards=True, limit=READ_PAGE_SIZE):
            if event.id in own_ids:
                return event.stream_position + 1
        return None

    def _kick_canonical_cleanup(self, stream: str, *, deleted: bool) -> None:
        """Queue the scope's pending canonical cleanups behind its emissions, after a deletion or after a
        write while one is pending (cached index, no I/O); never raises and never runs on the caller's thread.
        Runs whatever ``KURRENTDB_CANONICAL_EVENTS`` says (R17): canonical copies written while it was on must still go."""
        try:
            engine = self._engine_instance
            if not deleted and (engine is None or self._cleaner.backing_off(stream) or not engine.has_pending_canonical(stream)):
                return
            self._canonical_queue.submit(lambda: self._cleaner.run(stream=stream, verify=False))
        except Exception:
            logger.warning("Scheduling the canonical cleanup of %r failed", stream, exc_info=True)

    def run_canonical_obligations(self) -> canonical_cleanup.PassReport:
        """One pass over every open memory canonical cleanup and due verification (recovery service); never raises.

        Runs whatever ``KURRENTDB_CANONICAL_EVENTS`` says (R17): the flag gates emission, never removal.
        """
        return self._cleaner.run()

    def flush_canonical(self, timeout: float | None = None) -> bool:
        """Wait for queued canonical emissions (tests, shutdown); ``False`` when ``timeout`` ran out first."""
        return self._canonical_queue.flush(timeout)

    def _commit_destructive(self, stream: str, state: MemoryState, plan: Plan, *, user_id: str | None) -> MemoryState:
        """Write a plan that removes facts or clears the scope as a deletion (``DeletionEngine``).

        The intent's criteria are ``plan.criteria`` plus ``cutoff``: the revision
        right after the boundary, so sidecar records written under an earlier
        revision are removed and later ones survive. The boundary is one
        ``MemorySnapshot`` of the resulting state at the folded head, carrying the
        intent id; the sidecar boundary and ``$tb`` follow (or are finished by
        recovery). A boundary that did not commit is a manifest conflict; one whose
        outcome is unknown, or a deletion blocked by an open one, is a
        ``KurrentdbMemoryReadError``. Caller holds the scope lock.
        """
        if state.position is None or plan.criteria is None:
            raise AssertionError("a destructive plan needs existing state and criteria")
        criteria = {**plan.criteria, "cutoff": state.position + 2}
        intent = Intent.new(criteria["op"], criteria, stream, state.position)
        resulting = self._fold(state.copy(), self._recorded(state, events.new_change_set(plan.changes)))
        boundary = [events.new_event(events.MEMORY_SNAPSHOT, intent.intent_id, 0, {"agent": None, "intent_id": intent.intent_id, "state": resulting.snapshot_state()})]
        try:
            self._engine().run(intent, lambda: boundary, self._derive(intent) or [])
        except DeletionConflict as exc:
            raise MemoryManifestRevisionConflict(f"Memory deletion in {stream!r} did not commit: {exc}") from exc
        except DeletionError as exc:
            raise KurrentdbMemoryReadError(f"Memory deletion in {stream!r} failed: {exc}") from exc
        committed = self._fold(state.copy(), self._recorded(state, boundary))
        self._states[stream] = committed
        return committed

    def apply_changes(
        self,
        change_set: dict[str, Any],
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        expected_manifest_revision: int | None = None,
        allow_manifest_rebase: bool = False,
    ) -> dict[str, Any]:
        """Commit one change set as one append and return only the applied delta.

        Matches ``FileMemoryStorage.apply_changes``: ``upserts`` with
        ``upsertRevisions`` (``None`` = must not exist), ``deletes`` with
        ``deleteRevisions``, and ``summaries`` merged per section (on any scope).
        Fact revisions are checked against the fold and raise
        ``MemoryFactRevisionConflict`` before anything is written. A manifest
        conflict is retried from a fresh fold only when no manifest revision was
        expected, or with ``allow_manifest_rebase`` for fact-only change sets
        whose every target revision is pinned. ``complete`` is always ``False``.
        """
        parsed = changes.parse_change_set(change_set, agent_name=agent_name)
        stream = self._stream(agent_name, user_id)
        expected = expected_manifest_revision
        may_retry = expected_manifest_revision is None or (allow_manifest_rebase and parsed.rebase_safe)
        for attempt in range(CHANGE_SET_ATTEMPTS):
            try:
                with self._scope_lock(stream):
                    self._recover_before_write(stream)
                    state = self._refresh(stream)
                    if expected is not None and expected != state.revision:
                        raise MemoryManifestRevisionConflict(f"Expected user-memory revision {expected}, found {state.revision}")
                    plan = changes.plan_change_set(state, parsed, agent_name=agent_name, user_id=user_id)
                    committed = self._commit(stream, state, plan, user_id=user_id)
                    return self._delta(committed or self._refresh(stream), plan)
            except MemoryManifestRevisionConflict as exc:
                if not may_retry or attempt == CHANGE_SET_ATTEMPTS - 1:
                    raise
                expected = None
                logger.info("Rebasing a memory change set after a revision conflict: %s", exc)
        raise AssertionError("bounded change-set retry did not return or raise")

    @staticmethod
    def _delta(state: MemoryState, plan: Plan) -> dict[str, Any]:
        return {
            "complete": False,
            "version": DOCUMENT_VERSION,
            "revision": state.revision,
            "lastUpdated": state.last_updated or "",
            "upsertedFacts": copy.deepcopy(plan.upserted),
            "deletedFactIds": list(plan.deleted),
        }

    def clear_all(self, *, user_id: str | None = None) -> dict[str, Any]:
        """Clear the user's summaries and every agent's facts in one append; returns the default bucket's document."""
        stream = self._stream(None, user_id)
        for attempt in range(CHANGE_SET_ATTEMPTS):
            try:
                with self._scope_lock(stream):
                    self._recover_before_write(stream)
                    state = self._refresh(stream)
                    plan = changes.plan_clear_all(state)
                    self._commit(stream, state, plan, user_id=user_id)
                    if not plan.changes:
                        # An already-empty scope may still hold sidecars (agents without facts).
                        self._clear_metadata_durably(stream, memory_meta_stream(user_id), None, user_id=user_id)
                break
            except MemoryManifestRevisionConflict:
                if attempt == CHANGE_SET_ATTEMPTS - 1:
                    raise
                logger.info("Retrying a memory clear after a revision conflict")
        return self.load(DEFAULT_AGENT_BUCKET, user_id=user_id)

    def get_fact(self, fact_id: str, *, user_id: str | None = None, agent_name: str | None = None) -> dict[str, Any] | None:
        """One fact of one agent bucket from the fresh fold, or ``None``."""
        if agent_name is None:
            raise ValueError("agent_name is required to get a fact")
        stream = self._stream(agent_name, user_id)
        with self._read_lock(stream):
            fact = self._refresh(stream).agent_facts(agent_name).get(str(fact_id))
        return copy.deepcopy(fact)

    # --- sidecars ---------------------------------------------------------------

    def _meta_scope(self, agent_name: str, user_id: str | None) -> tuple[str, str]:
        if not isinstance(agent_name, str) or not agent_name:
            raise ValueError("agent_name is required for memory sidecars")
        return self._stream(agent_name, user_id), memory_meta_stream(user_id)

    def _refresh_meta(self, meta: str) -> SidecarState:
        """The sidecar stream's fold, head-checked like ``_refresh``. Caller holds the meta lock."""
        client = self._client()
        cached = self._meta_states.get(meta)
        if cached is not None:
            head = self._head(client, meta)
            if head == cached.position:
                return cached
            if head is None:
                state = SidecarState(self._config)
                self._meta_states[meta] = state
                return state
            if cached.position is not None and head > cached.position:
                start = cached.position + 1
                new = self._get_stream(client, meta, stream_position=start)
                if not new or new[0].stream_position == start or new[0].type == sidecars.METADATA_SNAPSHOT:
                    state = cached.copy()
                    for event in new:
                        state.apply(event)
                    self._meta_states[meta] = state
                    return state
        state = SidecarState(self._config)
        for event in self._since_newest_snapshot(client, meta, boundary=sidecars.METADATA_SNAPSHOT):
            state.apply(event)
        self._meta_states[meta] = state
        return state

    def _meta_view(self, primary: str, meta: str, what: str) -> SidecarState | None:
        """The sidecars without any committed intent's records, or ``None`` (logged) when they cannot be read."""
        try:
            with self._read_lock(meta):
                state = self._refresh_meta(meta)
            intents = list(self._intents_provider(primary))
            cached = self._meta_views.get(meta)
            if cached is not None and cached[0] is state and cached[1] == intents:
                return cached[2]
            view = state.filtered(intents)
            self._meta_views[meta] = (state, intents, view)
            return view
        except Exception:
            logger.warning("Reading memory %s from %r failed; treating it as empty", what, meta, exc_info=True)
            return None

    def _primary_revision(self, primary: str) -> int:
        """The primary revision sidecar records are written under (the cached fold's). Caller holds the scope lock."""
        cached = self._states.get(primary)
        return cached.revision if cached is not None else self._refresh(primary).revision

    def _meta_append(self, meta: str, event_type: str, data: dict[str, Any]) -> None:
        """One sidecar event: a blind append, or a compacting snapshot when the history is long. Caller holds the meta lock."""
        cached = self._meta_states.get(meta)
        if cached is not None and len(cached.log) >= SIDECAR_SNAPSHOT_EVERY:
            state = self._refresh_meta(meta).copy()
            state.apply_data(event_type, data)
            snapshot = sidecars.new_event(sidecars.METADATA_SNAPSHOT, {"agent": None, "revision": data.get("revision"), "state": state.snapshot_state()})
            if self._meta_snapshot(meta, state.position, snapshot):
                return
        event = sidecars.new_event(event_type, data)
        self._client().append_to_stream(meta, events=[event], current_version=StreamState.ANY, timeout=self._timeout)

    def _meta_snapshot(self, meta: str, position: int | None, snapshot: NewEvent) -> bool:
        """Append ``snapshot`` right after ``position``; ``False`` when another append landed first."""
        expected: int | StreamState = StreamState.NO_STREAM if position is None else position
        try:
            self._client().append_to_stream(meta, events=[snapshot], current_version=expected, timeout=self._timeout)
        except WrongCurrentVersionError:
            return False
        return True

    def _clear_metadata(self, primary: str, meta: str, criteria: Mapping[str, Any]) -> None:
        """Replace the sidecars with a snapshot of the records ``criteria`` do not match; best-effort."""
        try:
            with self._scope_lock(primary), self._scope_lock(meta):
                cached = self._states.get(primary)
                revision = cached.revision if cached is not None else None
                for _ in range(SIDECAR_SNAPSHOT_ATTEMPTS):
                    state = self._refresh_meta(meta)
                    survivors = state.without(criteria).snapshot_state()
                    if survivors == state.snapshot_state():
                        return
                    snapshot = sidecars.new_event(sidecars.METADATA_SNAPSHOT, {"agent": None, "revision": revision, "state": survivors})
                    if self._meta_snapshot(meta, state.position, snapshot):
                        return
                logger.warning("Clearing memory sidecars in %r kept conflicting with concurrent writes; gave up", meta)
        except Exception:
            logger.warning("Clearing memory sidecars in %r failed (criteria %r)", meta, dict(criteria), exc_info=True)

    def _clear_metadata_durably(self, primary: str, meta: str, agent: str | None, *, user_id: str | None, fact_ids: list[str] | None = None) -> None:
        """Clear ``agent``'s sidecar records (the scope's for ``None``; only those about ``fact_ids``
        when given, watermarks kept) as a ``clear_metadata`` deletion; best-effort.

        A sidecar-only clear must outlive sidecar appends from other processes that
        read the primary revision before it (``StreamState.ANY``; scope locks are
        process-local), and records carry only the primary revision. So the clear is
        a deletion like any other: an intent with a ``cutoff``, a primary boundary
        that leaves the state unchanged (it moves the revision, so later records
        survive), then the sidecar boundary. Reads keep filtering by the committed
        intent after it closes, so even a clear that finds nothing to remove is
        written (it cannot know whether such an append is in flight). A scope with
        sidecars but no primary stream gets an empty snapshot first; a scope with
        neither stream writes nothing. A fact-id clear is a deletion even right after
        the ``delete_facts`` deletion of those ids: a sidecar append made in between
        is stamped at that deletion's cutoff, which it does not cover, and sidecar
        appends never move the primary head. If the deletion cannot be written, the
        sidecars are still cleared directly (not durable against a late append) and
        nothing raises.
        """
        criteria: dict[str, Any] = {"op": "clear_metadata", "agent": agent}
        if fact_ids is not None:
            criteria["factIds"] = list(fact_ids)
        for attempt in range(CHANGE_SET_ATTEMPTS):
            try:
                with self._scope_lock(primary):
                    self._recover_before_write(primary)
                    state = self._refresh(primary)
                    if state.position is None:
                        if self._head(self._client(), meta) is None:
                            return  # nothing was ever written for this scope
                        self._append(primary, state, events.new_change_set([(events.MEMORY_SNAPSHOT, {"agent": None, "state": state.snapshot_state()})]))
                        state = self._refresh(primary)
                    self._commit_destructive(primary, state, Plan([], [], [], criteria), user_id=user_id)
                self._kick_canonical_cleanup(primary, deleted=True)
                return
            except MemoryManifestRevisionConflict:
                if attempt < CHANGE_SET_ATTEMPTS - 1:
                    continue
                logger.warning("Clearing memory sidecars of %r as a deletion kept conflicting; clearing them directly", primary)
            except Exception:
                logger.warning("Clearing memory sidecars of %r as a deletion failed; clearing them directly", primary, exc_info=True)
            break
        self._clear_metadata(primary, meta, criteria)

    def get_fact_usage(self, *, agent_name: str, user_id: str | None = None) -> dict[str, dict[str, Any]]:
        """Usage of the agent's current facts (a late access append for a deleted fact is dropped)."""
        primary, meta = self._meta_scope(agent_name, user_id)
        try:
            with self._read_lock(primary):
                facts = set(self._refresh(primary).agent_facts(agent_name))
        except Exception:
            logger.warning("Reading %r to filter fact usage failed; treating usage as empty", primary, exc_info=True)
            return {}
        view = self._meta_view(primary, meta, "fact usage")
        return {fact_id: entry for fact_id, entry in view.usage(agent_name).items() if fact_id in facts} if view is not None else {}

    def get_eviction_audit(self, *, agent_name: str, user_id: str | None = None) -> list[dict[str, Any]]:
        """The bounded capacity-eviction evidence, oldest first (the file storage's ``eviction-audit.json``)."""
        primary, meta = self._meta_scope(agent_name, user_id)
        view = self._meta_view(primary, meta, "eviction evidence")
        return view.evictions(agent_name) if view is not None else []

    def get_extraction_watermark(self, thread_id: str, *, agent_name: str, user_id: str | None = None) -> list[str] | None:
        primary, meta = self._meta_scope(agent_name, user_id)
        view = self._meta_view(primary, meta, "extraction watermark")
        return view.watermark(agent_name, thread_id) if view is not None else None

    def record_fact_accesses(self, fact_ids: list[str], *, agent_name: str, user_id: str | None = None, accessed_at: datetime | None = None) -> None:
        """One append of the hits that are still facts (checked under the scope lock, as the file storage does)."""
        unique_ids = list(dict.fromkeys(str(fact_id) for fact_id in fact_ids if fact_id))
        if not unique_ids:
            return
        now = accessed_at or datetime.now(UTC)
        primary, meta = self._meta_scope(agent_name, user_id)
        try:
            with self._read_lock(primary):
                state = self._refresh(primary)
                existing = [fact_id for fact_id in unique_ids if fact_id in state.agent_facts(agent_name)]
                if not existing:
                    return
                with self._read_lock(meta):
                    self._meta_append(meta, sidecars.FACTS_ACCESSED, {"agent": agent_name, "revision": state.revision, "factIds": existing, "at": sidecars.iso_z(now)})
        except Exception:
            logger.warning("Recording memory fact accesses in %r failed", meta, exc_info=True)

    def record_capacity_eviction(
        self,
        decision: FactEvictionDecision,
        *,
        max_facts: int,
        agent_name: str,
        user_id: str | None = None,
        occurred_at: datetime | None = None,
        shadow_decision: FactEvictionDecision | None = None,
    ) -> None:
        if not decision.evicted or self._config.eviction_audit_max_entries == 0:
            return
        record = sidecars.eviction_record(decision, max_facts=max_facts, now=occurred_at or datetime.now(UTC), shadow_decision=shadow_decision)
        self._record(agent_name, user_id, sidecars.CAPACITY_EVICTED, {"record": record}, "capacity-eviction evidence")

    def set_extraction_watermark(self, thread_id: str, watermark: list[str] | None, *, agent_name: str, user_id: str | None = None) -> None:
        """One append; the fold keeps the newest ``watermark_max_keys`` threads (``None`` drops this one)."""
        self._record(agent_name, user_id, sidecars.WATERMARK_SET, {"threadId": thread_id, "watermark": None if watermark is None else list(watermark)}, "extraction watermark")

    def _record(self, agent_name: str, user_id: str | None, event_type: str, data: dict[str, Any], what: str) -> None:
        primary, meta = self._meta_scope(agent_name, user_id)
        try:
            with self._scope_lock(primary):
                revision = self._primary_revision(primary)
                with self._scope_lock(meta):
                    self._meta_append(meta, event_type, {"agent": agent_name, "revision": revision, **data})
        except Exception:
            logger.warning("Recording memory %s in %r failed", what, meta, exc_info=True)

    def clear_fact_metadata(self, *, agent_name: str, user_id: str | None = None, fact_ids: list[str] | None = None) -> None:
        """Drop the sidecar records of ``fact_ids`` (usage, eviction items), or all of the agent's records.

        As ``FileMemoryStorage.clear_fact_metadata``: deleting facts keeps the
        agent's watermarks and other facts' records; ``None`` clears the agent.
        """
        primary, meta = self._meta_scope(agent_name, user_id)
        if fact_ids is None:
            self._clear_metadata_durably(primary, meta, agent_name, user_id=user_id)
            return
        removed = sorted({str(fact_id) for fact_id in fact_ids})
        if removed:
            # Callable on its own (the facts may remain), and even right after the facts'
            # deletion a sidecar append may already be stamped at its cutoff: always a deletion.
            self._clear_metadata_durably(primary, meta, agent_name, user_id=user_id, fact_ids=removed)

    # --- misc -------------------------------------------------------------------

    def capabilities(self) -> set[str]:
        return {"kurrentdb", "event-sourced", "revision", "substring-fallback"}

    def close(self) -> None:
        """Clients are shared per settings (``_client``), so nothing is closed here."""
