"""Tests for skills/custom/data-analyst/scripts/query_fault_context.py.

Sprint S6 — covers Story S2 acceptance for the data step:
- 24h hourly operations samples × 3 metrics
- 5 alarms spanning info/warning/critical
- 3 work orders covering closed/in_progress/open
- 2 maintenance records
- Related-equipment flag respected
- Bad fault-time / empty equipment-id produce structured errors
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts"
SCRIPT_PATH = SCRIPTS_DIR / "query_fault_context.py"
HELPERS_PATH = SCRIPTS_DIR / "_stub_helpers.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def query_fault_context():
    _load("_stub_helpers", HELPERS_PATH)
    return _load("query_fault_context", SCRIPT_PATH)


def _run(query_fault_context, tmp_path, **kwargs):
    args = [
        "query_fault_context.py",
        "--fault-time", kwargs.get("fault_time", "2026-05-15"),
        "--equipment-id", kwargs.get("equipment_id", "P-001"),
        "--symptom", kwargs.get("symptom", "vibration high"),
        "--output-dir", str(tmp_path),
    ]
    if kwargs.get("include_related"):
        args.append("--include-related-equipment")
    sys.argv = args
    rc = query_fault_context.main()
    assert rc == 0
    out = tmp_path / "data" / "fault_context.json"
    return json.loads(out.read_text(encoding="utf-8"))


def test_operations_24h_three_metrics(query_fault_context, tmp_path):
    result = _run(query_fault_context, tmp_path)
    ops = result["operations"]
    # 24 hours × 3 metrics = 72 samples
    assert len(ops) == 72
    metrics = sorted({op["metric"] for op in ops})
    assert metrics == ["bearing_temp", "load_factor", "vibration_level"]


def test_operations_each_carry_id(query_fault_context, tmp_path):
    result = _run(query_fault_context, tmp_path)
    for op in result["operations"]:
        assert "id" in op and op["id"], "operations samples must carry an id for evidence chain"


def test_alarms_have_5_entries_with_critical(query_fault_context, tmp_path):
    result = _run(query_fault_context, tmp_path)
    alarms = result["alarms"]
    assert len(alarms) == 5
    levels = {a["level"] for a in alarms}
    assert "critical" in levels, "demo alarms must contain at least one critical entry"
    assert "warning" in levels


def test_work_orders_have_3_with_distinct_statuses(query_fault_context, tmp_path):
    result = _run(query_fault_context, tmp_path)
    wos = result["work_orders"]
    assert len(wos) == 3
    statuses = sorted({wo["status"] for wo in wos})
    # Must cover all 3 statuses (closed / in_progress / open)
    assert statuses == ["closed", "in_progress", "open"]


def test_maintenance_records_count(query_fault_context, tmp_path):
    result = _run(query_fault_context, tmp_path)
    assert len(result["maintenance_records"]) == 2


def test_related_equipment_flag_off(query_fault_context, tmp_path):
    result = _run(query_fault_context, tmp_path, include_related=False)
    assert result["related_equipment"] == []
    assert result["include_related"] is False


def test_related_equipment_flag_on(query_fault_context, tmp_path):
    result = _run(query_fault_context, tmp_path, include_related=True)
    assert len(result["related_equipment"]) == 2
    assert result["include_related"] is True


def test_invalid_fault_time_emits_error(query_fault_context, tmp_path):
    sys.argv = [
        "query_fault_context.py",
        "--fault-time", "not-a-date",
        "--equipment-id", "P-001",
        "--output-dir", str(tmp_path),
    ]
    rc = query_fault_context.main()
    assert rc == 1


def test_empty_equipment_id_emits_error(query_fault_context, tmp_path):
    sys.argv = [
        "query_fault_context.py",
        "--fault-time", "2026-05-15",
        "--equipment-id", "   ",
        "--output-dir", str(tmp_path),
    ]
    rc = query_fault_context.main()
    assert rc == 1


def test_data_source_demo_fallback(query_fault_context, tmp_path):
    result = _run(query_fault_context, tmp_path)
    assert result["data_source"] == "demo_fallback"
