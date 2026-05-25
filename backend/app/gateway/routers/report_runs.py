"""REST API for ReportRun history (Phase 5 — §12.3 of the design).

Endpoints:

    GET    /api/report-runs                      list runs visible to caller
    GET    /api/report-runs/{report_run_id}      one run record
    GET    /api/report-runs/{report_run_id}/payload   the report_payload.json content

Listings combine the caller's private + tenant runs. ``builtin`` templates can
be referenced but they have no ReportRun records — runs are always owned by a
specific user. We filter by template_id query-param when present.

Note on ``POST /{rid}/cancel``: not implemented in MVP per design §8.3. While
the runtime is LLM-driven and bound to an existing thread/run, cancellation
flows through the thread-run cancel endpoint, not here. Add this route only
when an independent ReportRun JobRunner exists (post-MVP, see design §3.3).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from deerflow.report_templates.records import validate_report_run_id
from deerflow.report_templates.repository import (
    Scope,
    TemplateNotFoundError,
)
from deerflow.report_templates.service import get_repository

# Reuse the principal helper from the templates router to keep auth resolution
# in one place.
from app.gateway.routers.report_templates import _principal_from_request

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/report-runs", tags=["report-runs"])


def _scopes_for_listing(principal):
    yield Scope.private(principal.user_id)
    yield Scope.tenant(principal.tenant_id)


def _count_data_files(run) -> int:
    """Count JSON files under ``{run_output_dir}/data/`` for a run record."""
    for path_attr in ("parameters_path", "report_payload_path"):
        path_str = getattr(run, path_attr, None)
        if path_str:
            data_dir = Path(path_str).parent / "data"
            try:
                if data_dir.is_dir():
                    return sum(1 for f in data_dir.iterdir() if f.suffix == ".json")
            except OSError:
                return 0
    return 0


def _list_data_files(run) -> list[dict[str, str]]:
    """List JSON files under ``{run_output_dir}/data/`` with name + download path."""
    files: list[dict[str, str]] = []
    for path_attr in ("parameters_path", "report_payload_path"):
        path_str = getattr(run, path_attr, None)
        if path_str:
            data_dir = Path(path_str).parent / "data"
            try:
                if data_dir.is_dir():
                    for f in sorted(data_dir.iterdir()):
                        if f.suffix == ".json":
                            files.append({"name": f.name, "path": str(f)})
                    return files
            except OSError:
                return []
    return []


@router.get("", summary="List report runs visible to current user")
async def list_report_runs(
    request: Request,
    template_id: str | None = Query(default=None),
    thread_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
):
    principal = _principal_from_request(request)
    repo = get_repository()
    runs: list[dict] = []
    for scope in _scopes_for_listing(principal):
        try:
            templates = repo.list_templates(scope)
        except Exception:  # noqa: BLE001
            continue
        for entry in templates:
            if template_id and entry.id != template_id:
                continue
            try:
                step_runs = repo.list_report_runs(scope, entry.id)
            except Exception:  # noqa: BLE001
                continue
            for r in step_runs:
                if r.user_id != principal.user_id and not principal.is_superadmin:
                    continue
                if thread_id and r.thread_id != thread_id:
                    continue
                runs.append({**r.model_dump(), "data_file_count": _count_data_files(r)})
    runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return {"runs": runs[:limit]}


@router.get("/{report_run_id}", summary="Get a single report run record")
async def get_report_run(report_run_id: str, request: Request):
    try:
        validate_report_run_id(report_run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    principal = _principal_from_request(request)
    repo = get_repository()
    for scope in _scopes_for_listing(principal):
        try:
            templates = repo.list_templates(scope)
        except Exception:  # noqa: BLE001
            continue
        for entry in templates:
            run = repo.get_report_run(scope, entry.id, report_run_id)
            if run is None:
                continue
            if run.user_id != principal.user_id and not principal.is_superadmin:
                raise HTTPException(status_code=403, detail="not your report run")
            return {"run": {**run.model_dump(), "data_files": _list_data_files(run)}}
    raise HTTPException(status_code=404, detail=f"report_run {report_run_id!r} not found")


@router.get("/{report_run_id}/payload", summary="Read the assembled report_payload.json")
async def get_report_payload(report_run_id: str, request: Request):
    try:
        validate_report_run_id(report_run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    principal = _principal_from_request(request)
    repo = get_repository()
    for scope in _scopes_for_listing(principal):
        try:
            templates = repo.list_templates(scope)
        except Exception:  # noqa: BLE001
            continue
        for entry in templates:
            run = repo.get_report_run(scope, entry.id, report_run_id)
            if run is None:
                continue
            if run.user_id != principal.user_id and not principal.is_superadmin:
                raise HTTPException(status_code=403, detail="not your report run")
            if not run.report_payload_path:
                raise HTTPException(status_code=404, detail="payload not assembled yet")
            payload_path = Path(run.report_payload_path)
            if not payload_path.exists():
                raise HTTPException(status_code=410, detail="payload file gone")
            try:
                return json.loads(payload_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                raise HTTPException(status_code=500, detail=f"payload unreadable: {e}")
    raise HTTPException(status_code=404, detail=f"report_run {report_run_id!r} not found")
