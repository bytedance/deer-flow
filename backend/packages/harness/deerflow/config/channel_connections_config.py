"""Configuration for user-owned IM channel connections."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

ChannelConnectionMode = Literal["local", "private", "public"]
TelegramDeliveryMode = Literal["polling", "webhook"]


class SlackChannelConnectionConfig(BaseModel):
    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    signing_secret: str = ""
    scopes: list[str] = Field(
        default_factory=lambda: [
            "app_mentions:read",
            "chat:write",
            "channels:history",
            "channels:read",
        ]
    )
    event_delivery: str = "http"

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.signing_secret)


class TelegramChannelConnectionConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    bot_username: str = ""
    delivery: TelegramDeliveryMode = "polling"
    webhook_secret: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""

    @property
    def configured(self) -> bool:
        if self.delivery == "webhook":
            return bool(self.bot_token and self.bot_username and self.webhook_secret)
        return bool(self.bot_token and self.bot_username)


class DiscordChannelConnectionConfig(BaseModel):
    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    bot_token: str = ""
    permissions: str = ""
    require_message_content_intent: bool = True

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.bot_token)


class ChannelConnectionsConfig(BaseModel):
    """Top-level config for browser-connectable IM channels."""

    enabled: bool = False
    mode: ChannelConnectionMode = "local"
    public_base_url: str = ""
    encryption_key: str = ""
    slack: SlackChannelConnectionConfig = Field(default_factory=SlackChannelConnectionConfig)
    telegram: TelegramChannelConnectionConfig = Field(default_factory=TelegramChannelConnectionConfig)
    discord: DiscordChannelConnectionConfig = Field(default_factory=DiscordChannelConnectionConfig)

    @model_validator(mode="after")
    def _require_shared_config_when_enabled(self) -> ChannelConnectionsConfig:
        missing: list[str] = []
        if self.enabled and self.mode == "public" and not self.public_base_url:
            missing.append("public_base_url is required when channel_connections.mode is public")
        if missing:
            raise ValueError("; ".join(missing))
        return self

    def provider_status(self, provider: str) -> dict[str, bool]:
        config = getattr(self, provider, None)
        if config is None:
            return {"enabled": False, "configured": False}
        return {
            "enabled": bool(config.enabled),
            "configured": bool(config.configured),
        }
