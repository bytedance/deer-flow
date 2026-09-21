"""Configuration for the agent-only Regional LLM Wiki release reader."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class RegionalLlmWikiConfig(BaseModel):
    """Gateway-local, read-only LLM Wiki release configuration."""

    enabled: bool = False
    # This is a path inside the Gateway container, not a sandbox path.  The
    # deployment bind-mounts the maintainer's published parent directory here.
    runtime_root: str = "/mnt/regional-llm-wiki-runtime"
    max_search_results: int = Field(default=5, ge=1, le=10)
    max_page_chars: int = Field(default=24_000, ge=1_000, le=100_000)
    max_evidence_chars: int = Field(default=16_000, ge=1_000, le=100_000)

    @field_validator("runtime_root")
    @classmethod
    def _runtime_root_must_be_absolute(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("/"):
            raise ValueError("regional_llm_wiki.runtime_root must be an absolute Gateway path.")
        return normalized.rstrip("/") or "/"
