from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

_DEFAULT_MAX_CONTENT_CHARS = 8196


def get_max_content_chars(tool_name: str = "web_fetch") -> int:
    """Read ``max_content_chars`` from the tool config in *config.yaml*.

    The value is read from the tool entry in the top-level ``tools`` list
    whose ``name`` equals ``tool_name``, using its ``max_content_chars`` field.
    Falls back to 16 384 when the field is absent, the tool is not configured,
    or the stored value cannot be converted to a positive integer.
    """
    from .app_config import get_app_config

    config = get_app_config().get_tool_config(tool_name)
    extra = (config.model_extra or {}) if config is not None else {}
    if "max_content_chars" in extra:
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
        description="Variable name of the tool provider(e.g. deerflow.sandbox.tools:bash_tool)",
    )
    model_config = ConfigDict(extra="allow")
