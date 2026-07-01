"""Lock the intermediate JSON schema shared with chatbi-report.

This test enforces that ai-report's parse_md.py + assemble_wide_duckdb.py
output schemas stay byte-compatible with chatbi-report's expectations.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
EXAMPLES = SCRIPTS_DIR.parent / "example"

REQUIRED_PARSED_TOP_KEYS = {"title", "sections", "all_idx_ids"}
REQUIRED_SECTION_KEYS = {"title", "reports"}
REQUIRED_REPORT_KEYS = {
    "title", "org_contexts", "time_info", "headers",
    "data_rows", "computed_specs", "description_prompt",
}

REQUIRED_WIDE_KEYS = {"branch_num"}


def test_parsed_schema_top(tmp_path):
    md = EXAMPLES / "wangyi_2026_03.md"
    out = tmp_path / "p.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "parse_md.py"),
         "--md", str(md), "--out", str(out)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert REQUIRED_PARSED_TOP_KEYS.issubset(data.keys()), (
        f"missing keys in parsed.json top-level: {REQUIRED_PARSED_TOP_KEYS - data.keys()}"
    )
    sec = data["sections"][0]
    assert REQUIRED_SECTION_KEYS.issubset(sec.keys())
    rep = sec["reports"][0]
    assert REQUIRED_REPORT_KEYS.issubset(rep.keys())


def test_wide_schema_has_branch_num(tmp_path):
    """Synthesize a minimal parsed.json + query.json to drive assemble_wide_duckdb."""
    parsed = {
        "sections": [{
            "title": "示例",
            "reports": [{
                "title": "示例表",
                "org_contexts": [{"org_ecd": "A", "org_name": "A"}],
                "time_info": ["2026"],
                "headers": [],
            }],
        }],
    }
    query = {
        "metric_facts": [
            {"org_ecd": "A", "idx_id": "BAS_001", "period": "2026",
             "numeric_value": "100", "data_dt": "2026-12-31", "idx_name": "指标",
             "status": "ok", "error_message": None},
        ],
    }
    parsed_path = tmp_path / "p.json"
    parsed_path.write_text(json.dumps(parsed), encoding="utf-8")
    query_path = tmp_path / "q.json"
    query_path.write_text(json.dumps(query), encoding="utf-8")
    out = tmp_path / "wide.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "assemble_wide_duckdb.py"),
         "--parsed", str(parsed_path), "--query", str(query_path),
         "--out", str(out)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert REQUIRED_WIDE_KEYS.issubset(data[0].keys())