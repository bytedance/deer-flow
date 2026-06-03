"""Provider implementations for monthly-report skill.

Registers only PlatformMonthlyProvider — no daily/weekly/trend/diagnosis Providers.
"""

from __future__ import annotations

from _data_providers import (
    INS_SUCCESS,
    HttpProviderError,
    ProviderResult,
    register_provider,
)


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
