"""PostgreSQL pgvector vector store backend."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from deerflow.config.tenant import get_current_tenant_id
from deerflow.rag.vector_store import SearchResult, VectorStore

logger = logging.getLogger(__name__)


class PgvectorVectorStore(VectorStore):
    """PostgreSQL pgvector-backed vector store with tenant isolation via tenant_id column."""

    def __init__(self, connection_string: str = "") -> None:
        self._connection_string = connection_string
        self._engine: Any = None
        self._table_initialized = False

    def _get_engine(self) -> Any:
        if self._engine is None:
            try:
                from sqlalchemy import create_engine
            except ImportError:
                raise ImportError(
                    "sqlalchemy is required for the pgvector backend. "
                    "Install it with: uv add sqlalchemy psycopg[binary] pgvector"
                )
            conn_str = self._connection_string
            if not conn_str:
                raise ValueError("pgvector_connection_string must be set in RAG config")
            self._engine = create_engine(conn_str)
        return self._engine

    def _ensure_table(self) -> None:
        if self._table_initialized:
            return
        engine = self._get_engine()
        with engine.begin() as conn:
            conn.execute(  # type: ignore[attr-defined]
                """
                CREATE EXTENSION IF NOT EXISTS vector;
                CREATE TABLE IF NOT EXISTS deerflow_rag_chunks (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tenant_id TEXT NOT NULL,
                    collection TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata JSONB DEFAULT '{}',
                    embedding vector,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_rag_tenant_collection
                    ON deerflow_rag_chunks (tenant_id, collection);
                """
            )
        self._table_initialized = True

    def add(
        self,
        collection: str,
        chunks: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> list[str]:
        self._ensure_table()
        engine = self._get_engine()
        tid = get_current_tenant_id()
        import json

        ids = [uuid.uuid4().hex for _ in chunks]
        with engine.begin() as conn:
            for i, chunk in enumerate(chunks):
                conn.execute(  # type: ignore[attr-defined]
                    """
                    INSERT INTO deerflow_rag_chunks (tenant_id, collection, chunk_id, content, metadata, embedding)
                    VALUES (:tid, :col, :cid, :content, :meta, :emb)
                    """,
                    {
                        "tid": tid,
                        "col": collection,
                        "cid": ids[i],
                        "content": chunk["content"],
                        "meta": json.dumps(chunk.get("metadata", {})),
                        "emb": str(embeddings[i]),
                    },
                )
        logger.info("Added %d chunks to pgvector collection %r", len(ids), collection)
        return ids

    def search(
        self,
        collection: str,
        query_embedding: list[float],
        top_k: int = 5,
        score_threshold: float = 0.0,
    ) -> list[SearchResult]:
        self._ensure_table()
        engine = self._get_engine()
        tid = get_current_tenant_id()
        import json

        with engine.begin() as conn:
            rows = conn.execute(  # type: ignore[attr-defined]
                """
                SELECT chunk_id, content, metadata,
                       1.0 - (embedding <=> :emb::vector) AS similarity
                FROM deerflow_rag_chunks
                WHERE tenant_id = :tid AND collection = :col
                  AND 1.0 - (embedding <=> :emb::vector) >= :threshold
                ORDER BY embedding <=> :emb::vector
                LIMIT :limit
                """,
                {
                    "tid": tid,
                    "col": collection,
                    "emb": str(query_embedding),
                    "threshold": score_threshold,
                    "limit": top_k,
                },
            ).fetchall()

        results: list[SearchResult] = []
        for row in rows:
            meta = row[2]
            if isinstance(meta, str):
                meta = json.loads(meta)
            results.append(
                SearchResult(
                    chunk_id=row[0],
                    content=row[1],
                    metadata=meta or {},
                    score=float(row[3]),
                )
            )
        return results

    def delete(self, collection: str, chunk_ids: list[str]) -> int:
        self._ensure_table()
        engine = self._get_engine()
        tid = get_current_tenant_id()
        with engine.begin() as conn:
            result = conn.execute(  # type: ignore[attr-defined]
                "DELETE FROM deerflow_rag_chunks WHERE tenant_id = :tid AND collection = :col AND chunk_id = ANY(:ids)",
                {"tid": tid, "col": collection, "ids": chunk_ids},
            )
            return result.rowcount

    def list_collections(self) -> list[str]:
        self._ensure_table()
        engine = self._get_engine()
        tid = get_current_tenant_id()
        with engine.begin() as conn:
            rows = conn.execute(  # type: ignore[attr-defined]
                "SELECT DISTINCT collection FROM deerflow_rag_chunks WHERE tenant_id = :tid ORDER BY collection",
                {"tid": tid},
            ).fetchall()
        return [r[0] for r in rows]

    def delete_collection(self, collection: str) -> bool:
        self._ensure_table()
        engine = self._get_engine()
        tid = get_current_tenant_id()
        with engine.begin() as conn:
            conn.execute(  # type: ignore[attr-defined]
                "DELETE FROM deerflow_rag_chunks WHERE tenant_id = :tid AND collection = :col",
                {"tid": tid, "col": collection},
            )
        return True

    def count(self, collection: str) -> int:
        self._ensure_table()
        engine = self._get_engine()
        tid = get_current_tenant_id()
        with engine.begin() as conn:
            row = conn.execute(  # type: ignore[attr-defined]
                "SELECT COUNT(*) FROM deerflow_rag_chunks WHERE tenant_id = :tid AND collection = :col",
                {"tid": tid, "col": collection},
            ).fetchone()
        return row[0] if row else 0
