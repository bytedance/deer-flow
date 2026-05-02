"""RAG (Retrieval-Augmented Generation) Gateway API router."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deerflow.config.rag_config import get_rag_config
from deerflow.rag.ingestion import DocumentIngestor
from deerflow.rag.retrieval import DocumentRetriever
from deerflow.rag.vector_store import get_vector_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rag", tags=["rag"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class SearchRequest(BaseModel):
    query: str
    collection: str = "default"
    top_k: int | None = None
    score_threshold: float | None = None


class SearchResultModel(BaseModel):
    rank: int
    content: str
    score: float
    source: str


class SearchResponse(BaseModel):
    query: str
    collection: str
    results: list[SearchResultModel]


class IngestTextRequest(BaseModel):
    text: str
    source_name: str
    collection: str = "default"
    metadata: dict[str, Any] | None = None


class IngestResponse(BaseModel):
    collection: str
    source: str
    chunk_count: int
    chunk_ids: list[str]
    error: str | None = None


class DeleteRequest(BaseModel):
    collection: str
    chunk_ids: list[str]


class StatusResponse(BaseModel):
    enabled: bool
    backend: str
    embedding_model: str
    collections: list[str]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/status", response_model=StatusResponse)
def get_rag_status() -> StatusResponse:
    """Return the current RAG subsystem status."""
    config = get_rag_config()
    collections: list[str] = []
    if config.enabled:
        try:
            store = get_vector_store()
            collections = store.list_collections()
        except Exception as e:
            logger.warning("Could not list collections: %s", e)

    return StatusResponse(
        enabled=config.enabled,
        backend=config.vector_store_backend,
        embedding_model=config.embedding_model,
        collections=collections,
    )


@router.post("/search", response_model=SearchResponse)
def search_knowledge_base(req: SearchRequest) -> SearchResponse:
    """Search the knowledge base for relevant chunks."""
    config = get_rag_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="RAG subsystem is not enabled")

    retriever = DocumentRetriever()
    result = retriever.retrieve(
        query=req.query,
        collection=req.collection,
        top_k=req.top_k,
        score_threshold=req.score_threshold,
    )

    formatted = [
        SearchResultModel(
            rank=i + 1,
            content=r.content,
            score=round(r.score, 4),
            source=r.metadata.get("source", "unknown"),
        )
        for i, r in enumerate(result.results)
    ]

    return SearchResponse(query=req.query, collection=req.collection, results=formatted)


@router.post("/ingest", response_model=IngestResponse)
def ingest_document(req: IngestTextRequest) -> IngestResponse:
    """Ingest a text document into the knowledge base."""
    config = get_rag_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="RAG subsystem is not enabled")

    ingestor = DocumentIngestor()
    result = ingestor.ingest_text(
        text=req.text,
        source_name=req.source_name,
        collection=req.collection,
        metadata=req.metadata,
    )

    return IngestResponse(
        collection=result.collection,
        source=result.source,
        chunk_count=result.chunk_count,
        chunk_ids=result.chunk_ids,
        error=result.error,
    )


@router.get("/collections")
def list_collections() -> list[str]:
    """List all knowledge base collections for the current tenant."""
    config = get_rag_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="RAG subsystem is not enabled")

    store = get_vector_store()
    return store.list_collections()


@router.delete("/collections/{name}")
def delete_collection(name: str) -> dict[str, Any]:
    """Delete an entire knowledge base collection."""
    config = get_rag_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="RAG subsystem is not enabled")

    store = get_vector_store()
    ok = store.delete_collection(name)
    return {"success": ok, "collection": name}


@router.delete("/documents")
def delete_documents(req: DeleteRequest) -> dict[str, Any]:
    """Delete specific documents from a collection."""
    config = get_rag_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="RAG subsystem is not enabled")

    store = get_vector_store()
    count = store.delete(req.collection, req.chunk_ids)
    return {"success": True, "deleted": count}
