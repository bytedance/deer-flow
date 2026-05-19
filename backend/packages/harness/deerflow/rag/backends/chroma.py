"""ChromaDB vector store backend."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from deerflow.config.rag_config import get_rag_config
from deerflow.config.tenant import _DEFAULT_TENANT_ID, get_current_tenant_id
from deerflow.rag.vector_store import SearchResult, VectorStore

logger = logging.getLogger(__name__)


CHROMA_COSINE_METADATA: dict[str, Any] = {"hnsw:space": "cosine"}


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
        """Return the tenant-scoped collection name.

        B.4.3 guard: when the current tenant context is "default" (i.e.
        no auth middleware has run / context wasn't restored on a
        worker task) and ``rag.allow_no_auth_kb`` is False, refuse to
        return a name. The alternative is silently writing every
        tenant's vectors into the ``default_*`` collection, which is
        cross-tenant data leakage that's invisible until someone
        reads back the wrong KB.
        """
        tid = get_current_tenant_id()
        if tid == _DEFAULT_TENANT_ID and not get_rag_config().allow_no_auth_kb:
            raise RuntimeError(
                "ChromaVectorStore: refusing to resolve collection name with "
                "tenant_id='default' while rag.allow_no_auth_kb=False. This "
                "usually means a background worker (e.g. dispatcher) ran a job "
                "without restoring the submitter's tenant context — wrap the "
                "call site in deerflow.rag.job_context.with_kb_context()."
            )
        return f"{tid}_{collection}"

    def add(
        self,
        collection: str,
        chunks: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> list[str]:
        client = self._get_client()
        col_name = self._collection_name(collection)
        col = client.get_or_create_collection(
            name=col_name,
            metadata=dict(CHROMA_COSINE_METADATA),
        )

        ids = [uuid.uuid4().hex for _ in chunks]
        documents = [c["content"] for c in chunks]
        metadatas = [c.get("metadata", {}) for c in chunks]

        col.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
        logger.info("Added %d chunks to collection %r", len(ids), col_name)
        return ids

    def _resolve_metric(self, col: Any) -> str:
        """Read the collection's ``hnsw:space`` metadata.

        Why: chromadb's ``query`` returns *distances* whose meaning depends
        on the collection's configured metric (cosine / l2 / ip). We need
        to know which metric the collection actually uses to convert
        distance→similarity correctly. Defaults to ``l2`` to mirror the
        chromadb default for legacy collections that pre-date the cosine
        enforcement.
        """
        try:
            metadata = getattr(col, "metadata", None) or {}
            metric = str(metadata.get("hnsw:space") or "").strip().lower()
        except Exception:
            metric = ""
        return metric or "l2"

    @staticmethod
    def _distance_to_similarity(distance: float, metric: str) -> float:
        """Map a chromadb distance to a [0, 1] similarity score."""
        if metric == "cosine":
            # chromadb cosine distance is in [0, 2]; tighten to [0, 1].
            return max(0.0, min(1.0, 1.0 - (distance / 2.0)))
        if metric == "ip":
            # Inner-product "distance" is the negated dot product; squash
            # via a sigmoid so callers see a comparable [0, 1] score.
            try:
                from math import tanh

                return max(0.0, min(1.0, 0.5 + 0.5 * tanh(-distance)))
            except Exception:
                return 0.0
        # l2 / euclidean default — clamp into a soft similarity.
        return max(0.0, 1.0 / (1.0 + max(distance, 0.0)))

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

        metric = self._resolve_metric(col)
        results = col.query(query_embeddings=[query_embedding], n_results=top_k)

        ids_list = results.get("ids", [[]])[0]
        docs_list = results.get("documents", [[]])[0]
        metas_list = results.get("metadatas", [[]])[0]
        dists_list = results.get("distances", [[]])[0]

        search_results: list[SearchResult] = []
        for i, chunk_id in enumerate(ids_list):
            distance = dists_list[i] if i < len(dists_list) else 0.0
            score = self._distance_to_similarity(float(distance), metric)
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
