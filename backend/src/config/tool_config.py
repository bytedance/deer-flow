from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

_DEFAULT_MAX_CONTENT_CHARS = 8192


def get_max_content_chars(tool_name: str = "web_fetch") -> int:
    """Read ``max_content_chars`` from the tool config in config.yaml.

    Falls back to 8 192 when the key is absent or the tool is not configured.
    """
    from .app_config import get_app_config

    config = get_app_config().get_tool_config(tool_name)
    extra = config.model_extra if config is not None else None
    if extra and "max_content_chars" in extra:
        try:
            value = int(extra["max_content_chars"])
            return max(value, 1)
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
