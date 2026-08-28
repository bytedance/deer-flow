"""Configuration for the subagent result-verification layers."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class VerificationConfig(BaseModel):
    """Receipt-ledger settings for subagent result verification.

    Acceptance-criteria parsing and selective judging are not implemented yet.
    Their config fields are retained as a forward-compatible, fail-closed
    placeholder so an operator cannot mistakenly believe a judge ran.
    """

    receipts_enabled: bool = Field(
        default=True,
        description="Stamp deterministic tool receipts on every tool result",
    )
    receipts_render_mode: Literal["always", "delegation_only"] = Field(
        default="delegation_only",
        description="Receipt-ledger rendering for the lead chain; subagent chains always render (citations are produced there). 'delegation_only' renders only while processing subagent results",
    )
    judge_enabled: bool = Field(
        default=False,
        description="Reserved for the future selective judge; enabling it is rejected until that layer is implemented",
    )
    judge_model_name: str | None = Field(
        default=None,
        description="Reserved model name for the future selective judge",
    )

    @model_validator(mode="after")
    def reject_unimplemented_judge(self) -> "VerificationConfig":
        if self.judge_enabled:
            raise ValueError("verification.judge_enabled is reserved for a future implementation and must remain false")
        if self.judge_model_name is not None:
            raise ValueError("verification.judge_model_name is reserved for a future implementation and must remain null")
        return self
