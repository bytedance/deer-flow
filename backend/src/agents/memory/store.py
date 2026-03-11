"""Memory store abstractions and backend implementations."""

import json
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol

from src.agents.memory.constants import is_postgres_backend, normalize_memory_backend
from src.agents.memory.scope import MemoryScope
from src.config.memory_config import get_memory_config
from src.config.paths import get_paths


def create_empty_memory() -> dict[str, Any]:
    """Create an empty memory structure."""
    return {
        "version": "1.0",
        "lastUpdated": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
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


class MemoryStore(Protocol):
    """Storage interface for memory persistence backends."""

    def get_memory(self, scope: MemoryScope, agent_name: str | None = None) -> dict[str, Any]: ...

    def reload_memory(self, scope: MemoryScope, agent_name: str | None = None) -> dict[str, Any]: ...

    def save_memory(self, scope: MemoryScope, memory_data: dict[str, Any], agent_name: str | None = None) -> bool: ...


class FileMemoryStore:
    """File-backed memory store with mtime-based cache."""

    def __init__(self):
        # key: (scope_key, agent_name) -> (memory_data, file_mtime)
        self._cache: dict[tuple[str, str | None], tuple[dict[str, Any], float | None]] = {}

    def _get_file_path(self, scope: MemoryScope, agent_name: str | None = None) -> Path:
        if scope.is_global and agent_name is not None:
            return get_paths().agent_memory_file(agent_name)

        if scope.is_global and agent_name is None:
            config = get_memory_config()
            if config.storage_path:
                p = Path(config.storage_path)
                return p if p.is_absolute() else get_paths().base_dir / p
            return get_paths().memory_file

        scope_dir = get_paths().base_dir / "memory" / scope.workspace_type / scope.workspace_id
        if agent_name is None:
            return scope_dir / "memory.json"

        return scope_dir / "agents" / f"{agent_name.lower()}.json"

    def _load_memory(self, file_path: Path) -> dict[str, Any]:
        if not file_path.exists():
            return create_empty_memory()

        try:
            with open(file_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Failed to load memory file {file_path}: {e}")
            return create_empty_memory()

    def get_memory(self, scope: MemoryScope, agent_name: str | None = None) -> dict[str, Any]:
        cache_key = (scope.key, agent_name)
        file_path = self._get_file_path(scope, agent_name)

        try:
            current_mtime = file_path.stat().st_mtime if file_path.exists() else None
        except OSError:
            current_mtime = None

        cached = self._cache.get(cache_key)
        if cached is None or cached[1] != current_mtime:
            data = self._load_memory(file_path)
            self._cache[cache_key] = (data, current_mtime)
            return data

        return cached[0]

    def reload_memory(self, scope: MemoryScope, agent_name: str | None = None) -> dict[str, Any]:
        cache_key = (scope.key, agent_name)
        file_path = self._get_file_path(scope, agent_name)
        memory_data = self._load_memory(file_path)

        try:
            mtime = file_path.stat().st_mtime if file_path.exists() else None
        except OSError:
            mtime = None

        self._cache[cache_key] = (memory_data, mtime)
        return memory_data

    def save_memory(self, scope: MemoryScope, memory_data: dict[str, Any], agent_name: str | None = None) -> bool:
        cache_key = (scope.key, agent_name)
        file_path = self._get_file_path(scope, agent_name)

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            memory_data["lastUpdated"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")

            temp_path = file_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(memory_data, f, indent=2, ensure_ascii=False)

            temp_path.replace(file_path)

            try:
                mtime = file_path.stat().st_mtime
            except OSError:
                mtime = None

            self._cache[cache_key] = (memory_data, mtime)
            print(f"Memory saved to {file_path}")
            return True
        except OSError as e:
            print(f"Failed to save memory file {file_path}: {e}")
            return False


class PostgresMemoryStore:
    """Postgres-backed memory store with document semantics.

    This mirrors FileMemoryStore behavior by treating profile_json as the
    canonical memory document for a scope.
    """

    def __init__(self, database_url: str):
        self._database_url = database_url

    def _connect(self):
        try:
            psycopg = import_module("psycopg")
        except ImportError as e:
            raise RuntimeError("psycopg is required for memory.backend=postgres") from e

        return psycopg.connect(self._database_url)

    def get_memory(self, scope: MemoryScope, agent_name: str | None = None) -> dict[str, Any]:
        _ = agent_name
        empty = create_empty_memory()

        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT profile_json
                    FROM memory_profiles
                    WHERE workspace_type = %s AND workspace_id = %s
                    """,
                    (scope.workspace_type, scope.workspace_id),
                )
                row = cur.fetchone()
                return dict(row[0]) if row else empty
        except Exception as e:
            print(f"Failed to load memory from postgres: {e}")
            return empty

    def reload_memory(self, scope: MemoryScope, agent_name: str | None = None) -> dict[str, Any]:
        return self.get_memory(scope, agent_name)

    def save_memory(self, scope: MemoryScope, memory_data: dict[str, Any], agent_name: str | None = None) -> bool:
        _ = agent_name
        try:
            profile_json = dict(memory_data)
            profile_json["lastUpdated"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")

            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO memory_profiles (workspace_type, workspace_id, version, profile_json, last_updated, updated_at)
                    VALUES (%s, %s, %s, %s::jsonb, NOW(), NOW())
                    ON CONFLICT (workspace_type, workspace_id)
                    DO UPDATE SET
                      version = EXCLUDED.version,
                      profile_json = EXCLUDED.profile_json,
                      last_updated = NOW(),
                      updated_at = NOW()
                    """,
                    (scope.workspace_type, scope.workspace_id, profile_json.get("version", "1.0"), json.dumps(profile_json)),
                )

                conn.commit()

            return True
        except Exception as e:
            print(f"Failed to save memory to postgres: {e}")
            return False


_store_instance: MemoryStore | None = None
_store_backend: str | None = None


def get_memory_store() -> MemoryStore:
    """Get memory store singleton, refreshing if backend changes."""
    global _store_backend, _store_instance

    config = get_memory_config()
    backend = normalize_memory_backend(config.backend)

    if _store_instance is not None and _store_backend == backend:
        return _store_instance

    if is_postgres_backend(backend):
        if not config.database_url:
            raise ValueError("memory.database_url is required when memory.backend=postgres")
        _store_instance = PostgresMemoryStore(config.database_url)
    else:
        _store_instance = FileMemoryStore()

    _store_backend = backend
    return _store_instance
