"""Configuration and loaders for custom agents.

Custom agents are stored per-user under ``{base_dir}/users/{user_id}/agents/{name}/``.
A legacy shared layout at ``{base_dir}/agents/{name}/`` is still readable so that
installations that pre-date user isolation continue to work until they run the
``scripts/migrate_user_isolation.py`` migration. New writes always target the
per-user layout.
"""

import logging
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from deerflow.config.paths import get_paths
from deerflow.config.runtime_paths import project_root
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)

SOUL_FILENAME = "SOUL.md"
AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")


def validate_agent_name(name: str | None) -> str | None:
    """Validate a custom agent name before using it in filesystem paths."""
    if name is None:
        return None
    if not isinstance(name, str):
        raise ValueError("Invalid agent name. Expected a string or None.")
    if not AGENT_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"Invalid agent name '{name}'. Must match pattern: {AGENT_NAME_PATTERN.pattern}")
    return name


class StarterConfig(BaseModel):
    """A starter prompt that can be shown on the agent welcome page."""

    label: str
    prompt: str
    icon: str | None = None
    auto_start: bool = False


class AgentConfig(BaseModel):
    """Configuration for a custom agent."""

    name: str
    description: str = ""
    display_name: str | None = None
    icon: str | None = None
    model: str | None = None
    visibility: str = "public"
    type: str | None = None
    parent: str | None = None
    order: int | None = None
    tool_groups: list[str] | None = None
    exclude_tools: list[str] | None = None
    # skills controls which skills are loaded into the agent's prompt:
    # - None (or omitted): load all enabled skills (default fallback behavior)
    # - [] (explicit empty list): disable all skills
    # - ["skill1", "skill2"]: load only the specified skills
    skills: list[str] | None = None
    mcp_servers: list[str] | None = None
    tags: list[str] | None = None
    starters: list[StarterConfig] | None = None
    advanced: dict[str, Any] | None = None


class AgentInfo(BaseModel):
    """API response model for agent listings (includes runtime metadata)."""

    name: str
    description: str = ""
    display_name: str | None = None
    icon: str | None = None
    source: str = "user"
    tenant_id: str | None = None
    editable: bool = True
    enabled: bool = True
    type: str | None = None
    parent: str | None = None
    order: int | None = None
    tags: list[str] | None = None
    tool_groups: list[str] | None = None
    skills: list[str] | None = None
    mcp_servers: list[str] | None = None
    starters: list[StarterConfig] | None = None


def to_agent_info(config: AgentConfig, *, source: str = "user", editable: bool = True, enabled: bool = True, tenant_id: str | None = None) -> AgentInfo:
    """Convert an AgentConfig to an AgentInfo with runtime metadata."""
    return AgentInfo(
        name=config.name,
        description=config.description,
        display_name=config.display_name,
        icon=config.icon,
        source=source,
        tenant_id=tenant_id,
        editable=editable,
        enabled=enabled,
        type=config.type,
        parent=config.parent,
        order=config.order,
        tags=config.tags,
        tool_groups=config.tool_groups,
        skills=config.skills,
        mcp_servers=config.mcp_servers,
        starters=config.starters,
    )


def resolve_agent_dir(name: str, *, user_id: str | None = None) -> Path:
    """Return the on-disk directory for an agent, preferring the per-user layout.

    Resolution order:
    1. ``{base_dir}/users/{user_id}/agents/{name}/`` (per-user, current layout).
    2. ``{base_dir}/agents/{name}/`` (legacy shared layout — read-only fallback).

    If neither exists, the per-user path is returned so callers that intend to
    create the agent write into the new layout.

    Args:
        name: Validated agent name.
        user_id: Owner of the agent. Defaults to the effective user from the
            request context (or ``"default"`` in no-auth mode).
    """
    paths = get_paths()
    effective_user = user_id or get_effective_user_id()
    user_path = paths.user_agent_dir(effective_user, name)
    if user_path.exists():
        return user_path

    legacy_path = paths.agent_dir(name)
    if legacy_path.exists():
        return legacy_path

    return user_path


