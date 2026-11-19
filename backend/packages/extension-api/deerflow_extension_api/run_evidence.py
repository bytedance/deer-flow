"""Stable, read-only run evidence contracts for extension services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

RUN_EVIDENCE_READER_RESOLVER_KEY = "deerflow_extension_run_evidence_reader_resolver"


class InvalidRunEvidenceCursor(ValueError):
    """The cursor is malformed, unsupported, or belongs to another scope."""


@dataclass(frozen=True)
class RunStatusView:
    """Authoritative lifecycle projection for one visible run."""

    thread_id: str = ""
    run_id: str = ""
    status: str = ""
    created_at: str = ""
    updated_at: str = ""
    error: str | None = None
    stop_reason: str | None = None


@dataclass(frozen=True)
class RunEventView:
    """Persisted evidence envelope; ``seq`` is monotonic within its thread.

    Reader-returned content and metadata are detached from host storage.
    Fields are frozen, but nested payload containers may be modified locally.
    """

    thread_id: str = ""
    run_id: str = ""
    seq: int = 0
    event_type: str = ""
    category: str = ""
    content: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass(frozen=True)
class RunPage:
    """Changed runs plus the opaque cursor represented by this page."""

    items: tuple[RunStatusView, ...] = ()
    next_cursor: str | None = None
    has_more: bool = False


@dataclass(frozen=True)
class RunEventPage:
    """One forward page from a known run's persisted event stream."""

    items: tuple[RunEventView, ...] = ()
    next_after_seq: int | None = None
    has_more: bool = False


class RunEvidenceReader(Protocol):
    """Host-bound evidence reader; implementations never expose writes."""

    async def list_changed_runs(self, *, cursor: str | None, limit: int) -> RunPage:
        """Return visible runs changed after ``cursor`` in stable order.

        Callers persist ``next_cursor`` only after their own output is durable.
        Reusing the input cursor is valid and may replay items. An empty page
        means caught up; unsupported hosts omit the reader instead. Deletions
        do not produce tombstones in this feed. Consumers reconciling a run
        they already know must treat ``get_run_status(...) is None`` as absent.
        """
        raise NotImplementedError("the host does not provide changed-run discovery")

    async def list_run_events(
        self,
        *,
        thread_id: str,
        run_id: str,
        after_seq: int | None,
        limit: int,
    ) -> RunEventPage:
        """Return events with thread-scoped ``seq > after_seq``.

        A missing or invisible run returns an empty page, preventing identity
        probing across the reader's host-bound scope.
        """
        raise NotImplementedError("the host does not provide run-event reading")

    async def get_run_status(self, *, thread_id: str, run_id: str) -> RunStatusView | None:
        """Return authoritative status, or ``None`` when not visible."""
        raise NotImplementedError("the host does not provide run-status reading")


def resolve_run_evidence_reader(request: object) -> RunEvidenceReader | None:
    """Resolve a reader bound to the authenticated request, if supported.

    The resolver receives the request rather than a caller-supplied user ID or
    principal, so the host remains responsible for authentication and scope
    binding. Extensions should use this for user-facing routes; the global
    reader injected into ``ExtensionRuntimeDeps`` is for trusted services.
    Unsupported hosts return ``None``; denied authentication/authorization
    raises ``PermissionError``. Unexpected resolver errors propagate.
    """
    app = getattr(request, "app", None)
    state = getattr(app, "state", None)
    resolver = getattr(state, RUN_EVIDENCE_READER_RESOLVER_KEY, None)
    if not callable(resolver):
        return None
    return resolver(request)


def require_run_evidence_reader(request: object) -> RunEvidenceReader:
    """Return a reader; unsupported hosts raise ``NotImplementedError``.

    Authentication/authorization denial raises ``PermissionError``. Extensions
    may translate these to HTTP 503 and 403 respectively. Resolver failures
    propagate, never falling back to the global reader.
    """
    reader = resolve_run_evidence_reader(request)
    if reader is None:
        raise NotImplementedError("request-scoped run evidence is unavailable")
    return reader
