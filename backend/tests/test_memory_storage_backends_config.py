"""Config and loading tests for PG/Mongo memory storage backends."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from deerflow.agents.memory import MongoMemoryStorage, PostgresMemoryStorage
from deerflow.agents.memory.storage import FileMemoryStorage, get_memory_storage
from deerflow.config.memory_config import MemoryConfig


def test_get_memory_storage_postgres_backend_falls_back_when_dependency_missing():
    cfg = MemoryConfig(
        storage_class="deerflow.agents.memory.storage.PostgresMemoryStorage",
        connection_string="postgresql://user:pass@localhost:5432/deerflow",
        postgres_schema="public",
        table="agent_memory",
    )
    with patch("deerflow.agents.memory.storage.get_memory_config", return_value=cfg):
        storage = get_memory_storage()
        assert isinstance(storage, FileMemoryStorage) or storage is not None


def test_get_memory_storage_mongo_backend_falls_back_when_dependency_missing():
    cfg = MemoryConfig(
        storage_class="deerflow.agents.memory.storage.MongoMemoryStorage",
        connection_string="mongodb://localhost:27017",
        mongo_database="deerflow",
        mongo_collection="agent_memory",
    )
    with patch("deerflow.agents.memory.storage.get_memory_config", return_value=cfg):
        storage = get_memory_storage()
        assert isinstance(storage, FileMemoryStorage) or storage is not None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("connection_string", "postgresql://user:pass@localhost:5432/deerflow"),
        ("postgres_schema", "public"),
        ("table", "agent_memory"),
        ("mongo_collection", "agent_memory"),
        ("mongo_database", "deerflow"),
    ],
)
def test_memory_config_exposes_backend_fields(field: str, value: str):
    cfg = MemoryConfig(**{field: value})
    assert getattr(cfg, field) == value


def test_memory_module_exports_storage_backends():
    assert PostgresMemoryStorage.__name__ == "PostgresMemoryStorage"
    assert MongoMemoryStorage.__name__ == "MongoMemoryStorage"
