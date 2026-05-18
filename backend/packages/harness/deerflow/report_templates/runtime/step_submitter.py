"""Form submission handler — accept user-submitted form payload, advance state.

For each ``submit_step`` tool call:

  1. Locate the current ``form_step`` from the DSL by ``state.expected_step``.
  2. Lightly validate that all required fields are present in the payload.
  3. Merge the payload into ``state.form_state[step_id]``.
  4. Decide the next state:
       - ``next`` references another form_step → state stays in ``awaiting_step``
         with ``expected_step`` updated.
       - ``next == "generate"`` → transition to ``ready_for_data``.
"""

from __future__ import annotations

from typing import Any

from deerflow.report_templates.runtime.state import (
    RuntimeState,
    expect_status,
    transition,
)


class SubmitStepError(Exception):
    """Raised when the submitted payload is malformed for the expected step."""


def submit_step(
    *,
    dsl: dict[str, Any],
    state: RuntimeState,
    submitted_step_id: str,
    payload: dict[str, Any],
) -> str:
    """Apply ``payload`` to ``state`` and decide the next status.

    Args:
        dsl: The validated DSL document.
        state: Current ``RuntimeState`` (will be mutated in place).
        submitted_step_id: Step id the caller claims to have submitted.
        payload: Raw form-submission dict mapping field name → value.

    Returns:
        The next state's expected step id (or ``"__generate__"`` when the
        pipeline is moving into the data phase).

    Raises:
        SubmitStepError: payload does not match ``expected_step`` / missing
            required fields / unknown step.
    """
    expect_status(state, "pending", "awaiting_step")

    if state.expected_step and submitted_step_id != state.expected_step:
        raise SubmitStepError(
            f"step mismatch: expected {state.expected_step!r}, got {submitted_step_id!r}"
        )

    step = _find_step(dsl, submitted_step_id)

    # Validate required fields.
    missing: list[str] = []
    for f in step.get("fields", []) or []:
        if f.get("required") and not _has_value(payload.get(f["name"])):
            missing.append(f["name"])
    if missing:
        raise SubmitStepError(
            f"missing required fields in step {submitted_step_id!r}: {missing}"
        )

    # Merge submission into form_state and mark completed.
    state.form_state[submitted_step_id] = dict(payload)
    if submitted_step_id not in state.completed_steps:
        state.completed_steps.append(submitted_step_id)

    next_id = step.get("next", "generate")
    if next_id == "generate":
        state.expected_step = None
        transition(state, "ready_for_data")
        return "__generate__"

    state.expected_step = next_id
    # Stay in awaiting_step (transition allowed even when same status).
    if state.status == "pending":
        transition(state, "awaiting_step")
    else:
        transition(state, "awaiting_step")  # idempotent re-arm
    return next_id


def _find_step(dsl: dict[str, Any], step_id: str) -> dict[str, Any]:
    for step in dsl.get("form_steps", []) or []:
        if step["id"] == step_id:
            return step
    raise SubmitStepError(f"unknown form_step {step_id!r}")


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True
