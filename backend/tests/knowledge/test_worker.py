"""Tests for the async indexing worker (spec §3.6/§3.7).

The worker drives one document through the status machine
``uploaded → parsing → chunking → indexing → ready`` (or ``failed`` with the
error persisted), persists ``progress_percent`` as graph-settled/total chunks,
caps concurrency with a semaphore, and on startup re-enqueues non-terminal
documents — the slice-level extract state machine guarantees resumed runs
never re-extract ``done`` chunks.

Tests run fully offline: fake parser/LLM/embedder, a mocked vector store, and
a real SQLite database (slice status persistence is the point under test).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from qdrant_client.models import SparseVector

from deerflow.knowledge.captioner import CaptionOutcome
from deerflow.knowledge.embedder import EmbeddingResult
from deerflow.knowledge.graph.store import GraphStore
from deerflow.knowledge.parser import ParsedDocument, ParsedImage
from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.wiki.store import WikiStore
from deerflow.knowledge.worker import KnowledgeIndexWorker

SAMPLE_MD = """# 第一章 概述

DeerFlow 是超级智能体系统，Gateway 负责会话管理。

## 1.1 架构

索引流水线由 Parser 与 Chunker 组成，Chunker 按标题切片。
"""

#: Two sections each exceeding the chunker's merge threshold (>100 tokens), so
#: DeerFlow lands in two chunks — the freq≥2 wiki eligibility needs it (Task 8).
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


class FakeLLM:
    """One canned extraction payload per unique text (keyed by first chars)."""

    def __init__(self, mapping: dict[str, dict]) -> None:
        self.mapping = mapping
        self.seen_texts: list[str] = []

    async def ainvoke(self, messages):
        last = messages[-1] if isinstance(messages, list) else messages
        text = last["content"] if isinstance(last, dict) else getattr(last, "content", str(last))
        text = str(text)
        # gleaning follow-ups ("是否有遗漏") answer empty so extraction settles
        if "遗漏" in text:
            return SimpleNamespace(content='{"entities": [], "relations": []}')
        self.seen_texts.append(text)
        for key, payload in self.mapping.items():
            if key in text:
                return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
        return SimpleNamespace(content='{"entities": [], "relations": []}')


def _vector_store_mock() -> MagicMock:
    vs = MagicMock()
    vs.init_collections = AsyncMock()
    vs.upsert_chunks = AsyncMock(return_value=0)
    vs.upsert_entities = AsyncMock(return_value=0)
    vs.set_chunk_entities = AsyncMock()
    vs.delete_by_doc = AsyncMock()
    vs.delete_entities = AsyncMock()
    vs.upsert_wiki_entries = AsyncMock(return_value=0)
    vs.get_entity_vectors = AsyncMock(return_value={})
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
    llm = FakeLLM({"DeerFlow": {"entities": [{"name": "DeerFlow", "type": "系统", "description": "框架"}], "relations": []}})
    seen: list[str] = []
    worker = _worker(store, session_factory, parse_fn=_parse_fn(seen_statuses=seen, store=store, doc_id="doc-1"), llm=llm)

    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "ready"
    assert doc["progress_percent"] == 100
    # both heading blocks are small (<100 tokens) so the chunker merges them into one
    assert doc["chunk_count"] == 1
    assert seen == ["parsing"], "parse must run after the status advances to parsing"
    chunks = await store.list_chunks("doc-1", limit=10)
    assert {c["extract_status"] for c in chunks} == {"done"}
    assert any("DeerFlow" in (c["entities"] or []) for c in chunks)
    # vector path wrote chunk points + graph path backfilled payload + entities
    assert worker._vector_store.upsert_chunks.await_count >= 1
    assert worker._vector_store.set_chunk_entities.await_count == 1
    assert worker._vector_store.upsert_entities.await_count == 1
    # graph store persisted the entity
    graph = await GraphStore(session_factory).load_networkx("kb-1")
    assert "DeerFlow" in graph.nodes


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

    worker = _worker(store, session_factory, parse_fn=parse_with_images, llm=FakeLLM({}))
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

    worker = _worker(store, session_factory, parse_fn=parse_with_images, llm=FakeLLM({}))
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

    worker = _worker(store, session_factory, parse_fn=parse_with_images, llm=FakeLLM({}))
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
    # 解析期已初始化 pending/pending（悬停全程可用）；硬失败时未达终态的路记 failed
    assert doc["path_status"] == {"vector": "failed", "graph": "failed"}


@pytest.mark.asyncio
async def test_empty_parse_result_fails_document_instead_of_silent_ready(session_factory):
    """复现 2026-09-04（野生狗奶.pdf）：MinerU 对纯标题/超短页返回空 full.md，
    流水线此前照走到 ready + 0 切片（三路全绿的静默丢数据）。空解析文本必须
    把文档标记为 failed 并留下可操作的错误信息，而不是静默就绪。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.pdf", size_bytes=10, storage_path="/tmp/a.pdf")
    worker = _worker(store, session_factory, parse_fn=_parse_fn(md="  \n"), llm=FakeLLM({}))

    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "failed"
    assert "解析结果为空" in (doc["error"] or "")
    assert doc["chunk_count"] in (None, 0)
    assert await store.list_chunks("doc-1", limit=10) == []
    assert doc["path_status"] == {"vector": "failed", "graph": "failed"}


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

    worker = _worker(store, session_factory, parse_fn=parse_spy, llm=FakeLLM({}))
    await worker.process_document("doc-1")

    # parse_fn 执行时点（状态已是 parsing）：path_status 必须已初始化
    assert observed == [{"vector": "pending", "graph": "pending"}]


