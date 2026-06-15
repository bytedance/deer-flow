"""Memory API router for retrieving and managing memory data across User, Session, and Domain layers."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from deerflow.agents.memory.domain_storage import get_domain_storage
from deerflow.agents.memory.session_storage import get_session_storage
from deerflow.agents.memory.updater import (
    aclear_memory_data,
    acreate_memory_fact,
    adelete_memory_fact,
    aget_memory_data,
    aimport_memory_data,
    areload_memory_data,
    aupdate_memory_fact,
)
from deerflow.config.domain_memory_config import get_domain_memory_config
from deerflow.config.memory_api_config import get_memory_api_config
from deerflow.config.memory_config import get_memory_config
from deerflow.config.session_memory_config import get_session_memory_config
from deerflow.config.tenant import get_current_tenant_id
from deerflow.persistence.memory_audit import log_memory_audit
from deerflow.runtime.user_context import get_effective_user_id


def _check_memory_enabled() -> None:
    """FastAPI dependency that raises 503 if the memory API is disabled."""
    if not get_memory_api_config().enabled:
        raise HTTPException(status_code=503, detail="Memory API is disabled")


router = APIRouter(prefix="/api", tags=["memory"], dependencies=[Depends(_check_memory_enabled)])


class ContextSection(BaseModel):
    """Model for context sections (user and history)."""

    summary: str = Field(default="", description="Summary content")
    updatedAt: str = Field(default="", description="Last update timestamp")


class UserContext(BaseModel):
    """Model for user context."""

    workContext: ContextSection = Field(default_factory=ContextSection)
    personalContext: ContextSection = Field(default_factory=ContextSection)
    topOfMind: ContextSection = Field(default_factory=ContextSection)


class HistoryContext(BaseModel):
    """Model for history context."""

    recentMonths: ContextSection = Field(default_factory=ContextSection)
    earlierContext: ContextSection = Field(default_factory=ContextSection)
    longTermBackground: ContextSection = Field(default_factory=ContextSection)


class Fact(BaseModel):
    """Model for a memory fact."""

    id: str = Field(..., description="Unique identifier for the fact")
    content: str = Field(..., description="Fact content")
    category: str = Field(default="context", description="Fact category")
    confidence: float = Field(default=0.5, description="Confidence score (0-1)")
    createdAt: str = Field(default="", description="Creation timestamp")
    source: str = Field(default="unknown", description="Source thread ID")
    sourceError: str | None = Field(default=None, description="Optional description of the prior mistake or wrong approach")


class MemoryResponse(BaseModel):
    """Response model for memory data."""

    version: str = Field(default="1.0", description="Memory schema version")
    lastUpdated: str = Field(default="", description="Last update timestamp")
    user: UserContext = Field(default_factory=UserContext)
    history: HistoryContext = Field(default_factory=HistoryContext)
    facts: list[Fact] = Field(default_factory=list)


def _map_memory_fact_value_error(exc: ValueError) -> HTTPException:
    """Convert updater validation errors into stable API responses."""
    if exc.args and exc.args[0] == "confidence":
        detail = "Invalid confidence value; must be between 0 and 1."
    else:
        detail = "Memory fact content cannot be empty."
    return HTTPException(status_code=400, detail=detail)


class FactCreateRequest(BaseModel):
    """Request model for creating a memory fact."""

    content: str = Field(..., min_length=1, description="Fact content")
    category: str = Field(default="context", description="Fact category")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Confidence score (0-1)")


class FactPatchRequest(BaseModel):
    """PATCH request model that preserves existing values for omitted fields."""

    content: str | None = Field(default=None, min_length=1, description="Fact content")
    category: str | None = Field(default=None, description="Fact category")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0, description="Confidence score (0-1)")


class MemoryConfigResponse(BaseModel):
    """Response model for memory configuration."""

    enabled: bool = Field(..., description="Whether memory is enabled")
    storage_path: str = Field(..., description="Path to memory storage file")
    debounce_seconds: int = Field(..., description="Debounce time for memory updates")
    max_facts: int = Field(..., description="Maximum number of facts to store")
    fact_confidence_threshold: float = Field(..., description="Minimum confidence threshold for facts")
    injection_enabled: bool = Field(..., description="Whether memory injection is enabled")
    max_injection_tokens: int = Field(..., description="Maximum tokens for memory injection")


class MemoryStatusResponse(BaseModel):
    """Response model for memory status."""

    config: MemoryConfigResponse
    data: MemoryResponse


@router.get(
    "/memory",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Get Memory Data",
    description="Retrieve the current global memory data including user context, history, and facts.",
)
async def get_memory() -> MemoryResponse:
    """Get the current global memory data.

    Returns:
        The current memory data with user context, history, and facts.

    Example Response:
        ```json
        {
            "version": "1.0",
            "lastUpdated": "2024-01-15T10:30:00Z",
            "user": {
                "workContext": {"summary": "Working on DeerFlow project", "updatedAt": "..."},
                "personalContext": {"summary": "Prefers concise responses", "updatedAt": "..."},
                "topOfMind": {"summary": "Building memory API", "updatedAt": "..."}
            },
            "history": {
                "recentMonths": {"summary": "Recent development activities", "updatedAt": "..."},
                "earlierContext": {"summary": "", "updatedAt": ""},
                "longTermBackground": {"summary": "", "updatedAt": ""}
            },
            "facts": [
                {
                    "id": "fact_abc123",
                    "content": "User prefers TypeScript over JavaScript",
                    "category": "preference",
                    "confidence": 0.9,
                    "createdAt": "2024-01-15T10:30:00Z",
                    "source": "thread_xyz"
                }
            ]
        }
        ```
    """
    memory_data = await aget_memory_data(user_id=get_effective_user_id())
    return MemoryResponse(**memory_data)


@router.post(
    "/memory/reload",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Reload Memory Data",
    description="Reload memory data from the storage file, refreshing the in-memory cache.",
)
async def reload_memory() -> MemoryResponse:
    """Reload memory data from file.

    This forces a reload of the memory data from the storage file,
    useful when the file has been modified externally.

    Returns:
        The reloaded memory data.
    """
    memory_data = await areload_memory_data(user_id=get_effective_user_id())
    return MemoryResponse(**memory_data)


@router.delete(
    "/memory",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Clear All Memory Data",
    description="Delete all saved memory data and reset the memory structure to an empty state.",
)
async def clear_memory() -> MemoryResponse:
    """Clear all persisted memory data."""
    try:
        memory_data = await aclear_memory_data(user_id=get_effective_user_id())
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to clear memory data.") from exc

    await emit_memory_update(layer="user", action="clear", fact_id="*")
    return MemoryResponse(**memory_data)


@router.post(
    "/memory/facts",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Create Memory Fact",
    description="Create a single saved memory fact manually.",
)
async def create_memory_fact_endpoint(request: FactCreateRequest) -> MemoryResponse:
    """Create a single fact manually."""
    try:
        memory_data = await acreate_memory_fact(
            content=request.content,
            category=request.category,
            confidence=request.confidence,
            user_id=get_effective_user_id(),
        )
    except ValueError as exc:
        raise _map_memory_fact_value_error(exc) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to create memory fact.") from exc

    await emit_memory_update(layer="user", action="create", fact_id="latest")
    return MemoryResponse(**memory_data)


@router.delete(
    "/memory/facts/{fact_id}",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Delete Memory Fact",
    description="Delete a single saved memory fact by its fact id.",
)
async def delete_memory_fact_endpoint(fact_id: str) -> MemoryResponse:
    """Delete a single fact from memory by fact id."""
    try:
        memory_data = await adelete_memory_fact(fact_id, user_id=get_effective_user_id())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Memory fact '{fact_id}' not found.") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to delete memory fact.") from exc

    await emit_memory_update(layer="user", action="delete", fact_id=fact_id)
    return MemoryResponse(**memory_data)


@router.patch(
    "/memory/facts/{fact_id}",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Patch Memory Fact",
    description="Partially update a single saved memory fact by its fact id while preserving omitted fields.",
)
async def update_memory_fact_endpoint(fact_id: str, request: FactPatchRequest) -> MemoryResponse:
    """Partially update a single fact manually."""
    try:
        memory_data = await aupdate_memory_fact(
            fact_id=fact_id,
            content=request.content,
            category=request.category,
            confidence=request.confidence,
            user_id=get_effective_user_id(),
        )
    except ValueError as exc:
        raise _map_memory_fact_value_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Memory fact '{fact_id}' not found.") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to update memory fact.") from exc

    await emit_memory_update(layer="user", action="update", fact_id=fact_id)
    return MemoryResponse(**memory_data)


@router.get(
    "/memory/facts/{fact_id}",
    response_model=Fact,
    response_model_exclude_none=True,
    summary="Get Memory Fact",
    description="Retrieve a single memory fact by its fact id.",
)
async def get_memory_fact_endpoint(fact_id: str) -> Fact:
    """Get a single fact from memory by fact id."""
    memory_data = await aget_memory_data(user_id=get_effective_user_id())
    facts = memory_data.get("facts", [])

    for fact in facts:
        if fact.get("id") == fact_id:
            return Fact(**fact)

    raise HTTPException(status_code=404, detail=f"Memory fact '{fact_id}' not found.")


@router.get(
    "/memory/export",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Export Memory Data",
    description="Export the current global memory data as JSON for backup or transfer.",
)
async def export_memory() -> MemoryResponse:
    """Export the current memory data."""
    memory_data = await aget_memory_data(user_id=get_effective_user_id())
    return MemoryResponse(**memory_data)


@router.post(
    "/memory/import",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Import Memory Data",
    description="Import and overwrite the current global memory data from a JSON payload.",
)
async def import_memory(request: MemoryResponse) -> MemoryResponse:
    """Import and persist memory data."""
    try:
        memory_data = await aimport_memory_data(request.model_dump(), user_id=get_effective_user_id())
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to import memory data.") from exc

    await emit_memory_update(layer="user", action="import", fact_id="batch")
    return MemoryResponse(**memory_data)


@router.get(
    "/memory/config",
    response_model=MemoryConfigResponse,
    summary="Get Memory Configuration",
    description="Retrieve the current memory system configuration.",
)
async def get_memory_config_endpoint() -> MemoryConfigResponse:
    """Get the memory system configuration.

    Returns:
        The current memory configuration settings.

    Example Response:
        ```json
        {
            "enabled": true,
            "storage_path": ".deer-flow/memory.json",
            "debounce_seconds": 30,
            "max_facts": 100,
            "fact_confidence_threshold": 0.7,
            "injection_enabled": true,
            "max_injection_tokens": 2000
        }
        ```
    """
    config = get_memory_config()
    return MemoryConfigResponse(
        enabled=config.enabled,
        storage_path=config.storage_path,
        debounce_seconds=config.debounce_seconds,
        max_facts=config.max_facts,
        fact_confidence_threshold=config.fact_confidence_threshold,
        injection_enabled=config.injection_enabled,
        max_injection_tokens=config.max_injection_tokens,
    )


@router.get(
    "/memory/status",
    response_model=MemoryStatusResponse,
    response_model_exclude_none=True,
    summary="Get Memory Status",
    description="Retrieve both memory configuration and current data in a single request.",
)
async def get_memory_status() -> MemoryStatusResponse:
    """Get the memory system status including configuration and data.

    Returns:
        Combined memory configuration and current data.
    """
    config = get_memory_config()
    memory_data = await aget_memory_data(user_id=get_effective_user_id())

    return MemoryStatusResponse(
        config=MemoryConfigResponse(
            enabled=config.enabled,
            storage_path=config.storage_path,
            debounce_seconds=config.debounce_seconds,
            max_facts=config.max_facts,
            fact_confidence_threshold=config.fact_confidence_threshold,
            injection_enabled=config.injection_enabled,
            max_injection_tokens=config.max_injection_tokens,
        ),
        data=MemoryResponse(**memory_data),
    )


# ============================================================================
# Session Memory Endpoints
# ============================================================================


class SessionFactResponse(BaseModel):
    """Response model for a session memory fact."""

    id: str = Field(..., description="Fact ID")
    content: str = Field(..., description="Fact content")
    category: str = Field(default="context", description="Fact category")
    confidence: float = Field(default=0.5, description="Confidence score")
    created_at: str = Field(default="", description="Creation timestamp")
    source_error: str | None = Field(default=None, description="Source error if correction")


class SessionMemoryResponse(BaseModel):
    """Response model for session memory."""

    thread_id: str = Field(..., description="Thread ID")
    facts: list[SessionFactResponse] = Field(default_factory=list)
    session_context: dict[str, Any] = Field(default_factory=dict)


@router.get(
    "/memory/session",
    response_model=SessionMemoryResponse,
    summary="Get Session Memory",
    description="Retrieve session memory facts for a specific thread.",
)
async def get_session_memory_endpoint(
    thread_id: str = Query(..., description="Thread ID"),
) -> SessionMemoryResponse:
    """Get session memory for a thread."""
    config = get_session_memory_config()
    if not config.enabled:
        raise HTTPException(status_code=404, detail="Session memory is disabled")

    storage = get_session_storage()
    if storage is None:
        raise HTTPException(status_code=500, detail="Session storage unavailable")

    user_id = get_effective_user_id()
    data = await storage.aload(thread_id, user_id=user_id)

    facts = []
    for fact in data.get("facts", []):
        facts.append(
            SessionFactResponse(
                id=fact.get("id", ""),
                content=fact.get("content", ""),
                category=fact.get("category", "context"),
                confidence=fact.get("confidence", 0.5),
                created_at=fact.get("createdAt", ""),
                source_error=fact.get("sourceError"),
            )
        )

    return SessionMemoryResponse(
        thread_id=thread_id,
        facts=facts,
        session_context=data.get("session_context", {}),
    )


@router.get(
    "/memory/session/export",
    response_model=SessionMemoryResponse,
    summary="Export Session Memory",
    description="Export session memory for a thread as JSON.",
)
async def export_session_memory_endpoint(
    thread_id: str = Query(..., description="Thread ID"),
) -> SessionMemoryResponse:
    """Export session memory for a thread."""
    return await get_session_memory_endpoint(thread_id=thread_id)


class SessionImportRequest(BaseModel):
    """Request model for importing session memory."""

    thread_id: str = Field(..., description="Thread ID")
    facts: list[SessionFactResponse] = Field(default_factory=list)


@router.post(
    "/memory/session/import",
    response_model=SessionMemoryResponse,
    summary="Import Session Memory",
    description="Import session memory facts for a thread.",
)
async def import_session_memory_endpoint(
    request: SessionImportRequest,
) -> SessionMemoryResponse:
    """Import session memory for a thread."""
    config = get_session_memory_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Session memory is disabled")

    storage = get_session_storage()
    if storage is None:
        raise HTTPException(status_code=500, detail="Session storage unavailable")

    user_id = get_effective_user_id()
    tenant_id = get_current_tenant_id()

    data = {
        "facts": [
            {
                "id": f.id,
                "content": f.content,
                "category": f.category,
                "confidence": f.confidence,
                "createdAt": f.created_at,
                "sourceError": f.source_error,
            }
            for f in request.facts
        ],
        "session_context": {},
    }
    await storage.asave(data, request.thread_id, user_id=user_id)

    await log_memory_audit(
        tenant_id=tenant_id,
        user_id=user_id,
        action="import",
        layer="session",
        fact_id=request.thread_id,
        after={"count": len(request.facts)},
    )
    await emit_memory_update(layer="session", action="import", fact_id=request.thread_id, thread_id=request.thread_id)

    return await get_session_memory_endpoint(thread_id=request.thread_id)


# ============================================================================
# Domain Memory Endpoints
# ============================================================================


class DomainFactResponse(BaseModel):
    """Response model for a domain memory fact."""

    id: str = Field(..., description="Fact ID")
    content: str = Field(..., description="Fact content")
    domain: str = Field(..., description="Domain category")
    entity_id: str = Field(..., description="Entity identifier")
    confidence: float = Field(default=1.0, description="Confidence score")
    created_at: str = Field(default="", description="Creation timestamp")
    similarity_score: float = Field(default=0.0, description="Similarity score from search")
    adjusted_score: float = Field(default=0.0, description="Score after decay")


class DomainFactCreateRequest(BaseModel):
    """Request model for creating a domain fact."""

    content: str = Field(..., min_length=1, max_length=1000, description="Fact content")
    domain: str = Field(..., min_length=1, description="Domain category (e.g., equipment)")
    entity_id: str = Field(..., min_length=1, description="Entity identifier")
    confidence: float = Field(default=0.9, ge=0.0, le=1.0, description="Confidence score")


class DomainFactUpdateRequest(BaseModel):
    """Request model for updating a domain fact."""

    content: str | None = Field(default=None, min_length=1, max_length=1000)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


@router.get(
    "/memory/domain",
    response_model=list[DomainFactResponse],
    summary="Search Domain Memory",
    description="Search domain memory facts by query with optional domain/entity filters.",
)
async def search_domain_memory_endpoint(
    query: str = Query(..., min_length=1, description="Search query"),
    domain: str | None = Query(default=None, description="Domain filter"),
    entity_id: str | None = Query(default=None, description="Entity filter"),
    top_k: int = Query(default=20, ge=1, le=100, description="Max results"),
) -> list[DomainFactResponse]:
    """Search domain memory facts."""
    config = get_domain_memory_config()
    if not config.enabled:
        return []

    storage = get_domain_storage()
    if storage is None:
        raise HTTPException(status_code=500, detail="Domain storage unavailable")

    tenant_id = get_current_tenant_id()
    facts = storage.search_facts(
        tenant_id=tenant_id,
        query=query,
        domain=domain,
        entity_id=entity_id,
        top_k=top_k,
        min_score=config.min_retrieval_score,
    )

    return [
        DomainFactResponse(
            id=f.id,
            content=f.content,
            domain=f.domain,
            entity_id=f.entity_id,
            confidence=f.confidence,
            created_at=f.created_at.isoformat() if f.created_at else "",
            similarity_score=f.similarity_score,
            adjusted_score=f.adjusted_score,
        )
        for f in facts
    ]


@router.post(
    "/memory/domain/facts",
    response_model=DomainFactResponse,
    status_code=201,
    summary="Create Domain Fact",
    description="Create a new domain memory fact.",
)
async def create_domain_fact_endpoint(
    request: DomainFactCreateRequest,
) -> DomainFactResponse:
    """Create a domain memory fact."""
    config = get_domain_memory_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Domain memory is disabled")

    storage = get_domain_storage()
    if storage is None:
        raise HTTPException(status_code=500, detail="Domain storage unavailable")

    tenant_id = get_current_tenant_id()
    user_id = get_effective_user_id()

    fact_id = storage.store_fact(
        tenant_id=tenant_id,
        domain=request.domain,
        entity_id=request.entity_id,
        content=request.content,
        confidence=request.confidence,
    )

    if fact_id is None:
        raise HTTPException(status_code=500, detail="Failed to store domain fact")

    await log_memory_audit(
        tenant_id=tenant_id,
        user_id=user_id,
        action="create",
        layer="domain",
        fact_id=fact_id,
        after=request.model_dump(),
    )
    await emit_memory_update(layer="domain", action="create", fact_id=fact_id)

    return DomainFactResponse(
        id=fact_id,
        content=request.content,
        domain=request.domain,
        entity_id=request.entity_id,
        confidence=request.confidence,
        created_at=datetime.now().isoformat(),
    )


@router.put(
    "/memory/domain/facts/{fact_id}",
    response_model=DomainFactResponse,
    summary="Update Domain Fact",
    description="Update an existing domain memory fact.",
)
async def update_domain_fact_endpoint(
    fact_id: str,
    request: DomainFactUpdateRequest,
) -> DomainFactResponse:
    """Update a domain memory fact.

    Note: Vector store update requires delete + re-insert.
    This is a simplified implementation that logs the intent.
    Full implementation requires vector store update support.
    """
    config = get_domain_memory_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Domain memory is disabled")

    tenant_id = get_current_tenant_id()
    user_id = get_effective_user_id()

    await log_memory_audit(
        tenant_id=tenant_id,
        user_id=user_id,
        action="update",
        layer="domain",
        fact_id=fact_id,
        before=None,
        after=request.model_dump(exclude_none=True),
    )

    raise HTTPException(
        status_code=501,
        detail="Domain fact update requires vector store update support (not yet implemented)",
    )


@router.delete(
    "/memory/domain/facts/{fact_id}",
    status_code=204,
    summary="Delete Domain Fact",
    description="Delete a domain memory fact.",
)
async def delete_domain_fact_endpoint(fact_id: str) -> None:
    """Delete a domain memory fact.

    Note: Vector store delete requires collection-level support.
    This is a simplified implementation that logs the intent.
    """
    config = get_domain_memory_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Domain memory is disabled")

    tenant_id = get_current_tenant_id()
    user_id = get_effective_user_id()

    await log_memory_audit(
        tenant_id=tenant_id,
        user_id=user_id,
        action="delete",
        layer="domain",
        fact_id=fact_id,
        before=None,
        after=None,
    )

    raise HTTPException(
        status_code=501,
        detail="Domain fact delete requires vector store delete support (not yet implemented)",
    )


@router.get(
    "/memory/domain/export",
    response_model=list[DomainFactResponse],
    summary="Export Domain Memory",
    description="Export all domain memory facts as JSON.",
)
async def export_domain_memory_endpoint(
    domain: str | None = Query(default=None, description="Domain filter"),
    entity_id: str | None = Query(default=None, description="Entity filter"),
) -> list[DomainFactResponse]:
    """Export domain memory facts."""
    return await search_domain_memory_endpoint(
        query="*",
        domain=domain,
        entity_id=entity_id,
        top_k=100,
    )


class DomainImportRequest(BaseModel):
    """Request model for importing domain facts."""

    facts: list[DomainFactCreateRequest] = Field(default_factory=list)


@router.post(
    "/memory/domain/import",
    summary="Import Domain Memory",
    description="Import domain memory facts from JSON.",
)
async def import_domain_memory_endpoint(
    request: DomainImportRequest,
) -> dict[str, int]:
    """Import domain memory facts."""
    config = get_domain_memory_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Domain memory is disabled")

    storage = get_domain_storage()
    if storage is None:
        raise HTTPException(status_code=500, detail="Domain storage unavailable")

    tenant_id = get_current_tenant_id()
    user_id = get_effective_user_id()

    imported = 0
    for fact in request.facts:
        fact_id = storage.store_fact(
            tenant_id=tenant_id,
            domain=fact.domain,
            entity_id=fact.entity_id,
            content=fact.content,
            confidence=fact.confidence,
        )
        if fact_id:
            imported += 1

    await log_memory_audit(
        tenant_id=tenant_id,
        user_id=user_id,
        action="import",
        layer="domain",
        fact_id="batch",
        after={"count": imported},
    )
    await emit_memory_update(layer="domain", action="import", fact_id="batch")

    return {"imported": imported, "total": len(request.facts)}


# ============================================================================
# Audit Log Endpoint
# ============================================================================


class AuditEntryResponse(BaseModel):
    """Response model for an audit log entry."""

    id: int
    tenant_id: str
    user_id: str
    action: str
    layer: str
    fact_id: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    created_at: str


@router.get(
    "/memory/audit",
    response_model=list[AuditEntryResponse],
    summary="Query Audit Logs",
    description="Query memory audit logs with optional filters (admin only).",
)
async def get_audit_logs_endpoint(
    user_id: str | None = Query(default=None, description="Filter by user ID"),
    action: str | None = Query(default=None, description="Filter by action"),
    layer: str | None = Query(default=None, description="Filter by layer"),
    limit: int = Query(default=100, ge=1, le=1000, description="Max entries"),
) -> list[AuditEntryResponse]:
    """Query memory audit logs."""
    from sqlalchemy import select

    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.models.memory_audit import MemoryAuditRow

    session_factory = get_session_factory()
    if session_factory is None:
        raise HTTPException(status_code=500, detail="Persistence unavailable")

    tenant_id = get_current_tenant_id()

    async with session_factory() as session:
        stmt = select(MemoryAuditRow).where(MemoryAuditRow.tenant_id == tenant_id)
        if user_id:
            stmt = stmt.where(MemoryAuditRow.user_id == user_id)
        if action:
            stmt = stmt.where(MemoryAuditRow.action == action)
        if layer:
            stmt = stmt.where(MemoryAuditRow.layer == layer)
        stmt = stmt.order_by(MemoryAuditRow.created_at.desc()).limit(limit)

        result = await session.execute(stmt)
        rows = result.scalars().all()

    return [
        AuditEntryResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            action=row.action,
            layer=row.layer,
            fact_id=row.fact_id,
            before=row.before,
            after=row.after,
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]


# ============================================================================
# SSE Event Streaming
# ============================================================================


async def emit_memory_update(
    layer: str,
    action: str,
    fact_id: str,
    user_id: str | None = None,
    thread_id: str | None = None,
) -> None:
    """Emit SSE event for memory updates via the in-process event bus."""
    from deerflow.memory_events import get_memory_event_bus

    tenant_id = get_current_tenant_id()
    bus = get_memory_event_bus()
    await bus.publish(
        tenant_id=tenant_id,
        event_type="memory_updated",
        data={
            "layer": layer,
            "action": action,
            "fact_id": fact_id,
            "user_id": user_id,
            "thread_id": thread_id,
        },
    )


@router.get(
    "/memory/events",
    summary="Memory Update Events (SSE)",
    description="Server-Sent Events stream for real-time memory updates.",
)
async def memory_events_stream():
    """SSE endpoint for real-time memory update events."""
    from fastapi.responses import StreamingResponse

    from deerflow.memory_events import get_memory_event_bus

    tenant_id = get_current_tenant_id()
    bus = get_memory_event_bus()
    return StreamingResponse(
        bus.stream(tenant_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
