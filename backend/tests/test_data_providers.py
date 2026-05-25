"""Tests for the DataConnector abstraction layer.

Sprint goal: verify the 5 query scripts can be redirected to an HTTP backend
via the registry, and that fetch_with_fallback() degrades gracefully to demo
data when the HTTP path fails.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts"


def _load(name: str):
    """Load a sibling script module by file path."""
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def providers():
    """Load _data_providers + _data_provider_impls so the registry is populated.

    Module-scoped: re-running exec_module for each test would clear the
    registry state from the previously-imported module instance.
    """
    sys.path.insert(0, str(SCRIPTS_DIR))
    _load("_stub_helpers")
    dp = _load("_data_providers")
    # Importing _data_provider_impls populates the registry as a side effect
    _load("_data_provider_impls")
    return dp


# ---------------------------------------------------------------------------
# Registry / ProviderResult contract
# ---------------------------------------------------------------------------


def test_registry_has_all_5_sources_with_2_modes(providers):
    """Every source must register both demo + http modes."""
    registered = providers.list_registered()
    for source in ("trend", "fault_context", "failure_data", "closure_items", "inspection"):
        assert source in registered, f"source {source!r} missing from registry"
        assert "demo" in registered[source], f"source {source!r} missing demo provider"
        assert "http" in registered[source], f"source {source!r} missing http provider"


def test_provider_result_envelope_exposes_data_source(providers):
    """Every demo provider's ProviderResult must carry data_source='demo_fallback'."""
    for source in ("trend", "fault_context", "failure_data", "closure_items", "inspection"):
        provider = providers.get_provider(source, mode="demo")
        result = _invoke_demo(provider, source)
        assert isinstance(result, providers.ProviderResult)
        assert result.data_source == providers.DEMO_FALLBACK
        assert isinstance(result.data, dict)


def _invoke_demo(provider, source: str):
    """Call provider.fetch with reasonable defaults for the source."""
    if source == "trend":
        return provider.fetch(
            metric_keys=["runtime_rate"], date_range=("2026-04-01", "2026-04-30"),
            aggregation="daily", forecast_horizon=7,
        )
    if source == "fault_context":
        return provider.fetch(
            fault_time="2026-05-15", equipment_id="P-001",
            symptom="vibration", include_related_equipment=True,
        )
    if source == "failure_data":
        return provider.fetch(
            asset_id="P-001", failure_mode="bearing_seize",
            analysis_method="five_why", evidence_range="",
        )
    if source == "closure_items":
        return provider.fetch(
            issue_ids=["ISSUE-001", "ISSUE-002", "ISSUE-003", "ISSUE-004", "ISSUE-005"],
            owner_department="运行部", verification_period="",
        )
    if source == "inspection":
        return provider.fetch(
            inspection_date="2026-05-15", route="RT-A", area="A", severity_min="low",
        )
    raise AssertionError(f"unknown source {source}")


# ---------------------------------------------------------------------------
# Mode selection via env var
# ---------------------------------------------------------------------------


def test_default_mode_is_demo(providers, monkeypatch):
    monkeypatch.delenv("DEER_FLOW_DATA_PROVIDER", raising=False)
    p = providers.get_provider("trend")
    # The demo provider class lives in _data_provider_impls
    assert "Demo" in type(p).__name__


