"""Persisted record models — what ``repository.py`` actually reads/writes.

§6 of the design lists three conceptual entities:

  - ReportTemplate         → current metadata + pointer to active version
  - ReportTemplateVersion  → immutable snapshot per published version
  - ReportRun              → execution-time index, attached to a thread

These are the **persistence** views. The DSL itself (``schema.py``) is
embedded inside ``ReportTemplateVersion.dsl``; persistence layer never
re-parses DSL — that's the validator's job before save.

All timestamps are ISO 8601 with timezone (§7.1.5 V2 migration constraint).
All ID fields follow ULID-style patterns enforced by the validators below.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from deerflow.shared.status import RunStatus

# ---------------------------------------------------------------------------
# Error code constants — standardized traceability failure semantics
# ---------------------------------------------------------------------------


class ReportRunErrorCode:
    """Standardized error code prefixes for the template→run→artifact chain.

    These are set in ``ReportRunRecord.error_code`` by runtime tools when the
    corresponding failure occurs. The UI maps these prefixes to user-facing messages.
    """

    TEMPLATE_UNAVAILABLE = "TEMPLATE_UNAVAILABLE"
    KB_UNAVAILABLE = "KB_UNAVAILABLE"
    RUN_INTERRUPTED = "RUN_INTERRUPTED"
    DATA_STEP_FAILED = "DATA_STEP_FAILED"


# ---------------------------------------------------------------------------
# ID validation (§7.1.4)
# ---------------------------------------------------------------------------

_TEMPLATE_ID_RE = re.compile(r"^tpl_[A-Z0-9]{20,32}$")
_REPORT_RUN_ID_RE = re.compile(r"^rr_[A-Z0-9]{20,32}$")
_USER_TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def validate_template_id(value: str) -> str:
    if not _TEMPLATE_ID_RE.fullmatch(value):
        raise ValueError(
            f"template_id {value!r} must match {_TEMPLATE_ID_RE.pattern!r} (ULID-style)"
        )
    return value


def validate_report_run_id(value: str) -> str:
    if not _REPORT_RUN_ID_RE.fullmatch(value):
        raise ValueError(
            f"report_run_id {value!r} must match {_REPORT_RUN_ID_RE.pattern!r}"
        )
    return value


def validate_user_tenant_id(value: str) -> str:
    if not _USER_TENANT_ID_RE.fullmatch(value):
        raise ValueError(
            f"id {value!r} must match {_USER_TENANT_ID_RE.pattern!r} (max 64 chars, alphanum/_-)"
        )
    return value


def now_iso() -> str:
    """Generate an ISO-8601 timestamp with timezone."""
    return datetime.now(timezone.utc).isoformat()


def iso_to_epoch(iso_str: str) -> float:
    """Parse an ISO-8601 timestamp into a Unix epoch (UTC).

    Raises ``ValueError`` if the string is not parsable. Naïve datetimes
    are assumed to be UTC.
    """
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


# ---------------------------------------------------------------------------
# ID generators (Crockford base32 ULID-style — 96 random bits)
# ---------------------------------------------------------------------------

_ULID_ALPHA = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _gen_ulid_like(prefix: str, length: int = 24) -> str:
    n = secrets.randbits(length * 5)
    out = []
    for _ in range(length):
        out.append(_ULID_ALPHA[n & 0x1F])
        n >>= 5
    return f"{prefix}_" + "".join(reversed(out))


def new_template_id() -> str:
    return _gen_ulid_like("tpl")


def new_report_run_id() -> str:
    return _gen_ulid_like("rr")


def builtin_version_ref(dsl_version: str) -> str:
    """Build a ``template_version_ref`` string for a builtin template.

    Per design §6.2 the ref must combine the runtime DSL version with a
    short git SHA so a ReportRun can be replayed against the exact code
    that produced it. Returns ``"{sha[:8]}-{dsl_version}"`` when the working
    tree is a git checkout, falling back to ``"builtin-{dsl_version}"``
    otherwise (CI / installed wheels). Result is cached after the first call.
    """
    sha = _resolve_git_sha()
    if not sha or len(sha) < 8:
        return f"builtin-{dsl_version}"
    return f"{sha[:8]}-{dsl_version}"


_cached_git_sha: str | None = None
_git_sha_resolved: bool = False


def _resolve_git_sha() -> str | None:
    global _cached_git_sha, _git_sha_resolved
    if _git_sha_resolved:
        return _cached_git_sha
    import os
    import subprocess
    from pathlib import Path

    sha = os.environ.get("DEER_FLOW_GIT_SHA")
    if not sha:
        try:
            cwd = Path(__file__).resolve().parent
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if result.returncode == 0:
                sha = result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            sha = None
    _cached_git_sha = sha
    _git_sha_resolved = True
    return _cached_git_sha


# ---------------------------------------------------------------------------
# ReportTemplate — metadata.json
# ---------------------------------------------------------------------------

Visibility = Literal["private", "tenant", "builtin"]
TemplateStatus = Literal["draft", "published", "archived"]


class ReportTemplateRecord(BaseModel):
    """Current state of a single template — written to ``template.json``."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    display_name: str
    description: str = ""
    owner_user_id: str
    tenant_id: str
    visibility: Visibility = "private"
    status: TemplateStatus = "draft"
    current_version: int = 0
    dsl_version: str = "1"
    tags: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    etag: str

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        return validate_template_id(v)

    @field_validator("owner_user_id", "tenant_id")
    @classmethod
    def _check_owner_tenant(cls, v: str) -> str:
        return validate_user_tenant_id(v)


