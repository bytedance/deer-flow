"""SQL-backed managed subagent store."""

from __future__ import annotations

import uuid
from collections.abc import Hashable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from deerflow.persistence.agents.sql import get_sync_sessionmaker
from deerflow.persistence.managed_subagents.base import (
    ManagedSubagentDefinition,
    ManagedSubagentExistsError,
    ManagedSubagentStore,
    normalize_managed_subagent_name,
)
from deerflow.persistence.managed_subagents.model import ManagedSubagentRow


def _normalized_name(name: str) -> str:
    return normalize_managed_subagent_name(name)


class SqlManagedSubagentStore(ManagedSubagentStore):
    def __init__(self, url: str) -> None:
        self._url = url
        self._Session = get_sync_sessionmaker(url)

    def cache_identity(self) -> Hashable:
        return ("db", self._url)

    def get(self, name: str) -> ManagedSubagentDefinition:
        normalized = _normalized_name(name)
        with self._Session() as session:
            row = session.execute(select(ManagedSubagentRow).where(ManagedSubagentRow.name == normalized)).scalar_one_or_none()
        if row is None:
            raise FileNotFoundError(f"Managed subagent not found: {name}")
        return ManagedSubagentDefinition.model_validate(row.definition)

    def list(self) -> list[ManagedSubagentDefinition]:
        with self._Session() as session:
            rows = list(session.execute(select(ManagedSubagentRow).order_by(ManagedSubagentRow.name.asc())).scalars())
        return [ManagedSubagentDefinition.model_validate(row.definition) for row in rows]

    def create(self, definition: ManagedSubagentDefinition) -> None:
        normalize_managed_subagent_name(definition.name, for_creation=True)
        row = ManagedSubagentRow(
            id=uuid.uuid4().hex,
            name=definition.name,
            definition=definition.model_dump(mode="json"),
        )
        try:
            with self._Session() as session:
                session.add(row)
                session.commit()
        except IntegrityError as exc:
            raise ManagedSubagentExistsError(f"Managed subagent '{definition.name}' already exists") from exc

    def update(self, definition: ManagedSubagentDefinition) -> None:
        document = definition.model_dump(mode="json")
        stmt = select(ManagedSubagentRow).where(ManagedSubagentRow.name == definition.name)
        with self._Session() as session:
            # Serialize writers before reading updated_at, so each sees the
            # preceding commit's stamp even when both clocks return the same time.
            if session.get_bind().dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            else:
                stmt = stmt.with_for_update()
            row = session.execute(stmt).scalar_one_or_none()
            if row is None:
                raise FileNotFoundError(f"Managed subagent not found: {definition.name}")
            row.definition = document
            # Peer registries key their snapshots by (id, updated_at), so
            # advance the stamp even when the wall clock stalls or moves back.
            now = datetime.now(UTC)
            current = row.updated_at
            if current is not None:
                if current.tzinfo is None:  # SQLite returns naive datetimes
                    current = current.replace(tzinfo=UTC)
                if now <= current:
                    now = current + timedelta(microseconds=1)
            row.updated_at = now
            session.commit()

    def delete(self, name: str) -> bool:
        normalized = _normalized_name(name)
        with self._Session() as session:
            result = session.execute(delete(ManagedSubagentRow).where(ManagedSubagentRow.name == normalized))
            session.commit()
        return result.rowcount > 0

    def signature(self) -> Hashable:
        with self._Session() as session:
            # COUNT + MAX(updated_at) misses an update from a node whose clock
            # trails the current maximum. Preserve each row's timestamp so any
            # definition change invalidates peer-process registry snapshots.
            rows = session.execute(select(ManagedSubagentRow.id, ManagedSubagentRow.updated_at).order_by(ManagedSubagentRow.id.asc())).all()
        return tuple((row_id, updated_at) for row_id, updated_at in rows)
