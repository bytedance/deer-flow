from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from shutil import which

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "cleanup-containers.sh"
BASH_CANDIDATES = [
    Path(r"C:\Program Files\Git\bin\bash.exe"),
    Path(which("bash")) if which("bash") else None,
]
BASH_EXECUTABLE = next(
    (str(path) for path in BASH_CANDIDATES if path is not None and path.exists() and "WindowsApps" not in str(path)),
    None,
)

if BASH_EXECUTABLE is None:
    pytestmark = pytest.mark.skip(reason="bash is required for cleanup-containers.sh tests")


def _make_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_cleanup_containers_reports_invalid_apple_container_json():
    """Script must report JSON parse errors on Apple Container list output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bin_dir = Path(tmpdir)
        _make_executable(
            bin_dir / "container",
            '#!/usr/bin/env bash\nif [ "$1" = "list" ]; then\n  printf \'{invalid json\'\n  exit 0\nfi\nexit 0\n',
        )

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"

        result = subprocess.run(
            [BASH_EXECUTABLE, str(SCRIPT_PATH)],
            text=True,
            capture_output=True,
            env=env,
        )

    assert result.returncode != 0
    assert "Failed to parse Apple Container list JSON" in result.stderr
    assert "Failed to inspect Apple Container containers" in result.stderr


def test_cleanup_containers_skips_malformed_entries():
    """Script must skip malformed container entries and keep processing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bin_dir = Path(tmpdir)
        _make_executable(
            bin_dir / "container",
            '#!/usr/bin/env bash\nif [ "$1" = "list" ]; then\n  cat <<\'EOF\'\n[{"configuration":"broken"},{"configuration":{"id":"deer-flow-sandbox-1"}}]\nEOF\n  exit 0\nfi\nif [ "$1" = "stop" ]; then\n  exit 0\nfi\nexit 0\n',
        )

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"

        result = subprocess.run(
            [BASH_EXECUTABLE, str(SCRIPT_PATH)],
            text=True,
            capture_output=True,
            env=env,
        )

    assert result.returncode == 0
    assert "Skipping Apple Container entry with invalid configuration payload" in result.stderr
    assert "deer-flow-sandbox-1" in result.stdout or "deer-flow-sandbox-1" in result.stderr
