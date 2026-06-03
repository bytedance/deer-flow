"""Provider implementations for weekly-report skill.

Registers only InsWeeklyProvider — no daily/monthly/trend/diagnosis Providers.
"""

from __future__ import annotations

from _data_providers import (
    INS_SUCCESS,
    HttpProviderError,
    ProviderResult,
    register_provider,
)


class InsWeeklyProvider:
    """Fetches a 7-day window of daily entries via direct InS client.

    Returns a list of ``{date, kpis, kpi_units, alarms}`` dicts — one per day.
    The caller (query_weekly.py) owns aggregation into the weekly shape.
    Single ``InsApiClient`` instance is reused across all 7 days.
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
        from _ins_provider import fetch_daily_series_payload

        try:
            daily_entries = fetch_daily_series_payload(
                start_date=week_start,
                day_count=7,
                equipment_ids=equipment_ids,
                kpi_keys=kpi_keys,
                eq_type=eq_type,
                equipment_meta=equipment_meta,
            )
        except Exception as exc:
            raise HttpProviderError(
                f"Ins weekly provider failed: {type(exc).__name__}: {exc}"
            ) from exc

        return ProviderResult(data={"daily_entries": daily_entries}, data_source=INS_SUCCESS)


register_provider("weekly", "ins", InsWeeklyProvider)
