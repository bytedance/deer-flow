from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "backend" / "tests" / "_ai_report_ins_test_helpers.py"

_spec = importlib.util.spec_from_file_location("_ai_report_ins_test_helpers", HELPER_PATH)
assert _spec is not None and _spec.loader is not None
_helpers = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("_ai_report_ins_test_helpers", _helpers)
_spec.loader.exec_module(_helpers)

FakeClient = _helpers.FakeClient
clear_script_modules = _helpers.clear_script_modules
configure_report_env = _helpers.configure_report_env
load_script = _helpers.load_script
machine_2k = _helpers.machine_2k
machine_6k = _helpers.machine_6k
machine_8k = _helpers.machine_8k
machine_mixed = _helpers.machine_mixed
patch_ins_provider = _helpers.patch_ins_provider
raw_rows_2k = _helpers.raw_rows_2k
raw_rows_6k = _helpers.raw_rows_6k
raw_rows_8k_pressures = _helpers.raw_rows_8k_pressures


@pytest.fixture(autouse=True)
def _clear_modules():
    clear_script_modules()
    yield
    clear_script_modules()


def _load_query_monthly(monkeypatch, tmp_path, *, factory_id: str = "FAC-001"):
    configure_report_env(monkeypatch, tmp_path, provider_mode=None, factory_id=factory_id)
    return load_script("query_monthly")


def _load_monthly_kpi():
    return load_script("monthly_kpi")


def test_monthly_query_uses_ins_for_2k_payload(monkeypatch, tmp_path):
    fake = FakeClient(
        components={"EQ-2K": machine_2k()},
        trend_table={("P_2K_1", "2k"): raw_rows_2k((1.2, 5.5), (2.6, 9.8), (4.8, 21.0))},
    )
    patch_ins_provider(monkeypatch, fake_client=fake, features_available=True, factory_id="FAC-001")
    query_monthly = _load_query_monthly(monkeypatch, tmp_path)

    result = query_monthly.build_result(
        report_month="2026-05",
        equipment_ids=["EQ-2K"],
        kpi_keys=["vibration_velocity_rms"],
        compare_bases=["none"],
        eq_type="all",
        aggregate=False,
        equipment_meta={"EQ-2K": {"name": "P-3101A"}},
    )

    assert result["data_source"] == "ins"
    assert result["data_notes"] == []
    assert result["equipment_names"]["EQ-2K"] == "P-3101A"
    assert result["current"]["aggregated"]["kpis_mean"]["vibration_velocity_rms"] is not None
    assert fake.trend_calls
    assert fake.trend_calls[0]["kwargs"]["endpoint_series"] == "2k"


def test_monthly_query_uses_ins_for_8k_payload(monkeypatch, tmp_path):
    fake = FakeClient(
        components={"EQ-8K": machine_8k()},
        trend_table={("P_8K_1", "8k"): raw_rows_8k_pressures([1.2, 1.8, 2.4])},
    )
    patch_ins_provider(monkeypatch, fake_client=fake, features_available=True, factory_id="FAC-001")
    query_monthly = _load_query_monthly(monkeypatch, tmp_path)

    result = query_monthly.build_result(
        report_month="2026-05",
        equipment_ids=["EQ-8K"],
        kpi_keys=["outlet_pressure"],
        compare_bases=["none"],
        eq_type="all",
        aggregate=False,
    )

    assert result["data_source"] == "ins"
    assert result["current"]["aggregated"]["kpis_mean"]["outlet_pressure"] == pytest.approx(1.8, abs=1e-4)
    assert fake.trend_calls[0]["kwargs"]["endpoint_series"] == "8k"


