"""``channels.leader_lease`` configuration model and its reload-boundary registration."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deerflow.config.channel_leader_lease_config import (
    CHANNEL_LEADER_LEASE_FIELD,
    ChannelLeaderLeaseConfig,
    ChannelLeaderLeaseConfigError,
    channel_leader_lease_config,
    channel_leader_lease_from_app_config,
)
from deerflow.config.reload_boundary import STARTUP_ONLY_FIELDS, is_startup_only_field


def test_defaults_are_auto_30_10():
    config = ChannelLeaderLeaseConfig()
    assert config.enabled == "auto"
    assert config.lease_seconds == 30
    assert config.grace_seconds == 10
    assert config.explicitly_disabled is False


@pytest.mark.parametrize(
    ("enabled", "multi_process", "expected"),
    [
        ("auto", False, False),
        ("auto", True, True),
        (True, False, True),
        (True, True, True),
        (False, False, False),
        (False, True, False),
    ],
)
def test_auto_follows_the_multi_process_signal(enabled, multi_process, expected):
    config = ChannelLeaderLeaseConfig(enabled=enabled)
    assert config.resolve(multi_process=multi_process) is expected


def test_only_a_literal_false_counts_as_explicitly_disabled():
    assert ChannelLeaderLeaseConfig(enabled=False).explicitly_disabled is True
    assert ChannelLeaderLeaseConfig(enabled=True).explicitly_disabled is False
    assert ChannelLeaderLeaseConfig(enabled="auto").explicitly_disabled is False


def test_missing_section_and_empty_block_mean_defaults():
    assert channel_leader_lease_config(None) == ChannelLeaderLeaseConfig()
    assert channel_leader_lease_config({}) == ChannelLeaderLeaseConfig()
    assert channel_leader_lease_config({"telegram": {"enabled": True}}) == ChannelLeaderLeaseConfig()
    assert channel_leader_lease_config({"leader_lease": None}) == ChannelLeaderLeaseConfig()
    assert channel_leader_lease_config({"leader_lease": {}}) == ChannelLeaderLeaseConfig()


def test_block_values_are_read():
    config = channel_leader_lease_config({"leader_lease": {"enabled": False, "lease_seconds": 15, "grace_seconds": 0}})
    assert config.enabled is False
    assert config.lease_seconds == 15
    assert config.grace_seconds == 0


@pytest.mark.parametrize(
    ("block", "fragment"),
    [
        ({"enabled": "maybe"}, "enabled"),
        ({"lease_seconds": 0}, "lease_seconds"),
        ({"lease_seconds": 2}, "lease_seconds"),
        ({"grace_seconds": -1}, "grace_seconds"),
        ({"enable": False}, "enable"),  # typo: extra keys are refused, not ignored
    ],
)
def test_invalid_blocks_name_the_dotted_path_and_the_field(block, fragment):
    with pytest.raises(ChannelLeaderLeaseConfigError) as exc_info:
        channel_leader_lease_config({"leader_lease": block})
    message = str(exc_info.value)
    assert CHANNEL_LEADER_LEASE_FIELD in message
    assert fragment in message


def test_non_mapping_block_is_refused():
    with pytest.raises(ChannelLeaderLeaseConfigError, match="must be a mapping"):
        channel_leader_lease_config({"leader_lease": "auto"})


def test_from_app_config_reads_model_extra_and_tolerates_doubles():
    app_config = SimpleNamespace(model_extra={"channels": {"leader_lease": {"enabled": True}}})
    assert channel_leader_lease_from_app_config(app_config).enabled is True
    # SimpleNamespace without model_extra, and an AppConfig-like object with no channels section.
    assert channel_leader_lease_from_app_config(SimpleNamespace()) == ChannelLeaderLeaseConfig()
    assert channel_leader_lease_from_app_config(SimpleNamespace(model_extra={})) == ChannelLeaderLeaseConfig()
    assert channel_leader_lease_from_app_config(SimpleNamespace(model_extra=None)) == ChannelLeaderLeaseConfig()


def test_leader_lease_is_registered_as_startup_only():
    assert is_startup_only_field(CHANNEL_LEADER_LEASE_FIELD)
    reason = STARTUP_ONLY_FIELDS[CHANNEL_LEADER_LEASE_FIELD]
    assert "_enforce_postgres_for_multi_worker" in reason
    assert "ChannelService" in reason
