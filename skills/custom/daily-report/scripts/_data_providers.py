"""Data connector for daily-report query script.

A single ``DailyDataProvider`` Protocol with one concrete implementation
(``PlatformDailyProvider``) that routes through the integrations platform bridge.

The abstraction is **dependency-free** — only stdlib.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------

DEMO_FALLBACK = "demo_fallback"
HTTP_SUCCESS = "http"
INS_SUCCESS = "ins"


@dataclass(frozen=True)
class ProviderResult:
    """What every provider returns. ``data`` is the raw dict the script needs;
    ``data_source`` is the tag that ends up in the script's JSON output."""

    data: dict
    data_source: str = DEMO_FALLBACK
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class DailyDataProvider(Protocol):
    """Provides one-day ``current``/``compare`` block payload for query_daily."""

    def fetch(
        self,
        *,
        date_str: str,
        equipment_ids: list[str],
        kpi_keys: list[str],
        eq_type: str,
        include_per_equipment: bool,
        equipment_meta: dict[str, dict] | None,
    ) -> ProviderResult: ...


# ---------------------------------------------------------------------------
# HttpProviderError
# ---------------------------------------------------------------------------


class HttpProviderError(RuntimeError):
    """Raised by a provider when a backend call fails irrecoverably.

    Caller decides whether to bubble up or fall back to the demo provider.
    """


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_PROVIDER_FACTORIES: dict[str, dict[str, Callable[[], Any]]] = {
    "daily": {},
}


def register_provider(source: str, mode: str, factory: Callable[[], Any]) -> None:
    """Register a provider factory for (source, mode)."""
    if source not in _PROVIDER_FACTORIES:
        raise ValueError(f"unknown data source: {source!r}")
    _PROVIDER_FACTORIES[source][mode] = factory


def get_provider(source: str, *, mode: str | None = None) -> Any:
    """Resolve the active provider instance for ``source``.

    Mode resolution order:
        1. Explicit ``mode`` argument.
        2. ``DEER_FLOW_DATA_PROVIDER`` env var.
        3. Default ``platform``.

    Raises ``KeyError`` if the requested mode has no registered provider.
    """
    if source not in _PROVIDER_FACTORIES:
        raise ValueError(f"unknown data source: {source!r}")
    if mode is not None:
        chosen = mode.lower()
    else:
        env_mode = (os.environ.get("DEER_FLOW_DATA_PROVIDER") or "").lower()
        chosen = env_mode or "platform"
    factories = _PROVIDER_FACTORIES[source]
    if chosen not in factories:
        raise KeyError(
            f"no provider registered for source={source!r} mode={chosen!r}; "
            f"registered={sorted(factories.keys())}"
        )
    return factories[chosen]()


def list_registered() -> dict[str, list[str]]:
    """Inspection helper for tests: returns {source: [modes...]}."""
    return {k: sorted(v.keys()) for k, v in _PROVIDER_FACTORIES.items()}


# ---------------------------------------------------------------------------
# Fallback helper
# ---------------------------------------------------------------------------


def fetch_with_fallback(
    *,
    source: str,
    fetch_args: dict,
    mode: str | None = None,
) -> ProviderResult:
    """Try the active provider; on ``HttpProviderError`` fall back to demo."""
    primary = get_provider(source, mode=mode)
    try:
        result = primary.fetch(**fetch_args)
        if not isinstance(result, ProviderResult):
            raise TypeError(f"{source} provider returned non-ProviderResult: {type(result)}")
        return result
    except HttpProviderError as exc:
        demo = get_provider(source, mode="demo")
        fallback = demo.fetch(**fetch_args)
        notes = list(fallback.notes) + [f"HTTP provider failed, fell back to demo: {exc}"]
        return ProviderResult(
            data=fallback.data,
            data_source=DEMO_FALLBACK,
            notes=notes,
        )
    except Exception:
        raise


# ---------------------------------------------------------------------------
# PlatformDailyProvider — the one concrete implementation
# ---------------------------------------------------------------------------


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
