"""Precedence tests for merge_runtime_channel_configs (pure, no event loop)."""

from __future__ import annotations

from types import SimpleNamespace

from app.channels.runtime_config_store import merge_runtime_channel_configs


def _store(data):
    return SimpleNamespace(load_all=lambda: data)


def test_runtime_config_wins_over_yaml_on_shared_keys():
    # The runtime store holds credentials entered from the UI, which exist so a
    # deployment can configure a channel "without needing a config.yaml edit".
    # When the same provider is also present in config.yaml, the UI value the
    # user just saved must win; the yaml value must not silently override it.
    channels_config = {
        "telegram": {"bot_token": "yaml_token", "webhook_secret": "from_yaml"},
    }
    connections = SimpleNamespace(enabled=True, telegram=SimpleNamespace(enabled=True))
    store = _store({"telegram": {"bot_token": "user_token", "bot_username": "mybot"}})

    merge_runtime_channel_configs(channels_config, connections, store=store)

    merged = channels_config["telegram"]
    # UI-entered value wins on the shared key
    assert merged["bot_token"] == "user_token"
    # runtime-only key is added
    assert merged["bot_username"] == "mybot"
    # yaml-only key the UI never set is preserved
    assert merged["webhook_secret"] == "from_yaml"


def test_runtime_only_provider_is_added():
    channels_config: dict = {}
    connections = SimpleNamespace(enabled=True, telegram=SimpleNamespace(enabled=True))
    store = _store({"telegram": {"bot_token": "user_token"}})

    merge_runtime_channel_configs(channels_config, connections, store=store)

    assert channels_config["telegram"] == {"bot_token": "user_token"}
