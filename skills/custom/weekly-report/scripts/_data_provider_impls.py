"""Provider implementations for weekly-report skill.

Registers only PlatformWeeklyProvider — no daily/monthly/trend/diagnosis Providers.
"""

from __future__ import annotations

from _data_providers import (
    INS_SUCCESS,
    HttpProviderError,
    ProviderResult,
    register_provider,
)


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
