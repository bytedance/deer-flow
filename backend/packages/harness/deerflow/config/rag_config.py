"""Configuration for RAG (Retrieval-Augmented Generation) subsystem."""

import logging

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class RagConfig(BaseModel):
    """Configuration for the RAG (embedding + vector store) pipeline."""

    enabled: bool = Field(
        default=False,
        description="Whether to enable the RAG subsystem",
    )
    embedding_model: str = Field(
        default="openai:text-embedding-3-small",
        description="Embedding model in 'provider:model' format (e.g. 'openai:text-embedding-3-small')",
    )
    embedding_api_key: str = Field(
        default="",
        description="API key for the embedding provider. Supports $ENV_VAR resolution.",
    )
    embedding_base_url: str = Field(
        default="",
        description="Custom base URL for the embedding API (e.g. 'https://api.openai-proxy.com/v1'). "
        "Empty = use provider default.",
    )
    embedding_batch_size: int = Field(
        default=64,
        ge=1,
        le=2048,
        description="Maximum number of texts sent per embedding API request. "
        "OpenAI accepts up to 2048, but DashScope-style proxies (e.g. 'text-embedding-v4' "
        "via aliyun) cap this at 10. Lower this when the provider rejects with "
        "'batch size is invalid'.",
    )
    vector_store_backend: str = Field(
        default="chroma",
        description="Vector store backend: 'chroma' or 'pgvector'",
    )
    chroma_persist_dir: str = Field(
        default="",
        description="ChromaDB persistence directory. Empty = auto-resolve to tenant base dir.",
    )
    pgvector_connection_string: str = Field(
        default="",
        description="PostgreSQL connection string for pgvector backend",
    )
    chunk_size: int = Field(
        default=1000,
        ge=100,
        le=8000,
        description="Target chunk size in characters",
    )
    chunk_overlap: int = Field(
        default=200,
        ge=0,
        le=2000,
        description="Overlap between consecutive chunks in characters",
    )
    chunk_strategy: str = Field(
        default="recursive",
        description="Chunking strategy: 'recursive', 'markdown', or 'semantic'",
    )
    retrieval_top_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Number of chunks to retrieve per query",
    )
    score_threshold: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score threshold for retrieval (0 = disabled)",
    )
    reranker_enabled: bool = Field(
        default=False,
        description="Whether to enable cross-encoder reranking",
    )
    injection_enabled: bool = Field(
        default=True,
        description="Whether to auto-inject relevant chunks into the system prompt via middleware",
    )
    tool_enabled: bool = Field(
        default=True,
        description="Whether to register the search_knowledge_base tool",
    )
    max_injection_chunks: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Maximum chunks to inject via middleware",
    )
    max_injection_tokens: int = Field(
        default=2000,
        ge=100,
        le=8000,
        description="Maximum tokens for chunk injection into system prompt",
    )
    max_selected_kbs: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of knowledge bases that can be selected per session",
    )
    per_kb_timeout_ms: int = Field(
        default=1500,
        ge=100,
        le=10000,
        description="Timeout in milliseconds for each knowledge base retrieval",
    )
    max_chunks_per_document: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum chunks from a single document to include in results",
    )
    allow_no_auth_kb: bool = Field(
        default=False,
        description="Allow knowledge base access when user is unauthenticated (user_id='default'). "
        "Set to True only for development/demo environments.",
    )
    cross_kb_score_strategy: str = Field(
        default="absolute",
        description="How to compare scores across knowledge bases when merging "
        "multi-KB results. 'absolute' (default) keeps raw vector scores so a "
        "high-confidence hit from a small KB still wins; 'per_kb_minmax' "
        "min-max-normalizes each KB independently — better when KBs use different "
        "embedding models / metrics, worse when one KB has stronger relevance.",
    )
    rerank_recall_factor: float = Field(
        default=3.0,
        ge=1.0,
        le=10.0,
        description="When the cross-encoder reranker is enabled, retrieval pulls "
        "max_injection_chunks × this factor candidates first, then reranks and "
        "trims back to max_injection_chunks. Wider recall lets the reranker "
        "promote a chunk a vector search ranked low; capped by retrieval_top_k.",
    )
    indexing_workers: int = Field(
        default=2,
        ge=0,
        le=16,
        description="Number of background worker tasks consuming the indexing "
        "queue. 0 disables the dispatcher and falls back to inline indexing — "
        "useful for tests / bare-bones dev setups, but blocks the upload "
        "request on embedding latency.",
    )
    indexing_queue_max: int = Field(
        default=256,
        ge=1,
        le=10000,
        description="Maximum number of pending index jobs the dispatcher will "
        "buffer before submit() raises. Acts as a back-pressure signal so a "
        "burst of uploads can't grow the queue without bound.",
    )


# Global configuration instance
_rag_config: RagConfig = RagConfig()


def get_rag_config() -> RagConfig:
    """Get the current RAG configuration."""
    return _rag_config


def compute_effective_top_k(config: RagConfig) -> int:
    """Return the recall size that retrieval should ask for *before* rerank.

    Why: when ``reranker_enabled`` is False, the K we want to inject is
    also the K to retrieve. When the reranker is on, we want a wider
    recall pool so the reranker has room to promote a chunk that a vector
    search ranked low — multiply by ``rerank_recall_factor`` and cap at
    ``retrieval_top_k`` so we don't blow past the configured upper bound.

    How to apply: callers retrieve at ``compute_effective_top_k(config)``,
    then trim to ``config.max_injection_chunks`` after rerank.
    """
    base = max(1, int(config.max_injection_chunks))
    if not config.reranker_enabled:
        return min(base, config.retrieval_top_k)
    factor = max(1.0, float(config.rerank_recall_factor))
    return min(config.retrieval_top_k, max(base, int(round(base * factor))))


def set_rag_config(config: RagConfig) -> None:
    """Set the RAG configuration."""
    global _rag_config
    _rag_config = config


def load_rag_config_from_dict(config_dict: dict) -> None:
    """Load RAG configuration from a dictionary."""
    global _rag_config
    _rag_config = RagConfig(**config_dict)
    _log_startup_summary(_rag_config)


def _log_startup_summary(config: RagConfig) -> None:
    """Emit a one-line INFO summary of the RAG subsystem state at boot.

    The line is what an operator should grep for first when diagnosing
    "why is the agent not seeing my KB?": it shows the master enable
    switches, the injection / tool toggles, the no-auth posture, and
    the active vector backend.
    """
    logger.info(
        "RAG config loaded: enabled=%s injection=%s tool=%s "
        "allow_no_auth_kb=%s vector_store=%s embedding_model=%s "
        "max_selected_kbs=%d max_injection_chunks=%d max_injection_tokens=%d "
        "per_kb_timeout_ms=%d",
        config.enabled,
        config.injection_enabled,
        config.tool_enabled,
        config.allow_no_auth_kb,
        config.vector_store_backend,
        config.embedding_model,
        config.max_selected_kbs,
        config.max_injection_chunks,
        config.max_injection_tokens,
        config.per_kb_timeout_ms,
    )
