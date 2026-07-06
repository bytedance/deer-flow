"""Configuration for user-owned IM channel connections."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SlackChannelConnectionConfig(BaseModel):
    enabled: bool = False

    @property
    def configured(self) -> bool:
        return True


class TelegramChannelConnectionConfig(BaseModel):
    enabled: bool = False
    bot_username: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.bot_username)


class DiscordChannelConnectionConfig(BaseModel):
    enabled: bool = False

    @property
    def configured(self) -> bool:
        return True


class BindingCodeChannelConnectionConfig(BaseModel):
    enabled: bool = False

    @property
    def configured(self) -> bool:
        return True


class ChannelConnectionsConfig(BaseModel):
    """Top-level config for browser-connectable IM channels."""

    enabled: bool = False
    require_bound_identity: bool = True
    slack: SlackChannelConnectionConfig = Field(default_factory=SlackChannelConnectionConfig)
    telegram: TelegramChannelConnectionConfig = Field(default_factory=TelegramChannelConnectionConfig)
    discord: DiscordChannelConnectionConfig = Field(default_factory=DiscordChannelConnectionConfig)
    feishu: BindingCodeChannelConnectionConfig = Field(default_factory=BindingCodeChannelConnectionConfig)
    dingtalk: BindingCodeChannelConnectionConfig = Field(default_factory=BindingCodeChannelConnectionConfig)
    wechat: BindingCodeChannelConnectionConfig = Field(default_factory=BindingCodeChannelConnectionConfig)
    wecom: BindingCodeChannelConnectionConfig = Field(default_factory=BindingCodeChannelConnectionConfig)

    def provider_status(self, provider: str) -> dict[str, bool]:
        config = getattr(self, provider, None)
        if config is None:
            return {"enabled": False, "configured": False}
        enabled = bool(config.enabled)
        return {
            "enabled": enabled,
            "configured": enabled and bool(config.configured),
        }
