"""Fixtures for the retrieval tool tests (spec §4).

One shared environment: KB ``kb-t`` (owner ``user-1``) with one document and
three chunks, and a uniquely-prefixed Qdrant store whose points are seeded with
the same keyword one-hot embedder the tools are tested with — so a query
containing a keyword deterministically lands on the chunk carrying it.
"""

from __future__ import annotations

import uuid
import zlib
from collections.abc import AsyncIterator, Sequence
from types import SimpleNamespace

import pytest_asyncio
from deerflow_knowledge.embedder import EmbeddingResult
from deerflow_knowledge.store import KnowledgeStore
from deerflow_knowledge.vector_store import ChunkUpsert, KnowledgeVectorStore
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import SparseVector

from deerflow.knowledge_scope import KNOWLEDGE_SCOPE_RUNTIME_KEY, local_dataset_id

from ..conftest import QDRANT_TEST_URL

KB_ID = "kb-t"
DOC_ID = "doc-t"
OWNER_ID = "user-1"


def scope_runtime(
    kb_id: str | None = KB_ID,
    *,
    user_id: str = OWNER_ID,
    mode: str = "selected",
) -> SimpleNamespace:
    """Runtime carrying one admitted execution scope in its context dict.

    Mirrors what KnowledgeScopeMiddleware injects: the runtime-context carrier
    only, provider-qualified dataset ids (``local:<kb_id>``).
    """
    context: dict = {"user_id": user_id}
    if mode == "selected":
        if kb_id is not None:
            context[KNOWLEDGE_SCOPE_RUNTIME_KEY] = {
                "version": 1,
                "mode": "selected",
                "dataset_ids": [local_dataset_id(kb_id)],
            }
    else:
        context[KNOWLEDGE_SCOPE_RUNTIME_KEY] = {"version": 1, "mode": mode}
    return SimpleNamespace(context=context)


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
    try:
        yield {
            "store": store,
            "vector_store": vector_store,
            "client": client,
            "embedder": embedder,
        }
    finally:
        for name in vector_store.collection_names:
            await client.delete_collection(name)
        await client.close()
