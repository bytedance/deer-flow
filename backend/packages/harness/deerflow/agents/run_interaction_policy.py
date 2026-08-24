"""Run interaction policy shared by lead-agent tools and prompt guidance."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

INTERACTIVE_MODE = "interactive"
WEBHOOK_MODE = "webhook"
SCHEDULED_MODE = "scheduled"
AUTONOMOUS_MODE = "autonomous"
_VALID_MODES = frozenset({INTERACTIVE_MODE, WEBHOOK_MODE, SCHEDULED_MODE, AUTONOMOUS_MODE})
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RunInteractionPolicy:
    """Describe whether a run can ask a human and how ambiguity is handled."""

    mode: str = INTERACTIVE_MODE
    allows_clarification: bool = True

    def __post_init__(self) -> None:
        if self.mode not in _VALID_MODES:
            raise ValueError(f"Unknown run interaction mode: {self.mode!r}")

    @classmethod
    def resolve(cls, config: Mapping[str, Any] | None = None) -> RunInteractionPolicy:
        """Resolve one policy from trusted runtime fields.

        ``non_interactive`` and ``disable_clarification`` are legacy fields.
        They remain supported so existing callers keep their behavior while
        new entry points can use the more explicit ``run_interaction_mode``.
        """
        values = config or {}
        raw_requested = values.get("run_interaction_mode")
        if isinstance(raw_requested, str):
            requested = raw_requested.strip().lower()
        else:
            requested = None

        if requested not in _VALID_MODES:
            if raw_requested is not None:
                logger.warning("Unknown run interaction mode %r; falling back to legacy/default policy", raw_requested)
            if values.get("non_interactive"):
                requested = SCHEDULED_MODE
            elif values.get("disable_clarification"):
                requested = WEBHOOK_MODE
            else:
                requested = INTERACTIVE_MODE

        return cls(mode=requested, allows_clarification=requested == INTERACTIVE_MODE)

    @property
    def prompt_guidance(self) -> str:
        """Return prompt instructions compatible with this run's toolset."""
        if self.allows_clarification:
            return """<clarification_system>
**WORKFLOW PRIORITY: CLARIFY -> PLAN -> ACT**
- Analyze the request before acting and identify important missing or ambiguous details.
- When a human decision is needed, call `ask_clarification` before starting work and wait for the response.
- Use clarification for missing information, materially different interpretations, approach choices, and confirmation of risky or irreversible actions.
- Do not ask after starting work; once clarification is requested, wait for the user's response.
</clarification_system>"""

        if self.mode == WEBHOOK_MODE:
            return """<interaction_system mode="webhook">
This run has no synchronous human available. Infer intent from the issue, pull request, repository, and event context.
Make only minimal-risk, reversible assumptions and state those assumptions clearly in the result.
Do not wait for a human response or attempt to call a clarification tool.
If ambiguity affects an irreversible or high-risk action, stop that action and report a structured blocked outcome with the missing decision.
</interaction_system>"""

        if self.mode == SCHEDULED_MODE:
            return """<interaction_system mode="scheduled">
This run is unattended. Do not wait for a human response or attempt to call a clarification tool.
Follow the task prompt and any fallback explicitly provided by its context.
Make only minimal-risk, reversible assumptions and state those assumptions clearly in the result.
If ambiguity affects an irreversible or high-risk action, stop that action and report a structured blocked outcome with the missing decision.
</interaction_system>"""

        return """<interaction_system mode="autonomous">
This run is unattended. Make minimal-risk, reversible assumptions and state them clearly. Do not wait for a human response or attempt to call a clarification tool.
Stop and report a structured blocked outcome when ambiguity affects an irreversible or high-risk action.
</interaction_system>"""

    @property
    def thinking_guidance(self) -> str:
        if self.allows_clarification:
            return "- **PRIORITY CHECK: If anything is unclear, missing, or has multiple interpretations, use `ask_clarification` FIRST - do not proceed with work.**"
        return "- **PRIORITY CHECK: Do not wait for clarification. Use the interaction policy below: make minimal-risk, reversible assumptions, state them, and block only irreversible or high-risk ambiguity.**"

    @property
    def critical_reminder(self) -> str:
        if self.allows_clarification:
            return "- **Clarification First**: Clarify unclear, missing, or ambiguous requirements before starting work; wait for the human response."
        return "- **Unattended Run**: Do not wait for a human or invoke clarification; make minimal-risk, reversible assumptions, state them, and report irreversible or high-risk ambiguity as blocked."
