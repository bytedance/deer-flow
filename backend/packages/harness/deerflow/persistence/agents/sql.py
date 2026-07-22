"""SQL-backed agent store (synchronous).

Serves the ``agent_storage.backend: db`` path. It is intentionally synchronous
and uses its own small engine (see :mod:`deerflow.persistence.agents.base` for
why the store is sync). The engine points at the same database the async
persistence layer manages — the ``agents`` table is created by that layer's
Alembic bootstrap (migration ``0006``); this store only reads and writes rows.

Both the sqlite (stdlib) and postgres (psycopg) sync drivers already ship with
the app, so this adds no dependency.
"""

from __future__ import annotations

import logging
import shutil
import threading
import uuid
from collections.abc import Hashable
from datetime import UTC, datetime

from sqlalchemy import Engine, create_engine, delete, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from deerflow.config.agents_config import AgentConfig
from deerflow.config.paths import get_paths
from deerflow.persistence.agents.base import (
    AgentDeleteOutcome,
    AgentExistsError,
    AgentStore,
    parse_agent_config,
)
from deerflow.persistence.agents.model import AgentRow
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.utils.time import coerce_iso

logger = logging.getLogger(__name__)

# Cache sync engines by URL: the store is constructed on demand in multiple
# places (gateway routes, the graph factory) and each process should reuse one
# engine/pool rather than opening a connection per call. The lock keeps two
# threads first-touching the same URL from building — and registering connect
# listeners on — duplicate engines.
_engines: dict[str, Engine] = {}
_engines_lock = threading.Lock()


def _build_engine(url: str) -> Engine:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)
    if url.startswith("sqlite"):
        # Mirror the async engine's per-connection PRAGMAs (persistence/engine.py).
        # journal_mode=WAL is persistent on the DB file (the async bootstrap sets
        # it), but synchronous and busy_timeout are per-connection: without this
        # these sync connections run synchronous=FULL and pysqlite's default 5s
        # busy_timeout rather than the async engine's NORMAL + 30s. Match them so
        # both engines behave identically against the shared DB and a concurrent
        # writer waits up to 30s instead of failing early on lock contention.
        @event.listens_for(engine, "connect")
        def _enable_sqlite_pragmas(dbapi_conn, _record):  # noqa: ARG001 — SQLAlchemy contract
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.execute("PRAGMA foreign_keys=ON;")
                cursor.execute("PRAGMA busy_timeout=30000;")
            finally:
                cursor.close()

    return engine


def _get_sessionmaker(url: str) -> sessionmaker[Session]:
    engine = _engines.get(url)
    if engine is None:
        with _engines_lock:
            engine = _engines.get(url)
            if engine is None:
                engine = _build_engine(url)
                _engines[url] = engine
    return sessionmaker(engine, expire_on_commit=False)


def _config_document(config: dict) -> dict:
    """Strip the natural key from the stored document (``name`` is its own column)."""
    return {k: v for k, v in config.items() if k != "name"}


class SqlAgentStore(AgentStore):
    def __init__(self, url: str) -> None:
        self._Session = _get_sessionmaker(url)

    def _row(self, session: Session, name: str, user_id: str) -> AgentRow | None:
        stmt = select(AgentRow).where(AgentRow.user_id == user_id, AgentRow.name == name.lower())
        return session.execute(stmt).scalar_one_or_none()

    def get(self, name: str, *, user_id: str | None = None) -> AgentConfig:
        effective_user = user_id or get_effective_user_id()
        with self._Session() as session:
            row = self._row(session, name, effective_user)
        if row is None:
            raise FileNotFoundError(f"Agent config not found: {name} (user {effective_user})")
        return parse_agent_config(row.config or {}, row.name)

    def exists(self, name: str, *, user_id: str | None = None) -> bool:
        effective_user = user_id or get_effective_user_id()
        with self._Session() as session:
            return self._row(session, name, effective_user) is not None

    def get_soul(self, name: str, *, user_id: str | None = None) -> str | None:
        effective_user = user_id or get_effective_user_id()
        with self._Session() as session:
            row = self._row(session, name, effective_user)
        if row is None:
            return None
        return row.soul or None

    def list(self, *, user_id: str | None = None) -> list[AgentConfig]:
        effective_user = user_id or get_effective_user_id()
        stmt = select(AgentRow).where(AgentRow.user_id == effective_user).order_by(AgentRow.name.asc())
        with self._Session() as session:
            rows = list(session.execute(stmt).scalars())
        return [parse_agent_config(r.config or {}, r.name) for r in rows]

    def list_all(self) -> list[tuple[str, AgentConfig]]:
        stmt = select(AgentRow).order_by(AgentRow.user_id.asc(), AgentRow.name.asc())
        with self._Session() as session:
            rows = list(session.execute(stmt).scalars())
        return [(r.user_id, parse_agent_config(r.config or {}, r.name)) for r in rows]

    def create(self, name: str, config: dict, soul: str, *, user_id: str | None = None) -> None:
        effective_user = user_id or get_effective_user_id()
        now = datetime.now(UTC)
        row = AgentRow(
            id=uuid.uuid4().hex,
            user_id=effective_user,
            name=name.lower(),
            config=_config_document(config),
            soul=soul or "",
            created_at=now,
            updated_at=now,
        )
        try:
            with self._Session() as session:
                session.add(row)
                session.commit()
        except IntegrityError as e:
            # UNIQUE(user_id, name) turns the check-then-write race into a clean conflict.
            raise AgentExistsError(f"Agent '{name}' already exists for user '{effective_user}'") from e

    def update(self, name: str, config: dict | None, soul: str | None, *, user_id: str | None = None) -> None:
        effective_user = user_id or get_effective_user_id()
        with self._Session() as session:
            row = self._row(session, name, effective_user)
            if row is None:
                # Upsert: setup_agent and any first-time write land here.
                row = AgentRow(
                    id=uuid.uuid4().hex,
                    user_id=effective_user,
                    name=name.lower(),
                    config=_config_document(config or {}),
                    soul=soul or "",
                )
                session.add(row)
            else:
                if config is not None:
                    row.config = _config_document(config)
                if soul is not None:
                    row.soul = soul
            session.commit()

    def delete(self, name: str, *, user_id: str | None = None) -> AgentDeleteOutcome:
        effective_user = user_id or get_effective_user_id()
        with self._Session() as session:
            result = session.execute(delete(AgentRow).where(AgentRow.user_id == effective_user, AgentRow.name == name.lower()))
            session.commit()
            deleted = result.rowcount > 0
        # Explicit memory cleanup: in db mode the definition lives in the row, but
        # any co-located on-disk memory.json (deermem file backend) must not be
        # orphaned — remove the agent's on-disk directory if it exists. Mirrors
        # the file backend's rmtree, which bundles config + soul + memory.
        agent_dir = get_paths().user_agent_dir(effective_user, name)
        if agent_dir.exists():
            shutil.rmtree(agent_dir)
            deleted = True
        return "deleted" if deleted else "missing"

    def signature(self) -> Hashable:
        # MAX(updated_at) is not covered by an index (only user_id and the
        # (user_id, name) unique constraint are), so this is a small full scan.
        # It runs only on the webhook registry's cache-freshness check against a
        # tiny agents table, so an index is not warranted; revisit if agents ever
        # grow into the thousands with frequent webhook deliveries.
        with self._Session() as session:
            max_updated, count = session.execute(select(func.max(AgentRow.updated_at), func.count(AgentRow.id))).one()
        token = coerce_iso(max_updated) if isinstance(max_updated, datetime) else str(max_updated)
        return (token, int(count))
