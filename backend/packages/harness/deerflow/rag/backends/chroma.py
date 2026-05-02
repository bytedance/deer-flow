"""ChromaDB vector store backend."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from deerflow.config.tenant import get_current_tenant_id
from deerflow.rag.vector_store import SearchResult, VectorStore

logger = logging.getLogger(__name__)


class ChromaVectorStore(VectorStore):
    """ChromaDB-backed vector store with tenant isolation via collection naming."""

    def __init__(self, persist_dir: str = "") -> None:
        self._persist_dir = persist_dir
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import chromadb
            except ImportError:
                raise ImportError(
                    "chromadb is required for the Chroma vector store backend. "
                    "Install it with: uv add chromadb"
                )
            kwargs: dict[str, Any] = {}
            if self._persist_dir:
                kwargs["path"] = self._persist_dir
            else:
                from deerflow.config.paths import get_paths

                persist_path = get_paths().tenant_base_dir / "chroma"
                persist_path.mkdir(parents=True, exist_ok=True)
                kwargs["path"] = str(persist_path)
            self._client = chromadb.PersistentClient(**kwargs)
        return self._client

    def _collection_name(self, collection: str) -> str:
        """Return the tenant-scoped collection name."""
        tid = get_current_tenant_id()
        return f"{tid}_{collection}"

    def add(
        self,
        collection: str,
        chunks: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> list[str]:
        client = self._get_client()
        col_name = self._collection_name(collection)
        col = client.get_or_create_collection(name=col_name)

        ids = [uuid.uuid4().hex for _ in chunks]
        documents = [c["content"] for c in chunks]
        metadatas = [c.get("metadata", {}) for c in chunks]

        col.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
        logger.info("Added %d chunks to collection %r", len(ids), col_name)
        return ids

    def search(
        self,
        collection: str,
        query_embedding: list[float],
        top_k: int = 5,
        score_threshold: float = 0.0,
    ) -> list[SearchResult]:
        client = self._get_client()
        col_name = self._collection_name(collection)

        try:
            col = client.get_collection(name=col_name)
        except Exception:
            return []

        results = col.query(query_embeddings=[query_embedding], n_results=top_k)

        ids_list = results.get("ids", [[]])[0]
        docs_list = results.get("documents", [[]])[0]
        metas_list = results.get("metadatas", [[]])[0]
        dists_list = results.get("distances", [[]])[0]

        search_results: list[SearchResult] = []
        for i, chunk_id in enumerate(ids_list):
            distance = dists_list[i] if i < len(dists_list) else 0.0
            score = 1.0 - (distance / 2.0)  # cosine distance → similarity
            if score < score_threshold:
                continue
            search_results.append(
                SearchResult(
                    chunk_id=chunk_id,
                    content=docs_list[i] if i < len(docs_list) else "",
                    metadata=metas_list[i] if i < len(metas_list) else {},
                    score=score,
                )
            )
        return search_results

    def delete(self, collection: str, chunk_ids: list[str]) -> int:
        client = self._get_client()
        col_name = self._collection_name(collection)
        try:
            col = client.get_collection(name=col_name)
            col.delete(ids=chunk_ids)
            return len(chunk_ids)
        except Exception:
            return 0

    def list_collections(self) -> list[str]:
        client = self._get_client()
        tid = get_current_tenant_id()
        prefix = f"{tid}_"
        all_cols = client.list_collections()
        return [c.name[len(prefix):] for c in all_cols if c.name.startswith(prefix)]

    def delete_collection(self, collection: str) -> bool:
        client = self._get_client()
        col_name = self._collection_name(collection)
        try:
            client.delete_collection(name=col_name)
            return True
        except Exception:
            return False

    def count(self, collection: str) -> int:
        client = self._get_client()
        col_name = self._collection_name(collection)
        try:
            col = client.get_collection(name=col_name)
            return col.count()
        except Exception:
            return 0
