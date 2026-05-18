"""Tests for skills/custom/data-analyst/scripts/export_diagnosis_report.py
and the ``report_type="diagnosis"`` branch added to export_report.py.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts"
EXPORT_REPORT_PATH = SCRIPT_DIR / "export_report.py"
EXPORT_DIAGNOSIS_PATH = SCRIPT_DIR / "export_diagnosis_report.py"


@pytest.fixture(autouse=True)
def _add_script_dir_to_syspath(monkeypatch):
    """Make `import export_report` / `import export_diagnosis_report` work in tests."""
    monkeypatch.syspath_prepend(str(SCRIPT_DIR))


@pytest.fixture()
def export_diagnosis(tmp_path, monkeypatch, _add_script_dir_to_syspath):
    monkeypatch.setenv("DIAGNOSIS_OUTPUT_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location("export_diagnosis_report", EXPORT_DIAGNOSIS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules["export_diagnosis_report"] = module
    return module


@pytest.fixture()
def export_report_module(tmp_path, monkeypatch, _add_script_dir_to_syspath):
    monkeypatch.setenv("DIAGNOSIS_OUTPUT_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location("export_report", EXPORT_REPORT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules["export_report"] = module
    return module


def _diagnosis_payload() -> dict:
    return {
        "report_meta": {
            "kind": "centrifugal_pump",
            "rules_skill": "pump-fault-diagnosis",
            "generated_at": "2026-05-18T06:00:00Z",
            "data_source": "demo_fallback",
        },
        "equipment_summary": [
            {
                "equipment_id": "PUMP-A-001",
                "operation_phase": "steady_state",
                "alarm_status": "warning",
                "max_value": {
                    "point": "驱动端 X 轴振",
                    "feature": "pp_value",
                    "value": 48.6,
                    "unit": "μm",
                },
            }
        ],
        "evidence_chain": [
            {
                "category": "trend",
                "equipment_id": "PUMP-A-001",
                "point": "驱动端 X 轴振",
                "feature": "pp_value",
                "value": 48.6,
                "threshold": 35.0,
                "verdict": "exceed",
                "time": "2026-05-12T08:00:00",
            },
            {
                "category": "trend",
                "equipment_id": "PUMP-A-001",
                "point": "驱动端 X 轴振",
                "feature": "rms",
                "value": 35.5,
                "threshold": 35.0,
                "verdict": "marginal",
                "time": "2026-05-12T08:00:00",
            },
        ],
        "trend_chart": {
            "title": {"text": "趋势"},
            "tooltip": {},
            "legend": {"data": []},
            "xAxis": {"type": "category", "data": []},
            "yAxis": {"type": "value"},
            "series": [],
        },
        "spectrum_charts": [],
        "orbit_charts": [],
        "rule_matches": [
            {
                "equipment_id": "PUMP-A-001",
                "kind": "centrifugal_pump",
                "fault_family": "unbalance",
                "fault_subtype": None,
                "confidence": "high",
                "supporting_evidence_indices": [0],
                "marginal_evidence_indices": [1],
                "missing_evidence": ["orbit_repeatability"],
                "rule_section": "不平衡",
            },
            {
                "equipment_id": "PUMP-A-001",
                "kind": "centrifugal_pump",
                "fault_family": "cavitation",
                "fault_subtype": None,
                "confidence": "low",
                "supporting_evidence_indices": [],
                "marginal_evidence_indices": [],
                "missing_evidence": [],
                "rule_section": "汽蚀",
            },
        ],
        "historical_cases": [
            {
                "equipment_id": "PUMP-A-007",
                "fault_family": "unbalance",
                "occurred_at": "2026-04-08",
                "summary": "演示历史案例：高速动平衡后 pp_value 由 41 降至 18",
                "data_source": "demo_fallback",
            }
        ],
        "recommendations": ["下次停机执行高速动平衡", "检查叶轮积垢"],
        "warnings": [],
    }


# --- Markdown rendering ---


def test_render_markdown_contains_six_sections(export_diagnosis):
    md = export_diagnosis.render_diagnosis_markdown(_diagnosis_payload(), thread_id="t1")
    assert "# 故障诊断报告" in md
    assert "## 1. 设备与任务" in md
    assert "## 2. 异常发现" in md
    assert "## 3. 证据链" in md
    assert "## 4. 诊断结论" in md
    assert "## 5. 差异诊断" in md
    assert "## 6. 处置建议" in md


def test_render_markdown_includes_evidence_table_indices(export_diagnosis):
    """Evidence rows must be indexed so rule_matches[].supporting_evidence_indices remain meaningful."""
    md = export_diagnosis.render_diagnosis_markdown(_diagnosis_payload())
    # Expect a row "| 0 |" referencing the first evidence
    assert "| 0 |" in md
    assert "| 1 |" in md


def test_render_markdown_marks_marginal_evidence_separately(export_diagnosis):
    md = export_diagnosis.render_diagnosis_markdown(_diagnosis_payload())
    # Primary diagnosis lists marginal evidence in its own line
    assert "边缘证据" in md
    # And marginal verdict still appears in evidence chain table
    assert "边缘" in md


def test_render_markdown_demo_historical_marked(export_diagnosis):
    md = export_diagnosis.render_diagnosis_markdown(_diagnosis_payload())
    assert "## 附：同类故障历史" in md
    # demo_fallback cases must carry the "演示" prefix
    assert "演示 ·" in md


def test_render_markdown_handles_empty_payload(export_diagnosis):
    """Defensive: missing sections should not crash and must include placeholders."""
    md = export_diagnosis.render_diagnosis_markdown(
        {
            "report_meta": {},
            "equipment_summary": [],
            "evidence_chain": [],
            "rule_matches": [],
            "historical_cases": [],
            "recommendations": [],
            "warnings": [],
        }
    )
    assert "## 4. 诊断结论" in md
    # No matches → must say "未匹配到任何规则"
    assert "未匹配到任何规则" in md


def test_render_markdown_warnings_block_appears(export_diagnosis):
    payload = _diagnosis_payload()
    payload["warnings"] = ["ins-extract-trend-features failed twice: TimeoutExpired"]
    md = export_diagnosis.render_diagnosis_markdown(payload)
    assert "执行告警" in md
    assert "TimeoutExpired" in md


def test_render_markdown_no_warnings_block_when_empty(export_diagnosis):
    md = export_diagnosis.render_diagnosis_markdown(_diagnosis_payload())
    assert "执行告警" not in md


def test_render_markdown_single_match_says_no_differential(export_diagnosis):
    payload = _diagnosis_payload()
    payload["rule_matches"] = payload["rule_matches"][:1]
    md = export_diagnosis.render_diagnosis_markdown(payload)
    assert "未发现替代候选" in md


# --- Integration with export_report.write_report ---


def test_write_report_diagnosis_md_path(export_report_module, export_diagnosis, tmp_path):
    out = export_report_module.write_report(
        _diagnosis_payload(), "md", report_type="diagnosis"
    )
    assert out.parent == tmp_path
    assert out.name == "diagnosis_report.md"
    content = out.read_text(encoding="utf-8")
    assert "# 故障诊断报告" in content


def test_write_report_diagnosis_pdf_raises_importerror_when_weasyprint_absent(
    export_report_module, export_diagnosis, tmp_path
):
    """The ImportError must not be swallowed inside write_report —
    SOUL-side try/except is the contract."""
    # Force-simulate weasyprint absence by stubbing the import
    import builtins as _builtins

    original = _builtins.__import__

    def _shim(name, *args, **kwargs):
        if name == "weasyprint":
            raise ImportError("no weasyprint")
        return original(name, *args, **kwargs)

    _builtins.__import__ = _shim
    try:
        with pytest.raises(ImportError):
            export_report_module.write_report(
                _diagnosis_payload(), "pdf", report_type="diagnosis"
            )
    finally:
        _builtins.__import__ = original


def test_supported_report_types_includes_diagnosis(export_report_module):
    assert "diagnosis" in export_report_module.SUPPORTED_REPORT_TYPES


def test_load_payload_uses_diagnosis_filename(export_report_module, tmp_path):
    """When report_type=diagnosis and no path, load from <output_dir>/diagnosis_features.json."""
    payload = _diagnosis_payload()
    target = tmp_path / "diagnosis_features.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    loaded = export_report_module.load_payload(report_type="diagnosis")
    assert loaded["report_meta"]["rules_skill"] == "pump-fault-diagnosis"


def test_build_export_result_diagnosis(export_report_module, export_diagnosis, tmp_path):
    """build_export_result wraps write_report and returns the artifact contract."""
    result = export_report_module.build_export_result(
        _diagnosis_payload(), "md", report_type="diagnosis"
    )
    assert result["format"] == "md"
    assert result["filename"] == "diagnosis_report.md"
    assert result["present_files_hint"] == ["/mnt/user-data/outputs/diagnosis_report.md"]


def test_existing_daily_path_unaffected(export_report_module, tmp_path, monkeypatch):
    """Smoke-check that the new diagnosis branch has not broken the daily code path."""
    # Use a minimal daily payload — only the fields render_markdown actually reads
    daily_payload = {
        "report_date": "2026-05-13",
        "compare_type": "previous_day",
        "compare_date": "2026-05-12",
        "overall_status": {"level": "ok", "summary": "demo"},
        "kpi_summary": [],
        "trend_chart": {"series": []},
        "alarm_table": [],
        "recommendations": [],
    }
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))
    out = export_report_module.write_report(daily_payload, "md", report_type="daily")
    assert out.name == "daily_report.md"
    assert out.exists()
