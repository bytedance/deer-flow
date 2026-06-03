"""Tests for monthly report provider (direct InS path).

Covers: InsMonthlyProvider, _resolve_mode pinning, get_provider routing.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "skills" / "custom" / "monthly-report" / "scripts"


def _load(name: str):
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    with patch.dict(os.environ, {"FEATURES_TOOL_ROOT": ""}):
        spec.loader.exec_module(module)
    return module


def _load_fresh(name: str):
    sys.modules.pop(name, None)
    return _load(name)


# ---------------------------------------------------------------------------
# _resolve_mode tests
# ---------------------------------------------------------------------------


class TestResolveMode:
    """Tests for _data_providers._resolve_mode with monthly source."""

    def test_monthly_pinned_to_ins(self, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_DATA_PROVIDER", raising=False)
        dp = _load_fresh("_data_providers")
        assert dp._resolve_mode("monthly", None) == "ins"
        assert dp._resolve_mode("daily", None) == "ins"
        assert dp._resolve_mode("weekly", None) == "ins"

    def test_env_ins_does_not_change_pinned_sources(self, monkeypatch):
        monkeypatch.setenv("DEER_FLOW_DATA_PROVIDER", "ins")
        dp = _load_fresh("_data_providers")
        assert dp._resolve_mode("monthly", None) == "ins"

    def test_explicit_mode_overrides_pin(self, monkeypatch):
        monkeypatch.setenv("DEER_FLOW_DATA_PROVIDER", "ins")
        dp = _load_fresh("_data_providers")
        assert dp._resolve_mode("monthly", "platform") == "platform"
        assert dp._resolve_mode("monthly", "ins") == "ins"

    def test_ins_only_source_still_pinned(self, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_DATA_PROVIDER", raising=False)
        dp = _load_fresh("_data_providers")
        assert dp._resolve_mode("trend", None) == "ins"


# ---------------------------------------------------------------------------
# get_provider tests
# ---------------------------------------------------------------------------


class TestGetProvider:
    """Tests for get_provider routing with monthly source pinned to ins."""

    def test_get_provider_monthly_default_ins(self, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_DATA_PROVIDER", raising=False)
        dp = _load_fresh("_data_providers")
        _load("_data_provider_impls")
        provider = dp.get_provider("monthly")
        from _data_provider_impls import InsMonthlyProvider
        assert isinstance(provider, InsMonthlyProvider)

    def test_get_provider_monthly_ins_explicit(self, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_DATA_PROVIDER", raising=False)
        dp = _load_fresh("_data_providers")
        _load("_data_provider_impls")
        provider = dp.get_provider("monthly", mode="ins")
        from _data_provider_impls import InsMonthlyProvider
        assert isinstance(provider, InsMonthlyProvider)

    def test_ins_mode_registered(self, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_DATA_PROVIDER", raising=False)
        _load_fresh("_data_providers")
        _load("_data_provider_impls")
        from _data_providers import list_registered
        modes = list_registered()["monthly"]
        assert "ins" in modes


# ---------------------------------------------------------------------------
# InsMonthlyProvider tests
# ---------------------------------------------------------------------------


class TestDirectInsMonthlyProvider:
    """Tests for DirectInsMonthlyProvider.fetch()."""

    def test_fetch_returns_provider_result_with_data_source(self, monkeypatch):
        _load_fresh("_data_providers")
        _load_fresh("_data_provider_impls")
        from _data_providers import get_provider, ProviderResult, INS_SUCCESS

        provider = get_provider("monthly")

        fake_daily = [
            {"date": "2026-06-01", "kpis": {"runtime_rate": 0.9}, "kpi_units": {"runtime_rate": "%"}, "alarms": []},
            {"date": "2026-06-02", "kpis": {"runtime_rate": 0.85}, "kpi_units": {"runtime_rate": "%"}, "alarms": []},
        ]
        with patch("_data_provider_impls.fetch_daily_series_payload", return_value=fake_daily):
            result = provider.fetch(
                report_month="2026-06",
                equipment_ids=["EQ1"],
                kpi_keys=["runtime_rate"],
                eq_type="all",
            )

        assert isinstance(result, ProviderResult)
        assert result.data_source == INS_SUCCESS
        assert result.data["daily_entries"] == fake_daily

    def test_fetch_raises_http_provider_error_on_ins_failure(self, monkeypatch):
        _load_fresh("_data_providers")
        _load_fresh("_data_provider_impls")
        from _data_providers import get_provider, HttpProviderError

        provider = get_provider("monthly")

        with patch("_data_provider_impls.fetch_daily_series_payload", side_effect=HttpProviderError("InS unreachable")):
            with pytest.raises(HttpProviderError, match="InS unreachable"):
                provider.fetch(
                    report_month="2026-06",
                    equipment_ids=["EQ1"],
                    kpi_keys=["runtime_rate"],
                )

    def test_fetch_wraps_unexpected_errors(self, monkeypatch):
        _load_fresh("_data_providers")
        _load_fresh("_data_provider_impls")
        from _data_providers import get_provider, HttpProviderError

        provider = get_provider("monthly")

        with patch("_data_provider_impls.fetch_daily_series_payload", side_effect=RuntimeError("boom")):
            with pytest.raises(HttpProviderError, match="RuntimeError: boom"):
                provider.fetch(
                    report_month="2026-06",
                    equipment_ids=["EQ1"],
                    kpi_keys=["runtime_rate"],
                )
