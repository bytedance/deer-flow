from pydantic import BaseModel, Field


class McpTasksConfig(BaseModel):
    """Startup configuration for the protocol-neutral MCP task poller."""

    enabled: bool = Field(default=False)
    poll_interval_seconds: int = Field(default=5, ge=1, le=300)
    lease_seconds: int = Field(default=120, ge=5, le=3600)
    max_concurrent_polls: int = Field(default=8, ge=1, le=64)
