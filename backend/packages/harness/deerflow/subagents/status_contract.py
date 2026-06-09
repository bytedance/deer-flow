"""Backend↔frontend contract for the structured subagent status.

Bytedance/deer-flow issue #3146: the frontend used to derive the
subtask card state by string-matching the leading text of the
``task`` tool's result. That contract was fragile — any rewording on
the backend silently broke the card lifecycle, and the issue history
of #3107 BUG-007 / #3131 review showed it repeatedly.

This module replaces the text-shaped contract with a small structured
one carried inside ``ToolMessage.additional_kwargs``:

- ``subagent_status``: one of ``SUBAGENT_STATUS_VALUES``.
- ``subagent_error`` (optional): the human-readable error blob the
  backend recorded.

The mapping from "task tool result text" to status is the one piece
the backend stamper (``ToolErrorHandlingMiddleware``) and the
frontend fallback parser must agree on. The shared fixture at
``contracts/subagent_status_contract.json`` is the single source of
truth — both sides' tests load it and assert behaviour.
"""

from __future__ import annotations

from typing import Literal

SUBAGENT_STATUS_KEY = "subagent_status"
SUBAGENT_ERROR_KEY = "subagent_error"

SubagentStatusValue = Literal[
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "polling_timed_out",
]

#: Enumeration of every value ``subagent_status`` may take. Mirrors the
#: ``valid_status_values`` array in the shared fixture; the contract test
#: pins them against each other.
SUBAGENT_STATUS_VALUES: tuple[SubagentStatusValue, ...] = (
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "polling_timed_out",
)

# Prefix table — ordered most-specific-first because some prefixes are
# substrings of others ("Task timed out" vs "Task polling timed out", "Task
# failed" vs "Task failed. Error: ..."). The "Task " prefixes come from
# ``task_tool.py``'s 5 normal-return strings; the bare ``Error:`` prefix
# catches both the 3 ``Error:`` pre-execution returns and the wrapper
# produced by ``ToolErrorHandlingMiddleware`` for any task tool exception.
_PREFIX_TO_STATUS: tuple[tuple[str, SubagentStatusValue], ...] = (
    ("Task Succeeded. Result:", "completed"),
    ("Task polling timed out", "polling_timed_out"),
    ("Task timed out", "timed_out"),
    ("Task cancelled by user", "cancelled"),
    ("Task failed.", "failed"),
    ("Error", "failed"),
)


def extract_subagent_status(content: str) -> SubagentStatusValue | None:
    """Infer the structured status for a ``task`` tool result string.

    Returns ``None`` when the content does not match any known terminal
    prefix. Non-terminal streaming chunks fall into this branch by
    design — the middleware then leaves ``subagent_status`` unset so
    the frontend keeps the card on its in-progress placeholder until
    the real terminal frame arrives.
    """
    trimmed = content.strip()
    for prefix, status in _PREFIX_TO_STATUS:
        if trimmed.startswith(prefix):
            return status
    return None


def make_subagent_additional_kwargs(
    status: SubagentStatusValue,
    *,
    error: str | None = None,
) -> dict[str, str]:
    """Build the ``additional_kwargs`` payload the middleware stamps.

    Drops the error field when blank so the JSON wire format never carries
    a misleading empty ``subagent_error: ""``.

    Raises:
        ValueError: when ``status`` is not in :data:`SUBAGENT_STATUS_VALUES`.
            We do not accept arbitrary strings: a typo would silently leak
            through to the frontend and degrade to the legacy prefix
            fallback rather than failing loudly.
    """
    if status not in SUBAGENT_STATUS_VALUES:
        raise ValueError(f"invalid subagent status {status!r}; expected one of {SUBAGENT_STATUS_VALUES}")
    payload: dict[str, str] = {SUBAGENT_STATUS_KEY: status}
    if error and error.strip():
        payload[SUBAGENT_ERROR_KEY] = error.strip()
    return payload
