"""Pydantic DTOs and metadata schemas for the closed-loop subsystem.

Why discriminated unions?

The ``extra_metadata`` JSON column is intentionally free-form so each source
type can attach its own context (diagnosis findings, report parameters, manual
notes, etc.). To avoid silent rot we still validate the metadata in the
service layer using a discriminated union keyed by ``source_type``. Unknown
fields are *allowed* (forward-compatible) but the keys we already know about
must have the right shape.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ClosureSourceType(enum.StrEnum):
    DIAGNOSIS = "diagnosis"
    REPORT = "report"
    INSPECTION = "inspection"
    MANUAL = "manual"
    CHAT = "chat"


class ClosurePriority(enum.StrEnum):
    URGENT = "urgent"
    IMPORTANT = "important"
    NORMAL = "normal"
    OBSERVE = "observe"


# --- discriminated metadata schemas ----------------------------------------


class _BaseMeta(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)


class DiagnosisMetadata(_BaseMeta):
    source_type: Literal[ClosureSourceType.DIAGNOSIS] = ClosureSourceType.DIAGNOSIS
    findings: list[str] | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    fault_code: str | None = None


class ReportMetadata(_BaseMeta):
    source_type: Literal[ClosureSourceType.REPORT] = ClosureSourceType.REPORT
    report_run_id: str | None = None
    report_template_id: str | None = None
    period: str | None = None  # daily / weekly / monthly / custom


class InspectionMetadata(_BaseMeta):
    source_type: Literal[ClosureSourceType.INSPECTION] = ClosureSourceType.INSPECTION
    inspection_round: str | None = None
    inspector_id: str | None = None


class ManualMetadata(_BaseMeta):
    source_type: Literal[ClosureSourceType.MANUAL] = ClosureSourceType.MANUAL
    note: str | None = None


class ChatMetadata(_BaseMeta):
    source_type: Literal[ClosureSourceType.CHAT] = ClosureSourceType.CHAT
    note: str | None = None


ClosureMetadata = Annotated[
    DiagnosisMetadata | ReportMetadata | InspectionMetadata | ManualMetadata | ChatMetadata,
    Field(discriminator="source_type"),
]


# --- request / response DTOs -----------------------------------------------


class CreateTicketRequest(BaseModel):
    """Body of ``POST /api/closure/tickets`` and the ``create_closure_ticket`` tool."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    priority: ClosurePriority = ClosurePriority.NORMAL
    severity: str | None = Field(default=None, max_length=16)

    device_id: str | None = Field(default=None, max_length=64)
    device_name: str | None = Field(default=None, max_length=255)

    source_type: ClosureSourceType = ClosureSourceType.MANUAL
    source_run_id: str | None = Field(default=None, max_length=64)
    source_thread_id: str | None = Field(default=None, max_length=64)

    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="before")
    @classmethod
    def _normalize_metadata(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("metadata must be a dict")
        return value


class UpdateTicketRequest(BaseModel):
    """Body of ``PATCH /api/closure/tickets/{id}``.

    ``status`` is intentionally absent -- status changes go through
    ``POST /transition``. Trying to update ``status`` via this DTO is rejected
    by the service layer with a descriptive error.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    priority: ClosurePriority | None = None
    severity: str | None = Field(default=None, max_length=16)
    assignee_id: str | None = Field(default=None, max_length=64)
    device_name: str | None = Field(default=None, max_length=255)
    metadata_patch: dict[str, Any] | None = None


class TransitionRequest(BaseModel):
    """Body of ``POST /api/closure/tickets/{id}/transition``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ListTicketsFilter(BaseModel):
    """Query params for the listing endpoint and the ``list_closure_tickets`` tool."""

    model_config = ConfigDict(str_strip_whitespace=True)

    device_id: str | None = None
    status: str | None = None
    statuses: list[str] | None = None
    assignee_id: str | None = None
    created_by: str | None = None
    source_type: ClosureSourceType | None = None
    source_run_id: str | None = None
    priority: ClosurePriority | None = None
    is_overdue: bool | None = None

    created_at_gte: datetime | None = None
    created_at_lt: datetime | None = None
    closed_at_gte: datetime | None = None
    closed_at_lt: datetime | None = None
    due_at_gte: datetime | None = None
    due_at_lt: datetime | None = None

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)
    order_by: str = Field(default="created_at")
    order_desc: bool = True


# --- read models -----------------------------------------------------------


class TicketResponse(BaseModel):
    """Read DTO returned by every ticket-shaped endpoint and tool."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str
    tenant_id: str
    title: str
    description: str | None = None
    status: str
    priority: str
    severity: str | None = None
    device_id: str | None = None
    device_name: str | None = None
    created_by: str
    assignee_id: str | None = None
    verifier_id: str | None = None
    source_type: str
    source_run_id: str | None = None
    source_thread_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    due_at: datetime | None = None
    is_overdue: bool = False
    created_at: datetime
    updated_at: datetime
    assigned_at: datetime | None = None
    started_at: datetime | None = None
    submitted_at: datetime | None = None
    closed_at: datetime | None = None


class TicketEventDTO(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: str
    ticket_id: str
    tenant_id: str
    action: str
    from_status: str | None = None
    to_status: str | None = None
    actor_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class PageMeta(BaseModel):
    total: int
    page: int
    page_size: int


class TicketListResponse(BaseModel):
    items: list[TicketResponse]
    meta: PageMeta


class NotificationsSummary(BaseModel):
    """Aggregate response for the notifications/summary endpoint."""

    open_count: int = 0
    overdue_count: int = 0
    pending_verification_count: int = 0
    assigned_to_me_count: int = 0
