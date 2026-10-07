from pydantic import BaseModel, ConfigDict, Field


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
    # Opt-in tools load only when their group is explicitly listed (e.g. a
    # custom agent's ``tool_groups``); the default lead agent (groups=None)
    # never sees them. Used by the ``rag`` retrieval tool so the general
    # assistant doesn't gain knowledge-base tools by accident.
    opt_in: bool = Field(default=False, description="Load only when the tool's group is explicitly requested")
    model_config = ConfigDict(extra="allow")
