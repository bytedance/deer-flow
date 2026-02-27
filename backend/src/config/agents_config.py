"""Configuration and loaders for custom agents."""

import logging
from typing import Any

import yaml
from pydantic import BaseModel

from src.config.paths import get_paths

logger = logging.getLogger(__name__)

AGENT_NAME_PATTERN = r"^[a-z0-9-]+$"

SOUL_FILENAME = "SOUL.md"

DEFAULT_USER_MD = """\
# User Profile

This user is exploring DeerFlow's custom AI agents. \
Please be helpful, clear, and focused on their goals.\
"""


class AgentConfig(BaseModel):
    """Configuration for a custom agent."""

    name: str
    description: str = ""
    model: str | None = None
    tool_groups: list[str] | None = None


def load_agent_config(name: str) -> AgentConfig:
    """Load a custom agent's config from its directory.

    Args:
        name: The agent name.

    Returns:
        AgentConfig instance.

    Raises:
        FileNotFoundError: If the agent directory or config.yaml does not exist.
        ValueError: If config.yaml cannot be parsed.
    """
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


def load_agent_soul(agent_config: AgentConfig) -> str | None:
    """Read the SOUL.md file for a custom agent, if it exists.

    SOUL.md defines the agent's personality, values, and behavioral guardrails.
    It is injected into the lead agent's system prompt as additional context.

    Args:
        agent_config: The agent's configuration.

    Returns:
        The SOUL.md content as a string, or None if the file does not exist.
    """
    soul_path = get_paths().agent_dir(agent_config.name) / SOUL_FILENAME
    if not soul_path.exists():
        return None
    content = soul_path.read_text(encoding="utf-8").strip()
    return content or None


def load_user_md() -> str:
    """Read the global USER.md file, returning a default if it does not exist.

    USER.md describes the user's preferences, environment, and working style.
    It is injected into the lead agent's system prompt for all agents.

    Returns:
        The USER.md content as a string. Falls back to DEFAULT_USER_MD if the
        file is missing or empty.
    """
    user_md_path = get_paths().user_md_file
    if not user_md_path.exists():
        return DEFAULT_USER_MD
    content = user_md_path.read_text(encoding="utf-8").strip()
    return content or DEFAULT_USER_MD


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
