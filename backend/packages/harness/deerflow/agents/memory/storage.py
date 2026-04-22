"""Memory storage providers."""

from __future__ import annotations

import abc
import json
import logging
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deerflow.config.agents_config import AGENT_NAME_PATTERN
from deerflow.config.memory_config import get_memory_config
from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)

_COLL_OK = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
_PG_IDENT_OK = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def validate_postgres_identifier(value: str | None, *, kind: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise ValueError(f"memory.{kind} must be a non-empty identifier")
    if not _PG_IDENT_OK.match(normalized):
        raise ValueError(f"Invalid PostgreSQL {kind} {normalized!r}")
    return normalized


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

    def __init__(self):
        """Initialize the file memory storage."""
        # Per-user/agent memory cache: keyed by (user_id, agent_name) tuple (None = global)
        # Value: (memory_data, file_mtime)
        self._memory_cache: dict[tuple[str | None, str | None], tuple[dict[str, Any], float | None]] = {}

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
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load memory file: %s", e)
            return create_empty_memory()

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Load memory data (cached with file modification time check)."""
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)

        try:
            current_mtime = file_path.stat().st_mtime if file_path.exists() else None
        except OSError:
            current_mtime = None

        cache_key = (user_id, agent_name)
        cached = self._memory_cache.get(cache_key)

        if cached is None or cached[1] != current_mtime:
            memory_data = self._load_memory_from_file(agent_name, user_id=user_id)
            self._memory_cache[cache_key] = (memory_data, current_mtime)
            return memory_data

        return cached[0]

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        """Reload memory data from file, forcing cache invalidation."""
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)
        memory_data = self._load_memory_from_file(agent_name, user_id=user_id)

        try:
            mtime = file_path.stat().st_mtime if file_path.exists() else None
        except OSError:
            mtime = None

        cache_key = (user_id, agent_name)
        self._memory_cache[cache_key] = (memory_data, mtime)
        return memory_data

    def save(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None) -> bool:
        """Save memory data to file and update cache."""
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            memory_data["lastUpdated"] = utc_now_iso_z()

            temp_path = file_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(memory_data, f, indent=2, ensure_ascii=False)

            temp_path.replace(file_path)

            try:
                mtime = file_path.stat().st_mtime
            except OSError:
                mtime = None

            cache_key = (user_id, agent_name)
            self._memory_cache[cache_key] = (memory_data, mtime)
            logger.info("Memory saved to %s", file_path)
            return True
        except OSError as e:
            logger.error("Failed to save memory file: %s", e)
            return False


class MongoMemoryStorage(MemoryStorage):
    """Persist memory JSON as one document per (user_id, agent_name)."""

    def __init__(self):
        try:
            from pymongo import MongoClient
        except ImportError as e:
            raise ImportError(
                "MongoMemoryStorage requires pymongo. Install with: uv add pymongo "
                "or use optional dependency deerflow-harness[memory-db]."
            ) from e

        cfg = get_memory_config()
        if not cfg.connection_string or not str(cfg.connection_string).strip():
            raise ValueError("memory.connection_string is required when storage_class is MongoMemoryStorage")

        db_name = str(cfg.mongo_database).strip() or "deerflow"
        collection = str(cfg.mongo_collection).strip() or "agent_memory"
        if not _COLL_OK.match(collection):
            raise ValueError(f"Invalid memory.mongo_collection {collection!r}")

        self._client = MongoClient(str(cfg.connection_string).strip(), serverSelectionTimeoutMS=10_000)
        self._coll = self._client[db_name][collection]
        self._lock = threading.Lock()
        self._cache: dict[tuple[str | None, str | None], dict[str, Any]] = {}

    def _agent_key(self, agent_name: str | None) -> str:
        return agent_name or ""

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        if user_id is None:
            return create_empty_memory()
        cache_key = (user_id, agent_name)
        if cache_key in self._cache:
            return self._cache[cache_key]
        with self._lock:
            doc = self._coll.find_one({"user_id": user_id, "agent_name": self._agent_key(agent_name)}, projection={"payload": 1})
            data = (doc or {}).get("payload") or create_empty_memory()
            self._cache[cache_key] = data
            return data

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        if user_id is None:
            return create_empty_memory()
        with self._lock:
            doc = self._coll.find_one({"user_id": user_id, "agent_name": self._agent_key(agent_name)}, projection={"payload": 1})
            data = (doc or {}).get("payload") or create_empty_memory()
            self._cache[(user_id, agent_name)] = data
            return data

    def save(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None) -> bool:
        if user_id is None:
            logger.warning("MongoMemoryStorage.save skipped: user_id is None")
            return False
        payload = dict(memory_data)
        payload["lastUpdated"] = utc_now_iso_z()
        try:
            with self._lock:
                self._coll.replace_one(
                    {"user_id": user_id, "agent_name": self._agent_key(agent_name)},
                    {"user_id": user_id, "agent_name": self._agent_key(agent_name), "payload": payload},
                    upsert=True,
                )
                self._cache[(user_id, agent_name)] = payload
            return True
        except Exception:
            logger.exception("MongoMemoryStorage.save failed")
            return False


class PostgresMemoryStorage(MemoryStorage):
    """Persist memory JSON in a single table keyed by (user_id, agent_name)."""

    def __init__(self):
        try:
            import psycopg
            from psycopg import sql
            from psycopg.types.json import Json
        except ImportError as e:
            raise ImportError(
                "PostgresMemoryStorage requires psycopg. Install with: uv add 'psycopg[binary]' "
                "or use optional dependency deerflow-harness[memory-db]."
            ) from e

        cfg = get_memory_config()
        if not cfg.connection_string or not str(cfg.connection_string).strip():
            raise ValueError("memory.connection_string is required when storage_class is PostgresMemoryStorage")

        self._psycopg = psycopg
        self._sql = sql
        self._Json = Json
        self._dsn = str(cfg.connection_string).strip()
        self._schema = validate_postgres_identifier(cfg.postgres_schema, kind="postgres_schema") if cfg.postgres_schema else None
        self._table = validate_postgres_identifier(cfg.table, kind="table")
        self._lock = threading.Lock()
        self._cache: dict[tuple[str | None, str | None], dict[str, Any]] = {}

    def _table_ident(self):
        if self._schema:
            return self._sql.SQL("{}.{}").format(self._sql.Identifier(self._schema), self._sql.Identifier(self._table))
        return self._sql.Identifier(self._table)

    def _connect(self):
        return self._psycopg.connect(self._dsn, autocommit=True)

    def _ensure_table(self, conn) -> None:
        ddl = self._sql.SQL(
            "CREATE TABLE IF NOT EXISTS {} ("
            " user_id TEXT NOT NULL,"
            " agent_name TEXT NOT NULL DEFAULT '',"
            " payload JSONB NOT NULL,"
            " updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
            " PRIMARY KEY (user_id, agent_name)"
            ")"
        ).format(self._table_ident())
        with conn.cursor() as cur:
            cur.execute(ddl)

    def _agent_key(self, agent_name: str | None) -> str:
        return agent_name or ""

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        if user_id is None:
            return create_empty_memory()
        cache_key = (user_id, agent_name)
        if cache_key in self._cache:
            return self._cache[cache_key]
        query = self._sql.SQL("SELECT payload FROM {} WHERE user_id = %s AND agent_name = %s").format(self._table_ident())
        with self._lock:
            with self._connect() as conn:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(query, (user_id, self._agent_key(agent_name)))
                    row = cur.fetchone()
            data = row[0] if row else create_empty_memory()
            self._cache[cache_key] = data
            return data

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        if user_id is None:
            return create_empty_memory()
        query = self._sql.SQL("SELECT payload FROM {} WHERE user_id = %s AND agent_name = %s").format(self._table_ident())
        with self._lock:
            with self._connect() as conn:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(query, (user_id, self._agent_key(agent_name)))
                    row = cur.fetchone()
            data = row[0] if row else create_empty_memory()
            self._cache[(user_id, agent_name)] = data
            return data

    def save(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None) -> bool:
        if user_id is None:
            logger.warning("PostgresMemoryStorage.save skipped: user_id is None")
            return False
        payload = dict(memory_data)
        payload["lastUpdated"] = utc_now_iso_z()
        query = self._sql.SQL(
            "INSERT INTO {} (user_id, agent_name, payload) VALUES (%s, %s, %s) "
            "ON CONFLICT (user_id, agent_name) DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()"
        ).format(self._table_ident())
        try:
            with self._lock:
                with self._connect() as conn:
                    self._ensure_table(conn)
                    with conn.cursor() as cur:
                        cur.execute(query, (user_id, self._agent_key(agent_name), self._Json(payload)))
                self._cache[(user_id, agent_name)] = payload
            return True
        except Exception:
            logger.exception("PostgresMemoryStorage.save failed")
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
