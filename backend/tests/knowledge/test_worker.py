"""Tests for the async indexing worker (spec §3.6/§3.7).

The worker drives one document through the status machine
``uploaded → parsing → chunking → indexing → ready`` (or ``failed`` with the
error persisted), caps concurrency with a semaphore, and on startup
re-enqueues non-terminal documents.

Tests run fully offline: fake parser/embedder, a mocked vector store, and
a real SQLite database (slice status persistence is the point under test).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from qdrant_client.models import SparseVector

from deerflow.knowledge.captioner import CaptionOutcome
from deerflow.knowledge.embedder import EmbeddingResult
from deerflow.knowledge.parser import ParsedDocument, ParsedImage
from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.worker import KnowledgeIndexWorker

SAMPLE_MD = """# 第一章 概述

DeerFlow 是超级智能体系统，Gateway 负责会话管理。

## 1.1 架构

索引流水线由 Parser 与 Chunker 组成，Chunker 按标题切片。
"""

#: Two sections each exceeding the chunker's merge threshold (>100 tokens), so
#: DeerFlow lands in two chunks — the partial-batch case below needs two.
TWO_CHUNK_MD = """# 第一章 DeerFlow 概述

DeerFlow 是超级智能体系统，负责编排规划、工具调用与沙箱执行。DeerFlow 的设计目标是让复杂任务在多代理协作下自动完成，
DeerFlow 的核心环路包含规划、执行、观察与再规划四个阶段，DeerFlow 通过网关对外提供统一的会话入口与流式响应，
DeerFlow 的运行时状态全部落盘以便断点续跑，DeerFlow 的每一次工具调用都带有完整的审计记录，DeerFlow 支持技能扩展与多渠道接入。

## 1.1 DeerFlow 架构

DeerFlow 的索引流水线由 Parser 与 Chunker 组成，Chunker 按标题切片。DeerFlow 的图谱路从切片中抽取实体与关系并做归一化合并，
DeerFlow 的向量路把切片嵌入到向量库供召回排序，DeerFlow 的百科路为重要实体撰写百科条目，DeerFlow 的三路检索在问答期协同，
DeerFlow 的引用系统为每个论断提供来源编号，DeerFlow 的权限模型保证知识库级隔离与访问门禁。
"""


class FakeEmbedder:
    batch_size = 20

    async def embed(self, texts, *, text_type: str = "document"):
        return [EmbeddingResult(dense=[0.01 * (i + 1)] * 1024, sparse=SparseVector(indices=[i + 1], values=[0.5])) for i, _ in enumerate(texts)]


def _vector_store_mock() -> MagicMock:
    vs = MagicMock()
    vs.init_collections = AsyncMock()
    vs.upsert_chunks = AsyncMock(return_value=0)
    vs.delete_by_doc = AsyncMock()
    return vs


def _parse_fn(md: str = SAMPLE_MD, fail: Exception | None = None, seen_statuses: list[str] | None = None, store: KnowledgeStore | None = None, doc_id: str | None = None):
    async def _parse(path: str) -> ParsedDocument:
        if fail is not None:
            raise fail
        if seen_statuses is not None and store is not None and doc_id is not None:
            doc = await store.get_document(doc_id)
            seen_statuses.append(doc["status"])
        return ParsedDocument(markdown=md, images=[])

    return _parse


def _worker(store, session_factory, **kwargs) -> KnowledgeIndexWorker:
    kwargs.setdefault("vector_store", _vector_store_mock())
    kwargs.setdefault("embedder", FakeEmbedder())
    kwargs.setdefault("concurrency", 2)
    return KnowledgeIndexWorker(store=store, **kwargs)


@pytest.mark.asyncio
async def test_pipeline_advances_status_machine_to_ready(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")
    seen: list[str] = []
    worker = _worker(store, session_factory, parse_fn=_parse_fn(seen_statuses=seen, store=store, doc_id="doc-1"))

    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "ready"
    assert doc["progress_percent"] == 100
    # both heading blocks are small (<100 tokens) so the chunker merges them into one
    assert doc["chunk_count"] == 1
    assert seen == ["parsing"], "parse must run after the status advances to parsing"
    # vector path wrote the chunk points
    assert worker._vector_store.upsert_chunks.await_count >= 1


@pytest.mark.asyncio
async def test_parsed_images_are_persisted_next_to_document(session_factory, tmp_path, monkeypatch):
    """解析出的图片落盘到文档目录 images/ 下（chunk markdown 的 ``images/…``
    引用由 files 路由服务）；落盘在 require_alive 检查点之后、不影响切片入库。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    doc_dir = tmp_path / "knowledge" / "kb-1" / "doc-1"
    doc_dir.mkdir(parents=True)
    storage = doc_dir / "a.pdf"
    storage.write_bytes(b"pdf")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.pdf", size_bytes=3, storage_path=str(storage))
    images = [ParsedImage(ref="images/p1.jpg", content=b"jpeg-bytes", media_type="image/jpeg")]
    monkeypatch.setattr("deerflow.knowledge.worker.caption_images", AsyncMock(return_value=CaptionOutcome(captions={"images/p1.jpg": "图注"})))

    async def parse_with_images(path: str) -> ParsedDocument:
        return ParsedDocument(markdown=SAMPLE_MD + "\n\n![图注](images/p1.jpg)\n", images=images)

    worker = _worker(store, session_factory, parse_fn=parse_with_images)
    await worker.process_document("doc-1")

    assert (doc_dir / "images" / "p1.jpg").read_bytes() == b"jpeg-bytes"
    doc = await store.get_document("doc-1")
    assert doc["status"] == "ready"
    assert doc["chunk_count"] is not None and doc["chunk_count"] >= 1