@pytest.mark.asyncio
async def test_path_status_tracks_pipeline_stages(session_factory):
    """spec 2026-08-11 §5：worker 各阶段推进时顺手写入 path_status，且写入
    时序必须体现「向量先就绪」（vector done 先于 graph done）。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")
    llm = FakeLLM({"DeerFlow": {"entities": [{"name": "DeerFlow", "type": "系统", "description": "框架"}], "relations": []}})
    snapshots: list[dict[str, str]] = []
    original = store.update_document_status

    async def spy(doc_id, status, **kwargs):
        result = await original(doc_id, status, **kwargs)
        if result is not None and kwargs.get("path_status") is not None:
            snapshots.append(dict(result["path_status"]))
        return result

    store.update_document_status = spy  # type: ignore[method-assign]
    worker = _worker(store, session_factory, parse_fn=_parse_fn(), llm=llm)

    await worker.process_document("doc-1")

    assert snapshots == [
        {"vector": "pending", "graph": "pending"},  # 进入 parsing（初始化前移）
        {"vector": "pending", "graph": "pending"},  # 进入 indexing（幂等重写同值）
        {"vector": "done", "graph": "pending"},  # index_chunks 完成 → 向量先就绪
        {"vector": "done", "graph": "indexing"},  # 图谱路开始
        {"vector": "done", "graph": "done"},  # 图谱路完成
    ]


@pytest.mark.asyncio
async def test_path_status_graph_degraded_shares_source_with_error_marker(session_factory):
    """graph=degraded 与 error 子标记 ``graph degraded`` 同源（同一 stats.degraded 判定）。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")
    await store.update_document_status("doc-1", "indexing", chunk_count=2)
    await store.insert_chunks(
        [
            {"chunk_id": "doc-1#0000", "doc_id": "doc-1", "kb_id": "kb-1", "chunk_index": 0, "text": "DeerFlow 智能体", "heading_path": [], "page": None, "token_count": 5},
            {"chunk_id": "doc-1#0001", "doc_id": "doc-1", "kb_id": "kb-1", "chunk_index": 1, "text": "坏切片", "heading_path": [], "page": None, "token_count": 5},
        ]
    )
    worker = _worker(store, session_factory, llm=_PartialFailLLM())

    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "ready"
    assert "graph degraded" in doc["error"]  # 1/2 切片失败超阈值
    assert doc["path_status"] == {"vector": "done", "graph": "degraded"}


@pytest.mark.asyncio
async def test_path_status_marks_unfinished_legs_failed_on_pipeline_error(session_factory):
    """流水线硬失败：所有未达终态的路标记 failed（done/degraded 不被覆写）。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")
    vs = _vector_store_mock()
    vs.upsert_chunks = AsyncMock(side_effect=RuntimeError("qdrant down"))
    worker = _worker(store, session_factory, vector_store=vs, parse_fn=_parse_fn(), llm=FakeLLM({}))

    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "failed"
    assert doc["path_status"] == {"vector": "failed", "graph": "failed"}


class _FailingEmbedder:
    """EmbedderError 软失败：index_chunks 逐批降级。

    仅首次调用（向量路切片批次）抛错；后续调用（图谱路实体向量）正常返回——
    模拟全批次限流：向量路零切片入库，管线照走、文档落 failed（见下方用例）。
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
    标记 vector=failed、graph 照走（半截产物保留，可整篇重试）。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")
    llm = FakeLLM({"DeerFlow": {"entities": [{"name": "DeerFlow", "type": "系统", "description": "框架"}], "relations": []}})
    worker = _worker(store, session_factory, parse_fn=_parse_fn(), llm=llm, embedder=_FailingEmbedder())

    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    total = len(await store.list_chunks("doc-1", limit=10))
    assert doc["status"] == "failed"
    assert f"向量索引不完整：{total}/{total} 切片未入库" in (doc["error"] or "")
    assert doc["path_status"] == {"vector": "failed", "graph": "done"}


