"""Synchronous SQL repository for ``channel_runtime_configs`` (SQLite or PostgreSQL).

The callers of the runtime config store are synchronous and already run off the
event loop (``ChannelService.from_app_config`` and its config reloads run in
worker threads, the Gateway router offloads every store call), so this
repository uses a synchronous session factory over the application database,
the same split as the ``agent_storage.backend: db`` store
(``deerflow.persistence.agents.sql.get_sync_sessionmaker``).

- ``save`` is one dialect-native upsert that bumps ``version``: ``INSERT ...
  ON CONFLICT (provider) DO UPDATE SET ..., version = version + 1``. Two
  instances saving the same provider serialize on the row, so each save gets
  its own version. The new version is read back inside the same transaction.
- ``insert_missing`` imports rows with ``ON CONFLICT DO NOTHING``: a provider
  already in the table is never overwritten, so two instances importing the
  same legacy file at once neither duplicate nor clobber a row.

Ciphertext is opaque here; encryption lives in the application store
(``app.channels.runtime_config_store``). Database errors propagate.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from deerflow.persistence.channel_runtime_configs.model import ChannelRuntimeConfigRow, StoredChannelRuntimeConfig


def _insert(session: Session):
    name = session.get_bind().dialect.name
    if name == "postgresql":
        return pg_insert
    if name == "sqlite":
        return sqlite_insert
    raise ValueError(f"Unsupported channel runtime config database dialect: {name}")


def _stored(row: ChannelRuntimeConfigRow) -> StoredChannelRuntimeConfig:
    return StoredChannelRuntimeConfig(provider=row.provider, config_ciphertext=row.config_ciphertext, disconnected=bool(row.disconnected), version=int(row.version))


class SqlChannelRuntimeConfigRepository:
    """Persistence facade for ``channel_runtime_configs``; every call blocks, so run it off the event loop."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def list_all(self) -> list[StoredChannelRuntimeConfig]:
        with self._sf() as session:
            rows = session.scalars(select(ChannelRuntimeConfigRow).order_by(ChannelRuntimeConfigRow.provider)).all()
            return [_stored(row) for row in rows]

    def get(self, provider: str) -> StoredChannelRuntimeConfig | None:
        with self._sf() as session:
            row = session.get(ChannelRuntimeConfigRow, provider)
            return _stored(row) if row is not None else None

    def versions(self) -> dict[str, int]:
        """``provider -> version`` for every row, without reading the ciphertext."""
        with self._sf() as session:
            rows = session.execute(select(ChannelRuntimeConfigRow.provider, ChannelRuntimeConfigRow.version)).all()
        return {row.provider: int(row.version) for row in rows}

    def count(self) -> int:
        with self._sf() as session:
            return int(session.scalar(select(func.count()).select_from(ChannelRuntimeConfigRow)) or 0)

    def save(self, provider: str, *, config_ciphertext: str | None, disconnected: bool, now: float) -> int:
        """Create or replace ``provider``'s row and return its new version (1 for a new row)."""
        with self._sf() as session:
            insert = _insert(session)
            stmt = insert(ChannelRuntimeConfigRow).values(provider=provider, config_ciphertext=config_ciphertext, disconnected=disconnected, version=1, updated_at=now)
            stmt = stmt.on_conflict_do_update(
                index_elements=[ChannelRuntimeConfigRow.provider],
                set_={
                    "config_ciphertext": config_ciphertext,
                    "disconnected": disconnected,
                    "version": ChannelRuntimeConfigRow.version + 1,
                    "updated_at": now,
                },
            )
            session.execute(stmt)
            # Our own write, read inside the transaction that still holds it.
            version = session.scalar(select(ChannelRuntimeConfigRow.version).where(ChannelRuntimeConfigRow.provider == provider))
            session.commit()
        return int(version)

    def insert_missing(self, rows: Sequence[StoredChannelRuntimeConfig], *, now: float) -> int:
        """Insert the rows whose provider has none yet (at version 1); returns how many were inserted."""
        if not rows:
            return 0
        inserted = 0
        with self._sf() as session:
            insert = _insert(session)
            for row in rows:
                stmt = (
                    insert(ChannelRuntimeConfigRow)
                    .values(provider=row.provider, config_ciphertext=row.config_ciphertext, disconnected=row.disconnected, version=1, updated_at=now)
                    .on_conflict_do_nothing(index_elements=[ChannelRuntimeConfigRow.provider])
                    .returning(ChannelRuntimeConfigRow.provider)
                )
                # Counted from RETURNING (a row only when inserted): psycopg
                # reports rowcount -1 for ON CONFLICT DO NOTHING.
                inserted += len(session.execute(stmt).all())
            session.commit()
        return inserted
