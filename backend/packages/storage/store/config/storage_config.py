"""Unified storage backend configuration for checkpointer and application data.

SQLite: checkpointer → {sqlite_dir}/checkpoints.db, app → {sqlite_dir}/deerflow.db
        (separate files to avoid write-lock contention)
Postgres: shared URL, independent connection pools per layer.

Sensitive values use $VAR syntax resolved by AppConfig.resolve_env_variables()
before this config is instantiated.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field


def _strip_legacy_state_prefix(path: str) -> str:
    """Keep old .deer-flow/* config values compatible with Paths.base_dir."""
    prefix = ".deer-flow/"
    if path == ".deer-flow":
        return "."
    if path.startswith(prefix):
        return path[len(prefix) :]
    return path


class StorageConfig(BaseModel):
    driver: Literal["mysql", "sqlite", "postgres", "postgresql"] = Field(
        default="sqlite",
        description="Storage driver for both checkpointer and application data. 'sqlite' for single-node deployment (default),'postgres' for production multi-node deployment, 'mysql' for MySQL databases.",
    )
    sqlite_dir: str = Field(
        default=".deer-flow/data",
        description="Directory for SQLite .db files (sqlite driver only).",
    )
    username: str = Field(default="", description="db username ")
    password: str = Field(default="", description="db password. Use $VAR syntax in config.yaml to read from .env.")
    host: str = Field(default="localhost", description="db host.")
    port: int = Field(default=5432, description="db port.")
    db_name: str = Field(default="deerflow", description="db database name.")
    database_url: str = Field(default="", description="Complete SQLAlchemy database URL. Takes precedence for non-SQLite drivers.")
    sqlite_db_path: str = Field(default=".deer-flow/data", description="Directory for SQLite .db files (sqlite driver only).")
    echo_sql: bool = Field(default=False, description="Log all SQL statements (debug only).")
    pool_size: int = Field(default=5, description="Connection pool size per layer.")

    # -- Derived helpers (not user-configured) --

    @property
    def _resolved_sqlite_dir(self) -> str:
        """Resolve sqlite_dir to an absolute path under DeerFlow's base dir."""
        from pathlib import Path

        path = Path(self.sqlite_dir)
        if path.is_absolute():
            return str(path.resolve())

        try:
            from deerflow.config.paths import resolve_path

            return str(resolve_path(_strip_legacy_state_prefix(self.sqlite_dir)))
        except ImportError:
            return str(path.resolve())

    @property
    def sqlite_storage_path(self) -> str:
        """SQLite file path for storage-owned app data and checkpointer."""
        return os.path.join(self._resolved_sqlite_dir, "deerflow.db")
