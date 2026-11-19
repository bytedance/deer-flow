"""Host-contract service and HTTP surface for the run-postmortem example.

The service depends only on the public ``deerflow-extension-api`` contract: the
host owns evidence storage, authorization and retention; this package owns only
the interpretation of one sealed run, exposed as JSON and Markdown.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from deerflow_extension_api import (
    CompletedRunEvent,
    CompletedRunEvidenceReader,
    CompletedRunSnapshot,
    EvidenceLimits,
    ExtensionPrincipal,
    ExtensionRuntimeDeps,
    HostCapabilityError,
    resolve_principal,
    resolve_run_evidence_reader,
)
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from deerflow_extension_run_postmortem.postmortem import Postmortem, build_postmortem, render_markdown, to_dict

DEFAULT_MAX_EVENTS = 200
MAX_EVENTS = 2000
_STATUS_BY_CODE = {"NOT_GRANTED": 409, "NOT_FOUND": 404, "BAD_REQUEST": 400}


class PostmortemError(RuntimeError):
    """A named, caller-facing failure distinct from host capability errors."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


class PostmortemService:
    """Bounded evidence reader plus the pure derivation.

    ``start`` captures the host capability handle; ``stop`` drops it. Every
    request reads fresh evidence, so the service holds no per-run cache and a
    run that is still being sealed simply yields the evidence available now.
    """

    def __init__(self) -> None:
        self._evidence: CompletedRunEvidenceReader | None = None

    # -- ExtensionService protocol -----------------------------------------

    async def start(self, deps: ExtensionRuntimeDeps) -> None:
        self._evidence = deps.completed_run_evidence
        if self._evidence is None:
            raise PostmortemError(
                "NOT_GRANTED",
                "completed_run_evidence capability missing; grant host_access.evidence in config.yaml plugins",
            )

    async def stop(self) -> None:
        self._evidence = None

    # -- introspection ------------------------------------------------------

    @property
    def ready(self) -> bool:
        return self._evidence is not None

    async def postmortem(self, *, thread_id: str, run_id: str, max_events: int = DEFAULT_MAX_EVENTS) -> Postmortem:
        if not isinstance(max_events, int) or not 1 <= max_events <= MAX_EVENTS:
            raise PostmortemError("BAD_REQUEST", f"max_events must be an integer between 1 and {MAX_EVENTS}")
        evidence = self._require_evidence()
        limits = EvidenceLimits(max_events=max_events)
        snapshot = await evidence.get_snapshot(thread_id=thread_id, run_id=run_id, limits=limits)
        return build_postmortem(snapshot, await self._read_events(evidence, snapshot, limits), max_events=max_events)

    async def _read_events(self, evidence: CompletedRunEvidenceReader, snapshot: CompletedRunSnapshot, limits: EvidenceLimits) -> list[CompletedRunEvent]:
        """Follow the event cursor until the snapshot ends or the cap is met."""
        events: list[CompletedRunEvent] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while len(events) < limits.max_events:
            page = await evidence.read_events(snapshot_ref=snapshot.snapshot_ref, cursor=cursor, limits=limits)
            events.extend(page.items)
            if not page.has_more or page.next_cursor is None:
                break
            if page.next_cursor in seen_cursors:
                # A host that repeats a cursor must not spin the request.
                break
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor
        return events[: limits.max_events]

    def _require_evidence(self) -> CompletedRunEvidenceReader:
        if self._evidence is None:
            raise PostmortemError("NOT_GRANTED", "service is not started or the evidence capability is missing")
        return self._evidence


def build_router(service: PostmortemService):
    """Expose the report as JSON and as a shareable Markdown document."""
    router = APIRouter(prefix="/api/extension-run-postmortem", tags=["run-postmortem"])

    def _principal(request: Request) -> ExtensionPrincipal:
        principal = resolve_principal(request)
        if principal is None:
            raise HTTPException(status_code=401, detail="authentication required")
        return principal

    async def _require_visible_run(request: Request, thread_id: str, run_id: str) -> None:
        """Confirm the anchor is visible to the caller when the host offers it.

        The evidence handle is allowlist-scoped for the plugin, not scoped to the
        requesting user, so the route also compares the snapshot owner below.
        """
        try:
            reader = resolve_run_evidence_reader(request)
            if reader is None:
                return
            status = await reader.get_run_status(thread_id=thread_id, run_id=run_id)
        except NotImplementedError:
            return
        if status is None:
            raise PostmortemError("NOT_FOUND", f"run {run_id} is not visible to this caller")

    def _guard(coro: Awaitable[Any]) -> Awaitable[Any]:
        async def run():
            try:
                return await coro
            except PostmortemError as exc:
                raise HTTPException(status_code=_STATUS_BY_CODE.get(exc.code, 500), detail=str(exc)) from exc
            except PermissionError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
            except HostCapabilityError as exc:
                status = 404 if exc.code in {"NOT_FOUND", "NOT_FOUND_OR_FORBIDDEN"} else 409
                raise HTTPException(status_code=status, detail=str(exc)) from exc

        return run()

    async def _report(request: Request, thread_id: str, run_id: str, max_events: int) -> Postmortem:
        principal = _principal(request)
        await _require_visible_run(request, thread_id, run_id)
        postmortem = await service.postmortem(thread_id=thread_id, run_id=run_id, max_events=max_events)
        if postmortem.owner_id != principal.user_id:
            # Never disclose whether another user's run exists.
            raise PostmortemError("NOT_FOUND", f"run {run_id} is not visible to this caller")
        return postmortem

    @router.get("/health")
    async def health() -> dict[str, Any]:
        return {"ready": service.ready, "max_events": MAX_EVENTS}

    @router.get("/runs/{thread_id}/{run_id}")
    async def report(request: Request, thread_id: str, run_id: str, max_events: int = Query(DEFAULT_MAX_EVENTS, ge=1, le=MAX_EVENTS)) -> dict[str, Any]:
        return to_dict(await _guard(_report(request, thread_id, run_id, max_events)))

    @router.get("/runs/{thread_id}/{run_id}/markdown", response_class=PlainTextResponse)
    async def report_markdown(request: Request, thread_id: str, run_id: str, max_events: int = Query(DEFAULT_MAX_EVENTS, ge=1, le=MAX_EVENTS)) -> PlainTextResponse:
        postmortem = await _guard(_report(request, thread_id, run_id, max_events))
        return PlainTextResponse(render_markdown(postmortem), media_type="text/markdown")

    return router


__all__ = ["DEFAULT_MAX_EVENTS", "MAX_EVENTS", "PostmortemError", "PostmortemService", "build_router"]
