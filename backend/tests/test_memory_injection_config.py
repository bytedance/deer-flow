"""Tests for host-owned memory injection timing controls."""

import pytest

from deerflow.config.memory_config import MemoryConfig


def test_memory_injection_controls_preserve_existing_defaults():
    config = MemoryConfig()

    assert config.injection_enabled is True
    assert config.session_injection_enabled is True
    assert config.turn_injection_enabled is False


@pytest.mark.parametrize(
    ("injection_enabled", "session_enabled", "turn_enabled"),
    [
        pytest.param(False, False, False, id="master-disabled"),
        pytest.param(True, True, False, id="session-only"),
        pytest.param(True, False, True, id="turn-only"),
        pytest.param(True, True, True, id="session-and-turn"),
    ],
)
def test_memory_injection_control_combinations(
    injection_enabled: bool,
    session_enabled: bool,
    turn_enabled: bool,
):
    config = MemoryConfig(
        injection_enabled=injection_enabled,
        session_injection_enabled=session_enabled,
        turn_injection_enabled=turn_enabled,
    )

    assert config.injection_enabled is injection_enabled
    assert config.session_injection_enabled is session_enabled
    assert config.turn_injection_enabled is turn_enabled


def test_memory_injection_rejects_master_enabled_with_no_injection_path():
    with pytest.raises(ValueError, match="injection_enabled"):
        MemoryConfig(
            injection_enabled=True,
            session_injection_enabled=False,
            turn_injection_enabled=False,
        )
