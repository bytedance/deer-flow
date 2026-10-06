"""Contract tests for the vector-space projection endpoints (spec §7 P4).

GET  ``/api/knowledge-bases/{kb_id}/vector-projection`` — cached projection of
the four collections, computed through the real fetcher→reducer→cache chain
(only Qdrant scroll/retrieve and the query embedder are mocked).
POST ``/api/knowledge-bases/{kb_id}/vector-projection/query`` — query-text
transform through the cached PCA model; never triggers a projection compute.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from qdrant_client.models import SparseVector

from app.gateway.auth.models import User
from app.gateway.routers import knowledge_bases
from app.gateway.services import knowledge_service as ks_module
from app.gateway.services.knowledge_service import KnowledgeService
from deerflow.knowledge.embedder import EmbeddingResult
from deerflow.knowledge.projection.cache import CachedProjection
from deerflow.knowledge.store import KnowledgeStore

pytestmark = pytest.mark.asyncio

OWNER_ID = str(UUID(int=1234567890))


def _owner() -> User:
    return User(email="owner@example.com", password_hash="x", system_role="user", id=UUID(OWNER_ID))


_SCROLL_DATA: dict[str, list[SimpleNamespace]] = {
    "kb_chunks": [
        SimpleNamespace(id="pt-0", payload={"chunk_id": "d#0000", "kb_id": "kb", "doc_id": "d", "doc_name": "d.pdf", "entities": []}),
        SimpleNamespace(id="pt-1", payload={"chunk_id": "d#0001", "kb_id": "kb", "doc_id": "d", "doc_name": "d.pdf", "entities": []}),
        SimpleNamespace(id="pt-2", payload={"chunk_id": "d#0002", "kb_id": "kb", "doc_id": "d", "doc_name": "d.pdf", "entities": []}),
    ],
    "kb_entities": [],
    "kb_wiki": [SimpleNamespace(id="pt-w", payload={"entry_id": "e1", "kb_id": "kb", "title": "条目"})],
    "kb_cards": [],
}

_VECTORS: dict[str, list[float]] = {
    "pt-0": [1.0, 0.0, 0.0, 0.0],
    "pt-1": [0.0, 1.0, 0.0, 0.0],
    "pt-2": [0.0, 0.0, 1.0, 0.0],
    "pt-w": [0.0, 0.0, 0.0, 1.0],
}

#: KBs with seeded vectors — the fake scroll returns data only for these, so
#: the empty-KB case is expressible (cleared per test by the service fixture).
_SEEDED_KBS: set[str] = set()


@pytest.fixture
def service(session_factory, tmp_path) -> KnowledgeService:
    _SEEDED_KBS.clear()
    vector_store = MagicMock()
    vector_store.chunks_collection = "kb_chunks"
    vector_store.entities_collection = "kb_entities"
    vector_store.wiki_entries_collection = "kb_wiki"
    vector_store.manual_cards_collection = "kb_cards"

    async def _scroll(collection: str, kb_id: str, **kw):
        return _SCROLL_DATA.get(collection, []) if kb_id in _SEEDED_KBS else []

    vector_store.scroll_collection = AsyncMock(side_effect=_scroll)
    vector_store.retrieve_vectors = AsyncMock(side_effect=lambda collection, ids: {str(i): _VECTORS[str(i)] for i in ids if str(i) in _VECTORS})
    return KnowledgeService(
        store=KnowledgeStore(session_factory),
        vector_store=vector_store,
        graph_store=None,
        wiki_store=None,
        worker=None,
        data_dir=tmp_path,
    )


def _client(service: KnowledgeService, user_factory=_owner) -> TestClient:
    from _router_auth_helpers import make_authed_test_app

    app = make_authed_test_app(user_factory=user_factory)
    app.state.knowledge_service = service
    app.include_router(knowledge_bases.router)
    return TestClient(app)


def _create_kb(client: TestClient, name: str = "产品资料") -> dict:
    response = client.post("/api/knowledge-bases", json={"name": name, "description": "d"})
    assert response.status_code == 201, response.text
    return response.json()


async def _seed_chunks(service: KnowledgeService, kb_id: str) -> None:
    _SEEDED_KBS.add(kb_id)
    await service.store.insert_chunks([{"chunk_id": f"d#{i:04d}", "doc_id": "d", "kb_id": kb_id, "chunk_index": i, "text": f"切片{i}正文", "heading_path": ["第1章"]} for i in range(3)])


async def test_get_projection_returns_full_contract(service, session_factory) -> None:
    client = _client(service)
    kb = _create_kb(client)
    await _seed_chunks(service, kb["id"])
    # scroll payload kb_id must match the real kb for the fetcher filter — the
    # fake scroll ignores it, so only the DB rows need the real kb_id.

    first = client.get(f"/api/knowledge-bases/{kb['id']}/vector-projection?dims=2")
    assert first.status_code == 200, first.text
    body = first.json()

    assert body["kb_id"] == kb["id"]
    assert body["algo"] == "pca"
    assert body["dims"] == 2
    assert body["model_version"] == "pca-v1"
    assert body["fingerprint"].startswith("sha1:")
    assert body["cached"] is False
    assert isinstance(body["computed_ms"], int) and body["computed_ms"] >= 0
    assert body["total_points"] == 4
    assert body["shown_points"] == 4
    assert body["sampled"] is False
    assert len(body["points"]) == 4

    chunk_point = next(p for p in body["points"] if p["source_type"] == "chunk")
    assert isinstance(chunk_point["x"], float) and isinstance(chunk_point["y"], float)
    assert "z" not in chunk_point  # dims=2 carries no z
    assert chunk_point["label"] == "d.pdf"
    assert chunk_point["color_key"] == "d"
    assert chunk_point["preview"].startswith("切片")
    assert chunk_point["heading_path"] == ["第1章"]
    wiki_point = next(p for p in body["points"] if p["source_type"] == "wiki")
    assert wiki_point["color_key"] == "wiki"

    # second call with unchanged content serves the cache
    second = client.get(f"/api/knowledge-bases/{kb['id']}/vector-projection?dims=2")
    assert second.status_code == 200, second.text
    assert second.json()["cached"] is True
    assert second.json()["fingerprint"] == body["fingerprint"]


async def test_get_projection_empty_kb_returns_empty_points(service) -> None:
    client = _client(service)
    kb = _create_kb(client)

    response = client.get(f"/api/knowledge-bases/{kb['id']}/vector-projection")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["points"] == []
    assert body["total_points"] == 0
    assert body["sampled"] is False


async def test_get_projection_umap_without_extra_returns_400(service, monkeypatch) -> None:
    """环境无关：monkeypatch 拦截 umap 的 import——装了 extra 的开发机也走 400 分支。"""
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "umap" or name.startswith("umap."):
            raise ImportError("No module named 'umap'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    client = _client(service)
    kb = _create_kb(client)
    await _seed_chunks(service, kb["id"])

    response = client.get(f"/api/knowledge-bases/{kb['id']}/vector-projection?algo=umap")

    assert response.status_code == 400, response.text
    assert "umap" in response.json()["detail"].lower()


async def test_get_projection_rejects_invalid_dims(service) -> None:
    client = _client(service)
    kb = _create_kb(client)

    response = client.get(f"/api/knowledge-bases/{kb['id']}/vector-projection?dims=4")

    assert response.status_code == 422


async def test_get_projection_unknown_kb_404(service) -> None:
    client = _client(service)

    response = client.get("/api/knowledge-bases/kb-missing/vector-projection")

    assert response.status_code == 404


async def test_get_projection_unknown_collection_400(service) -> None:
    client = _client(service)
    kb = _create_kb(client)

    response = client.get(f"/api/knowledge-bases/{kb['id']}/vector-projection?collections=chunks,bogus")

    assert response.status_code == 400, response.text


async def test_get_projection_refresh_recomputes(service) -> None:
    client = _client(service)
    kb = _create_kb(client)
    await _seed_chunks(service, kb["id"])

    assert client.get(f"/api/knowledge-bases/{kb['id']}/vector-projection").json()["cached"] is False
    assert client.get(f"/api/knowledge-bases/{kb['id']}/vector-projection").json()["cached"] is True
    refreshed = client.get(f"/api/knowledge-bases/{kb['id']}/vector-projection?refresh=true")
    assert refreshed.json()["cached"] is False


async def test_project_query_after_projection_200(service, monkeypatch) -> None:
    class _FakeEmbedder:
        # 真实契约形态（2026-08-19 修复：embed 返回 EmbeddingResult，非裸向量——
        # 旧 fake 与实现漂移导致生产 500 而单测全绿）。
        async def embed(self, texts, *, text_type="document"):
            return [EmbeddingResult(dense=[0.5, 0.5, 0.0, 0.0], sparse=SparseVector(indices=[0], values=[1.0])) for _ in texts]

    # knowledge_service builds its embedder through build_embedder() — patch that seam.
    monkeypatch.setattr(ks_module, "build_embedder", lambda: _FakeEmbedder())
    client = _client(service)
    kb = _create_kb(client)
    await _seed_chunks(service, kb["id"])
    projection = client.get(f"/api/knowledge-bases/{kb['id']}/vector-projection?dims=2").json()

    response = client.post(f"/api/knowledge-bases/{kb['id']}/vector-projection/query", json={"text": "什么是 JVM"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body["x"], float) and isinstance(body["y"], float)
    assert "z" not in body
    assert body["model_version"] == "pca-v1"
    assert body["fingerprint"] == projection["fingerprint"]


async def test_project_query_without_cached_projection_409(service, monkeypatch) -> None:
    class _FakeEmbedder:
        # 真实契约形态（2026-08-19 修复：embed 返回 EmbeddingResult，非裸向量——
        # 旧 fake 与实现漂移导致生产 500 而单测全绿）。
        async def embed(self, texts, *, text_type="document"):
            return [EmbeddingResult(dense=[0.5, 0.5, 0.0, 0.0], sparse=SparseVector(indices=[0], values=[1.0])) for _ in texts]

    monkeypatch.setattr(ks_module, "build_embedder", lambda: _FakeEmbedder())
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(f"/api/knowledge-bases/{kb['id']}/vector-projection/query", json={"text": "问题"})

    assert response.status_code == 409, response.text


async def test_project_query_non_pca_model_409(service, monkeypatch) -> None:
    class _FakeEmbedder:
        # 真实契约形态（2026-08-19 修复：embed 返回 EmbeddingResult，非裸向量——
        # 旧 fake 与实现漂移导致生产 500 而单测全绿）。
        async def embed(self, texts, *, text_type="document"):
            return [EmbeddingResult(dense=[0.5, 0.5, 0.0, 0.0], sparse=SparseVector(indices=[0], values=[1.0])) for _ in texts]

    monkeypatch.setattr(ks_module, "build_embedder", lambda: _FakeEmbedder())
    client = _client(service)
    kb = _create_kb(client)

    # Seed a cache entry whose model is None (the umap shape) via the public API.
    async def _compute() -> CachedProjection:
        return CachedProjection(coords=[], points=(), model=None)

    await service.projection_cache.get_or_compute(
        (kb["id"], "umap", 2, 5000, ("chunks", "entities", "wiki", "cards")),
        fingerprint="fp",
        compute=_compute,
    )

    response = client.post(f"/api/knowledge-bases/{kb['id']}/vector-projection/query?algo=umap", json={"text": "问题"})

    assert response.status_code == 409, response.text
    assert "pca" in response.json()["detail"].lower()


async def test_project_query_blank_text_422(service) -> None:
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(f"/api/knowledge-bases/{kb['id']}/vector-projection/query", json={"text": "   "})

    assert response.status_code == 422
