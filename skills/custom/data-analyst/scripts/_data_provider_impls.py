"""Provider implementations for the DataConnector abstraction.

Each query script's data source has two providers registered here:
  - ``demo`` — wraps the existing deterministic demo logic
  - ``http`` — calls a configured HTTP endpoint (env-driven)

This module **must be imported** for the registry to pick up the providers.
Query scripts do this implicitly by importing ``_data_providers``.

Real backend integration is intentionally a single contract per source:
each ``Http*Provider`` POSTs a typed JSON body and expects a typed JSON
response. Engineers wiring a real CMMS / TSDB pull only need to:

  1. Stand up an endpoint matching the contract documented below each
     ``Http*Provider.fetch``.
  2. Set the ``DEER_FLOW_DATA_PROVIDER=http`` env var.
  3. Set the source-specific ``{PREFIX}_URL`` + ``{PREFIX}_TOKEN`` env vars
     (e.g. ``DEERFLOW_TREND_URL``).

If the endpoint isn't reachable or returns malformed JSON, ``fetch_with_fallback``
in ``_data_providers`` transparently falls back to the demo provider so the
demo / dev environment keeps working.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from _data_providers import (
    DEMO_FALLBACK,
    HTTP_SUCCESS,
    HttpEndpoint,
    HttpProviderError,
    ProviderResult,
    call_http_endpoint,
    register_provider,
)

# ---------------------------------------------------------------------------
# Lazy module loader — avoid circular imports when query scripts import this
# module on startup. We need to call helpers in the demo-data path of each
# query script without re-running its main(). The pattern: import the
# script module and call its top-level demo helpers directly.
# ---------------------------------------------------------------------------


def _load_script(name: str) -> Any:
    """Load a sibling script module by file path, bypassing import-side-effects."""
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ============================================================================
# trend / query_trend.py
# ============================================================================


class DemoTrendProvider:
    """Re-uses ``query_trend._build_series`` + ``_enumerate_steps`` to produce
    the deterministic sine demo data the existing tests rely on."""

    def fetch(
        self,
        *,
        metric_keys: list[str],
        date_range: tuple[str, str],
        aggregation: str,
        forecast_horizon: int,
    ) -> ProviderResult:
        qt = _load_script("query_trend")
        from datetime import date as _date

        start = _date.fromisoformat(date_range[0])
        end = _date.fromisoformat(date_range[1])
        timestamps = qt._enumerate_steps(start, end, aggregation)
        time_series = [qt._build_series(m, timestamps) for m in metric_keys]
        return ProviderResult(
            data={
                "time_series": time_series,
                "timestamps_meta": {
                    "first": timestamps[0] if timestamps else None,
                    "last": timestamps[-1] if timestamps else None,
                    "count_per_series": len(timestamps),
                },
            },
            data_source=DEMO_FALLBACK,
        )


class HttpTrendProvider:
    """POSTs to ``$DEERFLOW_TREND_URL`` with the parameters the script accepts.

    Expected request body::

        {
          "metric_keys": ["runtime_rate", ...],
          "date_range": {"start": "2026-04-01", "end": "2026-04-30"},
          "aggregation": "daily",
          "forecast_horizon": 7
        }

    Expected response body (must match the shape DemoTrendProvider produces)::

        {
          "time_series": [
            {
              "metric_key": "runtime_rate",
              "name": "运行率",
              "unit": "%",
              "timestamps": ["2026-04-01", ...],
              "values": [0.92, ...],
              "point_count": 30,
              "better_when_higher": true
            },
            ...
          ]
        }
    """

    def fetch(
        self,
        *,
        metric_keys: list[str],
        date_range: tuple[str, str],
        aggregation: str,
        forecast_horizon: int,
    ) -> ProviderResult:
        endpoint = HttpEndpoint.from_env("DEERFLOW_TREND")
        if endpoint is None:
            raise HttpProviderError("DEERFLOW_TREND_URL not set")
        body = {
            "metric_keys": metric_keys,
            "date_range": {"start": date_range[0], "end": date_range[1]},
            "aggregation": aggregation,
            "forecast_horizon": forecast_horizon,
        }
        data = call_http_endpoint(endpoint, body)
        if "time_series" not in data:
            raise HttpProviderError("response missing required field: time_series")
        return ProviderResult(data=data, data_source=HTTP_SUCCESS)


register_provider("trend", "demo", DemoTrendProvider)
register_provider("trend", "http", HttpTrendProvider)


# ============================================================================
# fault_context / query_fault_context.py
# ============================================================================


class DemoFaultContextProvider:
    def fetch(
        self,
        *,
        fault_time: str,
        equipment_id: str,
        symptom: str,
        include_related_equipment: bool,
    ) -> ProviderResult:
        qf = _load_script("query_fault_context")
        from datetime import date as _date

        fault_day = _date.fromisoformat(fault_time)
        return ProviderResult(
            data={
                "operations": qf._operations(fault_day, equipment_id),
                "alarms": qf._alarms(fault_day, equipment_id),
                "work_orders": qf._work_orders(fault_day, equipment_id),
                "maintenance_records": qf._maintenance_records(fault_day, equipment_id),
                "related_equipment": (
                    [f"{equipment_id}-aux", f"{equipment_id}-spare"]
                    if include_related_equipment
                    else []
                ),
            },
            data_source=DEMO_FALLBACK,
        )


class HttpFaultContextProvider:
    """POSTs to ``$DEERFLOW_FAULT_CONTEXT_URL``.

    Expected request body::

        {
          "fault_time": "2026-05-15",
          "equipment_id": "P-001",
          "symptom": "vibration high",
          "include_related_equipment": true
        }

    Expected response body::

        {
          "operations": [{id, t, equipment, metric, value, unit}, ...],
          "alarms":     [{id, time, equipment, level, message}, ...],
          "work_orders":         [{id, title, status, owner, equipment, created_at, closed_at?, note}, ...],
          "maintenance_records": [{id, type, equipment, at, owner, note}, ...],
          "related_equipment":   ["...aux", "...spare"]
        }
    """

    def fetch(
        self,
        *,
        fault_time: str,
        equipment_id: str,
        symptom: str,
        include_related_equipment: bool,
    ) -> ProviderResult:
        endpoint = HttpEndpoint.from_env("DEERFLOW_FAULT_CONTEXT")
        if endpoint is None:
            raise HttpProviderError("DEERFLOW_FAULT_CONTEXT_URL not set")
        body = {
            "fault_time": fault_time,
            "equipment_id": equipment_id,
            "symptom": symptom,
            "include_related_equipment": include_related_equipment,
        }
        data = call_http_endpoint(endpoint, body)
        missing = [k for k in ("operations", "alarms", "work_orders", "maintenance_records") if k not in data]
        if missing:
            raise HttpProviderError(f"response missing required fields: {missing}")
        if "related_equipment" not in data:
            data["related_equipment"] = []
        return ProviderResult(data=data, data_source=HTTP_SUCCESS)


register_provider("fault_context", "demo", DemoFaultContextProvider)
register_provider("fault_context", "http", HttpFaultContextProvider)


# ============================================================================
# failure_data / query_failure_data.py
# ============================================================================


class DemoFailureDataProvider:
    def fetch(
        self,
        *,
        asset_id: str,
        failure_mode: str,
        analysis_method: str,
        evidence_range: str,
    ) -> ProviderResult:
        qfd = _load_script("query_failure_data")
        from datetime import date as _date

        today = _date.today()
        method_seed = {
            "five_why": qfd._five_why_seed(failure_mode) if analysis_method == "five_why" else None,
            "fishbone": qfd._fishbone_seed(failure_mode) if analysis_method == "fishbone" else None,
            "fmea": qfd._fmea_seed(failure_mode) if analysis_method == "fmea" else None,
        }
        return ProviderResult(
            data={
                "operations": qfd._operations(today, asset_id),
                "maintenance": qfd._maintenance(today, asset_id),
                "inspections": qfd._inspections(today, asset_id),
                "spares": qfd._spares(today, asset_id),
                "environment": qfd._environment(),
                "method_seed": method_seed,
            },
            data_source=DEMO_FALLBACK,
        )


class HttpFailureDataProvider:
    """POSTs to ``$DEERFLOW_FAILURE_DATA_URL``.

    Expected request body::

        {
          "asset_id": "P-001",
          "failure_mode": "轴承卡死",
          "analysis_method": "five_why" | "fishbone" | "fmea",
          "evidence_range": "2026-01-01..2026-05-18"
        }

    Expected response body::

        {
          "operations": [...], "maintenance": [...], "inspections": [...],
          "spares": [...], "environment": {...},
          "method_seed": {"five_why": {...} | null, "fishbone": ... | null, "fmea": ... | null}
        }

    Note: only the entry matching ``analysis_method`` should be populated;
    the other two must be null (or the failure_analysis transform will route
    to the wrong branch).
    """

    def fetch(
        self,
        *,
        asset_id: str,
        failure_mode: str,
        analysis_method: str,
        evidence_range: str,
    ) -> ProviderResult:
        endpoint = HttpEndpoint.from_env("DEERFLOW_FAILURE_DATA")
        if endpoint is None:
            raise HttpProviderError("DEERFLOW_FAILURE_DATA_URL not set")
        body = {
            "asset_id": asset_id,
            "failure_mode": failure_mode,
            "analysis_method": analysis_method,
            "evidence_range": evidence_range,
        }
        data = call_http_endpoint(endpoint, body)
        missing = [k for k in ("operations", "maintenance", "inspections", "spares", "environment", "method_seed") if k not in data]
        if missing:
            raise HttpProviderError(f"response missing required fields: {missing}")
        # Backend must populate exactly the requested method seed
        seed = data["method_seed"]
        if not isinstance(seed, dict) or seed.get(analysis_method) is None:
            raise HttpProviderError(f"method_seed[{analysis_method!r}] is null in response")
        return ProviderResult(data=data, data_source=HTTP_SUCCESS)


register_provider("failure_data", "demo", DemoFailureDataProvider)
register_provider("failure_data", "http", HttpFailureDataProvider)


# ============================================================================
# closure_items / query_closure_items.py
# ============================================================================


class DemoClosureItemsProvider:
    def fetch(
        self,
        *,
        issue_ids: list[str],
        owner_department: str,
        verification_period: str,
    ) -> ProviderResult:
        qci = _load_script("query_closure_items")
        from datetime import date as _date

        today = _date.today()
        items = [
            qci._build_issue(idx, iid, today, owner_department) for idx, iid in enumerate(issue_ids)
        ]
        return ProviderResult(data={"closure_items": items}, data_source=DEMO_FALLBACK)


class HttpClosureItemsProvider:
    """POSTs to ``$DEERFLOW_CLOSURE_ITEMS_URL``.

    Expected request body::

        {
          "issue_ids": ["ISSUE-001", ...],
          "owner_department": "运行部",
          "verification_period": "2026-04-01..2026-05-15"
        }

    Expected response body::

        {
          "closure_items": [
            {
              "id": "ISSUE-001", "title": "...", "owner": "...", "department": "...",
              "status": "pending" | "in_progress" | "verifying" | "closed" | "reopened",
              "created_at": "ISO", "due_date": "ISO", "closed_at": "ISO" | null,
              "actions": [{id, label, owner, status, completed_at?}, ...],
              "verification_results": [{id, method, executor, outcome, executed_at, reopen_reason?}, ...],
              "notes": "..."
            }, ...
          ]
        }
    """

    def fetch(
        self,
        *,
        issue_ids: list[str],
        owner_department: str,
        verification_period: str,
    ) -> ProviderResult:
        endpoint = HttpEndpoint.from_env("DEERFLOW_CLOSURE_ITEMS")
        if endpoint is None:
            raise HttpProviderError("DEERFLOW_CLOSURE_ITEMS_URL not set")
        body = {
            "issue_ids": issue_ids,
            "owner_department": owner_department,
            "verification_period": verification_period,
        }
        data = call_http_endpoint(endpoint, body)
        if "closure_items" not in data or not isinstance(data["closure_items"], list):
            raise HttpProviderError("response missing closure_items[] array")
        return ProviderResult(data=data, data_source=HTTP_SUCCESS)


register_provider("closure_items", "demo", DemoClosureItemsProvider)
register_provider("closure_items", "http", HttpClosureItemsProvider)


# ============================================================================
# inspection / query_inspection.py
# ============================================================================


class DemoInspectionProvider:
    def fetch(
        self,
        *,
        inspection_date: str,
        route: str,
        area: str,
        severity_min: str,
    ) -> ProviderResult:
        qi = _load_script("query_inspection")
        from datetime import date as _date, datetime, timedelta

        inspection_day = _date.fromisoformat(inspection_date)
        min_rank = qi.SEVERITY_RANK[severity_min]
        base_dt = datetime.combine(inspection_day, datetime.min.time()) + timedelta(hours=8)

        records: list[dict] = []
        used_attachment_ids: set[str] = set()
        for idx, template in enumerate(qi.DEMO_RECORDS):
            if qi.SEVERITY_RANK[template["severity"]] < min_rank:
                continue
            record_dt = base_dt + timedelta(minutes=idx * 27)
            record_id = f"INSP-{inspection_day.strftime('%Y%m%d')}-{idx + 1:03d}"
            record_attachments = template["attachment_refs"]
            used_attachment_ids.update(record_attachments)
            records.append(
                {
                    "id": record_id,
                    "time": record_dt.isoformat(timespec="seconds"),
                    "route": route,
                    "area": area,
                    "equipment": template["equipment"],
                    "inspector": template["inspector"],
                    "status": template["status"],
                    "severity": template["severity"],
                    "description": template["description"],
                    "attachment_refs": record_attachments,
                }
            )
        attachments = [a for a in qi.DEMO_ATTACHMENTS if a["id"] in used_attachment_ids]
        return ProviderResult(
            data={"records": records, "attachments": attachments},
            data_source=DEMO_FALLBACK,
        )


class HttpInspectionProvider:
    """POSTs to ``$DEERFLOW_INSPECTION_URL``.

    Expected request body::

        {
          "inspection_date": "2026-05-15",
          "route": "RT-A",
          "area": "A区",
          "severity_min": "low" | "medium" | "high"
        }

    Expected response body::

        {
          "records": [
            {
              "id": "INSP-...", "time": "ISO", "route": "...", "area": "...",
              "equipment": "...", "inspector": "...",
              "status": "normal" | "warning" | "critical",
              "severity": "low" | "medium" | "high" | "critical",
              "description": "...", "attachment_refs": ["ATT-...", ...]
            }, ...
          ],
          "attachments": [
            {"id": "ATT-...", "type": "photo" | "note", "ref": "/path/or/empty", "summary": "..."}, ...
          ]
        }

    The backend should already apply ``severity_min`` filtering — clients
    don't post-filter.
    """

    def fetch(
        self,
        *,
        inspection_date: str,
        route: str,
        area: str,
        severity_min: str,
    ) -> ProviderResult:
        endpoint = HttpEndpoint.from_env("DEERFLOW_INSPECTION")
        if endpoint is None:
            raise HttpProviderError("DEERFLOW_INSPECTION_URL not set")
        body = {
            "inspection_date": inspection_date,
            "route": route,
            "area": area,
            "severity_min": severity_min,
        }
        data = call_http_endpoint(endpoint, body)
        if "records" not in data:
            raise HttpProviderError("response missing records[] array")
        if "attachments" not in data:
            data["attachments"] = []
        return ProviderResult(data=data, data_source=HTTP_SUCCESS)


register_provider("inspection", "demo", DemoInspectionProvider)
register_provider("inspection", "http", HttpInspectionProvider)
