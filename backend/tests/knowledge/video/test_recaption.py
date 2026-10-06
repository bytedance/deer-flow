"""Recaption ops re-run entry (spec 2026-09-08 §2 运维重跑入口, plan Task 8b).

caption 模型/prompt 升级后的类比 ``re_extract_chunk`` / ``regenerate_wiki_entries``
运维血统入口：重置 ``caption_status``（done/failed → pending，empty 保持）→ 只重跑
caption + materialize 子集腿（帧/ASR/segment 跳过，产物已持久化）→ **仅变更 chunk**
增量重嵌向量 → 受影响实体标 wiki dirty（复用 ``mark_dirty_for_entities``，不重抽图谱）。
与在飞管线互斥（409）；非视频文档 404。

Service/worker 层用真实 SQLite + fake 媒体腿（编排契约，非各腿内部逻辑——Task 3–7
单测已覆盖）；router 层用 TestClient 验 202/409/404/403 映射。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from qdrant_client.models import SparseVector

from app.gateway.auth.models import User
from app.gateway.routers import knowledge_bases
from app.gateway.services.knowledge_service import (
    DocumentProcessingError,
    KnowledgeService,
    NotVideoDocumentError,
)
from deerflow.knowledge.embedder import EmbeddingResult
from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.video.captioner import CaptionOutcome
from deerflow.knowledge.video.store import VideoShotStore
from deerflow.knowledge.wiki.store import WikiStore
from deerflow.knowledge.worker import KnowledgeIndexWorker

pytestmark = pytest.mark.asyncio

OWNER_ID = str(uuid.UUID(int=1234567890))


def _owner() -> User:
    return User(email="owner@example.com", password_hash="x", system_role="user", id=uuid.UUID(OWNER_ID))


def _stranger() -> User:
    return User(email="stranger@example.com", password_hash="x", system_role="user", id=uuid.UUID(int=987654321))


# ── fakes ────────────────────────────────────────────────────────────────


class SpyEmbedder:
    """记录被嵌入的文本——「仅变更 chunk 重嵌」断言的数据源。"""

    batch_size = 20

    def __init__(self) -> None:
        self.embedded: list[str] = []

    async def embed(self, texts, *, text_type: str = "document"):
        self.embedded.extend(texts)
        return [EmbeddingResult(dense=[0.01 * (i + 1)] * 8, sparse=SparseVector(indices=[i + 1], values=[0.5])) for i, _ in enumerate(texts)]


class FakeLLM:
    async def ainvoke(self, messages):
        return SimpleNamespace(content='{"entities": [], "relations": []}')


def _vs_mock() -> MagicMock:
    vs = MagicMock()
    vs.init_collections = AsyncMock()
    vs.upsert_chunks = AsyncMock(return_value=0)
    vs.upsert_entities = AsyncMock(return_value=0)
    vs.set_chunk_entities = AsyncMock()
    vs.delete_by_doc = AsyncMock()
    vs.delete_chunks = AsyncMock()
    vs.delete_entities = AsyncMock()
    return vs


def _video_config(**overrides):
    video = SimpleNamespace(
        max_shot_seconds=5.0,
        fallback_window_seconds=10.0,
        keyframes_per_shot=1,
        asr_provider="funasr",
        asr_model="paraformer-zh",
        card_text_mode="full",
        **overrides,
    )
    return SimpleNamespace(rag=SimpleNamespace(video=video, worker_concurrency=2, extract_concurrency=1, vlm_model="test-vlm"))


def _fake_media_legs(monkeypatch, *, caption: CaptionOutcome) -> dict[str, int]:
    """monkeypatch worker 模块级媒体腿为 fake；返回调用计数（子集腿跳过断言用）。

    recaption 只应触发 caption 腿（extract_caption_frames + caption_shots）；
    probe/asr/segment/keyframe 必须零调用（产物已持久化）。
    """
    import deerflow.knowledge.worker as w

    calls = {"probe": 0, "asr": 0, "cuts": 0, "keyframes": 0, "caption_frames": 0, "caption": 0}

    async def _probe(path, **kw):
        calls["probe"] += 1
        raise AssertionError("recaption must not re-run probe")

    async def _asr(path, **kw):
        calls["asr"] += 1
        raise AssertionError("recaption must not re-run asr")

    def _cuts(path):
        calls["cuts"] += 1
        raise AssertionError("recaption must not re-run segment detection")

    async def _keyframes(video_path, shots, doc_dir, **kw):
        calls["keyframes"] += 1
        raise AssertionError("recaption must not re-extract keyframes")

    async def _caption_frames(video_path, start_ms, end_ms, **kw):
        calls["caption_frames"] += 1
        return [b"\xff\xd8frame"]

    async def _caption(shot_frames, **kw):
        calls["caption"] += 1
        return caption

    monkeypatch.setattr(w, "probe_video", _probe)
    monkeypatch.setattr(w, "transcribe_video", _asr)
    monkeypatch.setattr(w, "_detect_scene_cuts", _cuts)
    monkeypatch.setattr(w, "extract_keyframes", _keyframes)
    monkeypatch.setattr(w, "extract_caption_frames", _caption_frames)
    monkeypatch.setattr(w, "caption_shots", _caption)
    monkeypatch.setattr(w, "get_app_config", lambda: _video_config())
    return calls


# ── seeding helpers ──────────────────────────────────────────────────────


async def _seed_video_doc(store, vstore, data_dir, *, doc_id, kb_id, name="clip.mp4", status="ready", shots=None, chunks=None):
    """造一个视频文档行（storage_path 后缀 .mp4）+ per-doc 目录 + 可选 shots/chunks。"""
    doc_dir = data_dir / "knowledge" / kb_id / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / name).write_bytes(b"video-placeholder")
    await store.create_document(doc_id=doc_id, kb_id=kb_id, uploader_id=OWNER_ID, name=name, size_bytes=17, storage_path=str(doc_dir / name))
    if status != "uploaded":
        await store.update_document_status(doc_id, status, progress_percent=100 if status == "ready" else 0, chunk_count=len(chunks or []))
    if shots:
        await vstore.bulk_upsert_shots(doc_id, kb_id=kb_id, shots=shots)
    if chunks:
        await store.insert_chunks(chunks)
    return doc_id


def _shot(index, start, end, *, caption="", asr="", ocr="", status="done", keyframe="frames/shot.jpg"):
    return {"shot_index": index, "start_ms": start, "end_ms": end, "caption": caption, "asr_text": asr, "ocr_text": ocr, "caption_status": status, "keyframe_path": keyframe}


def _chunk(doc_id, kb_id, index, text, *, entities=None):
    return {
        "chunk_id": f"{doc_id}#{index:04d}",
        "doc_id": doc_id,
        "kb_id": kb_id,
        "chunk_index": index,
        "text": text,
        "heading_path": ["clip.mp4", f"镜头 #{index}"],
        "page": None,
        "token_count": max(1, len(text)),
        "entities": entities or [],
    }


# ── service fixture (mock worker) ────────────────────────────────────────


@pytest.fixture
def service(session_factory, tmp_path) -> KnowledgeService:
    vector_store = _vs_mock()
    vector_store.delete_by_kb = AsyncMock()
    vector_store.delete_wiki_entries = AsyncMock()
    worker = MagicMock()
    worker.submit_recaption = AsyncMock()
    return KnowledgeService(
        store=KnowledgeStore(session_factory),
        vector_store=vector_store,
        graph_store=None,
        wiki_store=None,
        worker=worker,
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


# ── service: reset matrix + gating ───────────────────────────────────────


async def test_trigger_recaption_resets_done_and_failed_keeps_empty(service):
    """重置矩阵：done/failed → pending（重跑），empty 保持（三路俱空，重跑无意义）。"""
    await service.store.create_kb(kb_id="kb-1", owner_id=OWNER_ID, name="k")
    doc_id = uuid.uuid4().hex
    await _seed_video_doc(
        service.store,
        service.video_shot_store,
        service.data_dir,
        doc_id=doc_id,
        kb_id="kb-1",
        shots=[_shot(0, 0, 5000, caption="旧", status="done"), _shot(1, 5000, 9000, status="failed"), _shot(2, 9000, 12000, status="empty")],
    )

    result = await service.trigger_recaption(kb_id="kb-1", doc_id=doc_id)

    assert result == {"status": "enqueued", "reset_shots": 2}
    by_index = {s["shot_index"]: s["caption_status"] for s in await service.video_shot_store.list_shots(doc_id)}
    assert by_index == {0: "pending", 1: "pending", 2: "empty"}
    service.worker.submit_recaption.assert_awaited_once_with(doc_id)
    # 同步翻状态标记在飞（镜像 retry 的 status flip）→ 二次触发 409
    assert (await service.store.get_document(doc_id))["status"] == "parsing"


async def test_trigger_recaption_conflicts_with_in_flight_pipeline(service):
    """与在飞管线互斥：文档处于非终态（indexing）→ DocumentProcessingError（router 409）。"""
    await service.store.create_kb(kb_id="kb-1", owner_id=OWNER_ID, name="k")
    doc_id = uuid.uuid4().hex
    await _seed_video_doc(service.store, service.video_shot_store, service.data_dir, doc_id=doc_id, kb_id="kb-1", status="indexing", shots=[_shot(0, 0, 5000)])

    with pytest.raises(DocumentProcessingError):
        await service.trigger_recaption(kb_id="kb-1", doc_id=doc_id)
    service.worker.submit_recaption.assert_not_awaited()


async def test_trigger_recaption_rejects_non_video_document(service):
    """非视频文档 → NotVideoDocumentError（router 404）。"""
    await service.store.create_kb(kb_id="kb-1", owner_id=OWNER_ID, name="k")
    doc_id = uuid.uuid4().hex
    await service.store.create_document(doc_id=doc_id, kb_id="kb-1", uploader_id=OWNER_ID, name="手册.md", size_bytes=10, storage_path=f"/tmp/{doc_id}/手册.md")
    await service.store.update_document_status(doc_id, "ready")

    with pytest.raises(NotVideoDocumentError):
        await service.trigger_recaption(kb_id="kb-1", doc_id=doc_id)


async def test_trigger_recaption_returns_none_for_missing_or_cross_kb(service):
    """不存在 / 跨库文档 → None（router 404）。"""
    await service.store.create_kb(kb_id="kb-1", owner_id=OWNER_ID, name="k")
    assert await service.trigger_recaption(kb_id="kb-1", doc_id="nope") is None
    doc_id = uuid.uuid4().hex
    await _seed_video_doc(service.store, service.video_shot_store, service.data_dir, doc_id=doc_id, kb_id="kb-1", shots=[_shot(0, 0, 5000)])
    assert await service.trigger_recaption(kb_id="other-kb", doc_id=doc_id) is None


# ── worker: subset legs + incremental re-embed + wiki dirty ──────────────


async def test_recaption_skips_media_legs_and_reembeds_only_changed(session_factory, tmp_path, monkeypatch):
    """子集腿：probe/asr/segment/keyframe 零调用；仅文本变更的 chunk 重嵌。"""
    store = KnowledgeStore(session_factory)
    vstore = VideoShotStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    # 两镜头均 pending（模拟 service 已重置）；镜头1 的 caption 重跑后与旧值相同
    # → 卡正文不变 → 不重嵌（「仅变更 chunk 重嵌」的核心断言）。
    await _seed_video_doc(
        store,
        vstore,
        tmp_path,
        doc_id="doc-v",
        kb_id="kb-1",
        shots=[
            _shot(0, 0, 5000, caption="旧0", asr="你好", ocr="A", status="pending"),
            _shot(1, 5000, 10000, caption="保持1", asr="世界", ocr="B", status="pending"),
        ],
        chunks=[
            _chunk("doc-v", "kb-1", 0, "场景：旧0\n口述：你好\n屏幕文字：A", entities=["Alpha"]),
            _chunk("doc-v", "kb-1", 1, "场景：保持1\n口述：世界\n屏幕文字：B"),
        ],
    )
    calls = _fake_media_legs(monkeypatch, caption=CaptionOutcome(captions={0: "新0", 1: "保持1"}, failed=0, degraded=False))
    spy = SpyEmbedder()
    worker = KnowledgeIndexWorker(store=store, vector_store=_vs_mock(), embedder=spy, llm=FakeLLM())

    await worker.recaption_document("doc-v")

    assert calls["probe"] == 0 and calls["asr"] == 0 and calls["cuts"] == 0 and calls["keyframes"] == 0
    assert calls["caption_frames"] >= 1, "caption 腿仍抽临时帧（≤3 帧，非持久化关键帧）"
    # 仅 chunk0 文本变更 → 只它被重嵌；chunk1 正文未变 → 不进 embedder
    assert spy.embedded == ["场景：新0\n口述：你好\n屏幕文字：A"]
    doc = await store.get_document("doc-v")
    assert doc["status"] == "ready"
    assert doc["progress_percent"] == 100
    chunks = await store.list_chunks("doc-v", limit=10)
    assert chunks[0]["text"] == "场景：新0\n口述：你好\n屏幕文字：A"
    assert chunks[1]["text"] == "场景：保持1\n口述：世界\n屏幕文字：B"
    # 实体列保持（图谱腿不重跑）
    assert chunks[0]["entities"] == ["Alpha"]


async def test_recaption_config_error_keeps_the_old_content_and_marks_caption_failed(session_factory, tmp_path, monkeypatch):
    """spec 2026-09-23 D10.5: a target its entry cannot serve is caught inside recaption.

    The old captions/chunks/vectors stay (recaption is an enhancement, never destructive), the
    document keeps ready/100, this pass records ``caption=failed`` plus the sanitized reason,
    and nothing is left ``indexing``. The call returns normally, which is what frees the video
    side's in-flight slot — that side releases through a done-callback, not a ``finally``.
    """
    import json

    import deerflow.knowledge.worker as w
    from deerflow.config.app_config import AppConfig, RagConfig
    from deerflow.config.model_config import ModelConfig
    from deerflow.config.sandbox_config import SandboxConfig

    store = KnowledgeStore(session_factory)
    vstore = VideoShotStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await _seed_video_doc(
        store,
        vstore,
        tmp_path,
        doc_id="doc-v",
        kb_id="kb-1",
        shots=[_shot(0, 0, 5000, caption="旧0", asr="你好", ocr="A", status="pending")],
        chunks=[_chunk("doc-v", "kb-1", 0, "场景：旧0\n口述：你好\n屏幕文字：A", entities=["Alpha"])],
    )
    entry = ModelConfig(name="vl-entry", display_name="vl-entry", description=None, use="langchain_openai:ChatOpenAI", model="vl-wire", base_url="https://ui.example/v1", supports_thinking=False)
    config = AppConfig(models=[entry], sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"), rag=RagConfig(vlm_model="vl-entry"))
    config._ui_model_names = {"vl-entry"}  # keyless on purpose: the declared target is refused

    async def _frames(video_path, start_ms, end_ms, **kw):
        return [b"\xff\xd8frame"]

    monkeypatch.setattr(w, "extract_caption_frames", _frames)
    monkeypatch.setattr(w, "get_app_config", lambda: config)
    # The caption leg resolves through its own module's name — patching the worker's is not enough.
    monkeypatch.setattr("deerflow.knowledge.video.captioner.get_app_config", lambda: config)
    worker = KnowledgeIndexWorker(store=store, vector_store=_vs_mock(), embedder=SpyEmbedder(), llm=FakeLLM())

    await worker.recaption_document("doc-v")

    doc = await store.get_document("doc-v")
    assert doc["status"] == "ready"
    assert doc["progress_percent"] == 100
    assert doc["path_status"]["caption"] == "failed"  # this pass's verdict, not the leg's "indexing"
    assert "api_key" in doc["error"]  # the sanitized reason, appended as a marker
    assert "indexing" not in json.dumps(doc["path_status"])
    shots = await vstore.list_shots("doc-v")
    assert shots[0]["caption"] == "旧0"  # old content untouched
    chunks = await store.list_chunks("doc-v", limit=10)
    assert chunks[0]["text"] == "场景：旧0\n口述：你好\n屏幕文字：A"
    assert chunks[0]["entities"] == ["Alpha"]


async def test_recaption_marks_affected_entities_wiki_dirty(session_factory, tmp_path, monkeypatch):
    """变更 chunk 引用的实体 → 其 wiki 条目标 dirty（复用 mark_dirty_for_entities）。"""
    store = KnowledgeStore(session_factory)
    vstore = VideoShotStore(session_factory)
    wiki = WikiStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await _seed_video_doc(
        store,
        vstore,
        tmp_path,
        doc_id="doc-v",
        kb_id="kb-1",
        shots=[_shot(0, 0, 5000, caption="旧0", asr="你好", ocr="A", status="pending")],
        chunks=[_chunk("doc-v", "kb-1", 0, "场景：旧0\n口述：你好\n屏幕文字：A", entities=["Alpha"])],
    )
    await wiki.upsert_entry("kb-1", title="Alpha", content="# Alpha", source_chunk_ids=["doc-v#0000"], status="ready")
    _fake_media_legs(monkeypatch, caption=CaptionOutcome(captions={0: "新0"}, failed=0, degraded=False))
    worker = KnowledgeIndexWorker(store=store, vector_store=_vs_mock(), embedder=SpyEmbedder(), llm=FakeLLM(), wiki_store=wiki)

    await worker.recaption_document("doc-v")

    entries = await wiki.list_entries("kb-1")
    assert [(e["title"], e["status"]) for e in entries] == [("Alpha", "dirty")]


# ── router: HTTP mapping ─────────────────────────────────────────────────


async def test_recaption_endpoint_returns_202_and_enqueues(service):
    client = _client(service)
    kb = _create_kb(client)
    doc_id = uuid.uuid4().hex
    await _seed_video_doc(service.store, service.video_shot_store, service.data_dir, doc_id=doc_id, kb_id=kb["id"], shots=[_shot(0, 0, 5000, caption="旧", status="done")])

    response = client.post(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/video/recaption")

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "enqueued"
    service.worker.submit_recaption.assert_awaited_once_with(doc_id)


async def test_recaption_endpoint_409_in_flight(service):
    client = _client(service)
    kb = _create_kb(client)
    doc_id = uuid.uuid4().hex
    await _seed_video_doc(service.store, service.video_shot_store, service.data_dir, doc_id=doc_id, kb_id=kb["id"], status="indexing", shots=[_shot(0, 0, 5000)])

    assert client.post(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/video/recaption").status_code == 409


async def test_recaption_endpoint_404_non_video_and_missing(service):
    client = _client(service)
    kb = _create_kb(client)
    text_doc = uuid.uuid4().hex
    await service.store.create_document(doc_id=text_doc, kb_id=kb["id"], uploader_id=OWNER_ID, name="手册.md", size_bytes=10, storage_path=f"/tmp/{text_doc}/手册.md")
    await service.store.update_document_status(text_doc, "ready")

    assert client.post(f"/api/knowledge-bases/{kb['id']}/documents/{text_doc}/video/recaption").status_code == 404
    assert client.post(f"/api/knowledge-bases/{kb['id']}/documents/nope/video/recaption").status_code == 404


async def test_recaption_endpoint_requires_kb_access(service):
    owner_client = _client(service, _owner)
    kb = _create_kb(owner_client)
    doc_id = uuid.uuid4().hex
    await _seed_video_doc(service.store, service.video_shot_store, service.data_dir, doc_id=doc_id, kb_id=kb["id"], shots=[_shot(0, 0, 5000)])
    stranger = _client(service, _stranger)

    assert stranger.post(f"/api/knowledge-bases/{kb['id']}/documents/{doc_id}/video/recaption").status_code == 403
    assert owner_client.post(f"/api/knowledge-bases/nonexistent/documents/{doc_id}/video/recaption").status_code == 404