@pytest.mark.asyncio
async def test_vector_partial_index_fails_document_and_keeps_indexed_chunks(session_factory):
    """部分批次软失败（索引不完整）：不因「部分成功」放行 ready（RFC §5.2
    表行 4）；文档落 failed、error 记「N/M 切片未入库」，已入库切片保留
    （半截可见），可整篇重试。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")
    llm = FakeLLM({"DeerFlow": {"entities": [{"name": "DeerFlow", "type": "系统", "description": "框架"}], "relations": []}})
    worker = _worker(store, session_factory, parse_fn=_parse_fn(md=TWO_CHUNK_MD), llm=llm, embedder=_SecondCallFailingEmbedder())

    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "failed"
    assert "向量索引不完整：1/2 切片未入库" in (doc["error"] or "")
    assert doc["chunk_count"] == 1
    assert doc["path_status"] == {"vector": "failed", "graph": "done"}
    # 半截保留：成功批次已写向量库（1 条），失败切片行仍在（可整篇重试重建）
    upserted = [item for call in worker._vector_store.upsert_chunks.await_args_list for item in call.args[0]]
    assert len(upserted) == 1


@pytest.mark.asyncio
async def test_progress_percent_tracks_graph_settled_chunks(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")
    llm = FakeLLM({})
    worker = _worker(store, session_factory, parse_fn=_parse_fn(), llm=llm)
    progress_calls: list[int] = []
    original = store.update_document_status

    async def spy(doc_id, status, **kwargs):
        if "progress_percent" in kwargs and kwargs["progress_percent"] is not None:
            progress_calls.append(kwargs["progress_percent"])
        return await original(doc_id, status, **kwargs)

    store.update_document_status = spy  # type: ignore[method-assign]

    await worker.process_document("doc-1")

    assert progress_calls, "graph progress callback must persist progress_percent"
    assert progress_calls == sorted(progress_calls), "progress must be monotonic"
    assert progress_calls[-1] == 100


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

    worker = _worker(store, session_factory, parse_fn=slow_parse, llm=FakeLLM({}), concurrency=1)
    await worker.start()
    for i in range(3):
        await worker.submit(f"doc-{i}")
    await worker.wait_idle()
    await worker.stop()

    assert peak == 1
    for i in range(3):
        assert (await store.get_document(f"doc-{i}"))["status"] == "ready"


@pytest.mark.asyncio
async def test_startup_recovery_skips_terminal_and_done_chunks(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    # doc-A crashed mid-indexing: one chunk extracted, one still pending
    await store.create_document(doc_id="doc-a", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=1, storage_path="/tmp/a.md")
    await store.update_document_status("doc-a", "indexing", chunk_count=2)
    await store.insert_chunks(
        [
            {"chunk_id": "doc-a#0000", "doc_id": "doc-a", "kb_id": "kb-1", "chunk_index": 0, "text": "已完成切片", "heading_path": [], "page": None, "token_count": 5},
            {"chunk_id": "doc-a#0001", "doc_id": "doc-a", "kb_id": "kb-1", "chunk_index": 1, "text": "待抽取切片 DeerFlow", "heading_path": [], "page": None, "token_count": 5},
        ]
    )
    await store.update_chunk_extract("doc-a#0000", "done", entities=["DeerFlow"])
    # doc-B already terminal — recovery must not touch it
    await store.create_document(doc_id="doc-b", kb_id="kb-1", uploader_id="user-1", name="b.md", size_bytes=1, storage_path="/tmp/b.md")
    await store.update_document_status("doc-b", "ready", progress_percent=100, chunk_count=1)

    llm = FakeLLM({"DeerFlow": {"entities": [{"name": "DeerFlow", "type": "系统", "description": "框架"}], "relations": []}})
    worker = _worker(store, session_factory, llm=llm)
    await worker.start()
    await worker.wait_idle()
    await worker.stop()

    doc_a = await store.get_document("doc-a")
    assert doc_a["status"] == "ready"
    assert doc_a["progress_percent"] == 100
    chunk0 = {c["chunk_id"]: c for c in await store.list_chunks("doc-a", limit=10)}["doc-a#0000"]
    assert chunk0["extract_status"] == "done"
    # the pending chunk was extracted exactly once; the done chunk never re-sent to the LLM
    assert len(llm.seen_texts) == 1
    assert "待抽取切片" in llm.seen_texts[0]
    # terminal doc untouched (parse_fn default would fail loudly if invoked — none was provided)
    assert (await store.get_document("doc-b"))["status"] == "ready"


class _WikiLLM:
    """Main-model fake for wiki entry generation."""

    async def ainvoke(self, messages):
        return SimpleNamespace(content="# DeerFlow\n\nDeerFlow 是基于 LangGraph 的超级智能体系统，包含 Gateway 与沙箱。")


@pytest.mark.asyncio
async def test_ready_document_auto_triggers_wiki_generation(session_factory):
    """Regression: the auto wiki trigger must use the real WikiStore interface.

    Live smoke caught ``_maybe_generate_wiki`` calling ``wiki_store.list()``
    (the real method is ``list_entries``) — with a mocked wiki store the slip
    was invisible, and the trigger silently produced nothing.
    """
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")
    llm = FakeLLM({"DeerFlow": {"entities": [{"name": "DeerFlow", "type": "系统", "description": "框架"}], "relations": []}})
    worker = _worker(store, session_factory, parse_fn=_parse_fn(md=TWO_CHUNK_MD), llm=llm, main_llm=_WikiLLM())

    await worker.process_document("doc-1")
    await worker.wait_idle()  # the wiki leg is a tracked task now (D1): settle before asserting

    assert (await store.get_document("doc-1"))["status"] == "ready"
    entries = await WikiStore(session_factory).list_entries("kb-1")
    assert entries, "auto wiki trigger produced no entries"
    assert entries[0]["title"] == "DeerFlow"
    assert entries[0]["status"] == "ready"
    assert worker._vector_store.upsert_wiki_entries.await_count == 1


@pytest.mark.asyncio
async def test_entity_resolution_runs_after_graph_indexing(session_factory, monkeypatch):
    """D3: the worker triggers the incremental re-resolution with the touched
    entity set right after the graph leg, before marking the document ready."""
    from deerflow.knowledge.graph.resolver import ResolutionStats

    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")
    llm = FakeLLM({"DeerFlow": {"entities": [{"name": "DeerFlow", "type": "系统", "description": "框架"}], "relations": []}})
    spy = AsyncMock(return_value=ResolutionStats())
    monkeypatch.setattr("deerflow.knowledge.worker.resolve_entity_aliases", spy)
    worker = _worker(store, session_factory, parse_fn=_parse_fn(), llm=llm)

    await worker.process_document("doc-1")

    assert (await store.get_document("doc-1"))["status"] == "ready"
    assert spy.await_count == 1
    assert spy.await_args.kwargs["kb_id"] == "kb-1"
    assert spy.await_args.kwargs["touched_entities"] == {"DeerFlow"}


class _PartialFailLLM:
    """First chunk extracts fine, the '坏切片' chunk returns malformed JSON."""

    async def ainvoke(self, messages):
        last = messages[-1] if isinstance(messages, list) else messages
        text = str(last["content"] if isinstance(last, dict) else getattr(last, "content", last))
        if "遗漏" in text:
            return SimpleNamespace(content='{"entities": [], "relations": []}')
        if "坏切片" in text:
            return SimpleNamespace(content="这不是 JSON")
        return SimpleNamespace(content=json.dumps({"entities": [{"name": "DeerFlow", "type": "系统", "description": "框架"}], "relations": []}, ensure_ascii=False))


@pytest.mark.asyncio
async def test_entity_resolution_failure_degrades_without_blocking(session_factory, monkeypatch):
    """D3: a failing re-resolution never blocks the pipeline — the document
    still reaches ``ready`` and the error field gains a visible sub-marker
    alongside any existing ``graph degraded`` flag; wiki generation proceeds."""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")
    await store.update_document_status("doc-1", "indexing", chunk_count=3)
    await store.insert_chunks(
        [
            {"chunk_id": "doc-1#0000", "doc_id": "doc-1", "kb_id": "kb-1", "chunk_index": 0, "text": "DeerFlow 智能体", "heading_path": [], "page": None, "token_count": 5},
            {"chunk_id": "doc-1#0001", "doc_id": "doc-1", "kb_id": "kb-1", "chunk_index": 1, "text": "坏切片", "heading_path": [], "page": None, "token_count": 5},
            # Second good chunk: DeerFlow reaches freq 2 — wiki eligibility (Task 8).
            {"chunk_id": "doc-1#0002", "doc_id": "doc-1", "kb_id": "kb-1", "chunk_index": 2, "text": "DeerFlow 运行时", "heading_path": [], "page": None, "token_count": 5},
        ]
    )
    monkeypatch.setattr("deerflow.knowledge.worker.resolve_entity_aliases", AsyncMock(side_effect=RuntimeError("resolution boom")))
    worker = _worker(store, session_factory, llm=_PartialFailLLM(), main_llm=_WikiLLM())

    await worker.process_document("doc-1")
    await worker.wait_idle()  # the wiki leg is a tracked task now (D1): settle before asserting

    doc = await store.get_document("doc-1")
    assert doc["status"] == "ready"
    assert "graph degraded" in doc["error"]  # 1/3 chunks failed > 30%
    assert "entity-resolution failed" in doc["error"]
    entries = await WikiStore(session_factory).list_entries("kb-1")
    assert entries, "wiki generation must not be blocked by the resolution failure"


@pytest.mark.asyncio
async def test_new_document_marks_touched_wiki_entries_dirty(session_factory):
    """Task 5b: the new-document hook flags the touched entities' entries as
    dirty; untouched entries stay ready (spec §3.5 2026-08-12 revision).

    Since spec 2026-09-26 the wiki trigger resolves a model per run instead of returning
    early on a ``None`` boot instance, so a run that *reaches* the threshold would consume
    the flag in the same pass. The library therefore carries a second, unprocessed document
    (ready share 1/2 < 0.9): the trigger stays below its bar, which is the state this test is
    about. The fake ``main_llm`` keeps it offline even if that gauge ever moves.
    """
    store = KnowledgeStore(session_factory)
    wiki_store = WikiStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    # The library already has entries: DeerFlow gets touched by the new
    # document, Gateway does not.
    await wiki_store.upsert_entry("kb-1", title="DeerFlow", content="旧条目", source_chunk_ids=[], status="ready")
    await wiki_store.upsert_entry("kb-1", title="Gateway", content="旧条目", source_chunk_ids=[], status="ready")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")
    await store.create_document(doc_id="doc-2", kb_id="kb-1", uploader_id="user-1", name="b.md", size_bytes=10, storage_path="/tmp/b.md")
    llm = FakeLLM({"DeerFlow": {"entities": [{"name": "DeerFlow", "type": "系统", "description": "框架"}], "relations": []}})
    worker = _worker(store, session_factory, parse_fn=_parse_fn(), llm=llm, main_llm=_WikiLLM())

    await worker.process_document("doc-1")
    await worker.wait_idle()  # the wiki leg is a tracked task now (D1): settle before asserting

    assert (await store.get_document("doc-1"))["status"] == "ready"
    entries = {entry["title"]: entry for entry in await wiki_store.list_entries("kb-1")}
    assert entries["DeerFlow"]["status"] == "dirty"
    assert entries["Gateway"]["status"] == "ready"


@pytest.mark.asyncio
async def test_wiki_dirty_hook_failure_never_blocks_ready(session_factory, monkeypatch):
    """Task 5b: a failing dirty hook degrades to a log line only — the document
    still reaches ``ready`` and gains no error sub-marker (library-level concern)."""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")
    llm = FakeLLM({"DeerFlow": {"entities": [{"name": "DeerFlow", "type": "系统", "description": "框架"}], "relations": []}})
    monkeypatch.setattr("deerflow.knowledge.worker.mark_dirty_for_entities", AsyncMock(side_effect=RuntimeError("wiki store down")))
    worker = _worker(store, session_factory, parse_fn=_parse_fn(), llm=llm)

    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "ready"
    assert doc["error"] is None


@pytest.mark.asyncio
async def test_pipeline_aborts_quietly_when_document_deleted_mid_parse(session_factory):
    """Task 9: a document deleted mid-indexing must not be resurrected — the
    worker hits the next liveness checkpoint and aborts with no further writes
    (regression: phantom chunk refs and zombie chunks from the delete race)."""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.md", size_bytes=10, storage_path="/tmp/a.md")

    async def _parse_deleting(path: str) -> ParsedDocument:
        await store.delete_document("doc-1")  # user hits delete while the parser runs
        return ParsedDocument(markdown=SAMPLE_MD, images=[])

    llm = FakeLLM({"DeerFlow": {"entities": [{"name": "DeerFlow", "type": "系统", "description": "框架"}], "relations": []}})
    worker = _worker(store, session_factory, parse_fn=_parse_deleting, llm=llm)

    result = await worker.process_document("doc-1")

    assert result is None
    assert await store.get_document("doc-1") is None  # row stays deleted
    assert await store.list_chunks("doc-1", limit=10) == []  # no zombie chunks
    graph = await GraphStore(session_factory).load_networkx("kb-1")
    assert len(graph.nodes) == 0  # no phantom entities


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
# The pipeline order is caption → vector → graph, and both degraded legs write a marker into
# the same ``error`` column. The graph marker used to be written *by the indexer* with a plain
# overwrite, so a degraded caption verdict was erased by a degraded graph pass; the worker now
# owns both markers (it already had ``stats.degraded``) and appends them joined by ``; ``.
# A re-parse clears the previous caption verdict and marker before the new pass runs — the
# caption leg is the only leg whose state survives a re-parse otherwise (the chunk wipe does
# not touch ``documents.error``, and the status writes merge per key).

#: ``TWO_CHUNK_MD`` with an extraction-failure needle in the second section — the proven
#: two-chunk fixture, so the graph leg fails exactly one chunk (50% > 30% ⇒ degraded).
_FAILING_PAIR_MD = TWO_CHUNK_MD.replace("## 1.1 DeerFlow 架构", "## 1.1 坏切片的环境").replace("DeerFlow 的索引流水线由 Parser 与 Chunker 组成", "坏切片的索引流水线由 Parser 与 Chunker 组成")

CAPTION_MARKER = "image caption degraded: 1/1 images failed"
GRAPH_MARKER = "graph degraded: 1/2 chunks failed extraction"
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

    worker = _worker(store, session_factory, parse_fn=parse, llm=FakeLLM({}))
    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "failed"
    assert "api_key" in (doc["error"] or "")
    assert sent == []  # no caption request was ever built


@pytest.mark.asyncio
async def test_pipeline_appends_caption_then_graph_markers_in_that_order(session_factory, tmp_path, monkeypatch):
    """Both degraded legs keep their own marker, caption first (D8), and both sub-states survive."""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    storage, images = _image_workspace(tmp_path)
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.pdf", size_bytes=3, storage_path=str(storage))
    monkeypatch.setattr("deerflow.knowledge.worker.caption_images", AsyncMock(side_effect=_degraded_caption))

    async def parse(path: str) -> ParsedDocument:
        return ParsedDocument(markdown=_FAILING_PAIR_MD + "\n\n![图注](images/p1.jpg)\n", images=images)

    worker = _worker(store, session_factory, parse_fn=parse, llm=_PartialFailLLM())
    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "ready"
    assert doc["error"] == f"{CAPTION_MARKER}; {GRAPH_MARKER}"
    assert doc["path_status"]["caption"] == "degraded"
    assert doc["path_status"]["graph"] == "degraded"
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
    await store.update_document_status("doc-1", "parsing", path_status={"caption": "degraded", "vector": "done", "graph": "done"}, error=CAPTION_MARKER)

    worker = _worker(store, session_factory, parse_fn=_parse_fn(), llm=FakeLLM({}))
    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "ready"
    # The new pass has no images, so nothing may remain claiming a caption verdict.
    assert "caption" not in doc["path_status"]
    assert doc["path_status"] == {"vector": "done", "graph": "done"}
    assert not (doc["error"] or "").strip()


@pytest.mark.asyncio
async def test_reparse_clears_the_stale_caption_verdict_even_when_the_new_pass_fails(session_factory):
    """The clearing happens before the parse — a hard-failed re-parse must not leave the old
    caption key behind (its leg never ran, so the failure branch never overwrites it)."""
    store = KnowledgeStore(session_factory)
    await _create_doc(store)
    await store.update_document_status("doc-1", "parsing", path_status={"caption": "degraded", "vector": "done", "graph": "done"}, error=CAPTION_MARKER)

    worker = _worker(store, session_factory, parse_fn=_parse_fn(md="  \n"), llm=FakeLLM({}))
    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "failed"
    assert "caption" not in doc["path_status"]
    assert doc["path_status"] == {"vector": "failed", "graph": "failed"}


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

    worker = _worker(store, session_factory, parse_fn=parse, llm=FakeLLM({}))
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
    await store.update_document_status("doc-1", "indexing", path_status={"caption": "degraded", "vector": "done", "graph": "done"}, error=CAPTION_MARKER)
    stub = AsyncMock(side_effect=AssertionError("caption_images must not rerun on an indexing resume"))
    monkeypatch.setattr("deerflow.knowledge.worker.caption_images", stub)
    worker = _worker(store, session_factory, parse_fn=_parse_fn(), llm=FakeLLM({"DeerFlow": {"entities": [{"name": "DeerFlow", "type": "系统", "description": "框架"}], "relations": []}}))

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

    worker = _worker(store, session_factory, parse_fn=parse, llm=FakeLLM({}))
    await worker.process_document("doc-1")

    doc = await store.get_document("doc-1")
    assert doc["status"] == "failed"
    assert doc["error"] == "chunk table is locked"
    assert doc["path_status"] == {"caption": "degraded", "vector": "failed", "graph": "failed"}


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


# ── the wiki trigger resolves its model per trigger (spec 2026-09-26 D3, ③＝乙) ──


def _wiki_cfg(*names: str, **rag_kwargs):
    """A minimal real config: only the fields the resolver reads are meaningful here."""
    from deerflow.config.app_config import AppConfig, RagConfig
    from deerflow.config.model_config import ModelConfig
    from deerflow.config.sandbox_config import SandboxConfig

    return AppConfig(
        models=[
            ModelConfig(
                name=name,
                display_name=name,
                description=None,
                use="langchain_openai:ChatOpenAI",
                model=f"{name}-wire",
                supports_thinking=False,
                supports_vision=False,
            )
            for name in names
        ],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        rag=RagConfig(**rag_kwargs),
    )


def _target_spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str | None, object]]:
    """Record what this trigger hands the factory, without building a client."""
    seen: list[tuple[str | None, object]] = []

    def _fake(name=None, *, app_config=None, **_kwargs):
        seen.append((name, app_config))
        return SimpleNamespace(name=name)

    monkeypatch.setattr("deerflow.models.factory.create_chat_model", _fake)
    return seen


@pytest.fixture
def wiki_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Replace the batch writer: these cases are about *which* llm it is handed."""
    calls: list[dict] = []

    async def _fake_generate_wiki(*_args, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("deerflow.knowledge.worker.generate_wiki", _fake_generate_wiki)
    return calls


def _point_at(monkeypatch: pytest.MonkeyPatch, config) -> None:
    from deerflow.config import app_config as app_config_module

    monkeypatch.setattr(app_config_module, "get_app_config", lambda: config)


@pytest.mark.asyncio
async def test_the_wiki_trigger_follows_the_config_it_reads_each_time(session_factory, monkeypatch, wiki_calls):
    """③＝乙: no boot snapshot — one worker instance follows the configuration of each trigger.

    The reverse control at the end is what keeps the first half honest: with an unchanged
    config the target must not wander (so "it changed" cannot be a coincidence of the spy).
    """
    store = KnowledgeStore(session_factory)
    await _create_doc(store)
    await store.update_document_status("doc-1", "ready")
    worker = _worker(store, session_factory)
    seen = _target_spy(monkeypatch)

    _point_at(monkeypatch, _wiki_cfg("A", "B", "C", wiki_model="C"))
    await worker._maybe_generate_wiki("kb-1", FakeEmbedder())
    _point_at(monkeypatch, _wiki_cfg("A", "B", default_model="B"))
    await worker._maybe_generate_wiki("kb-1", FakeEmbedder())
    await worker._maybe_generate_wiki("kb-1", FakeEmbedder())

    assert [name for name, _config in seen] == ["C", "B", "B"]
    assert len(wiki_calls) == 3


@pytest.mark.asyncio
async def test_the_wiki_trigger_still_honours_the_injected_llm(session_factory, monkeypatch, wiki_calls):
    """The construction port survives the change: tests keep driving wiki generation with a fake."""
    store = KnowledgeStore(session_factory)
    await _create_doc(store)
    await store.update_document_status("doc-1", "ready")
    injected = _WikiLLM()
    worker = _worker(store, session_factory, main_llm=injected)
    seen = _target_spy(monkeypatch)

    # A config that would refuse on its own — proof the port short-circuits resolution.
    _point_at(monkeypatch, _wiki_cfg())
    await worker._maybe_generate_wiki("kb-1", FakeEmbedder())

    assert seen == []
    assert wiki_calls[-1]["llm"] is injected


@pytest.mark.asyncio
async def test_a_broken_wiki_target_is_logged_and_the_document_stays_ready(session_factory, monkeypatch, wiki_calls, caplog):
    """No usable model is not a document failure: the existing guard swallows it and says so."""
    store = KnowledgeStore(session_factory)
    await _create_doc(store)
    await store.update_document_status("doc-1", "ready")
    worker = _worker(store, session_factory)
    _target_spy(monkeypatch)
    _point_at(monkeypatch, _wiki_cfg())

    with caplog.at_level("ERROR"):
        await worker._maybe_generate_wiki("kb-1", FakeEmbedder())

    assert wiki_calls == []
    assert "wiki generation trigger failed for kb kb-1" in caplog.text
    assert (await store.get_document("doc-1"))["status"] == "ready"


def test_the_boot_snapshot_is_gone_from_both_sides():
    """The source claims behind ③＝乙: no model built at boot, and no snapshot read in the worker."""
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2]
    app_source = (backend / "app" / "gateway" / "app.py").read_text(encoding="utf-8")
    worker_source = (backend / "packages" / "harness" / "deerflow" / "knowledge" / "worker.py").read_text(encoding="utf-8")

    assert "Main model unavailable" not in app_source
    assert "main_llm=" not in app_source
    # The worker must read the *current* config where it used to consume a boot snapshot.
    assert "get_app_config" in worker_source
    assert "startup_config" not in worker_source


