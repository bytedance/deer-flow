"""Resolve delegation defaults before the shared model policy is applied."""

from dataclasses import dataclass
from typing import Any

from deerflow.models.reasoning import GENERIC_EFFORT_VALUES, resolve_reasoning_contract, resolve_reasoning_request
from deerflow.subagents.config import SubagentConfig


@dataclass(frozen=True)
class SubagentReasoningRequest:
    thinking_enabled: bool | None
    reasoning_effort: str | None


def resolve_subagent_reasoning(
    config: SubagentConfig,
    model_config: Any,
    *,
    parent_model_config: Any = None,
    parent_thinking_enabled: bool | None = None,
    parent_reasoning_effort: str | None = None,
) -> SubagentReasoningRequest:
    """Explicit worker overrides win; otherwise inherit compatible effective settings.

    A missing parent preference (or ``reasoning_source: model``) leaves the
    model/provider default intact. Inherited preferences adapt to the child's
    capabilities; explicit requests still go through factory validation.
    """
    contract = resolve_reasoning_contract(model_config)
    thinking = config.thinking_enabled
    effort = config.reasoning_effort
    if config.reasoning_source == "inherit":
        if thinking is None and isinstance(parent_thinking_enabled, bool):
            thinking = parent_thinking_enabled
            if contract.thinking == "required":
                thinking = True
            elif contract.thinking == "unsupported":
                thinking = False
        if effort is None and isinstance(parent_reasoning_effort, str):
            target = contract.effort
            parent = resolve_reasoning_contract(parent_model_config).effort
            inherited = parent_reasoning_effort
            # Legacy lead metadata may retain a raw effort that the parent's
            # factory dropped. Such a request is not an effective preference.
            if target is not None and (parent_model_config is None or parent is not None):
                same_legacy_profile = not target.strict and getattr(model_config, "name", None) is not None and model_config.name == getattr(parent_model_config, "name", None)
                # Provider-native tokens are portable only if the child declares
                # them, the profile is unchanged, or the parent supplies a generic alias.
                if inherited not in target.values and inherited not in target.aliases:
                    aliases = [key for key, value in parent.aliases.items() if key in GENERIC_EFFORT_VALUES and value == inherited] if parent else []
                    inherited = aliases[0] if len(aliases) == 1 else inherited
                if same_legacy_profile or inherited in target.values or inherited in target.aliases:
                    effort = resolve_reasoning_request(contract, thinking_enabled=thinking, reasoning_effort=inherited).reasoning_effort
    return SubagentReasoningRequest(thinking_enabled=thinking, reasoning_effort=effort)
