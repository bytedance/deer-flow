"""Vector store abstraction and factory."""

import abc
import logging
from dataclasses import dataclass, field
from typing import Any

from deerflow.config.rag_config import get_rag_config

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result from the vector store."""

    chunk_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0


class VectorStore(abc.ABC):
    """Abstract base class for vector store backends."""

    @abc.abstractmethod
    def add(
        self,
        collection: str,
        chunks: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> list[str]:
        """Add chunks with embeddings to a collection. Returns chunk IDs."""

    @abc.abstractmethod
    def search(
        self,
        collection: str,
        query_embedding: list[float],
        top_k: int = 5,
        score_threshold: float = 0.0,
    ) -> list[SearchResult]:
        """Search a collection with a query embedding."""

    @abc.abstractmethod
    def delete(self, collection: str, chunk_ids: list[str]) -> int:
        """Delete chunks by ID. Returns count of deleted items."""

    @abc.abstractmethod
    def list_collections(self) -> list[str]:
        """List all collection names."""

    @abc.abstractmethod
    def delete_collection(self, collection: str) -> bool:
        """Delete an entire collection."""

    @abc.abstractmethod
    def count(self, collection: str) -> int:
        """Return the number of chunks in a collection."""


def get_vector_store() -> VectorStore:
    """Create a vector store from the current RAG configuration."""
    config = get_rag_config()
    backend = config.vector_store_backend

    if backend == "chroma":
        from deerflow.rag.backends.chroma import ChromaVectorStore

        return ChromaVectorStore(persist_dir=config.chroma_persist_dir)

    if backend == "pgvector":
        from deerflow.rag.backends.pgvector import PgvectorVectorStore

        return PgvectorVectorStore(connection_string=config.pgvector_connection_string)

    raise ValueError(f"Unknown vector store backend: {backend!r}. Supported: 'chroma', 'pgvector'.")
