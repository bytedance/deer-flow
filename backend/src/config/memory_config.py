"""Configuration for memory mechanism."""

from pydantic import BaseModel, Field


class MemoryConfig(BaseModel):
    """Configuration for global memory mechanism."""

    enabled: bool = Field(
        default=True,
        description="Whether to enable memory mechanism",
    )
    storage_path: str = Field(
        default="",
        description=(
            "Path to store memory data. "
            "If empty, defaults to `{base_dir}/memory.json` (see Paths.memory_file). "
            "Absolute paths are used as-is. "
            "Relative paths are resolved against `Paths.base_dir` "
            "(not the backend working directory). "
            "Note: if you previously set this to `.deer-flow/memory.json`, "
            "the file will now be resolved as `{base_dir}/.deer-flow/memory.json`; "
            "migrate existing data or use an absolute path to preserve the old location."
        ),
    )
    debounce_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Seconds to wait before processing queued updates (debounce)",
    )
    model_name: str | None = Field(
        default=None,
        description="Model name to use for memory updates (None = use default model)",
    )
    max_facts: int = Field(
        default=100,
        ge=10,
        le=500,
        description="Maximum number of facts to store",
    )
    fact_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for storing facts",
    )
    injection_enabled: bool = Field(
        default=True,
        description="Whether to inject memory into system prompt",
    )
    max_injection_tokens: int = Field(
        default=2000,
        ge=100,
        le=8000,
        description="Maximum tokens to use for memory injection",
    )
    long_horizon_enabled: bool = Field(
        default=True,
        description="Enable long-horizon summary memory for multi-turn research workflows",
    )
    long_horizon_storage_path: str = Field(
        default="",
        description="Path to long-horizon summary store. Empty uses `{base_dir}/.deer-flow/memory_long_horizon.json`.",
    )
    long_horizon_max_entries: int = Field(
        default=500,
        ge=50,
        le=5000,
        description="Maximum long-horizon summary entries to retain",
    )
    long_horizon_summary_chars: int = Field(
        default=900,
        ge=200,
        le=4000,
        description="Maximum characters retained per turn summary",
    )
    long_horizon_injection_enabled: bool = Field(
        default=True,
        description="Whether relevant long-horizon summaries are injected before model calls",
    )
    long_horizon_top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Top-k long-horizon summaries to inject by vector similarity",
    )
    long_horizon_min_similarity: float = Field(
        default=0.12,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity required for long-horizon summary retrieval",
    )
    long_horizon_injection_max_chars: int = Field(
        default=2400,
        ge=200,
        le=12000,
        description="Maximum characters for injected long-horizon memory block",
    )
    long_horizon_embedding_dim: int = Field(
        default=256,
        ge=64,
        le=2048,
        description="Dense embedding dimension for long-horizon retrieval",
    )
    long_horizon_cross_thread_enabled: bool = Field(
        default=True,
        description="Whether long-horizon retrieval can include entries from other threads",
    )
    long_horizon_topic_memory_enabled: bool = Field(
        default=True,
        description="Enable topic-level aggregated memory for cross-turn retrieval",
    )
    long_horizon_topic_top_k: int = Field(
        default=2,
        ge=0,
        le=20,
        description="Top-k topic memories to include during long-horizon retrieval",
    )
    long_horizon_project_memory_enabled: bool = Field(
        default=True,
        description="Enable project-level aggregated memory for cross-thread retrieval",
    )
    long_horizon_project_top_k: int = Field(
        default=2,
        ge=0,
        le=20,
        description="Top-k project memories to include during long-horizon retrieval",
    )
    long_horizon_current_thread_boost: float = Field(
        default=0.08,
        ge=0.0,
        le=1.0,
        description="Similarity boost applied to entries from the current thread",
    )
    long_horizon_project_boost: float = Field(
        default=0.12,
        ge=0.0,
        le=1.0,
        description="Similarity boost applied when entry and query share project context",
    )
    long_horizon_topic_overlap_boost: float = Field(
        default=0.03,
        ge=0.0,
        le=1.0,
        description="Per-topic overlap bonus added to similarity score",
    )
    long_horizon_hypothesis_memory_enabled: bool = Field(
        default=True,
        description="Enable hypothesis-validation trajectory memory in long-horizon retrieval.",
    )
    long_horizon_hypothesis_top_k: int = Field(
        default=2,
        ge=0,
        le=20,
        description="Top-k hypothesis-validation memories to include during retrieval.",
    )
    long_horizon_hypothesis_max_entries: int = Field(
        default=400,
        ge=50,
        le=5000,
        description="Maximum hypothesis-validation memory entries to retain.",
    )
    long_horizon_hypothesis_failure_boost: float = Field(
        default=0.08,
        ge=0.0,
        le=1.0,
        description="Additional retrieval boost for failed/reopened hypothesis memories.",
    )


# Global configuration instance
_memory_config: MemoryConfig = MemoryConfig()


def get_memory_config() -> MemoryConfig:
    """Get the current memory configuration."""
    return _memory_config


def set_memory_config(config: MemoryConfig) -> None:
    """Set the memory configuration."""
    global _memory_config
    _memory_config = config


def load_memory_config_from_dict(config_dict: dict) -> None:
    """Load memory configuration from a dictionary."""
    global _memory_config
    _memory_config = MemoryConfig(**config_dict)
