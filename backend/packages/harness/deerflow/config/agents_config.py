"""Configuration and loaders for custom agents."""

import logging
import re
import unicodedata
from typing import Any

import yaml
from pydantic import BaseModel

from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)

SOUL_FILENAME = "SOUL.md"
AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")
AGENT_SLUG_FALLBACK = "agent"


class AgentConfig(BaseModel):
    """Configuration for a custom agent."""

    name: str
    display_name: str | None = None
    description: str = ""
    model: str | None = None
    tool_groups: list[str] | None = None
    # skills controls which skills are loaded into the agent's prompt:
    # - None (or omitted): load all enabled skills (default fallback behavior)
    # - [] (explicit empty list): disable all skills
    # - ["skill1", "skill2"]: load only the specified skills
    skills: list[str] | None = None


def normalize_agent_name(name: str) -> str:
    """Normalize the stable agent identifier for storage and routing."""
    return name.lower()


def normalize_display_name(display_name: str) -> str:
    """Normalize a user-facing display name without constraining its script."""
    normalized = " ".join(display_name.strip().split())
    if not normalized:
        raise ValueError("Display name must be a non-empty string.")
    return normalized


def display_name_key(display_name: str) -> str:
    """Build a comparison key for display-name uniqueness checks."""
    return normalize_display_name(display_name).casefold()


def derive_agent_name(display_name: str) -> str:
    """Derive an ASCII slug from a display name for filesystem-safe identity."""
    normalized = unicodedata.normalize("NFKD", display_name)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_only).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    return slug or AGENT_SLUG_FALLBACK


def get_unique_agent_name(display_name: str, existing_names: set[str]) -> str:
    """Generate a unique ASCII slug for a new agent."""
    base_slug = derive_agent_name(display_name)
    candidate = base_slug
    suffix = 2
    while candidate in existing_names:
        candidate = f"{base_slug}-{suffix}"
        suffix += 1
    return candidate


def get_agent_display_name(agent_name: str | None) -> str | None:
    """Return the user-facing display name for an agent, falling back to slug."""
    if agent_name is None:
        return None
    try:
        config = load_agent_config(agent_name)
    except (FileNotFoundError, ValueError):
        logger.debug(
            "Unable to load display name for agent '%s'; falling back to slug.",
            agent_name,
        )
        return None
    if config is None:
        return None
    return config.display_name or config.name


def load_agent_config(name: str | None) -> AgentConfig | None:
    """Load the custom or default agent's config from its directory.

    Args:
        name: The agent name.

    Returns:
        AgentConfig instance.

    Raises:
        FileNotFoundError: If the agent directory or config.yaml does not exist.
        ValueError: If config.yaml cannot be parsed.
    """

    if name is None:
        return None

    if not AGENT_NAME_PATTERN.match(name):
        raise ValueError(f"Invalid agent name '{name}'. Must match pattern: {AGENT_NAME_PATTERN.pattern}")
    normalized_name = normalize_agent_name(name)
    agent_dir = get_paths().agent_dir(normalized_name)
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
        data["name"] = normalized_name
    else:
        data["name"] = normalize_agent_name(str(data["name"]))

    if "display_name" in data and data["display_name"] is not None:
        data["display_name"] = normalize_display_name(str(data["display_name"]))

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
