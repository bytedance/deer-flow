"""Memory storage providers."""

import abc
import copy
import json
import logging
import math
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deerflow.config.agents_config import AGENT_NAME_PATTERN
from deerflow.config.memory_config import get_memory_config
from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)


def utc_now_iso_z() -> str:
    """Current UTC time as ISO-8601 with ``Z`` suffix (matches prior naive-UTC output)."""
    return datetime.now(UTC).isoformat().removesuffix("+00:00") + "Z"


_EMPTY_CONTEXT_SECTION: dict[str, str] = {"summary": "", "updatedAt": ""}


def _normalize_context_section(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return dict(_EMPTY_CONTEXT_SECTION)
    section = dict(value)
    section["summary"] = value.get("summary") if isinstance(value.get("summary"), str) else ""
    section["updatedAt"] = value.get("updatedAt") if isinstance(value.get("updatedAt"), str) else ""
    return section


def _normalize_memory_fact(value: Any) -> dict[str, Any] | None:
    """Normalize a recoverable legacy fact, dropping entries without content."""
    if not isinstance(value, dict):
        return None

    content = value.get("content")
    if not isinstance(content, str) or not content.strip():
        return None

    fact = dict(value)

    fact_id = fact.get("id")
    if not isinstance(fact_id, str) or not fact_id.strip():
        fact["id"] = f"fact_{uuid.uuid4().hex[:8]}"
    else:
        fact["id"] = fact_id.strip()

    category = fact.get("category")
    fact["category"] = category.strip() if isinstance(category, str) and category.strip() else "context"

    confidence = fact.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence):
        fact["confidence"] = 0.0
    else:
        fact["confidence"] = min(1.0, max(0.0, float(confidence)))

    created_at = fact.get("createdAt")
    fact["createdAt"] = created_at.strip() if isinstance(created_at, str) else ""

    source = fact.get("source")
    fact["source"] = source.strip() if isinstance(source, str) else ""
    if "sourceError" in fact and fact["sourceError"] is not None and not isinstance(fact["sourceError"], str):
        fact.pop("sourceError")

    return fact


def normalize_memory_data(data: dict[str, Any]) -> dict[str, Any]:
    """Return a canonical memory copy compatible with legacy persisted files."""
    normalized = copy.deepcopy(data) if isinstance(data, dict) else {}

    user = normalized.get("user")
    if not isinstance(user, dict):
        user = {}
    normalized["user"] = user

    for section in ("workContext", "personalContext", "topOfMind", "cognitiveStyle"):
        user[section] = _normalize_context_section(user.get(section))

    history = normalized.get("history")
    if not isinstance(history, dict):
        history = {}
    normalized["history"] = history

    for section in ("recentMonths", "earlierContext", "longTermBackground"):
        history[section] = _normalize_context_section(history.get(section))

    facts = normalized.get("facts")
    if not isinstance(facts, list):
        normalized["facts"] = []
    else:
        normalized["facts"] = [fact for value in facts if (fact := _normalize_memory_fact(value)) is not None]

    if not isinstance(normalized.get("version"), str):
        normalized["version"] = "1.0"
    if not isinstance(normalized.get("lastUpdated"), str):
        normalized["lastUpdated"] = ""
    return normalized


def create_empty_memory() -> dict[str, Any]:
    """Create an empty memory structure."""
    return {
        "version": "1.0",
        "lastUpdated": utc_now_iso_z(),
        "user": {
            "workContext": {"summary": "", "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
            "cognitiveStyle": {"summary": "", "updatedAt": ""},
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

    def _load_memory_from_file(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Load memory data from file."""
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)

        if not file_path.exists():
            return create_empty_memory()

        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            return normalize_memory_data(data)
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
            # Canonicalize at the persistence boundary so files and cache entries
            # never retain legacy or malformed schema variants. Normalization
            # returns a copy and therefore does not mutate the caller's dict.
            memory_data = normalize_memory_data(memory_data)
            memory_data["lastUpdated"] = utc_now_iso_z()

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
