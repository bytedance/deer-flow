"""Tenant initialization utilities for auto-forking builtin agents."""

from __future__ import annotations

import logging

import yaml

from deerflow.config.agents_config import load_builtin_agent_soul, scan_builtin_agents
from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)


def initialize_tenant_agents(tenant_id: str, *, auto_fork_agents: list[str] | None = None) -> list[str]:
    """Fork specified builtin agents to a tenant's agent directory.

    Called during tenant creation to seed the tenant with default agents.

    Args:
        tenant_id: The tenant to initialize.
        auto_fork_agents: List of builtin agent names to fork.
            If None or empty, no agents are forked.

    Returns:
        List of agent names that were successfully forked.
    """
    if not auto_fork_agents:
        return []

    paths = get_paths()
    builtin_agents = {a.name: a for a in scan_builtin_agents()}
    forked: list[str] = []

    for name in auto_fork_agents:
        if name not in builtin_agents:
            logger.warning(f"Cannot fork builtin agent '{name}' to tenant '{tenant_id}': not found")
            continue

        agent_dir = paths.base_dir / "tenants" / tenant_id / "agents" / name
        if agent_dir.exists():
            logger.debug(f"Tenant agent '{name}' already exists for tenant '{tenant_id}', skipping")
            continue

        config = builtin_agents[name]
        agent_dir.mkdir(parents=True, exist_ok=True)

        config_data: dict = {"name": name}
        if config.description:
            config_data["description"] = config.description
        if config.display_name:
            config_data["display_name"] = config.display_name
        if config.icon:
            config_data["icon"] = config.icon
        if config.model:
            config_data["model"] = config.model
        if config.tool_groups:
            config_data["tool_groups"] = config.tool_groups
        if config.skills is not None:
            config_data["skills"] = config.skills
        if config.mcp_servers:
            config_data["mcp_servers"] = config.mcp_servers
        if config.tags:
            config_data["tags"] = config.tags
        config_data["visibility"] = "tenant_public"

        (agent_dir / "config.yaml").write_text(yaml.dump(config_data, allow_unicode=True), encoding="utf-8")

        soul = load_builtin_agent_soul(name) or ""
        (agent_dir / "SOUL.md").write_text(soul, encoding="utf-8")

        forked.append(name)
        logger.info(f"Forked builtin agent '{name}' to tenant '{tenant_id}'")

    return forked
