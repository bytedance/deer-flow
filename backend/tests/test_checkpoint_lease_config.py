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
