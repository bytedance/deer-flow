"""Configuration for tool output budget protection."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field, field_validator

from deerflow.constants import TOOL_RESULTS_DIRNAME


class ToolOutputConfig(BaseModel):
    """Config section for tool-result output budget enforcement.

    When a tool returns more than ``externalize_min_chars`` characters,
    the full output is persisted to disk and replaced with a compact
    preview + file reference.  If disk persistence is unavailable the
    output falls back to head+tail truncation.

    The same middleware also budgets the other bulky side of a tool call in
    model-bound requests: the ``content`` argument of a successful
    ``write_file`` call, once a later read or write of the same path has
    made the historical copy redundant with the file on disk
    (``elide_superseded_writes``; issue #5328).
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
        description="Sampling budget retained for compatibility. Typed previews use this with preview_tail_chars only for fallback samples inside the structured synopsis.",
    )
    preview_tail_chars: int = Field(
        default=1_000,
        ge=0,
        description="Sampling budget retained for compatibility. Typed previews use this with preview_head_chars only for fallback samples inside the structured synopsis.",
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
        default=TOOL_RESULTS_DIRNAME,
        description=(
            "Single-segment directory name under the thread outputs path for persisted tool results. "
            "TOOL_RESULTS_DIRNAME is always excluded by the workspace-changes scanner; other custom values are "
            "excluded from workspace snapshots and run delivery verification at capture time."
        ),
    )

    @field_validator("storage_subdir")
    @classmethod
    def _storage_subdir_is_single_segment(cls, value: str) -> str:
        """Require a single directory name (no path separators).

        The workspace-changes scanner prunes by directory name during
        ``os.walk``, which yields one-segment dirnames — a nested value like
        ``cache/tool-results`` would never match the exclusion and its files
        would silently be counted as produced artifacts again. A loud config
        error beats a silent exclusion no-op.
        """
        if value == "" or value in {".", ".."} or os.path.isabs(value):
            raise ValueError("storage_subdir must be a single non-empty directory name")
        if "/" in value or "\\" in value:
            raise ValueError(f"storage_subdir must be a single directory name without path separators (got {value!r})")
        return value

    exempt_tools: list[str] = Field(
        default_factory=lambda: ["read_file", "read_file_tool"],
        description="Tool names exempt from budget enforcement (prevents persist→read→persist loops).",
    )
    tool_overrides: dict[str, int] = Field(
        default_factory=dict,
        description="Per-tool externalize_min_chars overrides. Keys are tool names, values are char thresholds. Use 0 to disable externalization for a specific tool.",
    )
    elide_superseded_writes: bool = Field(
        default=True,
        description=(
            "Replace the content argument of a successful write_file call with a short placeholder in model-bound "
            "requests once the same path was read or modified again later in the conversation. After a successful "
            "write the file on disk is the source of truth, and the read-before-write gate forces a read_file before "
            "the next modification, so the historical copy is redundant with that read. Only the request copy "
            "changes: stored message history, receipts, and the run journal keep the original arguments."
        ),
    )
    superseded_write_min_chars: int = Field(
        default=2000,
        ge=0,
        description=(
            "Elide only write_file content at least this many characters long; shorter content stays visible. "
            "0 elides every non-empty content. This is a Python character count, not a token count: the same value "
            "spans roughly 3-4x in real context cost between ASCII and CJK text, and the placeholder's elided-size "
            "figure is the same character count."
        ),
    )
    keep_recent_writes: int = Field(
        default=1,
        ge=0,
        description="Never elide the content of the newest N successful write_file calls (counted across all paths), even when superseded, so the model can still say what it just wrote without a read. 0 keeps none.",
    )
