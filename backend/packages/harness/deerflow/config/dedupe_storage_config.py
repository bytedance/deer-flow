"""Configuration for inbound webhook dedupe storage.

Controls where the ChannelManager's inbound dedupe state lives. See issue #4120
(cross-pod webhook dedupe). The default ``auto`` reuses the Postgres application
database whenever database.backend='postgres', otherwise an in-process memory
store. ``memory`` is per-pod and not shared across replicas; ``postgres`` shares
state across pods.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from deerflow.config.reload_boundary import format_field_description


class DedupeStorageBackend(StrEnum):
    AUTO = "auto"
    MEMORY = "memory"
    POSTGRES = "postgres"


class DedupeStorageConfig(BaseModel):
    """Where inbound webhook dedupe state lives."""

    backend: DedupeStorageBackend = Field(
        default=DedupeStorageBackend.AUTO,
        description=format_field_description(
            "dedupe_storage",
            field_doc=(
                "Storage backend for inbound webhook dedupe state. "
                "'auto' uses the Postgres application database whenever database.backend='postgres', "
                "otherwise an in-process memory store (single-pod). "
                "'memory' forces the in-process store (per-pod; not shared across replicas). "
                "'postgres' shares dedupe state across pods via the application database. "
                "See issue #4120."
            ),
        ),
    )
