"""Tests for :class:`AuditSigner` (plan M2-4)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from deerflow.enterprise.audit.events import AuditEvent, AuditEventType
from deerflow.enterprise.audit.signer import AuditSigner


def _make_event(**overrides) -> AuditEvent:
    base = {
        "event_type": AuditEventType.AGENT_TASK_STARTED,
        "user_id": "alice",
        "resource": "thread:abc",
        "action": "agent.start",
        "details": {"foo": "bar", "n": 42},
    }
    base.update(overrides)
    return AuditEvent(**base)


def test_sign_returns_stable_hex_digest():
    """Signing the same event twice yields the same hex digest."""
    signer = AuditSigner("test-key")
    event = _make_event()
    first = signer.sign(event)
    second = signer.sign(event)
    assert first == second
    assert len(first) == 64  # sha256 hex


def test_sign_is_deterministic_across_dict_ordering():
    """``details`` dicts in different insertion order produce identical signatures."""
    signer = AuditSigner("k")
    a = _make_event(details={"a": 1, "b": 2})
    b = _make_event(id=a.id, timestamp=a.timestamp, details={"b": 2, "a": 1})
    assert signer.sign(a) == signer.sign(b)


def test_verify_detects_tamper_in_details():
    """Mutating ``details`` after signing flips ``verify`` to False."""
    signer = AuditSigner("k")
    event = _make_event()
    event.signature = signer.sign(event)
    event.details["foo"] = "tampered"
    assert signer.verify(event) is False


def test_verify_unsigned_event_returns_false():
    """An event without a signature is treated identically to a tampered one."""
    signer = AuditSigner("k")
    event = _make_event()
    assert signer.verify(event) is False


def test_different_keys_produce_different_signatures():
    """The signer never collides across distinct keys."""
    e = _make_event()
    assert AuditSigner("k1").sign(e) != AuditSigner("k2").sign(e)


def test_empty_key_rejected_at_construction():
    """An empty key raises immediately — no silent unsigned events."""
    with pytest.raises(ValueError):
        AuditSigner("")


def test_datetime_normalisation_round_trips():
    """``datetime`` values inside ``details`` are normalised to ISO strings."""
    signer = AuditSigner("k")
    ts = datetime(2026, 5, 18, 12, 0, 0, tzinfo=timezone.utc)
    e1 = _make_event(details={"when": ts})
    e2 = _make_event(id=e1.id, timestamp=e1.timestamp, details={"when": ts})
    assert signer.sign(e1) == signer.sign(e2)
