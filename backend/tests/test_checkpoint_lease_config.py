"""PostgreSQL run leases require one database and schema for checkpoints."""

from types import SimpleNamespace

import pytest

from app.gateway.deps import _validate_checkpoint_lease_storage
from deerflow.config.checkpointer_config import CheckpointerConfig
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.run_ownership_config import RunOwnershipConfig


def _config(*, database_url="postgresql://user:pass@localhost:5432/app", database_schema="shared", checkpoint_url=None, checkpoint_schema="shared", heartbeat=True, database_backend="postgres", checkpoint_type="postgres"):
    if checkpoint_url is None:
        checkpoint_url = database_url
    return SimpleNamespace(
        database=DatabaseConfig(backend=database_backend, postgres_url=database_url, postgres_schema=database_schema),
        checkpointer=CheckpointerConfig(type=checkpoint_type, connection_string=checkpoint_url, postgres_schema=checkpoint_schema),
        run_ownership=RunOwnershipConfig(heartbeat_enabled=heartbeat),
    )


def test_matching_legacy_postgres_storage_passes() -> None:
    config = _config(checkpoint_url="postgresql+asyncpg://user:pass@localhost:5432/app")
    _validate_checkpoint_lease_storage(config)


def test_unified_postgres_storage_passes() -> None:
    config = _config()
    config.checkpointer = None
    _validate_checkpoint_lease_storage(config)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"checkpoint_schema": "other"}, "schema"),
        ({"checkpoint_url": "postgresql://user:pass@localhost:5432/other"}, "database"),
        ({"database_backend": "sqlite"}, "database.backend"),
        ({"checkpoint_type": "memory"}, "checkpointer.type"),
    ],
)
def test_mismatched_lease_storage_fails_before_startup(changes, reason) -> None:
    config = _config(**changes)
    with pytest.raises(SystemExit, match=reason):
        _validate_checkpoint_lease_storage(config)


def test_lease_storage_check_is_inert_without_heartbeat() -> None:
    config = _config(checkpoint_schema="other", heartbeat=False)
    _validate_checkpoint_lease_storage(config)


@pytest.mark.parametrize("checkpoint_type", ["memory", "sqlite"])
def test_heartbeat_rejects_non_atomic_checkpoint_storage(checkpoint_type) -> None:
    config = _config(database_backend="sqlite", checkpoint_type=checkpoint_type)
    with pytest.raises(SystemExit, match="PostgreSQL"):
        _validate_checkpoint_lease_storage(config)


def test_heartbeat_rejects_inferred_sqlite_checkpoint_storage() -> None:
    config = _config(database_backend="sqlite")
    config.checkpointer = None
    with pytest.raises(SystemExit, match="PostgreSQL"):
        _validate_checkpoint_lease_storage(config)


@pytest.mark.parametrize(
    "checkpoint_url",
    [
        "postgresql+psycopg://user:pass@localhost/app",
        "postgresql://user:pass@localhost:5432/app",
        "postgresql://user:pass@localhost/app?application_name=worker&sslmode=require",
    ],
)
def test_equivalent_checkpoint_urls_pass(checkpoint_url) -> None:
    database_url = "postgresql://user:pass@localhost:5432/app"
    if "?" in checkpoint_url:
        database_url += "?sslmode=require&application_name=worker"
    _validate_checkpoint_lease_storage(_config(database_url=database_url, checkpoint_url=checkpoint_url))


@pytest.mark.parametrize(
    "checkpoint_url",
    [
        "postgresql://user:pass@127.0.0.1/app",
        "postgresql://other:pass@localhost/app",
        "postgresql://user:pass@localhost/app?sslmode=disable",
    ],
)
def test_distinct_checkpoint_urls_fail(checkpoint_url) -> None:
    with pytest.raises(SystemExit, match="database URL"):
        _validate_checkpoint_lease_storage(_config(checkpoint_url=checkpoint_url))
