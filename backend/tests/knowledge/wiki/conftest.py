"""Fixtures for wiki-path (head-entity entry generation) tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from qdrant_client import AsyncQdrantClient

from deerflow.knowledge.graph.extractor import ExtractedEntity, ExtractedRelation
from deerflow.knowledge.graph.store import GraphStore
from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.vector_store import KnowledgeVectorStore

from ..conftest import QDRANT_TEST_URL

#: Five entities with controlled degree/frequency scores (DiGraph degree = in+out):
#:   DeerFlow  degree 3 (3 out)            + 2 chunks = 5
#:   Gateway   degree 2 (1 in + 1 out)     + 1 chunk  = 3
#:   Qdrant    degree 1 + 1 chunk = 2   LangGraph degree 1 + 1 chunk = 2
#:   MinerU    degree 1 + 1 chunk = 2
ENTITY_ROWS = [
    ExtractedEntity(name="DeerFlow", type="系统", description="超级智能体框架"),
    ExtractedEntity(name="Gateway", type="组件", description="会话管理"),
    ExtractedEntity(name="Qdrant", type="服务", description="向量库"),
    ExtractedEntity(name="LangGraph", type="框架", description="底层编排"),
    ExtractedEntity(name="MinerU", type="服务", description="文档解析"),
]

RELATION_ROWS = [
    ExtractedRelation(source="DeerFlow", target="Gateway", relation="包含", description=""),
    ExtractedRelation(source="DeerFlow", target="Qdrant", relation="使用", description=""),
    ExtractedRelation(source="DeerFlow", target="LangGraph", relation="基于", description=""),
    ExtractedRelation(source="Gateway", target="MinerU", relation="调用", description=""),
]


@pytest_asyncio.fixture
async def wiki_db_env(session_factory) -> AsyncIterator[dict]:
    """KB + document + graph-done chunks + a populated graph store (no Qdrant)."""
    store = KnowledgeStore(session_factory)
    graph_store = GraphStore(session_factory)
    kb_id, doc_id = "kb-w", "doc-w"
    await store.create_kb(kb_id=kb_id, owner_id="user-1", name="百科测试库")
    await store.create_document(doc_id=doc_id, kb_id=kb_id, uploader_id="user-1", name="架构.md", size_bytes=10, storage_path="/a.md")
    await store.insert_chunks(
        [
            {
                "chunk_id": f"{doc_id}-c{i}",
                "doc_id": doc_id,
                "kb_id": kb_id,
                "chunk_index": i,
                "text": text,
                "token_count": 50,
                "extract_status": "done",
                "entities": entities,
            }
            for i, (text, entities) in enumerate(
                [
                    ("DeerFlow 是基于 LangGraph 的超级智能体系统，包含 Gateway。", ["DeerFlow", "LangGraph", "Gateway"]),
                    ("DeerFlow 使用 Qdrant 存储向量，Gateway 调用 MinerU 解析文档。", ["DeerFlow", "Qdrant", "Gateway", "MinerU"]),
                ]
            )
        ]
    )
    # Entity frequencies: DeerFlow appears in both chunks, the rest in one each.
    for entity in ENTITY_ROWS:
        chunk_id = f"{doc_id}-c0" if entity.name in ("DeerFlow", "LangGraph", "Gateway") else f"{doc_id}-c1"
        await graph_store.upsert_entities(kb_id, [entity], chunk_id=chunk_id)
    await graph_store.upsert_entities(kb_id, [ExtractedEntity(name="DeerFlow", type="系统", description="超级智能体框架")], chunk_id=f"{doc_id}-c1")
    for relation in RELATION_ROWS:
        await graph_store.upsert_relations(kb_id, [relation], chunk_id=f"{doc_id}-c0")
    return {"store": store, "graph_store": graph_store, "kb_id": kb_id, "doc_id": doc_id}


@pytest_asyncio.fixture
async def wiki_env(wiki_db_env) -> AsyncIterator[dict]:
    """wiki_db_env plus a uniquely-prefixed vector store (torn down afterwards)."""
    client = AsyncQdrantClient(QDRANT_TEST_URL, timeout=10.0)
    vector_store = KnowledgeVectorStore(client=client, collection_prefix=f"testw{uuid.uuid4().hex[:10]}")
    await vector_store.init_collections()
    try:
        yield {**wiki_db_env, "vector_store": vector_store, "client": client}
    finally:
        for name in vector_store.collection_names:
            await client.delete_collection(name)
        await client.close()
