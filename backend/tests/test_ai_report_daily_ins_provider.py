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
raw_rows_2k_velocity_only = _helpers.raw_rows_2k_velocity_only
raw_rows_6k = _helpers.raw_rows_6k
raw_rows_8k_pressures = _helpers.raw_rows_8k_pressures


@pytest.fixture(autouse=True)
def _clear_modules():
    clear_script_modules()
    yield
    clear_script_modules()


def _load_query_daily(monkeypatch, tmp_path, *, factory_id: str = "FAC-001"):
    configure_report_env(monkeypatch, tmp_path, provider_mode=None, factory_id=factory_id)
    return load_script("query_daily")


def _load_daily_kpi():
    return load_script("daily_kpi")


def test_daily_query_uses_ins_for_2k_payload(monkeypatch, tmp_path):
    fake = FakeClient(
        components={"EQ-2K": machine_2k()},
        trend_table={
            ("P_2K_1", "2k"): raw_rows_2k((1.2, 5.5), (2.6, 9.8), (4.8, 21.0)),
        },
    )
    patch_ins_provider(monkeypatch, fake_client=fake, features_available=True, factory_id="FAC-001")
    query_daily = _load_query_daily(monkeypatch, tmp_path)

    result = query_daily.build_result(
        date_str="2026-05-01",
        equipment_ids=["EQ-2K"],
        kpi_keys=["vibration_velocity_rms", "vibration_acceleration_peak"],
        compare="none",
        eq_type="all",
        include_per_equipment=False,
        equipment_meta={"EQ-2K": {"name": "P-3101A"}},
    )

    assert result["data_source"] == "ins"
    assert result["data_notes"] == []
    assert result["equipment_names"]["EQ-2K"] == "P-3101A"
    assert result["current"]["kpis"]["vibration_velocity_rms"] == pytest.approx((1.2 + 2.6 + 4.8) / 3, abs=1e-4)
    assert result["current"]["kpis"]["vibration_acceleration_peak"] == pytest.approx((5.5 + 9.8 + 21.0) / 3, abs=1e-4)
    assert fake.trend_calls
    call = fake.trend_calls[0]
    assert call["kwargs"]["endpoint_series"] == "2k"
    assert "v_rms" in call["features"]
    assert "a_peak" in call["features"]


def test_daily_query_uses_ins_for_8k_payload(monkeypatch, tmp_path):
    fake = FakeClient(
        components={"EQ-8K": machine_8k()},
        trend_table={
            ("P_8K_1", "8k"): raw_rows_8k_pressures([1.2, 1.8, 2.4]),
        },
    )
    patch_ins_provider(monkeypatch, fake_client=fake, features_available=True, factory_id="FAC-001")
    query_daily = _load_query_daily(monkeypatch, tmp_path)

    result = query_daily.build_result(
        date_str="2026-05-01",
        equipment_ids=["EQ-8K"],
        kpi_keys=["outlet_pressure"],
        compare="none",
        eq_type="all",
        include_per_equipment=False,
    )

    assert result["data_source"] == "ins"
    assert result["data_notes"] == []
    assert result["current"]["kpis"]["outlet_pressure"] == pytest.approx(1.8, abs=1e-4)
    call = fake.trend_calls[0]
    assert call["kwargs"]["endpoint_series"] == "8k"
    assert "value" in call["features"]


def test_daily_query_uses_value_field_for_8k_bearing_temp(monkeypatch, tmp_path):
    components = {
        "EQ-8K-BT": [
            {
                "id": "EQ-8K-BT",
                "name": "C001-bearing",
                "type_num": 1,
                "points": [
                    {
                        "id": "P_8K_BT",
                        "name": "压缩机驱动端支撑轴承温度",
                        "type_num": 82,
                        "endpoint_series": "8k",
                        "h_alarm": 80.0,
                        "hh_alarm": 90.0,
                    }
                ],
            }
        ]
    }
    rows = [
        {
            "component_id": "P_8K_BT",
            "time_ms": str(1700000000000 + index * 60_000),
            "time": "t",
            "values": {"value": value},
        }
        for index, value in enumerate([62.2, 62.0, 61.8, 62.4])
    ]
    fake = FakeClient(
        components=components,
        trend_table={("P_8K_BT", "8k"): rows},
    )
    patch_ins_provider(monkeypatch, fake_client=fake, features_available=True, factory_id="FAC-001")
    query_daily = _load_query_daily(monkeypatch, tmp_path)

    result = query_daily.build_result(
        date_str="2026-05-01",
        equipment_ids=["EQ-8K-BT"],
        kpi_keys=["bearing_temp"],
        compare="none",
        eq_type="rotating_machinery",
        include_per_equipment=False,
    )

    assert result["data_source"] == "ins"
    assert result["current"]["kpis"]["bearing_temp"] == pytest.approx((62.2 + 62.0 + 61.8 + 62.4) / 4, abs=1e-4)
    assert "value" in fake.trend_calls[0]["features"]


