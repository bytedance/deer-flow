"""Shared data models for the insights subsystem.

All models are Pydantic with ``frozen=True`` for immutability (per project
coding-style rules). These are value objects used across analytics,
improvement, knowledge extraction, and memory integration modules.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FeedbackTrend(BaseModel, frozen=True):
    """Aggregated feedback metrics for a single agent over a time window."""

    agent_name: str
    positive_count: int
    negative_count: int
    positive_ratio: float
    trend_direction: str  # "improving" | "stable" | "declining"
    window_days: int
    top_complaints: list[tuple[str, int]] = Field(default_factory=list)
    computed_at: datetime = Field(default_factory=datetime.utcnow)


class ClosureMetrics(BaseModel, frozen=True):
    """Aggregated closure ticket metrics over a time window."""

    open_count: int
    closed_count: int
    overdue_count: int
    avg_resolution_hours: float | None = None
    sla_compliance_rate: float | None = None
    verification_pass_rate: float | None = None
    window_days: int
    computed_at: datetime = Field(default_factory=datetime.utcnow)


class ImprovementEvidence(BaseModel, frozen=True):
    """Supporting evidence for an improvement suggestion."""

    feedback_ids: list[str] = Field(default_factory=list)
    closure_ticket_ids: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class ImprovementSuggestion(BaseModel, frozen=True):
    """A ranked improvement recommendation generated from analytics."""

    id: str
    target: str  # "agent:<name>" | "kb" | "tool:<name>"
    issue_pattern: str
    suggestion: str
    confidence: float
    status: str = "pending"  # pending | accepted | applied | dismissed
    evidence: ImprovementEvidence = Field(default_factory=ImprovementEvidence)
    applied_note: str | None = None
    dismiss_reason: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class KBCandidate(BaseModel, frozen=True):
    """A knowledge base document candidate extracted from a closure ticket."""

    ticket_id: str
    tenant_id: str
    title: str
    body: str
    metadata_tags: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending_review"  # pending_review | approved | dismissed
    dismiss_reason: str | None = None
    source_type: str = "closure_resolution"
    confidence: float = 0.8
    created_at: datetime = Field(default_factory=datetime.utcnow)


class InsightAlert(BaseModel, frozen=True):
    """An immediate alert signal from cluster detection."""

    agent_name: str
    alert_type: str  # "negative_cluster"
    negative_count: int
    time_window_minutes: int
    contributing_feedback_ids: list[str] = Field(default_factory=list)
    triggered_at: datetime = Field(default_factory=datetime.utcnow)
