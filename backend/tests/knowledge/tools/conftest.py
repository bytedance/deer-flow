"""Fixtures for the three retrieval tools (spec §4).

One shared environment: KB ``kb-t`` (owner ``user-1``) with one document and
three chunks, a small graph (DeerFlow → Gateway → MinerU), one wiki entry,
and a uniquely-prefixed Qdrant store whose points are seeded with the same
keyword one-hot embedder the tools are tested with — so a query containing a
keyword deterministically lands on the chunk/entity/entry carrying it.
"""

from __future__ import annotations

import uuid
import zlib
from collections.abc import AsyncIterator, Sequence

import pytest_asyncio
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import SparseVector

from deerflow.knowledge.embedder import EmbeddingResult
from deerflow.knowledge.graph.extractor import ExtractedEntity, ExtractedRelation
from deerflow.knowledge.graph.store import GraphStore
from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.vector_store import ChunkUpsert, EntityUpsert, KnowledgeVectorStore, WikiEntryUpsert
from deerflow.knowledge.wiki.store import WikiStore

from ..conftest import QDRANT_TEST_URL

KB_ID = "kb-t"
DOC_ID = "doc-t"
OWNER_ID = "user-1"

#: keyword → one-hot dimension (deterministic "semantic" layout for tests).
KEYWORD_DIMS = {"Gateway": 10, "MinerU": 20, "DeerFlow": 30}

CHUNK_TEXTS = [
    ("Gateway 负责会话管理，是 DeerFlow 的入口组件。", ["DeerFlow", "Gateway"]),
    ("Gateway 调用 MinerU 完成文档解析。", ["Gateway", "MinerU"]),
    ("LangGraph 与检索内容无关的编排细节。", []),
]


def keyword_vector(text: str) -> list[float]:
    dense = [0.0] * 1024
    for keyword, dim in KEYWORD_DIMS.items():
        if keyword in text:
            dense[dim] = 1.0
            break
    else:
        dense[zlib.crc32(text.encode("utf-8")) % 900 + 100] = 1.0
    return dense


class KeywordEmbedder:
    """One-hot keyword embedder: queries land on documents sharing the keyword."""

    batch_size = 20

    async def embed(self, texts: Sequence[str], *, text_type: str = "document") -> list[EmbeddingResult]:
        return [EmbeddingResult(dense=keyword_vector(t), sparse=SparseVector(indices=[1], values=[0.5])) for t in texts]


@pytest_asyncio.fixture
async def tools_env(session_factory) -> AsyncIterator[dict]:
    store = KnowledgeStore(session_factory)
    graph_store = GraphStore(session_factory)
    wiki_store = WikiStore(session_factory)
    await store.create_kb(kb_id=KB_ID, owner_id=OWNER_ID, name="工具测试库")
    await store.create_document(doc_id=DOC_ID, kb_id=KB_ID, uploader_id=OWNER_ID, name="架构.md", size_bytes=10, storage_path="/a.md")
    await store.insert_chunks(
        [
            {
                "chunk_id": f"{DOC_ID}-c{i}",
                "doc_id": DOC_ID,
                "kb_id": KB_ID,
                "chunk_index": i,
                "text": text,
                "heading_path": ["架构"],
                "page": i + 1,
                "token_count": 40,
                "extract_status": "done" if entities else "empty",
                "entities": entities,
            }
            for i, (text, entities) in enumerate(CHUNK_TEXTS)
        ]
    )
    embedder = KeywordEmbedder()
    # Graph rows.
    await graph_store.upsert_entities(KB_ID, [ExtractedEntity(name="DeerFlow", type="系统", description="超级智能体")], chunk_id=f"{DOC_ID}-c0")
    await graph_store.upsert_entities(KB_ID, [ExtractedEntity(name="Gateway", type="组件", description="会话管理入口")], chunk_id=f"{DOC_ID}-c0")
    await graph_store.upsert_entities(KB_ID, [ExtractedEntity(name="MinerU", type="服务", description="文档解析服务")], chunk_id=f"{DOC_ID}-c1")
    await graph_store.upsert_relations(KB_ID, [ExtractedRelation(source="DeerFlow", target="Gateway", relation="包含", description="系统包含入口组件")], chunk_id=f"{DOC_ID}-c0")
    await graph_store.upsert_relations(KB_ID, [ExtractedRelation(source="Gateway", target="MinerU", relation="调用", description="解析调用")], chunk_id=f"{DOC_ID}-c1")
    # Wiki row.
    entry = await wiki_store.upsert_entry(KB_ID, title="DeerFlow", content="# DeerFlow\n\nDeerFlow 是基于 LangGraph 的超级智能体系统。", source_chunk_ids=[f"{DOC_ID}-c0"])

    prefix = f"testt{uuid.uuid4().hex[:10]}"
    client = AsyncQdrantClient(QDRANT_TEST_URL, timeout=10.0)
    vector_store = KnowledgeVectorStore(client=client, collection_prefix=prefix)
    await vector_store.init_collections()
    chunks = await store.list_chunks(DOC_ID, limit=10)
    await vector_store.upsert_chunks(
        [
            ChunkUpsert(
                chunk_id=c["chunk_id"],
                kb_id=KB_ID,
                doc_id=DOC_ID,
                dense=(await embedder.embed([c["text"]]))[0].dense,
                sparse=SparseVector(indices=[1], values=[0.5]),
                doc_name="架构.md",
                heading_path=c["heading_path"],
                page=c["page"],
                entities=c["entities"],
            )
            for c in chunks
        ]
    )
    for name, chunk_id in (("DeerFlow", f"{DOC_ID}-c0"), ("Gateway", f"{DOC_ID}-c0"), ("MinerU", f"{DOC_ID}-c1")):
        await vector_store.upsert_entities([EntityUpsert(name=name, kb_id=KB_ID, type="x", description=f"{name} 描述", dense=(await embedder.embed([name]))[0].dense)])
    await vector_store.upsert_wiki_entries([WikiEntryUpsert(entry_id=entry["id"], kb_id=KB_ID, title="DeerFlow", dense=(await embedder.embed(["DeerFlow"]))[0].dense)])
    try:
        yield {
            "store": store,
            "graph_store": graph_store,
            "wiki_store": wiki_store,
            "vector_store": vector_store,
            "client": client,
            "embedder": embedder,
            "entry_id": entry["id"],
        }
    finally:
        for name in vector_store.collection_names:
            await client.delete_collection(name)
        await client.close()
