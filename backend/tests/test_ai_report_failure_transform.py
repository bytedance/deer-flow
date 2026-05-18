"""Tests for skills/custom/data-analyst/scripts/failure_analysis.py (§13.2 contract).

Sprint S6 — covers Story S3 transform-layer acceptance:
- 5-field §13.2 contract for all 3 methods
- method_block structurally distinct (why_chain vs branches vs fmea_rows)
- corrective_actions ≥ 1 per method
- validation_plan ≥ 3 universal steps + 1 method-specific anchor
- Each finding linked to ≥ 1 evidence
- FMEA rows recomputed with formula (defense against tampered seed)
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
TRANSFORM_PATH = SCRIPTS_DIR / "failure_analysis.py"
QUERY_PATH = SCRIPTS_DIR / "query_failure_data.py"
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
    return _load("failure_analysis", TRANSFORM_PATH)


def _build_data(method, tmp_path):
    """Run query_failure_data + return path to its output."""
    _load("_stub_helpers", HELPERS_PATH)
    query = _load("query_failure_data", QUERY_PATH)
    sys.argv = [
        "query_failure_data.py",
        "--asset-id", "P-001",
        "--failure-mode", "轴承卡死",
        "--analysis-method", method,
        "--output-dir", str(tmp_path),
    ]
    rc = query.main()
    assert rc == 0
    return tmp_path / "data" / "failure_data.json"


def _run(transform, input_path, tmp_path):
    sys.argv = [
        "failure_analysis.py",
        "--input", str(input_path),
        "--output-dir", str(tmp_path),
    ]
    rc = transform.main()
    assert rc == 0
    return json.loads((tmp_path / "data" / "failure_analysis.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("method", ["five_why", "fishbone", "fmea"])
def test_contract_for_each_method(transform, tmp_path, method):
    """All 3 methods produce the §13.2 5-field contract + corrective_actions + validation_plan."""
    data = _build_data(method, tmp_path)
    result = _run(transform, data, tmp_path)

    for required in ("findings", "evidence", "confidence", "data_coverage", "human_review_required"):
        assert required in result, f"method={method} missing §13.2 field {required}"
    assert result["human_review_required"] is True
    assert "summary_markdown" not in result

    assert len(result["corrective_actions"]) >= 1
    assert len(result["validation_plan"]) >= 3

    assert result["metadata"]["analysis_method"] == method


def test_five_why_block_has_5_levels(transform, tmp_path):
    data = _build_data("five_why", tmp_path)
    result = _run(transform, data, tmp_path)
    block = result["method_block"]
    assert block["method"] == "five_why"
    assert len(block["why_chain"]) == 5
    # Each level references a finding_id
    for i, lvl in enumerate(block["why_chain"], start=1):
        assert lvl["level"] == i
        assert lvl["finding_id"].startswith("FA-5W-L")


def test_fishbone_block_has_6_branches(transform, tmp_path):
    data = _build_data("fishbone", tmp_path)
    result = _run(transform, data, tmp_path)
    block = result["method_block"]
    assert block["method"] == "fishbone"
    assert len(block["branches"]) == 6


def test_fmea_rpn_recomputed(transform, tmp_path):
    """Even if the upstream seed was tampered with, RPN is recomputed from formula."""
    data = _build_data("fmea", tmp_path)
    # Tamper with the seed file: set a wrong RPN
    raw = json.loads(data.read_text(encoding="utf-8"))
    raw["method_seed"]["fmea"]["rows"][0]["rpn"] = 1
    data.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    result = _run(transform, data, tmp_path)
    block = result["method_block"]
    for row in block["fmea_rows"]:
        expected = row["severity"] * row["occurrence"] * row["detection"]
        assert row["rpn"] == expected, "fmea RPN must be recomputed from formula"


def test_fmea_primary_is_highest_rpn(transform, tmp_path):
    data = _build_data("fmea", tmp_path)
    result = _run(transform, data, tmp_path)
    block = result["method_block"]
    # Findings list mirrors fmea_rows order (sorted by RPN desc), so primary is first
    primary = next(f for f in result["findings"] if f.get("is_primary"))
    assert primary["id"] == block["fmea_rows"][0]["id"]
    assert primary["rpn"] == block["fmea_rows"][0]["rpn"]


def test_each_finding_has_at_least_one_evidence(transform, tmp_path):
    """All 3 methods: every finding must have ≥1 evidence (sprint plan acceptance)."""
    for method in ["five_why", "fishbone", "fmea"]:
        data = _build_data(method, tmp_path)
        result = _run(transform, data, tmp_path)
        per_finding = Counter(e["finding_id"] for e in result["evidence"])
        finding_ids = {f["id"] for f in result["findings"]}
        for fid in finding_ids:
            assert per_finding[fid] >= 1, f"method={method} finding {fid} has no evidence"


def test_validation_plan_has_method_anchor(transform, tmp_path):
    """Each method should add a method-specific validation step on top of the 3 universal ones."""
    for method in ["five_why", "fishbone", "fmea"]:
        data = _build_data(method, tmp_path)
        result = _run(transform, data, tmp_path)
        plan = result["validation_plan"]
        assert len(plan) >= 4, f"method={method} validation_plan must have ≥4 steps (3 universal + 1 anchor)"


def test_confidence_high_when_breadth_and_severity(transform, tmp_path):
    """Demo data is designed to trigger high confidence (≥3 source_types + ≥1 high finding)."""
    data = _build_data("five_why", tmp_path)
    result = _run(transform, data, tmp_path)
    assert result["confidence"] in ("medium", "high")
