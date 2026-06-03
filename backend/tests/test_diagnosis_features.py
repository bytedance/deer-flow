"""Tests for docker/sandbox/features-tool/tools/diagnosis_features.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "docker" / "sandbox" / "features-tool" / "tools" / "diagnosis_features.py"
SKILLS_ROOT = REPO_ROOT / "skills" / "custom"


def _load_module():
    spec = importlib.util.spec_from_file_location("diagnosis_features", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def diagnosis_features(tmp_path, monkeypatch):
    monkeypatch.setenv("DIAGNOSIS_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("DIAGNOSIS_SKILLS_ROOT", str(SKILLS_ROOT))
    return _load_module()


def _query_payload(kind: str = "centrifugal_pump", equipment_ids: list[str] | None = None) -> dict:
    """Synthetic query_diagnosis.json payload for tests."""
    eq = equipment_ids or ["PUMP-A-001"]
    return {
        "kind": kind,
        "equipment_ids": eq,
        "time_window": {"start": "2026-05-12T00:00:00", "end": "2026-05-13T00:00:00"},
        "compare_window": None,
        "mode": "oneoff",
        "data_source": "demo_fallback",
        "warnings": [],
        "points": [
            {
                "equipment_id": eq[0],
                "point_id": "1801",
                "point_name": "驱动端 X 轴振",
                "point_type": 83,
                "default_features": ["pp_value", "rms"],
                "trend_summary": {
                    "summary": "pp_value 持续上升",
                    "notable_points": [
                        {"feature": "pp_value", "time_ms": 1747008000000, "value": 50.0, "threshold": 35.0},
                        {"feature": "rms", "time_ms": 1747008000000, "value": 35.5, "threshold": 35.0},
                        {"feature": "one_freq_x", "time_ms": 1747008000000, "value": 20.0, "threshold": 30.0},
                    ],
                    "anomaly_time_ms": [1747008000000],
                },
            }
        ],
        "process_signals": {
            "discharge_pressure": {
                "unit": "MPa",
                "series": [
                    {"time_ms": 1747008000000, "value": 1.0},
                    {"time_ms": 1747011600000, "value": 1.05},
                ],
            },
            "flow_rate": {
                "unit": "m3/h",
                "series": [
                    {"time_ms": 1747008000000, "value": 300.0},
                    {"time_ms": 1747011600000, "value": 305.0},
                ],
            },
        },
        "compare": None,
    }


# --- Verdict classification ---


def test_classify_verdict_three_states(diagnosis_features):
    # Above threshold + band → exceed
    assert diagnosis_features._classify_verdict(50.0, 35.0) == "exceed"
    # Within ±5% band → marginal
    assert diagnosis_features._classify_verdict(35.5, 35.0) == "marginal"
    assert diagnosis_features._classify_verdict(33.5, 35.0) == "marginal"
    # Well below threshold → normal
    assert diagnosis_features._classify_verdict(20.0, 35.0) == "normal"


def test_evidence_chain_includes_three_verdicts(diagnosis_features):
    payload = _query_payload()
    chain = diagnosis_features.build_evidence_chain(payload)
    verdicts = {row["verdict"] for row in chain}
    assert "exceed" in verdicts
    assert "marginal" in verdicts
    assert "normal" in verdicts


# --- Rule book loader ---


def test_load_rule_book_pump_has_nine_codes(diagnosis_features):
    """pump-fault-diagnosis SKILL.md mapping table must yield 9 codes."""
    rb = diagnosis_features.load_rule_book("pump-fault-diagnosis", skills_root=SKILLS_ROOT)
    assert rb["warnings"] == []
    assert len(rb["codes"]) == 9
    assert "unbalance" in rb["codes"]
    assert "min_flow_violation" in rb["codes"]
    assert "motor_coupling" in rb["codes"]
    assert len(rb["sections"]) >= 9


def test_load_rule_book_vibration_has_twelve_codes(diagnosis_features):
    rb = diagnosis_features.load_rule_book("vibration-fault-diagnosis", skills_root=SKILLS_ROOT)
    assert rb["warnings"] == []
    assert len(rb["codes"]) == 12
    assert "runout" in rb["codes"]
    assert "thrust_bearing_temperature_high" in rb["codes"]


def test_load_rule_book_reciprocating_has_eleven_codes(diagnosis_features):
    rb = diagnosis_features.load_rule_book("reciprocating-fault-diagnosis", skills_root=SKILLS_ROOT)
    assert rb["warnings"] == []
    assert len(rb["codes"]) == 11
    assert "valve_failure" in rb["codes"]
    assert "crosshead_knock" in rb["codes"]


def test_load_rule_book_missing_skill_records_warning(diagnosis_features, tmp_path):
    rb = diagnosis_features.load_rule_book("nonexistent-skill", skills_root=tmp_path)
    assert rb["codes"] == {}
    assert len(rb["warnings"]) >= 1
    assert "SKILL.md not found" in rb["warnings"][0]


def test_find_section_for_code_handles_slash_alternatives(diagnosis_features):
    """Code mapping like '不平衡类 / 初始不平衡' must match either side."""
    rb = diagnosis_features.load_rule_book("vibration-fault-diagnosis", skills_root=SKILLS_ROOT)
    title, body = diagnosis_features.find_section_for_code(rb, "unbalance")
    assert title is not None
    assert body is not None and len(body) > 0


# --- build_features end-to-end ---


def test_build_features_pump_three_codes_match(diagnosis_features, tmp_path):
    payload = _query_payload(equipment_ids=["PUMP-A-001"])
    result = diagnosis_features.build_features(
        query_payload=payload,
        focus_codes=["unbalance", "cavitation"],
        rules_skill="pump-fault-diagnosis",
        input_dir=tmp_path,
        skills_root=SKILLS_ROOT,
    )
    assert {row for row in result.keys()} >= {
        "report_meta",
        "equipment_summary",
        "evidence_chain",
        "trend_chart",
        "spectrum_charts",
        "orbit_charts",
        "rule_matches",
        "historical_cases",
        "recommendations",
        "warnings",
    }
    matches = result["rule_matches"]
    assert any(m["fault_family"] == "unbalance" for m in matches)
    # supporting_evidence_indices must reference real positions in evidence_chain
    chain = result["evidence_chain"]
    for m in matches:
        for idx in m["supporting_evidence_indices"]:
            assert 0 <= idx < len(chain)
            assert chain[idx]["verdict"] == "exceed"


def test_marginal_evidence_does_not_count_as_supporting(diagnosis_features, tmp_path):
    payload = _query_payload()
    result = diagnosis_features.build_features(
        query_payload=payload,
        focus_codes=["unbalance"],
        rules_skill="pump-fault-diagnosis",
        input_dir=tmp_path,
        skills_root=SKILLS_ROOT,
    )
    # Find unbalance match
    match = next((m for m in result["rule_matches"] if m["fault_family"] == "unbalance"), None)
    assert match is not None
    chain = result["evidence_chain"]
    for idx in match["supporting_evidence_indices"]:
        assert chain[idx]["verdict"] == "exceed", "supporting must be exceed only"
    for idx in match["marginal_evidence_indices"]:
        assert chain[idx]["verdict"] == "marginal", "marginal_evidence_indices must be marginal"


def test_reciprocating_skips_orbit_charts(diagnosis_features, tmp_path):
    """Reciprocating kinds must yield empty orbit_charts even if files exist."""
    # Plant a fake orbit_*.json that should be ignored
    (tmp_path / "orbit_DE.json").write_text(
        json.dumps({"bearing": "DE", "option": {"series": []}}), encoding="utf-8"
    )
    payload = _query_payload(kind="reciprocating_compressor", equipment_ids=["RC-001"])
    result = diagnosis_features.build_features(
        query_payload=payload,
        focus_codes=["valve_failure"],
        rules_skill="reciprocating-fault-diagnosis",
        input_dir=tmp_path,
        skills_root=SKILLS_ROOT,
    )
    assert result["orbit_charts"] == []


def test_pump_picks_up_orbit_files_when_present(diagnosis_features, tmp_path):
    (tmp_path / "orbit_DE.json").write_text(
        json.dumps({"bearing": "DE", "option": {"series": [{"name": "orbit"}]}}), encoding="utf-8"
    )
    payload = _query_payload(kind="centrifugal_pump")
    result = diagnosis_features.build_features(
        query_payload=payload,
        focus_codes=["unbalance"],
        rules_skill="pump-fault-diagnosis",
        input_dir=tmp_path,
        skills_root=SKILLS_ROOT,
    )
    assert len(result["orbit_charts"]) == 1
    assert result["orbit_charts"][0]["bearing"] == "DE"


def test_spectrum_files_collected_when_present(diagnosis_features, tmp_path):
    (tmp_path / "spectrum_1801.json").write_text(
        json.dumps({"point": "驱动端 X 轴振", "option": {"series": []}}), encoding="utf-8"
    )
    payload = _query_payload()
    result = diagnosis_features.build_features(
        query_payload=payload,
        focus_codes=["unbalance"],
        rules_skill="pump-fault-diagnosis",
        input_dir=tmp_path,
        skills_root=SKILLS_ROOT,
    )
    assert len(result["spectrum_charts"]) == 1
    assert result["spectrum_charts"][0]["point"] == "驱动端 X 轴振"


def test_missing_rule_book_yields_empty_matches_with_warning(diagnosis_features, tmp_path):
    """Per design doc §5.2: rule parse failure → JSON {warnings, rule_matches: []}, never raise."""
    # Point skills_root somewhere with no SKILL.md
    payload = _query_payload()
    result = diagnosis_features.build_features(
        query_payload=payload,
        focus_codes=["unbalance"],
        rules_skill="pump-fault-diagnosis",
        input_dir=tmp_path,
        skills_root=tmp_path,  # no skills here
    )
    assert result["rule_matches"] == []
    assert any("SKILL.md not found" in w for w in result["warnings"])
    # Other fields still produced
    assert result["evidence_chain"]
    assert result["trend_chart"]


def test_historical_cases_marked_demo_fallback(diagnosis_features, tmp_path):
    payload = _query_payload()
    result = diagnosis_features.build_features(
        query_payload=payload,
        focus_codes=["unbalance"],
        rules_skill="pump-fault-diagnosis",
        input_dir=tmp_path,
        skills_root=SKILLS_ROOT,
    )
    # Per design risk row 9.1: historical_cases must carry data_source
    for case in result["historical_cases"]:
        assert case["data_source"] == "demo_fallback"


def test_recommendations_synthesized_from_matches(diagnosis_features, tmp_path):
    payload = _query_payload()
    result = diagnosis_features.build_features(
        query_payload=payload,
        focus_codes=["unbalance", "cavitation"],
        rules_skill="pump-fault-diagnosis",
        input_dir=tmp_path,
        skills_root=SKILLS_ROOT,
    )
    recs = result["recommendations"]
    assert recs, "must produce at least one recommendation"
    # unbalance recommendation keyword should appear
    assert any("动平衡" in r for r in recs)


# --- ECharts option shape ---


def test_trend_chart_returns_complete_echarts_option(diagnosis_features, tmp_path):
    payload = _query_payload()
    chart = diagnosis_features.build_trend_chart(payload)
    for key in ("title", "tooltip", "legend", "xAxis", "yAxis", "series"):
        assert key in chart
    assert isinstance(chart["series"], list)
    assert all("data" in s for s in chart["series"])


# --- CLI ---


def test_main_writes_output_file(diagnosis_features, monkeypatch, tmp_path, capsys):
    # Plant a query_diagnosis.json
    (tmp_path / "query_diagnosis.json").write_text(
        json.dumps(_query_payload()), encoding="utf-8"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "diagnosis_features.py",
            "--input",
            str(tmp_path / "query_diagnosis.json"),
            "--focus",
            "unbalance,cavitation",
            "--rules-skill",
            "pump-fault-diagnosis",
            "--output",
            str(tmp_path / "diagnosis_features.json"),
        ],
    )
    assert diagnosis_features.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["rules_skill"] == "pump-fault-diagnosis"
    assert out["evidence_count"] >= 1
    written = json.loads((tmp_path / "diagnosis_features.json").read_text(encoding="utf-8"))
    assert written["report_meta"]["rules_skill"] == "pump-fault-diagnosis"


def test_main_rejects_unknown_rules_skill(diagnosis_features, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "diagnosis_features.py",
            "--focus",
            "unbalance",
            "--rules-skill",
            "nonexistent",
        ],
    )
    assert diagnosis_features.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert "--rules-skill" in out["error"]


def test_main_rejects_empty_focus(diagnosis_features, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "diagnosis_features.py",
            "--focus",
            "",
            "--rules-skill",
            "pump-fault-diagnosis",
        ],
    )
    assert diagnosis_features.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert "--focus must be a non-empty CSV" in out["error"]


def test_main_reports_missing_input_file(diagnosis_features, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "diagnosis_features.py",
            "--input",
            str(tmp_path / "missing.json"),
            "--focus",
            "unbalance",
            "--rules-skill",
            "pump-fault-diagnosis",
        ],
    )
    assert diagnosis_features.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert "input file not found" in out["error"]


def test_supporting_evidence_indices_reference_evidence_chain(diagnosis_features, tmp_path):
    """rule_matches[].supporting_evidence_indices must be valid indices into evidence_chain."""
    payload = _query_payload()
    result = diagnosis_features.build_features(
        query_payload=payload,
        focus_codes=["unbalance", "cavitation", "min_flow_violation"],
        rules_skill="pump-fault-diagnosis",
        input_dir=tmp_path,
        skills_root=SKILLS_ROOT,
    )
    chain_len = len(result["evidence_chain"])
    for m in result["rule_matches"]:
        for idx in m["supporting_evidence_indices"]:
            assert isinstance(idx, int)
            assert 0 <= idx < chain_len