def test_env_var_routes_to_http(providers, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_DATA_PROVIDER", "http")
    p = providers.get_provider("fault_context")
    assert "Http" in type(p).__name__


def test_env_var_ins_on_non_ins_source_falls_back_to_demo(providers, monkeypatch):
    """DEER_FLOW_DATA_PROVIDER=ins on trend/fault_context/etc. must fall back to demo."""
    monkeypatch.setenv("DEER_FLOW_DATA_PROVIDER", "ins")
    for source in ("trend", "fault_context", "failure_data", "closure_items", "inspection"):
        p = providers.get_provider(source)
        assert "Demo" in type(p).__name__, (
            f"get_provider({source!r}) returned {type(p).__name__}, expected Demo*Provider"
        )


def test_unknown_mode_raises_key_error(providers, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_DATA_PROVIDER", "nonexistent")
    with pytest.raises(KeyError):
        providers.get_provider("trend")


def test_unknown_source_raises_value_error(providers):
    with pytest.raises(ValueError):
        providers.get_provider("not_a_source")


# ---------------------------------------------------------------------------
# Daily / Weekly / Monthly are InS-only (DEER_FLOW_DATA_PROVIDER ignored)
# ---------------------------------------------------------------------------


def test_daily_weekly_monthly_only_register_ins(providers):
    registered = providers.list_registered()
    for source in ("daily", "weekly", "monthly"):
        assert source in registered, f"source {source!r} missing from registry"
        assert registered[source] == ["ins"], (
            f"source {source!r} has modes {registered[source]}, expected ['ins']"
        )


def test_daily_weekly_monthly_ignore_env_var_demo(providers, monkeypatch):
    """DEER_FLOW_DATA_PROVIDER=demo must NOT affect daily/weekly/monthly."""
    monkeypatch.setenv("DEER_FLOW_DATA_PROVIDER", "demo")
    for source in ("daily", "weekly", "monthly"):
        p = providers.get_provider(source)
        assert "Ins" in type(p).__name__, (
            f"get_provider({source!r}) returned {type(p).__name__}, expected Ins*Provider"
        )


def test_daily_weekly_monthly_reject_explicit_demo_mode(providers):
    for source in ("daily", "weekly", "monthly"):
        with pytest.raises(KeyError, match="demo"):
            providers.get_provider(source, mode="demo")


def test_daily_weekly_monthly_ignore_env_var_http(providers, monkeypatch):
    """DEER_FLOW_DATA_PROVIDER=http must NOT affect daily/weekly/monthly."""
    monkeypatch.setenv("DEER_FLOW_DATA_PROVIDER", "http")
    for source in ("daily", "weekly", "monthly"):
        p = providers.get_provider(source)
        assert "Ins" in type(p).__name__


# ---------------------------------------------------------------------------
# Fallback path
# ---------------------------------------------------------------------------


def test_fallback_when_http_url_missing(providers, monkeypatch):
    """When DEER_FLOW_DATA_PROVIDER=http but no URL is set, fall back to demo."""
    monkeypatch.setenv("DEER_FLOW_DATA_PROVIDER", "http")
    monkeypatch.delenv("DEERFLOW_TREND_URL", raising=False)

    result = providers.fetch_with_fallback(
        source="trend",
        fetch_args={
            "metric_keys": ["runtime_rate"],
            "date_range": ("2026-04-01", "2026-04-30"),
            "aggregation": "daily",
            "forecast_horizon": 7,
        },
    )
    assert result.data_source == providers.DEMO_FALLBACK
    assert any("fell back to demo" in n for n in result.notes)
    # Demo data still present
    assert len(result.data["time_series"]) == 1


def test_fallback_when_http_call_fails(providers, monkeypatch):
    """Patch urllib.request.urlopen to simulate a network failure."""
    monkeypatch.setenv("DEER_FLOW_DATA_PROVIDER", "http")
    monkeypatch.setenv("DEERFLOW_FAULT_CONTEXT_URL", "http://nonexistent.local:1/api")

    # Force urlopen to raise — this drives the HttpProvider's HttpProviderError
    import urllib.request

    def _broken(*a, **kw):
        raise ConnectionError("simulated network failure")

    monkeypatch.setattr(urllib.request, "urlopen", _broken)

    result = providers.fetch_with_fallback(
        source="fault_context",
        fetch_args={
            "fault_time": "2026-05-15",
            "equipment_id": "P-001",
            "symptom": "test",
            "include_related_equipment": False,
        },
    )
    assert result.data_source == providers.DEMO_FALLBACK
    assert "alarms" in result.data
    assert any("fell back to demo" in n for n in result.notes)


def test_http_success_path(providers, monkeypatch):
    """Patch urllib.request.urlopen to return a synthetic HTTP response.

    We don't run a real HTTP server — instead patch the call_http_endpoint
    pathway so the test stays hermetic.
    """
    monkeypatch.setenv("DEER_FLOW_DATA_PROVIDER", "http")
    monkeypatch.setenv("DEERFLOW_CLOSURE_ITEMS_URL", "http://example.test/api")

    canned_response = {
        "closure_items": [
            {
                "id": "REAL-001",
                "title": "from-http",
                "owner": "real_owner",
                "department": "real_dept",
                "status": "closed",
                "created_at": "2026-05-01",
                "due_date": "2026-05-15",
                "closed_at": "2026-05-10",
                "actions": [],
                "verification_results": [],
                "notes": "",
            }
        ]
    }

    class _FakeResponse:
        def __init__(self, body):
            self._body = body

        def read(self, *a):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import urllib.request

    def _fake_urlopen(req, timeout=None):
        return _FakeResponse(json.dumps(canned_response).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    result = providers.fetch_with_fallback(
        source="closure_items",
        fetch_args={
            "issue_ids": ["whatever"],
            "owner_department": "",
            "verification_period": "",
        },
    )
    assert result.data_source == providers.HTTP_SUCCESS
    assert result.data["closure_items"][0]["id"] == "REAL-001"


def test_http_response_missing_required_field_falls_back(providers, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_DATA_PROVIDER", "http")
    monkeypatch.setenv("DEERFLOW_INSPECTION_URL", "http://example.test/api")

    class _FakeResponse:
        def __init__(self, body):
            self._body = body

        def read(self, *a):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import urllib.request

    # Response missing 'records'
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **kw: _FakeResponse(json.dumps({"unrelated_field": []}).encode("utf-8")),
    )

    result = providers.fetch_with_fallback(
        source="inspection",
        fetch_args={
            "inspection_date": "2026-05-15", "route": "RT-A", "area": "A", "severity_min": "low",
        },
    )
    assert result.data_source == providers.DEMO_FALLBACK
    assert any("records" in n.lower() or "fell back" in n for n in result.notes)


# ---------------------------------------------------------------------------
# Demo path remains deterministic (no regression for existing tests)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source", ["trend", "fault_context", "failure_data", "closure_items", "inspection"])
def test_demo_path_produces_data(providers, monkeypatch, source):
    monkeypatch.delenv("DEER_FLOW_DATA_PROVIDER", raising=False)
    provider = providers.get_provider(source)
    result = _invoke_demo(provider, source)
    assert isinstance(result.data, dict) and result.data


def test_failure_data_demo_respects_method_routing(providers, monkeypatch):
    """Demo provider must populate only the requested method's seed."""
    monkeypatch.delenv("DEER_FLOW_DATA_PROVIDER", raising=False)
    provider = providers.get_provider("failure_data", mode="demo")
    for method in ("five_why", "fishbone", "fmea"):
        result = provider.fetch(
            asset_id="P-001", failure_mode="x", analysis_method=method, evidence_range="",
        )
        seed = result.data["method_seed"]
        assert seed[method] is not None, f"demo failure_data must populate seed[{method}]"
        # And only that one
        for other in ("five_why", "fishbone", "fmea"):
            if other != method:
                assert seed[other] is None, f"demo seeded {other} when method={method}"
