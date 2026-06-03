"""Tests for skills/custom/daily-report/scripts/query_daily.py.

After the demo data path was removed, every data fetch goes through the
InS-backed provider. These tests pin the script's CLI / validation / output
contract, mocking ``fetch_day_with_provenance`` with InS-tagged synthetic
payloads so we exercise ``build_result`` and ``main`` without standing up
the real provider stack.

For end-to-end InS provider tests see
``test_ai_report_daily_ins_provider.py``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "skills" / "custom" / "daily-report" / "scripts" / "query_daily.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("query_daily", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ins_day_payload(date_str: str, equipment_ids: list[str], kpi_keys: list[str]) -> dict:
    """Return a minimal InS-shaped daily payload, deterministic on inputs."""
    return {
        "kpis": {key: 0.5 for key in kpi_keys},
        "kpi_units": {key: "%" for key in kpi_keys},
        "hourly_runtime_rate": [0.5] * 24,
        "alarms": [],
        "marker": f"ins_{date_str}_{'-'.join(equipment_ids)}",
    }


def _stub_ins_fetch(query_daily, calls: list[str] | None = None):
    """Install a fake ``fetch_day_with_provenance`` that returns InS-tagged data."""

    def fake_fetch(date_str, equipment_ids, kpi_keys, eq_type="all",
                   include_per_equipment=False, equipment_meta=None):
        if calls is not None:
            calls.append(date_str)
        return _ins_day_payload(date_str, equipment_ids, kpi_keys), "ins", []

    query_daily.fetch_day_with_provenance = fake_fetch
    return fake_fetch


@pytest.fixture()
def query_daily(tmp_path, monkeypatch):
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.delenv("DATA_PLATFORM_URL", raising=False)
    monkeypatch.delenv("DATA_API_URL", raising=False)
    module = _load_module()
    _stub_ins_fetch(module)
    return module


def test_build_result_previous_day(query_daily):
    result = query_daily.build_result(
        date_str="2026-05-13",
        equipment_ids=["E001"],
        kpi_keys=["runtime_rate"],
        compare="previous_day",
    )
    assert result["report_date"] == "2026-05-13"
    assert result["compare_type"] == "previous_day"
    assert result["compare_date"] == "2026-05-12"
    assert result["compare"] is not None
    assert result["current"]["kpis"]["runtime_rate"] is not None
    assert result["data_source"] == "ins"
    assert result["data_notes"] == []


def test_build_result_previous_week(query_daily):
    result = query_daily.build_result(
        date_str="2026-05-13",
        equipment_ids=["E001"],
        kpi_keys=["runtime_rate"],
        compare="previous_week",
    )
    expected = (datetime.strptime("2026-05-13", "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    assert result["compare_type"] == "previous_week"
    assert result["compare_date"] == expected


def test_build_result_no_compare(query_daily):
    result = query_daily.build_result(
        date_str="2026-05-13",
        equipment_ids=["E001"],
        kpi_keys=["runtime_rate"],
        compare="none",
    )
    assert result["compare"] is None
    assert result["compare_type"] == "none"
    assert result["data_source"] == "ins"
    assert result["data_notes"] == []


def test_writes_to_output_dir(query_daily, tmp_path):
    result = query_daily.build_result(
        date_str="2026-05-13",
        equipment_ids=["E001"],
        kpi_keys=["runtime_rate"],
        compare="previous_day",
    )
    out_path = query_daily.write_payload(result)
    assert out_path.parent == tmp_path
    assert out_path.name == "daily_data.json"
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["report_date"] == "2026-05-13"
    assert loaded["data_source"] == "ins"


def test_main_accepts_form_csv_payload(query_daily, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_daily.py",
            "--date",
            "2026-05-13",
            "--equipment",
            "E001,E002",
            "--kpis",
            "runtime_rate,downtime_count",
            "--compare",
            "previous_day",
        ],
    )
    assert query_daily.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["output"] == str(tmp_path / "daily_data.json")
    loaded = json.loads((tmp_path / "daily_data.json").read_text(encoding="utf-8"))
    assert loaded["equipment_ids"] == ["E001", "E002"]
    assert loaded["kpi_keys"] == ["runtime_rate", "downtime_count"]
    assert loaded["data_source"] == "ins"


def test_main_rejects_empty_equipment(query_daily, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["query_daily.py", "--date", "2026-05-13", "--equipment", "", "--kpis", "runtime_rate"],
    )
    assert query_daily.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["error"] == "--equipment must be a non-empty CSV"


def test_main_rejects_invalid_equipment_id(query_daily, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["query_daily.py", "--date", "2026-05-13", "--equipment", "E001,$(touch pwned)", "--kpis", "runtime_rate"],
    )
    assert query_daily.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["error"] == "--equipment contains invalid equipment id(s): $(touch pwned)"


def test_main_rejects_invalid_kpi_key_format(query_daily, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["query_daily.py", "--date", "2026-05-13", "--equipment", "E001", "--kpis", "runtime_rate,$bad"],
    )
    assert query_daily.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["error"] == "--kpis contains invalid KPI key(s): $bad"


def test_main_rejects_unsupported_kpi_key(query_daily, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["query_daily.py", "--date", "2026-05-13", "--equipment", "E001", "--kpis", "runtime_rate,oee"],
    )
    assert query_daily.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["error"] == "--kpis contains unsupported KPI key(s): oee"


def test_main_deduplicates_equipment_and_kpis(query_daily, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_daily.py",
            "--date",
            "2026-05-13",
            "--equipment",
            "E001,E002,E001",
            "--kpis",
            "runtime_rate,downtime_count,runtime_rate",
        ],
    )
    assert query_daily.main() == 0
    json.loads(capsys.readouterr().out)
    loaded = json.loads((tmp_path / "daily_data.json").read_text(encoding="utf-8"))
    assert loaded["equipment_ids"] == ["E001", "E002"]
    assert loaded["kpi_keys"] == ["runtime_rate", "downtime_count"]


def test_new_kpi_units_registered(query_daily):
    """All 11 KPI keys must be in KPI_UNITS."""
    expected = {
        "runtime_rate", "downtime_count", "alarm_count", "output",
        "corrosion_rate", "thickness_loss", "vibration_level", "bearing_temp",
        "flow_rate", "outlet_pressure", "valve_temp",
    }
    assert expected.issubset(set(query_daily.KPI_UNITS.keys()))


# ---------------------------------------------------------------------------
# Provenance propagation — build_result must preserve the InS data_source tag
# and notes returned by fetch_day_with_provenance for both current and compare
# blocks, with no demo-fallback rewriting.
# ---------------------------------------------------------------------------


def test_build_result_propagates_ins_notes(query_daily, monkeypatch):
    def fake_fetch(date_str, equipment_ids, kpi_keys, eq_type="all",
                   include_per_equipment=False, equipment_meta=None):
        # Current day carries one note; compare day adds another.
        note = "note-current" if date_str == "2026-05-13" else "note-compare"
        return ({"kpis": {"runtime_rate": 0.9}, "marker": f"ins_{date_str}"}, "ins", [note])

    monkeypatch.setattr(query_daily, "fetch_day_with_provenance", fake_fetch)

    result = query_daily.build_result(
        date_str="2026-05-13",
        equipment_ids=["E001"],
        kpi_keys=["runtime_rate"],
        compare="previous_day",
    )

    assert result["data_source"] == "ins"
    assert result["current"]["marker"] == "ins_2026-05-13"
    assert result["compare"]["marker"] == "ins_2026-05-12"
    assert result["data_notes"] == ["note-current", "note-compare"]


def test_build_result_no_compare_keeps_current_source(query_daily, monkeypatch):
    """When compare='none' there is no compare fetch — data_source / notes
    come straight from the single current-day fetch."""

    def fake_fetch(date_str, equipment_ids, kpi_keys, eq_type="all",
                   include_per_equipment=False, equipment_meta=None):
        return ({"kpis": {"runtime_rate": 0.88}, "marker": "ins_only"}, "ins", ["note-a"])

    monkeypatch.setattr(query_daily, "fetch_day_with_provenance", fake_fetch)

    result = query_daily.build_result(
        date_str="2026-05-13",
        equipment_ids=["E001"],
        kpi_keys=["runtime_rate"],
        compare="none",
    )
    assert result["data_source"] == "ins"
    assert result["compare"] is None
    assert result["data_notes"] == ["note-a"]


def test_build_result_propagates_http_provider_error(query_daily, monkeypatch):
    """If the InS provider raises, build_result must not swallow it.

    The CLI catches the exception in ``main()`` and writes a JSON error blob;
    callers of ``build_result`` directly (weekly/monthly aggregators) rely on
    the exception bubbling up.
    """

    class _Boom(Exception):
        pass

    def fake_fetch(*args, **kwargs):
        raise _Boom("ins exploded")

    monkeypatch.setattr(query_daily, "fetch_day_with_provenance", fake_fetch)

    with pytest.raises(_Boom):
        query_daily.build_result(
            date_str="2026-05-13",
            equipment_ids=["E001"],
            kpi_keys=["runtime_rate"],
            compare="none",
        )


def test_main_emits_error_json_when_fetch_raises(query_daily, monkeypatch, capsys, tmp_path):
    """main() must convert any fetch exception into ``{"error": "...""}`` on
    stdout instead of bubbling and instead of writing daily_data.json."""

    def fake_fetch(*args, **kwargs):
        raise RuntimeError("ins unreachable")

    monkeypatch.setattr(query_daily, "fetch_day_with_provenance", fake_fetch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_daily.py",
            "--date", "2026-05-13",
            "--equipment", "E001",
            "--kpis", "runtime_rate",
            "--compare", "none",
        ],
    )
    rc = query_daily.main()
    out = capsys.readouterr().out.strip()
    assert rc == 0
    payload = json.loads(out)
    assert "error" in payload
    assert "RuntimeError" in payload["error"]
    assert "ins unreachable" in payload["error"]
    assert not (tmp_path / "daily_data.json").exists()


# ---------------------------------------------------------------------------
# KPI auto-substitution — when --kpis is left at its argparse default and the
# equipment type is detected as a specific type (e.g. pump), the script must
# swap 8K/9K defaults for type-appropriate KPIs so pumps get 2K vibration KPIs
# instead of runtime_rate / downtime_count / alarm_count that return no data.
# ---------------------------------------------------------------------------


def test_kpi_substitution_for_pump_equipment_mode(query_daily, monkeypatch, capsys, tmp_path):
    """Default KPIs must be swapped to pump-specific KPIs when auto-detection
    identifies the equipment as pump type."""
    calls: list[dict] = []

    def fake_fetch(date_str, equipment_ids, kpi_keys, eq_type="all",
                   include_per_equipment=False, equipment_meta=None):
        calls.append({"kpi_keys": list(kpi_keys), "eq_type": eq_type})
        return _ins_day_payload(date_str, equipment_ids, kpi_keys), "ins", []

    monkeypatch.setattr(query_daily, "fetch_day_with_provenance", fake_fetch)
    # Simulate auto-detection: _detect_equipment_type returns "pump"
    monkeypatch.setattr(query_daily, "_detect_equipment_type", lambda ids: "pump")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_daily.py",
            "--date", "2026-05-13",
            "--equipment", "PP-001",
            # No --kpis → argparse default "runtime_rate,downtime_count,alarm_count"
            "--compare", "none",
        ],
    )
    rc = query_daily.main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "error" not in out
    assert len(calls) == 1
    # Default KPIs must have been replaced with pump-specific ones
    assert calls[0]["kpi_keys"] == ["vibration_velocity_rms", "vibration_acceleration_peak", "bearing_temp", "kurtosis_index"]
    assert calls[0]["eq_type"] == "pump"


def test_kpi_substitution_not_applied_when_custom_kpis_provided(query_daily, monkeypatch, capsys):
    """When the caller explicitly passes --kpis, the substitution must NOT fire
    even if the equipment type is pump — the caller asked for specific KPIs."""
    calls: list[dict] = []

    def fake_fetch(date_str, equipment_ids, kpi_keys, eq_type="all",
                   include_per_equipment=False, equipment_meta=None):
        calls.append({"kpi_keys": list(kpi_keys), "eq_type": eq_type})
        return _ins_day_payload(date_str, equipment_ids, kpi_keys), "ins", []

    monkeypatch.setattr(query_daily, "fetch_day_with_provenance", fake_fetch)
    monkeypatch.setattr(query_daily, "_detect_equipment_type", lambda ids: "pump")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_daily.py",
            "--date", "2026-05-13",
            "--equipment", "PP-001",
            "--kpis", "runtime_rate,alarm_count",
            "--compare", "none",
        ],
    )
    rc = query_daily.main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "error" not in out
    # Custom KPIs must be preserved — no substitution
    assert calls[0]["kpi_keys"] == ["runtime_rate", "alarm_count"]


def test_kpi_substitution_not_applied_for_all_type(query_daily, monkeypatch, capsys):
    """When eq_type stays 'all', the substitution must NOT fire."""
    calls: list[dict] = []

    def fake_fetch(date_str, equipment_ids, kpi_keys, eq_type="all",
                   include_per_equipment=False, equipment_meta=None):
        calls.append({"kpi_keys": list(kpi_keys), "eq_type": eq_type})
        return _ins_day_payload(date_str, equipment_ids, kpi_keys), "ins", []

    monkeypatch.setattr(query_daily, "fetch_day_with_provenance", fake_fetch)
    # Auto-detection returns "all" (mixed types or undetermined)
    monkeypatch.setattr(query_daily, "_detect_equipment_type", lambda ids: "all")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_daily.py",
            "--date", "2026-05-13",
            "--equipment", "E001,E002",
            "--compare", "none",
        ],
    )
    rc = query_daily.main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "error" not in out
    # Default KPIs preserved for "all" type
    assert calls[0]["kpi_keys"] == ["runtime_rate", "downtime_count", "alarm_count"]


def test_kpi_substitution_for_rotating_machinery(query_daily, monkeypatch, capsys):
    """Rotating machinery must also get its type-specific KPIs substituted."""
    calls: list[dict] = []

    def fake_fetch(date_str, equipment_ids, kpi_keys, eq_type="all",
                   include_per_equipment=False, equipment_meta=None):
        calls.append({"kpi_keys": list(kpi_keys), "eq_type": eq_type})
        return _ins_day_payload(date_str, equipment_ids, kpi_keys), "ins", []

    monkeypatch.setattr(query_daily, "fetch_day_with_provenance", fake_fetch)
    monkeypatch.setattr(query_daily, "_detect_equipment_type", lambda ids: "rotating_machinery")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_daily.py",
            "--date", "2026-05-13",
            "--equipment", "RM-001",
            "--compare", "none",
        ],
    )
    rc = query_daily.main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "error" not in out
    assert calls[0]["kpi_keys"] == ["runtime_rate", "vibration_level", "bearing_temp", "downtime_count"]


def test_constants_match_list_equipment(query_daily):
    """The per-type KPI lists in query_daily must match list_equipment's
    EQUIPMENT_TYPE_KPIS."""
    import importlib.util
    le_path = SCRIPT_PATH.parent / "list_equipment.py"
    spec = importlib.util.spec_from_file_location("list_equipment", le_path)
    le = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(le)

    for eq_type in ["rotating_machinery", "pump", "reciprocating_machinery", "static_equipment"]:
        le_kpis = le.EQUIPMENT_TYPE_KPIS[eq_type]
        qd_kpis = query_daily._EQUIPMENT_TYPE_DEFAULT_KPIS[eq_type]
        assert qd_kpis == le_kpis, f"KPI mismatch for {eq_type}: query_daily={qd_kpis} vs list_equipment={le_kpis}"
