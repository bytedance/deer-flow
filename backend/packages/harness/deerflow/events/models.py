"""Event type definitions and Event dataclass for the event system."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class EventType(str, Enum):
    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    TOKEN_THRESHOLD_EXCEEDED = "token_threshold_exceeded"
    BUDGET_EXCEEDED = "budget_exceeded"
    CONTENT_SAFETY_FLAGGED = "content_safety_flagged"


@dataclass
class Event:
    """An event emitted by the DeerFlow system."""

    type: EventType
    tenant_id: str
    thread_id: str | None = None
    data: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "tenant_id": self.tenant_id,
            "thread_id": self.thread_id,
            "timestamp": self.timestamp,
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Event:
        return cls(
            id=d["id"],
            type=EventType(d["type"]),
            tenant_id=d["tenant_id"],
            thread_id=d.get("thread_id"),
            timestamp=d.get("timestamp", ""),
            data=d.get("data", {}),
        )
