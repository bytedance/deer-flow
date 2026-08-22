"""Subagent registry for managing available subagents."""

import logging
from dataclasses import replace
from typing import Any

from deerflow.sandbox.security import is_host_bash_allowed
from deerflow.subagents.builtins import BUILTIN_SUBAGENTS
from deerflow.subagents.config import SubagentConfig

logger = logging.getLogger(__name__)


def _resolve_subagents_app_config(app_config: Any | None = None):
    if app_config is None:
        from deerflow.config.subagents_config import get_subagents_app_config

        return get_subagents_app_config()
    return getattr(app_config, "subagents", app_config)


def _build_custom_subagent_config(name: str, *, app_config: Any | None = None) -> SubagentConfig | None:
    """Build a SubagentConfig from config.yaml custom_agents section.

    Args:
        name: The name of the custom subagent.
        app_config: Optional AppConfig or SubagentsAppConfig to resolve from.

    Returns:
        SubagentConfig if found in custom_agents, None otherwise.
    """
    subagents_config = _resolve_subagents_app_config(app_config)
    custom = subagents_config.custom_agents.get(name)
    if custom is None:
        return None

    return SubagentConfig(
        name=name,
        description=custom.description,
        system_prompt=custom.system_prompt,
        tools=custom.tools,
        disallowed_tools=custom.disallowed_tools,
        skills=custom.skills,
        model=custom.model,
        max_turns=custom.max_turns,
        timeout_seconds=custom.timeout_seconds,
    )


def _resolve_full_app_config(app_config: Any | None = None) -> Any | None:
    """Return a full AppConfig-like object carrying ``.tools`` for group expansion."""
    if app_config is not None and hasattr(app_config, "tools"):
        return app_config
    try:
        from deerflow.config.app_config import get_app_config

        resolved = get_app_config()
    except Exception:
        return None
    return resolved if hasattr(resolved, "tools") else None


def _expand_tool_groups(groups: list[str] | None, *, app_config: Any | None = None) -> list[str] | None:
    """Expand ``AgentConfig.tool_groups`` into concrete tool names.

    Mirrors :func:`deerflow.tools.tools.get_available_tools`'s config-level group
    filtering without instantiating tool objects: the executor later intersects
    this allowlist with the real assembled pool, so names alone suffice here.
    ``None`` (unrestricted) passes through unchanged; an explicit empty list stays
    empty ("no tools"). When no app config can be resolved the agent inherits the
    full pool, matching the unrestricted default rather than silently disabling it.
    """
    if groups is None:
        return None
    full_config = _resolve_full_app_config(app_config)
    if full_config is None:
        logger.debug("Could not resolve app config for tool-group expansion; inheriting full tool pool")
        return None
    return [tool.name for tool in full_config.tools if tool.group in groups]


def _load_user_agent_record(name: str, *, user_id: str | None = None) -> tuple[Any, str | None] | None:
    """Load ``(AgentConfig, soul)`` from the per-user agent store; None when absent/invalid."""
    from deerflow.config.agents_config import load_agent_config, load_agent_soul

    try:
        agent = load_agent_config(name, user_id=user_id)
    except (FileNotFoundError, ValueError):
        # FileNotFoundError: no such agent; ValueError: unparsable config or a name
        # rejected by validate_agent_name (e.g. path traversal via subagent_type).
        return None
    if agent is None:
        return None
    try:
        soul = load_agent_soul(name, user_id=user_id)
    except (FileNotFoundError, ValueError):
        soul = None
    return agent, soul


def _list_user_agents(*, user_id: str | None = None) -> list[Any]:
    """List AgentConfig entries from the per-user store; [] on any failure."""
    from deerflow.config.agents_config import list_custom_agents

    try:
        return list_custom_agents(user_id=user_id)
    except Exception:
        # Unexpected store failures (I/O errors, permission problems) should
        # surface in production logs; absence of agents is handled upstream as [].
        logger.warning("Could not list user-scoped custom agents", exc_info=True)
        return []


def _build_agent_store_subagent_config(name: str, *, app_config: Any | None = None, user_id: str | None = None) -> SubagentConfig | None:
    """Build a SubagentConfig from the user-scoped custom-agent store (``/api/agents``).

    Third resolution tier: built-in > config.yaml custom_agents > per-user API agents,
    so user-defined agents can be dispatched via ``task(subagent_type=...)`` without
    shadowing operator-controlled sources. SOUL.md becomes the system prompt;
    ``tool_groups`` expand to concrete tool names; an unset model maps to
    ``"inherit"`` so the subagent follows its parent by default; ``max_turns`` /
    ``timeout_seconds`` keep the SubagentConfig defaults (per-agent yaml overrides
    still apply on top). The subagent never re-delegates: the SubagentConfig default
    ``disallowed_tools=["task"]`` holds.
    """
    record = _load_user_agent_record(name, user_id=user_id)
    if record is None:
        return None
    agent, soul = record
    system_prompt = (soul.strip() or None) if isinstance(soul, str) else None
    return SubagentConfig(
        name=name,
        description=agent.description or "",
        system_prompt=system_prompt,
        tools=_expand_tool_groups(agent.tool_groups, app_config=app_config),
        skills=agent.skills,
        model=agent.model or "inherit",
    )


