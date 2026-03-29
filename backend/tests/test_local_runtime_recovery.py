"""Regression tests for local runtime recovery shell helpers."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "local-runtime-lib.sh"


def _run_shell(command: str) -> str:
    return subprocess.check_output(["bash", "-lc", command], text=True).strip()


def test_health_sample_rejects_split_gateway_and_frontend_health():
    command = (
        f"source '{SCRIPT_PATH}' && "
        "if is_healthy_runtime_sample 200 502 200 1; then echo healthy; else echo unhealthy; fi"
    )

    assert _run_shell(command) == "unhealthy"


def test_health_sample_requires_live_frontend_pid():
    command = (
        f"source '{SCRIPT_PATH}' && "
        "if is_healthy_runtime_sample 200 200 200 0; then echo healthy; else echo unhealthy; fi"
    )

    assert _run_shell(command) == "unhealthy"


def test_next_stable_health_count_only_advances_for_consecutive_healthy_samples():
    command = (
        f"source '{SCRIPT_PATH}' && "
        "count=0; "
        "count=$(next_stable_health_count \"$count\" 200 200 200 1); "
        "count=$(next_stable_health_count \"$count\" 200 200 200 1); "
        "count=$(next_stable_health_count \"$count\" 200 502 200 1); "
        "echo \"$count\""
    )

    assert _run_shell(command) == "0"


def test_clear_stale_frontend_lock_removes_lock_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        frontend_dir = Path(tmpdir)
        lock_file = frontend_dir / ".next" / "dev" / "lock"
        lock_file.parent.mkdir(parents=True)
        lock_file.write_text("")

        command = (
            f"source '{SCRIPT_PATH}' && "
            f"clear_stale_frontend_lock '{frontend_dir}' && "
            f"if [[ -e '{lock_file}' ]]; then echo present; else echo missing; fi"
        )

        assert _run_shell(command) == "missing"
