"""Session memory storage provider.

Stores thread-scoped memory in LangGraph Store under namespace
``("memory_session", tenant_id, user_id, thread_id)`` with key ``"data"``.

Session memory persists facts and context for the lifetime of a thread,
surviving message summarization to maintain continuity in long conversations.
"""

import logging
import threading
import time
from typing import Any

from langgraph.store.base import BaseStore

from deerflow.agents.memory.storage import MemoryStorage, create_empty_memory
from deerflow.config.tenant import get_current_tenant_id

logger = logging.getLogger(__name__)


def create_empty_session_memory() -> dict[str, Any]:
    """Create an empty session memory structure."""
    from deerflow.agents.memory.storage import utc_now_iso_z

    return {
        "version": "1.0",
        "lastUpdated": utc_now_iso_z(),
        "session_context": {"summary": "", "updatedAt": ""},
        "facts": [],
    }


class SessionStorage(MemoryStorage):
    """Thread-scoped memory storage using LangGraph Store.

    Stores session memory at namespace ``("memory_session", tenant_id, user_id, thread_id)``
    with key ``"data"``. This provides thread-local context that survives message
    summarization while remaining isolated from long-term User Memory.

    Session memory is only available when using StoreMemoryStorage backend.
    Users with FileMemoryStorage will not have session memory enabled.
    """

    def __init__(self, store_factory):
        """Initialize with a callable that returns a :class:`BaseStore`.

        Args:
            store_factory: Callable returning a BaseStore instance. Invoked lazily
                on every load/save to use the correct Store for the current context.
        """
        self._store_factory = store_factory

    def _ns(self, thread_id: str, user_id: str | None = None) -> tuple[str, str, str, str]:
        """Return the Store namespace for the current tenant, user, and thread.

        Args:
            thread_id: Thread identifier.
            user_id: Optional user identifier.

        Returns:
            Tuple of (scope, tenant_id, user_id, thread_id).
        """
        return ("memory_session", get_current_tenant_id(), user_id or "", thread_id)

    def _get_store(self) -> BaseStore:
        """Get the BaseStore instance from the factory."""
        store = self._store_factory()
        if store is None:
            raise RuntimeError("Store is not available")
        return store

    def load(self, thread_id: str, *, user_id: str | None = None, agent_name: str | None = None) -> dict[str, Any]:
        """Load session memory from the Store (sync path).

        Args:
            thread_id: Thread identifier.
            user_id: Optional user identifier.
            agent_name: Ignored (session memory is not agent-scoped).

        Returns:
            Session memory data, or empty structure if not found.
        """
        try:
            store = self._get_store()
            item = store.get(self._ns(thread_id, user_id), "data")
        except Exception:
            logger.warning("SessionStorage.load failed, returning empty session memory", exc_info=True)
            return create_empty_session_memory()

        if item is None or item.value is None:
            return create_empty_session_memory()
        return item.value

    def reload(self, thread_id: str, *, user_id: str | None = None, agent_name: str | None = None) -> dict[str, Any]:
        """Reload session memory (same as load for Store backend).

        Args:
            thread_id: Thread identifier.
            user_id: Optional user identifier.
            agent_name: Ignored.

        Returns:
            Session memory data.
        """
        return self.load(thread_id, user_id=user_id)

    def save(
        self,
        memory_data: dict[str, Any],
        thread_id: str,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> bool:
        """Save session memory to the Store (sync path).

        Args:
            memory_data: Session memory data to persist.
            thread_id: Thread identifier.
            user_id: Optional user identifier.
            agent_name: Ignored.

        Returns:
            True if save succeeded, False otherwise.
        """
        from deerflow.agents.memory.storage import utc_now_iso_z

        try:
            store = self._get_store()
            memory_data = {**memory_data, "lastUpdated": utc_now_iso_z()}
            start = time.monotonic()
            store.put(self._ns(thread_id, user_id), "data", memory_data)
            latency_ms = (time.monotonic() - start) * 1000
            facts_count = len(memory_data.get("facts", []))
            logger.info(
                "Session memory saved: tenant=%s user=%s thread=%s facts=%d latency=%.1fms",
                get_current_tenant_id(),
                user_id or "",
                thread_id,
                facts_count,
                latency_ms,
            )
            from deerflow.agents.memory.retrieval import invalidate_session_cache
            invalidate_session_cache(thread_id, user_id)
            return True
        except Exception:
            logger.error("SessionStorage.save failed", exc_info=True)
            return False

    async def aload(self, thread_id: str, *, user_id: str | None = None, agent_name: str | None = None) -> dict[str, Any]:
        """Async load session memory from the Store."""
        try:
            store = self._get_store()
            item = await store.aget(self._ns(thread_id, user_id), "data")
        except Exception:
            logger.warning("SessionStorage.aload failed, returning empty session memory", exc_info=True)
            return create_empty_session_memory()

        if item is None or item.value is None:
            return create_empty_session_memory()
        return item.value

    async def areload(self, thread_id: str, *, user_id: str | None = None, agent_name: str | None = None) -> dict[str, Any]:
        """Async reload session memory (same as aload for Store backend)."""
        return await self.aload(thread_id, user_id=user_id)

    async def asave(
        self,
        memory_data: dict[str, Any],
        thread_id: str,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> bool:
        """Async save session memory to the Store."""
        from deerflow.agents.memory.storage import utc_now_iso_z

        try:
            store = self._get_store()
            memory_data = {**memory_data, "lastUpdated": utc_now_iso_z()}
            start = time.monotonic()
            await store.aput(self._ns(thread_id, user_id), "data", memory_data)
            latency_ms = (time.monotonic() - start) * 1000
            facts_count = len(memory_data.get("facts", []))
            logger.info(
                "Session memory saved: tenant=%s user=%s thread=%s facts=%d latency=%.1fms",
                get_current_tenant_id(),
                user_id or "",
                thread_id,
                facts_count,
                latency_ms,
            )
            from deerflow.agents.memory.retrieval import invalidate_session_cache
            invalidate_session_cache(thread_id, user_id)
            return True
        except Exception:
            logger.error("SessionStorage.asave failed", exc_info=True)
            return False


# Global singleton for session storage
_session_storage_instance: SessionStorage | None = None
_session_storage_lock = threading.Lock()
_session_store_factory: Any = None


def get_session_storage() -> SessionStorage | None:
    """Get the session storage instance if available.

    Session storage is only available when using StoreMemoryStorage backend.
    Returns None if the current memory storage is FileMemoryStorage.

    Returns:
        SessionStorage instance, or None if not available.
    """
    from deerflow.agents.memory.storage import StoreMemoryStorage, get_memory_storage

    global _session_storage_instance, _session_store_factory

    # Check if current memory storage is Store-backed
    memory_storage = get_memory_storage()
    if not isinstance(memory_storage, StoreMemoryStorage):
        logger.debug("Session Memory disabled: requires StoreMemoryStorage backend")
        return None

    if _session_storage_instance is not None:
        return _session_storage_instance

    with _session_storage_lock:
        if _session_storage_instance is not None:
            return _session_storage_instance

        # Reuse the same store factory as StoreMemoryStorage
        if _session_store_factory is None:
            # Extract factory from StoreMemoryStorage
            _session_store_factory = memory_storage._store_factory

        try:
            _session_storage_instance = SessionStorage(_session_store_factory)
            logger.info("Session storage: using StoreMemoryStorage backend")
            return _session_storage_instance
        except Exception as e:
            logger.warning("Failed to create SessionStorage: %s", e)
            return None


def set_session_storage(storage: SessionStorage | None) -> None:
    """Replace the session storage singleton.

    Called during tests to inject mocks or reset state.

    Args:
        storage: SessionStorage instance, or None to disable.
    """
    global _session_storage_instance
    with _session_storage_lock:
        _session_storage_instance = storage


def set_session_store_factory(factory) -> None:
    """Set the callable used by SessionStorage to obtain a Store.

    Called during Gateway lifespan to inject the request-scoped Store.

    Args:
        factory: Callable returning a BaseStore instance.
    """
    global _session_store_factory, _session_storage_instance
    _session_store_factory = factory
    # Reset singleton so it's recreated with new factory
    _session_storage_instance = None
