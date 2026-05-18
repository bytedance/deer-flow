"""Tests for skills/custom/data-analyst/scripts/diagnosis_analysis.py (§13.2 contract).

Sprint S6 — covers Story S2 lower-half acceptance:
- 5-field §13.2 contract present
- summary_markdown NOT in output
- human_review_required ALWAYS true
- Each finding ≥ 2 evidence entries (S2 acceptance — stricter than S1)
- Evidence source_type union covers ≥ 3 of {timeseries, alarm, work_order, maintenance_record}
- impact_assessment shape (affected_equipment / downtime_minutes / business_impact)
- Optional timeline input is propagated
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts"
TRANSFORM_PATH = SCRIPTS_DIR / "diagnosis_analysis.py"
QUERY_PATH = SCRIPTS_DIR / "query_fault_context.py"
TIMELINE_PATH = SCRIPTS_DIR / "build_fault_timeline.py"
HELPERS_PATH = SCRIPTS_DIR / "_stub_helpers.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def transform():
    _load("_stub_helpers", HELPERS_PATH)
    return _load("diagnosis_analysis", TRANSFORM_PATH)


@pytest.fixture()
def fault_context(tmp_path):
    _load("_stub_helpers", HELPERS_PATH)
    query = _load("query_fault_context", QUERY_PATH)
    sys.argv = [
        "query_fault_context.py",
        "--fault-time", "2026-05-15",
        "--equipment-id", "P-001",
        "--symptom", "vibration high",
        "--include-related-equipment",
        "--output-dir", str(tmp_path),
    ]
    rc = query.main()
    assert rc == 0
    return tmp_path / "data" / "fault_context.json"


@pytest.fixture()
def fault_timeline(tmp_path, fault_context):
    timeline = _load("build_fault_timeline", TIMELINE_PATH)
    sys.argv = [
        "build_fault_timeline.py",
        "--input", str(fault_context),
        "--output-dir", str(tmp_path),
    ]
    rc = timeline.main()
    assert rc == 0
    return tmp_path / "data" / "fault_timeline.json"


def _run(transform, fault_context, tmp_path, timeline=None):
    args = [
        "diagnosis_analysis.py",
        "--input", str(fault_context),
        "--output-dir", str(tmp_path),
    ]
    if timeline:
        args.extend(["--timeline", str(timeline)])
    sys.argv = args
    rc = transform.main()
    assert rc == 0
    out = tmp_path / "data" / "diagnosis_analysis.json"
    return json.loads(out.read_text(encoding="utf-8"))


def test_no_summary_markdown(transform, fault_context, tmp_path):
    result = _run(transform, fault_context, tmp_path)
    assert "summary_markdown" not in result


def test_full_5_field_contract(transform, fault_context, tmp_path):
    result = _run(transform, fault_context, tmp_path)
    for required in ("findings", "evidence", "confidence", "data_coverage", "human_review_required"):
        assert required in result


def test_human_review_required_always_true(transform, fault_context, tmp_path):
    result = _run(transform, fault_context, tmp_path)
    assert result["human_review_required"] is True


def test_each_finding_has_at_least_two_evidence(transform, fault_context, tmp_path):
    result = _run(transform, fault_context, tmp_path)
    per_finding = Counter(e["finding_id"] for e in result["evidence"])
    finding_ids = {f["id"] for f in result["findings"]}
    for fid in finding_ids:
        assert per_finding[fid] >= 2, (
            f"sprint plan S2 acceptance: each finding must have ≥2 evidence; "
            f"{fid} only has {per_finding[fid]}"
        )


def test_evidence_source_types_union_at_least_3(transform, fault_context, tmp_path):
    result = _run(transform, fault_context, tmp_path)
    source_types = {e["source_type"] for e in result["evidence"]}
    # Sprint plan S2: must cover ≥3 of {timeseries, alarm, work_order, maintenance_record}
    expected_set = {"timeseries", "alarm", "work_order", "maintenance_record"}
    intersection = source_types & expected_set
    assert len(intersection) >= 3, f"source_type union must cover ≥3; got {sorted(source_types)}"


def test_findings_exactly_one_primary(transform, fault_context, tmp_path):
    result = _run(transform, fault_context, tmp_path)
    primaries = [f for f in result["findings"] if f.get("is_primary")]
    assert len(primaries) == 1, f"exactly one finding must be is_primary; got {len(primaries)}"


def test_impact_assessment_shape(transform, fault_context, tmp_path):
    result = _run(transform, fault_context, tmp_path)
    impact = result["impact_assessment"]
    for field in ("affected_equipment", "downtime_minutes", "business_impact", "critical_alarm_count"):
        assert field in impact


def test_timeline_optional_input_propagates(transform, fault_context, fault_timeline, tmp_path):
    result = _run(transform, fault_context, tmp_path, timeline=fault_timeline)
    assert len(result["timeline"]) > 0
    # Without timeline, timeline must be empty list
    result_no_tl = _run(transform, fault_context, tmp_path)
    assert result_no_tl["timeline"] == []


def test_data_coverage_counts_match_input(transform, fault_context, tmp_path):
    result = _run(transform, fault_context, tmp_path)
    coverage = result["data_coverage"]
    raw = json.loads(fault_context.read_text(encoding="utf-8"))
    assert coverage["operations_sample_count"] == len(raw["operations"])
    assert coverage["alarm_count"] == len(raw["alarms"])
    assert coverage["work_orders_count"] == len(raw["work_orders"])
    assert coverage["maintenance_records_count"] == len(raw["maintenance_records"])
