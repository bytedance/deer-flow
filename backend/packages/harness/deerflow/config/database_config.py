"""Unified database backend configuration.

Controls BOTH the LangGraph checkpointer and the DeerFlow application
persistence layer (runs, threads metadata, users, etc.). The user
configures one backend; the system handles physical separation details.

SQLite mode: checkpointer and app share a single .db file
({sqlite_dir}/deerflow.db) with WAL journal mode enabled on every
connection. WAL allows concurrent readers and a single writer without
blocking, making a unified file safe for both workloads.  Writers
that contend for the lock wait via the default 5-second sqlite3
busy timeout rather than failing immediately.

Postgres mode: both use the same database URL but maintain independent
connection pools with different lifecycles.

Memory mode: checkpointer uses MemorySaver, app uses in-memory stores.
No database is initialized.

Sensitive values (postgres_url) should use $VAR syntax in config.yaml
to reference environment variables from .env:

    database:
      backend: postgres
      postgres_url: $DATABASE_URL

The $VAR resolution is handled by AppConfig.resolve_env_variables()
before this config is instantiated -- DatabaseConfig itself does not
need to do any environment variable processing.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from deerflow.config.postgres_schema import POSTGRES_SCHEMA_PATTERN, validate_postgres_schema

logger = logging.getLogger(__name__)


def resolve_checkpoint_graph_cache_max(database_config: Any, field_name: str, default: int) -> int:
    """Read a graph-cache cap from a database config-ish object.

    Tolerates stub configs (SimpleNamespace/MagicMock in tests, missing
    section): anything that is not a plain int >= 1 falls back to
    ``default``.
    """
    section = getattr(database_config, "checkpoint_graph_cache", None)
    value = getattr(section, field_name, None)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return default
    return value


CheckpointChannelMode = Literal["full", "delta"]

DEFAULT_CHECKPOINT_SNAPSHOT_FREQUENCY = 10


class CheckpointDeltaConfig(BaseModel):
    """Tuning knobs for ``checkpoint_channel_mode: delta``.

    Ignored in ``full`` mode. Like the mode itself, these values are
    restart-required and must match across every process sharing one
    checkpoint database: the snapshot cadence is baked into each compiled
    graph's channel table, not stored in the checkpoint, so a mismatched
    process would apply a different cadence to the same threads.
    """

    snapshot_frequency: int = Field(
        default=DEFAULT_CHECKPOINT_SNAPSHOT_FREQUENCY,
        ge=1,
        description=(
            "DeltaChannel snapshot cadence: a full messages snapshot is stored "
            "every N per-step writes (higher = smaller checkpoints, slower "
            "materialization). Restart is required, and all processes sharing "
            "one checkpoint database must use the same value."
        ),
    )


class CheckpointGraphCacheConfig(BaseModel):
    """Size cap for the process-local compiled checkpoint graph cache.

    Unlike the mode and snapshot cadence, this is NOT restart-required:
    a larger/smaller cap only changes when the cache evicts, never graph
    semantics, so a hot-reloaded value takes effect on the next eviction
    check. The cache is keyed by (assistant, mode, cadence, app_config) and
    cleared wholesale at the cap.
    """

    accessor_graph_max: int = Field(
        default=64,
        ge=1,
        description=("Max compiled thread-state accessor graphs cached by the gateway (keyed per assistant, channel mode, and snapshot cadence)."),
    )


class CheckpointCacheConfig(BaseModel):
    """Delta-history cache policy. Performance-only: never frozen, never
    required to match across processes sharing one checkpoint database.

    Applies only when ``checkpoint_channel_mode`` is ``delta``. ``max_entries``
    bounds the process-local memory backend; ``0`` disables the cache
    entirely. The redis backend is bounded by ``ttl_seconds`` and the server's
    own maxmemory policy.
    """

    type: Literal["memory", "redis"] = Field(
        default="memory",
        description=("Checkpoint history cache backend. 'memory' = process-local LRU; 'redis' = shared cache for multi-worker deployments (async/Gateway path only; the sync embedded path rejects it)."),
    )
    max_entries: int = Field(
        default=128,
        ge=0,
        description="LRU capacity of the memory backend. 0 disables the cache.",
    )
    redis_url: str | None = Field(
        default=None,
        description=("Redis URL for type=redis. If omitted, DEER_FLOW_CHECKPOINT_CACHE_REDIS_URL, REDIS_URL, or redis://localhost:6379/0 is used."),
    )
    ttl_seconds: int = Field(
        default=86400,
        ge=0,
        description=(
            "Redis entry TTL; a leak safety net, not a correctness mechanism (entries are immutable). "
            "Thread deletion purges that thread's entries immediately; if the purge fails (redis outage), "
            "residual copies of the thread's history persist until this TTL expires. "
            "0 explicitly disables expiry — orphaned keys then rely on the redis maxmemory policy alone."
        ),
    )
    key_prefix: str = Field(
        default="",
        description="Optional override for the redis key prefix; defaults to a hash of the database identity.",
    )


class DatabaseConfig(BaseModel):
    backend: Literal["memory", "sqlite", "postgres"] = Field(
        default="memory",
        description=("Storage backend for both checkpointer and application data. 'memory' for development (no persistence across restarts), 'sqlite' for single-node deployment, 'postgres' for production multi-node deployment."),
    )
    checkpoint_channel_mode: CheckpointChannelMode = Field(
        default="full",
        description=(
            "Checkpoint representation for accumulating channels. "
            "'full' preserves full-value message checkpoints; 'delta' uses "
            "LangGraph DeltaChannel for messages. Restart is required, and all "
            "processes sharing one checkpoint database must use the same value."
        ),
    )
    checkpoint_delta: CheckpointDeltaConfig = Field(
        default_factory=CheckpointDeltaConfig,
        description="Delta-mode checkpoint tuning. Only applies when checkpoint_channel_mode is 'delta'.",
    )
    checkpoint_graph_cache: CheckpointGraphCacheConfig = Field(
        default_factory=CheckpointGraphCacheConfig,
        description="Size caps for the compiled checkpoint graph caches. Hot-reloadable; not restart-required.",
    )
    checkpoint_cache: CheckpointCacheConfig = Field(
        default_factory=CheckpointCacheConfig,
        description="Delta-mode checkpoint history cache. Performance-only; safe to differ across workers.",
    )
    sqlite_dir: str = Field(
        default=".deer-flow/data",
        description=("Directory for the SQLite database file. Both checkpointer and application data share {sqlite_dir}/deerflow.db."),
    )
    postgres_url: str = Field(
        default="",
        description=(
            "PostgreSQL connection URL, shared by checkpointer and app. "
            "Use $DATABASE_URL in config.yaml to reference .env. "
            "Example: postgresql://user:pass@host:5432/deerflow "
            "(the +asyncpg driver suffix is added automatically where needed)."
        ),
    )
    echo_sql: bool = Field(
        default=False,
        description="Echo all SQL statements to log (debug only).",
    )
    pool_size: int = Field(
        default=5,
        description="Connection pool size for the app ORM engine (postgres only).",
    )
    pool_recycle: int = Field(
        default=300,
        gt=0,
        description="Seconds before app ORM PostgreSQL connections are recycled.",
    )
    command_timeout: float | None = Field(
        default=30,
        gt=0,
        description="Timeout in seconds for app ORM PostgreSQL commands. Set to null to disable the command timeout.",
    )
    postgres_schema: str = Field(
        default="",
        description=(
            "PostgreSQL schema for both app ORM tables and LangGraph "
            "checkpointer/store tables (postgres only). Empty string keeps "
            "the server default search_path (usually 'public'). When set, "
            "the schema is created automatically at startup and applied via "
            "connection-level search_path. Only plain identifiers are "
            f"allowed: {POSTGRES_SCHEMA_PATTERN}."
        ),
    )

    @field_validator("postgres_schema")
    @classmethod
    def _validate_postgres_schema(cls, value: str) -> str:
        return validate_postgres_schema(value)

    # -- Legacy key migration (not user-configured) --

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_snapshot_frequency(cls, data: Any) -> Any:
        """Carry the pre-rename top-level ``checkpoint_delta_snapshot_frequency``
        key onto ``checkpoint_delta.snapshot_frequency``.

        ``DatabaseConfig`` ignores unknown keys (pydantic ``extra="ignore"``),
        so without this shim a config.yaml written against the old flat key
        would silently fall back to the new default cadence instead of the
        operator's chosen value. An explicitly set nested key always wins.
        """
        if not isinstance(data, dict) or "checkpoint_delta_snapshot_frequency" not in data:
            return data
        data = dict(data)
        legacy_value = data.pop("checkpoint_delta_snapshot_frequency")
        nested = data.get("checkpoint_delta")
        if isinstance(nested, dict):
            if "snapshot_frequency" in nested:
                logger.warning(
                    "Both database.checkpoint_delta_snapshot_frequency (deprecated) and database.checkpoint_delta.snapshot_frequency are set; the nested key wins.",
                )
                return data
            data["checkpoint_delta"] = {**nested, "snapshot_frequency": legacy_value}
        elif nested is None:
            data["checkpoint_delta"] = {"snapshot_frequency": legacy_value}
        else:
            # Programmatically constructed CheckpointDeltaConfig instance: the
            # explicit object wins over the legacy scalar.
            logger.warning(
                "Ignoring deprecated database.checkpoint_delta_snapshot_frequency because database.checkpoint_delta is already set.",
            )
            return data
        logger.warning(
            "database.checkpoint_delta_snapshot_frequency is deprecated; use database.checkpoint_delta.snapshot_frequency instead. Carried the legacy value (%r) forward.",
            legacy_value,
        )
        return data

    # -- Derived helpers (not user-configured) --

    @property
    def _resolved_sqlite_dir(self) -> str:
        """Resolve sqlite_dir to an absolute path (relative to CWD)."""
        from pathlib import Path

        return str(Path(self.sqlite_dir).resolve())

    @property
    def sqlite_path(self) -> str:
        """Unified SQLite file path shared by checkpointer and app."""
        return os.path.join(self._resolved_sqlite_dir, "deerflow.db")

    # Backward-compatible aliases
    @property
    def checkpointer_sqlite_path(self) -> str:
        """SQLite file path for the LangGraph checkpointer (alias for sqlite_path)."""
        return self.sqlite_path

    @property
    def app_sqlite_path(self) -> str:
        """SQLite file path for application ORM data (alias for sqlite_path)."""
        return self.sqlite_path

    @property
    def app_sqlalchemy_url(self) -> str:
        """SQLAlchemy async URL for the application ORM engine."""
        if self.backend == "sqlite":
            return f"sqlite+aiosqlite:///{self.sqlite_path}"
        if self.backend == "postgres":
            url = self.postgres_url
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            elif url.startswith("postgres://"):
                # libpq's short alias: accepted by the psycopg checkpointer, but not a SQLAlchemy dialect.
                url = url.replace("postgres://", "postgresql+asyncpg://", 1)
            return url
        raise ValueError(f"No SQLAlchemy URL for backend={self.backend!r}")

    @property
    def app_sync_sqlalchemy_url(self) -> str:
        """SQLAlchemy *synchronous* URL for the application ORM data.

        Used by the ``agent_storage.backend: db`` store, whose consumers (the
        LangGraph graph factory, the setup/update tools) are synchronous and may
        run on the event loop or in a separate process from the gateway, where an
        async engine cannot be driven. Points at the same database file/server as
        :meth:`app_sqlalchemy_url`; only the driver differs (both drivers —
        stdlib sqlite3 and psycopg — ship with the app, so this adds no
        dependency).
        """
        if self.backend == "sqlite":
            return f"sqlite:///{self.sqlite_path}"
        if self.backend == "postgres":
            url = self.postgres_url
            if url.startswith("postgresql+asyncpg://"):
                url = url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
            elif url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+psycopg://", 1)
            elif url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+psycopg://", 1)
            return url
        raise ValueError(f"No SQLAlchemy URL for backend={self.backend!r}")
