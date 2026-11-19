"""Tests for user-facing IM channel connection configuration."""

import pytest
from pydantic import ValidationError

from deerflow.config.channel_connections_config import ChannelConnectionsConfig


def test_channel_connections_disabled_by_default():
    config = ChannelConnectionsConfig()

    assert config.enabled is False
    assert config.require_bound_identity is True
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


def test_require_bound_identity_can_be_disabled_for_legacy_open_bot_mode():
    config = ChannelConnectionsConfig.model_validate({"enabled": True, "require_bound_identity": False})

    assert config.enabled is True
    assert config.require_bound_identity is False


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


def test_qq_connection_configuration_is_opt_in():
    assert ChannelConnectionsConfig().provider_status("qq") == {
        "enabled": False,
        "configured": False,
    }
    configured = ChannelConnectionsConfig.model_validate({"enabled": True, "qq": {"enabled": True}})
    assert configured.provider_status("qq") == {"enabled": True, "configured": True}
    assert configured.require_bound_identity is True


def test_notification_locale_defaults_to_english():
    assert ChannelConnectionsConfig().notification_locale == "en-US"
    assert ChannelConnectionsConfig.model_validate({"notification_locale": "zh-CN"}).notification_locale == "zh-CN"


@pytest.mark.parametrize("value", ["fr-FR", "zh", "en", "", None, 1])
def test_notification_locale_accepts_only_the_ui_languages(value):
    with pytest.raises(ValidationError):
        ChannelConnectionsConfig.model_validate({"notification_locale": value})
