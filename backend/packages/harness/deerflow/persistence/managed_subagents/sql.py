"""SQL-backed managed subagent store."""

from __future__ import annotations

import uuid
from collections.abc import Hashable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
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
        with self._Session() as session:
            row = session.execute(select(ManagedSubagentRow).where(ManagedSubagentRow.name == definition.name)).scalar_one_or_none()
            if row is None:
                raise FileNotFoundError(f"Managed subagent not found: {definition.name}")
            row.definition = definition.model_dump(mode="json")
            # ``signature()`` is the tuple of (id, updated_at), so a definition
            # change is only visible to peer processes when this row's stamp
            # moves. The ORM onupdate callback reads the wall clock, whose
            # resolution is coarse (about 15.6 ms on Windows) and which can
            # also sit behind a stamp written by a node with a skewed clock.
            # Either case leaves updated_at at or below the stored value, so
            # signature() reports "unchanged" and other processes keep serving
            # the stale definition. Force the stamp strictly forward instead
            # of relying on the clock alone.
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
