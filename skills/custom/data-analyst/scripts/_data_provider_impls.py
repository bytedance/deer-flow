"""Provider implementations for the DataConnector abstraction.

Two categories of sources live in this module:

* The 4 HTTP-backed sources (``fault_context`` / ``failure_data`` /
  ``closure_items`` / ``inspection``) each register a ``demo`` + ``http``
  pair. They keep deterministic synthetic data so the dev / demo workflows
  run offline; ``fetch_with_fallback`` swaps in the demo path when the HTTP
  endpoint is unreachable.

* The AI report sources (``daily`` / ``weekly`` / ``monthly``)
  register **only** their real-backed provider (platform). There is no
  demo fallback — any ``HttpProviderError`` propagates so the failure is
  visible at the CLI as ``{"error": "HttpProviderError: ..."}`` instead of
  being masked by synthetic output.

This module **must be imported** for the registry to pick up the providers.
Query scripts do this implicitly by importing ``_data_providers``.

For the HTTP-backed sources the integration contract is one typed JSON body
in, one typed JSON body out. Engineers wiring a real CMMS / TSDB pull only
need to:

  1. Stand up an endpoint matching the contract documented below each
     ``Http*Provider.fetch``.
  2. Set ``DEER_FLOW_DATA_PROVIDER=http`` (only affects the 4 demo sources).
  3. Set the source-specific ``{PREFIX}_URL`` + ``{PREFIX}_TOKEN`` env vars
     (e.g. ``DEERFLOW_TREND_URL``).
"""

from __future__ import annotations

from _report_common import load_sibling_module_required as _load_script

