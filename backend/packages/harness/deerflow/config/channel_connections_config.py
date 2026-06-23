"""Configuration for user-owned IM channel connections."""

from __future__ import annotations

from pydantic import BaseModel, Field


class BindingCodeChannelConnectionConfig(BaseModel):
    enabled: bool = False

    @property
    def configured(self) -> bool:
        return True


class ChannelConnectionsConfig(BaseModel):
    """Top-level config for browser-connectable IM channels."""

    enabled: bool = False
    require_bound_identity: bool = True
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