# ── 百科腿放槽（spec 2026-10-02 D1=乙）────────────────────────────────────


@pytest.mark.asyncio
async def test_a_hanging_wiki_leg_does_not_block_new_documents(session_factory, monkeypatch):
    """D1=乙: the wiki leg must not hold a worker slot.

    W=2; doc-1 finishes and triggers a wiki run that hangs (the slot-hogging
    shape of the pre-D1 pipeline). Two more documents submitted while it hangs
    must enter parse at full concurrency 2 — before the fix the hanging run
    eats one of the two slots and the newcomers serialize at 1.
    """
    import asyncio

    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="1.md", size_bytes=1, storage_path="/tmp/1.md")

    hang = asyncio.Event()
    wiki_started = asyncio.Event()

    async def _hanging_generate(*_args, **_kwargs):
        wiki_started.set()
        await hang.wait()

    monkeypatch.setattr("deerflow.knowledge.worker.generate_wiki", _hanging_generate)
    # Gate isolated: this test is about slot occupancy, not the trigger threshold.
    monkeypatch.setattr("deerflow.knowledge.worker.wiki_trigger_ready", AsyncMock(return_value=True))

    active = 0
    peak = 0

    async def slow_parse(path: str) -> ParsedDocument:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.05)
            return ParsedDocument(markdown="# 标题\n\n正文。", images=[])
        finally:
            active -= 1

    worker = _worker(store, session_factory, parse_fn=slow_parse, llm=FakeLLM({}), main_llm=_WikiLLM(), concurrency=2)
    await worker.start()  # recover() re-enqueues doc-1
    await wiki_started.wait()
    for i in (2, 3):
        await store.create_document(doc_id=f"doc-{i}", kb_id="kb-1", uploader_id="user-1", name=f"{i}.md", size_bytes=1, storage_path=f"/tmp/{i}.md")
        await worker.submit(f"doc-{i}")

    entered = False
    for _ in range(300):
        statuses = [(await store.get_document(f"doc-{i}"))["status"] for i in (2, 3)]
        if all(status != "uploaded" for status in statuses):
            entered = True
            break
        await asyncio.sleep(0.01)
    hang.set()
    await worker.wait_idle()
    await worker.stop()

    assert entered, "new documents never entered the pipeline while the wiki leg hung"
    assert peak == 2, f"parse concurrency collapsed to {peak} while the wiki leg held a slot"


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


