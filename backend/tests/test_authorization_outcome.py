"""The neutral Guardrail -> observer authorization handoff."""

from deerflow.authz.outcome import (
    _MAX_TRACKED_OUTCOMES,
    AUTHORIZATION_OUTCOME_CONTEXT_KEY,
    AuthorizationOutcome,
    pop_authorization_outcome,
    put_authorization_outcome,
)

OUTCOME = AuthorizationOutcome(decision="denied", policy_id="p", policy_version="1.0.0", reason_codes=("x",))


def test_round_trip_is_keyed_by_tool_call_id():
    context: dict = {}
    put_authorization_outcome(context, "call-1", OUTCOME)
    assert pop_authorization_outcome(context, "call-1") == OUTCOME


def test_pop_consumes_so_a_later_call_cannot_inherit_a_stale_decision():
    context: dict = {}
    put_authorization_outcome(context, "call-1", OUTCOME)
    pop_authorization_outcome(context, "call-1")
    assert pop_authorization_outcome(context, "call-1") is None


def test_context_key_is_double_underscore_prefixed_so_gateway_strips_forgeries():
    assert AUTHORIZATION_OUTCOME_CONTEXT_KEY.startswith("__")


def test_missing_context_or_tool_call_id_is_a_no_op_rather_than_an_error():
    put_authorization_outcome(None, "call-1", OUTCOME)
    put_authorization_outcome({}, None, OUTCOME)
    assert pop_authorization_outcome(None, "call-1") is None
    assert pop_authorization_outcome({}, None) is None


def test_the_store_evicts_the_oldest_entry_once_it_is_full():
    """No production caller pops entries yet, so an unbounded store would grow
    for the life of a run. Capping it keeps that growth to a fixed footprint."""
    context: dict = {}
    for i in range(_MAX_TRACKED_OUTCOMES + 1):
        put_authorization_outcome(context, f"call-{i}", OUTCOME)

    store = context[AUTHORIZATION_OUTCOME_CONTEXT_KEY]
    assert len(store) == _MAX_TRACKED_OUTCOMES
    assert "call-0" not in store
    assert f"call-{_MAX_TRACKED_OUTCOMES}" in store
