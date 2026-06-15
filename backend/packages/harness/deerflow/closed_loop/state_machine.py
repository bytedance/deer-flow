"""State machine for closure tickets.

The state machine is intentionally linear with a few branches:

    pending -> assigned -> in_progress -> pending_verification -> closed
                  |             |                |
                  v             v                v
              rejected      rejected       in_progress (reject_verification)
              closed        rejected
              (after reopen)

Direct PATCH of the ``status`` column is forbidden -- callers MUST go through
:func:`transition` so:

1. Each transition is validated against an explicit table.
2. ``due_at`` is computed when entering ``assigned``.
3. Lifecycle timestamps (``assigned_at`` / ``started_at`` / ``submitted_at`` /
   ``closed_at``) are stamped consistently.
4. An immutable :class:`ClosureTicketEventRow` audit row is emitted.

The function is pure (no I/O): it returns a :class:`TransitionResult` describing
the field updates and audit payload, and the caller (the service / repository
layer) is responsible for persisting them inside one transaction.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

# Default SLA hours per priority -- mirrors the seeded
# ``closure_sla_configs`` rows in alembic migration 002. Used only when the
# tenant has no override row.
DEFAULT_SLA_HOURS: Mapping[str, int] = {
    "urgent": 4,
    "important": 72,
    "normal": 7 * 24,
    "observe": 30 * 24,
}


class ClosureStatus(enum.StrEnum):
    """All legal lifecycle states of a closure ticket."""

    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    PENDING_VERIFICATION = "pending_verification"
    CLOSED = "closed"
    REJECTED = "rejected"
    REOPENED = "reopened"


class ClosureAction(enum.StrEnum):
    """All legal actions a caller can request through :func:`transition`."""

    CREATE = "create"
    ASSIGN = "assign"
    START = "start"
    SUBMIT_VERIFICATION = "submit_verification"
    VERIFY_CLOSE = "verify_close"
    REJECT_VERIFICATION = "reject_verification"
    REJECT = "reject"
    REOPEN = "reopen"
    MARK_OVERDUE = "mark_overdue"


# (current_status, action) -> next_status
_TRANSITIONS: dict[tuple[ClosureStatus, ClosureAction], ClosureStatus] = {
    (ClosureStatus.PENDING, ClosureAction.ASSIGN): ClosureStatus.ASSIGNED,
    (ClosureStatus.ASSIGNED, ClosureAction.START): ClosureStatus.IN_PROGRESS,
    (ClosureStatus.IN_PROGRESS, ClosureAction.SUBMIT_VERIFICATION): ClosureStatus.PENDING_VERIFICATION,
    (ClosureStatus.PENDING_VERIFICATION, ClosureAction.VERIFY_CLOSE): ClosureStatus.CLOSED,
    (ClosureStatus.PENDING_VERIFICATION, ClosureAction.REJECT_VERIFICATION): ClosureStatus.IN_PROGRESS,
    (ClosureStatus.PENDING, ClosureAction.REJECT): ClosureStatus.REJECTED,
    (ClosureStatus.ASSIGNED, ClosureAction.REJECT): ClosureStatus.REJECTED,
    (ClosureStatus.IN_PROGRESS, ClosureAction.REJECT): ClosureStatus.REJECTED,
    (ClosureStatus.CLOSED, ClosureAction.REOPEN): ClosureStatus.REOPENED,
    (ClosureStatus.REOPENED, ClosureAction.START): ClosureStatus.IN_PROGRESS,
    (ClosureStatus.REOPENED, ClosureAction.ASSIGN): ClosureStatus.ASSIGNED,
}

# Actions that gate-check the verifier role rather than the writer role.
VERIFY_ACTIONS: frozenset[ClosureAction] = frozenset(
    {ClosureAction.VERIFY_CLOSE, ClosureAction.REJECT_VERIFICATION}
)


class TransitionError(Exception):
    """Raised by :func:`transition` when the requested action is invalid.

    The service layer turns this into HTTP 409 / 422 as appropriate.
    """

    def __init__(self, message: str, *, code: str = "transition_invalid") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TicketSnapshot:
    """Read-only view of the ticket fields the state machine inspects.

    The repository converts an ORM row into this snapshot before calling
    :func:`transition`. This keeps the state machine framework-agnostic and
    easy to unit test.
    """

    id: str
    tenant_id: str
    status: ClosureStatus
    priority: str
    assignee_id: str | None = None
    verifier_id: str | None = None


@dataclass
class TransitionResult:
    """Pure description of what the caller must persist.

    ``column_updates`` -> updates to apply on the ticket row.
    ``event_payload`` -> stored in :class:`ClosureTicketEventRow.payload`.
    ``new_status`` -> convenience reference to ``column_updates['status']``.
    """

    new_status: ClosureStatus
    column_updates: dict[str, Any] = field(default_factory=dict)
    event_payload: dict[str, Any] = field(default_factory=dict)


def _compute_due_at(priority: str, assigned_at: datetime, sla_overrides: Mapping[str, int] | None) -> datetime:
    overrides = sla_overrides or {}
    hours = overrides.get(priority, DEFAULT_SLA_HOURS.get(priority, DEFAULT_SLA_HOURS["normal"]))
    return assigned_at + timedelta(hours=hours)


def transition(
    snapshot: TicketSnapshot,
    action: ClosureAction,
    *,
    actor_id: str | None,
    payload: Mapping[str, Any] | None = None,
    sla_overrides: Mapping[str, int] | None = None,
    now: datetime | None = None,
) -> TransitionResult:
    """Validate ``action`` against ``snapshot`` and return the updates to apply.

    Args:
        snapshot: Current ticket fields the machine needs to read.
        action: The requested action.
        actor_id: ID of the caller; copied into the event payload.
        payload: Action-specific arguments. Examples:

            * ``assign`` -- requires ``assignee_id``.
            * ``submit_verification`` / ``verify_close`` -- may carry
              ``verification_summary`` / ``evidence``.
            * ``reject_verification`` -- requires ``rejection_reason``.
        sla_overrides: Tenant-specific ``priority -> hours`` map; falls back
            to :data:`DEFAULT_SLA_HOURS`.
        now: Override for the current time (testing).

    Returns:
        :class:`TransitionResult` describing the column updates and audit
        payload. Persistence is the caller's responsibility.

    Raises:
        TransitionError: The action is not allowed from the current status,
            or required payload fields are missing.
    """
    payload = dict(payload or {})
    now = now or datetime.now(UTC)

    if action is ClosureAction.MARK_OVERDUE:
        # Special-case: overdue marking is a side-band update from the
        # background scanner. It does not move ``status`` -- it only sets
        # ``is_overdue=True`` on a still-open ticket.
        if snapshot.status in {ClosureStatus.CLOSED, ClosureStatus.REJECTED}:
            raise TransitionError(
                f"Cannot mark a {snapshot.status.value} ticket as overdue",
                code="overdue_terminal",
            )
        return TransitionResult(
            new_status=snapshot.status,
            column_updates={"is_overdue": True, "updated_at": now},
            event_payload={"reason": payload.get("reason", "due_at_passed")},
        )

    key = (snapshot.status, action)
    if key not in _TRANSITIONS:
        raise TransitionError(
            f"Cannot {action.value} from {snapshot.status.value}",
            code="transition_invalid",
        )

    new_status = _TRANSITIONS[key]
    column_updates: dict[str, Any] = {"status": new_status.value, "updated_at": now}
    event_payload: dict[str, Any] = dict(payload)

    if action is ClosureAction.ASSIGN:
        assignee = payload.get("assignee_id")
        if not assignee or not isinstance(assignee, str):
            raise TransitionError("assign requires assignee_id (string)", code="missing_assignee")
        column_updates["assignee_id"] = assignee
        column_updates["assigned_at"] = now
        column_updates["due_at"] = _compute_due_at(snapshot.priority, now, sla_overrides)
        # Reset the overdue flag in case this is a re-assign after rejection.
        column_updates["is_overdue"] = False
    elif action is ClosureAction.START:
        column_updates["started_at"] = now
    elif action is ClosureAction.SUBMIT_VERIFICATION:
        column_updates["submitted_at"] = now
    elif action is ClosureAction.VERIFY_CLOSE:
        column_updates["verifier_id"] = actor_id
        column_updates["closed_at"] = now
    elif action is ClosureAction.REJECT_VERIFICATION:
        if not payload.get("rejection_reason"):
            raise TransitionError(
                "reject_verification requires rejection_reason",
                code="missing_rejection_reason",
            )
    elif action is ClosureAction.REJECT:
        column_updates["closed_at"] = now
    elif action is ClosureAction.REOPEN:
        column_updates["closed_at"] = None
        column_updates["is_overdue"] = False

    return TransitionResult(
        new_status=new_status,
        column_updates=column_updates,
        event_payload=event_payload,
    )