def test_daily_query_uses_ins_for_6k_payload(monkeypatch, tmp_path):
    fake = FakeClient(
        components={"EQ-6K": machine_6k()},
        trend_table={
            ("P_6K_1", "6k"): raw_rows_6k((0.1, 10.0), (0.2, 9.8), (0.15, 9.7)),
        },
    )
    patch_ins_provider(monkeypatch, fake_client=fake, features_available=True, factory_id="FAC-001")
    query_daily = _load_query_daily(monkeypatch, tmp_path)

    result = query_daily.build_result(
        date_str="2026-05-01",
        equipment_ids=["EQ-6K"],
        kpi_keys=["corrosion_rate", "thickness_loss"],
        compare="none",
        eq_type="all",
        include_per_equipment=False,
    )

    assert result["data_source"] == "ins"
    assert result["data_notes"] == []
    assert result["current"]["kpis"]["corrosion_rate"] == pytest.approx((0.1 + 0.2 + 0.15) / 3, abs=1e-4)
    assert result["current"]["kpis"]["thickness_loss"] == pytest.approx(0.3, abs=1e-4)
    features = fake.trend_calls[0]["features"]
    assert "corrosionRate" in features or "thickness" in features
    assert fake.trend_calls[0]["kwargs"]["endpoint_series"] == "6k"


def test_daily_query_groups_mixed_endpoint_series(monkeypatch, tmp_path):
    fake = FakeClient(
        components={"EQ-MIX": machine_mixed()},
        trend_table={
            ("PMX_2K", "2k"): raw_rows_2k((1.1, 5.0), (1.3, 6.0)),
            ("PMX_6K", "6k"): raw_rows_6k((0.1, 10.0), (0.2, 9.9)),
            ("PMX_8K", "8k"): raw_rows_8k_pressures([1.0, 1.5]),
        },
    )
    patch_ins_provider(monkeypatch, fake_client=fake, features_available=True, factory_id="FAC-001")
    query_daily = _load_query_daily(monkeypatch, tmp_path)

    result = query_daily.build_result(
        date_str="2026-05-01",
        equipment_ids=["EQ-MIX"],
        kpi_keys=["vibration_velocity_rms", "corrosion_rate", "outlet_pressure"],
        compare="none",
        eq_type="all",
        include_per_equipment=False,
    )

    assert result["data_source"] == "ins"
    assert len(fake.trend_calls) == 3
    series = {call["kwargs"]["endpoint_series"] for call in fake.trend_calls}
    assert series == {"2k", "6k", "8k"}


def test_daily_query_raises_when_features_tool_unavailable(monkeypatch, tmp_path):
    fake = FakeClient(
        components={"EQ-2K": machine_2k()},
        trend_table={("P_2K_1", "2k"): raw_rows_2k((1.2, 5.5))},
    )
    provider = patch_ins_provider(
        monkeypatch, fake_client=fake, features_available=False, factory_id="FAC-001"
    )
    query_daily = _load_query_daily(monkeypatch, tmp_path)

    with pytest.raises(provider.HttpProviderError) as excinfo:
        query_daily.build_result(
            date_str="2026-05-01",
            equipment_ids=["EQ-2K"],
            kpi_keys=["vibration_velocity_rms"],
            compare="none",
            eq_type="all",
            include_per_equipment=False,
        )
    assert "features-tool" in str(excinfo.value).lower()


def test_daily_query_raises_when_ins_client_errors(monkeypatch, tmp_path):
    fake = FakeClient(
        components={"EQ-2K": machine_2k()},
        trend_table={("P_2K_1", "2k"): RuntimeError("socket timeout")},
    )
    patch_ins_provider(monkeypatch, fake_client=fake, features_available=True, factory_id="FAC-001")
    query_daily = _load_query_daily(monkeypatch, tmp_path)

    with pytest.raises(Exception) as excinfo:
        query_daily.build_result(
            date_str="2026-05-01",
            equipment_ids=["EQ-2K"],
            kpi_keys=["vibration_velocity_rms"],
            compare="none",
            eq_type="all",
            include_per_equipment=False,
        )
    assert "socket timeout" in str(excinfo.value)


