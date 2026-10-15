"""Configuration for user-owned IM channel connections."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Languages scheduled-task IM notices are rendered in (the web UI's languages).
NotificationLocale = Literal["en-US", "zh-CN"]


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
    # Language of scheduled-task IM notices for an owner who has no UI language
    # preference (auth disabled, or never signed in to the web app). The owner's
    # own preference, which the web app keeps in sync with its UI language, wins.
    notification_locale: NotificationLocale = "en-US"
    slack: SlackChannelConnectionConfig = Field(default_factory=SlackChannelConnectionConfig)
    telegram: TelegramChannelConnectionConfig = Field(default_factory=TelegramChannelConnectionConfig)
    discord: DiscordChannelConnectionConfig = Field(default_factory=DiscordChannelConnectionConfig)
    feishu: BindingCodeChannelConnectionConfig = Field(default_factory=BindingCodeChannelConnectionConfig)
    dingtalk: BindingCodeChannelConnectionConfig = Field(default_factory=BindingCodeChannelConnectionConfig)
    wechat: BindingCodeChannelConnectionConfig = Field(default_factory=BindingCodeChannelConnectionConfig)
    wecom: BindingCodeChannelConnectionConfig = Field(default_factory=BindingCodeChannelConnectionConfig)
    buzz: BindingCodeChannelConnectionConfig = Field(default_factory=BindingCodeChannelConnectionConfig)
    qq: BindingCodeChannelConnectionConfig = Field(default_factory=BindingCodeChannelConnectionConfig)

    def provider_status(self, provider: str) -> dict[str, bool]:
        config = getattr(self, provider, None)
        if config is None:
            return {"enabled": False, "configured": False}
        enabled = bool(config.enabled)
        return {
            "enabled": enabled,
            "configured": enabled and bool(config.configured),
        }
