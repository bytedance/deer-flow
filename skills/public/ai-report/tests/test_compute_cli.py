"""Subprocess-driven CLI test for scripts/compute.py."""

from __future__ import annotations

import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _run_compute(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "compute.py"), *args],
        capture_output=True, text=True, check=False,
    )


def test_compute_cli_help():
    result = _run_compute("--help")
    assert result.returncode == 0
    for sub in ("extract-ir", "validate", "evaluate", "apply-computed"):
        assert sub in result.stdout, f"missing subcommand {sub}"


def test_compute_cli_no_args():
    result = _run_compute()
    assert result.returncode != 0


def test_compute_extract_ir_writes_ir_json(tmp_path):
    # extract_ir regex matches: `> 计算: name = "X", prompt = "Y"[, examples = [...]]`
    parsed = {
        "sections": [{
            "title": "示例",
            "reports": [{
                "title": "示例表",
                "org_contexts": [],
                "time_info": ["2026-01"],
                "headers": [],
                "compute_block_md": (
                    '> 计算: name = "利润同比", prompt = "2024值减2023值再除2023值", '
                    'examples = [{"inputs": {"BAS_0263@2023": 100, "BAS_0263@2024": 120}, "expected": 0.2}]'
                ),
            }],
        }],
    }
    parsed_path = tmp_path / "parsed.json"
    parsed_path.write_text(json.dumps(parsed), encoding="utf-8")
    out = tmp_path / "ir.json"
    result = _run_compute("extract-ir", "--parsed", str(parsed_path), "--out", str(out))
    assert result.returncode == 0, f"stderr: {result.stderr}"
    ir = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(ir, list)
    assert ir[0]["name"] == "利润同比"
    assert ir[0]["prompt"] == "2024值减2023值再除2023值"
    assert len(ir[0]["examples"]) == 1


def test_compute_apply_computed_merges_column(tmp_path):
    wide = [
        {"branch_num": "A", "x@2026": "100.0"},
        {"branch_num": "B", "x@2026": "200.0"},
    ]
    # JSON round-trip forces strings; CLI decodes back and outputs string-preserved.
    computed = {"yoy@2026": ["0.20", "0.40"]}
    wide_path = tmp_path / "wide.json"
    wide_path.write_text(json.dumps(wide), encoding="utf-8")
    computed_path = tmp_path / "computed.json"
    computed_path.write_text(json.dumps(computed), encoding="utf-8")
    out = tmp_path / "wide.out.json"
    result = _run_compute(
        "apply-computed",
        "--wide", str(wide_path),
        "--computed", str(computed_path),
        "--out", str(out),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    merged = json.loads(out.read_text(encoding="utf-8"))
    assert len(merged) == 2
    assert merged[0]["branch_num"] == "A"
    assert merged[0]["yoy@2026"] == "0.20"