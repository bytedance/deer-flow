"""Tests for split configuration validation."""

from __future__ import annotations

import logging
import os
from unittest.mock import patch

import pytest

from deerflow.config.app_config import AppConfig, ConfigValidationError


def test_production_mode_rejects_split_config():
    """Production mode should raise ConfigValidationError on split backends."""
    config_data = {
        "database": {"backend": "postgres", "postgres_url": "postgresql://localhost/test"},
        "cost": {"storage_backend": "json"},  # split: postgres DB but JSON cost
    }
    with patch.dict(os.environ, {"DEER_FLOW_ENV": "production"}):
        with pytest.raises(ConfigValidationError) as exc_info:
            AppConfig._validate_postgres_consistency(config_data)
        assert "Split backend configuration detected" in str(exc_info.value)
        assert "cost.storage_backend" in str(exc_info.value)


def test_development_mode_warns_on_split_config(caplog):
    """Development mode should log WARNING on split backends."""
    config_data = {
        "database": {"backend": "postgres", "postgres_url": "postgresql://localhost/test"},
        "cost": {"storage_backend": "json"},
    }
    with patch.dict(os.environ, {"DEER_FLOW_ENV": "development"}, clear=False):
        with caplog.at_level(logging.WARNING, logger="deerflow.config.app_config"):
            AppConfig._validate_postgres_consistency(config_data)
        assert "Split backend configuration detected" in caplog.text
        assert "cost.storage_backend" in caplog.text


def test_consistent_config_no_error():
    """Consistent config (all postgres-compatible) should not raise or warn."""
    config_data = {
        "database": {"backend": "postgres", "postgres_url": "postgresql://localhost/test"},
        "run_events": {"backend": "db"},
        "memory": {"storage_class": "deerflow.agents.memory.storage.StoreMemoryStorage"},
        "rag": {"vector_store_backend": "pgvector"},
        "cost": {"storage_backend": "postgres"},
    }
    with patch.dict(os.environ, {"DEER_FLOW_ENV": "production"}):
        AppConfig._validate_postgres_consistency(config_data)  # should not raise


def test_sqlite_skips_validation():
    """SQLite backend should skip validation entirely."""
    config_data = {
        "database": {"backend": "sqlite"},
        "cost": {"storage_backend": "json"},  # would be split if postgres
    }
    with patch.dict(os.environ, {"DEER_FLOW_ENV": "production"}):
        AppConfig._validate_postgres_consistency(config_data)  # should not raise


def test_multiple_conflicts_reported():
    """Multiple split backends should all be reported in the error."""
    config_data = {
        "database": {"backend": "postgres", "postgres_url": "postgresql://localhost/test"},
        "run_events": {"backend": "memory"},
        "cost": {"storage_backend": "json"},
    }
    with patch.dict(os.environ, {"DEER_FLOW_ENV": "production"}):
        with pytest.raises(ConfigValidationError) as exc_info:
            AppConfig._validate_postgres_consistency(config_data)
        assert "run_events.backend" in str(exc_info.value)
        assert "cost.storage_backend" in str(exc_info.value)


def test_auto_defaults_then_validate_no_error():
    """After auto-defaults, validation should pass (no explicit conflicts)."""
    config_data = {
        "database": {"backend": "postgres", "postgres_url": "postgresql://localhost/test"},
    }
    AppConfig._apply_database_defaults(config_data)
    with patch.dict(os.environ, {"DEER_FLOW_ENV": "production"}):
        AppConfig._validate_postgres_consistency(config_data)  # should not raise
