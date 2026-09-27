"""deploy.sh must not shadow secrets the operator wrote to the repo-root .env.

Compose interpolates ``${BETTER_AUTH_SECRET}`` / ``${DEER_FLOW_INTERNAL_AUTH_TOKEN}``
from the shell environment first and ``--env-file`` second. deploy.sh only ever
looked at the shell before generating (or reloading a persisted) secret and
exporting it, so a value in ``.env`` -- the surface every deployment doc points
at -- was silently replaced by the auto-generated one.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from support.shell import find_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]

# Every test here shells out to bash; on Windows that must be Git Bash --
# the WSL launcher and Store alias stubs cannot run the repo scripts.
BASH = find_script_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="repo shell-script tests need Git Bash on Windows")

SECRETS = ("BETTER_AUTH_SECRET", "DEER_FLOW_INTERNAL_AUTH_TOKEN")
PERSISTED_FILE = {
    "BETTER_AUTH_SECRET": ".better-auth-secret",
    "DEER_FLOW_INTERNAL_AUTH_TOKEN": ".internal-auth-token",
}

# The fake docker records, per secret, whether the variable reached its
# environment at all and with which value.  "set:<value>" is what compose would
# interpolate from the shell; "" means compose falls through to --env-file.
_FAKE_DOCKER = """#!/usr/bin/env sh
{
  printf 'BETTER_AUTH_SECRET=%s\\n' "${BETTER_AUTH_SECRET+set:}${BETTER_AUTH_SECRET:-}"
  printf 'DEER_FLOW_INTERNAL_AUTH_TOKEN=%s\\n' "${DEER_FLOW_INTERNAL_AUTH_TOKEN+set:}${DEER_FLOW_INTERNAL_AUTH_TOKEN:-}"
} > "$CAPTURE_SECRETS"
for arg in "$@"; do printf "%s\\n" "$arg"; done > "$CAPTURE_DOCKER_ARGS"
exit 0
"""


def _worktree(tmp_path: Path) -> Path:
    worktree = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "scripts", worktree / "scripts")
    shutil.copytree(REPO_ROOT / "docker", worktree / "docker")
    (worktree / "backend").mkdir()
    (worktree / "config.yaml").write_text("database:\n  backend: sqlite\n", encoding="utf-8")
    (worktree / "extensions_config.json").write_text('{"mcpServers":{},"skills":{}}\n', encoding="utf-8")
    return worktree


def _run_deploy_build(tmp_path: Path, worktree: Path, *, shell_env: dict[str, str] | None = None):
    """Run ``deploy.sh build`` against a fake docker and return what it observed."""
    capture_secrets = tmp_path / "secrets.txt"
    capture_args = tmp_path / "docker_args.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    docker = bin_dir / "docker"
    docker.write_text(_FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)

    env = os.environ.copy()
    for key in (*SECRETS, "UV_EXTRAS"):
        env.pop(key, None)
    env["DEER_FLOW_HOME"] = str(tmp_path / "deer-flow-home")
    env["CAPTURE_SECRETS"] = str(capture_secrets)
    env["CAPTURE_DOCKER_ARGS"] = str(capture_args)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env.update(shell_env or {})

    result = subprocess.run(
        [BASH, str(worktree / "scripts" / "deploy.sh"), "build"],
        cwd=worktree,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    observed = dict(line.split("=", 1) for line in capture_secrets.read_text(encoding="utf-8").splitlines())
    args = capture_args.read_text(encoding="utf-8").splitlines()
    return result, observed, args, Path(env["DEER_FLOW_HOME"])


@pytest.mark.parametrize("key", SECRETS)
def test_deploy_leaves_dotenv_secret_for_compose_instead_of_generating_one(tmp_path, key):
    """A secret set in .env must reach compose through --env-file, unshadowed."""
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text(f"{key}=from-dotenv\n", encoding="utf-8")

    result, observed, args, home = _run_deploy_build(tmp_path, worktree)

    # Compose reads the dotenv itself; an exported copy would outrank it.
    assert "--env-file" in args
    assert observed[key] == "", f"{key} exported into the compose environment: {observed[key]!r}"
    assert not (home / PERSISTED_FILE[key]).exists(), "a persisted secret was generated despite the .env value"
    assert f"{key} loaded from" in result.stdout
    assert ".env" in result.stdout


@pytest.mark.parametrize("key", SECRETS)
def test_deploy_prefers_dotenv_secret_over_the_persisted_generated_one(tmp_path, key):
    """An operator-written .env value wins over the file an earlier run generated."""
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text(f"{key}=from-dotenv\n", encoding="utf-8")
    home = tmp_path / "deer-flow-home"
    home.mkdir()
    (home / PERSISTED_FILE[key]).write_text("from-persisted-file\n", encoding="utf-8")

    _, observed, _, _ = _run_deploy_build(tmp_path, worktree)

    assert observed[key] == "", f"the persisted secret shadowed the .env value: {observed[key]!r}"


@pytest.mark.parametrize("key", SECRETS)
def test_deploy_still_generates_and_persists_a_secret_when_dotenv_has_none(tmp_path, key):
    """Without an operator value the script keeps its generate-once contract."""
    worktree = _worktree(tmp_path)
    # A dotenv without the key, plus an empty assignment for the other secret,
    # must both count as "not provided".
    other = next(secret for secret in SECRETS if secret != key)
    (worktree / ".env").write_text(f"{other}=\nPORT=2026\n", encoding="utf-8")

    _, observed, _, home = _run_deploy_build(tmp_path, worktree)

    assert observed[key].startswith("set:")
    generated = observed[key].removeprefix("set:")
    assert re.fullmatch(r"[A-Za-z0-9_\-]{32,}", generated), generated
    persisted = home / PERSISTED_FILE[key]
    assert persisted.read_text(encoding="utf-8").strip() == generated
    assert (persisted.stat().st_mode & 0o777) == 0o600 or os.name == "nt"


@pytest.mark.parametrize("key", SECRETS)
def test_deploy_keeps_shell_export_ahead_of_dotenv(tmp_path, key):
    """An exported shell value keeps compose precedence: it wins over .env untouched."""
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text(f"{key}=from-dotenv\n", encoding="utf-8")

    _, observed, _, home = _run_deploy_build(tmp_path, worktree, shell_env={key: "from-shell"})

    assert observed[key] == "set:from-shell"
    assert not (home / PERSISTED_FILE[key]).exists()


@pytest.mark.parametrize("key", SECRETS)
def test_deploy_treats_an_empty_shell_export_as_missing_not_as_dotenv_provided(tmp_path, key):
    """Compose lets an exported-but-empty shell variable outrank .env.

    Leaving it alone would hand the stack an empty secret, so the script must
    still generate one (and export it) rather than trust the .env value it
    would never see.
    """
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text(f"{key}=from-dotenv\n", encoding="utf-8")

    _, observed, _, home = _run_deploy_build(tmp_path, worktree, shell_env={key: ""})

    assert observed[key].startswith("set:")
    assert observed[key] not in ("set:", "set:from-dotenv")
    assert (home / PERSISTED_FILE[key]).exists()
