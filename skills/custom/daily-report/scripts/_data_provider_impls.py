"""Provider implementations for daily-report skill.

Registers only PlatformDailyProvider — no weekly/monthly/trend/diagnosis Providers.
"""

from __future__ import annotations

from _data_providers import (
    INS_SUCCESS,
    HttpProviderError,
    ProviderResult,
    register_provider,
)


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
