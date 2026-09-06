"""Regression coverage for #3758: macOS nginx argv rewriting broke make stop."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVE_SH = REPO_ROOT / "scripts" / "serve.sh"


def _extract_shell_function(name: str) -> str:
    text = SERVE_SH.read_text(encoding="utf-8")
    marker = f"{name}() {{"
    start = text.index(marker)
    depth = 0
    chunks: list[str] = []

    for line in text[start:].splitlines(keepends=True):
        chunks.append(line)
        depth += line.count("{") - line.count("}")
        if depth == 0:
            return "".join(chunks)

    raise AssertionError(f"Could not extract shell function {name}")


def _is_repo_nginx_pid(
    *,
    command: str,
    args: str,
    repo_root: Path,
    deerflow_pid: bool = False,
) -> bool:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required to exercise serve.sh helpers")

    function = _extract_shell_function("_is_repo_nginx_pid")
    script = f"""
REPO_ROOT={shlex.quote(str(repo_root))}
DEERFLOW_ROOTS={shlex.quote(str(repo_root))}
FAKE_COMMAND={shlex.quote(command)}
FAKE_ARGS={shlex.quote(args)}
FAKE_DEERFLOW_PID={1 if deerflow_pid else 0}

_is_deerflow_pid() {{
    [ "$FAKE_DEERFLOW_PID" = "1" ]
}}

ps() {{
    case "$*" in
        *"-o comm="*) printf '%s\\n' "$FAKE_COMMAND" ;;
        *"-o args="*) printf '%s\\n' "$FAKE_ARGS" ;;
        *) return 1 ;;
    esac
}}

{function}

_is_repo_nginx_pid 12345
"""
    result = subprocess.run([bash, "-c", script], check=False)
    return result.returncode == 0


def test_repo_nginx_pid_accepts_macos_rewritten_master_command(tmp_path):
    repo_root = tmp_path / "deer-flow"
    nginx_conf = repo_root / "docker" / "nginx" / "nginx.local.conf"

    assert _is_repo_nginx_pid(
        command=f"nginx: master process /opt/homebrew/bin/nginx -c {nginx_conf}",
        args=f"nginx: master process /opt/homebrew/bin/nginx -c {nginx_conf} -p {repo_root}",
        repo_root=repo_root,
    )


def test_repo_nginx_pid_accepts_macos_rewritten_worker_after_repo_check(tmp_path):
    repo_root = tmp_path / "deer-flow"

    assert _is_repo_nginx_pid(
        command="nginx: worker process",
        args="nginx: worker process",
        repo_root=repo_root,
        deerflow_pid=True,
    )


@pytest.mark.parametrize(
    ("command", "args", "deerflow_pid"),
    [
        ("nginx: worker process", "nginx: worker process", False),
        ("python", "python -m nginx /tmp/deer-flow/docker/nginx/nginx.local.conf", True),
    ],
)
def test_repo_nginx_pid_rejects_unowned_or_non_nginx_processes(
    tmp_path,
    command: str,
    args: str,
    deerflow_pid: bool,
):
    assert not _is_repo_nginx_pid(
        command=command,
        args=args,
        repo_root=tmp_path / "deer-flow",
        deerflow_pid=deerflow_pid,
    )