@pytest.mark.asyncio
async def test_reparse_rebuilds_images_dir(session_factory, tmp_path, monkeypatch):
    """重解析重建 images/ 目录：上一版的残留文件被清掉，只留本次解析结果。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    doc_dir = tmp_path / "knowledge" / "kb-1" / "doc-1"
    stale_dir = doc_dir / "images"
    stale_dir.mkdir(parents=True)
    (stale_dir / "stale.jpg").write_bytes(b"stale")
    storage = doc_dir / "a.pdf"
    storage.write_bytes(b"pdf")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.pdf", size_bytes=3, storage_path=str(storage))
    images = [ParsedImage(ref="images/p1.jpg", content=b"fresh", media_type="image/jpeg")]
    monkeypatch.setattr("deerflow.knowledge.worker.caption_images", AsyncMock(return_value=CaptionOutcome(captions={"images/p1.jpg": "图注"})))

    async def parse_with_images(path: str) -> ParsedDocument:
        return ParsedDocument(markdown=SAMPLE_MD, images=images)

    worker = _worker(store, session_factory, parse_fn=parse_with_images)
    await worker.process_document("doc-1")

    assert not (stale_dir / "stale.jpg").exists()
    assert (stale_dir / "p1.jpg").read_bytes() == b"fresh"


@pytest.mark.asyncio
async def test_image_persist_failure_does_not_fail_document(session_factory, tmp_path, monkeypatch):
    """图片落盘与图注一样是增强：写盘失败降级为告警，流水线照常到 ready。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    doc_dir = tmp_path / "knowledge" / "kb-1" / "doc-1"
    doc_dir.mkdir(parents=True)
    storage = doc_dir / "a.pdf"
    storage.write_bytes(b"pdf")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.pdf", size_bytes=3, storage_path=str(storage))
    images = [ParsedImage(ref="images/p1.jpg", content=b"jpeg-bytes", media_type="image/jpeg")]
    monkeypatch.setattr("deerflow.knowledge.worker.caption_images", AsyncMock(return_value=CaptionOutcome(captions={"images/p1.jpg": "图注"})))

    async def boom(fn, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("deerflow.knowledge.worker.run_file_io", boom)

    async def parse_with_images(path: str) -> ParsedDocument:
        return ParsedDocument(markdown=SAMPLE_MD, images=images)

    worker = _worker(store, session_factory, parse_fn=parse_with_images)
    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "ready"


@pytest.mark.asyncio
async def test_parse_failure_marks_failed_with_error(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="bad.pdf", size_bytes=10, storage_path="/tmp/bad.pdf")
    worker = _worker(store, session_factory, parse_fn=_parse_fn(fail=RuntimeError("MinerU 服务不可用")))

    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "failed"
    assert "MinerU 服务不可用" in (doc["error"] or "")
    # 解析期已初始化 pending（悬停全程可用）；硬失败时未达终态的路记 failed
    assert doc["path_status"] == {"vector": "failed"}


@pytest.mark.asyncio
async def test_empty_parse_result_fails_document_instead_of_silent_ready(session_factory):
    """复现 2026-09-04（野生狗奶.pdf）：MinerU 对纯标题/超短页返回空 full.md，
    流水线此前照走到 ready + 0 切片（静默丢数据）。空解析文本必须
    把文档标记为 failed 并留下可操作的错误信息，而不是静默就绪。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.pdf", size_bytes=10, storage_path="/tmp/a.pdf")
    worker = _worker(store, session_factory, parse_fn=_parse_fn(md="  \n"))

    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "failed"
    assert "解析结果为空" in (doc["error"] or "")
    assert doc["chunk_count"] in (None, 0)
    assert await store.list_chunks("doc-1", limit=10) == []
    assert doc["path_status"] == {"vector": "failed"}


@pytest.mark.asyncio
async def test_path_status_initialized_at_parsing(session_factory):
    """path_status 初始化前移到 parsing 起点（2026-08-12 体验修正）：解析阶段
    悬停即可用，显示「待处理」——不再等到 indexing 才首次写入。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")
    observed: list[dict[str, str] | None] = []

    async def parse_spy(path: str) -> ParsedDocument:
        doc = await store.get_document("doc-1")
        observed.append(None if doc["path_status"] is None else dict(doc["path_status"]))
        return ParsedDocument(markdown=SAMPLE_MD, images=[])

    worker = _worker(store, session_factory, parse_fn=parse_spy)
    await worker.process_document("doc-1")

    # parse_fn 执行时点（状态已是 parsing）：path_status 必须已初始化
    assert observed == [{"vector": "pending"}]


@pytest.mark.asyncio
async def test_path_status_tracks_pipeline_stages(session_factory):
    """spec 2026-08-11 §5：worker 各阶段推进时顺手写入 path_status，且写入
    时序必须体现「向量先就绪」。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")
    snapshots: list[dict[str, str]] = []
    original = store.update_document_status

    async def spy(doc_id, status, **kwargs):
        result = await original(doc_id, status, **kwargs)
        if result is not None and kwargs.get("path_status") is not None:
            snapshots.append(dict(result["path_status"]))
        return result

    store.update_document_status = spy  # type: ignore[method-assign]
    worker = _worker(store, session_factory, parse_fn=_parse_fn())

    await worker.process_document("doc-1")

    assert snapshots == [
        {"vector": "pending"},  # 进入 parsing（初始化前移）
        {"vector": "pending"},  # 进入 indexing（幂等重写同值）
        {"vector": "done"},  # index_chunks 完成 → 向量就绪
    ]


@pytest.mark.asyncio
async def test_path_status_marks_unfinished_legs_failed_on_pipeline_error(session_factory):
    """流水线硬失败：所有未达终态的路标记 failed（done/degraded 不被覆写）。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")
    vs = _vector_store_mock()
    vs.upsert_chunks = AsyncMock(side_effect=RuntimeError("qdrant down"))
    worker = _worker(store, session_factory, vector_store=vs, parse_fn=_parse_fn())

    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "failed"
    assert doc["path_status"] == {"vector": "failed"}


class _FailingEmbedder:
    """EmbedderError 软失败：index_chunks 逐批降级。

    仅首次调用（向量路切片批次）抛错——模拟全批次限流：向量路零切片入库，
    管线照走、文档落 failed（见下方用例）。
    """

    batch_size = 20

    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, texts, *, text_type: str = "document"):
        from deerflow.knowledge.embedder import EmbedderError

        self.calls += 1
        if self.calls == 1:
            raise EmbedderError("embedding service down")
        return [EmbeddingResult(dense=[0.01 * (i + 1)] * 1024, sparse=SparseVector(indices=[i + 1], values=[0.5])) for i, _ in enumerate(texts)]


