"""Contract tests for the video stream endpoint (spec 2026-09-08 §4/§5, plan Task 10b).

``GET /{kb_id}/documents/{doc_id}/video/stream`` serves the source video for the
chunk drawer's inline ``<video>`` player. Starlette ≥1.3 ``FileResponse``
negotiates HTTP Range natively (200 full / 206 partial with ``Content-Range`` /
416 unsatisfiable / 400 malformed), streaming through anyio so a large file never
blocks the event loop — so the router just hands it the resolved path. These
tests pin the end-to-end contract the player relies on, plus the one piece
FileResponse guesses at: the suffix → Content-Type map for the frozen video set
(``mimetypes.guess_type`` is platform-dependent and unreliable for ``.mkv``).
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
from deerflow.knowledge.video.streaming import content_type_for_video

pytestmark = pytest.mark.asyncio

OWNER_ID = str(uuid.UUID(int=1234567890))

#: 20 bytes of known content so partial-range assertions are byte-exact.
_VIDEO_BYTES = bytes(range(20))


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


def _create_kb(client: TestClient, name: str = "视频库") -> dict:
    response = client.post("/api/knowledge-bases", json={"name": name, "description": "d"})
    assert response.status_code == 201, response.text
    return response.json()


async def _make_video_doc(service: KnowledgeService, kb_id: str, *, name: str = "培训.mp4", payload: bytes = _VIDEO_BYTES) -> str:
    """Create a video document row whose ``storage_path`` is a real file on disk.

    Bypasses upload so the test controls the suffix (the video-stream判据) and the
    exact bytes (for byte-precise range assertions).
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


# ── suffix → Content-Type pure helper ──────────────────────────────────────


def test_content_type_for_video_maps_frozen_set():
    assert content_type_for_video(".mp4") == "video/mp4"
    assert content_type_for_video(".mov") == "video/quicktime"
    assert content_type_for_video(".mkv") == "video/x-matroska"
    assert content_type_for_video(".webm") == "video/webm"


def test_content_type_for_video_is_case_insensitive_and_total():
    assert content_type_for_video(".MP4") == "video/mp4"
    # 未映射后缀回落 octet-stream（router 已按视频集门禁，此处只保证函数全定义）。
    assert content_type_for_video(".avi") == "application/octet-stream"


# ── stream endpoint (spec §4/§5) ───────────────────────────────────────────


async def test_stream_serves_full_body_200(service):
    client = _client(service)
    kb = _create_kb(client)
    doc_id = await _make_video_doc(service, kb["id"])

    response = client.get(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/video/stream")

    assert response.status_code == 200, response.text
    assert response.content == _VIDEO_BYTES
    assert response.headers["content-type"] == "video/mp4"
    # FileResponse 声明可 Range，播放器据此发分段请求。
    assert response.headers["accept-ranges"] == "bytes"


async def test_stream_partial_206_content_range(service):
    client = _client(service)
    kb = _create_kb(client)
    doc_id = await _make_video_doc(service, kb["id"])

    response = client.get(
        f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/video/stream",
        headers={"Range": "bytes=0-4"},
    )

    assert response.status_code == 206, response.text
    assert response.content == bytes(range(5))
    assert response.headers["content-range"] == f"bytes 0-4/{len(_VIDEO_BYTES)}"
    assert response.headers["content-length"] == "5"


async def test_stream_unsatisfiable_range_416(service):
    client = _client(service)
    kb = _create_kb(client)
    doc_id = await _make_video_doc(service, kb["id"])

    response = client.get(
        f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/video/stream",
        headers={"Range": "bytes=100-"},
    )

    assert response.status_code == 416, response.text
    assert response.headers["content-range"] == f"bytes */{len(_VIDEO_BYTES)}"


async def test_stream_404_for_non_video_and_missing(service):
    client = _client(service)
    kb = _create_kb(client)
    # 非视频文档（后缀 ∉ VIDEO_UPLOAD_SUFFIXES）→ 404，不泄露为可流。
    text_doc = uuid.uuid4().hex
    await service.store.create_document(
        doc_id=text_doc,
        kb_id=kb["id"],
        uploader_id=OWNER_ID,
        name="手册.md",
        size_bytes=10,
        storage_path=f"/tmp/{text_doc}/手册.md",
    )
    assert client.get(f"/api/knowledge-bases/{kb['id']}/documents/{text_doc}/video/stream").status_code == 404
    # 不存在的文档 → 404
    assert client.get(f"/api/knowledge-bases/{kb['id']}/documents/nope/video/stream").status_code == 404


async def test_stream_requires_kb_access(service):
    owner_client = _client(service, _owner)
    kb = _create_kb(owner_client)
    doc_id = await _make_video_doc(service, kb["id"])
    stranger = _client(service, _stranger)

    assert stranger.get(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/video/stream").status_code == 403
