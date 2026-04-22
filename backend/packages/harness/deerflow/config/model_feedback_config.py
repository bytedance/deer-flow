"""Configuration for per-model usage / feedback counters (``model_feedback``)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ModelFeedbackBackendType = Literal["memory", "sqlite", "postgres", "mongo", "redis"]


class ModelFeedbackConfig(BaseModel):
    """Backend for aggregated model run and feedback statistics."""

    enabled: bool = Field(default=False, description="When false, counters are not recorded and API returns disabled.")
    type: ModelFeedbackBackendType = Field(
        description="Stats backend: memory (ephemeral), sqlite, postgres, mongo, or redis.",
    )
    connection_string: str | None = Field(
        default=None,
        description="sqlite path or ':memory:'; postgres DSN; mongo URI; redis URL (not used for type memory).",
    )
    postgres_schema: str | None = Field(
        default=None,
        description="Optional Postgres schema for the stats table (created if missing when permitted).",
    )
    table: str = Field(
        default="model_usage_stats",
        description="SQL table name or default Mongo collection when mongo_collection is unset.",
    )
    mongo_collection: str | None = Field(
        default=None,
        description="MongoDB collection name; defaults to ``table`` when omitted.",
    )
    mongo_database: str = Field(
        default="deerflow",
        description="MongoDB database name.",
    )
    redis_key_prefix: str = Field(
        default="deerflow:model_feedback",
        description="Redis key prefix for per-model counter hashes.",
    )
