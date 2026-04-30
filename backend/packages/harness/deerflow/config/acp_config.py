"""ACP (Agent Client Protocol) agent configuration loaded from config.yaml."""

import logging
from collections.abc import Mapping

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


class ACPAgentConfig(BaseModel):
    """Configuration for a single ACP-compatible agent."""

    command: str | None = Field(default=None, description="Command to launch the ACP agent subprocess (required for stdio mode)")
    args: list[str] = Field(default_factory=list, description="Additional command arguments")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables to inject into the agent subprocess. Values starting with $ are resolved from host environment variables.")
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
    url: str | None = Field(default=None, description="Remote ACP service URL (e.g. http://localhost:3020). When set, uses HTTP REST API instead of stdio subprocess.")

    @model_validator(mode="after")
    def _validate_command_or_url(self) -> "ACPAgentConfig":
        if not self.command and not self.url:
            raise ValueError("Either 'command' (for stdio mode) or 'url' (for HTTP mode) must be provided")
        return self


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
