"""Audit event taxonomy and Pydantic model (plan M2-1, RFC §5.1).

Every event written by ``AuditMiddleware`` and by the approval engine
flows through :class:`AuditEvent`. We keep the schema deliberately flat
and JSON-serialisable: storage backends persist ``details`` as a TEXT
JSON blob, and the HMAC signer (see :mod:`signer`) consumes the same
serialisation so signatures are storage-agnostic.

Append-only enum
================

:class:`AuditEventType` is **strictly additive**. Removing or renaming a
value would break ``verify_integrity`` for every historical row that
carries the old label. The plan §4.4 risk register makes this explicit;
new event types in M3+ must be **appended**, never reordered.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class AuditEventType(str, Enum):
    """Canonical audit event labels (RFC §5.1, 22 values).

    Grouped by namespace for readability; the enum is otherwise a flat
    ``str``-valued list so storage backends can index it efficiently.
    """

    # ── Authentication / session ──
    USER_LOGIN = "user.login"
    USER_LOGOUT = "user.logout"
    USER_LOGIN_FAILED = "user.login_failed"
    USER_PASSWORD_CHANGED = "user.password_changed"

    # ── Agent lifecycle ──
    AGENT_TASK_STARTED = "agent.task_started"
    AGENT_TASK_COMPLETED = "agent.task_completed"
    AGENT_TASK_ERROR = "agent.task_error"

    # ── Sandbox / tool execution ──
    SANDBOX_COMMAND_EXECUTED = "sandbox.command_executed"
    SANDBOX_FILE_WRITTEN = "sandbox.file_written"
    TOOL_INVOKED = "tool.invoked"

    # ── Data movement ──
    DATA_EXPORTED = "data.exported"
    DATA_DELETED = "data.deleted"

    # ── Approval workflow (M3 consumes) ──
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_REJECTED = "approval.rejected"
    APPROVAL_EXPIRED = "approval.expired"
    APPROVAL_RESUBMITTED = "approval.resubmitted"

    # ── RBAC mutations ──
    ROLE_PERMISSION_CHANGED = "role.permission_changed"
    USER_ROLE_CHANGED = "user.role_changed"

    # ── System / config ──
    CONFIG_CHANGED = "system.config_changed"
    SYSTEM_STARTED = "system.started"
    SYSTEM_SHUTDOWN = "system.shutdown"


class AuditEvent(BaseModel):
    """A single audit log entry.

    Designed to be cheap to construct on every tool call — no nested
    Pydantic models, no enum coercion beyond ``event_type``, and the
    ``details`` blob is plain ``dict[str, Any]`` so callers don't have
    to invent a new sub-model for each event shape.
    """

    id: str = Field(default_factory=lambda: str(uuid4()), description="Unique event id (UUID4)")
    event_type: AuditEventType = Field(description="One of :class:`AuditEventType`")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp; storage backends index this column",
    )
    user_id: str | None = Field(default=None, description="Subject user id; null for system events")
    resource: str | None = Field(default=None, description='Resource identifier, e.g. "thread:abc-123"')
    action: str | None = Field(default=None, description='Action verb, e.g. "delete"')
    details: dict[str, Any] = Field(default_factory=dict, description="Event-specific payload (JSON-serialisable)")
    signature: str | None = Field(default=None, description="HMAC-SHA256 hex digest, set by :class:`AuditSigner`")

    model_config = ConfigDict(use_enum_values=False)


__all__ = ["AuditEvent", "AuditEventType"]
