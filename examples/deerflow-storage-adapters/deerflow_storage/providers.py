"""Backend-specific operations; this module never reads application environment variables."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import Table, create_engine, event
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.sql.dml import Insert

from .options import EngineOptions


def _parse_url(configured: str | URL) -> URL:
    try:
        return make_url(configured)
    except Exception:
        # SQLAlchemy's parse errors may include the original connection string.
        raise ValueError("Invalid database URL") from None


class DatabaseProvider(Protocol):
    """A provider owns URL validation, engine construction and its upsert dialect."""

    name: str

    def url(self, configured: str | URL) -> URL: ...
    def engine(self, url: URL, *, options: EngineOptions = EngineOptions()) -> Engine: ...
    def upsert(self, table: Table, values: Mapping[str, Any], updates: Mapping[str, Any]) -> Insert: ...


class MySQLProvider:
    name = "mysql"

    def url(self, configured: str | URL) -> URL:
        url = _parse_url(configured)
        if url.drivername not in ("mysql", "mysql+pymysql") or not url.database:
            raise ValueError("MySQL provider requires a mysql+pymysql URL and database name")
        return url.set(drivername="mysql+pymysql").update_query_dict({"charset": "utf8mb4"})

    def engine(self, url: URL, *, options: EngineOptions = EngineOptions()) -> Engine:
        return create_engine(
            self.url(url),
            pool_pre_ping=True,
            pool_size=options.pool_size,
            max_overflow=options.max_overflow,
            pool_timeout=options.pool_timeout,
            pool_recycle=options.pool_recycle,
            isolation_level="READ COMMITTED",
            connect_args={"connect_timeout": options.connect_timeout, "read_timeout": options.read_timeout, "write_timeout": options.write_timeout},
        )

    def upsert(self, table: Table, values: Mapping[str, Any], updates: Mapping[str, Any]) -> Insert:
        from sqlalchemy.dialects.mysql import insert

        return insert(table).values(**values).on_duplicate_key_update(**updates)


class SQLiteProvider:
    name = "sqlite"

    def url(self, configured: str | URL) -> URL:
        url = _parse_url(configured)
        if url.drivername != "sqlite":
            raise ValueError("SQLite provider requires a sqlite URL")
        return url

    def engine(self, url: URL, *, options: EngineOptions = EngineOptions()) -> Engine:
        url = self.url(url)
        if url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, pool_pre_ping=True, connect_args={"check_same_thread": False, "timeout": options.sqlite_busy_timeout})

        @event.listens_for(engine, "connect")
        def configure_connection(connection, _record):
            cursor = connection.cursor()
            try:
                cursor.execute(f"PRAGMA busy_timeout={max(1, round(options.sqlite_busy_timeout * 1000))}")
                cursor.execute(f"PRAGMA foreign_keys={'ON' if options.sqlite_foreign_keys else 'OFF'}")
                if options.sqlite_wal:
                    mode = cursor.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                    if mode not in ("wal", "memory"):
                        raise RuntimeError("SQLite WAL could not be enabled")
                # FULL preserves durable commits; applications can separately assess NORMAL.
                cursor.execute("PRAGMA synchronous=FULL")
            finally:
                cursor.close()

        return engine

    def upsert(self, table: Table, values: Mapping[str, Any], updates: Mapping[str, Any]) -> Insert:
        from sqlalchemy.dialects.sqlite import insert

        if not table.primary_key.columns:
            raise ValueError("SQLite upsert requires a primary key")
        return insert(table).values(**values).on_conflict_do_update(index_elements=list(table.primary_key.columns), set_=dict(updates))


class ProviderRegistry:
    """Registries are instance-scoped, so extensions and tests cannot pollute each other."""

    def __init__(self) -> None:
        self._providers: dict[str, DatabaseProvider] = {}
        self.register(MySQLProvider())
        self.register(SQLiteProvider())

    def register(self, adapter: DatabaseProvider) -> None:
        if not adapter.name or adapter.name in self._providers:
            raise ValueError("Storage provider name is empty or already registered")
        self._providers[adapter.name] = adapter

    def get(self, name: str) -> DatabaseProvider:
        try:
            return self._providers[name]
        except KeyError:
            raise ValueError("Unknown storage provider; available: " + ", ".join(self._providers)) from None
