"""Tests for database backend auto-default logic."""

from __future__ import annotations

from deerflow.config.app_config import AppConfig


def test_postgres_auto_defaults_all_subsystems():
    """When database.backend=postgres and no subsystem backends set, all should auto-default."""
    config_data = {
        "database": {"backend": "postgres", "postgres_url": "postgresql://localhost/test"},
    }
    AppConfig._apply_database_defaults(config_data)

    assert config_data["run_events"]["backend"] == "db"
    assert config_data["memory"]["storage_class"] == "deerflow.agents.memory.storage.StoreMemoryStorage"
    assert config_data["rag"]["vector_store_backend"] == "pgvector"
    assert config_data["cost"]["storage_backend"] == "postgres"


def test_postgres_auto_defaults_respect_explicit_config():
    """When database.backend=postgres but subsystem backends are explicitly set, they should not be overridden."""
    config_data = {
        "database": {"backend": "postgres", "postgres_url": "postgresql://localhost/test"},
        "run_events": {"backend": "jsonl"},
        "memory": {"storage_class": "deerflow.agents.memory.storage.FileMemoryStorage"},
        "rag": {"vector_store_backend": "chroma"},
        "cost": {"storage_backend": "json"},
    }
    AppConfig._apply_database_defaults(config_data)

    assert config_data["run_events"]["backend"] == "jsonl"
    assert config_data["memory"]["storage_class"] == "deerflow.agents.memory.storage.FileMemoryStorage"
    assert config_data["rag"]["vector_store_backend"] == "chroma"
    assert config_data["cost"]["storage_backend"] == "json"


def test_postgres_auto_defaults_partial_explicit():
    """When database.backend=postgres and some subsystem backends are explicitly set, only unset ones should auto-default."""
    config_data = {
        "database": {"backend": "postgres", "postgres_url": "postgresql://localhost/test"},
        "cost": {"storage_backend": "json"},
    }
    AppConfig._apply_database_defaults(config_data)

    assert config_data["run_events"]["backend"] == "db"
    assert config_data["memory"]["storage_class"] == "deerflow.agents.memory.storage.StoreMemoryStorage"
    assert config_data["rag"]["vector_store_backend"] == "pgvector"
    assert config_data["cost"]["storage_backend"] == "json"  # explicitly set, not overridden


def test_sqlite_no_auto_defaults():
    """When database.backend=sqlite, no subsystem auto-defaults should be applied."""
    config_data = {
        "database": {"backend": "sqlite"},
    }
    AppConfig._apply_database_defaults(config_data)

    assert "run_events" not in config_data or "backend" not in config_data.get("run_events", {})
    assert "memory" not in config_data or "storage_class" not in config_data.get("memory", {})
    assert "rag" not in config_data or "vector_store_backend" not in config_data.get("rag", {})
    assert "cost" not in config_data or "storage_backend" not in config_data.get("cost", {})


def test_memory_no_auto_defaults():
    """When database.backend=memory, no subsystem auto-defaults should be applied."""
    config_data = {
        "database": {"backend": "memory"},
    }
    AppConfig._apply_database_defaults(config_data)

    assert "run_events" not in config_data or "backend" not in config_data.get("run_events", {})
    assert "memory" not in config_data or "storage_class" not in config_data.get("memory", {})
    assert "rag" not in config_data or "vector_store_backend" not in config_data.get("rag", {})
    assert "cost" not in config_data or "storage_backend" not in config_data.get("cost", {})


def test_auto_defaults_logging(caplog):
    """Auto-default decisions should be logged at INFO level."""
    import logging
    config_data = {
        "database": {"backend": "postgres", "postgres_url": "postgresql://localhost/test"},
        "cost": {"storage_backend": "json"},
    }
    with caplog.at_level(logging.INFO, logger="deerflow.config.app_config"):
        AppConfig._apply_database_defaults(config_data)

    assert "Auto-defaulted run_events.backend=db" in caplog.text
    assert "Auto-defaulted memory.storage_class=StoreMemoryStorage" in caplog.text
    assert "Auto-defaulted rag.vector_store_backend=pgvector" in caplog.text
    assert "cost.storage_backend=json (explicitly configured" in caplog.text
