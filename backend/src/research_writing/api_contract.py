"""Schema contract governance for research runtime API."""

from __future__ import annotations

from dataclasses import dataclass

RESEARCH_API_SCHEMA_VERSION = "deerflow.research.v1"

# v0 clients can still call v1 endpoints; server advertises migration metadata.
_LEGACY_SCHEMA_MIGRATIONS: dict[str, str] = {
    "deerflow.research.v0": RESEARCH_API_SCHEMA_VERSION,
}


class UnsupportedResearchSchemaVersionError(ValueError):
    """Raised when client requests an unknown research schema version."""


@dataclass(frozen=True)
class ResearchSchemaContract:
    """Negotiated schema contract for one request."""

    requested_version: str
    response_version: str
    migrated_from: str | None = None
    migration_applied: bool = False


def _normalize_version(value: str | None) -> str:
    normalized = (value or "").strip()
    if not normalized:
        return RESEARCH_API_SCHEMA_VERSION
    return normalized


def resolve_schema_contract(requested_version: str | None) -> ResearchSchemaContract:
    """Resolve and validate requested schema version."""
    requested = _normalize_version(requested_version)
    if requested == RESEARCH_API_SCHEMA_VERSION:
        return ResearchSchemaContract(
            requested_version=requested,
            response_version=RESEARCH_API_SCHEMA_VERSION,
            migrated_from=None,
            migration_applied=False,
        )
    target = _LEGACY_SCHEMA_MIGRATIONS.get(requested)
    if target is not None:
        return ResearchSchemaContract(
            requested_version=requested,
            response_version=target,
            migrated_from=requested,
            migration_applied=True,
        )
    raise UnsupportedResearchSchemaVersionError(
        f"Unsupported research schema version: {requested}. "
        f"Supported: {RESEARCH_API_SCHEMA_VERSION}, {', '.join(sorted(_LEGACY_SCHEMA_MIGRATIONS.keys()))}"
    )

