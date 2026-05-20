"""ACP (Agent Client Protocol) agent configuration loaded from config.yaml."""

from pydantic import BaseModel, Field


class ACPAgentConfig(BaseModel):
    """Configuration for a single ACP-compatible agent."""

    command: str = Field(description="Command to launch the ACP agent subprocess")
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
