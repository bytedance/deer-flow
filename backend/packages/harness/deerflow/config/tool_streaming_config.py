"""Configuration for tool execution lifecycle streaming middleware."""

from pydantic import BaseModel, Field


class ToolStreamingConfig(BaseModel):
    """Config section for tool output streaming.

    When enabled, the ToolStreamingMiddleware emits ``tool_output_chunk`` custom
    stream events before and after each tool execution. Tools may also emit
    intermediate chunks through ``langgraph.config.get_stream_writer()``; the
    built-in tools currently provide lifecycle status only.
    """

    enabled: bool = Field(
        default=False,
        description="Enable tool execution lifecycle events on the custom stream.",
    )
