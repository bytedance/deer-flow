"""Memory storage providers.

This module intentionally exposes a single storage interface used by the
current memory updater code:

    load(agent_name=None, *, user_id=None)
    reload(agent_name=None, *, user_id=None)
    save(memory_data, agent_name=None, *, user_id=None)

Thread-specific memory persistence is not part of the current active caller
contract after the upstream rebase; the durable ownership boundary is the
current user plus optional agent scope.
"""

from __future__ import annotations

import abc
import json
import logging
import re
import shutil
import threading
import time
from datetime import datetime, timezone
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


def _cache_key(user_id: str | None, agent_name: str | None) -> tuple[str | None, str | None]:
    return (user_id, agent_name)


def utc_now_iso_z() -> str:
    """Current UTC time as ISO-8601 with ``Z`` suffix."""
    return datetime.now(timezone.utc).isoformat().removesuffix("+00:00") + "Z"


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
        pass

    @abc.abstractmethod
    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        pass

    @abc.abstractmethod
    def save(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None) -> bool:
        pass

    def delete_user_thread_storage(self, user_id: str, thread_id: str) -> None:
        """Best-effort cleanup for thread-scoped persisted artifacts.

        Current storage implementations are user/agent scoped, so the default
        behaviour is no-op unless a backend overrides it.
        """

    def delete_all_memory_for_user(self, user_id: str) -> None:
        """Delete all persisted memory owned by ``user_id``."""


class FileMemoryStorage(MemoryStorage):
    """File-based memory storage provider."""

    def __init__(self) -> None:
        self._memory_cache: dict[tuple[str | None, str | None], tuple[dict[str, Any], float | None]] = {}

    def _validate_agent_name(self, agent_name: str) -> None:
        if not agent_name:
            raise ValueError("Agent name must be a non-empty string.")
        if not AGENT_NAME_PATTERN.match(agent_name):
            raise ValueError(f"Invalid agent name {agent_name!r}: names must match {AGENT_NAME_PATTERN.pattern}")

    def _get_memory_file_path(self, agent_name: str | None = None, *, user_id: str | None = None) -> Path:
        if user_id is not None:
            if agent_name is not None:
                self._validate_agent_name(agent_name)
                return get_paths().user_agent_memory_file(user_id, agent_name)
            config = get_memory_config()
            if config.storage_path and Path(config.storage_path).is_absolute():
                return Path(config.storage_path)
            return get_paths().user_memory_file(user_id)

        if agent_name is not None:
            self._validate_agent_name(agent_name)
            return get_paths().agent_dir(agent_name) / "memory.json"

        config = get_memory_config()
        if config.storage_path:
            p = Path(config.storage_path)
            return p if p.is_absolute() else get_paths().base_dir / p
        return get_paths().memory_file

    def _load_memory_from_file(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)
        if not file_path.exists():
            return create_empty_memory()
        try:
            with open(file_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load memory file: %s", e)
            return create_empty_memory()

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)
        try:
            current_mtime = file_path.stat().st_mtime if file_path.exists() else None
        except OSError:
            current_mtime = None

        key = _cache_key(user_id, agent_name)
        cached = self._memory_cache.get(key)
        if cached is None or cached[1] != current_mtime:
            memory_data = self._load_memory_from_file(agent_name, user_id=user_id)
            self._memory_cache[key] = (memory_data, current_mtime)
            return memory_data
        return cached[0]

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)
        memory_data = self._load_memory_from_file(agent_name, user_id=user_id)
        try:
            mtime = file_path.stat().st_mtime if file_path.exists() else None
        except OSError:
            mtime = None
        self._memory_cache[_cache_key(user_id, agent_name)] = (memory_data, mtime)
        return memory_data

    def save(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None) -> bool:
        file_path = self._get_memory_file_path(agent_name, user_id=user_id)
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            payload = dict(memory_data)
            payload["lastUpdated"] = utc_now_iso_z()
            temp_path = file_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            temp_path.replace(file_path)
            try:
                mtime = file_path.stat().st_mtime
            except OSError:
                mtime = None
            self._memory_cache[_cache_key(user_id, agent_name)] = (payload, mtime)
            logger.info("Memory saved to %s", file_path)
            return True
        except OSError as e:
            logger.error("Failed to save memory file: %s", e)
            return False

    def delete_user_thread_storage(self, user_id: str, thread_id: str) -> None:
        thread_dir = get_paths().memory_dir(user_id, thread_id)
        logger.info("delete_user_thread_storage: %s", thread_dir)
        if thread_dir.exists():
            shutil.rmtree(thread_dir)

    def delete_all_memory_for_user(self, user_id: str) -> None:
        user_dir = get_paths().memory_dir(user_id)
        logger.info("delete_all_memory_for_user: %s", user_dir)
        if user_dir.exists():
            shutil.rmtree(user_dir)
        stale = [k for k in self._memory_cache if k[0] == user_id]
        for k in stale:
            del self._memory_cache[k]


