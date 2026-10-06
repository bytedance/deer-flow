"""Fixtures for graph-path (extract → normalize → store) tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from qdrant_client import AsyncQdrantClient

from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.vector_store import KnowledgeVectorStore

from ..conftest import QDRANT_TEST_URL

CHUNK_TEXTS = [
    "DeerFlow 是一个基于 LangGraph 的超级智能体系统，包含 Gateway 与沙箱。Gateway 负责会话管理。",
    "索引流水线由 Parser 与 Chunker 组成。Parser 调用 MinerU 解析文档，Chunker 按标题切片。",
    "Qdrant 存储切片向量。Embedder 调用 DashScope 产出稠密与稀疏向量，Indexer 负责写入 Qdrant。",
]


@pytest_asyncio.fixture
async def graph_env(session_factory) -> AsyncIterator[dict]:
    """KB + document + 3 pending chunks, plus a uniquely-prefixed vector store.

    Yields a dict with the business store, vector store, raw Qdrant client and
    the ids; the vector store collections are torn down afterwards.
    """
    store = KnowledgeStore(session_factory)
    kb_id, doc_id = "kb-g", "doc-g"
    await store.create_kb(kb_id=kb_id, owner_id="user-1", name="图谱测试库")
    await store.create_document(doc_id=doc_id, kb_id=kb_id, uploader_id="user-1", name="架构.md", size_bytes=100, storage_path="/a.md")
    await store.insert_chunks(
        [
            {
                "chunk_id": f"{doc_id}-c{i}",
                "doc_id": doc_id,
                "kb_id": kb_id,
                "chunk_index": i,
                "text": text,
                "heading_path": ["架构"],
                "page": i + 1,
                "token_count": 60,
            }
            for i, text in enumerate(CHUNK_TEXTS)
        ]
    )
    prefix = f"testg{uuid.uuid4().hex[:10]}"
    client = AsyncQdrantClient(QDRANT_TEST_URL, timeout=10.0)
    vector_store = KnowledgeVectorStore(client=client, collection_prefix=prefix)
    await vector_store.init_collections()
    try:
        yield {"store": store, "vector_store": vector_store, "client": client, "kb_id": kb_id, "doc_id": doc_id}
    finally:
        for name in vector_store.collection_names:
            await client.delete_collection(name)
        await client.close()
