"""Memory API router for retrieving and managing global memory data."""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.gateway.internal_auth import get_trusted_internal_owner_user_id
from deerflow.agents.memory import MemoryConflictError, MemoryCorruptionError, MemoryManager, get_memory_manager
from deerflow.config.memory_config import get_memory_config
from deerflow.config.paths import make_safe_user_id
from deerflow.runtime.user_context import get_effective_user_id

router = APIRouter(prefix="/api", tags=["memory"])


def _resolve_memory_user_id(request: Request) -> str:
    """Resolve the memory owner for this request.

    Honors the trusted internal owner header that channel workers attach when
    acting for a connection owner, so an IM ``/memory`` command reads the bound
    owner's memory instead of the synthetic internal user. The header is only
    honored after ``AuthMiddleware`` validated the internal token (see
    ``get_trusted_internal_owner_user_id``). Browser/API callers are never
    internal, so this falls back to the normal contextvar-based effective user.

    The trusted owner header carries the *raw* owner id, so sanitize it through
    ``make_safe_user_id`` (the same normalization the channel file pipeline applies
    via ``_safe_user_id_for_run``/``prepare_user_dir_for_raw_id``). This keeps the
    memory bucket aligned with the owner's file/upload bucket and avoids a 500 when
    the raw id contains characters ``_validate_user_id`` would reject.
    """
    raw_owner = get_trusted_internal_owner_user_id(request)
    if raw_owner:
        return make_safe_user_id(raw_owner)
    return get_effective_user_id()


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
    categoryExtension: str | None = Field(default=None, description="Extension category when category is 'other'")
    topics: list[str] | None = Field(default=None, description="Retrieval-oriented topic labels")
    confidence: float = Field(default=0.5, description="Confidence score (0-1)")
    createdAt: str = Field(default="", description="Creation timestamp")
    source: str = Field(default="unknown", description="Legacy source string; structured metadata remains internal to storage")
    sourceError: str | None = Field(default=None, description="Optional description of the prior mistake or wrong approach")
    schemaVersion: int | None = Field(default=None, description="Per-fact schema version")
    status: str | None = Field(default=None, description="Fact lifecycle status")
    scope: dict[str, str | None] | None = Field(default=None, description="Canonical user/agent scope")
    revision: int | None = Field(default=None, description="Fact optimistic revision")
    updatedAt: str | None = Field(default=None, description="Last fact update timestamp")
    consolidatedAt: str | None = None
    consolidatedFrom: list[str] | None = None

    @field_validator("source", mode="before")
    @classmethod
    def _legacy_source_string(cls, value: Any) -> str:
        """Keep the HTTP contract stable while Markdown stores rich metadata."""
        if isinstance(value, str):
            return value
        if not isinstance(value, dict):
            return "unknown"
        source_type = value.get("type")
        thread_id = value.get("threadId")
        if source_type == "conversation" and isinstance(thread_id, str) and thread_id:
            return thread_id
        if isinstance(source_type, str) and source_type:
            return source_type
        if isinstance(thread_id, str) and thread_id:
            return thread_id
        return "unknown"


class MemoryResponse(BaseModel):
    """Response model for memory data."""

    version: str = Field(default="1.0", description="Memory schema version")
    revision: int | None = Field(default=None, description="Manifest revision")
    lastUpdated: str = Field(default="", description="Last update timestamp")
    user: UserContext = Field(default_factory=UserContext)
    history: HistoryContext = Field(default_factory=HistoryContext)
    facts: list[Fact] = Field(default_factory=list)


def _map_memory_fact_value_error(exc: ValueError) -> HTTPException:
    """Convert updater validation errors into stable API responses."""
    if exc.args and exc.args[0] == "confidence":
        detail = "Invalid confidence value; must be between 0 and 1."
    elif exc.args and exc.args[0] == "agent_name":
        detail = "An agent name is required for fact operations; user-global memory stores summaries only."
    else:
        detail = "Memory fact content cannot be empty."
    return HTTPException(status_code=400, detail=detail)


def _map_memory_manager_error(exc: MemoryConflictError | MemoryCorruptionError) -> HTTPException:
    """Map backend-neutral manager errors without importing a storage plugin."""
    if isinstance(exc, MemoryConflictError):
        return HTTPException(status_code=409, detail="Memory changed concurrently; reload and retry.")
    return HTTPException(status_code=500, detail="Stored memory data is corrupted.")


def _unsupported_501(manager: object, label: str) -> HTTPException:
    """501 for an unsupported memory operation.

    Tier-3 hooks (``reload_memory`` / ``create_fact`` / ``delete_fact`` /
    ``update_fact``) and tier-2 management ops (``get_memory`` / ``clear_memory``
    / ``import_memory``) all default to ``raise NotImplementedError``; backends
    that support them override, unsupported ones inherit the raise. Before the
    contract change these were ``@abstractmethod`` (every backend implemented
    them, so the endpoints could never raise); now a minimal backend (only
    ``add`` + ``get_context``) inherits the raise, so endpoints invoke the
    method directly and catch ``NotImplementedError`` -> this 501. There is no
    global ``NotImplementedError`` handler, so an uncaught raise is a raw 500.
    """
    return HTTPException(
        status_code=501,
        detail=f"Operation '{label}' not supported by memory backend '{type(manager).__name__}'.",
    )


