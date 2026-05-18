"""Telemetry API for the Report Template Platform (Phase 7).

Pattern matches ``app/gateway/routers/genui_telemetry.py``: an in-memory
collector exposes its counters as JSON over HTTP. Admin tooling polls these
endpoints to surface the charter §16.2 monitoring indicators.

Routes:

    GET  /api/telemetry/report-templates/summary
        Current in-process counter snapshot. No auth — same trust boundary
        as ``/api/telemetry/genui/summary``.

    POST /api/telemetry/report-templates/scan-storage
        Run a one-shot storage scan (charter §4.5). Returns ``{owner_id: bytes}``.

    POST /api/telemetry/report-templates/scan-versions
        Run a one-shot version-count scan (charter §4.4). Returns
        ``{template_id: count}``.

Both POST routes are intended for ops cron jobs; they are O(n_files) and
should not be called from request hot paths.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from deerflow.report_templates.service import get_repository
from deerflow.report_templates.storage_scanner import (
    scan_storage,
    scan_version_counts,
)
from deerflow.report_templates.telemetry import get_telemetry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telemetry/report-templates", tags=["report-templates-telemetry"])


@router.get("/summary", summary="Phase 7 telemetry counters snapshot")
async def report_template_telemetry_summary() -> dict:
    return get_telemetry().summary()


@router.post("/scan-storage", summary="One-shot storage usage scan")
async def report_template_scan_storage() -> dict:
    runtime_root = get_repository()._runtime_root  # type: ignore[attr-defined]
    counts = scan_storage(runtime_root)
    return {"scanned": len(counts), "bytes_by_owner": counts}


@router.post("/scan-versions", summary="One-shot per-template version-count scan")
async def report_template_scan_versions() -> dict:
    runtime_root = get_repository()._runtime_root  # type: ignore[attr-defined]
    counts = scan_version_counts(runtime_root)
    return {"scanned": len(counts), "version_count_by_template": counts}
