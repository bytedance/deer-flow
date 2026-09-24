"""Typed shared lifecycle counters persisted alongside the extensions config.

The ``mcpLifecycle`` block is a top-level sibling key of ``mcpServers`` /
``skills`` in ``extensions_config.json``. Every supported writer recomputes and
overwrites it in the same atomic write as the config change, so its counters are
the shared, persisted identity of the MCP resource lifecycle (not the file's
content): ``configRevision`` counts committed writes, ``serverGenerations``
tracks per-server lifecycle events with history retained after removal, and
``globalGeneration`` tracks whole-pool lifecycle events such as interceptor
edits.

This module validates the block only; it performs no I/O and owns no locking.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator

#: The only lifecycle schema version this build can interpret. Any other value
#: is unverifiable and must fail closed rather than be treated as "newer, safe".
SUPPORTED_SCHEMA_VERSION = 1


class McpLifecycleError(ValueError):
    """Raised when a persisted ``mcpLifecycle`` value cannot be validated."""


class McpLifecycle(BaseModel):
    """Validated ``mcpLifecycle`` counters shared by every config writer.

    Strict integer types are used throughout so booleans and other JSON scalars
    are rejected instead of being silently coerced into a counter.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: StrictInt = Field(default=1, alias="schemaVersion", ge=1)
    config_revision: StrictInt = Field(default=0, alias="configRevision", ge=0)
    global_generation: StrictInt = Field(default=0, alias="globalGeneration", ge=0)
    server_generations: dict[str, Annotated[StrictInt, Field(ge=0)]] = Field(default_factory=dict, alias="serverGenerations")

    @model_validator(mode="after")
    def _reject_unsupported_schema_version(self) -> McpLifecycle:
        if self.schema_version != SUPPORTED_SCHEMA_VERSION:
            raise ValueError(f"unsupported mcpLifecycle schemaVersion: {self.schema_version}")
        return self


def parse_mcp_lifecycle(raw: object) -> McpLifecycle | None:
    """Validate a persisted ``mcpLifecycle`` value.

    Returns ``None`` only when the value is absent (``None``), which is the
    legacy file case. Any other malformed input raises :class:`McpLifecycleError`
    so callers can fail closed.
    """
    if raw is None:
        return None
    if isinstance(raw, Mapping):
        try:
            return McpLifecycle.model_validate(dict(raw))
        except ValidationError as exc:
            raise McpLifecycleError(f"invalid mcpLifecycle block: {exc}") from exc
    raise McpLifecycleError(f"mcpLifecycle must be an object, got {type(raw).__name__}")
