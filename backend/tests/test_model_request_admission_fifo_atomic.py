"""Regression coverage for atomic request-admission FIFO entry."""

import pytest

from deerflow.config.model_config import RequestAdmissionConfig
from deerflow.models import request_admission as admission


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(admission, "monotonic", lambda: now[0])
    return now


def test_blocking_waiter_reserves_fifo_position_before_newcomer_can_take_due_slot(clock):
    limiter = admission.RequestAdmission(RequestAdmissionConfig(requests_per_minute=60))
    assert limiter.acquire(blocking=False)

    acquired, ticket = limiter._try_or_enqueue(blocking=True)
    assert acquired is False
    assert ticket is limiter._waiters[0]

    clock[0] = 1
    assert limiter.acquire(blocking=False) is False

    limiter._remove(ticket)
    assert limiter.acquire(blocking=False) is True


def test_nonblocking_probe_never_joins_the_fifo(clock):
    limiter = admission.RequestAdmission(RequestAdmissionConfig(requests_per_minute=60))
    assert limiter.acquire(blocking=False)

    acquired, ticket = limiter._try_or_enqueue(blocking=False)

    assert acquired is False
    assert ticket is None
    assert not limiter._waiters
