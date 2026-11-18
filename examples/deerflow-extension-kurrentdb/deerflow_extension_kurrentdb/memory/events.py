"""Event types and payloads of a DeerMem memory stream.

One stream per user scope holds summaries and every agent's facts. Every event's
JSON data carries ``id`` (the change set it belongs to, a UUID string) and
``agent`` (the DeerMem bucket name, or ``None`` for the user-global part). A change
set is one append; its events get deterministic ids ``uuid5(change_set_id, index)``,
so a retried or settled append is recognisable by id.

Payloads (besides ``id`` and ``agent``) of the event types written to the stream:

- ``SummariesUpdated`` (agent ``None``): ``user``, ``history`` — the full sections
- ``FactUpserted``: ``fact`` — the normalized fact, carrying its own ``revision``
- ``MemorySnapshot`` (agent ``None``): ``state`` — ``user``, ``history``,
  ``facts`` (agent name -> fact list) and ``lastUpdated``; the fold restarts from it

``FactDeleted`` and ``MemoryCleared`` are fold steps only: a destructive plan folds
them in memory and writes the resulting ``MemorySnapshot`` as its deletion
boundary, so neither type is ever appended.

Fold-only steps:

- ``FactDeleted``: ``factId``, ``revision`` (the revision that was removed)
- ``MemoryCleared``: agent ``None`` clears summaries and every agent; a name clears
  that agent's facts

Each payload also has ``at``, the commit time shown as ``lastUpdated``.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from deerflow.agents.memory.backends.deermem.deermem.core.storage import utc_now_iso_z
from kurrentdbclient import NewEvent

PREFIX = "deerflow.memory."
SUMMARIES_UPDATED = f"{PREFIX}SummariesUpdated"
FACT_UPSERTED = f"{PREFIX}FactUpserted"
FACT_DELETED = f"{PREFIX}FactDeleted"
MEMORY_CLEARED = f"{PREFIX}MemoryCleared"
MEMORY_SNAPSHOT = f"{PREFIX}MemorySnapshot"

EVENT_TYPES = frozenset({SUMMARIES_UPDATED, FACT_UPSERTED, FACT_DELETED, MEMORY_CLEARED, MEMORY_SNAPSHOT})


def event_id(change_set_id: str, index: int) -> uuid.UUID:
    return uuid.uuid5(uuid.UUID(change_set_id), str(index))


def new_event(event_type: str, change_set_id: str, index: int, data: dict[str, Any], *, at: str | None = None) -> NewEvent:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown memory event type {event_type!r}")
    if "agent" not in data:
        raise ValueError("memory event data must name its agent (None for the global part)")
    payload = {**data, "id": change_set_id, "at": at or data.get("at") or utc_now_iso_z()}
    return NewEvent(id=event_id(change_set_id, index), type=event_type, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), content_type="application/json")


def new_change_set(changes: list[tuple[str, dict[str, Any]]]) -> list[NewEvent]:
    """Events of one change set (``[(event_type, data), ...]``), sharing one id and time."""
    change_set_id = str(uuid.uuid4())
    at = utc_now_iso_z()
    return [new_event(event_type, change_set_id, index, data, at=at) for index, (event_type, data) in enumerate(changes)]
