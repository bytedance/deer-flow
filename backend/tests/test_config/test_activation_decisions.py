"""ActivationDecisions — the typed async decision carrier (construction hardening).

The carrier's contract (see ``deerflow/authz/activation_decisions.py``):
a covered name returns the batched decision; a MISS resolves per the
provider-error policy with a loud WARNING and never touches a provider —
``None`` remains the sync-chain signal where the synchronous authorize() is
the correct API.
"""

from __future__ import annotations

import logging

from deerflow.authz.activation_decisions import ActivationDecisions


def test_covered_name_returns_batched_decision():
    decisions = ActivationDecisions({"alpha": True, "beta": False}, fail_closed=True)

    assert decisions.decision_for("alpha") is True
    assert decisions.decision_for("beta") is False


def test_miss_fails_closed_with_loud_log(caplog):
    decisions = ActivationDecisions({}, fail_closed=True)

    with caplog.at_level(logging.WARNING, logger="deerflow.authz.activation_decisions"):
        assert decisions.decision_for("uncovered") is False

    assert any("uncovered" in record.message and "denied" in record.message for record in caplog.records)


def test_miss_fails_open_with_loud_log(caplog):
    decisions = ActivationDecisions({}, fail_closed=False)

    with caplog.at_level(logging.WARNING, logger="deerflow.authz.activation_decisions"):
        assert decisions.decision_for("uncovered") is True

    assert any("uncovered" in record.message and "allowed" in record.message for record in caplog.records)


def test_get_or_none_distinguishes_miss_from_false():
    decisions = ActivationDecisions({"alpha": False}, fail_closed=True)

    assert decisions.get_or_none("alpha") is False
    assert decisions.get_or_none("uncovered") is None


def test_container_protocol_and_len():
    decisions = ActivationDecisions({"alpha": True}, fail_closed=True)

    assert "alpha" in decisions
    assert "uncovered" not in decisions
    assert len(decisions) == 1
