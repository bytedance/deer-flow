"""Immutable, bounded evidence projections. References never confer authorization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from deerflow_extension_api.run_evidence import RunPage


@dataclass(frozen=True)
class EvidenceLimits:
    max_events: int = 200
    max_bytes: int = 256 * 1024

    def __post_init__(self) -> None:
        if type(self.max_events) is not int or not 1 <= self.max_events <= 2000:
            raise ValueError("max_events must be between 1 and 2000")
        if type(self.max_bytes) is not int or not 1024 <= self.max_bytes <= 1024 * 1024:
            raise ValueError("max_bytes must be between 1024 and 1048576, including the envelope")


@dataclass(frozen=True)
class CompletedRunSnapshot:
    snapshot_ref: str = ""
    evidence_revision: str = ""
    retention_revision: int = 0
    thread_id: str = ""
    run_id: str = ""
    owner_id: str = ""
    agent_id: str | None = None
    origin: str = "unknown"
    status: str = ""
    stop_reason: str | None = None
    seal_state: str = "partial"
    seal_error: str | None = None
    upper_event_seq: int = 0
    event_count: int = 0
    coverage: str = "lead-journal-v1"
    coverage_limits: tuple[str, ...] = (
        "No complete background subagent, remote MCP, or external side-effect coverage.",
        "Prior conversation and attachment bodies are excluded.",
        "Skill loading and actual content hashes are unknown unless recorded.",
    )
    expires_at: str | None = None
    skill_observations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "coverage_limits", tuple(self.coverage_limits))
        object.__setattr__(self, "skill_observations", tuple(self.skill_observations))


@dataclass(frozen=True)
class CompletedRunEvent:
    """JSON strings keep nested event data immutable and detached from the host.

    ``content_sha256`` hashes the persisted UTF-8 content, before any preview.
    ``content_bytes`` is its persisted byte count, not the JSON envelope size.
    """

    event_id: str = ""
    seq: int = 0
    event_type: str = ""
    category: str = ""
    content_json: str = "null"
    metadata_json: str = "{}"
    content_bytes: int = 0
    content_sha256: str = ""
    truncated: bool = False


@dataclass(frozen=True)
class CompletedRunEventPage:
    items: tuple[CompletedRunEvent, ...] = ()
    next_cursor: str | None = None
    has_more: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))


class CompletedRunEvidenceReader(Protocol):
    async def list_changed_runs(self, *, cursor: str | None = None, limit: int = 200) -> RunPage:
        raise NotImplementedError

    async def get_snapshot(self, *, thread_id: str, run_id: str, limits: EvidenceLimits = EvidenceLimits()) -> CompletedRunSnapshot:
        raise NotImplementedError

    async def read_events(self, *, snapshot_ref: str, cursor: str | None = None, limits: EvidenceLimits = EvidenceLimits()) -> CompletedRunEventPage:
        raise NotImplementedError
