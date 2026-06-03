"""End-to-end contract test for the ai-report--daily Skill pipeline."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / "skills" / "custom" / "daily-report" / "scripts"


def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_fetch_day(date_str, equipment_ids, kpi_keys, eq_type="all", include_per_equipment=False, equipment_meta=None):
    """Stub fetch_day_with_provenance returning synthetic InS-tagged data."""
    _kpi_defaults = {
        "runtime_rate": 0.93,
        "downtime_count": 2,
        "alarm_count": 3,
        "vibration_level": 1.2,
        "bearing_temp": 65.0,
        "corrosion_rate": 0.05,
    }
    _units = {
        "runtime_rate": "%",
        "downtime_count": "次",
        "alarm_count": "条",
        "vibration_level": "mm/s",
        "bearing_temp": "℃",
        "corrosion_rate": "mm/a",
    }
    kpis = {k: _kpi_defaults.get(k, 1.0) for k in kpi_keys}
    data = {
        "kpis": kpis,
        "kpi_units": {k: _units.get(k, "") for k in kpis},
        "hourly_runtime_rate": [0.9] * 24,
        "alarms": [],
    }
    if include_per_equipment:
        per_eq: dict = {}
        for eid in equipment_ids:
            entry: dict = {"kpis": dict(kpis), "hourly_runtime_rate": [0.9] * 24}
            if equipment_meta and eid in equipment_meta:
                entry["name"] = equipment_meta[eid].get("name", eid)
                entry["area"] = equipment_meta[eid].get("area", "")
            per_eq[eid] = entry
        data["per_equipment"] = per_eq
    return (data, "ins", [])


def test_query_kpi_export_pipeline(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))

    query_daily = _load_module("query_daily")
    daily_kpi = _load_module("daily_kpi")
    export_report = _load_module("export_report")

    monkeypatch.setattr(query_daily, "fetch_day_with_provenance", _fake_fetch_day)

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
            "runtime_rate,downtime_count,alarm_count",
            "--compare",
            "previous_day",
        ],
    )
    assert query_daily.main() == 0
    query_result = json.loads(capsys.readouterr().out)
    assert query_result["output"] == str(tmp_path / "daily_data.json")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "daily_kpi.py",
            "--input",
            str(tmp_path / "daily_data.json"),
            "--output",
            str(tmp_path / "daily_kpi.json"),
        ],
    )
    assert daily_kpi.main() == 0
    kpi_result = json.loads(capsys.readouterr().out)
    assert kpi_result["output"] == str(tmp_path / "daily_kpi.json")

    kpi_payload = json.loads((tmp_path / "daily_kpi.json").read_text(encoding="utf-8"))
    assert kpi_payload["trend_chart"]["series"]
    assert kpi_payload["kpi_summary"]
    assert isinstance(kpi_payload["alarm_table"], list)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "export_report.py",
            "--input",
            str(tmp_path / "daily_kpi.json"),
            "--format",
            "md",
            "--output",
            str(tmp_path / "daily_report.md"),
        ],
    )
    assert export_report.main() == 0
    export_result = json.loads(capsys.readouterr().out)
    assert export_result == {
        "format": "md",
        "filename": "daily_report.md",
        "path": str(tmp_path / "daily_report.md"),
        "artifact_path": str(tmp_path / "daily_report.md"),
        "present_files_hint": ["/mnt/user-data/outputs/daily_report.md"],
    }

    markdown = (tmp_path / "daily_report.md").read_text(encoding="utf-8")
    assert "# 设备运行日报" in markdown
    assert "## KPI 指标" in markdown
    assert "## 异常事件" in markdown
    assert "## 建议" in markdown


def test_scope_aggregation_pipeline(monkeypatch, tmp_path, capsys):
    """End-to-end pipeline: list_equipment → query_daily(scope) → daily_kpi → export."""
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))

    list_equipment = _load_module("list_equipment")
    query_daily = _load_module("query_daily")
    daily_kpi = _load_module("daily_kpi")
    export_report = _load_module("export_report")

    monkeypatch.setattr(query_daily, "fetch_day_with_provenance", _fake_fetch_day)

    eq_result = list_equipment.query_equipment("static_equipment", "area", "A区", limit=10000)
    assert eq_result["total_matched"] == 250
    assert eq_result["equipment_type"] == "static_equipment"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_daily.py",
            "--date", "2026-05-13",
            "--type", "static_equipment",
            "--scope", "area",
            "--scope-filter", "A区",
            "--kpis", "runtime_rate,corrosion_rate",
            "--compare", "previous_day",
        ],
    )
    assert query_daily.main() == 0
    query_result = json.loads(capsys.readouterr().out)
    assert "output" in query_result

    data = json.loads((tmp_path / "daily_data.json").read_text(encoding="utf-8"))
    assert data["equipment_type"] == "static_equipment"
    assert data["equipment_count"] == 250
    assert "per_equipment" in data["current"]
    assert len(data["current"]["per_equipment"]) == 250
    sample_eq = next(iter(data["current"]["per_equipment"].values()))
    assert "name" in sample_eq
    assert "area" in sample_eq

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "daily_kpi.py",
            "--input", str(tmp_path / "daily_data.json"),
            "--output", str(tmp_path / "daily_kpi.json"),
        ],
    )
    assert daily_kpi.main() == 0
    capsys.readouterr()

    kpi_payload = json.loads((tmp_path / "daily_kpi.json").read_text(encoding="utf-8"))
    assert kpi_payload["aggregation_mode"] == "grouped"
    assert kpi_payload["equipment_count"] == 250
    assert isinstance(kpi_payload["top_anomalies"], list)
    for item in kpi_payload["kpi_summary"]:
        assert "min" in item
        assert "max" in item
        assert item["current_note"] == "均值"
    if kpi_payload["top_anomalies"]:
        anomaly = kpi_payload["top_anomalies"][0]
        assert anomaly["name"] != anomaly["equipment_id"]
        assert anomaly["area"] != ""

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "export_report.py",
            "--input", str(tmp_path / "daily_kpi.json"),
            "--format", "md",
            "--output", str(tmp_path / "daily_report.md"),
        ],
    )
    assert export_report.main() == 0
    capsys.readouterr()

    markdown = (tmp_path / "daily_report.md").read_text(encoding="utf-8")
    assert "# 静设备运行日报" in markdown
    assert "共 250 台" in markdown
    assert "当前（均值）" in markdown


def test_new_kpi_pipeline(monkeypatch, tmp_path, capsys):
    """Pipeline with new KPI keys (vibration_level, bearing_temp)."""
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))

    query_daily = _load_module("query_daily")
    daily_kpi = _load_module("daily_kpi")

    monkeypatch.setattr(query_daily, "fetch_day_with_provenance", _fake_fetch_day)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_daily.py",
            "--date", "2026-05-13",
            "--equipment", "RM-001,RM-002",
            "--kpis", "runtime_rate,vibration_level,bearing_temp",
            "--compare", "none",
        ],
    )
    assert query_daily.main() == 0
    capsys.readouterr()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "daily_kpi.py",
            "--input", str(tmp_path / "daily_data.json"),
            "--output", str(tmp_path / "daily_kpi.json"),
        ],
    )
    assert daily_kpi.main() == 0
    capsys.readouterr()

    kpi_payload = json.loads((tmp_path / "daily_kpi.json").read_text(encoding="utf-8"))
    kpi_keys = {item["key"] for item in kpi_payload["kpi_summary"]}
    assert "vibration_level" in kpi_keys
    assert "bearing_temp" in kpi_keys
    assert kpi_payload["aggregation_mode"] == "detail"
