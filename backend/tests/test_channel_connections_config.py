"""Tests for user-facing IM channel connection configuration."""

import pytest
from pydantic import ValidationError

from deerflow.config.channel_connections_config import ChannelConnectionsConfig


def test_channel_connections_disabled_by_default():
    config = ChannelConnectionsConfig()

    assert config.enabled is False
    assert config.public_base_url == ""
    assert config.encryption_key == ""
    assert config.slack.enabled is False
    assert config.telegram.enabled is False
    assert config.discord.enabled is False


def test_enabled_channel_connections_can_run_in_local_mode_without_public_url_or_encryption_key():
    config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "mode": "local",
            "telegram": {
                "enabled": True,
                "bot_token": "telegram-token",
                "bot_username": "deerflow_bot",
            },
        }
    )

    assert config.public_base_url == ""
    assert config.encryption_key == ""
    assert config.provider_status("telegram") == {"enabled": True, "configured": True}


def test_public_mode_requires_public_url():
    with pytest.raises(ValidationError) as excinfo:
        ChannelConnectionsConfig.model_validate(
            {
                "enabled": True,
                "mode": "public",
                "encryption_key": "test-secret",
            }
        )

    assert "public_base_url is required when channel_connections.mode is public" in str(excinfo.value)


def test_provider_config_completeness_is_reported_without_crashing():
    config = ChannelConnectionsConfig.model_validate(
        {
            "enabled": True,
            "public_base_url": "https://deerflow.example.com",
            "encryption_key": "test-secret",
            "slack": {
                "enabled": True,
                "client_id": "slack-client",
                "client_secret": "slack-secret",
                "signing_secret": "slack-signing",
            },
            "telegram": {
                "enabled": True,
                "bot_token": "telegram-token",
                "bot_username": "deerflow_bot",
                "webhook_secret": "telegram-webhook",
            },
            "discord": {"enabled": True, "client_id": "discord-client"},
        }
    )

    assert config.provider_status("slack") == {"enabled": True, "configured": True}
    assert config.provider_status("telegram") == {"enabled": True, "configured": True}
    assert config.provider_status("discord") == {"enabled": True, "configured": False}
    assert config.provider_status("unknown") == {"enabled": False, "configured": False}
