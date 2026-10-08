"""Regression coverage for deploy.sh's DEER_FLOW_HOME permission preflight."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from support.shell import find_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]
BASH = find_script_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="repo shell-script tests need Git Bash on Windows")


@pytest.fixture
def deploy_fixture(tmp_path: Path):
    """Run the real deploy script with isolated state and a recording Docker stub."""
    worktree = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "scripts", worktree / "scripts")
    shutil.copytree(REPO_ROOT / "docker", worktree / "docker")
    (worktree / "backend").mkdir()
    config = worktree / "config.yaml"
    config.write_text("sandbox:\n  use: deerflow.sandbox:LocalSandboxProvider\n", encoding="utf-8")
    extensions = worktree / "extensions_config.json"
    extensions.write_text('{"mcpServers":{},"skills":{}}\n', encoding="utf-8")

    # A path containing spaces also checks quoting in the guard and recovery hint.
    home = tmp_path / "runtime home"
    home.mkdir()
    capture = tmp_path / "docker-args.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text('#!/usr/bin/env sh\nprintf "%s\\n" "$@" >> "$CAPTURE_DOCKER_ARGS"\n', encoding="utf-8")
    docker.chmod(0o755)

    env = os.environ.copy()
    env.update(
        PATH=f"{bin_dir}{os.pathsep}{env['PATH']}",
        DEER_FLOW_HOME=str(home),
        DEER_FLOW_CONFIG_PATH=str(config),
        DEER_FLOW_EXTENSIONS_CONFIG_PATH=str(extensions),
        CAPTURE_DOCKER_ARGS=str(capture),
        # Keep the preflight independent of secret generation and optional extras.
        BETTER_AUTH_SECRET="test-better-auth-secret",
        DEER_FLOW_INTERNAL_AUTH_TOKEN="test-internal-auth-token",
        UV_EXTRAS="redis",
    )
    return worktree, env, home, capture


@pytest.fixture
def unwritable_home(deploy_fixture):
    """Reproduce unwritability without chown, restoring permissions on every exit."""
    if os.name != "posix":
        pytest.skip("directory write permissions require a POSIX filesystem")
    if os.geteuid() == 0:
        pytest.skip("root can write directories despite removed write permissions")

    _, _, home, _ = deploy_fixture
    original_mode = home.stat().st_mode
    home.chmod(0o555)
    try:
        if os.access(home, os.W_OK):
            pytest.skip("filesystem does not enforce directory write permissions")
        yield home
    finally:
        home.chmod(original_mode)


def _run_deploy(deploy_fixture, command: str):
    worktree, env, _, _ = deploy_fixture
    return subprocess.run(
        [BASH, str(worktree / "scripts" / "deploy.sh"), *([command] if command else [])],
        cwd=worktree,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


@pytest.mark.parametrize("command", ["", "build", "start"], ids=["up", "build", "start"])
def test_deploy_rejects_unwritable_home_before_invoking_docker(deploy_fixture, unwritable_home, command):
    _, _, _, capture = deploy_fixture

    result = _run_deploy(deploy_fixture, command)

    assert result.returncode == 1
    assert f"{unwritable_home} is not writable by '" in result.stderr
    assert "make docker-start" in result.stderr
    assert f"sudo chown -R {os.geteuid()}:{os.getegid()} '{unwritable_home}'" in result.stderr
    assert not capture.exists(), "Docker must not run when the home preflight fails"


@pytest.mark.parametrize(
    ("command", "compose_command"),
    [("", "up"), ("build", "build"), ("start", "up"), ("down", "down")],
    ids=["up", "build", "start", "down"],
)
def test_deploy_allows_writable_home(deploy_fixture, command, compose_command):
    _, _, _, capture = deploy_fixture

    result = _run_deploy(deploy_fixture, command)

    assert result.returncode == 0, result.stderr
    assert "is not writable" not in result.stderr
    assert compose_command in capture.read_text(encoding="utf-8").splitlines()


def test_deploy_down_allows_unwritable_home(deploy_fixture, unwritable_home):
    _, _, _, capture = deploy_fixture

    result = _run_deploy(deploy_fixture, "down")

    assert result.returncode == 0, result.stderr
    assert "is not writable" not in result.stderr
    assert capture.read_text(encoding="utf-8").splitlines()[-1] == "down"
