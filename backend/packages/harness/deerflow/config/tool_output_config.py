"""Configuration for tool output budget protection."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ToolOutputConfig(BaseModel):
    """Config section for tool-result output budget enforcement.

    When a tool returns more than ``externalize_min_chars`` characters,
    the full output is persisted to disk and replaced with a compact
    preview + file reference.  If disk persistence is unavailable the
    output falls back to head+tail truncation.
    """

    enabled: bool = Field(
        default=True,
        description="Enable the tool output budget middleware.",
    )
    externalize_min_chars: int = Field(
        default=12_000,
        ge=0,
        description="Character threshold to trigger disk externalization. Outputs below this pass through unchanged. Set to 0 to disable externalization (fallback truncation still applies when output exceeds fallback_max_chars).",
    )
    preview_head_chars: int = Field(
        default=2_000,
        ge=0,
        description="Characters to keep from the head of the output in the preview.",
    )
    preview_tail_chars: int = Field(
        default=1_000,
        ge=0,
        description="Characters to keep from the tail of the output in the preview.",
    )
    fallback_max_chars: int = Field(
        default=30_000,
        ge=0,
        description="Maximum characters when disk persistence is unavailable. 0 disables fallback truncation.",
    )
    fallback_head_chars: int = Field(
        default=8_000,
        ge=0,
        description="Head characters for fallback truncation.",
    )
    fallback_tail_chars: int = Field(
        default=3_000,
        ge=0,
        description="Tail characters for fallback truncation.",
    )
    storage_subdir: str = Field(
        default=".tool-results",
        description="Subdirectory under the thread outputs path for persisted tool results.",
    )
    exempt_tools: list[str] = Field(
        default_factory=lambda: ["read_file", "read_file_tool"],
        description="Tool names exempt from budget enforcement (prevents persist→read→persist loops).",
    )
    tool_overrides: dict[str, int] = Field(
        default_factory=dict,
        description="Per-tool externalize_min_chars overrides. Keys are tool names, values are char thresholds. Use 0 to disable externalization for a specific tool.",
    )