def get_subagent_config(name: str, *, app_config: Any | None = None, user_id: str | None = None) -> SubagentConfig | None:
    """Get a subagent configuration by name, with config.yaml overrides applied.

    Resolution order (mirrors Codex's config layering):
    1. Built-in subagents (general-purpose, bash)
    2. Custom subagents from config.yaml custom_agents section
    3. User-scoped custom agents from the agent store (``/api/agents``, per-user)
    4. Per-agent overrides from config.yaml agents section (timeout, max_turns, model, skills)

    Args:
        name: The name of the subagent.
        app_config: Optional AppConfig or SubagentsAppConfig to resolve overrides from.
        user_id: Owner whose agent-store agents are resolvable. Defaults to the
            effective user from the current runtime context.

    Returns:
        SubagentConfig if found (with any config.yaml overrides applied), None otherwise.
    """
    # Step 1: Look up built-in, then fall back to custom_agents, then to the
    # user-scoped API agent store. Later tiers can never shadow earlier ones.
    config = BUILTIN_SUBAGENTS.get(name)
    if config is None:
        config = _build_custom_subagent_config(name, app_config=app_config)
    if config is None:
        config = _build_agent_store_subagent_config(name, app_config=app_config, user_id=user_id)
    if config is None:
        return None

    # Step 2: Apply per-agent overrides from config.yaml agents section.
    # Only explicit per-agent overrides are applied here. Global defaults
    # (timeout_seconds, max_turns at the top level) apply to built-in agents
    # but must NOT override custom agents' own values — custom agents define
    # their own defaults in the custom_agents section.
    subagents_config = _resolve_subagents_app_config(app_config)
    is_builtin = name in BUILTIN_SUBAGENTS
    agent_override = subagents_config.agents.get(name)

    overrides = {}

    # Timeout: per-agent override > global default (builtins only) > config's own value
    if agent_override is not None and agent_override.timeout_seconds is not None:
        if agent_override.timeout_seconds != config.timeout_seconds:
            logger.debug("Subagent '%s': timeout overridden (%ss -> %ss)", name, config.timeout_seconds, agent_override.timeout_seconds)
            overrides["timeout_seconds"] = agent_override.timeout_seconds
    elif is_builtin and subagents_config.timeout_seconds != config.timeout_seconds:
        logger.debug("Subagent '%s': timeout from global default (%ss -> %ss)", name, config.timeout_seconds, subagents_config.timeout_seconds)
        overrides["timeout_seconds"] = subagents_config.timeout_seconds

    # Max turns: per-agent override > global default (builtins only) > config's own value
    if agent_override is not None and agent_override.max_turns is not None:
        if agent_override.max_turns != config.max_turns:
            logger.debug("Subagent '%s': max_turns overridden (%s -> %s)", name, config.max_turns, agent_override.max_turns)
            overrides["max_turns"] = agent_override.max_turns
    elif is_builtin and subagents_config.max_turns is not None and subagents_config.max_turns != config.max_turns:
        logger.debug("Subagent '%s': max_turns from global default (%s -> %s)", name, config.max_turns, subagents_config.max_turns)
        overrides["max_turns"] = subagents_config.max_turns

    # Model: per-agent override only (no global default for model)
    effective_model = subagents_config.get_model_for(name)
    if effective_model is not None and effective_model != config.model:
        logger.debug("Subagent '%s': model overridden (%s -> %s)", name, config.model, effective_model)
        overrides["model"] = effective_model

    # Skills: per-agent override only (no global default for skills)
    effective_skills = subagents_config.get_skills_for(name)
    if effective_skills is not None and effective_skills != config.skills:
        logger.debug("Subagent '%s': skills overridden (%s -> %s)", name, config.skills, effective_skills)
        overrides["skills"] = effective_skills

    if overrides:
        config = replace(config, **overrides)

    return config


def list_subagents(*, app_config: Any | None = None, user_id: str | None = None) -> list[SubagentConfig]:
    """List all available subagent configurations (with config.yaml overrides applied).

    Args:
        app_config: Optional AppConfig or SubagentsAppConfig to resolve overrides from.
        user_id: Owner whose agent-store agents are included.

    Returns:
        List of all registered SubagentConfig instances (built-in + custom + API agents).
    """
    configs = []
    for name in get_subagent_names(app_config=app_config, user_id=user_id):
        config = get_subagent_config(name, app_config=app_config, user_id=user_id)
        if config is not None:
            configs.append(config)
    return configs


def get_subagent_names(*, app_config: Any | None = None, user_id: str | None = None) -> list[str]:
    """Get all available subagent names (built-in + custom + per-user API agents).

    Args:
        app_config: Optional AppConfig or SubagentsAppConfig to resolve from.
        user_id: Owner whose agent-store agents are included.

    Returns:
        List of subagent names.
    """
    names = list(BUILTIN_SUBAGENTS.keys())

    # Merge custom_agents from config.yaml
    subagents_config = _resolve_subagents_app_config(app_config)
    for custom_name in subagents_config.custom_agents:
        if custom_name not in names:
            names.append(custom_name)

    # Merge per-user API agents last so they can never shadow built-ins or
    # operator-controlled yaml entries.
    for agent in _list_user_agents(user_id=user_id):
        if agent.name not in names:
            names.append(agent.name)

    return names


def get_available_subagent_names(*, app_config: Any | None = None, user_id: str | None = None) -> list[str]:
    """Get subagent names that should be exposed to the active runtime.

    Args:
        app_config: Optional AppConfig or SubagentsAppConfig to resolve from.
        user_id: Owner whose agent-store agents are visible.

    Returns:
        List of subagent names visible to the current sandbox configuration.
    """
    names = get_subagent_names(app_config=app_config, user_id=user_id)
    try:
        host_bash_allowed = is_host_bash_allowed(app_config) if hasattr(app_config, "sandbox") else is_host_bash_allowed()
    except Exception:
        logger.debug("Could not determine host bash availability; exposing all subagents")
        return names

    if not host_bash_allowed:
        names = [name for name in names if name != "bash"]
    return names
