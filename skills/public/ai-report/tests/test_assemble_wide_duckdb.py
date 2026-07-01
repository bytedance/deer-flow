"""Subprocess-driven CLI test for scripts/assemble_wide_duckdb.py (Step 4).

Locks the Phase 1 invariant: DECIMAL(38,10) precision through PIVOT (no float).
"""

from __future__ import annotations

import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def test_assemble_wide_duckdb_pivots_with_decimal_precision(tmp_path):
    parsed = {
        "sections": [{
            "title": "示例",
            "reports": [{
                "title": "示例表",
                "org_contexts": [{"org_ecd": "王益联社", "org_name": "王益联社"}],
                "time_info": ["2025", "2026"],
                "headers": [],  # unused by this stage
            }],
        }],
    }
    query = {
        "metric_facts": [
            # Phase 1: numeric_value stored as string to preserve precision.
            {"org_ecd": "王益联社", "idx_id": "BAS_0263", "period": "2025",
             "numeric_value": "1234567890.50", "data_dt": "2025-12-31", "idx_name": "利润总额",
             "status": "ok", "error_message": None},
            {"org_ecd": "王益联社", "idx_id": "BAS_0263", "period": "2026",
             "numeric_value": "1150000000.00", "data_dt": "2026-12-31", "idx_name": "利润总额",
             "status": "ok", "error_message": None},
            # Failed query: status='query_failed' (sentinel — NOT in cell).
            {"org_ecd": "王益联社", "idx_id": "BAS_040", "period": "2026",
             "numeric_value": None, "data_dt": "2026-12-31", "idx_name": "存款余额",
             "status": "query_failed", "error_message": "endpoint 5xx"},
        ],
    }
    parsed_path = tmp_path / "parsed.json"
    parsed_path.write_text(json.dumps(parsed), encoding="utf-8")
    query_path = tmp_path / "query.json"
    query_path.write_text(json.dumps(query), encoding="utf-8")
    out_path = tmp_path / "wide.json"

    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "assemble_wide_duckdb.py"),
         "--parsed", str(parsed_path), "--query", str(query_path),
         "--out", str(out_path)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"

    wide = json.loads(out_path.read_text(encoding="utf-8"))
    assert isinstance(wide, list)
    row = next(r for r in wide if r["branch_num"] == "王益联社")
    # Decimal precision: 1234567890.50 stays exactly that, not float-rounded.
    assert Decimal(row["BAS_0263@2025"]) == Decimal("1234567890.50")
    # Failed query → None (NOT a sentinel string).
    assert row["BAS_040@2026"] is None, "failed query must render as None, not '⚠️QUERY_FAILED'"