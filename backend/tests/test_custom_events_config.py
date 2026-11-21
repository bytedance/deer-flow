"""Tests for the ``custom_events`` config section and its tool-streaming guard."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from deerflow.config.app_config import AppConfig


def _app(**sections):
    return AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [{"name": "m", "use": "pkg:Cls", "model": "m"}],
            **sections,
        }
    )


def test_custom_events_is_on_by_default():
    """Turning the channel off by default would drop the existing task_* events."""
    assert _app().custom_events.enabled is True


def test_custom_events_can_be_disabled_alone():
    cfg = _app(custom_events={"enabled": False})

    assert cfg.custom_events.enabled is False


def test_tool_streaming_requires_the_custom_channel():
    """Reject the pair instead of enabling a producer with no subscriber."""
    with pytest.raises(ValidationError) as excinfo:
        _app(tool_streaming={"enabled": True}, custom_events={"enabled": False})

    assert "custom_events.enabled" in str(excinfo.value)


def test_tool_streaming_is_fine_when_the_channel_is_on():
    cfg = _app(tool_streaming={"enabled": True}, custom_events={"enabled": True})

    assert cfg.tool_streaming.enabled is True
    assert cfg.custom_events.enabled is True
