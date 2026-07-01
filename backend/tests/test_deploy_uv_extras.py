"""Regression coverage for production deploy.sh UV_EXTRAS propagation."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _backend_dockerfile_uv_sync_script() -> str:
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(r"""sh -c (?P<quote>["'])(?P<script>.*?uv sync.*?)(?P=quote)""", dockerfile, re.S)
    assert match is not None
    return match.group("script").replace("\\\n", "\n")


def test_backend_dockerfile_expands_multiple_uv_extras(tmp_path):
    """Dockerfile build args must become repeated uv --extra flags."""
    workdir = tmp_path / "work"
    backend = workdir / "backend"
    backend.mkdir(parents=True)
    capture = tmp_path / "uv_args.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(
        '#!/usr/bin/env sh\nfor arg in "$@"; do printf "%s\\n" "$arg"; done > "$CAPTURE_UV_ARGS"\n',
        encoding="utf-8",
    )
    uv.chmod(0o755)

    env = os.environ.copy()
    env["CAPTURE_UV_ARGS"] = str(capture)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["UV_EXTRAS"] = "discord,postgres"

    subprocess.run(
        ["sh", "-c", _backend_dockerfile_uv_sync_script()],
        cwd=workdir,
        env=env,
        check=True,
    )

    assert capture.read_text(encoding="utf-8").splitlines() == [
        "sync",
        "--extra",
        "discord",
        "--extra",
        "postgres",
    ]


def test_backend_dockerfile_rejects_glob_uv_extra(tmp_path):
    """Dockerfile extras must reject globs before invoking uv."""
    workdir = tmp_path / "work"
    backend = workdir / "backend"
    backend.mkdir(parents=True)
    (backend / "glob-match").touch()
    capture = tmp_path / "uv_args.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(
        '#!/usr/bin/env sh\nfor arg in "$@"; do printf "%s\\n" "$arg"; done > "$CAPTURE_UV_ARGS"\n',
        encoding="utf-8",
    )
    uv.chmod(0o755)

    env = os.environ.copy()
    env["CAPTURE_UV_ARGS"] = str(capture)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["UV_EXTRAS"] = "postgres,*"

    result = subprocess.run(
        ["sh", "-c", _backend_dockerfile_uv_sync_script()],
        cwd=workdir,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert not capture.exists()


def test_deploy_build_auto_detects_postgres_extra_when_other_extras_are_enabled(tmp_path):
    """Production image builds preserve every detected extra as Docker build tokens."""
    worktree = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "scripts", worktree / "scripts")
    shutil.copytree(REPO_ROOT / "docker", worktree / "docker")
    (worktree / "backend").mkdir()
    (worktree / "config.yaml").write_text(
        "database:\n  backend: postgres\nchannels:\n  discord:\n    enabled: true\n",
        encoding="utf-8",
    )
    (worktree / "extensions_config.json").write_text('{"mcpServers":{},"skills":{}}\n', encoding="utf-8")

    capture = tmp_path / "uv_extras.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        '#!/usr/bin/env sh\nprintf "%s" "${UV_EXTRAS:-}" > "$CAPTURE_UV_EXTRAS"\nexit 0\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)

    env = os.environ.copy()
    env.pop("UV_EXTRAS", None)
    env["CAPTURE_UV_EXTRAS"] = str(capture)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    subprocess.run(
        ["bash", str(worktree / "scripts" / "deploy.sh"), "build"],
        cwd=worktree,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    assert capture.read_text(encoding="utf-8") == "discord,postgres"


def test_deploy_uses_dotenv_without_sourcing_shell_syntax(tmp_path):
    """Repo-root .env is Docker Compose dotenv, not a shell script."""
    worktree = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "scripts", worktree / "scripts")
    shutil.copytree(REPO_ROOT / "docker", worktree / "docker")
    (worktree / "backend").mkdir()
    (worktree / "config.yaml").write_text(
        "database:\n  backend: postgres\n",
        encoding="utf-8",
    )
    (worktree / "extensions_config.json").write_text('{"mcpServers":{},"skills":{}}\n', encoding="utf-8")
    marker = tmp_path / "sourced-marker"
    (worktree / ".env").write_text(
        f"DATABASE_URL=postgresql://user:pass@localhost/db?sslmode=require&application_name=deer\nUNSAFE=$(touch {shlex.quote(str(marker))})\nUV_EXTRAS=discord\n",
        encoding="utf-8",
    )

    capture_extras = tmp_path / "uv_extras.txt"
    capture_args = tmp_path / "docker_args.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        '#!/usr/bin/env sh\nprintf "%s" "${UV_EXTRAS:-}" > "$CAPTURE_UV_EXTRAS"\nfor arg in "$@"; do printf "%s\\n" "$arg"; done > "$CAPTURE_DOCKER_ARGS"\nexit 0\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)

    env = os.environ.copy()
    env.pop("UV_EXTRAS", None)
    env["CAPTURE_UV_EXTRAS"] = str(capture_extras)
    env["CAPTURE_DOCKER_ARGS"] = str(capture_args)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    subprocess.run(
        ["bash", str(worktree / "scripts" / "deploy.sh"), "build"],
        cwd=worktree,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    assert not marker.exists()
    assert capture_extras.read_text(encoding="utf-8") == "discord"
    args = capture_args.read_text(encoding="utf-8").splitlines()
    assert "--env-file" in args
    assert str(worktree / ".env") in args


def test_deploy_build_auto_detects_postgres_extra_with_python_fallback(tmp_path):
    """Production deploy hosts may have python but no runnable python3."""
    worktree = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "scripts", worktree / "scripts")
    shutil.copytree(REPO_ROOT / "docker", worktree / "docker")
    (worktree / "backend").mkdir()
    (worktree / "config.yaml").write_text(
        "database:\n  backend: postgres\n",
        encoding="utf-8",
    )
    (worktree / "extensions_config.json").write_text('{"mcpServers":{},"skills":{}}\n', encoding="utf-8")

    capture = tmp_path / "uv_extras.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        '#!/usr/bin/env sh\nprintf "%s" "${UV_EXTRAS:-}" > "$CAPTURE_UV_EXTRAS"\nexit 0\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    python3 = bin_dir / "python3"
    python3.write_text("#!/usr/bin/env sh\nexit 1\n", encoding="utf-8")
    python3.chmod(0o755)
    python = bin_dir / "python"
    python.write_text(
        f'#!/usr/bin/env sh\nexec {shlex.quote(sys.executable)} "$@"\n',
        encoding="utf-8",
    )
    python.chmod(0o755)

    env = os.environ.copy()
    env.pop("UV_EXTRAS", None)
    env["CAPTURE_UV_EXTRAS"] = str(capture)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    subprocess.run(
        ["bash", str(worktree / "scripts" / "deploy.sh"), "build"],
        cwd=worktree,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    assert capture.read_text(encoding="utf-8") == "postgres"
