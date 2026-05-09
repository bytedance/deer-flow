"""Pydantic request/response schemas for knowledge base API."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CreateKnowledgeBaseRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    description: str | None = None


class UpdateKnowledgeBaseRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=256)
    description: str | None = None


class CreateDocumentRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    content: str = Field(..., min_length=1)
    content_format: str = "markdown"
    source_name: str | None = None
    metadata: dict | None = None


class UpdateDocumentRequest(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=512)
    content: str | None = Field(None, min_length=1)
    content_format: str | None = None
    source_name: str | None = None


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(5, ge=1, le=50)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    visibility: str
    status: str
    document_count: int
    chunk_count: int
    last_indexed_at: str | None = None
    last_search_at: str | None = None
    created_at: str
    updated_at: str


class DocumentResponse(BaseModel):
    id: str
    knowledge_base_id: str
    title: str
    content_format: str
    source_name: str | None = None
    content_length: int
    version: int
    chunk_count: int
    index_status: str
    index_error: str | None = None
    last_indexed_at: str | None = None
    created_at: str
    updated_at: str


class DocumentDetailResponse(DocumentResponse):
    content: str
    content_hash: str
    metadata_json: dict = {}


class SearchResultItem(BaseModel):
    chunk_id: str
    content: str
    score: float
    metadata: dict = {}


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    query: str
    knowledge_base_id: str
