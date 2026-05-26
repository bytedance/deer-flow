"""Tests for MemoryApiConfig defaults and validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from deerflow.config.memory_api_config import (
    MemoryApiConfig,
    get_memory_api_config,
    load_memory_api_config_from_dict,
    set_memory_api_config,
)


@pytest.fixture(autouse=True)
def _restore_config():
    """Restore the global config singleton after each test."""
    original = get_memory_api_config()
    yield
    set_memory_api_config(original)


def test_defaults():
    """Default values are sensible."""
    config = MemoryApiConfig()
    assert config.enabled is True
    assert config.max_content_length == 1000
    assert config.audit_log_retention_days == 90


def test_validation_max_content_length_too_low():
    """max_content_length below 100 is rejected."""
    with pytest.raises(ValidationError):
        MemoryApiConfig(max_content_length=50)


def test_validation_max_content_length_too_high():
    """max_content_length above 10000 is rejected."""
    with pytest.raises(ValidationError):
        MemoryApiConfig(max_content_length=20000)


def test_validation_retention_days_too_low():
    """audit_log_retention_days below 1 is rejected."""
    with pytest.raises(ValidationError):
        MemoryApiConfig(audit_log_retention_days=0)


def test_validation_retention_days_too_high():
    """audit_log_retention_days above 3650 is rejected."""
    with pytest.raises(ValidationError):
        MemoryApiConfig(audit_log_retention_days=5000)


def test_custom_values():
    """Custom values are accepted."""
    config = MemoryApiConfig(
        enabled=False,
        max_content_length=2000,
        audit_log_retention_days=365,
    )
    assert config.enabled is False
    assert config.max_content_length == 2000
    assert config.audit_log_retention_days == 365


def test_load_from_dict():
    """load_memory_api_config_from_dict sets the singleton."""
    load_memory_api_config_from_dict({
        "enabled": False,
        "max_content_length": 500,
        "audit_log_retention_days": 30,
    })
    config = get_memory_api_config()
    assert config.enabled is False
    assert config.max_content_length == 500
    assert config.audit_log_retention_days == 30


def test_set_and_get():
    """set_memory_api_config replaces the singleton."""
    custom = MemoryApiConfig(enabled=False)
    set_memory_api_config(custom)
    assert get_memory_api_config().enabled is False
