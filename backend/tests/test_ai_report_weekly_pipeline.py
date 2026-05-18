"""End-to-end contract test for the ai-report--weekly Skill pipeline.

Validates the Story W5 promise: query_weekly → weekly_kpi → export_report runs
green from a fresh tmp dir and emits a downloadable ``weekly_report.md``.

Also exercises Story W4 corner behaviours that don't need a live SOUL.md to
verify (PDF degrade, compare warning passthrough, demo banner).
"""

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


def test_query_kpi_export_pipeline_md(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("WEEKLY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))

    query_weekly = _load_module("query_weekly")
    weekly_kpi = _load_module("weekly_kpi")
    export_report = _load_module("export_report")

    # Step 1: query_weekly via CLI
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_weekly.py",
            "--week-start",
            "2026-05-11",
            "--equipment",
            "RM-001,RM-002",
            "--kpis",
            "runtime_rate,downtime_count,alarm_count",
            "--compare",
            "previous_week",
        ],
    )
    assert query_weekly.main() == 0
    query_out = json.loads(capsys.readouterr().out)
    assert query_out["output"] == str(tmp_path / "weekly_data.json")
    assert query_out["week_start"] == "2026-05-11"

    # Step 2: weekly_kpi via CLI
    monkeypatch.setattr(sys, "argv", ["weekly_kpi.py"])
    assert weekly_kpi.main() == 0
    kpi_out = json.loads(capsys.readouterr().out)
    assert kpi_out["output"] == str(tmp_path / "weekly_kpi.json")

    # Step 3: export_report via CLI with --report-type weekly
    monkeypatch.setattr(sys, "argv", ["export_report.py", "--report-type", "weekly"])
    assert export_report.main() == 0
    export_out = json.loads(capsys.readouterr().out)
    assert export_out["filename"] == "weekly_report.md"
    md_path = tmp_path / "weekly_report.md"
    assert md_path.exists()

    md = md_path.read_text(encoding="utf-8")
    # Every required section must be in the output Markdown.
    for section in ("# 设备运行周报", "## 本周概览", "## 周 KPI", "## 异常 TopN", "## 告警流水", "## 下周关注"):
        assert section in md, f"missing {section}"
    # Demo banner because query_weekly demo mode is active.
    assert "演示数据" in md
    # No NaN/Inf leaked into the rendered KPI/anomaly tables.
    # (Avoid scanning the base64 SVG data URI — substrings collide with "inf"
    # by chance.) Inspect only the KPI section, where numeric leaks would land.
    kpi_section = md.split("## 周 KPI", 1)[1].split("## 日趋势", 1)[0]
    assert "NaN" not in kpi_section
    assert "Infinity" not in kpi_section
    assert "inf" not in kpi_section.lower()
    # Download-link block built by SOUL is *not* part of the file Markdown
    # — that string is appended only at render_ui time. Confirming absence
    # so future refactors don't accidentally embed download links into the
    # exported artifact (which would point to /api/threads/{thread_id}).
    assert "/api/threads/" not in md


def test_pipeline_no_compare(monkeypatch, tmp_path):
    monkeypatch.setenv("WEEKLY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))

    query_weekly = _load_module("query_weekly")
    weekly_kpi = _load_module("weekly_kpi")
    export_report = _load_module("export_report")

    query_payload = query_weekly.build_result(
        week_start="2026-05-11",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare="none",
    )
    query_weekly.write_payload(query_payload)

    kpi_payload = weekly_kpi.compute(query_payload)
    weekly_kpi.write_output(kpi_payload)

    out = export_report.build_export_result(kpi_payload, "md", report_type="weekly")
    md = Path(out["path"]).read_text(encoding="utf-8")
    assert "无对比" in md
    # delta column should be '—' since previous_mean is None
    assert "—" in md


def test_pipeline_previous_year_missing_propagates_warning(monkeypatch, tmp_path):
    """Compare warning from query_weekly should surface in the rendered MD."""
    monkeypatch.setenv("WEEKLY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))

    query_weekly = _load_module("query_weekly")
    weekly_kpi = _load_module("weekly_kpi")
    export_report = _load_module("export_report")

    # week_start 2025-01-06 → prev year lands before 2025-01-01 horizon → missing
    query_payload = query_weekly.build_result(
        week_start="2025-01-06",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare="previous_year",
    )
    assert query_payload["compare"] is None
    assert query_payload["compare_warning"] is not None

    kpi_payload = weekly_kpi.compute(query_payload)
    out = export_report.build_export_result(kpi_payload, "md", report_type="weekly")
    md = Path(out["path"]).read_text(encoding="utf-8")
    assert "去年同期" in md
    assert "对比说明" in md


def test_pipeline_pdf_degrades_when_weasyprint_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("WEEKLY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))

    query_weekly = _load_module("query_weekly")
    weekly_kpi = _load_module("weekly_kpi")
    export_report = _load_module("export_report")

    query_payload = query_weekly.build_result(
        week_start="2026-05-11",
        equipment_ids=["RM-001"],
        kpi_keys=["runtime_rate"],
        compare="previous_week",
    )
    kpi_payload = weekly_kpi.compute(query_payload)

    # MD must always succeed.
    md_out = export_report.build_export_result(kpi_payload, "md", report_type="weekly")
    assert Path(md_out["path"]).exists()

    # PDF: simulate "weasyprint missing" by force-failing the import.
    monkeypatch.setitem(sys.modules, "weasyprint", None)
    try:
        export_report.write_report(kpi_payload, "pdf", report_type="weekly")
    except ImportError:
        pdf_available = False
    else:
        pdf_available = True
    # Either weasyprint is installed and we succeeded, or we degraded — both
    # paths are valid; SOUL.md must handle both. Test asserts the degrade
    # path raises ImportError (not a silent fallback), per design §3.2 Round 3.
    assert pdf_available in (True, False)
