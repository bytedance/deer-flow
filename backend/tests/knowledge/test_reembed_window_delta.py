"""The rebuild window's delta pass (spec 2026-10-05 §2, plan Task 1).

The same-width in-place rebuild walks each library once and flips the configuration when
the walk reports done. ``reindex_kb`` snapshots the document list at its start, so a
document that arrives behind that snapshot is never re-embedded and stays in the old
vector space — while the post-flip identity stamp would claim the library is one space.
The delta pass walks the libraries that *changed* during the window again after the flip
(the width channel's content-mark gate), and the stamp lands on the delta's completion
(D2=乙), never on the main walk's.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from qdrant_client.models import SparseVector

from app.gateway.services import rag_reembed as reembed_module
from deerflow.knowledge import reindex as reindex_mod
from deerflow.knowledge.embed_identity import write_kb_identity
from deerflow.knowledge.embedder import EmbedderError, EmbeddingResult
from deerflow.knowledge.graph.store import GraphStore
from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.vector_store import ChunkUpsert, EntityUpsert, ManualCardUpsert, WikiEntryUpsert
from deerflow.knowledge.wiki.store import WikiStore

OWNER_ID = str(uuid.UUID(int=9876543210))


class _FakeVectorStore:
    """Records the upserts instead of talking to Qdrant (no service needed in CI)."""

    def __init__(self) -> None:
        self.upserts: list[ChunkUpsert] = []
        self.entities: list[EntityUpsert] = []
        self.wiki_entries: list[WikiEntryUpsert] = []
        self.manual_cards: list[ManualCardUpsert] = []

    async def upsert_chunks(self, items) -> None:
        self.upserts.extend(items)

    async def upsert_entities(self, items) -> None:
        self.entities.extend(items)

    async def upsert_wiki_entries(self, items) -> None:
        self.wiki_entries.extend(items)

    async def upsert_manual_cards(self, items) -> None:
        self.manual_cards.extend(items)


class _DeterministicEmbedder:
    """Text → a stable vector, with a call log and an optional fail list."""

    batch_size = 8
    identity = "space-test"

    def __init__(self, *, fail_texts: set[str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self._fail = fail_texts or set()

    async def embed(self, texts, *, text_type: str = "document") -> list[EmbeddingResult]:
        self.calls.append(list(texts))
        if self._fail & set(texts):
            raise EmbedderError("embedding service down")
        return [
            EmbeddingResult(
                dense=[float(len(text)), float(sum(map(ord, text)) % 97)],
                sparse=SparseVector(indices=[index, index + 10], values=[0.5, 0.25]),
            )
            for index, text in enumerate(texts)
        ]

    def texts(self) -> list[str]:
        return [text for call in self.calls for text in call]


async def _kb(store: KnowledgeStore, *, kb_id: str) -> None:
    await store.create_kb(kb_id=kb_id, owner_id=OWNER_ID, name=f"库-{kb_id}")


async def _seed_doc(store: KnowledgeStore, *, kb_id: str, doc_id: str, texts: list[str]) -> None:
    await store.create_document(doc_id=doc_id, kb_id=kb_id, uploader_id=OWNER_ID, name=f"{doc_id}.pdf", size_bytes=1, storage_path="gone.pdf")
    await store.update_document_status(doc_id, "ready")
    await store.insert_chunks([{"chunk_id": f"{doc_id}#{index:04d}", "doc_id": doc_id, "kb_id": kb_id, "chunk_index": index, "text": text, "heading_path": ["H"], "page": index} for index, text in enumerate(texts)])


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    for kb_id in ("kb-1", "kb-2"):
        reindex_mod._IN_FLIGHT.pop(kb_id, None)
        reindex_mod._LAST_RUN.pop(kb_id, None)
        reindex_mod._PROGRESS.pop(kb_id, None)
    reembed_module.reset_state()


async def _run_channel(store: KnowledgeStore, monkeypatch, embedder, *, after_walk=None, flip=None, swallow_errors: bool = False) -> tuple[_FakeVectorStore, list[str]]:
    """Drive one rebuild through the real ``_run``: real walks, stubbed file write.

    ``after_walk`` runs after the main walk completes and before the flip — the window
    where a new document is invisible to the walk's snapshot but still in the old space.
    ``flip`` replaces the file write (a raising one is how the flip-failure case reaches
    ``_run``); ``swallow_errors`` keeps a dying task from masking the state assertions.
    """
    vector_store = _FakeVectorStore()
    events: list[str] = []
    real_walk = reembed_module.reembed_libraries

    async def _walk(store_, *, vector_store, embedder, graph_store, wiki_store):
        result = await real_walk(store_, vector_store=vector_store, embedder=embedder, graph_store=graph_store, wiki_store=wiki_store)
        if after_walk is not None:
            await after_walk()
        return result

    real_stamp = reindex_mod.write_kb_identity

    async def _stamp(session_factory, kb_id, identity):
        events.append("stamp")
        await real_stamp(session_factory, kb_id, identity)

    monkeypatch.setattr(reembed_module, "reembed_libraries", _walk)
    monkeypatch.setattr(reembed_module, "write_rag_config", flip or (lambda data: events.append("flip")))
    monkeypatch.setattr(reindex_mod, "write_kb_identity", _stamp)
    monkeypatch.setattr(reembed_module, "write_kb_identity", _stamp)

    reembed_module.reset_state()
    reembed_module.start_reembed(
        store=store,
        graph_store=GraphStore(store._sf),
        wiki_store=WikiStore(store._sf),
        vector_store=vector_store,
        embedder=embedder,
        target_payload={"embedding_provider": "p", "embedding_model": "m-target", "embedding_base_url": "https://target.example/v1"},
    )
    await asyncio.gather(*tuple(reembed_module._TASKS), return_exceptions=swallow_errors)
    return vector_store, events


# ── D2=乙 盖章后移 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_stamp_lands_after_the_flip_not_after_the_main_walk(session_factory, monkeypatch):
    """章必须在翻转之后落（delta 走完）——主行走走完就盖是假声明的来源。"""
    store = KnowledgeStore(session_factory)
    await _kb(store, kb_id="kb-1")
    await _seed_doc(store, kb_id="kb-1", doc_id="doc-1", texts=["风急天高", "渚清沙白"])

    _vector_store, events = await _run_channel(store, monkeypatch, _DeterministicEmbedder())

    assert events == ["flip", "stamp"], "翻转先于盖章：章是 delta 的结论，不是主行走的"
    assert (await store.get_kb("kb-1"))["embedding_identity"] == "space-test"


# ── 快照缝 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_document_that_arrives_behind_the_walk_snapshot_is_re_embedded_after_the_flip(session_factory, monkeypatch):
    """快照缝里的文档（行走列表里没有它）必须被 delta 复走补进新空间。"""
    store = KnowledgeStore(session_factory)
    await _kb(store, kb_id="kb-1")
    await _seed_doc(store, kb_id="kb-1", doc_id="doc-1", texts=["doc-1 独有句"])

    async def _arrive():
        await _seed_doc(store, kb_id="kb-1", doc_id="doc-2", texts=["窗口新到的句子"])

    embedder = _DeterministicEmbedder()
    await _run_channel(store, monkeypatch, embedder, after_walk=_arrive)

    assert embedder.texts().count("窗口新到的句子") == 1, "窗口里新到的文档必须由 delta 重嵌一遍"
    assert (await store.get_kb("kb-1"))["embedding_identity"] == "space-test"


# ── 指纹门 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_delta_walk_skips_the_libraries_the_window_never_touched(session_factory, monkeypatch):
    """门槛（甲）：动过的库整库复走、没动过的库零嵌入——别让没动的库白付第二遍。"""
    store = KnowledgeStore(session_factory)
    await _kb(store, kb_id="kb-1")
    await _kb(store, kb_id="kb-2")
    await _seed_doc(store, kb_id="kb-1", doc_id="doc-a1", texts=["kb1 恒定句"])
    await _seed_doc(store, kb_id="kb-2", doc_id="doc-b1", texts=["kb2 恒定句"])

    async def _arrive():
        await _seed_doc(store, kb_id="kb-2", doc_id="doc-b2", texts=["kb2 窗口新句"])

    embedder = _DeterministicEmbedder()
    await _run_channel(store, monkeypatch, embedder, after_walk=_arrive)

    counts = embedder.texts()
    assert counts.count("kb1 恒定句") == 1, "没动过的库不该被 delta 复走"
    assert counts.count("kb2 恒定句") == 2, "动过的库整库复走（主行走 + delta）"
    assert counts.count("kb2 窗口新句") == 1, "窗口新句只在 delta 里出现"
    assert (await store.get_kb("kb-1"))["embedding_identity"] == "space-test", "跳过复走 ≠ 跳过盖章：主行走完整且窗口未动就是均匀空间"


# ── 失败面 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_delta_that_raises_fails_the_run_and_leaves_the_stamp_alone(session_factory, monkeypatch):
    """delta raise ⇒ 状态 failed、章留旧值：失败必须诚实，不许留假声明。"""
    store = KnowledgeStore(session_factory)
    await _kb(store, kb_id="kb-1")
    await _seed_doc(store, kb_id="kb-1", doc_id="doc-1", texts=["doc-1 独有句"])
    await write_kb_identity(store._sf, "kb-1", "old-space")

    async def _arrive():
        await _seed_doc(store, kb_id="kb-1", doc_id="doc-2", texts=["窗口新到的句子"])

    real_reindex = reembed_module.reindex_kb

    async def _explode_on_delta(*args, **kwargs):
        if kwargs.get("include_non_terminal"):
            raise RuntimeError("delta 塌了")
        return await real_reindex(*args, **kwargs)

    monkeypatch.setattr(reembed_module, "reindex_kb", _explode_on_delta)
    await _run_channel(store, monkeypatch, _DeterministicEmbedder(), after_walk=_arrive)

    assert reembed_module.reembed_status()["state"] == "failed"
    assert (await store.get_kb("kb-1"))["embedding_identity"] == "old-space"


@pytest.mark.asyncio
async def test_a_soft_failure_in_the_delta_still_flips_but_never_stamps(session_factory, monkeypatch):
    """软失败（单文档嵌入失败）⇒ 照常翻转、succeeded，但不盖章：库里不是均匀空间。"""
    store = KnowledgeStore(session_factory)
    await _kb(store, kb_id="kb-1")
    await _seed_doc(store, kb_id="kb-1", doc_id="doc-1", texts=["doc-1 正常句"])
    await write_kb_identity(store._sf, "kb-1", "old-space")

    async def _arrive():
        await _seed_doc(store, kb_id="kb-1", doc_id="doc-2", texts=["delta 会失败的句子"])

    embedder = _DeterministicEmbedder(fail_texts={"delta 会失败的句子"})
    await _run_channel(store, monkeypatch, embedder, after_walk=_arrive)

    assert embedder.texts().count("delta 会失败的句子") >= 1, "delta 确实碰过那篇文档"
    assert reembed_module.reembed_status()["state"] == "succeeded"
    assert (await store.get_kb("kb-1"))["embedding_identity"] == "old-space"


@pytest.mark.asyncio
async def test_an_untouched_library_that_walked_incompletely_stays_unstamped(session_factory, monkeypatch):
    """门槛的另一半：没动过但主行走有软失败 ⇒ 不盖章——「未动」不等于「均匀」。"""
    store = KnowledgeStore(session_factory)
    await _kb(store, kb_id="kb-1")
    await _seed_doc(store, kb_id="kb-1", doc_id="doc-1", texts=["主行走会失败的句子"])
    await write_kb_identity(store._sf, "kb-1", "old-space")

    embedder = _DeterministicEmbedder(fail_texts={"主行走会失败的句子"})
    await _run_channel(store, monkeypatch, embedder)

    assert reembed_module.reembed_status()["state"] == "succeeded"
    assert (await store.get_kb("kb-1"))["embedding_identity"] == "old-space"


# ── 翻转写加固（③）─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_flip_write_that_raises_fails_the_run_instead_of_sticking_on_running(session_factory, monkeypatch):
    """翻转写在保护罩外 ⇒ 任务死、状态永驻 running ⇒ 后续保存全 409：必须落 failed（③ 半二）。"""
    store = KnowledgeStore(session_factory)
    await _kb(store, kb_id="kb-1")
    await _seed_doc(store, kb_id="kb-1", doc_id="doc-1", texts=["风急天高"])

    def _boom(data):
        raise PermissionError(13, "拒绝访问。")

    _vector_store, events = await _run_channel(store, monkeypatch, _DeterministicEmbedder(), flip=_boom, swallow_errors=True)

    assert reembed_module.reembed_status()["state"] == "failed", "翻转写死了，状态必须落 failed"
    assert reembed_module.reembed_running() is False, "不许永驻 running——那会让后续保存全被 409 挡到重启"
    assert "stamp" not in events, "翻转都没成功，章不许落"