class MongoMemoryStorage(MemoryStorage):
    """Persist memory JSON as one document per (user_id, agent_name)."""

    def __init__(self) -> None:
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

        dbn = str(cfg.mongo_database).strip() or str(cfg.table).strip() or "deerflow"
        coll = str(cfg.mongo_collection).strip() or "agent_memory"
        if not _COLL_OK.match(coll):
            raise ValueError(f"Invalid memory.mongo_collection {coll!r}")

        self._client = MongoClient(str(cfg.connection_string).strip(), serverSelectionTimeoutMS=10_000)
        self._coll = self._client[dbn][coll]
        self._lock = threading.Lock()
        self._ddl_lock = threading.Lock()
        self._cache: dict[tuple[str | None, str | None], tuple[dict[str, Any], float]] = {}
        self._indexes_ensured = False

    def _ensure_indexes(self) -> None:
        if self._indexes_ensured:
            return
        with self._ddl_lock:
            if self._indexes_ensured:
                return
            self._coll.create_index(
                [("user_id", 1), ("agent_name", 1)],
                unique=True,
                name="deerflow_memory_key",
            )
            self._indexes_ensured = True

    def _agent_key(self, agent_name: str | None) -> str:
        return agent_name or ""

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        if user_id is None:
            return create_empty_memory()
        self._ensure_indexes()
        key = _cache_key(user_id, agent_name)
        ag = self._agent_key(agent_name)
        with self._lock:
            doc = self._coll.find_one(
                {"user_id": user_id, "agent_name": ag},
                projection={"payload": 1, "updated_at": 1},
            )
            if doc is None:
                data, ts = create_empty_memory(), 0.0
            else:
                data = doc.get("payload") or create_empty_memory()
                raw = doc.get("updated_at")
                ts = raw.timestamp() if hasattr(raw, "timestamp") else time.time()
            cached = self._cache.get(key)
            if cached is None or cached[1] != ts:
                self._cache[key] = (data, ts)
                return data
            return cached[0]

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        if user_id is None:
            return create_empty_memory()
        self._ensure_indexes()
        key = _cache_key(user_id, agent_name)
        ag = self._agent_key(agent_name)
        with self._lock:
            doc = self._coll.find_one(
                {"user_id": user_id, "agent_name": ag},
                projection={"payload": 1, "updated_at": 1},
            )
            if doc is None:
                data, ts = create_empty_memory(), 0.0
            else:
                data = doc.get("payload") or create_empty_memory()
                raw = doc.get("updated_at")
                ts = raw.timestamp() if hasattr(raw, "timestamp") else time.time()
            self._cache[key] = (data, ts)
            return data

    def save(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None) -> bool:
        if user_id is None:
            logger.warning("MongoMemoryStorage.save skipped: user_id is None")
            return False
        self._ensure_indexes()
        key = _cache_key(user_id, agent_name)
        ag = self._agent_key(agent_name)
        payload = dict(memory_data)
        payload["lastUpdated"] = utc_now_iso_z()
        now = datetime.now(timezone.utc)
        try:
            with self._lock:
                self._coll.replace_one(
                    {"user_id": user_id, "agent_name": ag},
                    {
                        "user_id": user_id,
                        "agent_name": ag,
                        "payload": payload,
                        "updated_at": now,
                    },
                    upsert=True,
                )
                self._cache[key] = (payload, now.timestamp())
            logger.info("MongoMemoryStorage: saved user=%s agent=%r", user_id, ag)
            return True
        except Exception:
            logger.exception("MongoMemoryStorage.save failed")
            return False

    def delete_all_memory_for_user(self, user_id: str) -> None:
        self._ensure_indexes()
        with self._lock:
            self._coll.delete_many({"user_id": user_id})
            stale = [k for k in self._cache if k[0] == user_id]
            for k in stale:
                del self._cache[k]