def load_agent_config(name: str | None, *, user_id: str | None = None, tenant_id: str | None = None) -> AgentConfig | None:
    """Load the custom or default agent's config from its directory.

    Reads from the per-user layout first; falls back to tenant then builtin agents.

    Resolution order:
    1. User agent (per-user layout, then legacy shared layout)
    2. Tenant agent ({base_dir}/tenants/{tenant_id}/agents/{name}/)
    3. Builtin agent (project_root/agents/builtin/)

    Args:
        name: The agent name.
        user_id: Owner of the agent. Defaults to the effective user from the
            current request context.
        tenant_id: Tenant scope for agent lookup.

    Returns:
        AgentConfig instance, or ``None`` if ``name`` is ``None``.

    Raises:
        FileNotFoundError: If the agent directory or config.yaml does not exist
            in any of the searched locations.
        ValueError: If config.yaml cannot be parsed.
    """

    if name is None:
        return None

    name = validate_agent_name(name)

    # 1. User agent (existing logic)
    agent_dir = resolve_agent_dir(name, user_id=user_id)
    config_file = agent_dir / "config.yaml"

    if agent_dir.exists() and config_file.exists():
        try:
            with open(config_file, encoding="utf-8") as f:
                data: dict[str, Any] = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse agent config {config_file}: {e}") from e

        if "name" not in data:
            data["name"] = name

        known_fields = set(AgentConfig.model_fields.keys())
        data = {k: v for k, v in data.items() if k in known_fields}
        return AgentConfig(**data)

    # 2. Tenant agent (filesystem-based lookup)
    if tenant_id:
        tenant_agent_dir = get_paths().base_dir / "tenants" / tenant_id / "agents" / name
        tenant_config_file = tenant_agent_dir / "config.yaml"
        if tenant_agent_dir.exists() and tenant_config_file.exists():
            try:
                with open(tenant_config_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            except yaml.YAMLError as e:
                raise ValueError(f"Failed to parse tenant agent config {tenant_config_file}: {e}") from e

            if "name" not in data:
                data["name"] = name

            known_fields = set(AgentConfig.model_fields.keys())
            data = {k: v for k, v in data.items() if k in known_fields}
            return AgentConfig(**data)

    # 3. Builtin agent
    builtin_dir = _get_builtin_agents_dir() / name
    builtin_config = builtin_dir / "config.yaml"
    if builtin_dir.exists() and builtin_config.exists():
        try:
            with open(builtin_config, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse builtin agent config {builtin_config}: {e}") from e

        if "name" not in data:
            data["name"] = name

        known_fields = set(AgentConfig.model_fields.keys())
        data = {k: v for k, v in data.items() if k in known_fields}
        return AgentConfig(**data)

    raise FileNotFoundError(f"Agent '{name}' not found in user, tenant, or builtin locations")


def load_agent_soul(agent_name: str | None, *, user_id: str | None = None) -> str | None:
    """Read the SOUL.md file for a custom agent, if it exists.

    SOUL.md defines the agent's personality, values, and behavioral guardrails.
    It is injected into the lead agent's system prompt as additional context.

    Args:
        agent_name: The name of the agent or None for the default agent.
        user_id: Owner of the agent. Defaults to the effective user from the
            current request context.

    Returns:
        The SOUL.md content as a string, or None if the file does not exist.
    """
    if agent_name:
        agent_dir = resolve_agent_dir(agent_name, user_id=user_id)
        soul_path = agent_dir / SOUL_FILENAME
        if not soul_path.exists():
            # Fall through to builtin agents
            builtin_soul = _get_builtin_agents_dir() / agent_name / SOUL_FILENAME
            if builtin_soul.exists():
                soul_path = builtin_soul
            else:
                return None
    else:
        agent_dir = get_paths().base_dir
        soul_path = agent_dir / SOUL_FILENAME
        if not soul_path.exists():
            return None
    content = soul_path.read_text(encoding="utf-8").strip()
    return content or None


def list_custom_agents(*, user_id: str | None = None) -> list[AgentConfig]:
    """Scan the agents directory and return all valid custom agents.

    Returns the union of agents in the per-user layout and the legacy shared
    layout, so that pre-migration installations remain visible until they are
    migrated. Per-user entries shadow legacy entries with the same name.

    Args:
        user_id: Owner whose agents to list. Defaults to the effective user
            from the current request context.

    Returns:
        List of AgentConfig for each valid agent directory found.
    """
    paths = get_paths()
    effective_user = user_id or get_effective_user_id()

    seen: set[str] = set()
    agents: list[AgentConfig] = []

    user_root = paths.user_agents_dir(effective_user)
    legacy_root = paths.agents_dir

    for root in (user_root, legacy_root):
        if not root.exists():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name in seen:
                continue
            config_file = entry / "config.yaml"
            if not config_file.exists():
                logger.debug(f"Skipping {entry.name}: no config.yaml")
                continue

            try:
                agent_cfg = load_agent_config(entry.name, user_id=effective_user)
                if agent_cfg is None:
                    continue
                agents.append(agent_cfg)
                seen.add(entry.name)
            except Exception as e:
                logger.warning(f"Skipping agent '{entry.name}': {e}")

    agents.sort(key=lambda a: a.name)
    return agents


def _get_builtin_agents_dir() -> Path:
    """Return the path to the builtin agents directory at project root.

    Falls back to the repo root (parent of backend/) for monorepo layouts
    where project_root() resolves to the backend/ directory.
    """
    candidate = project_root() / "agents" / "builtin"
    if candidate.is_dir():
        return candidate
    # Monorepo fallback: backend/ is project_root, agents/ is one level up
    repo_root = Path(__file__).resolve().parents[4].parent
    fallback = repo_root / "agents" / "builtin"
    if fallback.is_dir():
        return fallback
    return candidate


def scan_builtin_agents() -> list[AgentConfig]:
    """Scan the builtin agents directory and return all valid builtin agents.

    Builtin agents are stored at ``{project_root}/agents/builtin/{name}/``
    alongside the ``skills/`` directory. They are git-tracked and ship with
    the application.

    Returns:
        List of AgentConfig for each valid builtin agent found.
        Returns an empty list if the directory does not exist.
    """
    builtin_dir = _get_builtin_agents_dir()
    if not builtin_dir.exists():
        return []

    agents: list[AgentConfig] = []
    for entry in sorted(builtin_dir.iterdir()):
        if not entry.is_dir():
            continue
        config_file = entry / "config.yaml"
        if not config_file.exists():
            logger.debug(f"Skipping builtin agent {entry.name}: no config.yaml")
            continue

        try:
            with open(config_file, encoding="utf-8") as f:
                data: dict[str, Any] = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            logger.warning(f"Skipping builtin agent '{entry.name}': {e}")
            continue

        if "name" not in data:
            data["name"] = entry.name

        known_fields = set(AgentConfig.model_fields.keys())
        data = {k: v for k, v in data.items() if k in known_fields}

        try:
            agents.append(AgentConfig(**data))
        except Exception as e:
            logger.warning(f"Skipping builtin agent '{entry.name}': {e}")

    agents.sort(key=lambda a: a.name)
    return agents


def load_builtin_agent_soul(name: str) -> str | None:
    """Read the SOUL.md for a builtin agent."""
    soul_path = _get_builtin_agents_dir() / name / SOUL_FILENAME
    if not soul_path.exists():
        return None
    content = soul_path.read_text(encoding="utf-8").strip()
    return content or None


def load_tenant_agent_soul(tenant_id: str, name: str) -> str | None:
    """Read the SOUL.md for a tenant agent."""
    soul_path = get_paths().base_dir / "tenants" / tenant_id / "agents" / name / SOUL_FILENAME
    if not soul_path.exists():
        return None
    content = soul_path.read_text(encoding="utf-8").strip()
    return content or None


def scan_tenant_agents(tenant_id: str) -> list[AgentConfig]:
    """Scan the tenant agents directory and return all valid tenant agents.

    Tenant agents are stored at ``{base_dir}/tenants/{tenant_id}/agents/{name}/``.
    They are managed via the tenant admin CRUD API.

    Args:
        tenant_id: The tenant whose agents to scan.

    Returns:
        List of AgentConfig for each valid tenant agent found.
        Returns an empty list if the directory does not exist.
    """
    tenant_agents_dir = get_paths().base_dir / "tenants" / tenant_id / "agents"
    if not tenant_agents_dir.exists():
        return []

    agents: list[AgentConfig] = []
    for entry in sorted(tenant_agents_dir.iterdir()):
        if not entry.is_dir():
            continue
        config_file = entry / "config.yaml"
        if not config_file.exists():
            continue

        try:
            with open(config_file, encoding="utf-8") as f:
                data: dict[str, Any] = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            logger.warning(f"Skipping tenant agent '{entry.name}': {e}")
            continue

        if "name" not in data:
            data["name"] = entry.name

        known_fields = set(AgentConfig.model_fields.keys())
        data = {k: v for k, v in data.items() if k in known_fields}

        try:
            agents.append(AgentConfig(**data))
        except Exception as e:
            logger.warning(f"Skipping tenant agent '{entry.name}': {e}")

    agents.sort(key=lambda a: a.name)
    return agents


def list_available_agents(*, tenant_id: str | None = None, user_id: str | None = None) -> list[AgentInfo]:
    """Return the merged list of agents visible to a user, with priority dedup.

    Discovery priority (higher overrides lower):
    1. User agents (highest — user's own customizations)
    2. Tenant agents (tenant-level shared agents)
    3. Builtin agents (lowest — shipped defaults)

    When the same agent name exists at multiple levels, the highest-priority
    version wins. This allows users to override tenant agents, and tenant
    agents to override builtins.

    Args:
        tenant_id: The tenant scope. If None, tenant agents are skipped.
        user_id: The user whose agents to include. Defaults to effective user.

    Returns:
        Deduplicated list of AgentInfo sorted by name.
    """
    seen: set[str] = set()
    result: list[AgentInfo] = []

    # 1. User agents (highest priority)
    for cfg in list_custom_agents(user_id=user_id):
        if cfg.name not in seen:
            seen.add(cfg.name)
            result.append(to_agent_info(cfg, source="user", editable=True, tenant_id=tenant_id))

    # 2. Tenant agents
    if tenant_id:
        for cfg in scan_tenant_agents(tenant_id):
            if cfg.name not in seen:
                seen.add(cfg.name)
                result.append(to_agent_info(cfg, source="tenant", editable=False, tenant_id=tenant_id))

    # 3. Builtin agents (lowest priority)
    for cfg in scan_builtin_agents():
        if cfg.name not in seen:
            seen.add(cfg.name)
            result.append(to_agent_info(cfg, source="builtin", editable=False))

    result.sort(key=lambda a: a.name)
    return result
