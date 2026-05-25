"""DataConnector abstraction layer for query scripts.

Sprint goal: keep the 5 query scripts (query_trend / query_fault_context /
query_failure_data / query_closure_items / query_inspection) decoupled from
specific data backends. A future integration (CMMS / TSDB / Improvement Plan
API / MCP data_catalog server) becomes a Provider implementation; the scripts
keep their CLI + output schema unchanged.

Design (5 layers):
1. **Protocol** — one Python ``Protocol`` per query script. Each protocol's
   single method returns a dict matching the script's expected source shape.
2. **DemoProvider** — every protocol has a ``Demo*Provider`` that produces the
   deterministic synthetic data the script already shipped. This is the
   default and always-available fallback.
3. **HttpProvider** — calls a configured ``http_connector`` (see
   config.yaml ``http_connectors``). Real backends wire here. Empty in this
   Sprint — left as TODO with a clear contract.
4. **Registry** — ``get_provider(source_name)`` resolves the active provider
   based on the ``DEER_FLOW_DATA_PROVIDER`` env var (``demo`` / ``http``).
5. **Result envelope** — every provider call returns a ``ProviderResult``
   carrying both the data and a ``data_source`` tag (``"demo_fallback"`` /
   ``"http"``). Scripts surface this in their JSON output.

The abstraction is **dependency-free** — only stdlib. Scripts run in the
sandbox without langchain / langgraph imports.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
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
# Protocols — one per query script
# ---------------------------------------------------------------------------


class TrendDataProvider(Protocol):
    """Provides ``time_series[]`` + ``metadata`` for query_trend."""

    def fetch(
        self,
        *,
        metric_keys: list[str],
        date_range: tuple[str, str],  # (start_iso, end_iso)
        aggregation: str,  # "hourly" | "daily" | "weekly"
        forecast_horizon: int,
    ) -> ProviderResult: ...


class FaultContextProvider(Protocol):
    """Provides ``operations[]`` / ``alarms[]`` / ``work_orders[]`` /
    ``maintenance_records[]`` for query_fault_context."""

    def fetch(
        self,
        *,
        fault_time: str,
        equipment_id: str,
        symptom: str,
        include_related_equipment: bool,
    ) -> ProviderResult: ...


class FailureDataProvider(Protocol):
    """Provides operations / maintenance / inspections / spares / environment
    + per-method seed (5why / fishbone / fmea) for query_failure_data."""

    def fetch(
        self,
        *,
        asset_id: str,
        failure_mode: str,
        analysis_method: str,  # "five_why" | "fishbone" | "fmea"
        evidence_range: str,
    ) -> ProviderResult: ...


class ClosureItemsProvider(Protocol):
    """Provides ``closure_items[]`` for query_closure_items."""

    def fetch(
        self,
        *,
        issue_ids: list[str],
        owner_department: str,
        verification_period: str,
    ) -> ProviderResult: ...


class InspectionProvider(Protocol):
    """Provides ``records[]`` + ``attachments[]`` for query_inspection."""

    def fetch(
        self,
        *,
        inspection_date: str,
        route: str,
        area: str,
        severity_min: str,  # "low" | "medium" | "high"
    ) -> ProviderResult: ...


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
# HttpProvider — generic helper that posts JSON to a configured HTTP endpoint
# ---------------------------------------------------------------------------


class HttpProviderError(RuntimeError):
    """Raised by HttpProvider when a backend call fails irrecoverably.

    Caller decides whether to bubble up or fall back to the demo provider.
    """


@dataclass(frozen=True)
class HttpEndpoint:
    """Subset of the http_connector config the abstraction layer cares about.

    The data-analyst skill cannot import deerflow.tools (it would pull in
    langchain), so we redefine just enough to call urllib directly. In the
    sandbox, scripts read these from environment variables — see ``from_env``.
    """

    url: str
    method: str = "POST"
    auth_token: str | None = None
    timeout_seconds: int = 30

    @classmethod
    def from_env(cls, prefix: str) -> HttpEndpoint | None:
        """Build endpoint from env vars: ``{prefix}_URL`` (+ ``_METHOD``,
        ``_TOKEN``, ``_TIMEOUT``). Returns None if the URL is missing."""
        url = os.environ.get(f"{prefix}_URL")
        if not url:
            return None
        return cls(
            url=url,
            method=os.environ.get(f"{prefix}_METHOD", "POST"),
            auth_token=os.environ.get(f"{prefix}_TOKEN"),
            timeout_seconds=int(os.environ.get(f"{prefix}_TIMEOUT", "30")),
        )


def call_http_endpoint(
    endpoint: HttpEndpoint, body: dict, *, max_response_bytes: int = 1_048_576
) -> dict:
    """Issue a single HTTP request with bearer auth + body JSON.

    Raises ``HttpProviderError`` on any failure (network / non-2xx / oversize
    / invalid JSON). Caller decides whether to fall back.
    """
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint.url,
        data=payload if endpoint.method.upper() != "GET" else None,
        method=endpoint.method.upper(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **({"Authorization": f"Bearer {endpoint.auth_token}"} if endpoint.auth_token else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=endpoint.timeout_seconds) as resp:
            raw = resp.read(max_response_bytes + 1)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise HttpProviderError(f"HTTP call failed: {type(exc).__name__}: {exc}") from exc
    except OSError as exc:  # other socket/timeout flavours
        raise HttpProviderError(f"HTTP call failed: {type(exc).__name__}: {exc}") from exc

    if len(raw) > max_response_bytes:
        raise HttpProviderError(f"response exceeded {max_response_bytes} bytes")

    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HttpProviderError(f"invalid JSON in response: {exc}") from exc
    if not isinstance(decoded, dict):
        raise HttpProviderError(f"expected JSON object, got {type(decoded).__name__}")
    return decoded


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


# Maps a *source kind* to the function the caller should invoke. Providers
# register themselves here at module load time. Sources include the original
# 5 (trend / fault_context / failure_data / closure_items / inspection) plus
# 3 added for equipment reports (daily / weekly / monthly).
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

INS_ONLY_SOURCES = {"daily", "weekly", "monthly"}


def _resolve_mode(source: str, mode: str | None) -> str:
    """Resolve the provider mode for ``source``.

    Equipment report sources (``daily`` / ``weekly`` / ``monthly``) are
    pinned to the InS backend — they ignore ``DEER_FLOW_DATA_PROVIDER`` and
    always resolve to ``ins``. The reverse is also enforced: non-INS sources
    never resolve to ``ins`` (fall back to ``demo`` when the env var says
    ``ins``, since those sources don't have an InS provider).
    """
    if mode is not None:
        return mode.lower()
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
        2. For ``daily`` / ``weekly`` / ``monthly``: always ``ins``.
        3. ``DEER_FLOW_DATA_PROVIDER`` env var.
        4. Default ``demo``.

    Equipment report sources (``daily`` / ``weekly`` / ``monthly``) are
    pinned to the InS backend; ``DEER_FLOW_DATA_PROVIDER`` is ignored for
    those sources.

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


# ---------------------------------------------------------------------------
# Fallback helper used by every query script
# ---------------------------------------------------------------------------


def fetch_with_fallback(
    *,
    source: str,
    fetch_args: dict,
    mode: str | None = None,
) -> ProviderResult:
    """Try the active provider; on ``HttpProviderError`` fall back to demo.

    Scripts call this helper rather than reaching into the registry directly.
    The result's ``data_source`` tag is forwarded to the script's JSON output
    so downstream consumers can tell which path produced the data.
    """
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
        # Anything else from the demo provider is a programming bug — bubble.
        raise
