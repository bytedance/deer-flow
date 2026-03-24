"""Regression tests for the WSL frontend daemon launcher."""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "start-frontend-wsl-daemon.py"


def test_launcher_clears_stale_lock_and_writes_a_live_pid():
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_root = Path(tmpdir)
        frontend_dir = temp_root / "frontend"
        log_dir = temp_root / "logs"
        lock_file = frontend_dir / ".next" / "dev" / "lock"
        pid_file = log_dir / "frontend-test.pid"

        frontend_dir.mkdir(parents=True)
        log_dir.mkdir(parents=True)
        lock_file.parent.mkdir(parents=True)
        lock_file.write_text("")

        env = os.environ | {
            "DEERFLOW_FRONTEND_DIR": str(frontend_dir),
            "DEERFLOW_LOG_DIR": str(log_dir),
            "DEERFLOW_FRONTEND_PID_FILE": pid_file.name,
            "DEERFLOW_FRONTEND_STDOUT_LOG": "frontend-test.log",
            "DEERFLOW_FRONTEND_STDERR_LOG": "frontend-test.err.log",
            "DEERFLOW_FRONTEND_COMMAND": "/usr/bin/python3 -c \"import time; time.sleep(60)\"",
        }

        pid = int(
            subprocess.check_output(
                ["/usr/bin/python3", str(SCRIPT_PATH)],
                text=True,
                env=env,
            ).strip()
        )

        try:
            assert not lock_file.exists()
            assert pid_file.read_text().strip() == str(pid)
            os.kill(pid, 0)
        finally:
            os.kill(pid, signal.SIGTERM)
