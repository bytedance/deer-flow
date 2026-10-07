"""The knowledge extension's packaging contract (Task 3).

Pins the lifecycle promises: an unenabled plugin does nothing at all; enabling it brings
the extension's own schema to head and makes the service + both routers reachable; stopping
keeps the data; a re-enable works; and the api marker passes the host's compatibility
window. The DB fixture below runs the *host* bootstrap only — the extension's tables must
appear because ``start()`` ran its chain, never because a fixture helped.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from deerflow_extension_api import API_VERSION, ExtensionRuntimeDeps
from deerflow_knowledge.install import install
from deerflow_knowledge.routers.knowledge_bases import build_router as build_knowledge_bases_router
from deerflow_knowledge.service import KnowledgeExtensionService
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text


class _RecordingRegistry:
    def __init__(self) -> None:
        self.services: list = []
        self.router_list: list = []

    def service(self, service) -> None:
        self.services.append(service)

    def routers(self, routers) -> None:
        self.router_list.extend(routers)


@pytest.fixture
def fake_vector_store(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Keep the service off the real Qdrant: only construction is under test here."""
    store = MagicMock()
    store.init_collections = AsyncMock()
    store.chunks_collection = "kb_chunks"
    monkeypatch.setattr("deerflow_knowledge.vector_store.get_vector_store", lambda: store)
    return store


@pytest_asyncio.fixture
async def raw_session_factory(tmp_path) -> AsyncIterator:
    """Host bootstrap only: the extension's chain must be the service's own doing."""
    from deerflow.config.database_config import DatabaseConfig
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config

    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        yield sf
    finally:
        await close_engine()


async def _kb_tables(sf) -> list[str]:
    async with sf() as session:
        return (await session.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'kb_%' ORDER BY name"))).scalars().all()


def test_install_registers_the_service_and_both_routers():
    registry = _RecordingRegistry()

    install(registry, {})

    assert [type(s).__name__ for s in registry.services] == ["KnowledgeExtensionService"]
    assert [router.prefix for router in registry.router_list] == ["/api/knowledge-bases", "/api"]
    assert all(router.routes for router in registry.router_list)
    paths = {route.path for route in registry.router_list[1].routes}
    assert "/api/rag/config" in paths


def test_a_disabled_plugin_registers_nothing():
    registry = _RecordingRegistry()

    install(registry, {"enabled": False})

    assert registry.services == []
    assert registry.router_list == []


def test_the_api_marker_passes_the_host_window():
    """Host 0.2.5 accepts a declared "0.2" (and "0.2.5"); a "0.3" extension is refused."""
    from deerflow.extensions.loader import _compatible

    assert install.__deerflow_api__ == "0.2"
    assert _compatible(install.__deerflow_api__, API_VERSION)
    assert _compatible("0.2.5", API_VERSION)
    assert not _compatible("0.3", API_VERSION)


async def test_an_unenabled_extension_creates_no_tables(raw_session_factory):
    """Host bootstrap alone must leave zero kb_ tables behind."""
    assert await _kb_tables(raw_session_factory) == []


async def test_start_migrates_serves_and_stop_keeps_the_data(raw_session_factory, fake_vector_store):
    service = KnowledgeExtensionService()
    await service.start(ExtensionRuntimeDeps(session_factory=raw_session_factory))

    assert service.knowledge is not None
    assert await _kb_tables(raw_session_factory) == ["kb_alembic_version", "kb_chunks", "kb_documents", "kb_eval_runs", "kb_knowledge_bases"]
    async with raw_session_factory() as session:
        version = (await session.execute(text("SELECT version_num FROM kb_alembic_version"))).scalar_one()
    assert version == "0002_eval_runs"
    await service.knowledge.store.create_kb(kb_id="kb-1", owner_id="u-1", name="库")

    # The routers answer through the running service: no auth middleware here, so the
    # endpoints' own identity gate is the reachable answer (not a 404 / 503).
    app = FastAPI()
    app.include_router(build_knowledge_bases_router(service))
    with TestClient(app) as client:
        response = client.get("/api/knowledge-bases")
    assert response.status_code == 401

    await service.stop()
    assert service.knowledge is None
    async with raw_session_factory() as session:
        surviving = (await session.execute(text("SELECT count(*) FROM kb_knowledge_bases"))).scalar_one()
    assert surviving == 1  # stopping keeps the data


async def test_a_second_start_resumes_cleanly(raw_session_factory, fake_vector_store):
    service = KnowledgeExtensionService()
    await service.start(ExtensionRuntimeDeps(session_factory=raw_session_factory))
    first = service.knowledge
    await service.stop()

    await service.start(ExtensionRuntimeDeps(session_factory=raw_session_factory))
    try:
        assert service.knowledge is not None
        assert service.knowledge is not first
    finally:
        await service.stop()


async def test_start_without_a_session_factory_refuses_loudly():
    service = KnowledgeExtensionService()

    with pytest.raises(RuntimeError, match="durable database"):
        await service.start(ExtensionRuntimeDeps(session_factory=None))
