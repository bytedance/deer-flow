"""Optional DeerFlow module configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DurableWorkflowsConfig(BaseModel):
    """Durable workflow runtime envelope and observability switches."""

    enabled: bool = Field(default=True, description="Create durable workflow envelopes around run execution.")
    api_enabled: bool = Field(default=True, description="Expose durable workflow read APIs.")
    auto_envelope_for_runs: bool = Field(default=True, description="Automatically bind API-created runs to workflow envelopes.")


class ModulesConfig(BaseModel):
    """Feature gates for optional DeerFlow modules.

    This module is intentionally small in the durable workflow runtime stack.
    Higher-level modules can extend it with their own feature gates later.
    """

    durable_workflows: DurableWorkflowsConfig = Field(default_factory=DurableWorkflowsConfig)