class _SecondCallFailingEmbedder:
    """第二批软失败（部分入库）：batch_size=1 ⇒ 每切片一次调用，第 2 次抛错、
    其余照常——模拟瞬时限流下「部分切片未入库」的索引不完整场景。"""

    batch_size = 1

    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, texts, *, text_type: str = "document"):
        from deerflow.knowledge.embedder import EmbedderError

        self.calls += 1
        if self.calls == 2:
            raise EmbedderError("rate limited")
        return [EmbeddingResult(dense=[0.01 * (i + 1)] * 1024, sparse=SparseVector(indices=[i + 1], values=[0.5])) for i, _ in enumerate(texts)]


@pytest.mark.asyncio
async def test_path_status_vector_failed_when_embed_soft_fails(session_factory):
    """向量路软失败（零切片入向量库）：文档落 failed，不再静默 ready——
    索引不完整不得放行（RFC §5.2 表行 4）；error 记计数，path_status 如实
    标记 vector=failed（半截产物保留，可整篇重试）。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")
    worker = _worker(store, session_factory, parse_fn=_parse_fn(), embedder=_FailingEmbedder())

    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    total = len(await store.list_chunks("doc-1", limit=10))
    assert doc["status"] == "failed"
    assert f"向量索引不完整：{total}/{total} 切片未入库" in (doc["error"] or "")
    assert doc["path_status"] == {"vector": "failed"}


@pytest.mark.asyncio
async def test_vector_partial_index_fails_document_and_keeps_indexed_chunks(session_factory):
    """部分批次软失败（索引不完整）：不因「部分成功」放行 ready（RFC §5.2
    表行 4）；文档落 failed、error 记「N/M 切片未入库」，已入库切片保留
    （半截可见），可整篇重试。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")
    worker = _worker(store, session_factory, parse_fn=_parse_fn(md=TWO_CHUNK_MD), embedder=_SecondCallFailingEmbedder())

    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "failed"
    assert "向量索引不完整：1/2 切片未入库" in (doc["error"] or "")
    assert doc["chunk_count"] == 1
    assert doc["path_status"] == {"vector": "failed"}
    # 半截保留：成功批次已写向量库（1 条），失败切片行仍在（可整篇重试重建）
    upserted = [item for call in worker._vector_store.upsert_chunks.await_args_list for item in call.args[0]]
    assert len(upserted) == 1


