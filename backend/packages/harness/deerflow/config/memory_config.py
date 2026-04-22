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
            "If empty, defaults to per-user memory at `{base_dir}/users/{user_id}/memory.json`. "
            "Absolute paths are used as-is and opt out of per-user isolation "
            "(all users share the same file). "
            "Relative paths are resolved against `Paths.base_dir` "
            "(not the backend working directory). "
            "Note: if you previously set this to `.deer-flow/memory.json`, "
            "the file will now be resolved as `{base_dir}/.deer-flow/memory.json`; "
            "migrate existing data or use an absolute path to preserve the old location."
        ),
    )
    storage_class: str = Field(
        default="deerflow.agents.memory.storage.FileMemoryStorage",
        description=(
            "Memory storage implementation. Built-ins: "
            "`deerflow.agents.memory.storage.FileMemoryStorage` (default), "
            "`deerflow.agents.memory.mongo_memory_storage.MongoMemoryStorage`, "
            "`deerflow.agents.memory.postgres_memory_storage.PostgresMemoryStorage`. "
            "Mongo/Postgres require optional deps: install `deerflow-harness[memory-db]` "
            "or add `pymongo` / `psycopg[binary]` to the environment."
        ),
    )
    connection_string: str | None = Field(
        default=None,
        description="PostgreSQL DSN when using PostgresMemoryStorage.",
    )
    postgres_schema: str | None = Field(
        default=None,
        description="Optional schema for the memory table (qualified as schema.table in SQL).",
    )
    table: str = Field(
        default="agent_memory",
        description="SQL table name or default Mongo collection when mongo_collection is unset.",
    )
    mongo_collection: str = Field(
        default="agent_memory",
        description="MongoDB collection name (one document per user_id + thread_id + agent_name).",
    )
    mongo_database: str = Field(
        default="deerflow",
        description="MongoDB database name for memory documents.",
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
