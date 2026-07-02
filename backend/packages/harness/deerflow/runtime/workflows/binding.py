"""Deterministic workflow-to-runtime binding helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class WorkflowBindingStatus(StrEnum):
    """Binding decision status for workflow intake."""

    resolved = "resolved"
    ambiguous = "ambiguous"
    unresolved = "unresolved"


@dataclass(frozen=True)
class WorkflowBindingCandidate:
    """One possible runtime binding target."""

    thread_id: str | None = None
    run_id: str | None = None
    checkpoint_ns: str | None = None
    checkpoint_id: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "WorkflowBindingCandidate":
        return cls(
            thread_id=_clean_ref(value.get("thread_id")),
            run_id=_clean_ref(value.get("run_id")),
            checkpoint_ns=_clean_ref(value.get("checkpoint_ns"), allow_empty=True),
            checkpoint_id=_clean_ref(value.get("checkpoint_id")),
            reason=_clean_ref(value.get("reason")),
            metadata=dict(value.get("metadata") or {}),
        )

    def identity(self) -> tuple[str | None, str | None, str | None, str | None]:
        return (self.thread_id, self.run_id, self.checkpoint_ns, self.checkpoint_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "run_id": self.run_id,
            "checkpoint_ns": self.checkpoint_ns,
            "checkpoint_id": self.checkpoint_id,
            "reason": self.reason,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class WorkflowBindingDecision:
    """Deterministic binding result persisted with workflow metadata."""

    status: WorkflowBindingStatus
    reason: str
    thread_id: str | None = None
    run_id: str | None = None
    checkpoint_ns: str | None = None
    checkpoint_id: str | None = None
    candidates: tuple[WorkflowBindingCandidate, ...] = ()

    def to_metadata(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "thread_id": self.thread_id,
            "run_id": self.run_id,
            "checkpoint_ns": self.checkpoint_ns,
            "checkpoint_id": self.checkpoint_id,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def _clean_ref(value: Any, *, allow_empty: bool = False) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if allow_empty and text == "":
        return ""
    return text or None


def _candidate_from_explicit_refs(
    *,
    explicit_thread_id: str | None = None,
    explicit_run_id: str | None = None,
    explicit_checkpoint_ns: str | None = None,
    explicit_checkpoint_id: str | None = None,
) -> WorkflowBindingCandidate | None:
    candidate = WorkflowBindingCandidate(
        thread_id=_clean_ref(explicit_thread_id),
        run_id=_clean_ref(explicit_run_id),
        checkpoint_ns=_clean_ref(explicit_checkpoint_ns, allow_empty=True),
        checkpoint_id=_clean_ref(explicit_checkpoint_id),
        reason="explicit_reference",
    )
    return candidate if any(candidate.identity()) else None


def _dedupe_candidates(candidates: list[WorkflowBindingCandidate]) -> tuple[WorkflowBindingCandidate, ...]:
    seen: set[tuple[str | None, str | None, str | None, str | None]] = set()
    deduped: list[WorkflowBindingCandidate] = []
    for candidate in candidates:
        identity = candidate.identity()
        if not any(identity) or identity in seen:
            continue
        seen.add(identity)
        deduped.append(candidate)
    return tuple(deduped)


def resolve_workflow_binding(
    *,
    explicit_thread_id: str | None = None,
    explicit_run_id: str | None = None,
    explicit_checkpoint_ns: str | None = None,
    explicit_checkpoint_id: str | None = None,
    candidate_bindings: list[dict[str, Any] | WorkflowBindingCandidate] | None = None,
) -> WorkflowBindingDecision:
    """Resolve a workflow runtime binding without guessing.

    Explicit references win because they came from the API route, user action,
    or adapter command. Without explicit refs, exactly one candidate is
    deterministic. Multiple distinct candidates are persisted as ambiguity for
    a human or agent to resolve later.
    """
    explicit = _candidate_from_explicit_refs(
        explicit_thread_id=explicit_thread_id,
        explicit_run_id=explicit_run_id,
        explicit_checkpoint_ns=explicit_checkpoint_ns,
        explicit_checkpoint_id=explicit_checkpoint_id,
    )
    if explicit is not None:
        return WorkflowBindingDecision(
            status=WorkflowBindingStatus.resolved,
            reason="explicit_reference",
            thread_id=explicit.thread_id,
            run_id=explicit.run_id,
            checkpoint_ns=explicit.checkpoint_ns,
            checkpoint_id=explicit.checkpoint_id,
            candidates=(explicit,),
        )

    normalized_candidates: list[WorkflowBindingCandidate] = []
    for item in candidate_bindings or []:
        if isinstance(item, WorkflowBindingCandidate):
            normalized_candidates.append(item)
        else:
            normalized_candidates.append(WorkflowBindingCandidate.from_mapping(item))
    candidates = _dedupe_candidates(normalized_candidates)
    if not candidates:
        return WorkflowBindingDecision(status=WorkflowBindingStatus.unresolved, reason="no_candidate")
    if len(candidates) == 1:
        candidate = candidates[0]
        return WorkflowBindingDecision(
            status=WorkflowBindingStatus.resolved,
            reason=candidate.reason or "single_candidate",
            thread_id=candidate.thread_id,
            run_id=candidate.run_id,
            checkpoint_ns=candidate.checkpoint_ns,
            checkpoint_id=candidate.checkpoint_id,
            candidates=candidates,
        )
    return WorkflowBindingDecision(
        status=WorkflowBindingStatus.ambiguous,
        reason="multiple_candidates",
        candidates=candidates,
    )
