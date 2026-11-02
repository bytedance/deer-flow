"""Private configuration for the skill-evolution extension.

The mapping handed to ``install()`` is operator-owned
(``config.yaml -> plugins: -> config``). Unknown or wrongly-typed fields are
hard errors: a silent fallback would let an operator typo quietly change the
model-facing evolution policy. Defaults reproduce the behaviour previously
hard-coded in the host's ``skill_evolution`` prompt section.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SCOPE_LEAD = "lead"
SCOPE_LEAD_AND_SUBAGENT = "lead_and_subagent"
_SCOPES = frozenset({SCOPE_LEAD, SCOPE_LEAD_AND_SUBAGENT})

# How saved trajectory annotations feed skill evolution. ``draft`` (default) is
# Plan A: a deterministic backend action synthesizes a draft SKILL.md from the
# current content plus the annotations, prefilled into the stage editor —
# fully offline, no new model surface. ``agent`` is Plan B: the middleware
# additionally declares the read-only ``skill_feedback`` tool and the evolution
# policy tells the agent to consult it before evolving a skill.
FEEDBACK_MODE_DRAFT = "draft"
FEEDBACK_MODE_AGENT = "agent"
_FEEDBACK_MODES = frozenset({FEEDBACK_MODE_DRAFT, FEEDBACK_MODE_AGENT})

_MIN_TOOL_CALLS_HINT_MIN = 1
_MIN_TOOL_CALLS_HINT_MAX = 100


@dataclass(frozen=True)
class SkillEvolutionSettings:
    """Validated, frozen policy knobs for the extension.

    ``min_tool_calls_hint`` is only rendered into the prompt as advice; it is
    not a deterministic trigger, counter, or scheduler. ``scope`` selects
    which agent builds receive the contribution; ``lead`` is the deliberate
    default — subagents do not need an active evolution prompt.
    """

    min_tool_calls_hint: int = 5
    prefer_patch: bool = True
    confirm_before_create: bool = True
    scope: str = SCOPE_LEAD
    storage_path: str | None = None
    feedback_mode: str = FEEDBACK_MODE_DRAFT

    @property
    def includes_subagents(self) -> bool:
        return self.scope == SCOPE_LEAD_AND_SUBAGENT


_FIELDS = frozenset({"min_tool_calls_hint", "prefer_patch", "confirm_before_create", "scope", "storage_path", "feedback_mode"})


def parse_config(config: Mapping[str, Any]) -> SkillEvolutionSettings:
    """Validate the operator's private config block; raise ``ValueError`` on any defect."""
    unknown = sorted(str(key) for key in config if key not in _FIELDS)
    if unknown:
        raise ValueError(f"Unknown skill-evolution config key(s): {', '.join(unknown)}. Supported keys: {', '.join(sorted(_FIELDS))}.")

    min_tool_calls_hint = config.get("min_tool_calls_hint", 5)
    # ``type(...) is int`` rejects bools: True/False are ints in Python and a
    # boolean here would silently render nonsense ("1+ tool calls").
    if type(min_tool_calls_hint) is not int or not (_MIN_TOOL_CALLS_HINT_MIN <= min_tool_calls_hint <= _MIN_TOOL_CALLS_HINT_MAX):
        raise ValueError(f"min_tool_calls_hint must be an integer between {_MIN_TOOL_CALLS_HINT_MIN} and {_MIN_TOOL_CALLS_HINT_MAX}, got {min_tool_calls_hint!r}.")

    prefer_patch = config.get("prefer_patch", True)
    if type(prefer_patch) is not bool:
        raise ValueError(f"prefer_patch must be a boolean, got {prefer_patch!r}.")

    confirm_before_create = config.get("confirm_before_create", True)
    if type(confirm_before_create) is not bool:
        raise ValueError(f"confirm_before_create must be a boolean, got {confirm_before_create!r}.")

    scope = config.get("scope", SCOPE_LEAD)
    if scope not in _SCOPES:
        raise ValueError(f"scope must be one of {', '.join(sorted(_SCOPES))}, got {scope!r}.")

    storage_path = config.get("storage_path")
    if storage_path is not None and (not isinstance(storage_path, str) or not storage_path.strip()):
        raise ValueError(f"storage_path must be a non-empty absolute path string, got {storage_path!r}.")

    feedback_mode = config.get("feedback_mode", FEEDBACK_MODE_DRAFT)
    if feedback_mode not in _FEEDBACK_MODES:
        raise ValueError(f"feedback_mode must be one of {', '.join(sorted(_FEEDBACK_MODES))}, got {feedback_mode!r}.")

    return SkillEvolutionSettings(
        min_tool_calls_hint=min_tool_calls_hint,
        prefer_patch=prefer_patch,
        confirm_before_create=confirm_before_create,
        scope=scope,
        storage_path=storage_path,
        feedback_mode=feedback_mode,
    )
