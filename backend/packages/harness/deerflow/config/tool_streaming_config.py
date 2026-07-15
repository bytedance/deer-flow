"""Configuration for real-time tool output streaming middleware."""

from pydantic import BaseModel, Field


class ToolStreamingConfig(BaseModel):
    """Config section for tool output streaming.

    When enabled, the ToolStreamingMiddleware emits ``tool_output_chunk`` custom
    stream events before and after each tool execution.  Tools that support
    streaming (e.g. bash) can emit intermediate chunks via
    ``langgraph.config.get_stream_writer()`` during execution so the frontend
    renders partial results in real-time instead of waiting for the full result.
    """

    enabled: bool = Field(
        default=False,
        description="Enable real-time tool output streaming via custom stream events.",
    )
