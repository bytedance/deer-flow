"""Subagent registry for managing available subagents."""

import logging
from dataclasses import replace

from deerflow.sandbox.security import is_host_bash_allowed
from deerflow.subagents.builtins import BUILTIN_SUBAGENTS
from deerflow.subagents.config import SubagentConfig

logger = logging.getLogger(__name__)


def get_subagent_config(name: str) -> SubagentConfig | None:
    """Get a subagent configuration by name, with config.yaml overrides applied.

    Args:
        name: The name of the subagent.

    Returns:
        SubagentConfig if found (with any config.yaml overrides applied), None otherwise.
    """
    config = BUILTIN_SUBAGENTS.get(name)
    if config is None:
        return None

    # Apply timeout override from config.yaml (lazy import to avoid circular deps)
    from deerflow.config.subagents_config import get_subagents_app_config

    app_config = get_subagents_app_config()
    effective_timeout = app_config.get_timeout_for(name)
    effective_max_turns = app_config.get_max_turns_for(name, config.max_turns)

    overrides = {}
    if effective_timeout != config.timeout_seconds:
        logger.debug(
            "Subagent '%s': timeout overridden by config.yaml (%ss -> %ss)",
            name,
            config.timeout_seconds,
            effective_timeout,
        )
        overrides["timeout_seconds"] = effective_timeout
    if effective_max_turns != config.max_turns:
        logger.debug(
            "Subagent '%s': max_turns overridden by config.yaml (%s -> %s)",
            name,
            config.max_turns,
            effective_max_turns,
        )
        overrides["max_turns"] = effective_max_turns
    if overrides:
        config = replace(config, **overrides)

    return config


def list_subagents() -> list[SubagentConfig]:
    """List all available subagent configurations (with config.yaml overrides applied).

    Returns:
        List of all registered SubagentConfig instances.
    """
    return [get_subagent_config(name) for name in BUILTIN_SUBAGENTS]


def get_subagent_names() -> list[str]:
    """Get all available subagent names.

    Returns:
        List of subagent names.
    """
    return list(BUILTIN_SUBAGENTS.keys())


def get_available_subagent_names() -> list[str]:
    """Get subagent names that should be exposed to the active runtime.

    Returns:
        List of subagent names visible to the current sandbox configuration.
    """
    names = list(BUILTIN_SUBAGENTS.keys())
    try:
        host_bash_allowed = is_host_bash_allowed()
    except Exception:
        logger.debug("Could not determine host bash availability; exposing all built-in subagents")
        return names

    if not host_bash_allowed:
        names = [name for name in names if name != "bash"]
    return names
