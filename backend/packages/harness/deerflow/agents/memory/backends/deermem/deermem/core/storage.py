"""Memory storage providers."""

import abc
import json
import logging
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import DeerMemConfig
from .paths import memory_file_path

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
    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Load memory data for the given agent."""
        pass

    @abc.abstractmethod
    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Force reload memory data for the given agent."""
        pass

    @abc.abstractmethod
    def save(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None) -> bool:
        """Save memory data for the given agent."""
        pass


class FileMemoryStorage(MemoryStorage):
    """File-based memory storage provider."""

    def __init__(self, config: DeerMemConfig):
        """Initialize the file memory storage with an injected DeerMemConfig."""
        self._config = config
        # Per-user/agent memory cache: keyed by (user_id, agent_name) tuple (None = global)
        # Value: (memory_data, file_mtime)
        self._memory_cache: dict[tuple[str | None, str | None], tuple[dict[str, Any], float | None]] = {}
        # Guards all reads and writes to _memory_cache across concurrent callers.
        self._cache_lock = threading.Lock()

    def _get_memory_file_path(self, agent_name: str | None = None, *, user_id: str | None = None) -> Path:
        """Get the path to the memory file (DeerMem's own path resolution)."""
        return memory_file_path(self._config, agent_name, user_id=user_id)

    def _load_memory_from_file(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Load memory data from file."""
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)

        if not file_path.exists():
            return create_empty_memory()

        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load memory file: %s", e)
            return create_empty_memory()

    @staticmethod
    def _cache_key(agent_name: str | None = None, *, user_id: str | None = None) -> tuple[str | None, str | None]:
        return (user_id, agent_name)

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Load memory data (cached with file modification time check)."""
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)
        cache_key = self._cache_key(agent_name, user_id=user_id)

        try:
            current_mtime = file_path.stat().st_mtime if file_path.exists() else None
        except OSError:
            current_mtime = None

        with self._cache_lock:
            cached = self._memory_cache.get(cache_key)
            if cached is not None and cached[1] == current_mtime:
                return cached[0]

        memory_data = self._load_memory_from_file(agent_name, user_id=user_id)

        with self._cache_lock:
            self._memory_cache[cache_key] = (memory_data, current_mtime)

        return memory_data

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Reload memory data from file, forcing cache invalidation."""
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)
        memory_data = self._load_memory_from_file(agent_name, user_id=user_id)
        cache_key = self._cache_key(agent_name, user_id=user_id)

        try:
            mtime = file_path.stat().st_mtime if file_path.exists() else None
        except OSError:
            mtime = None

        with self._cache_lock:
            self._memory_cache[cache_key] = (memory_data, mtime)
        return memory_data

    def save(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None) -> bool:
        """Save memory data to file and update cache."""
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)
        cache_key = self._cache_key(agent_name, user_id=user_id)

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
                self._memory_cache[cache_key] = (memory_data, mtime)
            logger.info("Memory saved to %s", file_path)
            return True
        except OSError as e:
            logger.error("Failed to save memory file: %s", e)
            return False


def create_storage(config: DeerMemConfig) -> MemoryStorage:
    """Build the configured memory storage instance for ``config``.

    Replaces the old ``get_memory_storage()`` global singleton: the caller
    (``DeerMem.__init__``) owns the returned instance. Empty ``storage_class``
    (default) -> ``FileMemoryStorage`` directly (no importlib, portable); a
    dotted path is resolved and raises ``ValueError`` on failure (fail-fast:
    memory is persistent state, so an unresolved ``storage_class`` is not
    silently substituted with ``FileMemoryStorage`` -- mirrors the
    ``manager_class`` resolution policy).
    """
    storage_class_path = config.storage_class
    if not storage_class_path:
        return FileMemoryStorage(config)

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

        return storage_class(config)
    except Exception as e:
        raise ValueError(
            f"backend_config.storage_class={storage_class_path!r} failed to load: {e}. "
            "Refusing to silently fall back to FileMemoryStorage - memory is persistent "
            "state, so a wrong store is a silent data-integrity footgun (a misspelled "
            "class path would otherwise write every fact to local JSON instead of the "
            "intended backend)."
        ) from e
