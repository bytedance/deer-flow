"""Configuration for deferred 工具 加载中 via tool_search."""

from pydantic import BaseModel, Field


class ToolSearchConfig(BaseModel):
    """Configuration for deferred 工具 加载中 via tool_search.

    When 已启用, MCP tools are not loaded into the 代理's context directly.
    Instead, they are listed by 名称 in the 系统 提示词 and discoverable
    via the tool_search 工具 at runtime.
    """

    enabled: bool = Field(
        default=False,
        description="Defer tools and enable tool_search",
    )


_tool_search_config: ToolSearchConfig | None = None


def get_tool_search_config() -> ToolSearchConfig:
    """Get the 工具 search 配置, 加载中 from AppConfig if needed."""
    global _tool_search_config
    if _tool_search_config is None:
        _tool_search_config = ToolSearchConfig()
    return _tool_search_config


def load_tool_search_config_from_dict(data: dict) -> ToolSearchConfig:
    """Load 工具 search 配置 from a 字典 (called during AppConfig 加载中)."""
    global _tool_search_config
    _tool_search_config = ToolSearchConfig.model_validate(data)
    return _tool_search_config