@pytest.mark.asyncio
async def test_wait_idle_covers_the_detached_wiki_leg(session_factory, monkeypatch):
    """D1=乙: by the time ``wait_idle`` returns, the wiki run it spawned has settled.

    Regression guard for the slot release: the wiki leg becomes a tracked task,
    and the test-visible drain point is ``wait_idle`` — returning before the
    entry is written would strand every wiki assertion in the suite.
    """
    import asyncio

    store = KnowledgeStore(session_factory)
    await _create_doc(store)
    wiki_store = WikiStore(session_factory)

    async def _writing_generate(*_args, **_kwargs):
        # 0.2s >> the drain gap: without the wait_idle drain this returns long
        # before the entry lands, so the neuter proof cannot race past it.
        await asyncio.sleep(0.2)
        await wiki_store.upsert_entry("kb-1", title="DeerFlow", content="新条目", source_chunk_ids=[], status="ready")

    monkeypatch.setattr("deerflow.knowledge.worker.generate_wiki", _writing_generate)
    worker = _worker(store, session_factory, parse_fn=_parse_fn(), llm=FakeLLM({}), main_llm=_WikiLLM())
    await worker.start()
    await worker.wait_idle()
    # Read BETWEEN wait_idle and stop: stop() gathers the tracked tasks too, and
    # asserting after it could never tell the two drain points apart.
    entries = await wiki_store.list_entries("kb-1")
    await worker.stop()

    assert entries, "wait_idle returned before the detached wiki run wrote its entry"
    assert entries[0]["title"] == "DeerFlow"


