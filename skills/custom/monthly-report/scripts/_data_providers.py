"""Data provider registry for monthly-report query scripts.

Sprint goal: keep query_monthly.py decoupled from specific data backends.
A future integration (CMMS / TSDB / Improvement Plan API / MCP data_catalog
server) becomes a Provider implementation; the script keeps its CLI + output
schema unchanged.

Design:
1. **ProviderResult** — every provider call returns a ``ProviderResult``
   carrying both the data and a ``data_source`` tag.
2. **MonthlyDataProvider Protocol** — the contract ``InsMonthlyProvider`` fulfills.
3. **Registry** — ``get_provider(source_name)`` resolves the active provider.
   Monthly/daily/weekly sources are pinned to the ``ins`` mode.
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


class MonthlyDataProvider(Protocol):
    """Provides one-month aggregated payload for query_monthly."""

    def fetch(
        self,
        *,
        report_month: str,
        equipment_ids: list[str],
        kpi_keys: list[str],
        eq_type: str,
        aggregate: bool,
        equipment_meta: dict[str, dict] | None,
    ) -> ProviderResult: ...


# ---------------------------------------------------------------------------
# HttpProviderError
# ---------------------------------------------------------------------------


class HttpProviderError(RuntimeError):
    """Raised when a backend call fails irrecoverably."""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_PROVIDER_FACTORIES: dict[str, dict[str, Callable[[], Any]]] = {
    "trend": {},
    "fault_context": {},
    "failure_data": {},
    "closure_items": {},
    "inspection": {},
    "daily": {},
    "weekly": {},
    "monthly": {},
}

INS_ONLY_SOURCES: set[str] = {"trend"}

_INS_SOURCES = {"daily", "weekly", "monthly"}


def _resolve_mode(source: str, mode: str | None) -> str:
    """Resolve the provider mode for ``source``.

    Equipment report sources (``daily`` / ``weekly`` / ``monthly``) are
    pinned to the direct InS path — they ignore ``DEER_FLOW_DATA_PROVIDER``
    and always resolve to ``ins``.

    Trend is pinned to ``ins`` (it is not an AI report feature).
    """
    if mode is not None:
        return mode.lower()
    if source in _INS_SOURCES:
        return "ins"
    if source in INS_ONLY_SOURCES:
        return "ins"
    env_mode = (os.environ.get("DEER_FLOW_DATA_PROVIDER") or "").lower()
    if env_mode == "ins":
        return "demo"
    return env_mode or "demo"


def register_provider(source: str, mode: str, factory: Callable[[], Any]) -> None:
    """Register a provider factory for (source, mode).

    Modes used by ``get_provider``:
        ``demo`` — always-available deterministic synthetic data
        ``http`` — calls the configured HTTP endpoint
        ``ins``  — calls the InS (神固云) features-tool adapter (daily/weekly/monthly only)
    """
    if source not in _PROVIDER_FACTORIES:
        raise ValueError(f"unknown data source: {source!r}")
    _PROVIDER_FACTORIES[source][mode] = factory


def get_provider(source: str, *, mode: str | None = None) -> Any:
    """Resolve the active provider instance for ``source``.

    Mode resolution order:
        1. Explicit ``mode`` argument.
        2. For ``daily`` / ``weekly`` / ``monthly`` / ``trend``: always ``ins``.
        3. ``DEER_FLOW_DATA_PROVIDER`` env var.
        4. Default ``demo``.

    Equipment report sources (``daily`` / ``weekly`` / ``monthly``) are
    pinned to the direct InS path; ``DEER_FLOW_DATA_PROVIDER`` is ignored
    for those sources.

    Raises ``KeyError`` if the requested mode has no registered provider.
    """
    if source not in _PROVIDER_FACTORIES:
        raise ValueError(f"unknown data source: {source!r}")
    chosen = _resolve_mode(source, mode)
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
