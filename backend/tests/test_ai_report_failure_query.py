"""Tests for skills/custom/data-analyst/scripts/query_failure_data.py.

Sprint S6 — covers Story S3 query-layer acceptance:
- All 3 analysis methods (five_why / fishbone / fmea) produce method_seed
- Method-seed structure correctness (5 levels / 6 categories / FMEA RPN)
- Invalid method / empty asset-id / empty failure-mode emit structured errors
- Shared signal blocks (operations / maintenance / inspections / spares) always present
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts"
SCRIPT_PATH = SCRIPTS_DIR / "query_failure_data.py"
HELPERS_PATH = SCRIPTS_DIR / "_stub_helpers.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def query_failure_data():
    _load("_stub_helpers", HELPERS_PATH)
    return _load("query_failure_data", SCRIPT_PATH)


def _run(query, tmp_path, method="five_why", asset_id="P-001", failure_mode="轴承卡死"):
    sys.argv = [
        "query_failure_data.py",
        "--asset-id", asset_id,
        "--failure-mode", failure_mode,
        "--analysis-method", method,
        "--output-dir", str(tmp_path),
    ]
    rc = query.main()
    assert rc == 0
    out = tmp_path / "data" / "failure_data.json"
    return json.loads(out.read_text(encoding="utf-8"))


def test_shared_signal_blocks_present(query_failure_data, tmp_path):
    """Operations + maintenance + inspections + spares + environment always emitted."""
    result = _run(query_failure_data, tmp_path)
    for field in ("operations", "maintenance", "inspections", "spares", "environment"):
        assert field in result
    assert len(result["operations"]) > 0
    assert len(result["maintenance"]) >= 3
    assert len(result["inspections"]) >= 2
    assert len(result["spares"]) >= 2


def test_five_why_seed_has_5_levels(query_failure_data, tmp_path):
    """sprint plan S3 acceptance: 5why must produce exactly 5 levels."""
    result = _run(query_failure_data, tmp_path, method="five_why")
    seed = result["method_seed"]["five_why"]
    assert seed is not None
    assert len(seed["levels"]) == 5
    for i, level in enumerate(seed["levels"], start=1):
        assert level["level"] == i
        for field in ("why", "candidate_cause", "evidence_hint"):
            assert field in level
    # Other method seeds should be None
    assert result["method_seed"]["fishbone"] is None
    assert result["method_seed"]["fmea"] is None


def test_fishbone_seed_has_6_categories(query_failure_data, tmp_path):
    """sprint plan S3 acceptance: fishbone must cover 人/机/料/法/环/测."""
    result = _run(query_failure_data, tmp_path, method="fishbone")
    seed = result["method_seed"]["fishbone"]
    assert seed is not None
    categories = [b["category"] for b in seed["branches"]]
    assert categories == ["人", "机", "料", "法", "环", "测"]
    assert result["method_seed"]["five_why"] is None
    assert result["method_seed"]["fmea"] is None


def test_fmea_seed_has_rpn_computed(query_failure_data, tmp_path):
    """sprint plan S3 acceptance: FMEA RPN = severity × occurrence × detection."""
    result = _run(query_failure_data, tmp_path, method="fmea")
    seed = result["method_seed"]["fmea"]
    assert seed is not None
    rows = seed["rows"]
    assert len(rows) >= 3
    for row in rows:
        expected = row["severity"] * row["occurrence"] * row["detection"]
        assert row["rpn"] == expected, (
            f"FMEA RPN formula mismatch on {row['id']}: "
            f"{row['severity']}×{row['occurrence']}×{row['detection']} != {row['rpn']}"
        )


def test_invalid_method_emits_error(query_failure_data, tmp_path):
    sys.argv = [
        "query_failure_data.py",
        "--asset-id", "P-001",
        "--failure-mode", "x",
        "--analysis-method", "unknown_method",
        "--output-dir", str(tmp_path),
    ]
    assert query_failure_data.main() == 1


def test_empty_asset_id_emits_error(query_failure_data, tmp_path):
    sys.argv = [
        "query_failure_data.py",
        "--asset-id", "   ",
        "--failure-mode", "x",
        "--output-dir", str(tmp_path),
    ]
    assert query_failure_data.main() == 1


def test_empty_failure_mode_emits_error(query_failure_data, tmp_path):
    sys.argv = [
        "query_failure_data.py",
        "--asset-id", "P-001",
        "--failure-mode", "",
        "--output-dir", str(tmp_path),
    ]
    assert query_failure_data.main() == 1


def test_data_source_demo_fallback(query_failure_data, tmp_path):
    result = _run(query_failure_data, tmp_path)
    assert result["data_source"] == "demo_fallback"


def test_spares_remaining_pct_present(query_failure_data, tmp_path):
    result = _run(query_failure_data, tmp_path)
    for sp in result["spares"]:
        assert "remaining_pct" in sp
        assert "expected_life_days" in sp
