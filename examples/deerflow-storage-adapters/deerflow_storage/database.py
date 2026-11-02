"""Lazy engine/session lifecycle with an application-owned schema initializer."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from sqlalchemy import Table
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.dml import Insert

from .options import EngineOptions
from .providers import ProviderRegistry


@dataclass(frozen=True)
class DatabaseConfig:
    backend: str
    url: str | URL = field(repr=False)
    options: EngineOptions = field(default_factory=EngineOptions)


class Database:
    """Initialize once on first use. Sessions belong to callers; close them before dispose().

    No schema is created unless the caller provides an initializer. Each session has
    its own transaction. session() never commits implicitly; transaction() does.
    This synchronous API should run outside an async event loop's blocking path.
    """

    def __init__(self, config: DatabaseConfig, *, registry: ProviderRegistry | None = None, initialize: Callable[[Engine], None] | None = None) -> None:
        self._provider = (registry or ProviderRegistry()).get(config.backend)
        self._url = self._provider.url(config.url)
        self._options = config.options
        self._initialize = initialize
        self._lock = Lock()
        self._engine: Engine | None = None
        self._factory: sessionmaker[Session] | None = None
        self._closed = False

    def _start(self) -> sessionmaker[Session]:
        # Also guards creation against dispose(). Session work itself is not serialized.
        with self._lock:
            if self._closed:
                raise RuntimeError("Database has been disposed")
            if self._factory is None:
                engine = self._provider.engine(self._url, options=self._options)
                try:
                    if self._initialize is not None:
                        self._initialize(engine)
                    factory = sessionmaker(bind=engine, expire_on_commit=False)
                except Exception:
                    engine.dispose()
                    raise
                self._engine = engine
                self._factory = factory
            return self._factory

    @property
    def engine(self) -> Engine:
        self._start()
        assert self._engine is not None
        return self._engine

    def session(self) -> Session:
        return self._start()()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self.session() as session, session.begin():
            yield session

    def upsert(self, table: Table, values: Mapping[str, Any], updates: Mapping[str, Any]) -> Insert:
        if not updates:
            raise ValueError("Upsert requires at least one update value")
        return self._provider.upsert(table, values, updates)

    def dispose(self) -> None:
        """Terminal shutdown, after application workers and sessions have stopped."""
        with self._lock:
            if self._closed:
                return
            if self._engine is not None:
                self._engine.dispose()
            self._closed = True
