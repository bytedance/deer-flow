"""Pure unit tests for the closure state machine.

The :func:`transition` function has no I/O, so we test it directly without a
database. Coverage:

1. Every legal ``(status, action)`` pair returns the expected new status.
2. Every illegal pair raises :class:`TransitionError` with code
   ``transition_invalid``.
3. ``ASSIGN`` requires ``assignee_id`` (missing -> ``missing_assignee``).
4. ``REJECT_VERIFICATION`` requires ``rejection_reason`` (missing ->
   ``missing_rejection_reason``).
5. ``due_at`` is computed from default SLA hours when no override is given.
6. Tenant SLA overrides take precedence over the defaults.
7. ``MARK_OVERDUE`` is a side-band action that does not change ``status``
   and is rejected on terminal tickets.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from deerflow.closed_loop.state_machine import (
    DEFAULT_SLA_HOURS,
    ClosureAction,
    ClosureStatus,
    TicketSnapshot,
    TransitionError,
    transition,
)


def _snap(status: ClosureStatus, *, priority: str = "normal") -> TicketSnapshot:
    return TicketSnapshot(id="t-1", tenant_id="tenant-a", status=status, priority=priority)


_LEGAL = [
    (ClosureStatus.PENDING, ClosureAction.ASSIGN, ClosureStatus.ASSIGNED),
    (ClosureStatus.ASSIGNED, ClosureAction.START, ClosureStatus.IN_PROGRESS),
    (ClosureStatus.IN_PROGRESS, ClosureAction.SUBMIT_VERIFICATION, ClosureStatus.PENDING_VERIFICATION),
    (ClosureStatus.PENDING_VERIFICATION, ClosureAction.VERIFY_CLOSE, ClosureStatus.CLOSED),
    (ClosureStatus.PENDING_VERIFICATION, ClosureAction.REJECT_VERIFICATION, ClosureStatus.IN_PROGRESS),
    (ClosureStatus.PENDING, ClosureAction.REJECT, ClosureStatus.REJECTED),
    (ClosureStatus.ASSIGNED, ClosureAction.REJECT, ClosureStatus.REJECTED),
    (ClosureStatus.IN_PROGRESS, ClosureAction.REJECT, ClosureStatus.REJECTED),
    (ClosureStatus.CLOSED, ClosureAction.REOPEN, ClosureStatus.REOPENED),
    (ClosureStatus.REOPENED, ClosureAction.START, ClosureStatus.IN_PROGRESS),
    (ClosureStatus.REOPENED, ClosureAction.ASSIGN, ClosureStatus.ASSIGNED),
]


@pytest.mark.parametrize("from_status,action,to_status", _LEGAL)
def test_legal_transitions(from_status: ClosureStatus, action: ClosureAction, to_status: ClosureStatus) -> None:
    payload: dict = {}
    if action is ClosureAction.ASSIGN:
        payload["assignee_id"] = "u-2"
    elif action is ClosureAction.REJECT_VERIFICATION:
        payload["rejection_reason"] = "needs more evidence"

    result = transition(_snap(from_status), action, actor_id="actor", payload=payload)
    assert result.new_status is to_status
    assert result.column_updates["status"] == to_status.value


_ILLEGAL = [
    (ClosureStatus.PENDING, ClosureAction.START),
    (ClosureStatus.PENDING, ClosureAction.SUBMIT_VERIFICATION),
    (ClosureStatus.PENDING, ClosureAction.VERIFY_CLOSE),
    (ClosureStatus.PENDING, ClosureAction.REJECT_VERIFICATION),
    (ClosureStatus.PENDING, ClosureAction.REOPEN),
    (ClosureStatus.ASSIGNED, ClosureAction.SUBMIT_VERIFICATION),
    (ClosureStatus.ASSIGNED, ClosureAction.VERIFY_CLOSE),
    (ClosureStatus.IN_PROGRESS, ClosureAction.ASSIGN),
    (ClosureStatus.IN_PROGRESS, ClosureAction.VERIFY_CLOSE),
    (ClosureStatus.PENDING_VERIFICATION, ClosureAction.START),
    (ClosureStatus.PENDING_VERIFICATION, ClosureAction.REJECT),
    (ClosureStatus.CLOSED, ClosureAction.START),
    (ClosureStatus.CLOSED, ClosureAction.ASSIGN),
    (ClosureStatus.CLOSED, ClosureAction.REJECT),
    (ClosureStatus.REJECTED, ClosureAction.REOPEN),
    (ClosureStatus.REJECTED, ClosureAction.START),
]


@pytest.mark.parametrize("from_status,action", _ILLEGAL)
def test_illegal_transitions_raise(from_status: ClosureStatus, action: ClosureAction) -> None:
    with pytest.raises(TransitionError) as excinfo:
        transition(_snap(from_status), action, actor_id="actor", payload={})
    assert excinfo.value.code == "transition_invalid"


def test_assign_requires_assignee_id() -> None:
    with pytest.raises(TransitionError) as excinfo:
        transition(_snap(ClosureStatus.PENDING), ClosureAction.ASSIGN, actor_id="a", payload={})
    assert excinfo.value.code == "missing_assignee"


def test_assign_rejects_non_string_assignee_id() -> None:
    with pytest.raises(TransitionError) as excinfo:
        transition(
            _snap(ClosureStatus.PENDING),
            ClosureAction.ASSIGN,
            actor_id="a",
            payload={"assignee_id": 123},
        )
    assert excinfo.value.code == "missing_assignee"


def test_reject_verification_requires_reason() -> None:
    with pytest.raises(TransitionError) as excinfo:
        transition(
            _snap(ClosureStatus.PENDING_VERIFICATION),
            ClosureAction.REJECT_VERIFICATION,
            actor_id="a",
            payload={},
        )
    assert excinfo.value.code == "missing_rejection_reason"


@pytest.mark.parametrize(
    "priority,expected_hours",
    [
        ("urgent", 4),
        ("important", 72),
        ("normal", 7 * 24),
        ("observe", 30 * 24),
    ],
)
def test_assign_computes_due_at_from_default_sla(priority: str, expected_hours: int) -> None:
    now = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)
    result = transition(
        _snap(ClosureStatus.PENDING, priority=priority),
        ClosureAction.ASSIGN,
        actor_id="actor",
        payload={"assignee_id": "u-1"},
        now=now,
    )
    assert result.column_updates["due_at"] == now + timedelta(hours=expected_hours)
    assert result.column_updates["assignee_id"] == "u-1"
    assert result.column_updates["assigned_at"] == now
    assert result.column_updates["is_overdue"] is False
    assert DEFAULT_SLA_HOURS[priority] == expected_hours


def test_assign_uses_tenant_sla_override() -> None:
    now = datetime(2026, 5, 19, tzinfo=UTC)
    result = transition(
        _snap(ClosureStatus.PENDING, priority="urgent"),
        ClosureAction.ASSIGN,
        actor_id="actor",
        payload={"assignee_id": "u-1"},
        sla_overrides={"urgent": 1},
        now=now,
    )
    assert result.column_updates["due_at"] == now + timedelta(hours=1)


def test_assign_after_reject_resets_overdue_flag() -> None:
    """Re-assigning after a rejection clears any stale ``is_overdue`` flag."""
    result = transition(
        _snap(ClosureStatus.REOPENED),
        ClosureAction.ASSIGN,
        actor_id="actor",
        payload={"assignee_id": "u-1"},
    )
    assert result.column_updates["is_overdue"] is False


def test_start_stamps_started_at() -> None:
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    result = transition(
        _snap(ClosureStatus.ASSIGNED),
        ClosureAction.START,
        actor_id="actor",
        now=now,
    )
    assert result.column_updates["started_at"] == now


def test_submit_verification_stamps_submitted_at() -> None:
    now = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
    result = transition(
        _snap(ClosureStatus.IN_PROGRESS),
        ClosureAction.SUBMIT_VERIFICATION,
        actor_id="actor",
        now=now,
    )
    assert result.column_updates["submitted_at"] == now


def test_verify_close_stamps_verifier_and_closed_at() -> None:
    now = datetime(2026, 5, 19, 10, 0, tzinfo=UTC)
    result = transition(
        _snap(ClosureStatus.PENDING_VERIFICATION),
        ClosureAction.VERIFY_CLOSE,
        actor_id="verifier-1",
        now=now,
    )
    assert result.column_updates["verifier_id"] == "verifier-1"
    assert result.column_updates["closed_at"] == now


def test_reopen_clears_closed_at_and_overdue() -> None:
    result = transition(
        _snap(ClosureStatus.CLOSED),
        ClosureAction.REOPEN,
        actor_id="actor",
    )
    assert result.column_updates["closed_at"] is None
    assert result.column_updates["is_overdue"] is False


def test_mark_overdue_does_not_change_status() -> None:
    result = transition(
        _snap(ClosureStatus.IN_PROGRESS),
        ClosureAction.MARK_OVERDUE,
        actor_id=None,
    )
    assert result.new_status is ClosureStatus.IN_PROGRESS
    assert result.column_updates["is_overdue"] is True
    assert "status" not in result.column_updates


def test_mark_overdue_rejected_for_closed_ticket() -> None:
    with pytest.raises(TransitionError) as excinfo:
        transition(
            _snap(ClosureStatus.CLOSED),
            ClosureAction.MARK_OVERDUE,
            actor_id=None,
        )
    assert excinfo.value.code == "overdue_terminal"


def test_mark_overdue_rejected_for_rejected_ticket() -> None:
    with pytest.raises(TransitionError) as excinfo:
        transition(
            _snap(ClosureStatus.REJECTED),
            ClosureAction.MARK_OVERDUE,
            actor_id=None,
        )
    assert excinfo.value.code == "overdue_terminal"
