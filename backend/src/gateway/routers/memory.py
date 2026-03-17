"""Memory API router for retrieving and managing global memory data."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.agents.memory.updater import get_memory_data, reload_memory_data
from src.config.memory_config import get_memory_config

logger = logging.getLogger(__name__)
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
    storage_path: str = Field(..., description="Path to memory storage file")
    debounce_seconds: int = Field(..., description="Debounce time for memory updates")
    max_facts: int = Field(..., description="Maximum number of facts to store")
    fact_confidence_threshold: float = Field(..., description="Minimum confidence threshold for facts")
    injection_enabled: bool = Field(..., description="Whether memory injection is enabled")
    max_injection_tokens: int = Field(..., description="Maximum tokens for memory injection")
    long_horizon_enabled: bool = Field(default=True, description="Whether long-horizon summary memory is enabled")
    long_horizon_storage_path: str = Field(default="", description="Long-horizon summary storage path")
    long_horizon_max_entries: int = Field(default=500, description="Maximum long-horizon summary entries")
    long_horizon_summary_chars: int = Field(default=900, description="Maximum characters per long-horizon summary")
    long_horizon_injection_enabled: bool = Field(default=True, description="Whether long-horizon retrieval is injected before model calls")
    long_horizon_top_k: int = Field(default=5, description="Top-k long-horizon summaries for injection")
    long_horizon_min_similarity: float = Field(default=0.12, description="Minimum similarity threshold for long-horizon retrieval")
    long_horizon_injection_max_chars: int = Field(default=2400, description="Maximum characters for long-horizon injection block")
    long_horizon_embedding_dim: int = Field(default=256, description="Dense embedding dimension for long-horizon memory retrieval")
    long_horizon_cross_thread_enabled: bool = Field(default=True, description="Whether long-horizon retrieval can include entries from other threads")
    long_horizon_topic_memory_enabled: bool = Field(default=True, description="Whether topic-level aggregated memory is enabled")
    long_horizon_topic_top_k: int = Field(default=2, description="Top-k topic-level memory entries to inject")
    long_horizon_project_memory_enabled: bool = Field(default=True, description="Whether project-level aggregated memory is enabled")
    long_horizon_project_top_k: int = Field(default=2, description="Top-k project-level memory entries to inject")
    long_horizon_current_thread_boost: float = Field(default=0.08, description="Similarity boost for same-thread entries")
    long_horizon_project_boost: float = Field(default=0.12, description="Similarity boost for same-project entries")
    long_horizon_topic_overlap_boost: float = Field(default=0.03, description="Per-topic overlap bonus for long-horizon retrieval")
    long_horizon_hypothesis_memory_enabled: bool = Field(default=True, description="Whether hypothesis-validation memory retrieval is enabled")
    long_horizon_hypothesis_top_k: int = Field(default=2, description="Top-k hypothesis-validation memories to inject")
    long_horizon_hypothesis_max_entries: int = Field(default=400, description="Maximum retained hypothesis-validation memory entries")
    long_horizon_hypothesis_failure_boost: float = Field(default=0.08, description="Retrieval boost for failed/reopened hypothesis memories")


class MemoryStatusResponse(BaseModel):
    """Response model for memory status."""

    config: MemoryConfigResponse
    data: MemoryResponse


@router.get(
    "/memory",
    response_model=MemoryResponse,
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
    try:
        memory_data = get_memory_data()
        return MemoryResponse(**memory_data)
    except Exception as e:
        logger.error("Failed to get memory data: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get memory data")


@router.post(
    "/memory/reload",
    response_model=MemoryResponse,
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
    try:
        memory_data = reload_memory_data()
        return MemoryResponse(**memory_data)
    except Exception as e:
        logger.error("Failed to reload memory data: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reload memory data")


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
        enabled=getattr(config, "enabled", True),
        storage_path=getattr(config, "storage_path", ""),
        debounce_seconds=getattr(config, "debounce_seconds", 30),
        max_facts=getattr(config, "max_facts", 100),
        fact_confidence_threshold=getattr(config, "fact_confidence_threshold", 0.7),
        injection_enabled=getattr(config, "injection_enabled", True),
        max_injection_tokens=getattr(config, "max_injection_tokens", 2000),
        long_horizon_enabled=getattr(config, "long_horizon_enabled", True),
        long_horizon_storage_path=getattr(config, "long_horizon_storage_path", ""),
        long_horizon_max_entries=getattr(config, "long_horizon_max_entries", 500),
        long_horizon_summary_chars=getattr(config, "long_horizon_summary_chars", 900),
        long_horizon_injection_enabled=getattr(config, "long_horizon_injection_enabled", True),
        long_horizon_top_k=getattr(config, "long_horizon_top_k", 5),
        long_horizon_min_similarity=getattr(config, "long_horizon_min_similarity", 0.12),
        long_horizon_injection_max_chars=getattr(config, "long_horizon_injection_max_chars", 2400),
        long_horizon_embedding_dim=getattr(config, "long_horizon_embedding_dim", 256),
        long_horizon_cross_thread_enabled=getattr(config, "long_horizon_cross_thread_enabled", True),
        long_horizon_topic_memory_enabled=getattr(config, "long_horizon_topic_memory_enabled", True),
        long_horizon_topic_top_k=getattr(config, "long_horizon_topic_top_k", 2),
        long_horizon_project_memory_enabled=getattr(config, "long_horizon_project_memory_enabled", True),
        long_horizon_project_top_k=getattr(config, "long_horizon_project_top_k", 2),
        long_horizon_current_thread_boost=getattr(config, "long_horizon_current_thread_boost", 0.08),
        long_horizon_project_boost=getattr(config, "long_horizon_project_boost", 0.12),
        long_horizon_topic_overlap_boost=getattr(config, "long_horizon_topic_overlap_boost", 0.03),
        long_horizon_hypothesis_memory_enabled=getattr(config, "long_horizon_hypothesis_memory_enabled", True),
        long_horizon_hypothesis_top_k=getattr(config, "long_horizon_hypothesis_top_k", 2),
        long_horizon_hypothesis_max_entries=getattr(config, "long_horizon_hypothesis_max_entries", 400),
        long_horizon_hypothesis_failure_boost=getattr(config, "long_horizon_hypothesis_failure_boost", 0.08),
    )


@router.get(
    "/memory/status",
    response_model=MemoryStatusResponse,
    summary="Get Memory Status",
    description="Retrieve both memory configuration and current data in a single request.",
)
async def get_memory_status() -> MemoryStatusResponse:
    """Get the memory system status including configuration and data.

    Returns:
        Combined memory configuration and current data.
    """
    config = get_memory_config()
    memory_data = get_memory_data()

    return MemoryStatusResponse(
        config=MemoryConfigResponse(
            enabled=getattr(config, "enabled", True),
            storage_path=getattr(config, "storage_path", ""),
            debounce_seconds=getattr(config, "debounce_seconds", 30),
            max_facts=getattr(config, "max_facts", 100),
            fact_confidence_threshold=getattr(config, "fact_confidence_threshold", 0.7),
            injection_enabled=getattr(config, "injection_enabled", True),
            max_injection_tokens=getattr(config, "max_injection_tokens", 2000),
            long_horizon_enabled=getattr(config, "long_horizon_enabled", True),
            long_horizon_storage_path=getattr(config, "long_horizon_storage_path", ""),
            long_horizon_max_entries=getattr(config, "long_horizon_max_entries", 500),
            long_horizon_summary_chars=getattr(config, "long_horizon_summary_chars", 900),
            long_horizon_injection_enabled=getattr(config, "long_horizon_injection_enabled", True),
            long_horizon_top_k=getattr(config, "long_horizon_top_k", 5),
            long_horizon_min_similarity=getattr(config, "long_horizon_min_similarity", 0.12),
            long_horizon_injection_max_chars=getattr(config, "long_horizon_injection_max_chars", 2400),
            long_horizon_embedding_dim=getattr(config, "long_horizon_embedding_dim", 256),
            long_horizon_cross_thread_enabled=getattr(config, "long_horizon_cross_thread_enabled", True),
            long_horizon_topic_memory_enabled=getattr(config, "long_horizon_topic_memory_enabled", True),
            long_horizon_topic_top_k=getattr(config, "long_horizon_topic_top_k", 2),
            long_horizon_project_memory_enabled=getattr(config, "long_horizon_project_memory_enabled", True),
            long_horizon_project_top_k=getattr(config, "long_horizon_project_top_k", 2),
            long_horizon_current_thread_boost=getattr(config, "long_horizon_current_thread_boost", 0.08),
            long_horizon_project_boost=getattr(config, "long_horizon_project_boost", 0.12),
            long_horizon_topic_overlap_boost=getattr(config, "long_horizon_topic_overlap_boost", 0.03),
            long_horizon_hypothesis_memory_enabled=getattr(config, "long_horizon_hypothesis_memory_enabled", True),
            long_horizon_hypothesis_top_k=getattr(config, "long_horizon_hypothesis_top_k", 2),
            long_horizon_hypothesis_max_entries=getattr(config, "long_horizon_hypothesis_max_entries", 400),
            long_horizon_hypothesis_failure_boost=getattr(config, "long_horizon_hypothesis_failure_boost", 0.08),
        ),
        data=MemoryResponse(**memory_data),
    )