def test_daily_query_raises_when_kpi_cannot_map_to_ins_point(monkeypatch, tmp_path):
    fake = FakeClient(
        components={"EQ-8K": machine_8k()},
        trend_table={("P_8K_1", "8k"): raw_rows_8k_pressures([1.2, 1.8])},
    )
    provider = patch_ins_provider(
        monkeypatch, fake_client=fake, features_available=True, factory_id="FAC-001"
    )
    query_daily = _load_query_daily(monkeypatch, tmp_path)

    with pytest.raises(provider.HttpProviderError):
        query_daily.build_result(
            date_str="2026-05-01",
            equipment_ids=["EQ-8K"],
            kpi_keys=["totally_made_up_kpi_xyz"],
            compare="none",
            eq_type="all",
            include_per_equipment=False,
        )


def test_daily_query_main_emits_error_json_for_ins_failure(monkeypatch, tmp_path, capsys):
    """End-to-end: an InS failure makes `query_daily.main` write a JSON error to stdout."""
    fake = FakeClient(
        components={"EQ-8K": machine_8k()},
        trend_table={("P_8K_1", "8k"): RuntimeError("upstream 503")},
    )
    patch_ins_provider(monkeypatch, fake_client=fake, features_available=True, factory_id="FAC-001")
    query_daily = _load_query_daily(monkeypatch, tmp_path)

    monkeypatch.setattr(
        "sys.argv",
        [
            "query_daily.py",
            "--date",
            "2026-05-01",
            "--equipment",
            "EQ-8K",
            "--kpis",
            "outlet_pressure",
            "--compare",
            "none",
            "--type",
            "all",
        ],
    )

    rc = query_daily.main()
    out = capsys.readouterr().out.strip()
    import json

    payload = json.loads(out)
    assert rc == 0
    assert "error" in payload
    assert "HttpProviderError" in payload["error"]
    assert not (tmp_path / "daily_data.json").exists()


def test_daily_query_counts_2k_alarm_threshold_crossings(monkeypatch, tmp_path):
    fake = FakeClient(
        components={"EQ-2K": machine_2k()},
        trend_table={
            ("P_2K_1", "2k"): raw_rows_2k_velocity_only([0.8, 2.1, 2.5, 3.2]),
        },
    )
    provider = patch_ins_provider(monkeypatch, fake_client=fake, features_available=True, factory_id="FAC-001")
    spec = dict(provider._KPI_FEATURE_MAP["vibration_velocity_rms"])
    spec["derivation"] = "alarm_count"
    provider._KPI_FEATURE_MAP["vibration_velocity_rms"] = spec
    query_daily = _load_query_daily(monkeypatch, tmp_path)

    result = query_daily.build_result(
        date_str="2026-05-01",
        equipment_ids=["EQ-2K"],
        kpi_keys=["vibration_velocity_rms"],
        compare="none",
        eq_type="all",
        include_per_equipment=False,
    )

    assert result["data_source"] == "ins"
    assert result["current"]["kpis"]["vibration_velocity_rms"] == 3


def test_daily_kpi_preserves_provenance_from_query_payload(monkeypatch, tmp_path):
    fake = FakeClient(
        components={"EQ-8K": machine_8k()},
        trend_table={("P_8K_1", "8k"): raw_rows_8k_pressures([1.1, 1.3, 1.8])},
    )
    patch_ins_provider(monkeypatch, fake_client=fake, features_available=True, factory_id="FAC-001")
    query_daily = _load_query_daily(monkeypatch, tmp_path)
    daily_kpi = _load_daily_kpi()

    payload = query_daily.build_result(
        date_str="2026-05-01",
        equipment_ids=["EQ-8K"],
        kpi_keys=["outlet_pressure"],
        compare="none",
        eq_type="all",
        include_per_equipment=False,
    )
    result = daily_kpi.compute(payload)

    assert payload["data_source"] == "ins"
    assert payload["data_notes"] == []
    assert result["data_source"] == "ins"
    assert result["data_notes"] == []
    assert "data_source_banner" not in result


def test_daily_kpi_missing_data_source_raises_key_error():
    daily_kpi = load_script("daily_kpi")

    payload = {
        "report_date": "2026-05-01",
        "equipment_ids": ["EQ-1"],
        "kpi_keys": ["outlet_pressure"],
        "current": {"kpis": {"outlet_pressure": 1.0}, "kpi_units": {}, "alarms": []},
        "compare": None,
        # NOTE: data_source intentionally omitted
        "data_notes": [],
    }

    with pytest.raises(KeyError):
        daily_kpi.compute(payload)
