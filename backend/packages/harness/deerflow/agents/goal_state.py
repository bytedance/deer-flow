from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

GoalBlocker = Literal[
    "none",
    "missing_evidence",
    "needs_user_input",
    "run_failed",
    "external_wait",
    "goal_not_met_yet",
]


class GoalEvaluation(TypedDict):
    satisfied: bool
    blocker: GoalBlocker
    reason: str
    evidence_summary: NotRequired[str]
    relied_on_assumption: NotRequired[bool]


class GoalState(TypedDict):
    objective: str
    status: Literal["active"]
    created_at: str
    updated_at: str
    continuation_count: int
    max_continuations: int
    no_progress_count: int
    max_no_progress_continuations: int
    last_evaluation: NotRequired[dict[str, Any]]


class GoalOutcomeState(TypedDict):
    """The latest met goal, written only by the checkpoint write that clears it."""

    status: Literal["achieved"]
    objective: str
    goal_created_at: str
    achieved_at: str
    continuation_count: int
    max_continuations: int
    reason: str
    relied_on_assumption: bool
    reply_message_id: str | None
