"""Shared fixtures for knowledge-base (RAG) tests."""

from __future__ import annotations

import importlib
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

QDRANT_TEST_URL = os.environ.get("QDRANT_TEST_URL", "http://127.0.0.1:6333")


def spy_embed_text(monkeypatch, module_path: str, name: str) -> list[tuple]:
    """Spy on a consumer module's *own* embed-text helper and return its call log.

    Recipe precedent: ``test_worker.py:525``. ``raising=False`` keeps the
    pre-switch state (callers inline the f-string, the module has no such
    name) a clean RED — the call log simply stays empty. Post-switch the spy
    delegates to the module's real helper, so the existing text assertions
    keep holding (spec 2026-09-24 §4.1 同源钉子, 2026-09-25).
    """
    module = importlib.import_module(module_path)
    real = getattr(module, name, None)
    calls: list[tuple] = []

    def spy(*args, **kwargs):
        calls.append(args)
        assert real is not None, f"{module_path}.{name} is not the shared helper yet"
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, spy, raising=False)
    return calls


def _qdrant_available() -> bool:
    """Probe the Qdrant service with a short-timeout sync client.

    Mirrors the ``_redis_available`` pattern in tests/test_stream_bridge.py:
    runs at collection time so the integration suite degrades to skips when
    the service is not running.
    """
    try:
        from qdrant_client import QdrantClient
    except ImportError:
        return False
    try:
        client = QdrantClient(QDRANT_TEST_URL, timeout=1.0)
        try:
            client.get_collections()
        finally:
            client.close()
        return True
    except Exception:
        return False


requires_qdrant = pytest.mark.skipif(not _qdrant_available(), reason=f"Qdrant not reachable at {QDRANT_TEST_URL}")


@pytest_asyncio.fixture
async def session_factory(tmp_path) -> AsyncIterator:
    """Bootstrap a throwaway SQLite database at alembic head per test.

    Host bootstrap first, then the extension's own chain — the production
    sequence (the extension's tables live under its private MetaData and are
    never created by the host's ``create_all``).
    """
    from deerflow_knowledge.migrations.runner import run_knowledge_migrations

    from deerflow.config.database_config import DatabaseConfig
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config

    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        await run_knowledge_migrations(sf)
        yield sf
    finally:
        await close_engine()
