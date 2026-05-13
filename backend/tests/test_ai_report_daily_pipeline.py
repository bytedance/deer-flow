"""End-to-end contract test for the ai-report--daily Skill pipeline."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts"


def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_query_kpi_export_pipeline(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))

    query_daily = _load_module("query_daily")
    daily_kpi = _load_module("daily_kpi")
    export_report = _load_module("export_report")

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
    }

    markdown = (tmp_path / "daily_report.md").read_text(encoding="utf-8")
    assert "# 设备运行日报" in markdown
    assert "## KPI 指标" in markdown
    assert "## 异常事件" in markdown
    assert "## 建议" in markdown
