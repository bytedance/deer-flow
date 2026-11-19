"""The user's "stop when ..." rule and the launch-time instruction around it.

The rule is stored in ``scheduled_tasks.stop_condition``; the stored task
prompt never contains it. Only a launch composes the model-facing paragraph,
so the prefixes below are backend-internal and can change without migrating
any stored row.
"""

from typing import Final

STOP_RULE_PREFIX: Final[str] = "Stop rule from the user: when this is true, report it and call stop_scheduled_task to pause this schedule: "
STOP_RULE_NO_TOOL_PREFIX: Final[str] = "Stop rule from the user (this run cannot pause the schedule; if it is true, say so clearly so the user can pause it): "
MAX_STOP_CONDITION_CHARS: Final[int] = 500


def normalize_stop_condition(value: str | None) -> str | None:
    """Return the stored form of a stop condition, or None for "no rule".

    Whitespace and newlines collapse to single spaces. A blank value clears
    the rule. Raises ``ValueError`` when the normalized text is too long.
    """
    if value is None:
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if len(normalized) > MAX_STOP_CONDITION_CHARS:
        raise ValueError(f"stop_condition must be at most {MAX_STOP_CONDITION_CHARS} characters")
    return normalized


def launch_prompt(prompt: str, stop_condition: str | None, *, can_stop: bool) -> str:
    """Compose the launched message: the stored prompt plus the stop rule."""
    if not stop_condition:
        return prompt
    prefix = STOP_RULE_PREFIX if can_stop else STOP_RULE_NO_TOOL_PREFIX
    return f"{prompt.rstrip()}\n\n{prefix}{stop_condition}"
