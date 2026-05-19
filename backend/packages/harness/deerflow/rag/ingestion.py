"""Document ingestion pipeline for RAG."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deerflow.config.rag_config import get_rag_config
from deerflow.rag.chunking import get_chunk_strategy
from deerflow.rag.embeddings import EmbeddingProvider, get_embedding_provider
from deerflow.rag.errors import EmbeddingDimensionMismatchError
from deerflow.rag.vector_store import get_vector_store

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    """Result of a document ingestion operation."""

    collection: str
    source: str
    chunk_count: int
    chunk_ids: list[str] = field(default_factory=list)
    embedding_dim: int = 0
    chunks_per_doc: int = 0
    error: str | None = None


class DocumentIngestor:
    """Orchestrates chunk → embed → store for document ingestion.

    Pass ``embedder`` to bind ingestion to a specific KB's embedding
    model (B.3.2). Pass ``expected_dim`` to enforce dim consistency
    against an existing KB binding (B.3.3) — mismatches raise
    ``EmbeddingDimensionMismatchError`` *before* writing to the vector
    store, so partial-write inconsistency is impossible.
    """

    def __init__(
        self,
        *,
        embedder: EmbeddingProvider | None = None,
        expected_dim: int | None = None,
    ) -> None:
        config = get_rag_config()
        self._chunk_strategy = get_chunk_strategy(
            name=config.chunk_strategy,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
        )
        self._embedder = embedder if embedder is not None else get_embedding_provider()
        self._store = get_vector_store()
        self._expected_dim = expected_dim

    def ingest_text(
        self,
        text: str,
        source_name: str,
        collection: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> IngestionResult:
        """Ingest raw text into the vector store."""
        meta = {"source": source_name, **(metadata or {})}
        try:
            chunks = self._chunk_strategy.split(text, meta)
            if not chunks:
                return IngestionResult(collection=collection, source=source_name, chunk_count=0)

            contents = [{"content": c.content, "metadata": c.metadata} for c in chunks]
            embeddings = self._embedder.embed([c.content for c in chunks])
            actual_dim = len(embeddings[0]) if embeddings else 0
            if self._expected_dim and actual_dim and actual_dim != self._expected_dim:
                # Raise *before* the vector-store write so the collection
                # never accumulates a mix of dimensions.
                raise EmbeddingDimensionMismatchError(
                    expected=self._expected_dim,
                    actual=actual_dim,
                    collection=collection,
                )
            ids = self._store.add(collection=collection, chunks=contents, embeddings=embeddings)

            logger.info("Ingested %d chunks from %r into collection %r", len(ids), source_name, collection)
            return IngestionResult(
                collection=collection,
                source=source_name,
                chunk_count=len(ids),
                chunk_ids=ids,
                embedding_dim=actual_dim,
            )
        except EmbeddingDimensionMismatchError:
            # Surface the typed error to the caller — the indexing
            # service needs to mark the doc failed with a routable code.
            raise
        except Exception as e:
            logger.error("Ingestion failed for %r: %s", source_name, e)
            return IngestionResult(collection=collection, source=source_name, chunk_count=0, error=str(e))

    def ingest_file(
        self,
        file_path: str | Path,
        collection: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> IngestionResult:
        """Ingest a file into the vector store."""
        path = Path(file_path)
        if not path.exists():
            return IngestionResult(collection=collection, source=str(path), chunk_count=0, error="File not found")

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return IngestionResult(collection=collection, source=str(path), chunk_count=0, error="File is not UTF-8 text")

        return self.ingest_text(text, source_name=path.name, collection=collection, metadata=metadata)

    def ingest_directory(
        self,
        directory: str | Path,
        collection: str = "default",
        glob_pattern: str = "*.md",
        metadata: dict[str, Any] | None = None,
    ) -> list[IngestionResult]:
        """Ingest all matching files in a directory."""
        dir_path = Path(directory)
        if not dir_path.is_dir():
            return [IngestionResult(collection=collection, source=str(dir_path), chunk_count=0, error="Not a directory")]

        results: list[IngestionResult] = []
        for file_path in sorted(dir_path.glob(glob_pattern)):
            if file_path.is_file():
                results.append(self.ingest_file(file_path, collection=collection, metadata=metadata))
        return results
