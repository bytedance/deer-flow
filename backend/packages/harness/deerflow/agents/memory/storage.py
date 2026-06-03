"""Memory storage providers."""

import abc
import json
import logging
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deerflow.config.agents_config import AGENT_NAME_PATTERN
from deerflow.config.memory_config import get_memory_config
from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)

_deleted_agent_memory_targets: dict[tuple[str | None, str], datetime] = {}
_deleted_agent_memory_lock = threading.Lock()
_DELETED_AGENT_MEMORY_MARKS_DIR = ".deleted-agent-memory"


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


def _deleted_agent_key(agent_name: str, *, user_id: str | None = None) -> tuple[str | None, str]:
    return (user_id, agent_name.lower())


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_iso_datetime(value: str) -> datetime | None:
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        return _normalize_datetime(datetime.fromisoformat(normalized))
    except ValueError:
        return None


def _deleted_agent_mark_file(agent_name: str, *, user_id: str | None = None) -> Path:
    normalized_agent_name = agent_name.lower()
    paths = get_paths()
    if user_id is not None:
        return paths.user_dir(user_id) / _DELETED_AGENT_MEMORY_MARKS_DIR / f"{normalized_agent_name}.json"
    return paths.base_dir / _DELETED_AGENT_MEMORY_MARKS_DIR / f"{normalized_agent_name}.json"


