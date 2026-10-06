"""Contract tests for POST /api/knowledge-bases/{kb_id}/chunk-positions.

批量 chunk_id → 文档内存活位次（chunk_index 升序，空洞不占位）——图谱实体
抽屉行内「切片 #K」与向量空间跳转定位的数据源，与 recall-test 的
chunk_position 注入同源（store.chunk_positions），词汇与切片总览抽屉 #K 一致。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.routers import knowledge_bases
from app.gateway.services.knowledge_service import KnowledgeService
from deerflow.knowledge.store import KnowledgeStore

pytestmark = pytest.mark.asyncio

OWNER_ID = str(uuid.UUID(int=1234567890))


def _owner() -> User:
    return User(email="owner@example.com", password_hash="x", system_role="user", id=uuid.UUID(OWNER_ID))


@pytest.fixture
def service(session_factory, tmp_path) -> KnowledgeService:
    vector_store = MagicMock()
    vector_store.delete_by_doc = AsyncMock()
    vector_store.delete_by_kb = AsyncMock()
    vector_store.delete_entities = AsyncMock()
    return KnowledgeService(
        store=KnowledgeStore(session_factory),
        vector_store=vector_store,
        graph_store=None,
        wiki_store=None,
        worker=None,
        data_dir=tmp_path,
    )


def _client(service: KnowledgeService) -> TestClient:
    app = make_authed_test_app(user_factory=_owner)
    app.state.knowledge_service = service
    app.include_router(knowledge_bases.router)
    return TestClient(app)


def _create_kb(client: TestClient) -> dict:
    response = client.post("/api/knowledge-bases", json={"name": "产品资料", "description": "d"})
    assert response.status_code == 201, response.text
    return response.json()


async def test_chunk_positions_maps_ids_to_live_positions(service):
    """存活位次映射：空洞不占位（#0002 已删 → #0003 位次是 3 不是 4）；
    畸形 id 与不存在文档的切片缺键（前端诚实缺省不显）。"""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = "d" * 32
    await service.store.create_document(doc_id=doc_id, kb_id=kb["id"], uploader_id=OWNER_ID, name="hole.md", size_bytes=1, storage_path="p")
    await service.store.insert_chunks([{"chunk_id": f"{doc_id}#000{i}", "doc_id": doc_id, "kb_id": kb["id"], "chunk_index": i, "text": text} for i, text in [(0, "a"), (1, "b"), (3, "d")]])
    ghost_id = f"{'e' * 32}#0000"
    response = client.post(
        f"/api/knowledge-bases/{kb['id']}/chunk-positions",
        json={
            "chunk_ids": [
                f"{doc_id}#0000",
                f"{doc_id}#0001",
                f"{doc_id}#0002",
                f"{doc_id}#0003",
                "malformed",
                ghost_id,
            ]
        },
    )
    assert response.status_code == 200, response.text
    positions = response.json()["positions"]
    assert positions[f"{doc_id}#0000"] == 1
    assert positions[f"{doc_id}#0001"] == 2
    assert positions[f"{doc_id}#0003"] == 3
    assert f"{doc_id}#0002" not in positions
    assert "malformed" not in positions
    assert ghost_id not in positions


async def test_chunk_positions_empty_body_returns_empty_map(service):
    client = _client(service)
    kb = _create_kb(client)
    response = client.post(f"/api/knowledge-bases/{kb['id']}/chunk-positions", json={"chunk_ids": []})
    assert response.status_code == 200, response.text
    assert response.json() == {"positions": {}}
