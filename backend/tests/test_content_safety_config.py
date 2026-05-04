"""Tests for ContentSafetyConfig singleton pattern and defaults."""

import pytest

from deerflow.config.content_safety_config import (
    ContentSafetyConfig,
    get_content_safety_config,
    load_content_safety_config_from_dict,
    reset_content_safety_config,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_content_safety_config()
    yield
    reset_content_safety_config()


class TestContentSafetyConfigDefaults:
    def test_default_disabled(self):
        cfg = get_content_safety_config()
        assert cfg.enabled is False

    def test_default_input_guard_enabled(self):
        cfg = get_content_safety_config()
        assert cfg.input_guard.enabled is True
        assert cfg.input_guard.block_on_harmful is True
        assert "hate" in cfg.input_guard.categories

    def test_default_output_guard_enabled(self):
        cfg = get_content_safety_config()
        assert cfg.output_guard.enabled is True
        assert cfg.output_guard.pii_detection is True
        assert cfg.output_guard.pii_action == "mask"

    def test_default_provider_is_none(self):
        cfg = get_content_safety_config()
        assert cfg.provider is None


class TestContentSafetyConfigLoad:
    def test_load_enables_content_safety(self):
        load_content_safety_config_from_dict({
            "enabled": True,
            "input_guard": {"enabled": True, "block_on_harmful": False, "categories": ["hate"], "prompt_injection_detection": False},
            "output_guard": {"enabled": False, "pii_detection": False, "pii_action": "pass", "block_on_harmful": False},
            "provider": {"use": "some.module:Provider", "config": {"key": "val"}},
        })
        cfg = get_content_safety_config()
        assert cfg.enabled is True
        assert cfg.input_guard.block_on_harmful is False
        assert cfg.output_guard.enabled is False
        assert cfg.provider is not None
        assert cfg.provider.use == "some.module:Provider"

    def test_singleton_persists(self):
        load_content_safety_config_from_dict({"enabled": True})
        assert get_content_safety_config().enabled is True

    def test_reset_clears_singleton(self):
        load_content_safety_config_from_dict({"enabled": True})
        reset_content_safety_config()
        assert get_content_safety_config().enabled is False
