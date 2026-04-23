"""Configuration and loaders for custom agents."""

import logging
import os.path
import re
from typing import Any

import yaml
from pydantic import BaseModel

from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)

SOUL_FILENAME = "SOUL.md"
AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")


class AgentConfig(BaseModel):
    """Configuration for a custom agent."""

    name: str
    description: str = ""
    model: str | None = None
    tool_groups: list[str] | None = None
    # skills controls which skills are loaded into the agent's prompt:
    # - None (or omitted): load all enabled skills (default fallback behavior)
    # - [] (explicit empty list): disable all skills
    # - ["skill1", "skill2"]: load only the specified skills
    skills: list[str] | None = None
    owner: str = "public"


def load_agent_config(user_id: str = "public", name: str | None = None) -> AgentConfig | None:
    """Load the custom or default agent's config from its directory.

    Args:
        name: The agent name.

    Returns:
        AgentConfig instance.

    Raises:
        FileNotFoundError: If the agent directory or config.yaml does not exist.
        ValueError: If config.yaml cannot be parsed.
    """

    # Backward compatibility: historical call pattern was load_agent_config(name)
    # with no explicit user_id. If only one positional argument is provided,
    # treat it as the agent name under the public namespace.
    if name is None and user_id != "public":
        name = user_id
        user_id = "public"

    if name is None:
        return None

    if not AGENT_NAME_PATTERN.match(name):
        raise ValueError(f"Invalid agent name '{name}'. Must match pattern: {AGENT_NAME_PATTERN.pattern}")
    agent_dir = get_paths().agent_dir(user_id, name)
    owner = user_id

    # Backward compatibility: older layouts stored shared agents directly under
    # ``agents/<name>`` instead of ``agents/public/<name>``.
    if user_id == "public" and not agent_dir.exists():
        legacy_agent_dir = get_paths().agent_dir(name)
        if legacy_agent_dir.exists():
            agent_dir = legacy_agent_dir

    if not agent_dir.exists():
        agent_dir = get_paths().agent_dir("public", name)
        owner = "public"
        if not agent_dir.exists():
            legacy_agent_dir = get_paths().agent_dir(name)
            if legacy_agent_dir.exists():
                agent_dir = legacy_agent_dir

    if not agent_dir.exists():
        raise FileNotFoundError(f"Agent directory not found: {agent_dir}")

    config_file = agent_dir / "config.yaml"
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

    if "owner" not in data:
        data["owner"] = owner
    # Strip unknown fields before passing to Pydantic (e.g. legacy prompt_file)
    known_fields = set(AgentConfig.model_fields.keys())
    data = {k: v for k, v in data.items() if k in known_fields}

    

    return AgentConfig(**data)


def load_agent_soul(user_id: str | None, agent_name: str | None = None) -> str | None:
    """Read the SOUL.md file for a custom agent, if it exists.

    SOUL.md defines the agent's personality, values, and behavioral guardrails.
    It is injected into the lead agent's system prompt as additional context.

    Args:
        agent_name: The name of the agent or None for the default agent.

    Returns:
        The SOUL.md content as a string, or None if the file does not exist.
    """
    # Backward compatibility: historical call pattern was load_agent_soul(agent_name)
    # with no explicit user_id.
    if agent_name is None and user_id is not None:
        agent_name = user_id
        user_id = "public"

    if agent_name:
        agent_dir = get_paths().agent_dir(user_id or "public", agent_name)
        if (user_id or "public") == "public" and not agent_dir.exists():
            legacy_agent_dir = get_paths().agent_dir(agent_name)
            if legacy_agent_dir.exists():
                agent_dir = legacy_agent_dir
    else:
        agent_dir = get_paths().base_dir
    soul_path = agent_dir / SOUL_FILENAME
    if not soul_path.exists():
        return None
    content = soul_path.read_text(encoding="utf-8").strip()
    return content or None


def list_custom_agents(user_id: str = "public") -> list[AgentConfig]:
    """Scan the agents directory and return all valid custom agents.

    Returns:
        List of AgentConfig for each valid agent directory found.
    """
    agents_dir = get_paths().agents_dir

    if not agents_dir.exists():
        return []

    agents: list[AgentConfig] = []
    seen: set[tuple[str, str]] = set()

    # agents下public、user_id。文件目录下是agent_name
    for category in ["public", user_id]:
        category_path = agents_dir / category
        if not category_path.is_dir():
            continue
        logger.info(f"category_path:{category_path}")
        for entry in sorted(category_path.iterdir()):
            if not entry.is_dir():
                continue

            config_file = entry / "config.yaml"
            if not config_file.exists():
                logger.debug(f"Skipping {entry.name}: no config.yaml")
                continue
            try:
                agent_cfg = load_agent_config(category, entry.name)
                key = (agent_cfg.owner, agent_cfg.name)
                if key not in seen:
                    agents.append(agent_cfg)
                    seen.add(key)
            except Exception as e:
                logger.warning(f"Skipping agent '{entry.name}': {e}")

    # Backward compatibility: historical shared agents lived directly under
    # ``agents/<name>`` instead of ``agents/public/<name>``.
    for entry in sorted(agents_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in {"public", user_id}:
            continue
        config_file = entry / "config.yaml"
        if not config_file.exists():
            continue
        try:
            agent_cfg = load_agent_config("public", entry.name)
            key = (agent_cfg.owner, agent_cfg.name)
            if key not in seen:
                agents.append(agent_cfg)
                seen.add(key)
        except Exception as e:
            logger.warning(f"Skipping legacy agent '{entry.name}': {e}")

    return agents
