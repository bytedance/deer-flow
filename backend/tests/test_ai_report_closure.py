"""Tests for closure_summary + query_closure_items.

Sprint S6 — covers Story S4 acceptance (factual report; NO §13.2 fields):
- 5 issue statuses (pending/in_progress/verifying/closed/reopened) all in demo
- completion_rate formula = closed / total
- Overdue detection (due_date < today AND status != closed)
- Reopened item flagged as critical risk
- unclosed_items length = total - closed
- NO findings / evidence / confidence / human_review_required in output
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts"
QUERY_PATH = SCRIPTS_DIR / "query_closure_items.py"
TRANSFORM_PATH = SCRIPTS_DIR / "closure_summary.py"
HELPERS_PATH = SCRIPTS_DIR / "_stub_helpers.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def query_closure():
    _load("_stub_helpers", HELPERS_PATH)
    return _load("query_closure_items", QUERY_PATH)


@pytest.fixture()
def transform():
    _load("_stub_helpers", HELPERS_PATH)
    return _load("closure_summary", TRANSFORM_PATH)


def _run_query(query, tmp_path, ids="ISSUE-001,ISSUE-002,ISSUE-003,ISSUE-004,ISSUE-005,ISSUE-006,ISSUE-007"):
    sys.argv = [
        "query_closure_items.py",
        "--issue-ids", ids,
        "--owner-department", "运行部",
        "--verification-period", "2026-04-01..2026-05-15",
        "--output-dir", str(tmp_path),
    ]
    rc = query.main()
    assert rc == 0
    return tmp_path / "data" / "closure_items.json"


def _run_transform(transform, input_path, tmp_path):
    sys.argv = [
        "closure_summary.py",
        "--input", str(input_path),
        "--output-dir", str(tmp_path),
    ]
    rc = transform.main()
    assert rc == 0
    return json.loads((tmp_path / "data" / "closure_summary.json").read_text(encoding="utf-8"))


def test_demo_covers_all_5_statuses(query_closure, tmp_path):
    data = _run_query(query_closure, tmp_path)
    raw = json.loads(data.read_text(encoding="utf-8"))
    statuses = Counter(it["status"] for it in raw["closure_items"])
    # Cycle of 5 statuses × 7 items → at least 1 of each
    for status in ("pending", "in_progress", "verifying", "closed", "reopened"):
        assert statuses[status] >= 1, f"demo must cover status={status}; got {statuses}"


def test_no_interpretive_contract_fields(query_closure, transform, tmp_path):
    """Factual report — must NOT have findings/evidence/confidence/human_review_required."""
    data = _run_query(query_closure, tmp_path)
    result = _run_transform(transform, data, tmp_path)
    forbidden = ("findings", "evidence", "confidence", "human_review_required", "summary_markdown")
    for field in forbidden:
        assert field not in result, f"factual closure_summary must NOT contain '{field}'"


def test_completion_rate_formula(query_closure, transform, tmp_path):
    data = _run_query(query_closure, tmp_path)
    raw = json.loads(data.read_text(encoding="utf-8"))
    result = _run_transform(transform, data, tmp_path)
    total = len(raw["closure_items"])
    closed = sum(1 for it in raw["closure_items"] if it["status"] == "closed")
    assert result["overall_status"]["completion_rate"] == round(closed / total, 4)
    assert result["overall_status"]["total"] == total
    assert result["overall_status"]["closed_count"] == closed
    assert result["overall_status"]["unclosed_count"] == total - closed


def test_status_distribution_always_has_5_rows(query_closure, transform, tmp_path):
    data = _run_query(query_closure, tmp_path)
    result = _run_transform(transform, data, tmp_path)
    dist = result["status_distribution"]
    statuses_in_dist = [row["status"] for row in dist]
    assert statuses_in_dist == ["pending", "in_progress", "verifying", "closed", "reopened"]


def test_unclosed_items_excludes_closed(query_closure, transform, tmp_path):
    data = _run_query(query_closure, tmp_path)
    result = _run_transform(transform, data, tmp_path)
    for item in result["unclosed_items"]:
        assert item["status"] != "closed"


def test_reopened_items_flagged_as_risk(query_closure, transform, tmp_path):
    data = _run_query(query_closure, tmp_path)
    result = _run_transform(transform, data, tmp_path)
    risk_kinds = {r["kind"] for r in result["risk_items"]}
    assert "reopened" in risk_kinds, "reopened items must be flagged as risk"


def test_overdue_detection(transform, tmp_path):
    """Synthetic input where due_date is in the past and status != closed."""
    today = date.today()
    raw = {
        "schema_version": "1",
        "verification_period": "",
        "closure_items": [
            {
                "id": "X-1",
                "title": "Overdue still open",
                "status": "in_progress",
                "owner": "x",
                "department": "运行部",
                "created_at": (today - timedelta(days=60)).isoformat(),
                "due_date": (today - timedelta(days=10)).isoformat(),
                "closed_at": None,
                "actions": [],
                "verification_results": [],
                "notes": "",
            }
        ],
    }
    in_path = tmp_path / "synth.json"
    in_path.write_text(json.dumps(raw), encoding="utf-8")
    result = _run_transform(transform, in_path, tmp_path)
    risk_kinds = {r["kind"] for r in result["risk_items"]}
    assert "overdue" in risk_kinds


def test_level_critical_on_reopened(query_closure, transform, tmp_path):
    """Demo has at least one reopened → overall_status.level == critical."""
    data = _run_query(query_closure, tmp_path)
    result = _run_transform(transform, data, tmp_path)
    assert result["overall_status"]["level"] == "critical"


def test_closure_conclusion_mentions_completion_rate(query_closure, transform, tmp_path):
    data = _run_query(query_closure, tmp_path)
    result = _run_transform(transform, data, tmp_path)
    assert "%" in result["closure_conclusion"]


def test_invalid_empty_ids_emits_error(query_closure, tmp_path):
    sys.argv = [
        "query_closure_items.py",
        "--issue-ids", "",
        "--output-dir", str(tmp_path),
    ]
    assert query_closure.main() == 1
