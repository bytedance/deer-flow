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
assert_fallback_note = _helpers.assert_fallback_note
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


def _load_query_monthly(monkeypatch, tmp_path, *, provider_mode: str = "ins", factory_id: str = "FAC-001"):
    configure_report_env(monkeypatch, tmp_path, provider_mode=provider_mode, factory_id=factory_id)
    return load_script("query_monthly")


def _load_monthly_kpi():
    return load_script("monthly_kpi")


def _load_export_report():
    return load_script("export_report")


def test_monthly_query_defaults_to_demo_when_provider_not_enabled(monkeypatch, tmp_path):
    query_monthly = _load_query_monthly(monkeypatch, tmp_path, provider_mode="demo", factory_id="FAC-001")

    result = query_monthly.build_result(
        report_month="2026-05",
        equipment_ids=["EQ-1"],
        kpi_keys=["outlet_pressure"],
        compare_bases=["none"],
        eq_type="all",
        aggregate=False,
    )

    assert result["data_source"] == "demo_fallback"
    assert result["data_notes"] == []


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


def test_monthly_query_falls_back_when_features_tool_unavailable(monkeypatch, tmp_path):
    fake = FakeClient(
        components={"EQ-2K": machine_2k()},
        trend_table={("P_2K_1", "2k"): raw_rows_2k((1.2, 5.5))},
    )
    patch_ins_provider(monkeypatch, fake_client=fake, features_available=False, factory_id="FAC-001")
    query_monthly = _load_query_monthly(monkeypatch, tmp_path)

    result = query_monthly.build_result(
        report_month="2026-05",
        equipment_ids=["EQ-2K"],
        kpi_keys=["vibration_velocity_rms"],
        compare_bases=["none"],
        eq_type="all",
        aggregate=False,
    )

    assert result["data_source"] == "demo_fallback"
    assert_fallback_note(result["data_notes"], "features-tool")


def test_monthly_query_falls_back_when_ins_client_errors(monkeypatch, tmp_path):
    fake = FakeClient(
        components={"EQ-2K": machine_2k()},
        trend_table={("P_2K_1", "2k"): RuntimeError("socket timeout")},
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
    )

    assert result["data_source"] == "demo_fallback"
    assert_fallback_note(result["data_notes"], "socket timeout")


def test_monthly_query_falls_back_when_kpi_cannot_map_to_ins_point(monkeypatch, tmp_path):
    fake = FakeClient(
        components={"EQ-8K": machine_8k()},
        trend_table={("P_8K_1", "8k"): raw_rows_8k_pressures([1.2, 1.8])},
    )
    patch_ins_provider(monkeypatch, fake_client=fake, features_available=True, factory_id="FAC-001")
    query_monthly = _load_query_monthly(monkeypatch, tmp_path)

    result = query_monthly.build_result(
        report_month="2026-05",
        equipment_ids=["EQ-8K"],
        kpi_keys=["totally_made_up_kpi_xyz"],
        compare_bases=["none"],
        eq_type="all",
        aggregate=False,
    )

    assert result["data_source"] == "demo_fallback"
    assert result["data_notes"]


def test_monthly_query_downgrades_mixed_sources_for_compare_consistency(monkeypatch, tmp_path):
    query_monthly = _load_query_monthly(monkeypatch, tmp_path, provider_mode="demo", factory_id="FAC-001")

    current_payload = {
        "weekly": [],
        "aggregated": {"kpis_mean": {"outlet_pressure": 1.8}, "kpis_max": {}, "kpis_min": {}, "kpis_std": {}, "kpis_target_rate": {}},
        "maintenance": {"total_failures": 0, "total_uptime_hours": 720, "total_downtime_minutes": 0, "total_repair_minutes": 0, "mtbf_hours": None, "mttr_hours": None},
        "alarms": [],
        "critical_events": [],
        "improvement_tracking": [],
        "kpi_units": {"outlet_pressure": "MPa"},
    }
    compare_payload = {
        "weekly": [],
        "aggregated": {"kpis_mean": {"outlet_pressure": 1.2}, "kpis_max": {}, "kpis_min": {}, "kpis_std": {}, "kpis_target_rate": {}},
        "maintenance": {"total_failures": 1, "total_uptime_hours": 700, "total_downtime_minutes": 60, "total_repair_minutes": 30, "mtbf_hours": 700, "mttr_hours": 0.5},
        "alarms": [],
        "critical_events": [],
        "improvement_tracking": [],
        "kpi_units": {"outlet_pressure": "MPa"},
    }

    def _fake_fetch_month_with_provenance(report_month, equipment_ids, kpi_keys, eq_type="all", aggregate=False, equipment_meta=None, provider_mode=None):
        if provider_mode == "demo":
            return current_payload, "demo_fallback", []
        if report_month == "2026-05":
            return current_payload, "ins", []
        return compare_payload, "demo_fallback", ["forced compare fallback"]

    monkeypatch.setattr(query_monthly, "fetch_month_with_provenance", _fake_fetch_month_with_provenance)

    result = query_monthly.build_result(
        report_month="2026-05",
        equipment_ids=["EQ-8K"],
        kpi_keys=["outlet_pressure"],
        compare_bases=["previous_month"],
        eq_type="all",
        aggregate=False,
    )

    assert result["data_source"] == "demo_fallback"
    assert any("data_source mismatch" in note for note in result["data_notes"])


