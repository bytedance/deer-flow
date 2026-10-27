"""Neutral Guardrail->observer authorization outcome contract.

GuardrailMiddleware writes an AuthorizationOutcome into the per-run runtime
context; an observer pops it to record which policy actually decided a given
tool call. Neither side imports the other -- both depend only on this
contract. The context key is ``__``-prefixed so Gateway build_run_config
strips any caller-supplied forgery, matching ``__run_journal`` /
``__active_skill_secrets``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AUTHORIZATION_OUTCOME_CONTEXT_KEY = "__authorization_outcome"

#: A run with no observer never pops entries (``pop_authorization_outcome`` has
#: no production caller yet), so an authorization-enabled deployment would
#: otherwise grow this store for the life of the run, one entry per tool call.
#: Capping it bounds that growth to a fixed footprint; the oldest entries are
#: evicted first since a stale decision is the least likely to still be wanted.
_MAX_TRACKED_OUTCOMES = 500


@dataclass(frozen=True)
class AuthorizationOutcome:
    decision: Literal["allowed", "denied"]
    policy_id: str
    policy_version: str
    reason_codes: tuple[str, ...] = ()


def put_authorization_outcome(context: object, tool_call_id: object, outcome: AuthorizationOutcome) -> None:
    if not isinstance(context, dict) or not tool_call_id:
        return
    store = context.get(AUTHORIZATION_OUTCOME_CONTEXT_KEY)
    if not isinstance(store, dict):
        store = {}
        context[AUTHORIZATION_OUTCOME_CONTEXT_KEY] = store
    store[tool_call_id] = outcome
    while len(store) > _MAX_TRACKED_OUTCOMES:
        store.pop(next(iter(store)))


def pop_authorization_outcome(context: object, tool_call_id: object) -> AuthorizationOutcome | None:
    if not isinstance(context, dict) or not tool_call_id:
        return None
    store = context.get(AUTHORIZATION_OUTCOME_CONTEXT_KEY)
    if not isinstance(store, dict):
        return None
    return store.pop(tool_call_id, None)
