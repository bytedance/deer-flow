"""Content safety configuration — input/output content moderation."""

from __future__ import annotations

from pydantic import BaseModel, Field


class InputGuardConfig(BaseModel):
    """Configuration for input content guard."""

    enabled: bool = Field(default=True, description="Enable input content guard")
    block_on_harmful: bool = Field(default=True, description="Block requests with harmful content")
    categories: list[str] = Field(default_factory=lambda: ["hate", "sexual", "violence", "self-harm", "illegal"], description="Categories to check")
    prompt_injection_detection: bool = Field(default=True, description="Enable prompt injection detection")


class OutputGuardConfig(BaseModel):
    """Configuration for output content guard."""

    enabled: bool = Field(default=True, description="Enable output content guard")
    pii_detection: bool = Field(default=True, description="Enable PII detection in output")
    pii_action: str = Field(default="mask", description="Action for PII: mask, block, or pass")
    block_on_harmful: bool = Field(default=False, description="Block responses with harmful content")


class ContentSafetyProviderConfig(BaseModel):
    """Provider configuration for content safety."""

    use: str = Field(default="", description="Class path to ContentSafetyProvider implementation")
    config: dict = Field(default_factory=dict, description="Provider-specific configuration")


class ContentSafetyConfig(BaseModel):
    """Configuration for content safety (input/output moderation)."""

    enabled: bool = Field(default=False, description="Enable content safety moderation")
    input_guard: InputGuardConfig = Field(default_factory=InputGuardConfig, description="Input guard configuration")
    output_guard: OutputGuardConfig = Field(default_factory=OutputGuardConfig, description="Output guard configuration")
    provider: ContentSafetyProviderConfig | None = Field(default=None, description="Content safety provider configuration")


_content_safety_config: ContentSafetyConfig | None = None


def get_content_safety_config() -> ContentSafetyConfig:
    """Get the current content safety config singleton."""
    global _content_safety_config
    if _content_safety_config is None:
        _content_safety_config = ContentSafetyConfig()
    return _content_safety_config


def load_content_safety_config_from_dict(data: dict) -> ContentSafetyConfig:
    """Load content safety config from a dictionary."""
    global _content_safety_config
    _content_safety_config = ContentSafetyConfig.model_validate(data)
    return _content_safety_config


def reset_content_safety_config() -> None:
    """Reset the content safety config singleton."""
    global _content_safety_config
    _content_safety_config = None
