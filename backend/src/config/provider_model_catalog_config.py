from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SUPPORTED_PROVIDER_IDS = {
    "openai",
    "anthropic",
    "gemini",
    "deepseek",
    "kimi",
    "zai",
    "minimax",
    "epfl-rcp",
}

ThinkingEffort = Literal["low", "medium", "high", "xhigh", "max"]


class AdaptiveThinkingConfig(BaseModel):
    """Adaptive thinking support and allowed effort levels for a model."""

    efforts: list[ThinkingEffort] = Field(default_factory=list, description="Allowed adaptive thinking efforts for this model")
    default_effort: ThinkingEffort = Field(default="medium", description="Default adaptive thinking effort")
    model_config = ConfigDict(extra="forbid")

    @field_validator("efforts")
    @classmethod
    def _validate_efforts(cls, value: list[ThinkingEffort]) -> list[ThinkingEffort]:
        if not value:
            raise ValueError("adaptive_thinking.efforts must contain at least one effort.")
        # De-duplicate while preserving the original ordering.
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _validate_default(self) -> "AdaptiveThinkingConfig":
        if self.default_effort not in self.efforts:
            raise ValueError("adaptive_thinking.default_effort must be one of adaptive_thinking.efforts.")
        return self


class ProviderModelCatalogEntry(BaseModel):
    """A single model option shown in the provider model selector."""

    model_id: str = Field(..., min_length=1, description="Provider model identifier")
    display_name: str | None = Field(default=None, description="Display name for UI")
    description: str | None = Field(default=None, description="Optional description for UI")
    supports_vision: bool = Field(default=False, description="Whether this model supports vision/image inputs")
    thinking_enabled: bool = Field(default=False, description="Whether thinking is always enabled for this model")
    adaptive_thinking: AdaptiveThinkingConfig | None = Field(default=None, description="Adaptive thinking capability (if supported)")
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_thinking_capabilities(self) -> "ProviderModelCatalogEntry":
        # Models with adaptive thinking are always thinking-enabled.
        if self.adaptive_thinking is not None and not self.thinking_enabled:
            self.thinking_enabled = True
        return self


class ProviderCatalogEntry(BaseModel):
    """Provider-level model catalog configuration."""

    id: str = Field(..., description="Provider identifier")
    display_name: str | None = Field(default=None, description="Provider display name")
    description: str | None = Field(default=None, description="Provider description")
    enabled_by_default: bool = Field(default=False, description="Whether this provider is enabled in UI by default")
    requires_api_key: bool = Field(default=True, description="Whether using this provider requires an API key")
    models: list[ProviderModelCatalogEntry] = Field(default_factory=list, description="Allowed models for this provider")
    model_config = ConfigDict(extra="forbid")

    @field_validator("id")
    @classmethod
    def _validate_provider_id(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_PROVIDER_IDS:
            raise ValueError(f"Unsupported provider id '{value}'.")
        return normalized


class ProviderModelCatalogConfig(BaseModel):
    """Top-level provider model catalog section in config.yaml."""

    providers: list[ProviderCatalogEntry] = Field(default_factory=list, description="Allowed providers and model options for runtime selection")
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_unique_provider_ids(self) -> "ProviderModelCatalogConfig":
        provider_ids = [provider.id for provider in self.providers]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("provider_models.providers contains duplicate provider ids.")
        return self

    def get_provider(self, provider_id: str) -> ProviderCatalogEntry | None:
        normalized = provider_id.strip().lower()
        return next((provider for provider in self.providers if provider.id == normalized), None)

