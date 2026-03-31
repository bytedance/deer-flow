"""Configuration and loaders for custom agents."""

import logging
import re
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel

from deerflow.config.paths import get_paths

if TYPE_CHECKING:
    from deerflow.identity.agent_identity import AgentIdentity

logger = logging.getLogger(__name__)

SOUL_FILENAME = "SOUL.md"
AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")


class AgentConfig(BaseModel):
    """Configuration for a custom agent."""

    name: str
    description: str = ""
    model: str | None = None
    tool_groups: list[str] | None = None


def load_agent_config(name: str | None, identity: "AgentIdentity | None" = None) -> AgentConfig | None:
    """Load the custom or default agent's config from its directory.

    When *identity* is provided and non-global (has dept_id or user_id), the
    identity-scoped path is tried first:
      depts/{dept_id}/users/{user_id}/agents/{name}/config.yaml
    If that directory or config.yaml does not exist, None is returned
    (the caller should fall back to global defaults).

    When *identity* is absent or global, the original path is used:
      agents/{name}/config.yaml

    Args:
        name: The agent name.
        identity: Optional three-tier identity for path resolution.

    Returns:
        AgentConfig instance, or None if no config file was found.

    Raises:
        FileNotFoundError: Only for the legacy (no-identity) path when the
            agent directory itself is missing.
        ValueError: If the agent name is invalid (legacy path only).
    """
    if name is None:
        return None

    # ── Identity-scoped path (new behaviour) ────────────────────────────
    if identity is not None and not identity.is_global:
        agent_dir = get_paths().identity_agent_dir(identity)
        if agent_dir is None or not agent_dir.exists():
            # Identity directory not set up yet — gracefully return None
            return None
        config_file = agent_dir / "config.yaml"
        if not config_file.exists():
            # config.yaml is optional in the identity path
            return None
    else:
        # ── Legacy path (original behaviour, unchanged) ─────────────────
        if not AGENT_NAME_PATTERN.match(name):
            raise ValueError(f"Invalid agent name '{name}'. Must match pattern: {AGENT_NAME_PATTERN.pattern}")
        agent_dir = get_paths().agent_dir(name)
        config_file = agent_dir / "config.yaml"

        if not agent_dir.exists():
            raise FileNotFoundError(f"Agent directory not found: {agent_dir}")
        if not config_file.exists():
            raise FileNotFoundError(f"Agent config not found: {config_file}")

    try:
        with open(config_file, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse agent config {config_file}: {e}") from e

    # Ensure name is set from directory name if not in file
    if "name" not in data:
        data["name"] = name

    # Strip unknown fields before passing to Pydantic (e.g. legacy prompt_file)
    known_fields = set(AgentConfig.model_fields.keys())
    data = {k: v for k, v in data.items() if k in known_fields}

    return AgentConfig(**data)


def load_agent_soul(agent_name: str | None) -> str | None:
    """Read the SOUL.md file for a custom agent, if it exists.

    SOUL.md defines the agent's personality, values, and behavioral guardrails.
    It is injected into the lead agent's system prompt as additional context.

    Args:
        agent_name: The name of the agent or None for the default agent.

    Returns:
        The SOUL.md content as a string, or None if the file does not exist.
    """
    agent_dir = get_paths().agent_dir(agent_name) if agent_name else get_paths().base_dir
    soul_path = agent_dir / SOUL_FILENAME
    if not soul_path.exists():
        return None
    content = soul_path.read_text(encoding="utf-8").strip()
    return content or None


def list_custom_agents() -> list[AgentConfig]:
    """Scan the agents directory and return all valid custom agents.

    Returns:
        List of AgentConfig for each valid agent directory found.
    """
    agents_dir = get_paths().agents_dir

    if not agents_dir.exists():
        return []

    agents: list[AgentConfig] = []

    for entry in sorted(agents_dir.iterdir()):
        if not entry.is_dir():
            continue

        config_file = entry / "config.yaml"
        if not config_file.exists():
            logger.debug(f"Skipping {entry.name}: no config.yaml")
            continue

        try:
            agent_cfg = load_agent_config(entry.name)
            agents.append(agent_cfg)
        except Exception as e:
            logger.warning(f"Skipping agent '{entry.name}': {e}")

    return agents
