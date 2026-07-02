"""Event-sourced memory storage backed by KurrentDB streams.

Prototype for deer-flow discussion #3796: every memory update is appended as
an immutable ``MemoryUpdated`` event to a per-user (optionally per-agent)
KurrentDB stream, and the current memory state is the newest event on that
stream. The full update history therefore comes for free: point-in-time
replay ("what did the agent know at turn N"), auditability, and cross-agent
consumers all read the same streams with no extra write path.

Optional integration: requires the ``kurrentdbclient`` package (install the
``deerflow-harness[kurrentdb]`` extra) and the ``KURRENTDB_CONNECTION_STRING``
environment variable (e.g. ``kurrentdb://localhost:2113?tls=false``). Enable
it via the existing reflection hook in ``config.yaml`` — no core changes::

    memory:
      storage_class: deerflow.community.kurrentdb.memory_storage.KurrentdbMemoryStorage

The ``MemoryStorage`` ABC is synchronous (called from the memory updater's
timer threads and from Gateway request paths), so this implementation uses
the sync ``KurrentDBClient``. Reads are cache-first: after the first load per
``(user_id, agent_name)`` no gRPC call happens on the hot path; ``reload()``
(and the ``POST /api/memory/reload`` endpoint) forces a re-read.
"""

import functools
import json
import logging
import math
import os
import re
import threading
from collections.abc import Callable
from typing import Any

from deerflow.agents.memory.storage import MemoryStorage, create_empty_memory, utc_now_iso_z
from deerflow.config.agents_config import AGENT_NAME_PATTERN

logger = logging.getLogger(__name__)

STREAM_PREFIX = "deerflow.memory"
EVENT_TYPE = "MemoryUpdated"
_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
DEFAULT_TIMEOUT_SECONDS = 10.0

# kurrent-agents canonical app identifier for deer-flow (github.com/kurrent-io/kurrent-agents).
# Used to build the canonical AgentMemory-deerflow-{user_id} stream name.
CANONICAL_APP_NAME = "deerflow"

# Emitted once per process if kurrent_agent_schema is not installed, instead
# of logging a warning on every save() (the package is optional even when
# the kurrentdbclient-backed storage itself is in use).
_canonical_schema_warned = False


class KurrentdbMemoryReadError(RuntimeError):
    """Raised when the newest memory snapshot could not be read from KurrentDB.

    Signals a transport failure, an unexpected event type, or a corrupt
    (non-JSON/non-UTF-8) event on the memory stream -- as opposed to a
    missing stream, which is a legitimate empty-memory answer. Callers must
    not treat this as "empty memory" and must not write a basis derived from
    this failure: doing so (load -> mutate -> save) would append an
    empty-derived snapshot that clobbers the real newest event on the
    stream. Read-modify-write callers should let this exception abort the
    operation; explicit overwrite flows (import/clear) never read and remain
    available as the repair path.
    """


def _make_default_client(connection_string: str) -> Any:
    from kurrentdbclient import KurrentDBClient

    return KurrentDBClient(uri=connection_string)


def _fact_identity(fact: dict[str, Any]) -> tuple[str, str] | None:
    """Identity key for a fact dict: ``id`` when present, else normalized content.

    Returns ``None`` for facts that have neither a usable ``id`` nor
    ``content`` -- such facts cannot be matched against a previous basis and
    are treated as always-new by the caller's set-difference logic (they
    simply never appear in the "previous" identity set).
    """
    fact_id = fact.get("id") if isinstance(fact, dict) else None
    if isinstance(fact_id, str) and fact_id:
        return ("id", fact_id)
    content = fact.get("content") if isinstance(fact, dict) else None
    if isinstance(content, str) and content.strip():
        return ("content", content.strip())
    return None


def _parse_fact_created_at(created_at: Any) -> Any:
    """Parse a fact's ``createdAt`` (e.g. ``utc_now_iso_z()`` output) to a datetime.

    Falls back to the current UTC time when ``created_at`` is missing or not
    a parseable ISO-8601 string, per the contract: "the fact's createdAt when
    parseable else now".
    """
    import datetime as _dt

    if isinstance(created_at, str) and created_at:
        try:
            return _dt.datetime.fromisoformat(created_at)
        except ValueError:
            pass
    return _dt.datetime.now(_dt.UTC)


