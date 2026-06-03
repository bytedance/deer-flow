"""Provider implementations for monthly-report skill.

Registers InsMonthlyProvider — direct InS API calls within the sandbox process.
"""

from __future__ import annotations

from _data_providers import (
    INS_SUCCESS,
    HttpProviderError,
    ProviderResult,
    register_provider,
)
from _ins_provider import fetch_daily_series_payload


class InsMonthlyProvider:
    """Fetches a calendar-month of daily entries via direct InS API calls.

    Uses ``_ins_provider.fetch_daily_series_payload`` for a single
    process-internal async call that reuses one InS client across all days.
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

        year, month = map(int, report_month.split("-"))
        _, day_count = calendar.monthrange(year, month)
        month_start = f"{year:04d}-{month:02d}-01"

        try:
            daily_entries = fetch_daily_series_payload(
                start_date=month_start,
                day_count=day_count,
                equipment_ids=equipment_ids,
                kpi_keys=kpi_keys,
                eq_type=eq_type,
                equipment_meta=equipment_meta,
            )
        except HttpProviderError:
            raise
        except Exception as exc:
            raise HttpProviderError(
                f"Ins monthly provider failed: {type(exc).__name__}: {exc}"
            ) from exc

        return ProviderResult(data={"daily_entries": daily_entries}, data_source=INS_SUCCESS)


register_provider("monthly", "ins", InsMonthlyProvider)