class PostgresMemoryStorage(MemoryStorage):
    """Persist memory JSON in a single table keyed by (user_id, agent_name)."""

    def __init__(self) -> None:
        try:
            import psycopg
            from psycopg import sql
            from psycopg.types.json import Json
        except ImportError as e:
            raise ImportError(
                "PostgresMemoryStorage requires psycopg. Install with: uv add 'psycopg[binary]' "
                "or use optional dependency deerflow-harness[memory-db]."
            ) from e

        self._psycopg = psycopg
        self._sql = sql
        self._Json = Json

        cfg = get_memory_config()
        if not cfg.connection_string or not str(cfg.connection_string).strip():
            raise ValueError("memory.connection_string is required when storage_class is PostgresMemoryStorage")

        self._dsn = str(cfg.connection_string).strip()
        self._schema = (
            validate_postgres_identifier(cfg.postgres_schema, kind="schema")
            if cfg.postgres_schema and str(cfg.postgres_schema).strip()
            else None
        )
        self._table = validate_postgres_identifier(cfg.table, kind="table")
        self._lock = threading.Lock()
        self._ddl_lock = threading.Lock()
        self._cache: dict[tuple[str | None, str | None], tuple[dict[str, Any], float]] = {}
        self._table_ready = False

    def _table_ident(self):
        s = self._sql
        if self._schema:
            return s.SQL("{}.{}").format(s.Identifier(self._schema), s.Identifier(self._table))
        return s.Identifier(self._table)

    def _ensure_table(self, conn) -> None:
        if self._table_ready:
            return
        with self._ddl_lock:
            if self._table_ready:
                return
            s = self._sql
            tbl = self._table_ident()
            ddl = s.SQL(
                "CREATE TABLE IF NOT EXISTS {} ("
                " user_id TEXT NOT NULL,"
                " agent_name TEXT NOT NULL DEFAULT '',"
                " payload JSONB NOT NULL,"
                " updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
                " PRIMARY KEY (user_id, agent_name)"
                ")"
            ).format(tbl)
            with conn.cursor() as cur:
                cur.execute(ddl)
            self._table_ready = True

    def _connect(self):
        return self._psycopg.connect(self._dsn, autocommit=True)

    def _agent_key(self, agent_name: str | None) -> str:
        return agent_name or ""

    def _fetch(self, user_id: str, agent_name: str | None) -> tuple[dict[str, Any], float]:
        ag = self._agent_key(agent_name)
        s = self._sql
        tbl = self._table_ident()
        q = s.SQL(
            "SELECT payload, EXTRACT(EPOCH FROM updated_at)::float "
            "FROM {} WHERE user_id = %s AND agent_name = %s"
        ).format(tbl)
        with self._connect() as conn:
            self._ensure_table(conn)
            with conn.cursor() as cur:
                cur.execute(q, (user_id, ag))
                row = cur.fetchone()
        if row is None:
            return create_empty_memory(), 0.0
        payload, epoch = row
        data = payload if isinstance(payload, dict) else dict(payload) if payload is not None else create_empty_memory()
        return data, float(epoch or 0.0)

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        if user_id is None:
            return create_empty_memory()
        key = _cache_key(user_id, agent_name)
        with self._lock:
            data, ts = self._fetch(user_id, agent_name)
            cached = self._cache.get(key)
            if cached is None or cached[1] != ts:
                self._cache[key] = (data, ts)
                return data
            return cached[0]

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        if user_id is None:
            return create_empty_memory()
        key = _cache_key(user_id, agent_name)
        with self._lock:
            data, ts = self._fetch(user_id, agent_name)
            self._cache[key] = (data, ts)
            return data

    def save(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None) -> bool:
        if user_id is None:
            logger.warning("PostgresMemoryStorage.save skipped: user_id is None")
            return False
        key = _cache_key(user_id, agent_name)
        ag = self._agent_key(agent_name)
        payload = dict(memory_data)
        payload["lastUpdated"] = utc_now_iso_z()
        s = self._sql
        tbl = self._table_ident()
        upsert = s.SQL(
            "INSERT INTO {} (user_id, agent_name, payload, updated_at) "
            "VALUES (%s, %s, %s, NOW()) "
            "ON CONFLICT (user_id, agent_name) "
            "DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW() "
            "RETURNING EXTRACT(EPOCH FROM updated_at)::float"
        ).format(tbl)
        try:
            with self._lock:
                with self._connect() as conn:
                    self._ensure_table(conn)
                    with conn.cursor() as cur:
                        cur.execute(upsert, (user_id, ag, self._Json(payload)))
                        row = cur.fetchone()
                ts = float(row[0]) if row and row[0] is not None else time.time()
                self._cache[key] = (payload, ts)
            logger.info("PostgresMemoryStorage: saved user=%s agent=%r", user_id, ag)
            return True
        except Exception:
            logger.exception("PostgresMemoryStorage.save failed")
            return False

    def delete_all_memory_for_user(self, user_id: str) -> None:
        s = self._sql
        tbl = self._table_ident()
        q = s.SQL("DELETE FROM {} WHERE user_id = %s").format(tbl)
        with self._lock:
            with self._connect() as conn:
                self._ensure_table(conn)
                with conn.cursor() as cur:
                    cur.execute(q, (user_id,))
            stale = [k for k in self._cache if k[0] == user_id]
            for k in stale:
                del self._cache[k]

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
        logger.info("storage_class_path: %s", storage_class_path)

        try:
            module_path, class_name = storage_class_path.rsplit(".", 1)
            import importlib

            module = importlib.import_module(module_path)
            storage_class = getattr(module, class_name)
            if not isinstance(storage_class, type):
                raise TypeError(f"Configured memory storage {storage_class_path!r} is not a class: {storage_class!r}")
            if not issubclass(storage_class, MemoryStorage):
                raise TypeError(f"Configured memory storage {storage_class_path!r} is not a subclass of MemoryStorage")
            _storage_instance = storage_class()
        except Exception as e:
            logger.error(
                "Failed to load memory storage %s, falling back to FileMemoryStorage: %s",
                storage_class_path,
                e,
            )
            _storage_instance = FileMemoryStorage()

    return _storage_instance
