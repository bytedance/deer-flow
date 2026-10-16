"""Cleanup-only captured targets; no live execution or result capability."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime

from deerflow.authz.workspace import WorkspaceContext


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def identifier(value, maximum=255):
    if type(value) is not str or not 1 <= len(value) <= maximum or value.strip() != value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("invalid control identifier")


@dataclass(frozen=True, slots=True)
class TaskControlTarget:
    task_id: str
    user_id: str
    workspace_id: str
    thread_id: str
    thread_incarnation: str
    run_id: str
    server_name: str
    remote_task_id: str
    workspace_context: WorkspaceContext

    def __post_init__(self):
        for name in ("task_id", "user_id", "thread_id", "run_id", "server_name", "remote_task_id"):
            identifier(getattr(self, name))
        identifier(self.thread_incarnation, 32)
        if type(self.workspace_context) is not WorkspaceContext or self.workspace_context.workspace_id != self.workspace_id or self.workspace_context.actor_user_id != self.user_id:
            raise ValueError("control target workspace binding differs")

    @classmethod
    def from_payload(cls, payload):
        if type(payload) is not dict or set(payload) != set(cls.__dataclass_fields__):
            raise ValueError("invalid control target shape")
        value = dict(payload)
        try:
            value["workspace_context"] = WorkspaceContext(**value["workspace_context"])
            return cls(**value)
        except (TypeError, ValueError):
            raise ValueError("invalid captured control target") from None

    @classmethod
    def from_row(cls, row):
        return cls.from_payload({name: row.id if name == "task_id" else row.workspace_context_json if name == "workspace_context" else getattr(row, name) for name in cls.__dataclass_fields__})

    def as_payload(self):
        return asdict(self)

    @property
    def digest(self):
        return hashlib.sha256(canonical(self.as_payload())).hexdigest()


@dataclass(frozen=True, slots=True)
class TaskStopReceipt:
    operation_id: str
    target_sha256: str
    remote_task_id: str
    spec_digest: str
    observed_at: datetime
    evidence: str


@dataclass(slots=True)
class TaskControlRuntime:
    ready: bool = False
    servers: frozenset[str] = field(default_factory=frozenset)
    owner_token: str | None = None

    def supports(self, server_name):
        return self.ready and server_name in self.servers


class McpTaskControlUnavailable(RuntimeError):
    """The configured cleanup provider is not available for this server."""
