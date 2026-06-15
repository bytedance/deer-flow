"""Tests for multi-worker deployment config framework.

Covers: DeploymentConfig model, env var handling, mode override logic,
dev mode sledgehammer, _apply_multi_worker_defaults, and interaction
with _apply_database_defaults.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from deerflow.config.app_config import AppConfig
from deerflow.config.deployment_config import (
    DeploymentConfig,
    get_deployment_config,
    load_deployment_config_from_dict,
    reset_deployment_config,
)


@pytest.fixture(autouse=True)
def _clean_env():
    """Remove multi-worker env vars before/after each test."""
    keys = ("DEER_FLOW_MULTI_WORKER", "DEER_FLOW_DEV_MODE")
    saved = {k: os.environ.pop(k, None) for k in keys}
    reset_deployment_config()
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
    reset_deployment_config()


# ---------------------------------------------------------------------------
# DeploymentConfig model
# ---------------------------------------------------------------------------


class TestDeploymentConfig:
    def test_default_is_single_worker(self) -> None:
        cfg = DeploymentConfig()
        assert cfg.mode == "single_worker"

    def test_multi_worker_accepted(self) -> None:
        cfg = DeploymentConfig(mode="multi_worker")
        assert cfg.mode == "multi_worker"

    def test_invalid_mode_rejected(self) -> None:
        with pytest.raises(Exception):
            DeploymentConfig(mode="triple_worker")

    def test_singleton_lifecycle(self) -> None:
        reset_deployment_config()
        a = get_deployment_config()
        b = get_deployment_config()
        assert a is b

    def test_load_from_dict(self) -> None:
        reset_deployment_config()
        cfg = load_deployment_config_from_dict({"mode": "multi_worker"})
        assert cfg.mode == "multi_worker"
        assert get_deployment_config().mode == "multi_worker"


# ---------------------------------------------------------------------------
# _apply_deployment_mode_env
# ---------------------------------------------------------------------------


class TestApplyDeploymentModeEnv:
    def test_multi_worker_env_sets_mode(self) -> None:
        config_data: dict = {}
        with patch.dict(os.environ, {"DEER_FLOW_MULTI_WORKER": "1"}):
            AppConfig._apply_deployment_mode_env(config_data)
        assert config_data["deployment"]["mode"] == "multi_worker"

    def test_multi_worker_env_does_not_override_explicit(self) -> None:
        config_data: dict = {"deployment": {"mode": "single_worker"}}
        with patch.dict(os.environ, {"DEER_FLOW_MULTI_WORKER": "1"}):
            AppConfig._apply_deployment_mode_env(config_data)
        assert config_data["deployment"]["mode"] == "single_worker"

    def test_dev_mode_forces_single_worker(self) -> None:
        config_data: dict = {"deployment": {"mode": "multi_worker"}}
        with patch.dict(os.environ, {"DEER_FLOW_DEV_MODE": "1"}):
            AppConfig._apply_deployment_mode_env(config_data)
        assert config_data["deployment"]["mode"] == "single_worker"

    def test_dev_mode_overrides_multi_worker_env(self) -> None:
        config_data: dict = {}
        with patch.dict(os.environ, {"DEER_FLOW_DEV_MODE": "1", "DEER_FLOW_MULTI_WORKER": "1"}):
            AppConfig._apply_deployment_mode_env(config_data)
        assert config_data["deployment"]["mode"] == "single_worker"

    def test_dev_mode_forces_local_backends(self) -> None:
        config_data: dict = {
            "database": {"backend": "postgres"},
            "stream_bridge": {"type": "redis"},
        }
        with patch.dict(os.environ, {"DEER_FLOW_DEV_MODE": "1"}):
            AppConfig._apply_deployment_mode_env(config_data)
        assert config_data["database"]["backend"] == "sqlite"
        assert config_data["stream_bridge"]["type"] == "memory"
        assert config_data["memory"]["storage_class"] == "deerflow.agents.memory.storage.FileMemoryStorage"
        assert config_data["rag"]["vector_store_backend"] == "chroma"
        assert config_data["cost"]["storage_backend"] == "json"
        assert config_data["rate_limit"]["backend"] == "memory"

    def test_no_env_no_change(self) -> None:
        config_data: dict = {}
        AppConfig._apply_deployment_mode_env(config_data)
        assert "deployment" not in config_data or config_data.get("deployment", {}).get("mode") is None

    def test_empty_env_ignored(self) -> None:
        config_data: dict = {}
        with patch.dict(os.environ, {"DEER_FLOW_MULTI_WORKER": "0"}):
            AppConfig._apply_deployment_mode_env(config_data)
        mode = config_data.get("deployment", {}).get("mode")
        assert mode is None


# ---------------------------------------------------------------------------
# _apply_multi_worker_defaults
# ---------------------------------------------------------------------------


class TestApplyMultiWorkerDefaults:
    def test_sets_postgres_and_subsystems(self) -> None:
        config_data: dict = {"deployment": {"mode": "multi_worker"}}
        database_config: dict = {}
        AppConfig._apply_multi_worker_defaults(config_data, database_config, user_set_backend=False)
        assert database_config["backend"] == "postgres"
        assert config_data["stream_bridge"]["type"] == "redis"
        assert config_data["rate_limit"]["backend"] == "redis"
        assert config_data["indexing"]["dispatcher_mode"] == "queue"
        assert config_data["im"]["coordination_mode"] == "redis"

    def test_user_set_backend_preserved(self) -> None:
        config_data: dict = {"deployment": {"mode": "multi_worker"}}
        database_config: dict = {"backend": "sqlite"}
        AppConfig._apply_multi_worker_defaults(config_data, database_config, user_set_backend=True)
        assert database_config["backend"] == "sqlite"

    def test_explicit_subsystem_values_preserved(self) -> None:
        config_data: dict = {
            "deployment": {"mode": "multi_worker"},
            "stream_bridge": {"type": "memory"},
            "indexing": {"dispatcher_mode": "local"},
        }
        database_config: dict = {}
        AppConfig._apply_multi_worker_defaults(config_data, database_config, user_set_backend=False)
        assert config_data["stream_bridge"]["type"] == "memory"
        assert config_data["indexing"]["dispatcher_mode"] == "local"

    def test_single_worker_no_defaults(self) -> None:
        config_data: dict = {"deployment": {"mode": "single_worker"}}
        database_config: dict = {}
        AppConfig._apply_multi_worker_defaults(config_data, database_config, user_set_backend=False)
        assert "backend" not in database_config
        assert "stream_bridge" not in config_data

    def test_no_deployment_section_noop(self) -> None:
        config_data: dict = {}
        database_config: dict = {}
        AppConfig._apply_multi_worker_defaults(config_data, database_config, user_set_backend=False)
        assert "backend" not in database_config


# ---------------------------------------------------------------------------
# _apply_database_defaults integration
# ---------------------------------------------------------------------------


class TestApplyDatabaseDefaultsIntegration:
    def test_multi_worker_triggers_postgres_auto_defaults(self) -> None:
        """multi_worker → database.backend=postgres → memory/rag/cost auto-defaults."""
        config_data: dict = {"deployment": {"mode": "multi_worker"}}
        AppConfig._apply_database_defaults(config_data)
        assert config_data["database"]["backend"] == "postgres"
        assert config_data["memory"]["storage_class"] == "deerflow.agents.memory.storage.StoreMemoryStorage"
        assert config_data["rag"]["vector_store_backend"] == "pgvector"
        assert config_data["cost"]["storage_backend"] == "postgres"
        assert config_data["run_events"]["backend"] == "db"

    def test_multi_worker_with_explicit_postgres_preserves_memory(self) -> None:
        """Explicit memory.storage_class wins even in multi-worker mode."""
        config_data: dict = {
            "deployment": {"mode": "multi_worker"},
            "memory": {"storage_class": "deerflow.agents.memory.storage.FileMemoryStorage"},
        }
        AppConfig._apply_database_defaults(config_data)
        assert config_data["memory"]["storage_class"] == "deerflow.agents.memory.storage.FileMemoryStorage"

    def test_single_worker_keeps_sqlite(self) -> None:
        config_data: dict = {"deployment": {"mode": "single_worker"}}
        AppConfig._apply_database_defaults(config_data)
        assert config_data["database"]["backend"] == "sqlite"

    def test_postgres_without_multi_worker_still_auto_defaults(self) -> None:
        """database.backend=postgres (explicit) should still trigger postgres auto-defaults."""
        config_data: dict = {"database": {"backend": "postgres"}}
        AppConfig._apply_database_defaults(config_data)
        assert config_data["memory"]["storage_class"] == "deerflow.agents.memory.storage.StoreMemoryStorage"
        assert config_data["rag"]["vector_store_backend"] == "pgvector"


# ---------------------------------------------------------------------------
# _force_dev_mode_defaults
# ---------------------------------------------------------------------------


class TestForceDevModeDefaults:
    def test_overrides_all_explicit_backends(self) -> None:
        config_data: dict = {
            "database": {"backend": "postgres"},
            "memory": {"storage_class": "deerflow.agents.memory.storage.StoreMemoryStorage"},
            "rag": {"vector_store_backend": "pgvector"},
            "cost": {"storage_backend": "postgres"},
            "stream_bridge": {"type": "redis"},
            "rate_limit": {"backend": "redis"},
        }
        AppConfig._force_dev_mode_defaults(config_data)
        assert config_data["database"]["backend"] == "sqlite"
        assert config_data["memory"]["storage_class"] == "deerflow.agents.memory.storage.FileMemoryStorage"
        assert config_data["rag"]["vector_store_backend"] == "chroma"
        assert config_data["cost"]["storage_backend"] == "json"
        assert config_data["stream_bridge"]["type"] == "memory"
        assert config_data["rate_limit"]["backend"] == "memory"

    def test_creates_missing_sections(self) -> None:
        config_data: dict = {}
        AppConfig._force_dev_mode_defaults(config_data)
        assert config_data["database"]["backend"] == "sqlite"
        assert config_data["memory"]["storage_class"] == "deerflow.agents.memory.storage.FileMemoryStorage"
