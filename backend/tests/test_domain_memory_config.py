"""Unit tests for domain memory configuration."""

import pytest
from pydantic import ValidationError

from deerflow.config.domain_memory_config import (
    DomainDecayConfig,
    DomainMemoryConfig,
    get_domain_memory_config,
    load_domain_memory_config_from_dict,
    set_domain_memory_config,
)


class TestDomainDecayConfig:
    """Tests for DomainDecayConfig."""

    def test_defaults(self):
        """DomainDecayConfig has correct defaults."""
        config = DomainDecayConfig()
        assert config.policy == "never"
        assert config.half_life_days == 90.0

    def test_custom_values(self):
        """DomainDecayConfig accepts custom values."""
        config = DomainDecayConfig(policy="linear", half_life_days=30.0)
        assert config.policy == "linear"
        assert config.half_life_days == 30.0

    def test_validates_half_life_range(self):
        """DomainDecayConfig validates half_life_days range."""
        with pytest.raises(ValidationError):
            DomainDecayConfig(half_life_days=0.5)  # Below minimum of 1.0

        with pytest.raises(ValidationError):
            DomainDecayConfig(half_life_days=5000.0)  # Above maximum of 3650.0


class TestDomainMemoryConfig:
    """Tests for DomainMemoryConfig."""

    def test_defaults(self):
        """DomainMemoryConfig has correct defaults."""
        config = DomainMemoryConfig()
        assert config.enabled is False
        assert config.model_name is None
        assert config.debounce_seconds == 30
        assert config.fact_confidence_threshold == 0.8
        assert config.injection_enabled is True
        assert config.max_injection_tokens == 1000
        assert config.min_retrieval_score == 0.7
        assert config.domains == {}

    def test_custom_values(self):
        """DomainMemoryConfig accepts custom values."""
        config = DomainMemoryConfig(
            enabled=True,
            model_name="gpt-4",
            debounce_seconds=60,
            fact_confidence_threshold=0.9,
            injection_enabled=False,
            max_injection_tokens=2000,
            min_retrieval_score=0.8,
        )
        assert config.enabled is True
        assert config.model_name == "gpt-4"
        assert config.debounce_seconds == 60
        assert config.fact_confidence_threshold == 0.9
        assert config.injection_enabled is False
        assert config.max_injection_tokens == 2000
        assert config.min_retrieval_score == 0.8

    def test_validates_debounce_seconds_range(self):
        """DomainMemoryConfig validates debounce_seconds range."""
        with pytest.raises(ValidationError):
            DomainMemoryConfig(debounce_seconds=0)  # Below minimum of 1

        with pytest.raises(ValidationError):
            DomainMemoryConfig(debounce_seconds=500)  # Above maximum of 300

    def test_validates_confidence_threshold_range(self):
        """DomainMemoryConfig validates fact_confidence_threshold range."""
        with pytest.raises(ValidationError):
            DomainMemoryConfig(fact_confidence_threshold=-0.1)

        with pytest.raises(ValidationError):
            DomainMemoryConfig(fact_confidence_threshold=1.5)

    def test_validates_max_injection_tokens_range(self):
        """DomainMemoryConfig validates max_injection_tokens range."""
        with pytest.raises(ValidationError):
            DomainMemoryConfig(max_injection_tokens=50)  # Below minimum of 100

        with pytest.raises(ValidationError):
            DomainMemoryConfig(max_injection_tokens=10000)  # Above maximum of 8000

    def test_per_domain_decay_config(self):
        """DomainMemoryConfig supports per-domain decay configuration."""
        config = DomainMemoryConfig(
            enabled=True,
            domains={
                "equipment": DomainDecayConfig(policy="never", half_life_days=365),
                "process": DomainDecayConfig(policy="linear", half_life_days=30),
            },
        )
        assert len(config.domains) == 2
        assert config.domains["equipment"].policy == "never"
        assert config.domains["process"].policy == "linear"

    def test_get_domain_decay_returns_configured(self):
        """get_domain_decay() returns configured decay for known domain."""
        config = DomainMemoryConfig(
            domains={"equipment": DomainDecayConfig(policy="exponential", half_life_days=60)},
        )
        decay = config.get_domain_decay("equipment")
        assert decay.policy == "exponential"
        assert decay.half_life_days == 60

    def test_get_domain_decay_returns_default_for_unknown(self):
        """get_domain_decay() returns default decay for unknown domain."""
        config = DomainMemoryConfig()
        decay = config.get_domain_decay("unknown_domain")
        assert decay.policy == "never"
        assert decay.half_life_days == 90.0


class TestDomainMemoryConfigFunctions:
    """Tests for domain memory config functions."""

    def test_get_domain_memory_config_returns_singleton(self):
        """get_domain_memory_config() returns same instance."""
        config1 = get_domain_memory_config()
        config2 = get_domain_memory_config()
        assert config1 is config2

    def test_set_domain_memory_config_updates_singleton(self):
        """set_domain_memory_config() updates the singleton."""
        original = get_domain_memory_config()
        new_config = DomainMemoryConfig(enabled=True, debounce_seconds=45)
        set_domain_memory_config(new_config)
        try:
            retrieved = get_domain_memory_config()
            assert retrieved is new_config
            assert retrieved.enabled is True
            assert retrieved.debounce_seconds == 45
        finally:
            set_domain_memory_config(original)

    def test_load_domain_memory_config_from_dict(self):
        """load_domain_memory_config_from_dict() creates config from dict."""
        original = get_domain_memory_config()
        try:
            load_domain_memory_config_from_dict({
                "enabled": True,
                "debounce_seconds": 90,
                "fact_confidence_threshold": 0.85,
            })
            config = get_domain_memory_config()
            assert config.enabled is True
            assert config.debounce_seconds == 90
            assert config.fact_confidence_threshold == 0.85
        finally:
            set_domain_memory_config(original)

    def test_load_domain_memory_config_from_empty_dict(self):
        """load_domain_memory_config_from_dict() uses defaults for empty dict."""
        original = get_domain_memory_config()
        try:
            load_domain_memory_config_from_dict({})
            config = get_domain_memory_config()
            assert config.enabled is False
            assert config.debounce_seconds == 30
        finally:
            set_domain_memory_config(original)
