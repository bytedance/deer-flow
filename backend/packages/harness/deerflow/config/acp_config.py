"""ACP (Agent Client Protocol) agent configuration loaded from config.yaml."""

import logging
from collections.abc import Mapping

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ACPAgentConfig(BaseModel):
    """Configuration for a single ACP-compatible agent."""

    command: str = Field(description="Command to launch the ACP agent subprocess")
    args: list[str] = Field(default_factory=list, description="Additional command arguments")
    description: str = Field(description="Description of the agent's capabilities (shown in tool description)")
    model: str | None = Field(default=None, description="Model hint passed to the agent (optional)")
    auto_approve_permissions: bool = Field(
        default=False,
        description=(
            "When True, DeerFlow automatically approves all ACP permission requests from this agent "
            "(allow_once preferred over allow_always). When False (default), all permission requests "
            "are denied — the agent must be configured to operate without requesting permissions."
        ),
    )


_acp_agents: dict[str, ACPAgentConfig] = {}


def get_acp_agents() -> dict[str, ACPAgentConfig]:
    """Get the currently configured ACP agents.

    Returns:
        Mapping of agent name -> ACPAgentConfig.  Empty dict if no ACP agents are configured.
    """
    return _acp_agents


def load_acp_config_from_dict(config_dict: Mapping[str, Mapping[str, object]] | None) -> None:
    """Load ACP agent configuration from a dictionary (typically from config.yaml).

    Args:
        config_dict: Mapping of agent name -> config fields.
    """
    global _acp_agents
    if config_dict is None:
        config_dict = {}
    _acp_agents = {name: ACPAgentConfig(**cfg) for name, cfg in config_dict.items()}
    logger.info("ACP config loaded: %d agent(s): %s", len(_acp_agents), list(_acp_agents.keys()))
