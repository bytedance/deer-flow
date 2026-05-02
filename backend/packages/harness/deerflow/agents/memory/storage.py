"""Memory storage providers."""

import abc
import asyncio
import json
import logging
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langgraph.store.base import BaseStore

from deerflow.config.agents_config import AGENT_NAME_PATTERN
from deerflow.config.memory_config import get_memory_config
from deerflow.config.paths import get_paths
from deerflow.config.tenant import get_current_tenant_id

logger = logging.getLogger(__name__)


def utc_now_iso_z() -> str:
    """Current UTC time as ISO-8601 with ``Z`` suffix (matches prior naive-UTC output)."""
    return datetime.now(UTC).isoformat().removesuffix("+00:00") + "Z"


def create_empty_memory() -> dict[str, Any]:
    """Create an empty memory structure."""
    return {
        "version": "1.0",
        "lastUpdated": utc_now_iso_z(),
        "user": {
            "workContext": {"summary": "", "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": [],
    }


class MemoryStorage(abc.ABC):
    """Abstract base class for memory storage providers."""

    @abc.abstractmethod
    def load(self, agent_name: str | None = None) -> dict[str, Any]:
        """Load memory data for the given agent."""
        pass

    @abc.abstractmethod
    def reload(self, agent_name: str | None = None) -> dict[str, Any]:
        """Force reload memory data for the given agent."""
        pass

    @abc.abstractmethod
    def save(self, memory_data: dict[str, Any], agent_name: str | None = None) -> bool:
        """Save memory data for the given agent."""
        pass


class FileMemoryStorage(MemoryStorage):
    """File-based memory storage provider."""

    def __init__(self):
        """Initialize the file memory storage."""
        # Per-tenant, per-agent memory cache: keyed by (tenant_id, agent_name)
        # Value: (memory_data, file_mtime)
        self._memory_cache: dict[tuple[str, str | None], tuple[dict[str, Any], float | None]] = {}
        # Guards all reads and writes to _memory_cache across concurrent callers.
        self._cache_lock = threading.Lock()

    @staticmethod
    def _cache_key(agent_name: str | None = None) -> tuple[str, str | None]:
        """Return the cache key for the current tenant and agent."""
        return (get_current_tenant_id(), agent_name)

    def _validate_agent_name(self, agent_name: str) -> None:
        """Validate that the agent name is safe to use in filesystem paths.

        Uses the repository's established AGENT_NAME_PATTERN to ensure consistency
        across the codebase and prevent path traversal or other problematic characters.
        """
        if not agent_name:
            raise ValueError("Agent name must be a non-empty string.")
        if not AGENT_NAME_PATTERN.match(agent_name):
            raise ValueError(f"Invalid agent name {agent_name!r}: names must match {AGENT_NAME_PATTERN.pattern}")

    def _get_memory_file_path(self, agent_name: str | None = None) -> Path:
        """Get the path to the memory file."""
        if agent_name is not None:
            self._validate_agent_name(agent_name)
            return get_paths().agent_memory_file(agent_name)

        config = get_memory_config()
        if config.storage_path:
            p = Path(config.storage_path)
            return p if p.is_absolute() else get_paths().tenant_base_dir / p
        return get_paths().memory_file

    def _load_memory_from_file(self, agent_name: str | None = None) -> dict[str, Any]:
        """Load memory data from file."""
        file_path = self._get_memory_file_path(agent_name)

        if not file_path.exists():
            return create_empty_memory()

        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load memory file: %s", e)
            return create_empty_memory()

    def load(self, agent_name: str | None = None) -> dict[str, Any]:
        """Load memory data (cached with file modification time check)."""
        file_path = self._get_memory_file_path(agent_name)

        try:
            current_mtime = file_path.stat().st_mtime if file_path.exists() else None
        except OSError:
            current_mtime = None

        with self._cache_lock:
            cached = self._memory_cache.get(self._cache_key(agent_name))
            if cached is not None and cached[1] == current_mtime:
                return cached[0]

        memory_data = self._load_memory_from_file(agent_name)

        with self._cache_lock:
            self._memory_cache[self._cache_key(agent_name)] = (memory_data, current_mtime)

        return memory_data

    def reload(self, agent_name: str | None = None) -> dict[str, Any]:
        """Reload memory data from file, forcing cache invalidation."""
        file_path = self._get_memory_file_path(agent_name)
        memory_data = self._load_memory_from_file(agent_name)

        try:
            mtime = file_path.stat().st_mtime if file_path.exists() else None
        except OSError:
            mtime = None

        with self._cache_lock:
            self._memory_cache[self._cache_key(agent_name)] = (memory_data, mtime)
        return memory_data

    def save(self, memory_data: dict[str, Any], agent_name: str | None = None) -> bool:
        """Save memory data to file and update cache."""
        file_path = self._get_memory_file_path(agent_name)

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            # Shallow-copy before adding lastUpdated so the caller's dict is not
            # mutated as a side-effect, and the cache reference is not silently
            # updated before the file write succeeds.
            memory_data = {**memory_data, "lastUpdated": utc_now_iso_z()}

            temp_path = file_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(memory_data, f, indent=2, ensure_ascii=False)

            temp_path.replace(file_path)

            try:
                mtime = file_path.stat().st_mtime
            except OSError:
                mtime = None

            with self._cache_lock:
                self._memory_cache[self._cache_key(agent_name)] = (memory_data, mtime)
            logger.info("Memory saved to %s", file_path)
            return True
        except OSError as e:
            logger.error("Failed to save memory file: %s", e)
            return False


class StoreMemoryStorage(MemoryStorage):
    """LangGraph Store-based memory storage provider.

    Stores memory data in the LangGraph Store under the namespace
    ``("memory", tenant_id, agent_name)`` with key ``"data"``.

    This unifies memory persistence with the thread Store, giving
    memory the same backend (memory/sqlite/postgres) and the same
    tenant-isolation guarantees without a separate cache layer.
    """

    def __init__(self, store_factory):
        """Initialize with a callable that returns a :class:`BaseStore`.

        ``store_factory`` is invoked lazily on every load/save so that
        the storage always uses the correct Store for the current
        request context (Gateway) or process (CLI / embedded client).
        """
        self._store_factory = store_factory

    def _ns(self, agent_name: str | None = None) -> tuple[str, str, str]:
        """Return the Store namespace for the current tenant and agent."""
        return ("memory", get_current_tenant_id(), agent_name or "default")

    def _get_store(self) -> BaseStore:
        store = self._store_factory()
        if store is None:
            raise RuntimeError("Store is not available")
        return store

    def load(self, agent_name: str | None = None) -> dict[str, Any]:
        """Load memory data from the Store."""
        try:
            store = self._get_store()
            item = _run_async(store.aget(self._ns(agent_name), "data"))
        except Exception:
            logger.warning("StoreMemoryStorage.load failed, returning empty memory", exc_info=True)
            return create_empty_memory()

        if item is None or item.value is None:
            return create_empty_memory()
        return item.value

    def reload(self, agent_name: str | None = None) -> dict[str, Any]:
        """Reload memory data from the Store (same as load for Store backend)."""
        return self.load(agent_name)

    def save(self, memory_data: dict[str, Any], agent_name: str | None = None) -> bool:
        """Save memory data to the Store."""
        try:
            store = self._get_store()
            memory_data = {**memory_data, "lastUpdated": utc_now_iso_z()}
            _run_async(store.aput(self._ns(agent_name), "data", memory_data))
            logger.info("Memory saved to Store for tenant=%s agent=%s", get_current_tenant_id(), agent_name or "default")
            return True
        except Exception:
            logger.error("StoreMemoryStorage.save failed", exc_info=True)
            return False


def _run_async(coro):
    """Run an async operation from sync code, handling nested event loops."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    if loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()

    return asyncio.run(coro)


_storage_instance: MemoryStorage | None = None
_storage_lock = threading.Lock()
_store_factory: Any = None
_gateway_store: BaseStore | None = None


def set_gateway_store(store: BaseStore | None) -> None:
    """Set the Gateway's Store instance for memory storage.

    Called from the Gateway lifespan so that :class:`StoreMemoryStorage`
    can access the same Store used by threads.
    """
    global _gateway_store, _store_factory
    _gateway_store = store
    if store is not None:
        _store_factory = lambda: _gateway_store


def set_memory_storage(storage: MemoryStorage) -> None:
    """Replace the global memory storage singleton.

    Called during Gateway startup to inject a Store-backed instance,
    and during tests to reset state.
    """
    global _storage_instance
    with _storage_lock:
        _storage_instance = storage


def set_store_factory(factory) -> None:
    """Set the callable used by :class:`StoreMemoryStorage` to obtain a Store.

    In Gateway mode this is set once during lifespan to
    ``lambda: get_store(request)``.  In CLI / embedded-client mode it
    defaults to ``deerflow.runtime.store.provider.get_store``.
    """
    global _store_factory
    _store_factory = factory


def get_memory_storage() -> MemoryStorage:
    """Get the configured memory storage instance.

    Priority:
    1. Explicitly-set instance (via :func:`set_memory_storage`)
    2. Store-backed storage (when a store factory is configured)
    3. File-based storage (fallback)
    """
    global _storage_instance, _store_factory
    if _storage_instance is not None:
        return _storage_instance

    with _storage_lock:
        if _storage_instance is not None:
            return _storage_instance

        # Prefer Store-backed storage when a factory is available
        if _store_factory is not None:
            try:
                _storage_instance = StoreMemoryStorage(_store_factory)
                logger.info("Memory storage: using StoreMemoryStorage")
                return _storage_instance
            except Exception as e:
                logger.warning("Failed to create StoreMemoryStorage, falling back to FileMemoryStorage: %s", e)

        # Default to sync Store singleton when no explicit factory is set
        # (covers CLI tools and the embedded DeerFlowClient).
        try:
            from deerflow.runtime.store.provider import get_store as get_sync_store

            _store_factory = get_sync_store
            _storage_instance = StoreMemoryStorage(_store_factory)
            logger.info("Memory storage: using StoreMemoryStorage (sync store)")
            return _storage_instance
        except Exception as e:
            logger.warning("Failed to create StoreMemoryStorage with sync store, falling back to FileMemoryStorage: %s", e)

        config = get_memory_config()
        storage_class_path = config.storage_class

        try:
            module_path, class_name = storage_class_path.rsplit(".", 1)
            import importlib

            module = importlib.import_module(module_path)
            storage_class = getattr(module, class_name)

            # Validate that the configured storage is a MemoryStorage implementation
            if not isinstance(storage_class, type):
                raise TypeError(f"Configured memory storage '{storage_class_path}' is not a class: {storage_class!r}")
            if not issubclass(storage_class, MemoryStorage):
                raise TypeError(f"Configured memory storage '{storage_class_path}' is not a subclass of MemoryStorage")

            _storage_instance = storage_class()
        except Exception as e:
            logger.error(
                "Failed to load memory storage %s, falling back to FileMemoryStorage: %s",
                storage_class_path,
                e,
            )
            _storage_instance = FileMemoryStorage()

    return _storage_instance
