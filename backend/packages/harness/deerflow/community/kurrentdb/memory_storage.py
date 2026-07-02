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
import os
import threading
from collections.abc import Callable
from typing import Any

from deerflow.agents.memory.storage import MemoryStorage, create_empty_memory, utc_now_iso_z
from deerflow.config.agents_config import AGENT_NAME_PATTERN

logger = logging.getLogger(__name__)

STREAM_PREFIX = "deerflow.memory"
EVENT_TYPE = "MemoryUpdated"


def _make_default_client(connection_string: str) -> Any:
    from kurrentdbclient import KurrentDBClient

    return KurrentDBClient(uri=connection_string)


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

    @staticmethod
    def _validate_agent_name(agent_name: str) -> None:
        if not agent_name:
            raise ValueError("Agent name must be a non-empty string.")
        if not AGENT_NAME_PATTERN.match(agent_name):
            raise ValueError(f"Invalid agent name {agent_name!r}: names must match {AGENT_NAME_PATTERN.pattern}")

    @classmethod
    def _stream_name(cls, agent_name: str | None = None, *, user_id: str | None = None) -> str:
        """Derive the stream for a memory owner.

        KurrentDB's ``$by_category`` projection splits at the first ``-``, so
        every memory stream lands in the ``deerflow.memory`` category.
        """
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

    def _read_latest(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any] | None:
        """Read the newest memory snapshot from KurrentDB.

        Returns the parsed memory dict, an empty structure when the stream
        does not exist yet, or ``None`` on transport/decode errors so callers
        can avoid caching failures (the next call retries).
        """
        from kurrentdbclient.exceptions import NotFoundError

        stream_name = self._stream_name(agent_name, user_id=user_id)
        try:
            events = self._get_client().get_stream(stream_name, backwards=True, limit=1)
        except NotFoundError:
            return create_empty_memory()
        except Exception as e:
            logger.warning("Failed to read memory stream %s: %s", stream_name, e)
            return None
        if not events:
            return create_empty_memory()
        try:
            return json.loads(events[0].data)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("Failed to decode memory event from stream %s: %s", stream_name, e)
            return None

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Load memory data (cache-first; first miss reads from KurrentDB)."""
        cache_key = (user_id, agent_name)
        with self._cache_lock:
            cached = self._memory_cache.get(cache_key)
        if cached is not None:
            return cached
        memory_data = self._read_latest(agent_name, user_id=user_id)
        if memory_data is None:
            return create_empty_memory()
        with self._cache_lock:
            self._memory_cache[cache_key] = memory_data
        return memory_data

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Force a re-read from KurrentDB, refreshing the cache on success."""
        memory_data = self._read_latest(agent_name, user_id=user_id)
        if memory_data is None:
            return create_empty_memory()
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
        try:
            event = NewEvent(
                type=EVENT_TYPE,
                data=json.dumps(memory_data, ensure_ascii=False).encode("utf-8"),
                metadata=json.dumps(event_metadata, ensure_ascii=False).encode("utf-8"),
            )
            self._get_client().append_to_stream(stream_name, events=event, current_version=StreamState.ANY)
        except Exception as e:
            logger.error("Failed to append memory event to KurrentDB stream %s: %s", stream_name, e)
            return False
        with self._cache_lock:
            self._memory_cache[(user_id, agent_name)] = memory_data
        logger.info("Memory appended to KurrentDB stream %s", stream_name)
        return True