# ── 同 KB 生成单飞+合并（spec 2026-10-02 D2=乙）────────────────────────────


@pytest.mark.asyncio
async def test_same_kb_wiki_triggers_are_single_flight(session_factory, monkeypatch):
    """D2=乙: concurrent triggers for one KB run one generation at a time."""
    import asyncio

    store = KnowledgeStore(session_factory)
    await _create_doc(store)
    started = asyncio.Event()
    release = asyncio.Event()
    active = 0
    peak = 0
    calls = 0

    async def _hanging_generate(*_args, **_kwargs):
        nonlocal active, peak, calls
        calls += 1
        active += 1
        peak = max(peak, active)
        started.set()
        try:
            await release.wait()
        finally:
            active -= 1

    monkeypatch.setattr("deerflow.knowledge.worker.generate_wiki", _hanging_generate)
    monkeypatch.setattr("deerflow.knowledge.worker.wiki_trigger_ready", AsyncMock(return_value=True))
    worker = _worker(store, session_factory, main_llm=_WikiLLM())
    embedder = FakeEmbedder()

    for _ in range(5):
        worker._spawn_wiki("kb-1", embedder)
    await started.wait()
    release.set()
    await worker.wait_idle()

    assert peak == 1, f"{peak} wiki runs overlapped for one KB"
    # All five triggers land before the runner even starts, so they coalesce
    # into the single initial run (no trailing needed); a claim-less shape
    # would run the stub five times.
    assert calls == 1, f"expected one coalesced run, got {calls}"


