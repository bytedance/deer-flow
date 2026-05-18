"""Tests for query_inspection / inspection_summary / inspection_attachment_summary.

Sprint S6 — covers Story S5 acceptance (factual report; NO §13.2 fields):
- All 4 severity tiers (low/medium/high/critical) in demo with severity_min=low
- severity_min filter actually drops lower tiers
- severity_distribution always has 4 rows (low/medium/high/critical)
- anomaly_list = records with severity >= medium
- attachment_summary length equals records length
- Per-record photo/note counts
- NO findings/evidence/human_review_required (factual)
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
QUERY_PATH = SCRIPTS_DIR / "query_inspection.py"
SUMMARY_PATH = SCRIPTS_DIR / "inspection_summary.py"
ATT_PATH = SCRIPTS_DIR / "inspection_attachment_summary.py"
HELPERS_PATH = SCRIPTS_DIR / "_stub_helpers.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def query_inspection():
    _load("_stub_helpers", HELPERS_PATH)
    return _load("query_inspection", QUERY_PATH)


@pytest.fixture()
def summary_transform():
    _load("_stub_helpers", HELPERS_PATH)
    return _load("inspection_summary", SUMMARY_PATH)


@pytest.fixture()
def attachment_transform():
    _load("_stub_helpers", HELPERS_PATH)
    return _load("inspection_attachment_summary", ATT_PATH)


def _run_query(query, tmp_path, severity_min="low"):
    sys.argv = [
        "query_inspection.py",
        "--inspection-date", "2026-05-15",
        "--route", "RT-A",
        "--area", "A区",
        "--severity-min", severity_min,
        "--output-dir", str(tmp_path),
    ]
    rc = query.main()
    assert rc == 0
    return tmp_path / "data" / "inspection_data.json"


def _run_summary(summary, input_path, tmp_path):
    sys.argv = ["inspection_summary.py", "--input", str(input_path), "--output-dir", str(tmp_path)]
    rc = summary.main()
    assert rc == 0
    return json.loads((tmp_path / "data" / "inspection_summary.json").read_text(encoding="utf-8"))


def _run_attachments(att, input_path, tmp_path):
    sys.argv = ["inspection_attachment_summary.py", "--input", str(input_path), "--output-dir", str(tmp_path)]
    rc = att.main()
    assert rc == 0
    return json.loads((tmp_path / "data" / "inspection_attachments.json").read_text(encoding="utf-8"))


def test_demo_covers_all_4_severities(query_inspection, tmp_path):
    data = _run_query(query_inspection, tmp_path, severity_min="low")
    raw = json.loads(data.read_text(encoding="utf-8"))
    severities = Counter(r["severity"] for r in raw["records"])
    for sev in ("low", "medium", "high", "critical"):
        assert severities[sev] >= 1, f"demo must cover severity={sev}; got {severities}"


def test_severity_min_high_filters_out_low_medium(query_inspection, tmp_path):
    data = _run_query(query_inspection, tmp_path, severity_min="high")
    raw = json.loads(data.read_text(encoding="utf-8"))
    severities = {r["severity"] for r in raw["records"]}
    # Only high + critical should pass
    assert severities.issubset({"high", "critical"})


def test_severity_min_medium_drops_low(query_inspection, tmp_path):
    data = _run_query(query_inspection, tmp_path, severity_min="medium")
    raw = json.loads(data.read_text(encoding="utf-8"))
    severities = {r["severity"] for r in raw["records"]}
    assert "low" not in severities


def test_invalid_severity_min_emits_error(query_inspection, tmp_path):
    sys.argv = [
        "query_inspection.py",
        "--inspection-date", "2026-05-15",
        "--severity-min", "unknown",
        "--output-dir", str(tmp_path),
    ]
    assert query_inspection.main() == 1


def test_invalid_date_emits_error(query_inspection, tmp_path):
    sys.argv = [
        "query_inspection.py",
        "--inspection-date", "not-a-date",
        "--severity-min", "low",
        "--output-dir", str(tmp_path),
    ]
    assert query_inspection.main() == 1


def test_summary_no_interpretive_contract(query_inspection, summary_transform, tmp_path):
    data = _run_query(query_inspection, tmp_path)
    result = _run_summary(summary_transform, data, tmp_path)
    forbidden = ("findings", "evidence", "confidence", "human_review_required", "summary_markdown")
    for field in forbidden:
        assert field not in result, f"factual inspection_summary must NOT have '{field}'"


def test_severity_distribution_has_4_rows(query_inspection, summary_transform, tmp_path):
    data = _run_query(query_inspection, tmp_path)
    result = _run_summary(summary_transform, data, tmp_path)
    dist = result["severity_distribution"]
    severities = [row["severity"] for row in dist]
    assert severities == ["low", "medium", "high", "critical"]
    for row in dist:
        assert row["count"] >= 0
        assert 0 <= row["percentage"] <= 1


def test_anomaly_list_excludes_low(query_inspection, summary_transform, tmp_path):
    data = _run_query(query_inspection, tmp_path)
    result = _run_summary(summary_transform, data, tmp_path)
    for row in result["anomaly_list"]:
        assert row["severity"] != "low"


def test_attachment_summary_length_equals_records(query_inspection, attachment_transform, tmp_path):
    data = _run_query(query_inspection, tmp_path)
    raw = json.loads(data.read_text(encoding="utf-8"))
    result = _run_attachments(attachment_transform, data, tmp_path)
    assert len(result["attachment_summary"]) == len(raw["records"])


def test_attachment_summary_counts_match_refs(query_inspection, attachment_transform, tmp_path):
    data = _run_query(query_inspection, tmp_path)
    raw = json.loads(data.read_text(encoding="utf-8"))
    result = _run_attachments(attachment_transform, data, tmp_path)

    # Cross-check: photo_count + note_count of each summary entry must equal
    # the number of attachment_refs the source record had
    refs_by_record = {r["id"]: r["attachment_refs"] for r in raw["records"]}
    for s in result["attachment_summary"]:
        expected = len(refs_by_record.get(s["record_id"], []))
        assert s["photo_count"] + s["note_count"] == expected


def test_data_source_demo_fallback(query_inspection, tmp_path):
    data = _run_query(query_inspection, tmp_path)
    raw = json.loads(data.read_text(encoding="utf-8"))
    assert raw["data_source"] == "demo_fallback"


def test_overall_level_critical_when_critical_present(query_inspection, summary_transform, tmp_path):
    """Demo at severity_min=low has 1 critical record → level=critical."""
    data = _run_query(query_inspection, tmp_path, severity_min="low")
    result = _run_summary(summary_transform, data, tmp_path)
    assert result["overall_status"]["level"] == "critical"
