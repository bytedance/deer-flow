"""Tests for user-facing IM channel connection configuration."""

from deerflow.config.channel_connections_config import ChannelConnectionsConfig


def test_channel_connections_disabled_by_default():
    config = ChannelConnectionsConfig()

    assert config.enabled is False
    assert config.slack.enabled is False
    assert config.telegram.enabled is False
    assert config.discord.enabled is False
    assert config.feishu.enabled is False
    assert config.dingtalk.enabled is False
    assert config.wechat.enabled is False
    assert config.wecom.enabled is False


def test_enabled_channel_connections_do_not_require_public_url_or_encryption_key():
    config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "telegram": {
                "enabled": True,
                "bot_username": "deerflow_bot",
            },
            "slack": {"enabled": True},
            "discord": {"enabled": True},
            "feishu": {"enabled": True},
            "dingtalk": {"enabled": True},
            "wechat": {"enabled": True},
            "wecom": {"enabled": True},
        }
    )

    assert config.enabled is True
    assert config.provider_status("telegram") == {"enabled": True, "configured": True}
    assert config.provider_status("slack") == {"enabled": True, "configured": True}
    assert config.provider_status("discord") == {"enabled": True, "configured": True}
    assert config.provider_status("feishu") == {"enabled": True, "configured": True}
    assert config.provider_status("dingtalk") == {"enabled": True, "configured": True}
    assert config.provider_status("wechat") == {"enabled": True, "configured": True}
    assert config.provider_status("wecom") == {"enabled": True, "configured": True}


def test_provider_status_reports_disabled_and_unknown_providers():
    config = ChannelConnectionsConfig.model_validate({"enabled": True})

    assert config.provider_status("slack") == {"enabled": False, "configured": False}
    assert config.provider_status("telegram") == {"enabled": False, "configured": False}
    assert config.provider_status("discord") == {"enabled": False, "configured": False}
    assert config.provider_status("feishu") == {"enabled": False, "configured": False}
    assert config.provider_status("dingtalk") == {"enabled": False, "configured": False}
    assert config.provider_status("wechat") == {"enabled": False, "configured": False}
    assert config.provider_status("wecom") == {"enabled": False, "configured": False}
    assert config.provider_status("unknown") == {"enabled": False, "configured": False}
