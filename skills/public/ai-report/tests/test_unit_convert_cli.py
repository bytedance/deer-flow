"""Subprocess-driven CLI test for scripts/unit_convert.py."""

from __future__ import annotations

import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _run_unit_convert(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "unit_convert.py"), *args],
        capture_output=True, text=True, check=False,
    )


def test_unit_convert_cli_help_has_apply():
    result = _run_unit_convert("--help")
    assert result.returncode == 0
    assert "apply" in result.stdout


def test_unit_convert_cli_apply_preserves_decimal_precision(tmp_path):
    """1234567890.50 / 10000 must equal Decimal('123456.78905'), not float.

    The actual apply_units key for a basic column is `idx_id@period`. The leaf
    cell carries `idx_id='BAS_0263'` + `period='2026'` + `data_unit='万元'`.
    """
    wide = [{"branch_num": "王益联社", "BAS_0263@2026": "1234567890.50"}]
    headers = [[
        {"text": "利润总额", "data_unit": "万元", "is_computed": False,
         "idx_id": "BAS_0263", "period": "2026"},
    ]]
    wide_path = tmp_path / "wide.json"
    wide_path.write_text(json.dumps(wide), encoding="utf-8")
    headers_path = tmp_path / "headers.json"
    headers_path.write_text(json.dumps(headers), encoding="utf-8")
    out_path = tmp_path / "wide.out.json"
    result = _run_unit_convert(
        "apply", "--wide", str(wide_path),
        "--headers", str(headers_path), "--out", str(out_path),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    converted = json.loads(out_path.read_text(encoding="utf-8"))
    # Phase 1 invariant: converted value parses as Decimal with 5 fractional digits.
    val = Decimal(converted[0]["BAS_0263@2026"])
    expected = Decimal("123456.78905")
    assert val == expected, f"Decimal precision violated: {val} != {expected}"


def test_unit_convert_cli_apply_accepts_parsed_json_shape(tmp_path):
    """headers JSON may be the full parsed.json (sections > reports > headers)."""
    wide = [{"branch_num": "A", "x@2026": "50000"}]
    wide_path = tmp_path / "wide.json"
    wide_path.write_text(json.dumps(wide), encoding="utf-8")
    parsed_like = {
        "sections": [{
            "title": "示例",
            "reports": [{
                "headers": [[
                    {"text": "利润总额", "data_unit": "万元", "is_computed": False,
                     "idx_id": "x", "period": "2026"},
                ]],
            }],
        }],
    }
    headers_path = tmp_path / "headers.json"
    headers_path.write_text(json.dumps(parsed_like), encoding="utf-8")
    out_path = tmp_path / "wide.out.json"
    result = _run_unit_convert(
        "apply", "--wide", str(wide_path),
        "--headers", str(headers_path), "--out", str(out_path),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    converted = json.loads(out_path.read_text(encoding="utf-8"))
    # 50000 * 0.0001 = 5.0
    assert Decimal(converted[0]["x@2026"]) == Decimal("5")