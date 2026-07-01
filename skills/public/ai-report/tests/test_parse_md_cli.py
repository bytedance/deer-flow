"""Subprocess-driven CLI test for scripts/parse_md.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
EXAMPLES = SCRIPTS_DIR.parent / "example"

SAMPLE_MD = (EXAMPLES / "wangyi_2026_03.md").read_text(encoding="utf-8")


def test_parse_md_cli_writes_parsed_json(tmp_path):
    md = tmp_path / "in.md"
    md.write_text(SAMPLE_MD, encoding="utf-8")
    out = tmp_path / "out.parsed.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "parse_md.py"), "--md", str(md), "--out", str(out)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, f"parse_md CLI failed: {result.stderr}"
    assert out.exists(), "expected --out to be written"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "title" in data
    assert "sections" in data
    assert isinstance(data["sections"], list)
    assert "all_idx_ids" in data