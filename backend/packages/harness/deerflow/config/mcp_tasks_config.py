from pydantic import BaseModel, Field, ValidationInfo, field_validator

from deerflow.config._boolean_guards import reject_boolean


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

    @field_validator(
        "poll_interval_seconds",
        "lease_seconds",
        "max_concurrent_polls",
        "max_poll_backoff_seconds",
        "input_required_poll_interval_seconds",
        "tracking_degraded_after_errors",
        "max_result_bytes",
        "result_preview_max_chars",
        mode="before",
    )
    @classmethod
    def _reject_boolean_mcp_task_integers(cls, value: object, info: ValidationInfo) -> object:
        return reject_boolean(value, info, kind="an integer")
