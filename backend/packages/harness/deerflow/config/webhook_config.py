"""Webhook configuration — URLs, signing, and retry settings."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WebhookConfig(BaseModel):
    enabled: bool = Field(default=False, description="Enable webhook event delivery")
    signing_secret: str = Field(default="", description="HMAC-SHA256 signing secret")
    max_retries: int = Field(default=3, ge=1, le=10, description="Max delivery retries")
    timeout_seconds: float = Field(default=10.0, description="HTTP request timeout in seconds")
    urls: list[str] = Field(default_factory=list, description="Webhook endpoint URLs")


_webhook_config: WebhookConfig | None = None


def get_webhook_config() -> WebhookConfig:
    global _webhook_config
    if _webhook_config is None:
        _webhook_config = WebhookConfig()
    return _webhook_config


def load_webhook_config_from_dict(data: dict) -> WebhookConfig:
    global _webhook_config
    _webhook_config = WebhookConfig.model_validate(data)
    return _webhook_config


def reset_webhook_config() -> None:
    global _webhook_config
    _webhook_config = None
