"""Cron job type definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import uuid4


def _now_ms() -> int:
    """Get current time in milliseconds."""
    return int(datetime.now().timestamp() * 1000)


def _generate_id() -> str:
    """Generate a short unique ID."""
    return uuid4().hex[:8]


@dataclass
class CronSchedule:
    """Schedule configuration for a cron job.

    Supports three types:
    - "at": One-time execution at a specific timestamp
    - "every": Recurring execution with fixed interval
    - "cron": Cron expression (e.g., "0 9 * * *" for daily at 9am)
    """

    kind: Literal["at", "every", "cron"]
    at_ms: int | None = None  # For "at" type: timestamp in milliseconds
    every_ms: int | None = None  # For "every" type: interval in milliseconds
    expr: str | None = None  # For "cron" type: cron expression
    tz: str | None = None  # Timezone for cron expression (e.g., "Asia/Shanghai")


@dataclass
class CronPayload:
    """Payload for cron job execution."""

    kind: Literal["agent_turn", "system_event"] = "agent_turn"
    message: str = ""  # The task/prompt to execute
    deliver: bool = False  # Whether to deliver result to a channel
    channel: str | None = None  # Target channel (e.g., "telegram", "slack")
    to: str | None = None  # Target chat/user ID
    thread_ts: str | None = None  # Optional thread identifier for threaded replies
    thread_id: str | None = None  # Optional thread ID for context
    assistant_id: str | None = None  # Optional LangGraph assistant ID to execute
    agent_name: str | None = None  # Optional DeerFlow custom agent name
    thinking_enabled: bool | None = None  # Optional thinking override
    subagent_enabled: bool | None = None  # Optional subagent override


@dataclass
class CronJobState:
    """Runtime state for a cron job."""

    next_run_at_ms: int | None = None  # Next execution timestamp
    last_run_at_ms: int | None = None  # Last execution timestamp
    last_status: Literal["pending", "ok", "error"] = "pending"
    last_error: str | None = None


@dataclass
class CronJob:
    """A complete cron job definition."""

    id: str
    name: str
    enabled: bool = True
    schedule: CronSchedule = field(default_factory=lambda: CronSchedule(kind="at"))
    payload: CronPayload = field(default_factory=CronPayload)
    state: CronJobState = field(default_factory=CronJobState)
    delete_after_run: bool = False  # Auto-delete after one-time execution
    created_at_ms: int = field(default_factory=_now_ms)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "schedule": {
                "kind": self.schedule.kind,
                "at_ms": self.schedule.at_ms,
                "every_ms": self.schedule.every_ms,
                "expr": self.schedule.expr,
                "tz": self.schedule.tz,
            },
            "payload": {
                "kind": self.payload.kind,
                "message": self.payload.message,
                "deliver": self.payload.deliver,
                "channel": self.payload.channel,
                "to": self.payload.to,
                "thread_ts": self.payload.thread_ts,
                "thread_id": self.payload.thread_id,
                "assistant_id": self.payload.assistant_id,
                "agent_name": self.payload.agent_name,
                "thinking_enabled": self.payload.thinking_enabled,
                "subagent_enabled": self.payload.subagent_enabled,
            },
            "state": {
                "next_run_at_ms": self.state.next_run_at_ms,
                "last_run_at_ms": self.state.last_run_at_ms,
                "last_status": self.state.last_status,
                "last_error": self.state.last_error,
            },
            "delete_after_run": self.delete_after_run,
            "created_at_ms": self.created_at_ms,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CronJob:
        """Create from dictionary."""
        schedule_data = data.get("schedule", {})
        payload_data = data.get("payload", {})
        state_data = data.get("state", {})

        return cls(
            id=data["id"],
            name=data["name"],
            enabled=data.get("enabled", True),
            schedule=CronSchedule(
                kind=schedule_data.get("kind", "at"),
                at_ms=schedule_data.get("at_ms"),
                every_ms=schedule_data.get("every_ms"),
                expr=schedule_data.get("expr"),
                tz=schedule_data.get("tz"),
            ),
            payload=CronPayload(
                kind=payload_data.get("kind", "agent_turn"),
                message=payload_data.get("message", ""),
                deliver=payload_data.get("deliver", False),
                channel=payload_data.get("channel"),
                to=payload_data.get("to"),
                thread_ts=payload_data.get("thread_ts"),
                thread_id=payload_data.get("thread_id"),
                assistant_id=payload_data.get("assistant_id"),
                agent_name=payload_data.get("agent_name"),
                thinking_enabled=payload_data.get("thinking_enabled"),
                subagent_enabled=payload_data.get("subagent_enabled"),
            ),
            state=CronJobState(
                next_run_at_ms=state_data.get("next_run_at_ms"),
                last_run_at_ms=state_data.get("last_run_at_ms"),
                last_status=state_data.get("last_status", "pending"),
                last_error=state_data.get("last_error"),
            ),
            delete_after_run=data.get("delete_after_run", False),
            created_at_ms=data.get("created_at_ms", _now_ms()),
        )
