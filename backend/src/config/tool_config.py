from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

_DEFAULT_MAX_CONTENT_CHARS = 16384


def get_max_content_chars(tool_name: str = "web_fetch") -> int:
    """Read ``max_content_chars`` from the tool config in config.yaml.

    Falls back to 16 384 when the key is absent or the tool is not configured.
    """
    from .app_config import get_app_config

    config = get_app_config().get_tool_config(tool_name)
    if config is not None and "max_content_chars" in config.model_extra:
        try:
            return int(config.model_extra["max_content_chars"])
        except (ValueError, TypeError):
            return _DEFAULT_MAX_CONTENT_CHARS
    return _DEFAULT_MAX_CONTENT_CHARS


class ToolGroupConfig(BaseModel):
    """Config section for a tool group"""

    name: str = Field(..., description="Unique name for the tool group")
    model_config = ConfigDict(extra="allow")


class ToolConfig(BaseModel):
    """Config section for a tool"""

    name: str = Field(..., description="Unique name for the tool")
    group: str = Field(..., description="Group name for the tool")
    use: str = Field(
        ...,
        description="Variable name of the tool provider(e.g. src.sandbox.tools:bash_tool)",
    )
    model_config = ConfigDict(extra="allow")