def test_monthly_query_uses_ins_for_6k_payload(monkeypatch, tmp_path):
    fake = FakeClient(
        components={"EQ-6K": machine_6k()},
        trend_table={("P_6K_1", "6k"): raw_rows_6k((0.1, 10.0), (0.2, 9.8), (0.15, 9.7))},
    )
    patch_ins_provider(monkeypatch, fake_client=fake, features_available=True, factory_id="FAC-001")
    query_monthly = _load_query_monthly(monkeypatch, tmp_path)

    result = query_monthly.build_result(
        report_month="2026-05",
        equipment_ids=["EQ-6K"],
        kpi_keys=["corrosion_rate", "thickness_loss"],
        compare_bases=["none"],
        eq_type="all",
        aggregate=False,
    )

    assert result["data_source"] == "ins"
    assert result["current"]["aggregated"]["kpis_mean"]["corrosion_rate"] == pytest.approx((0.1 + 0.2 + 0.15) / 3, abs=1e-4)
    assert result["current"]["aggregated"]["kpis_mean"]["thickness_loss"] == pytest.approx(0.3, abs=1e-4)
    assert fake.trend_calls[0]["kwargs"]["endpoint_series"] == "6k"


def test_monthly_query_groups_mixed_endpoint_series(monkeypatch, tmp_path):
    fake = FakeClient(
        components={"EQ-MIX": machine_mixed()},
        trend_table={
            ("PMX_2K", "2k"): raw_rows_2k((1.1, 5.0), (1.3, 6.0)),
            ("PMX_6K", "6k"): raw_rows_6k((0.1, 10.0), (0.2, 9.9)),
            ("PMX_8K", "8k"): raw_rows_8k_pressures([1.0, 1.5]),
        },
    )
    patch_ins_provider(monkeypatch, fake_client=fake, features_available=True, factory_id="FAC-001")
    query_monthly = _load_query_monthly(monkeypatch, tmp_path)

    result = query_monthly.build_result(
        report_month="2026-05",
        equipment_ids=["EQ-MIX"],
        kpi_keys=["vibration_velocity_rms", "corrosion_rate", "outlet_pressure"],
        compare_bases=["none"],
        eq_type="all",
        aggregate=False,
    )

    assert result["data_source"] == "ins"
    assert len(fake.trend_calls) >= 3
    series = {call["kwargs"]["endpoint_series"] for call in fake.trend_calls}
    assert series == {"2k", "6k", "8k"}


def test_monthly_query_raises_when_features_tool_unavailable(monkeypatch, tmp_path):
    fake = FakeClient(
        components={"EQ-2K": machine_2k()},
        trend_table={("P_2K_1", "2k"): raw_rows_2k((1.2, 5.5))},
    )
    provider = patch_ins_provider(
        monkeypatch, fake_client=fake, features_available=False, factory_id="FAC-001"
    )
    query_monthly = _load_query_monthly(monkeypatch, tmp_path)

    with pytest.raises(provider.HttpProviderError) as excinfo:
        query_monthly.build_result(
            report_month="2026-05",
            equipment_ids=["EQ-2K"],
            kpi_keys=["vibration_velocity_rms"],
            compare_bases=["none"],
            eq_type="all",
            aggregate=False,
        )
    assert "features-tool" in str(excinfo.value).lower()


def test_monthly_query_raises_when_ins_client_errors(monkeypatch, tmp_path):
    fake = FakeClient(
        components={"EQ-2K": machine_2k()},
        trend_table={("P_2K_1", "2k"): RuntimeError("socket timeout")},
    )
    patch_ins_provider(monkeypatch, fake_client=fake, features_available=True, factory_id="FAC-001")
    query_monthly = _load_query_monthly(monkeypatch, tmp_path)

    with pytest.raises(Exception) as excinfo:
        query_monthly.build_result(
            report_month="2026-05",
            equipment_ids=["EQ-2K"],
            kpi_keys=["vibration_velocity_rms"],
            compare_bases=["none"],
            eq_type="all",
            aggregate=False,
        )
    assert "socket timeout" in str(excinfo.value)