# ---------------------------------------------------------------------------
# ReportTemplateVersion — versions/v{N}.json
# ---------------------------------------------------------------------------


class ReportTemplateVersionRecord(BaseModel):
    """Immutable snapshot of a published version."""

    model_config = ConfigDict(extra="forbid")

    template_id: str
    version: int = Field(ge=0)
    dsl: dict[str, Any]
    dsl_yaml: str  # original YAML text preserving comments
    checksum: str  # sha256 of dsl_yaml
    source_template_id: str | None = None
    source_template_version: int | None = None
    created_by: str
    created_at: str
    changelog: str = ""

    @field_validator("template_id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        return validate_template_id(v)

    @field_validator("source_template_id")
    @classmethod
    def _check_src_id(cls, v: str | None) -> str | None:
        return None if v is None else validate_template_id(v)

    @field_validator("created_by")
    @classmethod
    def _check_creator(cls, v: str) -> str:
        return validate_user_tenant_id(v)


# ---------------------------------------------------------------------------
# ReportRun — runs/{id}.json
# ---------------------------------------------------------------------------

# ISSUE-02: RunStatus now imported from shared/status.py; "canceled" → "cancelled" spelling unified


class ReportRunRecord(BaseModel):
    """Index entry for a single template execution."""

    model_config = ConfigDict(extra="forbid")

    id: str
    template_id: str
    template_version: int | None = None  # None for builtin templates (use template_version_ref)
    template_version_ref: str | None = None
    thread_id: str
    run_id: str
    user_id: str
    tenant_id: str
    idempotency_key: str | None = None
    status: RunStatus = "pending"
    parameters_summary: dict[str, Any] = Field(default_factory=dict)
    parameters_path: str | None = None
    report_payload_path: str | None = None
    artifact_paths: dict[str, str | None] = Field(default_factory=dict)
    pdf_skipped_reason: str | None = None
    data_snapshot_paths: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    knowledge_sources: list[dict[str, Any]] = Field(default_factory=list)
    trigger_type: str = "manual"
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None

    @field_validator("id")
    @classmethod
    def _check_run_id(cls, v: str) -> str:
        return validate_report_run_id(v)

    @field_validator("template_id")
    @classmethod
    def _check_template_id(cls, v: str) -> str:
        return validate_template_id(v)

    @field_validator("user_id", "tenant_id")
    @classmethod
    def _check_owner(cls, v: str) -> str:
        return validate_user_tenant_id(v)


# ---------------------------------------------------------------------------
# Index — index.json (per user/tenant)
# ---------------------------------------------------------------------------


class IndexEntry(BaseModel):
    """One row in the user/tenant ``index.json``."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    display_name: str
    visibility: Visibility
    status: TemplateStatus
    current_version: int
    tags: list[str] = Field(default_factory=list)
    updated_at: str


class TemplateIndex(BaseModel):
    """``index.json`` — the listing data source for one user or tenant."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1"
    updated_at: str
    templates: list[IndexEntry] = Field(default_factory=list)
