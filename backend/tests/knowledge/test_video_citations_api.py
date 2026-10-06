"""Contract tests for video timecode citations + keyframe serving (spec 2026-09-08 §4, plan Task 8).

Three surfaces, all read-time joins over ``video_shots`` (zero schema change to
``chunks`` / citations):

- the recall-test citation payload carries ``media``/``shot_index``/``start_ms``/
  ``end_ms``/``frame_url`` for video-shot chunks only — text citations stay
  byte-for-byte untouched (前端旧渲染零回归);
- ``GET /{kb_id}/documents/{doc_id}/shots/{shot_index}/frame`` streams the
  persisted keyframe JPEG behind the document-read auth gate, 404 on any
  missing frame;
- the document list aggregates ``duration_ms`` (last shot's ``end_ms``) +
  ``shot_count`` for video documents only (spec §5 读时聚合，不加列).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.routers import knowledge_bases
from app.gateway.services import knowledge_service as ks_module
from app.gateway.services.knowledge_service import KnowledgeService
from deerflow.knowledge.store import KnowledgeStore

pytestmark = pytest.mark.asyncio

OWNER_ID = str(uuid.UUID(int=1234567890))

#: Minimal JPEG-ish payload — the endpoint streams bytes verbatim, no decode.
_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01fake-keyframe-bytes"


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


async def _make_video_doc(service: KnowledgeService, kb_id: str, *, name: str = "培训.mp4", shots: list[dict] | None = None) -> str:
    """Create a video document row + its ``video_shots`` (+ frame files on disk).

    Bypasses the upload endpoint so the test controls ``storage_path`` (the
    video-suffix判据) and seeds shots directly — the pipeline legs are Task 7's
    concern, here we only need the persisted end state to read against.
    """
    doc_id = uuid.uuid4().hex
    doc_dir = service.data_dir / "knowledge" / kb_id / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / name).write_bytes(b"\x00\x00\x00\x18ftypmp42")
    await service.store.create_document(
        doc_id=doc_id,
        kb_id=kb_id,
        uploader_id=OWNER_ID,
        name=name,
        size_bytes=100,
        storage_path=str(doc_dir / name),
    )
    for shot in shots or []:
        rel = shot.get("keyframe_path")
        if rel:
            frame = doc_dir / rel
            frame.parent.mkdir(parents=True, exist_ok=True)
            frame.write_bytes(_JPEG)
    if shots:
        await service.video_shot_store.bulk_upsert_shots(doc_id, kb_id=kb_id, shots=shots)
    return doc_id


def _mock_impls(monkeypatch, *, vector: dict, graph: dict | None = None, wiki: dict | None = None) -> None:
    monkeypatch.setattr(ks_module, "_hybrid_search_impl", AsyncMock(return_value=vector))
    monkeypatch.setattr(ks_module, "_graph_search_impl", AsyncMock(return_value=graph or {"entities": [], "relations": [], "evidence": [], "message": ""}))
    monkeypatch.setattr(ks_module, "_wiki_search_impl", AsyncMock(return_value=wiki or {"entries": [], "message": ""}))


# ── citation payload join (spec §4) ──────────────────────────────────────


async def test_recall_test_citation_payload_joins_video_shots(service, monkeypatch):
    """Video-shot chunks gain the timecode四字段 + frame_url；text chunks untouched."""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = await _make_video_doc(
        service,
        kb["id"],
        shots=[
            {"shot_index": 0, "start_ms": 0, "end_ms": 5000, "keyframe_path": "frames/shot_0000.jpg"},
            {"shot_index": 1, "start_ms": 5000, "end_ms": 12400},  # 缺帧 → 无 frame_url
        ],
    )
    _mock_impls(
        monkeypatch,
        vector={
            "results": [
                {"chunk_id": f"{doc_id}#0000", "text": "场景：讲师开场", "doc_name": "培训.mp4", "page": None, "heading_path": ["培训.mp4", "镜头 #0"], "score": 0.9},
                {"chunk_id": "textdoc#0002", "text": "文本切片", "doc_name": "手册.md", "page": 3, "heading_path": ["第1章"], "score": 0.8},
            ],
            "message": "检索到 2 条相关切片。",
        },
        graph={
            "entities": [],
            "relations": [],
            "evidence": [{"chunk_id": f"{doc_id}#0001", "text": "口述：……", "doc_name": "培训.mp4", "heading_path": [], "page": None, "score": 0.7}],
            "message": "命中 1 条切片证据。",
        },
    )

    body = client.post(f"/api/knowledge-bases/{kb['id']}/recall-test", json={"query": "开场"}).json()

    vhits = body["paths"]["vector"]["hits"]
    video_hit = vhits[0]
    assert video_hit["media"] == "video"
    assert video_hit["shot_index"] == 0
    assert video_hit["start_ms"] == 0
    assert video_hit["end_ms"] == 5000
    assert video_hit["frame_url"] == f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/shots/0/frame"
    # 文本引用字段一字不动（旧渲染零回归）
    assert video_hit["doc_name"] == "培训.mp4"
    assert video_hit["score"] == 0.9

    text_hit = vhits[1]
    assert "media" not in text_hit
    assert "shot_index" not in text_hit
    assert "frame_url" not in text_hit
    assert text_hit["page"] == 3, "文本引用字段保持原样"

    # 图谱路证据同为 chunk 级引用 → 同样 join；缺帧镜头无 frame_url
    evidence = body["paths"]["graph"]["evidence"][0]
    assert evidence["media"] == "video"
    assert evidence["shot_index"] == 1
    assert evidence["start_ms"] == 5000
    assert evidence["end_ms"] == 12400
    assert "frame_url" not in evidence


async def test_recall_test_video_join_absent_for_non_shot_chunk(service, monkeypatch):
    """A video doc's chunk whose shot_index has no ``video_shots`` row (e.g. an
    empty shot that produced no card) gets no video fields — honest absence."""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = await _make_video_doc(service, kb["id"], shots=[{"shot_index": 0, "start_ms": 0, "end_ms": 5000}])
    _mock_impls(
        monkeypatch,
        vector={"results": [{"chunk_id": f"{doc_id}#0007", "text": "x", "doc_name": "培训.mp4", "page": None, "heading_path": [], "score": 0.5}], "message": "命中 1 条。"},
    )

    hit = client.post(f"/api/knowledge-bases/{kb['id']}/recall-test", json={"query": "x"}).json()["paths"]["vector"]["hits"][0]

    assert "media" not in hit
    assert "frame_url" not in hit


# ── keyframe serving endpoint (spec §4) ──────────────────────────────────


async def test_shot_frame_endpoint_streams_jpeg(service):
    client = _client(service)
    kb = _create_kb(client)
    doc_id = await _make_video_doc(service, kb["id"], shots=[{"shot_index": 0, "start_ms": 0, "end_ms": 5000, "keyframe_path": "frames/shot_0000.jpg"}])

    response = client.get(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/shots/0/frame")

    assert response.status_code == 200, response.text
    assert response.content == _JPEG
    assert response.headers["content-type"].startswith("image/jpeg")


async def test_shot_frame_endpoint_404_matrix(service):
    """缺帧镜头 / 不存在镜头 / 非视频文档 / 磁盘帧丢失 / 穿越 keyframe_path 一律 404。"""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = await _make_video_doc(
        service,
        kb["id"],
        shots=[
            {"shot_index": 0, "start_ms": 0, "end_ms": 5000, "keyframe_path": "frames/shot_0000.jpg"},
            {"shot_index": 1, "start_ms": 5000, "end_ms": 9000},  # 无 keyframe_path
        ],
    )
    base = f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/shots"

    assert client.get(f"{base}/1/frame").status_code == 404, "缺帧镜头 → 404"
    assert client.get(f"{base}/99/frame").status_code == 404, "不存在镜头 → 404"
    # 非视频文档（无 video_shots 行）
    text_doc = uuid.uuid4().hex
    await service.store.create_document(doc_id=text_doc, kb_id=kb["id"], uploader_id=OWNER_ID, name="手册.md", size_bytes=10, storage_path=f"/tmp/{text_doc}/手册.md")
    assert client.get(f"/api/knowledge-bases/{kb['id']}/documents/{text_doc}/shots/0/frame").status_code == 404
    # 不存在的文档
    assert client.get(f"/api/knowledge-bases/{kb['id']}/documents/nope/shots/0/frame").status_code == 404

    # 磁盘帧被删（DB 仍指 keyframe_path）→ 404，不 500
    frame = service.data_dir / "knowledge" / kb["id"] / doc_id / "frames" / "shot_0000.jpg"
    frame.unlink()
    assert client.get(f"{base}/0/frame").status_code == 404


async def test_shot_frame_endpoint_rejects_traversal_keyframe_path(service):
    """A poisoned ``keyframe_path`` escaping the doc dir resolves outside → 404
    (defense-in-depth mirroring the ``files`` route, even though the worker
    only ever writes ``frames/shot_%04d.jpg``)."""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = await _make_video_doc(service, kb["id"], shots=[{"shot_index": 0, "start_ms": 0, "end_ms": 5000, "keyframe_path": "../../secret.jpg"}])
    secret = service.data_dir / "knowledge" / kb["id"] / "secret.jpg"
    secret.write_bytes(_JPEG)

    assert client.get(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/shots/0/frame").status_code == 404


async def test_shot_frame_endpoint_requires_kb_access(service):
    owner_client = _client(service, _owner)
    kb = _create_kb(owner_client)
    doc_id = await _make_video_doc(service, kb["id"], shots=[{"shot_index": 0, "start_ms": 0, "end_ms": 5000, "keyframe_path": "frames/shot_0000.jpg"}])
    stranger = _client(service, _stranger)

    assert stranger.get(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/shots/0/frame").status_code == 403
    assert owner_client.get(f"/api/knowledge-bases/nonexistent/documents/{doc_id}/shots/0/frame").status_code == 404


# ── document list read-time aggregate (spec §5) ──────────────────────────


async def test_document_list_carries_video_duration_and_shot_count(service):
    """视频行带 duration_ms（末镜 end_ms）+ shot_count；文本行不带（payload 不变）。"""
    client = _client(service)
    kb = _create_kb(client)
    video_doc = await _make_video_doc(
        service,
        kb["id"],
        shots=[
            {"shot_index": 0, "start_ms": 0, "end_ms": 5000},
            {"shot_index": 1, "start_ms": 5000, "end_ms": 12400},
        ],
    )
    text_doc = uuid.uuid4().hex
    await service.store.create_document(doc_id=text_doc, kb_id=kb["id"], uploader_id=OWNER_ID, name="手册.md", size_bytes=10, storage_path=f"/tmp/{text_doc}/手册.md")

    listing = client.get(f"/api/knowledge-bases/{kb['id']}/documents").json()
    by_id = {doc["id"]: doc for doc in listing}

    assert by_id[video_doc]["duration_ms"] == 12400
    assert by_id[video_doc]["shot_count"] == 2
    assert "duration_ms" not in by_id[text_doc]
    assert "shot_count" not in by_id[text_doc]


async def test_document_list_omits_video_fields_before_shots_exist(service):
    """视频文档在 materialize 之前（无 video_shots 行）不带 duration_ms/shot_count
    ——读时聚合，数据未就绪则诚实缺省。"""
    client = _client(service)
    kb = _create_kb(client)
    video_doc = await _make_video_doc(service, kb["id"], shots=[])

    (doc,) = client.get(f"/api/knowledge-bases/{kb['id']}/documents").json()

    assert doc["id"] == video_doc
    assert "duration_ms" not in doc
    assert "shot_count" not in doc


# ── chunk list endpoint video join (spec §5, plan Task 10) ────────────────


async def test_list_document_chunks_injects_video_timecode_fields(service):
    """切片抽屉的列表端点为视频镜头 chunk 补时间码四字段 + frame_url（spec §5）
    ——复用 recall-test 同款 join 助手；正文原样（spec §3 嵌入文本契约，无时间码头）。"""
    client = _client(service)
    kb = _create_kb(client)
    doc_id = await _make_video_doc(
        service,
        kb["id"],
        shots=[
            {"shot_index": 0, "start_ms": 0, "end_ms": 5000, "keyframe_path": "frames/shot_0000.jpg"},
            {"shot_index": 1, "start_ms": 5000, "end_ms": 12400},  # 缺帧 → 无 frame_url
        ],
    )
    await service.store.insert_chunks(
        [
            {"chunk_id": f"{doc_id}#0000", "doc_id": doc_id, "kb_id": kb["id"], "chunk_index": 0, "text": "场景：讲师开场"},
            {"chunk_id": f"{doc_id}#0001", "doc_id": doc_id, "kb_id": kb["id"], "chunk_index": 1, "text": "口述：……"},
        ]
    )

    body = client.get(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/chunks").json()
    items = {item["chunk_id"]: item for item in body["items"]}

    shot0 = items[f"{doc_id}#0000"]
    assert shot0["media"] == "video"
    assert shot0["shot_index"] == 0
    assert shot0["start_ms"] == 0
    assert shot0["end_ms"] == 5000
    assert shot0["frame_url"] == f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/shots/0/frame"
    # 正文原样：chunks.text 不含时间码头（spec §3），时间码由展示层合成
    assert shot0["text"] == "场景：讲师开场"

    shot1 = items[f"{doc_id}#0001"]
    assert shot1["start_ms"] == 5000
    assert shot1["end_ms"] == 12400
    assert "frame_url" not in shot1, "缺帧镜头无 frame_url（spec §2 降级）"


async def test_list_document_chunks_text_doc_untouched(service):
    """文本文档的 chunk 不带任何视频字段（前端旧渲染零回归）。"""
    client = _client(service)
    kb = _create_kb(client)
    text_doc = uuid.uuid4().hex
    await service.store.create_document(doc_id=text_doc, kb_id=kb["id"], uploader_id=OWNER_ID, name="手册.md", size_bytes=10, storage_path=f"/tmp/{text_doc}/手册.md")
    await service.store.insert_chunks(
        [
            {"chunk_id": f"{text_doc}#0000", "doc_id": text_doc, "kb_id": kb["id"], "chunk_index": 0, "text": "文本切片", "page": 3},
        ]
    )

    (item,) = client.get(f"/api/knowledge-bases/{kb['id']}/documents/{text_doc}/chunks").json()["items"]

    assert "media" not in item
    assert "shot_index" not in item
    assert "frame_url" not in item
    assert item["page"] == 3, "文本 chunk 字段保持原样"
