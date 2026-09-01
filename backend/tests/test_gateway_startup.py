"""Regression coverage for local and Docker Gateway startup contracts."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _deploy_fixture(tmp_path: Path, *, docker_script: str) -> tuple[Path, dict[str, str]]:
    worktree = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "scripts", worktree / "scripts")
    shutil.copytree(REPO_ROOT / "docker", worktree / "docker")
    (worktree / "backend").mkdir()
    (worktree / "config.yaml").write_text("sandbox:\n  use: deerflow.sandbox:LocalSandboxProvider\n", encoding="utf-8")
    (worktree / "extensions_config.json").write_text('{"mcpServers":{},"skills":{}}\n', encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(docker_script, encoding="utf-8")
    docker.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["BETTER_AUTH_SECRET"] = "test-better-auth-secret"
    env["DEER_FLOW_INTERNAL_AUTH_TOKEN"] = "test-internal-auth-token"
    return worktree, env


def test_gateway_runtime_commands_never_sync_dependencies() -> None:
    """A built environment must not resolve or install packages at process start."""
    compose = _read("docker/docker-compose.yaml")
    serve = _read("scripts/serve.sh")

    assert "PYTHONPATH=. uv run --no-sync uvicorn app.gateway.app:app" in compose
    assert "PYTHONPATH=. uv run --no-sync uvicorn app.gateway.app:app" in serve


def test_local_frontend_ignores_public_docker_port() -> None:
    """Root PORT config is public Docker ingress, not the local Next.js port."""
    serve = _read("scripts/serve.sh")

    assert "env PORT=3000" in serve
    assert 'run_service "Frontend"' in serve
    assert "3000 300" in serve


def test_production_gateway_has_a_real_readiness_probe() -> None:
    """Compose readiness must exercise the Gateway HTTP endpoint."""
    compose = _read("docker/docker-compose.yaml")

    assert "healthcheck:" in compose
    assert "http://127.0.0.1:8001/health" in compose
    assert "gateway:\n        condition: service_healthy" in compose


def test_deploy_waits_for_gateway_readiness_before_success(tmp_path: Path) -> None:
    capture = tmp_path / "docker-args.txt"
    worktree, env = _deploy_fixture(
        tmp_path,
        docker_script=('#!/usr/bin/env sh\nprintf "%s\\n" "$@" > "$CAPTURE_DOCKER_ARGS"\nexit 0\n'),
    )
    env["CAPTURE_DOCKER_ARGS"] = str(capture)

    result = subprocess.run(
        ["bash", str(worktree / "scripts" / "deploy.sh"), "start"],
        cwd=worktree,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    args = capture.read_text(encoding="utf-8").splitlines()
    assert "--wait" in args
    assert "--wait-timeout" in args
    assert "DeerFlow is running!" in result.stdout


def test_deploy_failure_prints_gateway_diagnostics_and_never_claims_success(tmp_path: Path) -> None:
    capture = tmp_path / "docker-calls.txt"
    worktree, env = _deploy_fixture(
        tmp_path,
        docker_script=('#!/usr/bin/env sh\nprintf "%s\\n" "$*" >> "$CAPTURE_DOCKER_CALLS"\ncase " $* " in\n  *" up "*) exit 1 ;;\n  *) exit 0 ;;\nesac\n'),
    )
    env["CAPTURE_DOCKER_CALLS"] = str(capture)

    result = subprocess.run(
        ["bash", str(worktree / "scripts" / "deploy.sh"), "start"],
        cwd=worktree,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "DeerFlow is running!" not in result.stdout
    assert "DeerFlow services failed to become ready" in result.stderr
    assert "supports `docker compose up --wait`" in result.stderr
    calls = capture.read_text(encoding="utf-8")
    assert any(call.endswith(" ps") for call in calls.splitlines())
    assert " logs --no-color --tail 100 gateway" in calls
