"""Offline regression tests for scripts/sync_labels.py.

The status glyphs (✓ / ✗) used to crash the sync with UnicodeEncodeError after
`gh label create --force` had already run, on hosts whose stdio encoding cannot
represent them (Windows code pages, POSIX C locale, PYTHONIOENCODING=ascii);
`gh`'s UTF-8 diagnostics were decoded with the host locale instead.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# The script imports pyyaml at module load; the stub keeps these tests hermetic
# (pyyaml is not a backend dependency — the Makefile runs the script with
# `uv run --with pyyaml`).
STUB_YAML = """\
def safe_load(text):
    return {
        "labels": [
            {"name": "test-label", "color": "#ff0000", "description": "中文 描述"},
        ]
    }
"""

LABELS_YAML = """\
labels:
  - name: test-label
    color: ff0000
    description: "中文 描述"
"""

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the stub gh is a POSIX shell script")


@pytest.fixture
def script_checkout(tmp_path: Path) -> Path:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (tmp_path / ".github").mkdir()
    (scripts_dir / "sync_labels.py").write_text(
        (REPO_ROOT / "scripts" / "sync_labels.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / ".github" / "labels.yml").write_text(LABELS_YAML, encoding="utf-8")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "yaml.py").write_text(STUB_YAML, encoding="utf-8")
    return tmp_path


def _stub_gh(tmp_path: Path, body: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _run(script_checkout: Path, tmp_path: Path, bin_dir: Path | None, *args: str):
    env = {
        **os.environ,
        "PYTHONIOENCODING": "ascii",
        "PYTHONPATH": str(script_checkout / "stubs"),
    }
    if bin_dir is not None:
        env["PATH"] = f"{bin_dir}:{os.environ.get('PATH', '')}"
    return subprocess.run(
        [sys.executable, str(script_checkout / "scripts" / "sync_labels.py"), *args],
        env=env,
        capture_output=True,
        check=False,
        timeout=60,
    )


def test_success_path_emits_utf8_glyphs_into_non_utf8_stdout(script_checkout: Path, tmp_path: Path):
    bin_dir = _stub_gh(tmp_path, "exit 0")

    result = _run(script_checkout, tmp_path, bin_dir, "--repo", "octo/demo")

    # Before the fix this crashed with UnicodeEncodeError after the label was
    # already created on GitHub.
    assert result.returncode == 0, result.stderr
    assert "✓ test-label".encode() in result.stdout
    assert "Done — 1 labels in sync.".encode() in result.stdout
    assert b"UnicodeEncodeError" not in result.stderr


def test_gh_failure_decodes_utf8_and_reports_gracefully(script_checkout: Path, tmp_path: Path):
    bin_dir = _stub_gh(tmp_path, "printf '%s\\n' '中文 失败' >&2\nexit 1")

    result = _run(script_checkout, tmp_path, bin_dir, "--repo", "octo/demo")

    # Before the fix the UTF-8 stderr was decoded with the host codec and
    # raised UnicodeDecodeError instead of printing the failure line.
    assert result.returncode == 1, result.stdout
    assert "✗ test-label: 中文 失败".encode() in result.stderr
    assert b"1 label(s) failed to sync" in result.stderr
    assert b"Traceback" not in result.stderr
    assert b"UnicodeDecodeError" not in result.stderr


def test_dry_run_works_under_ascii_stdout(script_checkout: Path, tmp_path: Path):
    # No gh on PATH: the dry run must not invoke it.
    result = _run(script_checkout, tmp_path, None, "--dry-run")

    assert result.returncode == 0, result.stderr
    assert b"[dry-run]" in result.stdout
    assert "Done — 1 labels in sync.".encode() in result.stdout
