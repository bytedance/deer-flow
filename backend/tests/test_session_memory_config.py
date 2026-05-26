"""Unit tests for SessionMemoryConfig."""

from deerflow.config.session_memory_config import (
    SessionMemoryConfig,
    get_session_memory_config,
    load_session_memory_config_from_dict,
    set_session_memory_config,
)


class TestSessionMemoryConfig:
    """Tests for SessionMemoryConfig."""

    def test_defaults(self):
        config = SessionMemoryConfig()
        assert config.enabled is False
        assert config.model_name is None
        assert config.debounce_seconds == 30
        assert config.max_facts == 100
        assert config.fact_confidence_threshold == 0.7
        assert config.injection_enabled is True
        assert config.max_injection_tokens == 2000

    def test_custom_values(self):
        config = SessionMemoryConfig(
            enabled=True,
            model_name="gpt-4",
            debounce_seconds=60,
            max_facts=200,
            fact_confidence_threshold=0.8,
            injection_enabled=False,
            max_injection_tokens=4000,
        )
        assert config.enabled is True
        assert config.model_name == "gpt-4"
        assert config.debounce_seconds == 60
        assert config.max_facts == 200
        assert config.fact_confidence_threshold == 0.8
        assert config.injection_enabled is False
        assert config.max_injection_tokens == 4000

    def test_validation_debounce_seconds_min(self):
        from pydantic import ValidationError
        try:
            SessionMemoryConfig(debounce_seconds=0)
            assert False, "Should have raised"
        except ValidationError:
            pass

    def test_validation_max_facts_min(self):
        from pydantic import ValidationError
        try:
            SessionMemoryConfig(max_facts=5)
            assert False, "Should have raised"
        except ValidationError:
            pass

    def test_validation_confidence_range(self):
        from pydantic import ValidationError
        try:
            SessionMemoryConfig(fact_confidence_threshold=1.5)
            assert False, "Should have raised"
        except ValidationError:
            pass


class TestSessionMemoryConfigFunctions:
    """Tests for get/set/load functions."""

    def test_get_set_roundtrip(self):
        original = get_session_memory_config()
        try:
            new_config = SessionMemoryConfig(enabled=True, max_facts=150)
            set_session_memory_config(new_config)
            result = get_session_memory_config()
            assert result.enabled is True
            assert result.max_facts == 150
        finally:
            set_session_memory_config(original)

    def test_load_from_dict(self):
        original = get_session_memory_config()
        try:
            load_session_memory_config_from_dict({
                "enabled": True,
                "debounce_seconds": 45,
                "max_facts": 120,
            })
            result = get_session_memory_config()
            assert result.enabled is True
            assert result.debounce_seconds == 45
            assert result.max_facts == 120
            assert result.injection_enabled is True  # default preserved
        finally:
            set_session_memory_config(original)

    def test_load_from_empty_dict_uses_defaults(self):
        original = get_session_memory_config()
        try:
            load_session_memory_config_from_dict({})
            result = get_session_memory_config()
            assert result.enabled is False
            assert result.debounce_seconds == 30
        finally:
            set_session_memory_config(original)
