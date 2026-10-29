"""``ChannelService`` treats ``channels.leader_lease`` as settings, not as a provider."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.channels.service import ChannelService, enabled_transport_providers
from deerflow.config.channel_connections_config import ChannelConnectionsConfig
from deerflow.config.channel_leader_lease_config import ChannelLeaderLeaseConfig, ChannelLeaderLeaseConfigError


def test_leader_lease_block_is_stripped_and_exposed():
    service = ChannelService(channels_config={"leader_lease": {"enabled": True, "lease_seconds": 12, "grace_seconds": 3}, "telegram": {"enabled": False}})

    assert service.leader_lease == ChannelLeaderLeaseConfig(enabled=True, lease_seconds=12, grace_seconds=3)
    assert service._config == {"telegram": {"enabled": False}}
    assert "leader_lease" not in service.get_status()["channels"]


def test_missing_block_gives_defaults():
    service = ChannelService(channels_config={})
    assert service.leader_lease == ChannelLeaderLeaseConfig()
    assert service.leader_lease.enabled == "auto"


def test_malformed_block_raises_the_config_error():
    with pytest.raises(ChannelLeaderLeaseConfigError, match="channels.leader_lease"):
        ChannelService(channels_config={"leader_lease": {"lease_seconds": 0}})


def test_from_app_config_strips_the_block(monkeypatch, tmp_path):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    app_config = SimpleNamespace(model_extra={"channels": {"leader_lease": {"enabled": "auto"}, "telegram": {"enabled": False}}})

    service = ChannelService.from_app_config(app_config)

    assert service._config == {"telegram": {"enabled": False}}
    assert service.leader_lease.enabled == "auto"


def test_ensure_ready_channels_ignores_non_provider_keys(caplog):
    """A settings block whose ``enabled`` is truthy must never be started as a channel.

    A dict block that is neither a registered provider nor ``leader_lease`` is
    almost certainly a misspelled provider key, so it is skipped with a warning
    (before the registry guard it reached ``_start_channel`` and logged
    'Unknown channel type'; silence would hide the typo).
    """
    service = ChannelService(channels_config={"telegram": {"enabled": False}})
    # Simulate a later configure/overlay that put non-provider dicts back into the live config.
    service._config["leader_lease"] = {"enabled": "auto"}
    service._config["telegam"] = {"enabled": True, "bot_token": "x"}
    service._config["disabled_typo"] = {"enabled": False}
    service._running = True
    try:
        with caplog.at_level("WARNING", logger="app.channels.service"):
            ready = asyncio.run(service.ensure_ready_channels())
    finally:
        service._running = False
    assert ready == {}
    warnings = [record.message for record in caplog.records if record.levelname == "WARNING"]
    assert len(warnings) == 1, warnings
    assert warnings[0].startswith("Ignoring channels.telegam:")
    assert "telegram" in warnings[0]  # the registry is listed so the operator sees the right spelling
    assert "leader_lease" not in "\n".join(warnings)


def _app_config(*, channels=None, connections=None):
    config = SimpleNamespace(model_extra={"channels": channels} if channels is not None else {})
    if connections is not None:
        config.channel_connections = ChannelConnectionsConfig.model_validate(connections)
    return config


def test_enabled_transport_providers_reads_config_yaml_channels():
    channels = {
        "langgraph_url": "http://gw:8001/api",
        "session": {"assistant_id": "lead_agent"},
        "leader_lease": {"enabled": "auto"},
        "telegram": {"enabled": True, "bot_token": "x"},
        "slack": {"enabled": False, "bot_token": "y"},
        "discord": {"enabled": True},
        "github": {"enabled": True},
    }
    assert enabled_transport_providers(_app_config(channels=channels)) == ["discord", "telegram"]


def test_enabled_transport_providers_includes_ui_connectable_providers():
    connections = {"enabled": True, "telegram": {"enabled": True, "bot_username": "bot"}, "feishu": {"enabled": True}, "slack": {"enabled": False}}
    assert enabled_transport_providers(_app_config(connections=connections)) == ["feishu", "telegram"]
    # The master switch off: nothing can be connected from the UI.
    connections["enabled"] = False
    assert enabled_transport_providers(_app_config(connections=connections)) == []


def test_enabled_transport_providers_merges_both_sources_and_tolerates_doubles():
    config = _app_config(channels={"discord": {"enabled": True}}, connections={"enabled": True, "telegram": {"enabled": True}})
    assert enabled_transport_providers(config) == ["discord", "telegram"]
    assert enabled_transport_providers(SimpleNamespace()) == []
    assert enabled_transport_providers(SimpleNamespace(model_extra=None)) == []
