"""Memory API router for retrieving and managing global memory data."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.agents.memory.updater import get_memory_data, reload_memory_data, save_memory_data
from src.config.memory_config import get_memory_config

router = APIRouter(prefix="/api", tags=["memory"])


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


class MemoryResponse(BaseModel):
    """Response model for memory data."""

    version: str = Field(default="1.0", description="Memory schema version")
    lastUpdated: str = Field(default="", description="Last update timestamp")
    user: UserContext = Field(default_factory=UserContext)
    history: HistoryContext = Field(default_factory=HistoryContext)
    facts: list[Fact] = Field(default_factory=list)


class MemoryConfigResponse(BaseModel):
    """Response model for memory configuration."""

    enabled: bool = Field(..., description="Whether memory is enabled")
    backend: str = Field(..., description="Configured memory backend: 'file' or 'postgres'")
    storage_path: str = Field(..., description="Path to memory storage file")
    database_configured: bool = Field(..., description="Whether a database URL is configured for the selected backend")
    strict_scope: bool = Field(..., description="Whether workspace_type/workspace_id are required for memory operations")
    auth_mode: str = Field(..., description="Scope trust mode used by the memory subsystem")
    debounce_seconds: int = Field(..., description="Debounce time for memory updates")
    max_facts: int = Field(..., description="Maximum number of facts to store")
    fact_confidence_threshold: float = Field(..., description="Minimum confidence threshold for facts")
    injection_enabled: bool = Field(..., description="Whether memory injection is enabled")
    max_injection_tokens: int = Field(..., description="Maximum tokens for memory injection")


class MemoryStatusResponse(BaseModel):
    """Response model for memory status."""

    config: MemoryConfigResponse
    data: MemoryResponse


class FactCreateRequest(BaseModel):
    """Request model for creating a memory fact."""

    content: str = Field(..., min_length=1, description="Fact content")
    category: str = Field(default="context", description="Fact category")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Confidence score (0-1)")
    source: str = Field(default="api", description="Fact source")


class FactUpdateRequest(BaseModel):
    """Request model for updating a memory fact."""

    content: str | None = Field(default=None, min_length=1, description="Fact content")
    category: str | None = Field(default=None, description="Fact category")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0, description="Confidence score (0-1)")
    source: str | None = Field(default=None, description="Fact source")


def _normalize_scope(workspace_type: str | None, workspace_id: str | None) -> tuple[str | None, str | None]:
    wt = workspace_type.strip() if isinstance(workspace_type, str) and workspace_type.strip() else None
    wid = workspace_id.strip() if isinstance(workspace_id, str) and workspace_id.strip() else None
    return wt, wid


def _load_memory_with_scope(workspace_type: str | None, workspace_id: str | None) -> dict:
    wt, wid = _normalize_scope(workspace_type, workspace_id)
    try:
        return get_memory_data(workspace_type=wt, workspace_id=wid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _save_memory_with_scope(memory_data: dict, workspace_type: str | None, workspace_id: str | None) -> None:
    wt, wid = _normalize_scope(workspace_type, workspace_id)
    try:
        ok = save_memory_data(memory_data, workspace_type=wt, workspace_id=wid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not ok:
        raise HTTPException(status_code=500, detail="Failed to persist memory data")


def _enforce_max_facts(memory_data: dict) -> None:
    config = get_memory_config()
    facts = memory_data.get("facts", [])
    if len(facts) <= config.max_facts:
        return
    memory_data["facts"] = sorted(facts, key=lambda f: f.get("confidence", 0), reverse=True)[: config.max_facts]


@router.get(
    "/memory",
    response_model=MemoryResponse,
    summary="Get Memory Data",
    description="Retrieve the current global memory data including user context, history, and facts.",
)
async def get_memory(
    workspace_type: str | None = Query(default=None, description="Workspace type scope key"),
    workspace_id: str | None = Query(default=None, description="Workspace ID scope key"),
) -> MemoryResponse:
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
    memory_data = _load_memory_with_scope(workspace_type, workspace_id)
    return MemoryResponse(**memory_data)


@router.post(
    "/memory/reload",
    response_model=MemoryResponse,
    summary="Reload Memory Data",
    description="Reload memory data from the storage file, refreshing the in-memory cache.",
)
async def reload_memory(
    workspace_type: str | None = Query(default=None, description="Workspace type scope key"),
    workspace_id: str | None = Query(default=None, description="Workspace ID scope key"),
) -> MemoryResponse:
    """Reload memory data from file.

    This forces a reload of the memory data from the storage file,
    useful when the file has been modified externally.

    Returns:
        The reloaded memory data.
    """
    wt, wid = _normalize_scope(workspace_type, workspace_id)
    try:
        memory_data = reload_memory_data(workspace_type=wt, workspace_id=wid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return MemoryResponse(**memory_data)


@router.put(
    "/memory",
    response_model=MemoryResponse,
    summary="Replace Memory Data",
    description="Replace the full memory document for the selected scope.",
)
async def put_memory(
    payload: MemoryResponse,
    workspace_type: str | None = Query(default=None, description="Workspace type scope key"),
    workspace_id: str | None = Query(default=None, description="Workspace ID scope key"),
) -> MemoryResponse:
    memory_data = payload.model_dump()
    _enforce_max_facts(memory_data)
    _save_memory_with_scope(memory_data, workspace_type, workspace_id)
    return MemoryResponse(**_load_memory_with_scope(workspace_type, workspace_id))


@router.post(
    "/memory/facts",
    response_model=MemoryResponse,
    summary="Create Memory Fact",
    description="Create a new memory fact in the selected scope.",
)
async def create_memory_fact(
    payload: FactCreateRequest,
    workspace_type: str | None = Query(default=None, description="Workspace type scope key"),
    workspace_id: str | None = Query(default=None, description="Workspace ID scope key"),
) -> MemoryResponse:
    memory_data = _load_memory_with_scope(workspace_type, workspace_id)
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    memory_data.setdefault("facts", []).append(
        {
            "id": f"fact_{uuid.uuid4().hex[:8]}",
            "content": payload.content,
            "category": payload.category,
            "confidence": payload.confidence,
            "createdAt": now,
            "source": payload.source,
        }
    )
    _enforce_max_facts(memory_data)
    _save_memory_with_scope(memory_data, workspace_type, workspace_id)
    return MemoryResponse(**_load_memory_with_scope(workspace_type, workspace_id))


@router.put(
    "/memory/facts/{fact_id}",
    response_model=MemoryResponse,
    summary="Update Memory Fact",
    description="Update an existing memory fact by ID in the selected scope.",
)
async def update_memory_fact(
    fact_id: str,
    payload: FactUpdateRequest,
    workspace_type: str | None = Query(default=None, description="Workspace type scope key"),
    workspace_id: str | None = Query(default=None, description="Workspace ID scope key"),
) -> MemoryResponse:
    memory_data = _load_memory_with_scope(workspace_type, workspace_id)
    facts = memory_data.get("facts", [])

    updated = False
    for fact in facts:
        if fact.get("id") != fact_id:
            continue
        if payload.content is not None:
            fact["content"] = payload.content
        if payload.category is not None:
            fact["category"] = payload.category
        if payload.confidence is not None:
            fact["confidence"] = payload.confidence
        if payload.source is not None:
            fact["source"] = payload.source
        updated = True
        break

    if not updated:
        raise HTTPException(status_code=404, detail=f"Fact '{fact_id}' not found")

    _enforce_max_facts(memory_data)
    _save_memory_with_scope(memory_data, workspace_type, workspace_id)
    return MemoryResponse(**_load_memory_with_scope(workspace_type, workspace_id))


@router.delete(
    "/memory/facts/{fact_id}",
    response_model=MemoryResponse,
    summary="Delete Memory Fact",
    description="Delete an existing memory fact by ID in the selected scope.",
)
async def delete_memory_fact(
    fact_id: str,
    workspace_type: str | None = Query(default=None, description="Workspace type scope key"),
    workspace_id: str | None = Query(default=None, description="Workspace ID scope key"),
) -> MemoryResponse:
    memory_data = _load_memory_with_scope(workspace_type, workspace_id)
    facts = memory_data.get("facts", [])
    remaining = [f for f in facts if f.get("id") != fact_id]
    if len(remaining) == len(facts):
        raise HTTPException(status_code=404, detail=f"Fact '{fact_id}' not found")

    memory_data["facts"] = remaining
    _save_memory_with_scope(memory_data, workspace_type, workspace_id)
    return MemoryResponse(**_load_memory_with_scope(workspace_type, workspace_id))


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
        backend=config.backend,
        storage_path=config.storage_path,
        database_configured=bool(config.database_url),
        strict_scope=config.strict_scope,
        auth_mode=config.auth_mode,
        debounce_seconds=config.debounce_seconds,
        max_facts=config.max_facts,
        fact_confidence_threshold=config.fact_confidence_threshold,
        injection_enabled=config.injection_enabled,
        max_injection_tokens=config.max_injection_tokens,
    )


@router.get(
    "/memory/status",
    response_model=MemoryStatusResponse,
    summary="Get Memory Status",
    description="Retrieve both memory configuration and current data in a single request.",
)
async def get_memory_status(
    workspace_type: str | None = Query(default=None, description="Workspace type scope key"),
    workspace_id: str | None = Query(default=None, description="Workspace ID scope key"),
) -> MemoryStatusResponse:
    """Get the memory system status including configuration and data.

    Returns:
        Combined memory configuration and current data.
    """
    config = get_memory_config()
    memory_data = _load_memory_with_scope(workspace_type, workspace_id)

    return MemoryStatusResponse(
        config=MemoryConfigResponse(
            enabled=config.enabled,
            backend=config.backend,
            storage_path=config.storage_path,
            database_configured=bool(config.database_url),
            strict_scope=config.strict_scope,
            auth_mode=config.auth_mode,
            debounce_seconds=config.debounce_seconds,
            max_facts=config.max_facts,
            fact_confidence_threshold=config.fact_confidence_threshold,
            injection_enabled=config.injection_enabled,
            max_injection_tokens=config.max_injection_tokens,
        ),
        data=MemoryResponse(**memory_data),
    )
