"""Configuration for Gateway user↔thread mapping persistence (``mapping_store``)."""

from typing import Literal

from pydantic import BaseModel, Field

UserThreadMappingType = Literal["memory", "sqlite", "postgres", "postgres-legacy", "mongo", "redis"]


class UserThreadMappingConfig(BaseModel):
    """Backend for listing and registering user-owned threads (independent of LangGraph Store)."""

    enabled: bool = Field(default=False, description="Enable user thread mapping API and registration on runs")

    type: UserThreadMappingType = Field(
        description="Mapping backend: memory (ephemeral), sqlite, postgres (persistence adapter), postgres-legacy, mongo, or redis."
    )
    connection_string: str | None = Field(
        default=None,
        description="Connection string or path: sqlite file path or ':memory:'; postgres DSN; mongo URI; redis URL.",
    )
    postgres_schema: str | None = Field(
        default=None,
        description="When type is postgres, optional schema for the mapping table (qualified as schema.table in SQL). "
                    "Created automatically if missing (requires DB permission).",
    )
    table: str = Field(
        default="user_thread_mappings",
        description=(
            "SQL table name (sqlite/postgres) or default MongoDB collection name when mongo_collection is unset. "
            "Must be a single unquoted SQL identifier for SQL backends."
        ),
    )
    mongo_collection: str | None = Field(
        default=None,
        description="When type is mongo, collection name; defaults to ``table`` when omitted.",
    )
    mongo_database: str = Field(
        default="deerflow",
        description="When type is mongo, database name.",
    )
    redis_key_prefix: str = Field(
        default="deerflow:utm",
        description="When type is redis, key prefix for per-user hashes (``{prefix}:user:{user_id}``).",
    )


_user_thread_mapping_config: UserThreadMappingConfig | None = None


def get_user_thread_mapping_config() -> UserThreadMappingConfig | None:
    """Return the loaded ``user_thread_mapping`` config, or None if not configured."""
    return _user_thread_mapping_config


def set_user_thread_mapping_config(config: UserThreadMappingConfig | None) -> None:
    """Set the user_thread_mapping configuration."""
    global _user_thread_mapping_config
    _user_thread_mapping_config = config


def load_user_thread_mapping_config_from_dict(config_dict: dict) -> None:
    """Load user_thread_mapping configuration from a dictionary."""
    global _user_thread_mapping_config
    _user_thread_mapping_config = UserThreadMappingConfig(**config_dict)
