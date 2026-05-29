"""Provenance tracking for integration data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Provenance:
    """Data origin and transformation tracking."""

    source_system_key: str
    source_system_type: str
    capability_key: str
    fetched_at: datetime
    query_params: dict[str, Any] = field(default_factory=dict)
    transform_steps: tuple[str, ...] = ()
    source_metadata: dict[str, Any] = field(default_factory=dict)

    def with_transform(self, step: str) -> "Provenance":
        """Return new Provenance with added transform step."""
        return Provenance(
            source_system_key=self.source_system_key,
            source_system_type=self.source_system_type,
            capability_key=self.capability_key,
            fetched_at=self.fetched_at,
            query_params=self.query_params,
            transform_steps=self.transform_steps + (step,),
            source_metadata=self.source_metadata,
        )


@dataclass(frozen=True)
class PartialFailure:
    """Record of a failed enrichment or fallback attempt."""

    system_key: str
    capability_key: str
    error_type: str
    error_message: str
    timestamp: datetime