def test_monthly_query_mixed_compare_sources_refetches_with_explicit_demo_mode(monkeypatch, tmp_path):
    query_monthly = _load_query_monthly(monkeypatch, tmp_path, provider_mode="demo", factory_id="FAC-001")

    current_payload = {
        "weekly": [],
        "aggregated": {"kpis_mean": {"outlet_pressure": 1.8}, "kpis_max": {}, "kpis_min": {}, "kpis_std": {}, "kpis_target_rate": {}},
        "maintenance": {"total_failures": 0},
        "alarms": [],
    }
    compare_payload = {
        "weekly": [],
        "aggregated": {"kpis_mean": {"outlet_pressure": 1.2}, "kpis_max": {}, "kpis_min": {}, "kpis_std": {}, "kpis_target_rate": {}},
        "maintenance": {"total_failures": 1},
        "alarms": [],
    }
    demo_payload = {
        "weekly": [],
        "aggregated": {"kpis_mean": {"outlet_pressure": 1.5}, "kpis_max": {}, "kpis_min": {}, "kpis_std": {}, "kpis_target_rate": {}},
        "maintenance": {"total_failures": 0},
        "alarms": [],
    }
    calls: list[tuple[str, str | None]] = []

    def _fake_fetch_month_with_provenance(report_month, equipment_ids, kpi_keys, eq_type="all", aggregate=False, equipment_meta=None, provider_mode=None):
        calls.append((report_month, provider_mode))
        if provider_mode == "demo":
            return demo_payload, "demo_fallback", []
        if report_month == "2026-05":
            return current_payload, "ins", []
        return compare_payload, "demo_fallback", ["forced compare fallback"]

    monkeypatch.setattr(query_monthly, "fetch_month_with_provenance", _fake_fetch_month_with_provenance)

    result = query_monthly.build_result(
        report_month="2026-05",
        equipment_ids=["EQ-8K"],
        kpi_keys=["outlet_pressure"],
        compare_bases=["previous_month"],
        eq_type="all",
        aggregate=False,
    )

    assert result["data_source"] == "demo_fallback"
    assert result["current"] == demo_payload
    assert result["compare"]["previous_month"]["aggregated"] == compare_payload["aggregated"]
    assert calls == [
        ("2026-05", None),
        ("2026-04", None),
        ("2026-05", "demo"),
    ]


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
    assert result["data_source_banner"] == "> ✅ 数据来源：InS 实时接入"


@pytest.mark.parametrize(
    ("data_source", "data_notes", "expected_first_line"),
    [
        (
            "demo_fallback",
            [],
            "> ⚠️ 当前使用演示数据（fallback）。原因：未配置真实数据源（DEER_FLOW_DATA_PROVIDER 未设置为 ins）",
        ),
        (
            "demo_fallback",
            ["HTTP provider failed, fell back to demo: socket timeout"],
            "> ⚠️ 当前使用演示数据（fallback）。原因：HTTP provider failed, fell back to demo: socket timeout",
        ),
        ("ins", [], "> ✅ 数据来源：InS 实时接入"),
    ],
)
def test_monthly_export_banner_is_first_line_and_idempotent(
    monkeypatch,
    tmp_path,
    data_source,
    data_notes,
    expected_first_line,
):
    _load_query_monthly(monkeypatch, tmp_path)
    export_report = _load_export_report()

    payload = {
        "report_period": {"report_month": "2026-05", "month_start": "2026-05-01", "month_end": "2026-05-31", "day_count": 31},
        "compare_types": [],
        "compare_periods": {},
        "overall_status": {"level": "good", "summary": "ok"},
        "kpi_summary": [],
        "weekly_trend_chart": {},
        "anomaly_top_n": [],
        "critical_events": [],
        "improvement_tracking": [],
        "monthly_review": "ok",
        "next_month_plan": [],
        "data_source": data_source,
        "data_notes": data_notes,
    }

    first = export_report.render_monthly_markdown(payload)
    assert first.splitlines()[0] == expected_first_line

    same = export_report.render_monthly_markdown(payload)
    assert same == first

    second = export_report.render_monthly_markdown(
        {
            **payload,
            "data_source": "ins" if data_source == "demo_fallback" else "demo_fallback",
            "data_notes": [] if data_source == "demo_fallback" else ["forced fallback for rerender"],
        }
    )
    assert second.splitlines()[0] != "# 设备运行月报"
