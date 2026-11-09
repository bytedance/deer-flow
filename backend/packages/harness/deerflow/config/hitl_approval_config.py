"""Configuration for the HITL tool-approval middleware."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class HitlApprovalConfig(BaseModel):
    """Human-in-the-loop approval for high-risk tool calls.

    The high-risk tool list is a host-owned security policy. Extensions may only
    add entries (never remove them) in later phases; there is no merge logic yet.
    """

    enabled: bool = Field(
        default=False,
        description="Enable approval pauses for tools listed in `tools`",
    )
    tools: list[str] = Field(
        default_factory=list,
        description="Tool names that require human approval before execution",
    )
    non_interactive: Literal["deny", "allow"] = Field(
        default="deny",
        description="Behavior for runs that cannot collect approval (scheduled, IM channels, subagents)",
    )
    max_actions: int = Field(
        default=32,
        ge=0,
        description="Maximum matching tool calls included in one approval batch; 0 disables the count limit",
    )

    @field_validator("tools")
    @classmethod
    def _validate_tool_names(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        for name in value:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("hitl_approval.tools entries must be non-empty strings")
            if name in seen:
                raise ValueError(f"hitl_approval.tools contains duplicate entry {name!r}")
            seen.add(name)
        return value
