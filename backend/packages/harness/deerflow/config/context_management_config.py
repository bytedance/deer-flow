"""Configuration for incremental context management."""

from pydantic import BaseModel, Field


class SnipConfig(BaseModel):
    enabled: bool = Field(default=True, description="Whether to strip low-value context before model calls")
    strip_historical_upload_blocks: bool = Field(
        default=True,
        description="Whether to remove <uploaded_files> bookkeeping from older human turns",
    )


class MicrocompactConfig(BaseModel):
    enabled: bool = Field(default=True, description="Whether to compact old verbose tool results before model calls")
    compactable_tools: list[str] = Field(
        default_factory=lambda: [
            "bash",
            "read_file",
            "web_search",
            "web_fetch",
            "x-reader_read_url",
            "x-reader_read_batch",
        ],
        description="Tool names whose older results can be replaced with placeholders",
    )
    keep_recent_tool_results: int = Field(
        default=2,
        ge=1,
        le=20,
        description="How many recent compactable tool results to preserve verbatim",
    )
    min_content_chars: int = Field(
        default=1200,
        ge=0,
        le=100000,
        description="Minimum content length before a tool result becomes eligible for compaction",
    )


class ToolResultBudgetConfig(BaseModel):
    enabled: bool = Field(default=True, description="Whether to externalize oversized tool outputs before they enter message history")
    externalize_min_chars: int = Field(
        default=12000,
        ge=0,
        le=1000000,
        description="Minimum content length before a tool output is written to thread outputs and replaced with a preview",
    )
    preview_head_chars: int = Field(
        default=2000,
        ge=0,
        le=50000,
        description="How many leading characters to keep in the in-context preview for externalized tool output",
    )
    preview_tail_chars: int = Field(
        default=1000,
        ge=0,
        le=50000,
        description="How many trailing characters to keep in the in-context preview for externalized tool output",
    )
    storage_subdir: str = Field(
        default=".context/tool-results",
        description="Subdirectory under thread outputs used to persist oversized tool outputs",
    )


class SessionStateConfig(BaseModel):
    enabled: bool = Field(default=True, description="Whether to maintain a lightweight execution-state reminder for long sessions")
    collapse_enabled: bool = Field(default=True, description="Whether to collapse older thread history into a compact execution summary before full summarization")
    collapse_when_message_count_at_least: int = Field(
        default=12,
        ge=4,
        le=1000,
        description="Minimum visible message count before older history is collapsed into a compact execution summary",
    )
    keep_recent_messages: int = Field(
        default=6,
        ge=4,
        le=100,
        description="How many recent raw messages to preserve when collapsing older session history",
    )
    max_tool_observations: int = Field(
        default=4,
        ge=0,
        le=20,
        description="Maximum number of older tool observations to preserve in the collapsed summary",
    )
    max_tool_observation_chars: int = Field(
        default=240,
        ge=40,
        le=2000,
        description="Maximum characters kept per tool observation inside the collapsed summary",
    )
    inject_when_message_count_at_least: int = Field(
        default=8,
        ge=1,
        le=500,
        description="Minimum visible message count before injecting the session-state reminder",
    )
    max_goal_chars: int = Field(
        default=600,
        ge=80,
        le=4000,
        description="Maximum characters to keep from the latest user goal in session state",
    )
    max_response_chars: int = Field(
        default=400,
        ge=80,
        le=4000,
        description="Maximum characters to keep from the latest final assistant response in session state",
    )
    max_items: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of todos or artifacts to retain in session state",
    )


class ContextManagementConfig(BaseModel):
    snip: SnipConfig = Field(default_factory=SnipConfig)
    microcompact: MicrocompactConfig = Field(default_factory=MicrocompactConfig)
    tool_result_budget: ToolResultBudgetConfig = Field(default_factory=ToolResultBudgetConfig)
    session_state: SessionStateConfig = Field(default_factory=SessionStateConfig)


_context_management_config: ContextManagementConfig = ContextManagementConfig()


def get_context_management_config() -> ContextManagementConfig:
    return _context_management_config


def set_context_management_config(config: ContextManagementConfig) -> None:
    global _context_management_config
    _context_management_config = config


def load_context_management_config_from_dict(config_dict: dict) -> None:
    global _context_management_config
    _context_management_config = ContextManagementConfig(**config_dict)