@pytest.mark.asyncio
async def test_wiki_triggers_during_a_run_coalesce_into_one_trailing_run(session_factory, monkeypatch):
    """D2=乙: triggers that land mid-run collapse into exactly one trailing run."""
    import asyncio

    store = KnowledgeStore(session_factory)
    await _create_doc(store)
    calls = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _hanging_generate(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()

    monkeypatch.setattr("deerflow.knowledge.worker.generate_wiki", _hanging_generate)
    monkeypatch.setattr("deerflow.knowledge.worker.wiki_trigger_ready", AsyncMock(return_value=True))
    worker = _worker(store, session_factory, main_llm=_WikiLLM())
    embedder = FakeEmbedder()

    worker._spawn_wiki("kb-1", embedder)
    await entered.wait()
    entered.clear()
    for _ in range(3):
        worker._spawn_wiki("kb-1", embedder)
    release.set()
    await worker.wait_idle()

    assert calls == 2, f"expected one run plus one coalesced trailing run, got {calls}"


@pytest.mark.asyncio
async def test_worker_defers_wiki_while_a_manual_run_is_in_flight(session_factory, monkeypatch):
    """D2=乙 cross-path: a manual run owns the KB — the worker waits its turn.

    The deferred trigger runs exactly once afterwards (a lone trigger is not
    "in flight" for itself: no trailing run on top).
    """
    import asyncio

    store = KnowledgeStore(session_factory)
    await _create_doc(store)
    calls = 0
    manual_running = True
    polled = asyncio.Event()

    async def _counting_generate(*_args, **_kwargs):
        nonlocal calls
        calls += 1

    def _manual_gate(_kb_id):
        polled.set()
        return manual_running

    monkeypatch.setattr("deerflow.knowledge.worker.generate_wiki", _counting_generate)
    monkeypatch.setattr("deerflow.knowledge.worker.wiki_trigger_ready", AsyncMock(return_value=True))
    monkeypatch.setattr("deerflow.knowledge.worker.wiki_generation_in_progress", _manual_gate, raising=False)
    worker = _worker(store, session_factory, main_llm=_WikiLLM())

    worker._spawn_wiki("kb-1", FakeEmbedder())
    # The runner has reached its cross-path gate and is deferring: assert on the
    # probe, not on elapsed time.
    await asyncio.wait_for(polled.wait(), timeout=5)
    assert calls == 0, "the worker run overlapped the manual run"
    manual_running = False
    await worker.wait_idle()

    assert calls == 1, f"a lone trigger must run exactly once, got {calls}"


# ── 触发面加固（spec 2026-10-02 ⑤）────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_failed_task_creation_never_freezes_the_kb(session_factory, monkeypatch):
    """⑤: a create_task failure must not leave the busy claim stuck.

    The claim exists to keep one runner per KB; if no runner can start, the
    claim must not survive — otherwise every later trigger folds into a
    pending set nothing drains and the KB goes silently dead.
    """
    import asyncio

    store = KnowledgeStore(session_factory)
    await _create_doc(store)
    calls = 0

    async def _counting_generate(*_args, **_kwargs):
        nonlocal calls
        calls += 1

    monkeypatch.setattr("deerflow.knowledge.worker.generate_wiki", _counting_generate)
    monkeypatch.setattr("deerflow.knowledge.worker.wiki_trigger_ready", AsyncMock(return_value=True))
    worker = _worker(store, session_factory, main_llm=_WikiLLM())
    embedder = FakeEmbedder()
    real_create_task = asyncio.create_task

    def _boom(*_args, **_kwargs):
        raise RuntimeError("no running loop")

    monkeypatch.setattr("asyncio.create_task", _boom)
    with pytest.raises(RuntimeError):
        worker._spawn_wiki("kb-1", embedder)
    assert "kb-1" not in worker._wiki_busy, "a failed spawn froze the KB behind a dead claim"
    assert "kb-1" in worker._wiki_pending
    monkeypatch.setattr("asyncio.create_task", real_create_task)

    worker._spawn_wiki("kb-1", embedder)
    await worker.wait_idle()

    assert calls == 1, "the trigger after a failed spawn never ran"


# ── 开机扫描（spec 2026-10-02 Task 3，D2=不过阈值门）────────────────────────


@pytest.mark.asyncio
async def test_boot_scan_resumes_dirty_wikis_without_new_documents(session_factory, monkeypatch):
    """D2=不过阈值门: a dirty entry stranded by a crash is resumed at boot.

    The KB has zero documents, so the trigger threshold can never pass
    (``wiki_trigger_ready`` refuses total==0) — the boot scan is the one leg
    that skips it, matching the manual button's "有 dirty 就跑" stance.
    Without the scan the entry strands until the next document completes.
    """
    store = KnowledgeStore(session_factory)
    wiki_store = WikiStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await wiki_store.upsert_entry("kb-1", title="DeerFlow", content="旧条目", source_chunk_ids=[], status="dirty")
    seen: list[bool] = []

    async def _counting_generate(*_args, **kwargs):
        seen.append(kwargs.get("only_dirty"))

    monkeypatch.setattr("deerflow.knowledge.worker.generate_wiki", _counting_generate)
    worker = _worker(store, session_factory, main_llm=_WikiLLM())

    await worker.start()
    await worker.wait_idle()
    await worker.stop()

    assert seen == [True], f"boot scan must resume the dirty entry exactly once as a dirty pass, got {seen}"


@pytest.mark.asyncio
async def test_boot_scan_skips_kbs_without_dirty_entries(session_factory, monkeypatch):
    """Scope guard: the boot scan touches only KBs carrying dirty entries.

    A boot scan over every KB would re-run generation for libraries that are
    fully settled — wasted LLM passes on every restart.
    """
    store = KnowledgeStore(session_factory)
    wiki_store = WikiStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await wiki_store.upsert_entry("kb-1", title="DeerFlow", content="旧条目", source_chunk_ids=[], status="ready")
    calls = 0

    async def _counting_generate(*_args, **_kwargs):
        nonlocal calls
        calls += 1

    monkeypatch.setattr("deerflow.knowledge.worker.generate_wiki", _counting_generate)
    worker = _worker(store, session_factory, main_llm=_WikiLLM())

    await worker.start()
    await worker.wait_idle()
    await worker.stop()

    assert calls == 0, f"a settled KB must not be regenerated at boot, got {calls} run(s)"


# ── D2 嵌入身份（spec 2026-10-04 §2.2：新库首次入库完成 ⇒ 盖章）────────────────


class _IdentityEmbedder(FakeEmbedder):
    identity = "space-a"


@pytest.mark.asyncio
async def test_the_first_completed_document_stamps_the_library_identity(session_factory):
    store = KnowledgeStore(session_factory)
    await _create_doc(store)
    worker = _worker(store, session_factory, parse_fn=_parse_fn(), llm=FakeLLM({"DeerFlow": {"entities": [{"name": "DeerFlow", "type": "系统", "description": "框架"}], "relations": []}}), embedder=_IdentityEmbedder())

    await worker.process_document("doc-1")

    assert (await store.get_kb("kb-1"))["embedding_identity"] == "space-a"


@pytest.mark.asyncio
async def test_an_incremental_document_never_overwrites_the_library_identity(session_factory):
    """遗留库（已有终态文档、身份未记）不能被新入库盖成「均匀」——那会遮掉存量的旧空间声明。"""
    store = KnowledgeStore(session_factory)
    await _create_doc(store)
    await store.update_document_status("doc-1", "ready")
    await store.create_document(doc_id="doc-2", kb_id="kb-1", uploader_id="user-1", name="b.md", size_bytes=3, storage_path="/tmp/b.md")
    worker = _worker(store, session_factory, parse_fn=_parse_fn(), llm=FakeLLM({"DeerFlow": {"entities": [{"name": "DeerFlow", "type": "系统", "description": "框架"}], "relations": []}}), embedder=_IdentityEmbedder())

    await worker.process_document("doc-2")

    assert (await store.get_kb("kb-1"))["embedding_identity"] is None
