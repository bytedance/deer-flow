import logging
import re
from dataclasses import dataclass

import chromadb

from governance_kb_mcp.chunking import DocumentChunk
from governance_kb_mcp.config import KBConfig
from governance_kb_mcp.embedding import EmbeddingClient

logger = logging.getLogger(__name__)


def _sanitize_collection_name(level: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", level)
    name = name.strip("._-")
    if len(name) < 3:
        name = (name + "_kb").ljust(3, "_")
    return name


@dataclass
class SearchResult:
    content: str
    source_file: str
    line_range: str
    level: str
    score: float


@dataclass
class CollectionInfo:
    level: str
    collection_name: str
    document_count: int


class KBStore:
    def __init__(self, config: KBConfig, embedding_client: EmbeddingClient):
        self._config = config
        self._embedding = embedding_client
        self._client = chromadb.PersistentClient(path=str(config.chroma_path))

    def _get_collection(self, level: str):
        return self._client.get_or_create_collection(
            name=_sanitize_collection_name(level),
            metadata={"hnsw:space": "cosine", "level": level},
        )

    def add_documents(
        self,
        chunks: list[DocumentChunk],
        level: str,
        metadata: dict | None = None,
    ) -> list[str]:
        if not chunks:
            return []
        meta = metadata or {}
        embeddings = self._embedding.embed_batch([c.content for c in chunks])
        if embeddings:
            embeddings = embeddings[: len(chunks)]
        collection = self._get_collection(level)
        ids = [f"{level}_{i}_{hash(chunks[i].content)}" for i in range(len(chunks))]
        metadatas = [
            {
                "source_file": c.source_file,
                "line_range": c.line_range,
                "level": level,
                **meta,
            }
            for c in chunks
        ]
        collection.add(
            ids=ids,
            documents=[c.content for c in chunks],
            metadatas=metadatas,
            embeddings=embeddings if any(embeddings) else None,
        )
        return ids

    def search(self, query: str, level: str, top_k: int = 5) -> list[SearchResult]:
        query_embedding = self._embedding.embed(query)
        if not query_embedding:
            logger.warning("Empty query embedding, returning no results")
            return []
        try:
            collection = self._get_collection(level)
            if collection.count() == 0:
                return []
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, collection.count()),
            )
            search_results = []
            if results["documents"] and results["documents"][0]:
                for i, doc in enumerate(results["documents"][0]):
                    meta = results["metadatas"][0][i]
                    dist = results["distances"][0][i] if results["distances"] else 0.0
                    search_results.append(
                        SearchResult(
                            content=doc,
                            source_file=meta.get("source_file", "unknown"),
                            line_range=meta.get("line_range", ""),
                            level=meta.get("level", level),
                            score=1.0 - dist,
                        )
                    )
            return search_results
        except Exception as e:
            logger.warning("ChromaDB search error: %s", e)
            return []

    def list_collections(self) -> list[CollectionInfo]:
        collections = self._client.list_collections()
        result = []
        for col in collections:
            chroma_name = col.name if hasattr(col, "name") else col
            col_meta = col.metadata if hasattr(col, "metadata") else {}
            level = (
                col_meta.get("level", chroma_name)
                if isinstance(col_meta, dict)
                else chroma_name
            )
            count = (
                self._client.get_collection(chroma_name).count()
                if isinstance(chroma_name, str)
                else 0
            )
            result.append(
                CollectionInfo(
                    level=level,
                    collection_name=level,
                    document_count=count,
                )
            )
        return result
