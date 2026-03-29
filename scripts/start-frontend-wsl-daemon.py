#!/usr/bin/env python3
"""Launch the WSL frontend as a detached process with pid/log files."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value) if value else default


def _existing_pid(pid_file: Path) -> int | None:
    if not pid_file.exists():
        return None

    text = pid_file.read_text().strip()
    if not text:
        return None

    try:
        pid = int(text)
    except ValueError:
        return None

    try:
        os.kill(pid, 0)
    except OSError:
        return None

    return pid


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    frontend_dir = _env_path("DEERFLOW_FRONTEND_DIR", repo_root / "frontend")
    log_dir = _env_path("DEERFLOW_LOG_DIR", repo_root / "logs")
    pid_file = log_dir / os.environ.get("DEERFLOW_FRONTEND_PID_FILE", "frontend-wsl.pid")
    stdout_log = log_dir / os.environ.get("DEERFLOW_FRONTEND_STDOUT_LOG", "frontend-wsl.log")
    stderr_log = log_dir / os.environ.get("DEERFLOW_FRONTEND_STDERR_LOG", "frontend-wsl.err.log")
    entrypoint = _env_path("DEERFLOW_FRONTEND_ENTRYPOINT", repo_root / "run-frontend-wsl.sh")
    command_text = os.environ.get("DEERFLOW_FRONTEND_COMMAND")

    log_dir.mkdir(parents=True, exist_ok=True)
    (frontend_dir / ".next" / "dev").mkdir(parents=True, exist_ok=True)

    lock_file = frontend_dir / ".next" / "dev" / "lock"
    if lock_file.exists():
        lock_file.unlink()

    pid = _existing_pid(pid_file)
    if pid is not None:
        print(pid)
        return 0

    if command_text:
        command = shlex.split(command_text)
    else:
        command = ["/usr/bin/bash", str(entrypoint)]

    with stdout_log.open("ab") as stdout, stderr_log.open("ab") as stderr:
        process = subprocess.Popen(
            command,
            cwd=frontend_dir,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )

    pid_file.write_text(f"{process.pid}\n")
    print(process.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
