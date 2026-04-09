"""A2A (Agent-to-Agent) remote agent configuration loaded from config.yaml."""

import logging
from collections.abc import Mapping

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class A2AAgentConfig(BaseModel):
    """Configuration for a single A2A-compatible remote agent."""

    name: str = Field(description="Unique name identifying this remote agent")
    url: str = Field(description="Base URL of the A2A agent server (e.g. http://localhost:8001)")
    description: str = Field(default="", description="Description of the agent's capabilities (shown in tool description)")


class A2AConfig(BaseModel):
    """Configuration for the A2A remote agent integration."""

    enabled: bool = Field(default=False, description="Enable A2A remote agent integration")
    agents: list[A2AAgentConfig] = Field(default_factory=list, description="List of configured A2A remote agents")


_config: A2AConfig | None = None


def get_a2a_config() -> A2AConfig:
    """Get the currently configured A2A config.

    Returns:
        A2AConfig instance. Returns a default (disabled) config if not configured.
    """
    return _config or A2AConfig()


def load_a2a_config_from_dict(config_dict: Mapping[str, object] | None) -> None:
    """Load A2A configuration from a dictionary (typically from config.yaml).

    Args:
        config_dict: A2A config fields, including optional ``agents`` list.
    """
    global _config
    if config_dict is None:
        config_dict = {}
    _config = A2AConfig(**config_dict)
    logger.info("A2A config loaded: enabled=%s, %d agent(s): %s", _config.enabled, len(_config.agents), [a.name for a in _config.agents])
