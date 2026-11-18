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
delete facts or clear a scope go through ``_commit_destructive`` as a
``MemorySnapshot`` boundary of the resulting state.

``load()`` serves a per-scope cache but checks the stream head on every call and
folds only the new events; ``reload()`` re-reads from the newest snapshot. DeerMem
calls storage from timer threads, so each scope's cache and writes are guarded by
a per-scope lock.
"""

from __future__ import annotations

import copy
import logging
import threading
from collections.abc import Callable
from typing import Any, NamedTuple

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.paths import DEFAULT_AGENT_BUCKET, validate_agent_name
from deerflow.agents.memory.backends.deermem.deermem.core.storage import DOCUMENT_VERSION, MemoryManifestRevisionConflict, MemoryStorage, MemoryStorageCorruption
from deerflow.agents.memory.manager import MemoryReadError
from kurrentdbclient import NewEvent, StreamState
from kurrentdbclient.exceptions import NotFoundError, WrongCurrentVersionError

from .._client import sync_client_factory
from .._fence import AmbiguousAppendError, settle_append
from .._naming import memory_stream
from .._settings import load_settings
from . import changes, events
from .changes import Plan
from .fold import MemoryState

logger = logging.getLogger(__name__)

# Events per backwards page when looking for the newest snapshot.
READ_PAGE_SIZE = 256
# Attempts of one change set across manifest conflicts it may retry (as the file storage).
CHANGE_SET_ATTEMPTS = 3


class KurrentdbMemoryReadError(MemoryReadError):
    """KurrentDB could not be read (transport, timeout), or a write's outcome is unknown."""


class _Recorded(NamedTuple):
    type: str
    data: bytes
    stream_position: int


class KurrentdbMemoryStorage(MemoryStorage):
    def __init__(self, config: DeerMemConfig, *, client_factory: Callable[[], Any] | None = None):
        self._config = config
        self._settings = load_settings()
        self._timeout = self._settings.timeout
        self._client_factory = client_factory if client_factory is not None else sync_client_factory(self._settings)
        self._locks_guard = threading.Lock()
        self._scope_locks: dict[str, threading.RLock] = {}
        self._states: dict[str, MemoryState] = {}

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

    def _since_newest_snapshot(self, client: Any, stream: str) -> list[Any]:
        """The stream's events from its newest snapshot (or its first event) forward."""
        collected: list[Any] = []
        position: int | None = None
        while True:
            page = self._get_stream(client, stream, stream_position=position, backwards=True, limit=READ_PAGE_SIZE)
            for event in page:
                collected.append(event)
                if event.type == events.MEMORY_SNAPSHOT:
                    return collected[::-1]
            if len(page) < READ_PAGE_SIZE or page[-1].stream_position == 0:
                return collected[::-1]
            position = page[-1].stream_position - 1

    @staticmethod
    def _fold(state: MemoryState, recorded: list[Any] | tuple[Any, ...], stream: str) -> MemoryState:
        for event in recorded:
            state.apply(event)
        return state

    def _full_read(self, client: Any, stream: str) -> MemoryState:
        return self._fold(MemoryState(), self._since_newest_snapshot(client, stream), stream)

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
                    state = self._fold(cached.copy(), new, stream)
            else:
                state = self._full_read(client, stream)
        self._states[stream] = state
        return state

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        stream = self._stream(agent_name, user_id)
        with self._scope_lock(stream):
            return self._refresh(stream).to_document(agent_name)

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        stream = self._stream(agent_name, user_id)
        with self._scope_lock(stream):
            state = self._full_read(self._client(), stream)
            self._states[stream] = state
            return state.to_document(agent_name)

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
        committed = self._fold(state.copy(), self._recorded(state, new_events), stream)
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
            return self._append(stream, state, events.new_change_set(plan.changes))
        return self._commit_destructive(stream, state, plan, user_id=user_id)

    def _commit_destructive(self, stream: str, state: MemoryState, plan: Plan, *, user_id: str | None) -> MemoryState | None:
        """Write a plan that removes facts or clears the scope as one ``MemorySnapshot`` boundary.

        The deletion engine's entry point: everything that deletes goes through
        here, with ``plan.criteria`` naming what is removed. This interim engine
        writes the boundary (the resulting state, in one append at the folded
        head) and then drops the removed facts' sidecar metadata. It does not yet
        record a deletion intent or raise ``$tb``; the full protocol replaces it.
        Caller holds the scope lock.
        """
        resulting = self._fold(state.copy(), self._recorded(state, events.new_change_set(plan.changes)), stream)
        boundary = events.new_change_set([(events.MEMORY_SNAPSHOT, {"agent": None, "state": resulting.snapshot_state()})])
        committed = self._append(stream, state, boundary)
        criteria = plan.criteria or {}
        if criteria.get("op") == "delete_facts":
            self.clear_fact_metadata(agent_name=criteria["agent"], user_id=user_id, fact_ids=list(criteria["factIds"]))
        elif criteria.get("op") == "clear_all":
            for agent_name in criteria["agents"]:
                self.clear_fact_metadata(agent_name=agent_name, user_id=user_id)
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
                    state = self._refresh(stream)
                    self._commit(stream, state, changes.plan_clear_all(state), user_id=user_id)
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
        with self._scope_lock(stream):
            fact = self._refresh(stream).agent_facts(agent_name).get(str(fact_id))
        return copy.deepcopy(fact)

    # --- misc -------------------------------------------------------------------

    def capabilities(self) -> set[str]:
        return {"kurrentdb", "event-sourced", "revision", "substring-fallback"}

    def close(self) -> None:
        """Clients are shared per settings (``_client``), so nothing is closed here."""
