"""Provider registry for weekly-report skill.

The weekly report uses a single data source (weekly) with a single mode (ins).
Provider implementations register via ``register_provider``; callers resolve
via ``get_provider("weekly")``.

Design:
1. **Protocol** — ``WeeklyDataProvider`` defines the fetch contract.
2. **Registration** — ``_data_provider_impls.py`` registers ``InsWeeklyProvider`` at import time.
3. **Resolution** — ``get_provider("weekly")`` returns the registered provider instance.
4. **Result envelope** — every provider returns ``ProviderResult`` with ``data`` + ``data_source``.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------

INS_SUCCESS = "ins"


@dataclass(frozen=True)
class ProviderResult:
    """What every provider returns. ``data`` is the raw dict the script needs;
    ``data_source`` is the tag that ends up in the script's JSON output."""

    data: dict
    data_source: str = INS_SUCCESS
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class WeeklyDataProvider(Protocol):
    """Provides one-week aggregated payload for query_weekly."""

    def fetch(
        self,
        *,
        week_start: str,
        equipment_ids: list[str],
        kpi_keys: list[str],
        eq_type: str,
        aggregate: bool,
        equipment_meta: dict[str, dict] | None,
    ) -> ProviderResult: ...


# ---------------------------------------------------------------------------
# HttpProviderError — shared with _ins_provider.py
# ---------------------------------------------------------------------------


class HttpProviderError(RuntimeError):
    """Raised when a data fetch fails irrecoverably."""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_PROVIDER_FACTORIES: dict[str, dict[str, Callable[[], Any]]] = {
    "weekly": {},
}


def _resolve_mode(source: str, mode: str | None) -> str:
    """Resolve the provider mode for ``source``.

    Weekly report is pinned to the direct InS path — it ignores
    ``DEER_FLOW_DATA_PROVIDER`` and always resolves to ``ins``.
    """
    if mode is not None:
        return mode.lower()
    return "ins"


def register_provider(source: str, mode: str, factory: Callable[[], Any]) -> None:
    """Register a provider factory for (source, mode)."""
    if source not in _PROVIDER_FACTORIES:
        raise ValueError(f"unknown data source: {source!r}")
    _PROVIDER_FACTORIES[source][mode] = factory


def get_provider(source: str, *, mode: str | None = None) -> Any:
    """Resolve the active provider instance for ``source``.

    Weekly report always resolves to ``ins`` mode.
    ``DEER_FLOW_DATA_PROVIDER`` is ignored.

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
