"""Two Gateways booting the same missing PostgreSQL database: only one can create it.

``_auto_create_postgres_db`` runs when bootstrap fails with SQLSTATE 3D000. With two
processes starting against the same server, the loser's ``CREATE DATABASE`` is refused with
SQLSTATE 42P04 *after* the winner has committed the catalog row, so the target exists and is
usable — the boot must continue to the retry rather than fail on a race it effectively won.
"""

from __future__ import annotations

import logging

import pytest

from deerflow.persistence import engine as engine_mod

_TARGET_URL = "postgresql+asyncpg://deerflow:secret@127.0.0.1:5432/deerflow_target"


class _SqlstateError(Exception):
    """Stands in for the asyncpg exception, which the driver attaches ``sqlstate`` to."""

    def __init__(self, sqlstate: str | None, message: str = "server said no") -> None:
        super().__init__(message)
        if sqlstate is not None:
            self.sqlstate = sqlstate


class _FailingMaintenanceEngine:
    """Fake throwaway ``postgres``-database engine whose CREATE DATABASE raises *error*."""

    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.statements: list[str] = []
        self.disposed = False

    def connect(self) -> _FailingMaintenanceEngine:
        return self

    async def __aenter__(self) -> _FailingMaintenanceEngine:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def execute(self, statement: object) -> None:
        self.statements.append(str(statement))
        raise self.error

    async def dispose(self) -> None:
        self.disposed = True


@pytest.fixture
def maintenance(monkeypatch: pytest.MonkeyPatch):
    installed: list[_FailingMaintenanceEngine] = []

    def _install(error: BaseException) -> _FailingMaintenanceEngine:
        engine = _FailingMaintenanceEngine(error)
        installed.append(engine)
        monkeypatch.setattr(engine_mod, "create_async_engine", lambda *args, **kwargs: engine)
        return engine

    _install.installed = installed  # type: ignore[attr-defined]
    return _install


@pytest.mark.asyncio
async def test_duplicate_database_from_a_peer_continues_the_boot(maintenance, caplog) -> None:
    engine = maintenance(_SqlstateError("42P04", 'database "deerflow_target" already exists'))

    with caplog.at_level(logging.INFO):
        await engine_mod._auto_create_postgres_db(_TARGET_URL)

    assert 'CREATE DATABASE "deerflow_target"' in engine.statements[0]
    assert "was created by a peer process" in caplog.text
    assert engine.disposed, "the throwaway maintenance engine must still be disposed"


@pytest.mark.asyncio
async def test_wrapped_duplicate_database_is_recognised(maintenance) -> None:
    """SQLSTATE lives on the driver exception, which reaches us wrapped in ``orig``."""
    wrapper = RuntimeError("bootstrap failed")
    wrapper.__cause__ = _SqlstateError("42P04", 'database "deerflow_target" already exists')
    engine = maintenance(wrapper)

    await engine_mod._auto_create_postgres_db(_TARGET_URL)

    assert engine.disposed


@pytest.mark.asyncio
async def test_permission_denied_still_propagates(maintenance) -> None:
    """The other CREATE DATABASE failure mode is a real error and must not be swallowed."""
    engine = maintenance(_SqlstateError("42501", "permission denied to create database"))

    with pytest.raises(_SqlstateError):
        await engine_mod._auto_create_postgres_db(_TARGET_URL)

    assert engine.disposed


@pytest.mark.asyncio
async def test_unrelated_failure_still_propagates(maintenance) -> None:
    engine = maintenance(OSError("connection refused"))

    with pytest.raises(OSError):
        await engine_mod._auto_create_postgres_db(_TARGET_URL)

    assert engine.disposed


def test_missing_and_duplicate_codes_are_distinct() -> None:
    """Guards against collapsing the two SQLSTATEs into one constant."""
    assert engine_mod._MISSING_DATABASE_SQLSTATE != engine_mod._DUPLICATE_DATABASE_SQLSTATE
    assert not engine_mod._is_missing_database_error(_SqlstateError("42P04"))
    assert not engine_mod._is_duplicate_database_error(_SqlstateError("3D000"))
