"""Workflow frontdoor schema enums."""

from enum import StrEnum


class WorkflowKind(StrEnum):
    """Generic workflow kinds accepted by the frontdoor."""

    message = "message"
    command = "command"
    resume = "resume"
    handoff = "handoff"
    other = "other"


class WorkflowSourceType(StrEnum):
    """Source category for a workflow intake envelope."""

    api = "api"
    dashboard = "dashboard"
    channel = "channel"
    agent_session = "agent_session"
    other = "other"


class WorkflowStatus(StrEnum):
    """Lifecycle status for a workflow envelope."""

    received = "received"
    bound = "bound"
    claimed = "claimed"
    run_created = "run_created"
    running = "running"
    waiting = "waiting"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    orphaned = "orphaned"
    ignored = "ignored"
