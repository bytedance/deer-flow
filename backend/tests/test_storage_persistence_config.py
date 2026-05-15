from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEER_FLOW_CONFIG_PATH", str(Path(__file__).resolve().parents[2] / "config.example.yaml"))

from store.config.storage_config import StorageConfig
from store.persistence.factory import _create_database_url, storage_config_from_database_config


def test_database_sqlite_config_maps_to_storage_config(tmp_path):
    database = SimpleNamespace(
        backend="sqlite",
        sqlite_dir=str(tmp_path),
        echo_sql=True,
        pool_size=9,
    )

    storage = storage_config_from_database_config(database)

    assert storage == StorageConfig(
        driver="sqlite",
        sqlite_dir=str(tmp_path),
        echo_sql=True,
        pool_size=9,
    )
    assert storage.sqlite_storage_path == str(tmp_path / "deerflow.db")


def test_database_memory_config_is_not_a_storage_backend():
    database = SimpleNamespace(backend="memory")

    with pytest.raises(ValueError, match="Unsupported database backend"):
        storage_config_from_database_config(database)


def test_database_postgres_config_preserves_url_and_pool_options():
    database = SimpleNamespace(
        backend="postgres",
        postgres_url="postgresql://user:pass@db.example:5544/deerflow",
        echo_sql=True,
        pool_size=11,
    )

    storage = storage_config_from_database_config(database)
    url = _create_database_url(storage)

    assert storage.driver == "postgres"
    assert storage.database_url == "postgresql://user:pass@db.example:5544/deerflow"
    assert storage.username == "user"
    assert storage.password == "pass"
    assert storage.host == "db.example"
    assert storage.port == 5544
    assert storage.db_name == "deerflow"
    assert storage.echo_sql is True
    assert storage.pool_size == 11
    assert url.drivername == "postgresql+asyncpg"
    assert url.database == "deerflow"


def test_mysql_database_url_is_normalized_to_async_driver():
    storage = StorageConfig(
        driver="mysql",
        database_url="mysql://user:pass@db.example:3306/deerflow",
    )

    url = _create_database_url(storage)

    assert url.drivername == "mysql+aiomysql"
    assert url.database == "deerflow"


def test_mysql_async_database_url_is_preserved():
    storage = StorageConfig(
        driver="mysql",
        database_url="mysql+asyncmy://user:pass@db.example:3306/deerflow",
    )

    url = _create_database_url(storage)

    assert url.drivername == "mysql+asyncmy"
    assert url.database == "deerflow"


def test_database_postgres_requires_url():
    database = SimpleNamespace(backend="postgres", postgres_url="")

    with pytest.raises(ValueError, match="database.postgres_url is required"):
        storage_config_from_database_config(database)


def test_unsupported_database_backend_rejected():
    database = SimpleNamespace(backend="oracle")

    with pytest.raises(ValueError, match="Unsupported database backend"):
        storage_config_from_database_config(database)


def test_storage_models_import_without_config_file(tmp_path):
    env = os.environ.copy()
    env["DEER_FLOW_CONFIG_PATH"] = str(tmp_path / "missing-config.yaml")

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from store.persistence.base_model import UniversalText, id_key; from store.repositories.models import RunEvent; print(UniversalText.__name__, RunEvent.__tablename__, id_key)",
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "UniversalText run_events" in result.stdout
