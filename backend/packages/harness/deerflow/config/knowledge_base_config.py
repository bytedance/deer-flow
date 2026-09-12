from pydantic import BaseModel, ConfigDict, Field


class KnowledgeBaseConfig(BaseModel):
    """Hot-reloadable DeerFlow knowledge capability settings.

    Provider connection and retrieval options belong to the provider tool
    entry (for example ``tools[].use: ...ragflow...``), not this generic
    capability block.
    """

    model_config = ConfigDict(validate_default=True)

    enabled: bool = Field(default=False)
    scope_selection_enabled: bool = Field(default=False)
