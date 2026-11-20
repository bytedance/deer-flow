from pydantic import BaseModel, Field


class McpTasksConfig(BaseModel):
    """Startup configuration for the protocol-neutral MCP task poller."""

    enabled: bool = Field(default=False)
    poll_interval_seconds: int = Field(default=5, ge=1, le=300)
    lease_seconds: int = Field(default=120, ge=5, le=3600)
    max_concurrent_polls: int = Field(default=8, ge=1, le=64)
    max_poll_backoff_seconds: int = Field(default=300, ge=1, le=3600)
    input_required_poll_interval_seconds: int = Field(default=60, ge=5, le=3600)
    tracking_degraded_after_errors: int = Field(default=3, ge=1, le=100)
    max_result_bytes: int = Field(default=65_536, ge=1024, le=10_485_760)
    result_preview_max_chars: int = Field(default=2_000, ge=64, le=100_000)
