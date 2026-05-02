"""Configuration for RAG (Retrieval-Augmented Generation) subsystem."""

from pydantic import BaseModel, Field


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


# Global configuration instance
_rag_config: RagConfig = RagConfig()


def get_rag_config() -> RagConfig:
    """Get the current RAG configuration."""
    return _rag_config


def set_rag_config(config: RagConfig) -> None:
    """Set the RAG configuration."""
    global _rag_config
    _rag_config = config


def load_rag_config_from_dict(config_dict: dict) -> None:
    """Load RAG configuration from a dictionary."""
    global _rag_config
    _rag_config = RagConfig(**config_dict)
