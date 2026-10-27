"""Configuration for deferred tool loading via tool_search."""

from pydantic import BaseModel, Field, field_validator

AUTO_PROMOTE_TOP_K_MIN = 1
AUTO_PROMOTE_TOP_K_MAX = 5


def clamp_auto_promote_top_k(value: int) -> int:
    """Clamp the global MCP routing auto-promote breadth to PR2's range."""
    return max(AUTO_PROMOTE_TOP_K_MIN, min(AUTO_PROMOTE_TOP_K_MAX, int(value)))


class ToolSearchConfig(BaseModel):
    """Configuration for deferred tool loading via tool_search.

    When enabled, MCP tools are not loaded into the agent's context directly.
    Instead, they are listed by name in the system prompt and discoverable
    via the tool_search tool at runtime.
    """

    enabled: bool = Field(
        default=False,
        description="Defer tools and enable tool_search",
    )
    auto_promote_top_k: int = Field(
        default=3,
        description="Maximum number of deferred MCP tool schemas auto-promoted from routing metadata per model call",
    )

    @field_validator("auto_promote_top_k")
    @classmethod
    def _clamp_auto_promote_top_k(cls, value: int) -> int:
        return clamp_auto_promote_top_k(value)


_tool_search_config: ToolSearchConfig | None = None


def get_tool_search_config() -> ToolSearchConfig:
    """Get the tool search config, loading from AppConfig if needed."""
    global _tool_search_config
    if _tool_search_config is None:
        _tool_search_config = ToolSearchConfig()
    return _tool_search_config


def load_tool_search_config_from_dict(data: dict) -> ToolSearchConfig:
    """Load tool search config from a dict (called during AppConfig loading)."""
    global _tool_search_config
    _tool_search_config = ToolSearchConfig.model_validate(data)
    return _tool_search_config