from _data_providers import (
    DEMO_FALLBACK,
    HTTP_SUCCESS,
    INS_SUCCESS,
    HttpEndpoint,
    HttpProviderError,
    ProviderResult,
    call_http_endpoint,
    register_provider,
)

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
        equipment_name: str | None = None,
    ) -> ProviderResult:
        qf = _load_script("query_fault_context")
        from datetime import date as _date

        fault_day = _date.fromisoformat(fault_time)
        return ProviderResult(
            data={
                "operations": qf._operations(fault_day, equipment_id),
                "alarms": qf._alarms(fault_day, equipment_id, equipment_name),
                "work_orders": qf._work_orders(fault_day, equipment_id, equipment_name),
                "maintenance_records": qf._maintenance_records(fault_day, equipment_id, equipment_name),
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
        equipment_name: str | None = None,
    ) -> ProviderResult:
        endpoint = HttpEndpoint.from_env("DEERFLOW_FAULT_CONTEXT")
        if endpoint is None:
            raise HttpProviderError("DEERFLOW_FAULT_CONTEXT_URL not set")
        body = {
            "fault_time": fault_time,
            "equipment_id": equipment_id,
            "equipment_name": equipment_name or "",
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
        from datetime import date as _date
        from datetime import datetime, timedelta

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
                    "equipment_id": template.get("equipment_id") or template["equipment"],
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


# ============================================================================
# daily / query_daily.py — platform-backed equipment daily report
# ============================================================================


class PlatformDailyProvider:
    """Routes through the integrations platform bridge (capability + action).

    On success returns a ``current``-block-shaped dict tagged
    ``data_source="ins"``. Any failure raises ``HttpProviderError`` which the
    query script propagates as ``{"error": "HttpProviderError: ..."}``.
    """

    def fetch(
        self,
        *,
        date_str: str,
        equipment_ids: list[str],
        kpi_keys: list[str],
        eq_type: str = "all",
        include_per_equipment: bool = False,
        equipment_meta: dict[str, dict] | None = None,
    ) -> ProviderResult:
        from _platform_bridge import call_capability, call_action

        try:
            day_start = f"{date_str}T00:00:00"
            day_end = f"{date_str}T23:59:59"

            # Step 1: raw trend data via integrations capability
            trend_result = call_capability("monitoring.trend", {
                "equipment_ids": equipment_ids,
                "start_time": day_start,
                "end_time": day_end,
                "eq_type": eq_type,
            })

            # Step 2: KPI aggregation via integrations action
            kpi_result = call_action("aggregate_kpi", adapter="ins_prod", params={
                "trend_data": trend_result["data"],
                "kpi_keys": kpi_keys,
                "eq_type": eq_type,
            })

        except Exception as exc:
            raise HttpProviderError(
                f"Platform daily provider failed: {type(exc).__name__}: {exc}"
            ) from exc

        kpi_data = kpi_result["data"]
        return ProviderResult(
            data={
                "kpis": kpi_data.get("kpis", {}),
                "hourly_runtime_rate": kpi_data.get("hourly_runtime_rate", [0.0] * 24),
                "alarms": [],
            },
            data_source=INS_SUCCESS,
        )


register_provider("daily", "platform", PlatformDailyProvider)


# ============================================================================
# weekly / query_weekly.py — platform-backed equipment weekly report
# ============================================================================


class PlatformWeeklyProvider:
    """Fetches a 7-day window of daily entries via the platform bridge.

    Returns a list of ``{date, kpis, kpi_units, alarms}`` dicts — one per day.
    The caller (query_weekly.py) owns aggregation into the weekly shape.
    """

    def fetch(
        self,
        *,
        week_start: str,
        equipment_ids: list[str],
        kpi_keys: list[str],
        eq_type: str = "all",
        aggregate: bool = False,
        equipment_meta: dict[str, dict] | None = None,
    ) -> ProviderResult:
        from datetime import datetime, timedelta

        from _platform_bridge import call_capability, call_action

        start_dt = datetime.strptime(week_start, "%Y-%m-%d")
        day_count = 7
        daily_entries: list[dict] = []

        try:
            for offset in range(day_count):
                date_str = (start_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
                day_start = f"{date_str}T00:00:00"
                day_end = f"{date_str}T23:59:59"

                trend_result = call_capability("monitoring.trend", {
                    "equipment_ids": equipment_ids,
                    "start_time": day_start,
                    "end_time": day_end,
                    "eq_type": eq_type,
                })

                kpi_result = call_action("aggregate_kpi", adapter="ins_prod", params={
                    "trend_data": trend_result["data"],
                    "kpi_keys": kpi_keys,
                    "eq_type": eq_type,
                })

                kpi_data = kpi_result["data"]
                daily_entries.append({
                    "date": date_str,
                    "kpis": kpi_data.get("kpis", {}),
                    "kpi_units": kpi_data.get("kpi_units", {}),
                    "alarms": [],
                })

        except Exception as exc:
            raise HttpProviderError(
                f"Platform weekly provider failed: {type(exc).__name__}: {exc}"
            ) from exc

        return ProviderResult(data={"daily_entries": daily_entries}, data_source=INS_SUCCESS)


register_provider("weekly", "platform", PlatformWeeklyProvider)


# ============================================================================
# monthly / query_monthly.py — platform-backed equipment monthly report
# ============================================================================


class PlatformMonthlyProvider:
    """Fetches a calendar-month of daily entries via the platform bridge.

    Returns a list of ``{date, kpis, kpi_units, alarms}`` dicts — one per day.
    The caller (query_monthly.py) owns aggregation into weekly buckets and
    the monthly shape.
    """

    def fetch(
        self,
        *,
        report_month: str,
        equipment_ids: list[str],
        kpi_keys: list[str],
        eq_type: str = "all",
        aggregate: bool = False,
        equipment_meta: dict[str, dict] | None = None,
    ) -> ProviderResult:
        import calendar
        from datetime import datetime, timedelta

        from _platform_bridge import call_capability, call_action

        year, month = map(int, report_month.split("-"))
        _, day_count = calendar.monthrange(year, month)
        month_start = f"{year:04d}-{month:02d}-01"
        start_dt = datetime.strptime(month_start, "%Y-%m-%d")
        daily_entries: list[dict] = []

        try:
            for offset in range(day_count):
                date_str = (start_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
                day_start = f"{date_str}T00:00:00"
                day_end = f"{date_str}T23:59:59"

                trend_result = call_capability("monitoring.trend", {
                    "equipment_ids": equipment_ids,
                    "start_time": day_start,
                    "end_time": day_end,
                    "eq_type": eq_type,
                })

                kpi_result = call_action("aggregate_kpi", adapter="ins_prod", params={
                    "trend_data": trend_result["data"],
                    "kpi_keys": kpi_keys,
                    "eq_type": eq_type,
                })

                kpi_data = kpi_result["data"]
                daily_entries.append({
                    "date": date_str,
                    "kpis": kpi_data.get("kpis", {}),
                    "kpi_units": kpi_data.get("kpi_units", {}),
                    "alarms": [],
                })

        except Exception as exc:
            raise HttpProviderError(
                f"Platform monthly provider failed: {type(exc).__name__}: {exc}"
            ) from exc

        return ProviderResult(data={"daily_entries": daily_entries}, data_source=INS_SUCCESS)


register_provider("monthly", "platform", PlatformMonthlyProvider)
