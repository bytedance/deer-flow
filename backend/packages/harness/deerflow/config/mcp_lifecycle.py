"""Typed shared lifecycle counters persisted alongside the extensions config.

The ``mcpLifecycle`` block is a top-level sibling key of ``mcpServers`` /
``skills`` in ``extensions_config.json``. Every supported writer recomputes and
overwrites it in the same atomic write as the config change, so its counters are
the shared, persisted identity of the MCP resource lifecycle (not the file's
content): ``lifecycleId`` is the lineage of the current trusted baseline,
``configRevision`` counts committed writes, ``serverGenerations`` tracks
per-server lifecycle events with history retained after removal, and
``globalGeneration`` tracks whole-pool lifecycle events such as interceptor
edits.

Counters alone are not a complete identity: a fresh baseline (first
initialization, or recovery from an unverifiable block) restarts them, so a
repaired block can coincide with a version another worker already applied.
``lifecycleId`` is what makes that distinguishable -- it is regenerated only
when a fresh baseline is established, so a worker that missed the intervening
history still sees a different lineage and fails closed.

This module validates the block only; it performs no I/O and owns no locking.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator

#: The only lifecycle schema version this build can interpret. Any other value
#: is unverifiable and must fail closed rather than be treated as "newer, safe".
#: Version 2 added ``lifecycleId``; a version-1 block is therefore unverifiable.
SUPPORTED_SCHEMA_VERSION = 2

#: Every field a *persisted* block must carry explicitly. A truncated or
#: partially written block is not a trusted version and must not be completed
#: with defaults, so persisted parsing requires all of them.
_REQUIRED_PERSISTED_FIELDS = (
    "schemaVersion",
    "lifecycleId",
    "configRevision",
    "globalGeneration",
    "serverGenerations",
)


class McpLifecycleError(ValueError):
    """Raised when a persisted ``mcpLifecycle`` value cannot be validated."""


def new_lifecycle_id() -> str:
    """Return a fresh, opaque lineage id for a newly established baseline."""
    return uuid.uuid4().hex


class McpLifecycle(BaseModel):
    """Validated ``mcpLifecycle`` counters shared by every config writer.

    Strict integer types are used throughout so booleans and other JSON scalars
    are rejected instead of being silently coerced into a counter. The defaults
    exist for *construction* of a new block; :func:`parse_mcp_lifecycle` is the
    stricter entry point used for anything read back from disk.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: StrictInt = Field(default=SUPPORTED_SCHEMA_VERSION, alias="schemaVersion", ge=1)
    lifecycle_id: str = Field(default_factory=new_lifecycle_id, alias="lifecycleId", min_length=1)
    config_revision: StrictInt = Field(default=0, alias="configRevision", ge=0)
    global_generation: StrictInt = Field(default=0, alias="globalGeneration", ge=0)
    server_generations: dict[str, Annotated[StrictInt, Field(ge=0)]] = Field(default_factory=dict, alias="serverGenerations")

    @model_validator(mode="after")
    def _reject_unsupported_schema_version(self) -> McpLifecycle:
        if self.schema_version != SUPPORTED_SCHEMA_VERSION:
            raise ValueError(f"unsupported mcpLifecycle schemaVersion: {self.schema_version}")
        return self


def _safe_validation_summary(exc: ValidationError) -> str:
    """Describe a validation failure without echoing any input value.

    Pydantic's ``str(exc)`` and each error's ``input``/``msg`` can carry the
    offending value, and this block is read from an operator-editable file, so
    only the error locations and types are safe to surface.
    """
    parts = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error.get("loc", ())) or "<root>"
        parts.append(f"{location}:{error.get('type', 'invalid')}")
    return "; ".join(parts) or "invalid"


def parse_mcp_lifecycle(raw: object) -> McpLifecycle | None:
    """Validate a *persisted* ``mcpLifecycle`` value.

    Returns ``None`` only when the value is absent (``None``), which is the
    legacy file case. Any other malformed input raises :class:`McpLifecycleError`
    so callers can fail closed. Unlike direct construction, a persisted block
    must carry every field explicitly: missing fields mean the block cannot be
    trusted as a version.
    """
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise McpLifecycleError(f"mcpLifecycle must be an object, got {type(raw).__name__}")
    missing = [field for field in _REQUIRED_PERSISTED_FIELDS if field not in raw]
    if missing:
        raise McpLifecycleError(f"mcpLifecycle is missing required field(s): {', '.join(missing)}")
    try:
        return McpLifecycle.model_validate(dict(raw))
    except ValidationError as exc:
        raise McpLifecycleError(f"invalid mcpLifecycle block ({_safe_validation_summary(exc)})") from exc


def lifecycle_covers_servers(lifecycle: McpLifecycle, server_names: Iterable[str]) -> bool:
    """Whether *lifecycle* records a generation for every given server.

    Every enabled stdio server must have a ``serverGenerations`` entry: the
    writer always creates one, so a missing entry means the block and the
    effective configuration do not describe the same revision and the block must
    not be trusted.
    """
    return all(name in lifecycle.server_generations for name in server_names)