def _new_facts(previous_facts: list[Any], current_facts: list[Any]) -> list[dict[str, Any]]:
    """Facts present in ``current_facts`` whose identity is not in ``previous_facts``.

    Identity is the fact's ``id`` when present, else its normalized
    ``content`` (see ``_fact_identity``). Facts without a stable identity
    are always considered new since they cannot be matched against the
    previous basis.
    """
    previous_identities = {identity for f in previous_facts if isinstance(f, dict) and (identity := _fact_identity(f)) is not None}
    new_facts = []
    for fact in current_facts:
        if not isinstance(fact, dict):
            continue
        identity = _fact_identity(fact)
        if identity is not None and identity in previous_identities:
            continue
        new_facts.append(fact)
    return new_facts


class KurrentdbMemoryStorage(MemoryStorage):
    """Memory storage provider that appends updates to KurrentDB streams."""

    def __init__(self, client_factory: Callable[[], Any] | None = None):
        if client_factory is None:
            connection_string = os.environ.get("KURRENTDB_CONNECTION_STRING", "").strip()
            if not connection_string:
                raise RuntimeError("KurrentdbMemoryStorage requires the KURRENTDB_CONNECTION_STRING environment variable (e.g. kurrentdb://localhost:2113?tls=false)")
            client_factory = functools.partial(_make_default_client, connection_string)
        self._client_factory = client_factory
        # Client creation is lazy so __init__ never touches the network and
        # get_memory_storage()'s singleton resolution stays side-effect free.
        self._client: Any | None = None
        self._client_lock = threading.Lock()
        # Per-user/agent memory cache keyed by (user_id, agent_name), mirroring
        # FileMemoryStorage. Cache-first reads keep gRPC off hot paths.
        self._memory_cache: dict[tuple[str | None, str | None], dict[str, Any]] = {}
        self._cache_lock = threading.Lock()
        self._timeout = self._resolve_timeout()

    @staticmethod
    def _resolve_timeout() -> float:
        raw = os.environ.get("KURRENTDB_MEMORY_TIMEOUT_SECONDS", "").strip()
        if not raw:
            return DEFAULT_TIMEOUT_SECONDS
        try:
            value = float(raw)
        except ValueError:
            logger.warning("Invalid KURRENTDB_MEMORY_TIMEOUT_SECONDS %r: not a number, using default %s", raw, DEFAULT_TIMEOUT_SECONDS)
            return DEFAULT_TIMEOUT_SECONDS
        if not math.isfinite(value) or value <= 0:
            logger.warning("Invalid KURRENTDB_MEMORY_TIMEOUT_SECONDS %r: must be a positive finite number, using default %s", raw, DEFAULT_TIMEOUT_SECONDS)
            return DEFAULT_TIMEOUT_SECONDS
        return value

    @staticmethod
    def _validate_agent_name(agent_name: str) -> None:
        if not agent_name:
            raise ValueError("Agent name must be a non-empty string.")
        if not AGENT_NAME_PATTERN.match(agent_name):
            raise ValueError(f"Invalid agent name {agent_name!r}: names must match {AGENT_NAME_PATTERN.pattern}")

    @staticmethod
    def _validate_user_id(user_id: str) -> None:
        if not _USER_ID_PATTERN.match(user_id) or user_id == "_global":
            raise ValueError(f"Invalid user id {user_id!r}: only alphanumeric characters, hyphens, and underscores are allowed, and '_global' is reserved.")

    @classmethod
    def _stream_name(cls, agent_name: str | None = None, *, user_id: str | None = None) -> str:
        """Derive the stream for a memory owner.

        KurrentDB's ``$by_category`` projection splits at the first ``-``, so
        every memory stream lands in the ``deerflow.memory`` category.
        """
        if user_id is not None:
            cls._validate_user_id(user_id)
        owner = user_id if user_id is not None else "_global"
        if agent_name is not None:
            cls._validate_agent_name(agent_name)
            return f"{STREAM_PREFIX}-{owner}.agent.{agent_name}"
        return f"{STREAM_PREFIX}-{owner}"

    def _get_client(self) -> Any:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    self._client = self._client_factory()
        return self._client

    def _read_latest(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Read the newest memory snapshot from KurrentDB.

        Returns the parsed memory dict, or an empty structure when the
        stream does not exist yet (a legitimate empty answer). Transport
        errors, an unexpected event type, or a corrupt (non-JSON/non-UTF-8)
        event raise ``KurrentdbMemoryReadError`` instead of returning a
        fallback value: the caller cannot tell "really empty" from "could
        not read", so read-modify-write flows must abort rather than risk
        saving an empty-derived basis over the real newest event.
        """
        from kurrentdbclient.exceptions import NotFoundError

        stream_name = self._stream_name(agent_name, user_id=user_id)
        try:
            events = self._get_client().get_stream(stream_name, backwards=True, limit=1, timeout=self._timeout)
        except NotFoundError:
            return create_empty_memory()
        except Exception as e:
            logger.error("Failed to read memory stream %s: %s", stream_name, e)
            raise KurrentdbMemoryReadError(f"Failed to read memory stream {stream_name}") from e
        if not events:
            return create_empty_memory()
        latest_event = events[0]
        if latest_event.type != EVENT_TYPE:
            logger.error("Unexpected event type %r (expected %r) on memory stream %s", latest_event.type, EVENT_TYPE, stream_name)
            raise KurrentdbMemoryReadError(f"Unexpected event type {latest_event.type!r} (expected {EVENT_TYPE!r}) on memory stream {stream_name}")
        try:
            memory_data = json.loads(latest_event.data)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error("Failed to decode memory event from stream %s: %s", stream_name, e)
            raise KurrentdbMemoryReadError(f"Failed to decode memory event from stream {stream_name}") from e
        return memory_data

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Load memory data (cache-first; first miss reads from KurrentDB).

        Raises:
            KurrentdbMemoryReadError: The read failed (see ``_read_latest``).
                Nothing is cached on this path -- there is no fallback value
                to cache, and the next call retries.
        """
        cache_key = (user_id, agent_name)
        with self._cache_lock:
            cached = self._memory_cache.get(cache_key)
        if cached is not None:
            return cached
        memory_data = self._read_latest(agent_name, user_id=user_id)
        with self._cache_lock:
            # Populate-only-if-absent: a concurrent save() may have already
            # written a fresher value while this read was in flight. That
            # value is newer than what we just read, so keep it and return
            # it instead of clobbering the cache with our stale read.
            self._memory_cache.setdefault(cache_key, memory_data)
            return self._memory_cache[cache_key]

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Force a re-read from KurrentDB, refreshing the cache on success.

        Raises:
            KurrentdbMemoryReadError: The read failed (see ``_read_latest``).
                The cache is left untouched on this path.
        """
        memory_data = self._read_latest(agent_name, user_id=user_id)
        with self._cache_lock:
            self._memory_cache[(user_id, agent_name)] = memory_data
        return memory_data

    def save(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None) -> bool:
        """Append the new memory snapshot as an immutable event."""
        from kurrentdbclient import NewEvent, StreamState

        stream_name = self._stream_name(agent_name, user_id=user_id)
        # Shallow-copy before stamping lastUpdated so the caller's dict is not
        # mutated as a side-effect (mirrors FileMemoryStorage.save).
        memory_data = {**memory_data, "lastUpdated": utc_now_iso_z()}
        event_metadata = {"user_id": user_id, "agent_name": agent_name, "source": "deerflow-memory", "schema": "v0"}
        # Serialization happens outside the try so a non-JSON-serializable
        # memory dict raises (TypeError) to the caller instead of being
        # masked as a transport failure -- mirrors FileMemoryStorage, which
        # only catches OSError around the actual write.
        event = NewEvent(
            type=EVENT_TYPE,
            data=json.dumps(memory_data, ensure_ascii=False).encode("utf-8"),
            metadata=json.dumps(event_metadata, ensure_ascii=False).encode("utf-8"),
        )
        try:
            self._get_client().append_to_stream(stream_name, events=event, current_version=StreamState.ANY, timeout=self._timeout)
        except Exception as e:
            logger.error("Failed to append memory event to KurrentDB stream %s: %s", stream_name, e)
            return False
        cache_key = (user_id, agent_name)
        with self._cache_lock:
            # Captured before the cache update so the delta below compares
            # against the basis this save() was actually applied on top of,
            # not the snapshot we are about to write.
            previous_basis = self._memory_cache.get(cache_key)
            self._memory_cache[cache_key] = memory_data
        logger.info("Memory appended to KurrentDB stream %s", stream_name)
        self._emit_canonical_fact_events(memory_data, previous_basis, user_id=user_id)
        return True

    def _emit_canonical_fact_events(self, memory_data: dict[str, Any], previous_basis: dict[str, Any] | None, *, user_id: str | None) -> None:
        """Best-effort dual-write of new facts as canonical kurrent-agents events.

        Emits one ``FactRetained`` event per NEW fact (identity not present
        in ``previous_basis``) to the canonical stream
        ``AgentMemory-deerflow-{user_id}`` so any other kurrent-agents
        integration (github.com/kurrent-io/kurrent-agents) can read
        deer-flow's retained facts. This is entirely best-effort: the
        snapshot stream (already appended by the time this runs) remains the
        single source of truth, and any failure here -- import error,
        connection error, serialization error -- is logged and swallowed. It
        never changes save()'s return value or raises.

        Skipped (no canonical append, by design):
        - Cold save (no previous basis): avoids re-emitting the entire fact
          list as "new" after every process restart, since the in-memory
          cache -- not the canonical stream -- is the delta basis.
        - ``user_id is None``: the canonical v1 schema scopes AgentMemory
          streams per-app-per-user only; there is no global-memory stream.
        - Empty delta (no new facts): nothing to append.
        """
        if previous_basis is None or user_id is None:
            return
        new_facts = _new_facts(previous_basis.get("facts") or [], memory_data.get("facts") or [])
        if not new_facts:
            return
        try:
            self._append_canonical_fact_events(new_facts, user_id=user_id)
        except Exception as e:
            logger.warning("Best-effort canonical kurrent-agents FactRetained emission failed: %s", e)

    def _append_canonical_fact_events(self, new_facts: list[dict[str, Any]], *, user_id: str) -> None:
        global _canonical_schema_warned
        try:
            from kurrent_agent_schema import EVENT_TYPE_NAMES, SCHEMA_VERSION, FactRetained, agent_memory_stream, to_json
        except ImportError as e:
            if not _canonical_schema_warned:
                logger.warning("kurrent_agent_schema is not installed; skipping canonical FactRetained emission (install the deerflow-harness[kurrentdb] extra): %s", e)
                _canonical_schema_warned = True
            return
        from kurrentdbclient import NewEvent, StreamState

        canonical_stream = agent_memory_stream(CANONICAL_APP_NAME, user_id)
        event_type_name = EVENT_TYPE_NAMES[FactRetained]
        canonical_events = []
        for fact in new_facts:
            retained_at = _parse_fact_created_at(fact.get("createdAt"))
            fact_event = FactRetained(fact=str(fact.get("content", "")), retained_at=retained_at)
            canonical_events.append(
                NewEvent(
                    type=event_type_name,
                    data=to_json(fact_event).encode("utf-8"),
                    metadata=json.dumps({"schema_version": SCHEMA_VERSION}, ensure_ascii=False).encode("utf-8"),
                )
            )
        self._get_client().append_to_stream(canonical_stream, events=canonical_events, current_version=StreamState.ANY, timeout=self._timeout)
        logger.info("Emitted %d canonical FactRetained event(s) to %s", len(canonical_events), canonical_stream)