def _get_memory_or_501(manager: MemoryManager, user_id: str, label: str) -> dict[str, Any]:
    """Read the full memory doc; 501 if the backend doesn't expose one.

    ``get_memory`` is tier-2 (default ``raise NotImplementedError``); a minimal
    backend doesn't expose a full doc. The standalone read endpoints (GET
    /memory, /memory/export, /memory/status) and the /memory/reload fallback all
    route reads through here so an unsupported backend gets a clean 501 instead
    of a raw 500. ``label`` is the operation name in the 501 detail (the
    endpoint's verb, e.g. "get memory" / "export memory" / "reload memory").
    """
    try:
        return manager.get_memory(user_id=user_id)
    except NotImplementedError:
        raise _unsupported_501(manager, label) from None
    except (MemoryConflictError, MemoryCorruptionError) as exc:
        raise _map_memory_manager_error(exc) from exc


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

    enabled: bool = Field(..., description="Whether the memory mechanism is enabled (call-site gate).")
    mode: Literal["middleware", "tool"] = Field(..., description="Memory operation mode: 'middleware' (passive per-turn LLM summarization) or 'tool' (model calls memory tools directly). Mechanism-level, applies to any backend.")
    injection_enabled: bool = Field(..., description="Whether memory is injected into the system prompt (call-site gate).")
    shutdown_flush_timeout_seconds: float = Field(..., description="Hard budget (s) to drain pending memory updates on Gateway graceful shutdown; must fit inside the pod's K8s terminationGracePeriodSeconds.")
    manager_class: str = Field(..., description="Active memory backend selector (backend name or dotted path).")
    backend_config: dict = Field(..., description="Backend-private config (self-interpreted by the backend).")


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
async def get_memory(http_request: Request) -> MemoryResponse:
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
    manager = get_memory_manager()
    memory_data = _get_memory_or_501(manager, _resolve_memory_user_id(http_request), "get memory")
    return MemoryResponse(**memory_data)


@router.post(
    "/memory/reload",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Reload Memory Data",
    description="Reload memory data from the storage file, refreshing the in-memory cache.",
)
async def reload_memory(http_request: Request) -> MemoryResponse:
    """Reload memory data from file.

    This forces a reload of the memory data from the storage file,
    useful when the file has been modified externally.

    Returns:
        The reloaded memory data.
    """
    user_id = _resolve_memory_user_id(http_request)
    manager = get_memory_manager()
    try:
        memory_data = manager.reload_memory(user_id=user_id)
    except NotImplementedError:
        # Non-DeerMem backends have no reload concept; fall back to get_memory
        # (read-only refresh, so degrading is safe and still useful -- vs fact
        # CRUD writes, which fail loud at 501 since silently no-op'ing a write
        # would hide data loss). If get_memory is also unsupported (a minimal
        # backend with no full doc), surface 501 rather than a raw 500: reads
        # degrade only when there is a doc to degrade to.
        memory_data = _get_memory_or_501(manager, user_id, "reload memory")
    except (MemoryConflictError, MemoryCorruptionError) as exc:
        raise _map_memory_manager_error(exc) from exc
    return MemoryResponse(**memory_data)


@router.delete(
    "/memory",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Clear All Memory Data",
    description="Delete all saved memory data and reset the memory structure to an empty state.",
)
async def clear_memory(http_request: Request) -> MemoryResponse:
    """Clear all persisted memory data."""
    manager = get_memory_manager()
    try:
        memory_data = manager.clear_memory(user_id=_resolve_memory_user_id(http_request))
    except NotImplementedError:
        raise _unsupported_501(manager, "clear memory") from None
    except (MemoryConflictError, MemoryCorruptionError) as exc:
        raise _map_memory_manager_error(exc) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to clear memory data.") from exc

    return MemoryResponse(**memory_data)


@router.post(
    "/memory/facts",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Create Memory Fact",
    description="Create a single saved memory fact manually.",
)
async def create_memory_fact_endpoint(request: FactCreateRequest, http_request: Request) -> MemoryResponse:
    """Create a single fact manually."""
    manager = get_memory_manager()
    try:
        memory_data, fact_id = manager.create_fact(
            content=request.content,
            category=request.category,
            confidence=request.confidence,
            user_id=_resolve_memory_user_id(http_request),
        )
    except NotImplementedError:
        raise _unsupported_501(manager, "create fact") from None
    except ValueError as exc:
        raise _map_memory_fact_value_error(exc) from exc
    except (MemoryConflictError, MemoryCorruptionError) as exc:
        raise _map_memory_manager_error(exc) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to create memory fact.") from exc

    if fact_id is None:
        # max_facts cap evicted the new (lower-confidence) fact; it was not stored.
        raise HTTPException(status_code=409, detail="Fact was not stored because memory.max_facts kept higher-confidence facts")
    return MemoryResponse(**memory_data)


