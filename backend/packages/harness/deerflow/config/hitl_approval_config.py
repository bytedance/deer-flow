"""Configuration for the HITL tool-approval middleware."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class HitlApprovalConfig(BaseModel):
    """Operator-owned policy for runtime tool approval and independent review."""

    enabled: bool = Field(
        default=False,
        description="Enable runtime approval of selected and unknown tools",
    )
    tools: list[str] = Field(
        default_factory=list,
        description="Explicitly review these tools, including trusted read tools",
    )
    non_interactive: Literal["deny", "allow"] = Field(
        default="deny",
        description="Legacy Ask-mode unattended override; Auto uncertainty and child runs still fail closed",
    )
    max_actions: int = Field(
        default=32,
        ge=0,
        description="Maximum matching tool calls included in one approval batch; 0 disables the count limit",
    )
    default_mode: Literal["ask", "auto", "full"] = "ask"
    allowed_modes: list[Literal["ask", "auto", "full"]] = Field(default_factory=lambda: ["ask", "auto"])
    review_unknown_tools: bool = Field(default=True, description="Review unknown, extension and MCP tools, ignoring remote read-only hints")
    allow_tools: list[str] = Field(default_factory=list, description="Operator-approved tool names; mandatory authorization still applies")
    deny_tools: list[str] = Field(default_factory=list, description="Always block these tools, including in Full mode")
    always_ask_tools: list[str] = Field(default_factory=list, description="Require a human in every mode; unavailable in unattended runs")
    reviewer_model: str | None = Field(default=None, description="Model profile for a separate approval call; null reuses the execution model")
    reviewer_timeout_seconds: float = Field(default=30, gt=0, le=120, allow_inf_nan=False)
    reviewer_max_input_bytes: int = Field(default=64 * 1024, ge=1024, le=512 * 1024)
    max_payload_bytes: int = Field(default=512 * 1024, ge=1024, le=2 * 1024 * 1024)
    child_approval_timeout_seconds: float = Field(default=300, gt=0, le=3600, allow_inf_nan=False)

    @model_validator(mode="after")
    def _validate_policy(self):
        if not self.allowed_modes or len(set(self.allowed_modes)) != len(self.allowed_modes) or self.default_mode not in self.allowed_modes:
            raise ValueError("hitl_approval.default_mode must belong to a non-empty, unique allowed_modes list")
        for names in (self.allow_tools, self.deny_tools, self.always_ask_tools):
            self._validate_tool_names(names)
        if set(self.allow_tools) & (set(self.deny_tools) | set(self.always_ask_tools)):
            raise ValueError("hitl_approval allow rules conflict with mandatory deny/ask rules")
        return self

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