@pytest.mark.asyncio
async def test_concurrency_cap_respected(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    for i in range(3):
        await store.create_document(doc_id=f"doc-{i}", kb_id="kb-1", uploader_id="user-1", name=f"{i}.md", size_bytes=1, storage_path=f"/tmp/{i}.md")

    active = 0
    peak = 0

    async def slow_parse(path: str) -> ParsedDocument:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            import asyncio

            await asyncio.sleep(0.01)
            return ParsedDocument(markdown="# 标题\n\n正文。", images=[])
        finally:
            active -= 1

    worker = _worker(store, session_factory, parse_fn=slow_parse, concurrency=1)
    await worker.start()
    for i in range(3):
        await worker.submit(f"doc-{i}")
    await worker.wait_idle()
    await worker.stop()

    assert peak == 1
    for i in range(3):
        assert (await store.get_document(f"doc-{i}"))["status"] == "ready"


@pytest.mark.asyncio
async def test_startup_recovery_skips_terminal_documents(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    # doc-A crashed mid-indexing: the chunk rows exist, the vector leg never ran
    await store.create_document(doc_id="doc-a", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=1, storage_path="/tmp/a.md")
    await store.update_document_status("doc-a", "indexing", chunk_count=2)
    await store.insert_chunks(
        [
            {"chunk_id": "doc-a#0000", "doc_id": "doc-a", "kb_id": "kb-1", "chunk_index": 0, "text": "已完成切片", "heading_path": [], "page": None, "token_count": 5},
            {"chunk_id": "doc-a#0001", "doc_id": "doc-a", "kb_id": "kb-1", "chunk_index": 1, "text": "待抽取切片 DeerFlow", "heading_path": [], "page": None, "token_count": 5},
        ]
    )
    # doc-B already terminal — recovery must not touch it
    await store.create_document(doc_id="doc-b", kb_id="kb-1", uploader_id="user-1", name="b.md", size_bytes=1, storage_path="/tmp/b.md")
    await store.update_document_status("doc-b", "ready", progress_percent=100, chunk_count=1)

    worker = _worker(store, session_factory)
    await worker.start()
    await worker.wait_idle()
    await worker.stop()

    doc_a = await store.get_document("doc-a")
    assert doc_a["status"] == "ready"
    assert doc_a["progress_percent"] == 100
    # terminal doc untouched (parse_fn default would fail loudly if invoked — none was provided)
    assert (await store.get_document("doc-b"))["status"] == "ready"


@pytest.mark.asyncio
async def test_pipeline_aborts_quietly_when_document_deleted_mid_parse(session_factory):
    """Task 9: a document deleted mid-indexing must not be resurrected — the
    worker hits the next liveness checkpoint and aborts with no further writes
    (regression: zombie chunks from the delete race)."""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")

    async def _parse_deleting(path: str) -> ParsedDocument:
        await store.delete_document("doc-1")  # user hits delete while the parser runs
        return ParsedDocument(markdown=SAMPLE_MD, images=[])

    worker = _worker(store, session_factory, parse_fn=_parse_deleting)

    result = await worker.process_document("doc-1")

    assert result is None
    assert await store.get_document("doc-1") is None  # row stays deleted
    assert await store.list_chunks("doc-1", limit=10) == []  # no zombie chunks


@pytest.mark.asyncio
async def test_worker_noops_when_document_deleted_after_retry_acceptance(session_factory):
    """重试受理后、worker 接手前的删除窗口（spec §4.3「重试受理中删除」）：受理面
    已把行 reset 回 ``uploaded``（旧切片/向量已擦），删除先落 ⇒ worker 静默收尾——
    行不复活、零僵尸切片（Task 9 删除竞态同族）。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")
    await store.update_document_status("doc-1", "failed", error="boom")
    await store.reset_document_for_retry("doc-1")  # 受理面：先擦后写的第一步
    assert await store.delete_document("doc-1") is True  # 删除先于 worker 接手

    worker = _worker(store, session_factory, parse_fn=_parse_fn())
    result = await worker.process_document("doc-1")

    assert result is None
    assert await store.get_document("doc-1") is None  # row stays deleted
    assert await store.list_chunks("doc-1", limit=10) == []  # no zombie chunks


# ── caption lifecycle & the marker's producer (spec 2026-09-23 D8/R8/R21) ──
#
# The pipeline order is caption → vector, and a degraded caption leg writes its marker into
# the ``error`` column, which the vector leg's own completeness markers also share. A re-parse
# clears the previous caption verdict and marker before the new pass runs — the caption leg is
# the only leg whose state survives a re-parse otherwise (the chunk wipe does not touch
# ``documents.error``, and the status writes merge per key).

CAPTION_MARKER = "image caption degraded: 1/1 images failed"
CAPTION_PREFIX = "image caption degraded:"


def _degraded_caption(images, **kwargs) -> CaptionOutcome:
    """The captioner's own verdict is unit-tested in test_parser.py; the worker only reads it.

    The text differs from the markdown's own alt ("图注"), so the chunk text proves *these*
    captions travelled through ``apply_captions()`` and not the original alt.
    """
    return CaptionOutcome(captions={image.ref: "VLM 图注" for image in images}, failed=1, degraded=True)


def _image_workspace(tmp_path):
    """A real doc dir with a source file plus one parsed image (persisting needs a dir)."""
    doc_dir = tmp_path / "knowledge" / "kb-1" / "doc-1"
    doc_dir.mkdir(parents=True)
    storage = doc_dir / "a.pdf"
    storage.write_bytes(b"pdf")
    images = [ParsedImage(ref="images/p1.jpg", content=b"jpeg-bytes", media_type="image/jpeg")]
    return storage, images


async def _create_doc(store) -> None:
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=3, storage_path="/tmp/a.md")


@pytest.mark.asyncio
async def test_a_config_error_on_a_new_document_fails_it_without_a_request(session_factory, tmp_path, monkeypatch):
    """spec 2026-09-23 D10.1/§4.10: the caption target's configuration error is not a per-image
    degradation.

    A *declared* target whose UI entry carries no key is refused at the entrance, so the new
    document fails with that reason and no caption request is ever built — the placeholder
    degradation stays reserved for the out-of-scope cases.
    """
    from deerflow.config.app_config import AppConfig, RagConfig
    from deerflow.config.model_config import ModelConfig
    from deerflow.config.sandbox_config import SandboxConfig

    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    storage, images = _image_workspace(tmp_path)
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.pdf", size_bytes=3, storage_path=str(storage))
    entry = ModelConfig(name="vl-entry", display_name="vl-entry", description=None, use="langchain_openai:ChatOpenAI", model="vl-wire", base_url="https://ui.example/v1", supports_thinking=False)
    config = AppConfig(models=[entry], sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"), rag=RagConfig(vlm_model="vl-entry"))
    config._ui_model_names = {"vl-entry"}
    monkeypatch.setattr("deerflow.knowledge.captioner.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.knowledge.worker.get_app_config", lambda: config)
    sent: list[object] = []
    monkeypatch.setattr("deerflow.knowledge.caption_client.httpx.AsyncClient", lambda **kw: sent.append(kw) or object())

    async def parse(path: str) -> ParsedDocument:
        return ParsedDocument(markdown=SAMPLE_MD, images=images)

    worker = _worker(store, session_factory, parse_fn=parse)
    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "failed"
    assert "api_key" in (doc["error"] or "")
    assert sent == []  # no caption request was ever built


@pytest.mark.asyncio
async def test_pipeline_records_a_degraded_caption_leg(session_factory, tmp_path, monkeypatch):
    """A degraded caption leg keeps its own marker and sub-state (D8), and its captions reach
    the chunk markdown."""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    storage, images = _image_workspace(tmp_path)
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.pdf", size_bytes=3, storage_path=str(storage))
    monkeypatch.setattr("deerflow.knowledge.worker.caption_images", AsyncMock(side_effect=_degraded_caption))

    async def parse(path: str) -> ParsedDocument:
        return ParsedDocument(markdown=SAMPLE_MD + "\n\n![图注](images/p1.jpg)\n", images=images)

    worker = _worker(store, session_factory, parse_fn=parse)
    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "ready"
    assert doc["error"] == CAPTION_MARKER
    assert doc["path_status"]["caption"] == "degraded"
    assert doc["path_status"]["vector"] == "done"
    # The captions reached the chunk markdown (spec 2026-09-23 D8: the leg reads
    # ``outcome.captions`` — the original alt was "图注", the fake caption is "VLM 图注").
    chunks = await store.list_chunks("doc-1", limit=10)
    assert any("VLM 图注" in chunk["text"] for chunk in chunks), "captions must be applied to the chunk markdown"


@pytest.mark.asyncio
async def test_reparse_clears_the_previous_caption_verdict_and_marker(session_factory):
    """R21 ①: the chunk wipe does not touch ``error``, and the status merge keeps the old
    ``caption`` key — both residues must be deleted when a new pass starts."""
    store = KnowledgeStore(session_factory)
    await _create_doc(store)
    await store.insert_chunks([{"chunk_id": "doc-1#0000", "doc_id": "doc-1", "kb_id": "kb-1", "chunk_index": 0, "text": "旧切片", "heading_path": [], "page": None, "token_count": 5}])
    await store.update_document_status("doc-1", "parsing", path_status={"caption": "degraded", "vector": "done"}, error=CAPTION_MARKER)

    worker = _worker(store, session_factory, parse_fn=_parse_fn())
    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "ready"
    # The new pass has no images, so nothing may remain claiming a caption verdict.
    assert "caption" not in doc["path_status"]
    assert doc["path_status"] == {"vector": "done"}
    assert not (doc["error"] or "").strip()


@pytest.mark.asyncio
async def test_reparse_clears_the_stale_caption_verdict_even_when_the_new_pass_fails(session_factory):
    """The clearing happens before the parse — a hard-failed re-parse must not leave the old
    caption key behind (its leg never ran, so the failure branch never overwrites it)."""
    store = KnowledgeStore(session_factory)
    await _create_doc(store)
    await store.update_document_status("doc-1", "parsing", path_status={"caption": "degraded", "vector": "done"}, error=CAPTION_MARKER)

    worker = _worker(store, session_factory, parse_fn=_parse_fn(md="  \n"))
    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "failed"
    assert "caption" not in doc["path_status"]
    assert doc["path_status"] == {"vector": "failed"}


@pytest.mark.asyncio
async def test_reparse_refreshes_a_counted_marker_instead_of_stacking(session_factory, tmp_path, monkeypatch):
    """The old count must not survive anywhere: a stacked second claim would read as two
    independent degradations (R21 ②)."""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    storage, images = _image_workspace(tmp_path)
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.pdf", size_bytes=3, storage_path=str(storage))
    await store.update_document_status("doc-1", "parsing", path_status={"caption": "degraded"}, error="image caption degraded: 1/2 images failed")
    monkeypatch.setattr("deerflow.knowledge.worker.caption_images", AsyncMock(side_effect=_degraded_caption))

    async def parse(path: str) -> ParsedDocument:
        return ParsedDocument(markdown=SAMPLE_MD, images=images)

    worker = _worker(store, session_factory, parse_fn=parse)
    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["error"] == CAPTION_MARKER  # the new 1/1, not the old 1/2 and not both
    assert doc["path_status"]["caption"] == "degraded"


@pytest.mark.asyncio
async def test_a_counted_marker_is_refreshed_in_place_not_stacked(session_factory):
    """R21 ②: the idempotence check compares substrings while the marker carries a count, so
    the choice is explicit — a marker sharing the prefix is replaced, never duplicated."""
    store = KnowledgeStore(session_factory)
    await _create_doc(store)
    worker = _worker(store, session_factory)

    await worker._append_error_marker("doc-1", CAPTION_MARKER, replace_prefix=CAPTION_PREFIX)
    await worker._append_error_marker("doc-1", CAPTION_MARKER, replace_prefix=CAPTION_PREFIX)

    assert (await store.get_document("doc-1"))["error"] == CAPTION_MARKER  # same count: once

    await worker._append_error_marker("doc-1", "image caption degraded: 2/2 images failed", replace_prefix=CAPTION_PREFIX)

    assert (await store.get_document("doc-1"))["error"] == "image caption degraded: 2/2 images failed"


@pytest.mark.asyncio
async def test_an_indexing_resume_keeps_the_caption_result_and_never_reruns_it(session_factory, monkeypatch):
    """D8: an ``indexing`` resume re-runs the index legs only — the caption leg has no input
    to redo and its recorded verdict stays."""
    store = KnowledgeStore(session_factory)
    await _create_doc(store)
    await store.insert_chunks([{"chunk_id": "doc-1#0000", "doc_id": "doc-1", "kb_id": "kb-1", "chunk_index": 0, "text": "DeerFlow 智能体", "heading_path": [], "page": None, "token_count": 5}])
    await store.update_document_status("doc-1", "indexing", path_status={"caption": "degraded", "vector": "done"}, error=CAPTION_MARKER)
    stub = AsyncMock(side_effect=AssertionError("caption_images must not rerun on an indexing resume"))
    monkeypatch.setattr("deerflow.knowledge.worker.caption_images", stub)
    worker = _worker(store, session_factory, parse_fn=_parse_fn())

    await worker.process_document("doc-1")

    assert stub.await_count == 0
    doc = await store.get_document("doc-1")
    assert doc["status"] == "ready"
    assert doc["path_status"]["caption"] == "degraded"
    assert doc["error"] == CAPTION_MARKER


@pytest.mark.asyncio
async def test_a_hard_failure_still_overwrites_the_caption_marker(session_factory, tmp_path, monkeypatch):
    """R21 ③ — existing behaviour, not fixed here: the failure branch writes ``error=str(exc)``
    wholesale, so the marker only survives a successful/degraded pass. The already-written
    caption sub-state stays (it reached a terminal verdict)."""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    storage, images = _image_workspace(tmp_path)
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.pdf", size_bytes=3, storage_path=str(storage))
    monkeypatch.setattr("deerflow.knowledge.worker.caption_images", AsyncMock(side_effect=_degraded_caption))
    store.insert_chunks = AsyncMock(side_effect=RuntimeError("chunk table is locked"))

    async def parse(path: str) -> ParsedDocument:
        return ParsedDocument(markdown=SAMPLE_MD, images=images)

    worker = _worker(store, session_factory, parse_fn=parse)
    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "failed"
    assert doc["error"] == "chunk table is locked"
    assert doc["path_status"] == {"caption": "degraded", "vector": "failed"}


@pytest.mark.asyncio
async def test_the_store_deletes_a_path_key_only_for_an_explicit_none_value(session_factory):
    """R21 ④: ``None`` at the *argument* level means "leave unchanged"; a ``None`` *value*
    inside ``path_status`` is the deletion channel. A fake store cannot show this."""
    store = KnowledgeStore(session_factory)
    await _create_doc(store)
    await store.update_document_status("doc-1", "parsing", path_status={"caption": "degraded", "vector": "done"})

    await store.update_document_status("doc-1", "parsing")  # no path_status argument: unchanged

    assert (await store.get_document("doc-1"))["path_status"] == {"caption": "degraded", "vector": "done"}

    await store.update_document_status("doc-1", "parsing", path_status={"caption": None, "graph": "pending"})

    assert (await store.get_document("doc-1"))["path_status"] == {"vector": "done", "graph": "pending"}


@pytest.mark.asyncio
async def test_duplicate_submits_coalesce_into_serial_rerun(session_factory):
    """D3=甲（2026-10-04）：同一文档并发重复提交收敛为「单次运行 + 至多一次
    补跑」——补跑排在原运行收尾之后（终态复检兜底），绝不并发进入管线。"""
    import asyncio

    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")
    worker = _worker(store, session_factory)

    depth = 0
    max_depth = 0
    entered: list[str] = []
    first_entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_process(doc_id: str) -> None:
        nonlocal depth, max_depth
        entered.append(doc_id)
        depth += 1
        max_depth = max(max_depth, depth)
        first_entered.set()
        await release.wait()
        depth -= 1

    worker.process_document = slow_process  # type: ignore[method-assign]

    await worker.start()
    await worker.submit("doc-1")
    await first_entered.wait()  # 首个运行已进入且被挂起
    await worker.submit("doc-1")  # 在途重复提交 ×2（同一文档不重复启动重试）
    await worker.submit("doc-1")
    await asyncio.sleep(0.05)  # 让重复任务入档登记（pending）
    release.set()
    await worker.wait_idle()
    await worker.stop()

    assert max_depth == 1, f"same doc entered the pipeline concurrently (depth={max_depth})"
    assert entered == ["doc-1", "doc-1"]  # 至多一次补跑（两支重复收敛为一）
    assert worker._active == set()
    assert worker._pending == set()


# ── D2 嵌入身份（spec 2026-10-04 §2.2：新库首次入库完成 ⇒ 盖章）────────────────


class _IdentityEmbedder(FakeEmbedder):
    identity = "space-a"


@pytest.mark.asyncio
async def test_the_first_completed_document_stamps_the_library_identity(session_factory):
    store = KnowledgeStore(session_factory)
    await _create_doc(store)
    worker = _worker(store, session_factory, parse_fn=_parse_fn(), embedder=_IdentityEmbedder())

    await worker.process_document("doc-1")

    assert (await store.get_kb("kb-1"))["embedding_identity"] == "space-a"


@pytest.mark.asyncio
async def test_an_incremental_document_never_overwrites_the_library_identity(session_factory):
    """遗留库（已有终态文档、身份未记）不能被新入库盖成「均匀」——那会遮掉存量的旧空间声明。"""
    store = KnowledgeStore(session_factory)
    await _create_doc(store)
    await store.update_document_status("doc-1", "ready")
    await store.create_document(doc_id="doc-2", kb_id="kb-1", uploader_id="user-1", name="b.md", size_bytes=3, storage_path="/tmp/b.md")
    worker = _worker(store, session_factory, parse_fn=_parse_fn(), embedder=_IdentityEmbedder())

    await worker.process_document("doc-2")

    assert (await store.get_kb("kb-1"))["embedding_identity"] is None
