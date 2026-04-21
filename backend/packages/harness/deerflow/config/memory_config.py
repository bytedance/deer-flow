"""Configuration for memory mechanism."""

from pydantic import BaseModel, Field, model_validator


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
    storage_class: str = Field(
        default="deerflow.agents.memory.storage.FileMemoryStorage",
        description="The class path for memory storage provider",
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
    # SQLite writer-queue tunables. These only apply when the configured
    # ``storage_class`` is ``SQLiteMemoryStorage``; file storage ignores them.
    lock_stale_seconds: int = Field(
        default=90,
        ge=10,
        le=3600,
        description=(
            "Writer lease is considered dead after this many seconds without "
            "a heartbeat renewal. Must be strictly greater than "
            "2 * heartbeat_interval_seconds (enforced by the cross-field "
            "validator below) to preserve a safety margin before the lease "
            "is considered stale."
        ),
    )
    heartbeat_interval_seconds: int = Field(
        default=30,
        ge=1,
        le=600,
        description=("Writer lease heartbeat period. Must be strictly less than lock_stale_seconds / 2 (enforced by the cross-field validator below) to preserve a safety margin before the lease is considered stale."),
    )
    processing_timeout_seconds: int = Field(
        default=300,
        ge=10,
        le=86400,
        description=("Maximum time a queue task may remain in the 'processing' state before reset_stuck_tasks() moves it back to 'pending'."),
    )

    @model_validator(mode="after")
    def _validate_writer_queue_timings(self) -> "MemoryConfig":
        """Enforce ``heartbeat_interval_seconds * 2 < lock_stale_seconds``.

        This keeps the heartbeat interval comfortably below the stale-lease
        threshold, so a briefly delayed writer (for example, a long LLM call)
        does not lose its lease to a racing process. Invalid configs fail fast
        at load time instead of being silently clamped later.
        """
        if self.heartbeat_interval_seconds * 2 >= self.lock_stale_seconds:
            raise ValueError(
                f"heartbeat_interval_seconds must be strictly less than lock_stale_seconds / 2 to preserve the stale-lease safety margin (got heartbeat={self.heartbeat_interval_seconds}s, lock_stale={self.lock_stale_seconds}s)."
            )
        return self


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