def test_monthly_query_raises_when_kpi_cannot_map_to_ins_point(monkeypatch, tmp_path):
    fake = FakeClient(
        components={"EQ-8K": machine_8k()},
        trend_table={("P_8K_1", "8k"): raw_rows_8k_pressures([1.2, 1.8])},
    )
    provider = patch_ins_provider(
        monkeypatch, fake_client=fake, features_available=True, factory_id="FAC-001"
    )
    query_monthly = _load_query_monthly(monkeypatch, tmp_path)

    with pytest.raises(provider.HttpProviderError):
        query_monthly.build_result(
            report_month="2026-05",
            equipment_ids=["EQ-8K"],
            kpi_keys=["totally_made_up_kpi_xyz"],
            compare_bases=["none"],
            eq_type="all",
            aggregate=False,
        )


def test_monthly_query_main_emits_error_json_for_ins_failure(monkeypatch, tmp_path, capsys):
    """End-to-end: an InS failure makes `query_monthly.main` write a JSON error to stdout."""
    fake = FakeClient(
        components={"EQ-2K": machine_2k()},
        trend_table={("P_2K_1", "2k"): RuntimeError("upstream 503")},
    )
    patch_ins_provider(monkeypatch, fake_client=fake, features_available=True, factory_id="FAC-001")
    query_monthly = _load_query_monthly(monkeypatch, tmp_path)

    monkeypatch.setattr(
        "sys.argv",
        [
            "query_monthly.py",
            "--report-month",
            "2026-05",
            "--equipment",
            "EQ-2K",
            "--kpis",
            "vibration_velocity_rms",
            "--compare",
            "none",
            "--type",
            "all",
        ],
    )

    rc = query_monthly.main()
    out = capsys.readouterr().out.strip()
    import json

    payload = json.loads(out)
    assert rc == 0
    assert "error" in payload
    assert "HttpProviderError" in payload["error"]
    assert not (tmp_path / "monthly_data.json").exists()


def test_monthly_kpi_preserves_provenance_from_query_payload(monkeypatch, tmp_path):
    fake = FakeClient(
        components={"EQ-8K": machine_8k()},
        trend_table={("P_8K_1", "8k"): raw_rows_8k_pressures([1.1, 1.3, 1.8])},
    )
    patch_ins_provider(monkeypatch, fake_client=fake, features_available=True, factory_id="FAC-001")
    query_monthly = _load_query_monthly(monkeypatch, tmp_path)
    monthly_kpi = _load_monthly_kpi()

    payload = query_monthly.build_result(
        report_month="2026-05",
        equipment_ids=["EQ-8K"],
        kpi_keys=["outlet_pressure"],
        compare_bases=["none"],
        eq_type="all",
        aggregate=False,
    )
    result = monthly_kpi.compute(payload)

    assert payload["data_source"] == "ins"
    assert payload["data_notes"] == []
    assert result["data_source"] == "ins"
    assert result["data_notes"] == []
    assert "data_source_banner" not in result


def test_monthly_kpi_missing_data_source_raises_key_error():
    monthly_kpi = load_script("monthly_kpi")

    payload = {
        "report_period": {"report_month": "2026-05", "month_start": "2026-05-01", "month_end": "2026-05-31", "day_count": 31},
        "equipment_ids": ["EQ-1"],
        "kpi_keys": ["outlet_pressure"],
        "current": {
            "weekly": [],
            "aggregated": {"kpis_mean": {"outlet_pressure": 1.0}, "kpis_max": {}, "kpis_min": {}, "kpis_std": {}, "kpis_target_rate": {}},
            "maintenance": {"total_failures": 0, "total_uptime_hours": 720, "total_downtime_minutes": 0, "total_repair_minutes": 0, "mtbf_hours": None, "mttr_hours": None},
            "alarms": [],
            "critical_events": [],
            "improvement_tracking": [],
            "kpi_units": {"outlet_pressure": "MPa"},
        },
        "compare": {},
        # NOTE: data_source intentionally omitted
        "data_notes": [],
    }

    with pytest.raises(KeyError):
        monthly_kpi.compute(payload)
