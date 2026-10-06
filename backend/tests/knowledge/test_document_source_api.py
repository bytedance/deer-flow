"""Contract tests for the document source download endpoint (2026-09-10).

``GET /{kb_id}/documents/{doc_id}/source`` serves the original uploaded file
(round-trip export): the bytes persisted at upload time, under the document's
stored name via ``Content-Disposition``. The route takes no user-supplied path
segment — it serves exactly the row's ``storage_path`` — so traversal is
structurally impossible. Auth mirrors document read (``_require_kb_access``:
404 missing kb / 403 non-owner); a source gone off disk is a plain 404.
"""

from __future__ import annotations

import uuid
from pathlib import Path
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

#: Known bytes so the round-trip assertion is byte-exact.
_SOURCE_BYTES = b"raw source bytes \x00\x01\x02"


def _owner() -> User:
    return User(email="owner@example.com", password_hash="x", system_role="user", id=uuid.UUID(OWNER_ID))


def _stranger() -> User:
    return User(email="stranger@example.com", password_hash="x", system_role="user", id=uuid.UUID(int=987654321))


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


def _client(service: KnowledgeService, user_factory=_owner) -> TestClient:
    app = make_authed_test_app(user_factory=user_factory)
    app.state.knowledge_service = service
    app.include_router(knowledge_bases.router)
    return TestClient(app)


def _create_kb(client: TestClient, name: str = "资料库") -> dict:
    response = client.post("/api/knowledge-bases", json={"name": name, "description": "d"})
    assert response.status_code == 201, response.text
    return response.json()


async def _make_doc(service: KnowledgeService, kb_id: str, *, name: str = "报告.pdf", payload: bytes = _SOURCE_BYTES) -> str:
    """Create a document row whose ``storage_path`` is a real file on disk.

    Bypasses upload so the test controls the exact bytes and name.
    """
    doc_id = uuid.uuid4().hex
    doc_dir = service.data_dir / "knowledge" / kb_id / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / name).write_bytes(payload)
    await service.store.create_document(
        doc_id=doc_id,
        kb_id=kb_id,
        uploader_id=OWNER_ID,
        name=name,
        size_bytes=len(payload),
        storage_path=str(doc_dir / name),
    )
    return doc_id


async def test_source_download_returns_original_bytes_and_filename(service: KnowledgeService) -> None:
    client = _client(service)
    kb = _create_kb(client)
    doc_id = await _make_doc(service, kb["id"])

    response = client.get(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/source")
    assert response.status_code == 200, response.text
    assert response.content == _SOURCE_BYTES
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert "报告.pdf" in disposition or "%E6%8A%A5%E5%91%8A" in disposition


async def test_source_download_denies_stranger(service: KnowledgeService) -> None:
    client = _client(service)
    kb = _create_kb(client)
    doc_id = await _make_doc(service, kb["id"])

    stranger = _client(service, user_factory=_stranger)
    response = stranger.get(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/source")
    assert response.status_code == 403


async def test_source_download_404_when_file_off_disk(service: KnowledgeService) -> None:
    client = _client(service)
    kb = _create_kb(client)
    doc_id = await _make_doc(service, kb["id"])
    doc = await service.store.get_document(doc_id)
    Path(doc["storage_path"]).unlink()

    response = client.get(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/source")
    assert response.status_code == 404


async def test_source_download_404_for_document_of_other_kb(service: KnowledgeService) -> None:
    client = _client(service)
    kb = _create_kb(client, "甲库")
    other = _create_kb(client, "乙库")
    doc_id = await _make_doc(service, kb["id"])

    response = client.get(f"/api/knowledge-bases/{other['id']}/documents/{doc_id}/source")
    assert response.status_code == 404