@router.delete(
    "/memory/facts/{fact_id}",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Delete Memory Fact",
    description="Delete a single saved memory fact by its fact id.",
)
async def delete_memory_fact_endpoint(fact_id: str, http_request: Request) -> MemoryResponse:
    """Delete a single fact from memory by fact id."""
    manager = get_memory_manager()
    try:
        memory_data = manager.delete_fact(fact_id, user_id=_resolve_memory_user_id(http_request))
    except NotImplementedError:
        raise _unsupported_501(manager, "delete fact") from None
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Memory fact '{fact_id}' not found.") from exc
    except (MemoryConflictError, MemoryCorruptionError) as exc:
        raise _map_memory_manager_error(exc) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to delete memory fact.") from exc

    return MemoryResponse(**memory_data)


@router.patch(
    "/memory/facts/{fact_id}",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Patch Memory Fact",
    description="Partially update a single saved memory fact by its fact id while preserving omitted fields.",
)
async def update_memory_fact_endpoint(fact_id: str, request: FactPatchRequest, http_request: Request) -> MemoryResponse:
    """Partially update a single fact manually."""
    manager = get_memory_manager()
    try:
        memory_data = manager.update_fact(
            fact_id=fact_id,
            content=request.content,
            category=request.category,
            confidence=request.confidence,
            user_id=_resolve_memory_user_id(http_request),
        )
    except NotImplementedError:
        raise _unsupported_501(manager, "update fact") from None
    except ValueError as exc:
        raise _map_memory_fact_value_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Memory fact '{fact_id}' not found.") from exc
    except (MemoryConflictError, MemoryCorruptionError) as exc:
        raise _map_memory_manager_error(exc) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to update memory fact.") from exc

    return MemoryResponse(**memory_data)


@router.get(
    "/memory/export",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Export Memory Data",
    description="Export the current global memory data as JSON for backup or transfer.",
)
async def export_memory(http_request: Request) -> MemoryResponse:
    """Export the current memory data."""
    manager = get_memory_manager()
    memory_data = _get_memory_or_501(manager, _resolve_memory_user_id(http_request), "export memory")
    return MemoryResponse(**memory_data)


@router.post(
    "/memory/import",
    response_model=MemoryResponse,
    response_model_exclude_none=True,
    summary="Import Memory Data",
    description="Import and overwrite the current global memory data from a JSON payload.",
)
async def import_memory(request: MemoryResponse, http_request: Request) -> MemoryResponse:
    """Import and persist memory data."""
    manager = get_memory_manager()
    try:
        memory_data = manager.import_memory(request.model_dump(exclude_none=True), user_id=_resolve_memory_user_id(http_request))
    except NotImplementedError:
        raise _unsupported_501(manager, "import memory") from None
    except (MemoryConflictError, MemoryCorruptionError) as exc:
        raise _map_memory_manager_error(exc) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to import memory data.") from exc

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
        The current memory configuration. The response is backend-agnostic:
        ``enabled`` / ``injection_enabled`` / ``mode`` are mechanism-level
        fields that apply to any backend (``mode`` selects middleware vs tool
        operation), and ``backend_config`` is an opaque dict the active
        backend (``manager_class``) self-interprets. DeerMem's knobs
        (``storage_path``, ``max_facts``, ``debounce_seconds``, ...) live under
        ``backend_config`` -- they are NOT top-level, because a non-DeerMem
        backend has its own (different) knobs.

    Example Response:
        ```json
        {
            "enabled": true,
            "injection_enabled": true,
            "shutdown_flush_timeout_seconds": 30.0,
            "mode": "middleware",
            "manager_class": "deermem",
            "backend_config": {
                "storage_path": "/.../.deer-flow",
                "debounce_seconds": 30,
                "max_facts": 100,
                "fact_confidence_threshold": 0.7,
                "max_injection_tokens": 2000,
                "token_counting": "tiktoken"
            }
        }
        ```
    """
    config = get_memory_config()
    return MemoryConfigResponse(
        enabled=config.enabled,
        mode=config.mode,
        injection_enabled=config.injection_enabled,
        shutdown_flush_timeout_seconds=config.shutdown_flush_timeout_seconds,
        manager_class=config.manager_class,
        backend_config=config.backend_config,
    )


@router.get(
    "/memory/status",
    response_model=MemoryStatusResponse,
    response_model_exclude_none=True,
    summary="Get Memory Status",
    description="Retrieve both memory configuration and current data in a single request.",
)
async def get_memory_status(http_request: Request) -> MemoryStatusResponse:
    """Get the memory system status including configuration and data.

    Returns:
        Combined memory configuration and current data.
    """
    config = get_memory_config()
    manager = get_memory_manager()
    memory_data = _get_memory_or_501(manager, _resolve_memory_user_id(http_request), "get memory status")

    return MemoryStatusResponse(
        config=MemoryConfigResponse(
            enabled=config.enabled,
            mode=config.mode,
            injection_enabled=config.injection_enabled,
            shutdown_flush_timeout_seconds=config.shutdown_flush_timeout_seconds,
            manager_class=config.manager_class,
            backend_config=config.backend_config,
        ),
        data=MemoryResponse(**memory_data),
    )