def _write_deleted_agent_mark(agent_name: str, deleted_at: datetime, *, user_id: str | None = None) -> None:
    mark_file = _deleted_agent_mark_file(agent_name, user_id=user_id)
    mark_file.parent.mkdir(parents=True, exist_ok=True)
    temp_path = mark_file.with_suffix(f".{uuid.uuid4().hex}.tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump({"deletedAt": deleted_at.isoformat().replace("+00:00", "Z")}, f, ensure_ascii=False)
    temp_path.replace(mark_file)


def _read_deleted_agent_mark(agent_name: str, *, user_id: str | None = None) -> datetime | None:
    mark_file = _deleted_agent_mark_file(agent_name, user_id=user_id)
    try:
        with open(mark_file, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read deleted-agent memory marker %s: %s", mark_file, e)
        return None

    deleted_at = data.get("deletedAt")
    if not isinstance(deleted_at, str):
        return None
    return _parse_iso_datetime(deleted_at)


def mark_agent_memory_deleted(agent_name: str, *, user_id: str | None = None) -> None:
    """Record that an agent memory target was deleted across workers."""
    deleted_at = datetime.now(UTC)
    _write_deleted_agent_mark(agent_name, deleted_at, user_id=user_id)
    with _deleted_agent_memory_lock:
        _deleted_agent_memory_targets[_deleted_agent_key(agent_name, user_id=user_id)] = deleted_at


def clear_deleted_agent_memory_mark(agent_name: str, *, user_id: str | None = None) -> None:
    """Clear the deleted-agent memory marker for one target."""
    try:
        _deleted_agent_mark_file(agent_name, user_id=user_id).unlink(missing_ok=True)
    except OSError as e:
        logger.warning("Failed to clear deleted-agent memory marker for %s: %s", agent_name, e)
    with _deleted_agent_memory_lock:
        _deleted_agent_memory_targets.pop(_deleted_agent_key(agent_name, user_id=user_id), None)


def clear_deleted_agent_memory_marks() -> None:
    """Clear deleted-agent memory markers. Intended for tests."""
    paths = get_paths()
    marker_roots = [paths.base_dir / _DELETED_AGENT_MEMORY_MARKS_DIR]
    users_dir = paths.base_dir / "users"
    if users_dir.exists():
        marker_roots.extend(user_dir / _DELETED_AGENT_MEMORY_MARKS_DIR for user_dir in users_dir.iterdir() if user_dir.is_dir())
    for marker_root in marker_roots:
        if marker_root.exists():
            for marker_file in marker_root.glob("*.json"):
                try:
                    marker_file.unlink()
                except OSError as e:
                    logger.warning("Failed to remove deleted-agent memory marker %s: %s", marker_file, e)
    with _deleted_agent_memory_lock:
        _deleted_agent_memory_targets.clear()


def is_agent_memory_obsolete(
    agent_name: str | None,
    *,
    user_id: str | None = None,
    context_timestamp: datetime | None = None,
) -> bool:
    """Return whether a memory update context predates the latest agent deletion."""
    if agent_name is None or context_timestamp is None:
        return False

    context_timestamp = _normalize_datetime(context_timestamp)

    with _deleted_agent_memory_lock:
        deleted_at = _deleted_agent_memory_targets.get(_deleted_agent_key(agent_name, user_id=user_id))
    if deleted_at is None:
        deleted_at = _read_deleted_agent_mark(agent_name, user_id=user_id)
        if deleted_at is not None:
            with _deleted_agent_memory_lock:
                _deleted_agent_memory_targets[_deleted_agent_key(agent_name, user_id=user_id)] = deleted_at

    return deleted_at is not None and context_timestamp <= deleted_at


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

    def __init__(self):
        """Initialize the file memory storage."""
        # Per-user/agent memory cache: keyed by (user_id, agent_name) tuple (None = global)
        # Value: (memory_data, file_mtime)
        self._memory_cache: dict[tuple[str | None, str | None], tuple[dict[str, Any], float | None]] = {}
        # Guards all reads and writes to _memory_cache across concurrent callers.
        self._cache_lock = threading.Lock()

    def _validate_agent_name(self, agent_name: str) -> None:
        """Validate that the agent name is safe to use in filesystem paths.

        Uses the repository's established AGENT_NAME_PATTERN to ensure consistency
        across the codebase and prevent path traversal or other problematic characters.
        """
        if not agent_name:
            raise ValueError("Agent name must be a non-empty string.")
        if not AGENT_NAME_PATTERN.match(agent_name):
            raise ValueError(f"Invalid agent name {agent_name!r}: names must match {AGENT_NAME_PATTERN.pattern}")

    def _get_memory_file_path(self, agent_name: str | None = None, *, user_id: str | None = None) -> Path:
        """Get the path to the memory file."""
        if user_id is not None:
            if agent_name is not None:
                self._validate_agent_name(agent_name)
                return get_paths().user_agent_memory_file(user_id, agent_name)
            config = get_memory_config()
            if config.storage_path and Path(config.storage_path).is_absolute():
                return Path(config.storage_path)
            return get_paths().user_memory_file(user_id)
        # Legacy: no user_id
        if agent_name is not None:
            self._validate_agent_name(agent_name)
            return get_paths().agent_memory_file(agent_name)
        config = get_memory_config()
        if config.storage_path:
            p = Path(config.storage_path)
            return p if p.is_absolute() else get_paths().base_dir / p
        return get_paths().memory_file

    def _agent_config_exists(self, agent_name: str, *, user_id: str | None = None) -> bool:
        """Return whether the per-agent memory target still has an agent config."""
        paths = get_paths()
        if user_id is not None:
            return (paths.user_agent_dir(user_id, agent_name) / "config.yaml").exists()
        return (paths.agent_dir(agent_name) / "config.yaml").exists()

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

    def discard_cache(self, agent_name: str | None = None, *, user_id: str | None = None) -> None:
        """Remove cached memory for one target."""
        cache_key = self._cache_key(agent_name, user_id=user_id)
        with self._cache_lock:
            self._memory_cache.pop(cache_key, None)

    def save(
        self,
        memory_data: dict[str, Any],
        agent_name: str | None = None,
        *,
        user_id: str | None = None,
        context_timestamp: datetime | None = None,
    ) -> bool:
        """Save memory data to file and update cache."""
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)
        cache_key = self._cache_key(agent_name, user_id=user_id)

        try:
            if is_agent_memory_obsolete(agent_name, user_id=user_id, context_timestamp=context_timestamp):
                self.discard_cache(agent_name, user_id=user_id)
                logger.info(
                    "Skipped obsolete memory save for deleted agent %s",
                    agent_name,
                )
                return False

            if agent_name is not None and not self._agent_config_exists(agent_name, user_id=user_id):
                self.discard_cache(agent_name, user_id=user_id)
                logger.info(
                    "Skipped memory save for deleted or missing agent %s",
                    agent_name,
                )
                return False

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


def discard_memory_cache(agent_name: str | None = None, *, user_id: str | None = None) -> None:
    """Clear cached memory for one target when the storage provider supports it."""
    storage = get_memory_storage()
    discard_cache = getattr(storage, "discard_cache", None)
    if callable(discard_cache):
        discard_cache(agent_name, user_id=user_id)


def save_memory_data(
    memory_data: dict[str, Any],
    agent_name: str | None = None,
    *,
    user_id: str | None = None,
    context_timestamp: datetime | None = None,
    storage: MemoryStorage | None = None,
) -> bool:
    """Save memory while honoring deleted-agent guards when available."""
    storage = storage or get_memory_storage()
    if isinstance(storage, FileMemoryStorage):
        return storage.save(memory_data, agent_name, user_id=user_id, context_timestamp=context_timestamp)
    if is_agent_memory_obsolete(agent_name, user_id=user_id, context_timestamp=context_timestamp):
        logger.info("Skipped obsolete memory save for deleted agent %s", agent_name)
        return False
    return storage.save(memory_data, agent_name, user_id=user_id)


_storage_instance: MemoryStorage | None = None
_storage_lock = threading.Lock()


def get_memory_storage() -> MemoryStorage:
    """Get the configured memory storage instance."""
    global _storage_instance
    if _storage_instance is not None:
        return _storage_instance

    with _storage_lock:
        if _storage_instance is not None:
            return _storage_instance

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
