"""Configuration for the subagent result-verification layers."""

from pydantic import BaseModel, Field


class VerificationConfig(BaseModel):
    """Receipt ledger, acceptance checklist, and selective judge settings."""

    receipts_enabled: bool = Field(
        default=True,
        description="Stamp deterministic tool receipts on every tool result",
    )
    judge_enabled: bool = Field(
        default=False,
        description="Run a one-shot small-model review of completed subagent results that carry acceptance criteria",
    )
    judge_model_name: str | None = Field(
        default=None,
        description="Model for the selective judge; falls back to the parent model when unset",
    )
