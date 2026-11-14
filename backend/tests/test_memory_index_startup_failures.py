"""Operational startup failures must not be treated as index corruption."""

import sqlite3

import pytest

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core import retrieval


@pytest.mark.parametrize("code", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_READONLY, sqlite3.SQLITE_IOERR, sqlite3.SQLITE_ERROR])
def test_operational_startup_failure_preserves_existing_index(tmp_path, monkeypatch, code):
    config = DeerMemConfig(storage_path=str(tmp_path))
    adapter = retrieval.create_fts5_retrieval(config)
    adapter._engine.index_fact("existing", "remember deployment preference")
    adapter.close()
    index = tmp_path / ".retrieval" / "memory-fts5.sqlite3"
    original = index.read_bytes()
    attempts = []

    def unavailable(self):
        attempts.append(self)
        error = sqlite3.OperationalError("temporary startup failure")
        error.sqlite_errorcode = code
        raise error

    with monkeypatch.context() as patched:
        patched.setattr(retrieval.FTS5Retrieval, "_init_schema", unavailable)
        assert retrieval.create_fts5_retrieval(config) is None

    assert index.read_bytes() == original
    assert len(attempts) == 1
    recovered = retrieval.FTS5Retrieval(index)
    try:
        assert [fact["id"] for fact in recovered.search("deployment")] == ["existing"]
    finally:
        recovered.close()
