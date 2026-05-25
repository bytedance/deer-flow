"""Pydantic request/response schemas for knowledge base API."""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CreateKnowledgeBaseRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    description: str | None = None
    visibility: str = Field("private", pattern=r"^(private|tenant|public)$")


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
    owner_user_id: str | None = None
    owner_display_name: str | None = None
    document_count: int
    chunk_count: int
    last_indexed_at: str | None = None
    last_search_at: str | None = None
    created_at: str
    updated_at: str
    my_role: str | None = None
    can_write: bool | None = None
    can_admin: bool | None = None


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


# ---------------------------------------------------------------------------
# Permission management models
# ---------------------------------------------------------------------------


class GrantPermissionRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    role: str = Field(..., pattern=r"^(viewer|editor|admin)$")


class PermissionResponse(BaseModel):
    id: str
    knowledge_base_id: str
    tenant_id: str
    user_id: str
    role: str
    granted_by: str
    created_at: str


# ---------------------------------------------------------------------------
# Index status (lightweight polling endpoint)
# ---------------------------------------------------------------------------


class DocumentIndexStatusResponse(BaseModel):
    id: str
    knowledge_base_id: str
    index_status: str
    index_error: str | None = None
    index_queued_at: str | None = None
    last_indexed_at: str | None = None
    chunk_count: int


# ---------------------------------------------------------------------------
# Index stats (observability)
# ---------------------------------------------------------------------------


class IndexStatsResponse(BaseModel):
    total: int
    ready: int
    pending: int
    indexing: int
    failed: int
    cancelled: int
    failure_by_type: dict[str, int] = {}
    avg_index_duration_ms: float = 0.0
    avg_retrieval_latency_ms: float = 0.0
    p95_retrieval_latency_ms: float = 0.0
    total_queries: int = 0
    recent_failures: list[dict] = []


class HealthSummaryDocuments(BaseModel):
    total: int = 0
    ready: int = 0
    pending: int = 0
    indexing: int = 0
    failed: int = 0
    cancelled: int = 0


class HealthSummaryRetrieval(BaseModel):
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    total_queries: int = 0


class HealthSummaryPerKb(BaseModel):
    kb_id: str
    kb_name: str
    total: int
    ready: int
    failed: int
    avg_retrieval_latency_ms: float
    total_queries: int


class HealthSummaryResponse(BaseModel):
    total_kbs: int
    documents: HealthSummaryDocuments
    index_success_rate: float
    failure_by_type: dict[str, int] = {}
    retrieval: HealthSummaryRetrieval
    recent_failures: list[dict] = []
    per_kb: list[HealthSummaryPerKb] = []


class KnowledgeBaseListResponse(KnowledgeBaseResponse):
    indexed_count: int = 0
    failed_count: int = 0


class KnowledgeBaseDetailResponse(KnowledgeBaseResponse):
    indexed_count: int = 0
    indexing_count: int = 0
    failed_count: int = 0
    recent_failures: list[dict] = []
