"""deploy.sh must not shadow secrets the operator wrote to the repo-root .env.

Compose interpolates ``${BETTER_AUTH_SECRET}`` / ``${DEER_FLOW_INTERNAL_AUTH_TOKEN}``
from the shell environment first and ``--env-file`` second. deploy.sh only ever
looked at the shell before generating (or reloading a persisted) secret and
exporting it, so a value in ``.env`` -- the surface every deployment doc points
at -- was silently replaced by the auto-generated one.

Whether ``.env`` provides a value is Compose's call, not a ``KEY=VALUE`` grep:
Compose accepts ``KEY: VALUE`` lines and interpolates ``${VAR}`` inside values.
The script therefore asks ``docker compose config --environment`` and only
falls back to the plain reader when the client predates that flag.
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
GENERATED = re.compile(r"set:[A-Za-z0-9_\-]{32,}")

# The fake docker answers `compose ... config --environment` with a canned
# resolved environment (what real Compose would print for the .env under
# test), or with FAKE_COMPOSE_CONFIG_RC to imitate a client without the flag.
# Every other invocation stands in for `compose build` and records, per
# secret, whether the variable reached its environment and with which value:
# "set:<value>" is what Compose would take from the shell, "" means Compose
# falls through to --env-file.
_FAKE_DOCKER = """#!/usr/bin/env sh
case " $* " in
  *" config "*)
    for arg in "$@"; do printf "%s\\n" "$arg"; done > "$CAPTURE_CONFIG_ARGS"
    if [ -n "${REAL_DOCKER:-}" ]; then exec "$REAL_DOCKER" "$@"; fi
    [ "${FAKE_COMPOSE_CONFIG_RC:-0}" = 0 ] || exit "$FAKE_COMPOSE_CONFIG_RC"
    [ -z "${FAKE_COMPOSE_ENVIRONMENT:-}" ] || cat "$FAKE_COMPOSE_ENVIRONMENT"
    exit 0
    ;;
esac
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


def _run_deploy_build(
    tmp_path: Path,
    worktree: Path,
    *,
    compose_environment: dict[str, str] | None = None,
    compose_config_rc: int = 0,
    real_docker: str | None = None,
    shell_env: dict[str, str] | None = None,
):
    """Run ``deploy.sh build`` against the fake docker and return what it observed."""
    capture_secrets = tmp_path / "secrets.txt"
    capture_args = tmp_path / "docker_args.txt"
    capture_config_args = tmp_path / "config_args.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    docker = bin_dir / "docker"
    docker.write_text(_FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)

    env = os.environ.copy()
    for key in (*SECRETS, "UV_EXTRAS", "REAL_DOCKER", "FAKE_COMPOSE_ENVIRONMENT", "FAKE_COMPOSE_CONFIG_RC"):
        env.pop(key, None)
    env["DEER_FLOW_HOME"] = str(tmp_path / "deer-flow-home")
    env["CAPTURE_SECRETS"] = str(capture_secrets)
    env["CAPTURE_DOCKER_ARGS"] = str(capture_args)
    env["CAPTURE_CONFIG_ARGS"] = str(capture_config_args)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    if compose_environment is not None:
        canned = tmp_path / "compose_environment.txt"
        canned.write_text("".join(f"{k}={v}\n" for k, v in compose_environment.items()), encoding="utf-8")
        env["FAKE_COMPOSE_ENVIRONMENT"] = str(canned)
    if compose_config_rc:
        env["FAKE_COMPOSE_CONFIG_RC"] = str(compose_config_rc)
    if real_docker:
        env["REAL_DOCKER"] = real_docker
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
    config_args = capture_config_args.read_text(encoding="utf-8").splitlines() if capture_config_args.exists() else []
    return result, observed, args, config_args, Path(env["DEER_FLOW_HOME"])


def _other(key: str) -> str:
    return next(secret for secret in SECRETS if secret != key)


# ── The script asks Compose, and trusts its answer ──────────────────────────


def test_deploy_asks_compose_for_the_environment_it_will_interpolate(tmp_path):
    """The probe uses the same --env-file as the real compose command."""
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text("BETTER_AUTH_SECRET=from-dotenv\n", encoding="utf-8")

    _, _, args, config_args, _ = _run_deploy_build(tmp_path, worktree, compose_environment={"BETTER_AUTH_SECRET": "from-dotenv"})

    assert config_args[:1] == ["compose"]
    assert "config" in config_args and "--environment" in config_args
    assert "--env-file" in config_args
    assert config_args[config_args.index("--env-file") + 1] == args[args.index("--env-file") + 1]
    # The probe resolves the default .env from the same project directory as
    # the real command (the compose file's directory), not from the cwd.
    assert "--project-directory" in config_args
    probe_dir = config_args[config_args.index("--project-directory") + 1]
    assert Path(probe_dir).resolve() == Path(args[args.index("-f") + 1]).resolve().parent


@pytest.mark.parametrize("key", SECRETS)
@pytest.mark.parametrize(
    "dotenv_line",
    ["{key}=from-dotenv", "{key}: from-dotenv", '{key}="from-${{OTHER}}"'],
    ids=["equals", "colon", "quoted-interpolated"],
)
def test_deploy_leaves_a_compose_resolved_secret_for_compose_instead_of_generating_one(tmp_path, key, dotenv_line):
    """Whatever the dotenv spelling, a value Compose resolves is left to Compose."""
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text("OTHER=dotenv\n" + dotenv_line.format(key=key) + "\n", encoding="utf-8")

    result, observed, args, _, home = _run_deploy_build(tmp_path, worktree, compose_environment={key: "from-dotenv"})

    # Compose reads the dotenv itself; an exported copy would outrank it.
    assert "--env-file" in args
    assert observed[key] == "", f"{key} exported into the compose environment: {observed[key]!r}"
    assert not (home / PERSISTED_FILE[key]).exists(), "a persisted secret was generated despite the .env value"
    assert f"{key} loaded from" in result.stdout
    assert ".env" in result.stdout


@pytest.mark.parametrize("key", SECRETS)
def test_deploy_generates_when_compose_resolves_the_dotenv_value_to_empty(tmp_path, key):
    """``KEY=${UNSET}`` looks set to a grep but is empty to Compose: generate."""
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text(f"{key}=${{UNSET_DEPLOY_SECRET}}\n", encoding="utf-8")

    _, observed, _, _, home = _run_deploy_build(tmp_path, worktree, compose_environment={key: "", _other(key): "x"})

    assert GENERATED.fullmatch(observed[key]), observed[key]
    assert (home / PERSISTED_FILE[key]).exists()


@pytest.mark.parametrize("key", SECRETS)
def test_deploy_prefers_dotenv_secret_over_the_persisted_generated_one(tmp_path, key):
    """An operator-written .env value wins over the file an earlier run generated."""
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text(f"{key}=from-dotenv\n", encoding="utf-8")
    home = tmp_path / "deer-flow-home"
    home.mkdir()
    (home / PERSISTED_FILE[key]).write_text("from-persisted-file\n", encoding="utf-8")

    _, observed, _, _, _ = _run_deploy_build(tmp_path, worktree, compose_environment={key: "from-dotenv"})

    assert observed[key] == "", f"the persisted secret shadowed the .env value: {observed[key]!r}"


@pytest.mark.parametrize("key", SECRETS)
def test_deploy_still_generates_and_persists_a_secret_when_dotenv_has_none(tmp_path, key):
    """Without an operator value the script keeps its generate-once contract."""
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text(f"{_other(key)}=x\nPORT=2026\n", encoding="utf-8")

    _, observed, _, _, home = _run_deploy_build(tmp_path, worktree, compose_environment={_other(key): "x", "PORT": "2026"})

    assert GENERATED.fullmatch(observed[key]), observed[key]
    generated = observed[key].removeprefix("set:")
    persisted = home / PERSISTED_FILE[key]
    assert persisted.read_text(encoding="utf-8").strip() == generated
    assert (persisted.stat().st_mode & 0o777) == 0o600 or os.name == "nt"


@pytest.mark.parametrize("key", SECRETS)
def test_deploy_keeps_shell_export_ahead_of_dotenv(tmp_path, key):
    """An exported shell value keeps compose precedence: it wins over .env untouched."""
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text(f"{key}=from-dotenv\n", encoding="utf-8")

    _, observed, _, _, home = _run_deploy_build(tmp_path, worktree, compose_environment={key: "from-shell"}, shell_env={key: "from-shell"})

    assert observed[key] == "set:from-shell"
    assert not (home / PERSISTED_FILE[key]).exists()


@pytest.mark.parametrize("key", SECRETS)
def test_deploy_treats_an_empty_shell_export_as_missing_not_as_dotenv_provided(tmp_path, key):
    """Compose lets an exported-but-empty shell variable outrank .env.

    Compose reports that as ``KEY=``; leaving it alone would hand the stack an
    empty secret, so the script must still generate one (and export it).
    """
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text(f"{key}=from-dotenv\n", encoding="utf-8")

    _, observed, _, _, home = _run_deploy_build(tmp_path, worktree, compose_environment={key: ""}, shell_env={key: ""})

    assert GENERATED.fullmatch(observed[key]), observed[key]
    assert (home / PERSISTED_FILE[key]).exists()


# ── Compose clients without `config --environment` (< 2.28) ─────────────────


@pytest.mark.parametrize("key", SECRETS)
def test_deploy_falls_back_to_the_plain_dotenv_reader_when_compose_cannot_report_its_environment(tmp_path, key):
    """An older client still gets the KEY=VALUE reader rather than shadowing .env."""
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text(f"{key}=from-dotenv\n", encoding="utf-8")

    _, observed, _, config_args, home = _run_deploy_build(tmp_path, worktree, compose_config_rc=125)

    assert config_args, "the script must have tried Compose first"
    assert observed[key] == "", f"{key} exported into the compose environment: {observed[key]!r}"
    assert not (home / PERSISTED_FILE[key]).exists()


def test_deploy_fallback_reader_generates_when_dotenv_lacks_the_key(tmp_path):
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text("PORT=2026\n", encoding="utf-8")

    _, observed, _, _, _ = _run_deploy_build(tmp_path, worktree, compose_config_rc=125)

    for key in SECRETS:
        assert GENERATED.fullmatch(observed[key]), observed[key]


# ── Against the real Compose client, when one is installed ──────────────────


def _real_compose_with_environment_flag() -> str | None:
    docker = shutil.which("docker")
    if docker is None:
        return None
    try:
        probe = subprocess.run(
            [docker, "compose", "-f", "-", "config", "--environment"],
            input="services: {}\n",
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return docker if probe.returncode == 0 else None


REAL_DOCKER = _real_compose_with_environment_flag()
needs_real_compose = pytest.mark.skipif(REAL_DOCKER is None, reason="needs a docker compose client with `config --environment` (Compose >= 2.28)")


@needs_real_compose
@pytest.mark.parametrize("key", SECRETS)
@pytest.mark.parametrize(
    ("dotenv_line", "expected"),
    [
        ("{key}=from-dotenv", "from-dotenv"),
        ("{key}: from-colon", "from-colon"),
        ('{key}="from-${{OTHER}}"', "from-dotenv"),
        ("{key}=${{UNSET_DEPLOY_SECRET:-defaulted}}", "defaulted"),
    ],
    ids=["equals", "colon", "quoted-interpolated", "default-expansion"],
)
def test_real_compose_dotenv_forms_are_left_for_compose(tmp_path, key, dotenv_line, expected):
    """Every spelling Compose accepts counts as provided, and Compose sees the operator's value."""
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text("OTHER=dotenv\n" + dotenv_line.format(key=key) + "\n", encoding="utf-8")

    _, observed, _, _, home = _run_deploy_build(tmp_path, worktree, real_docker=REAL_DOCKER)

    assert observed[key] == "", f"{key} exported into the compose environment: {observed[key]!r}"
    assert not (home / PERSISTED_FILE[key]).exists()
    resolved = subprocess.run(
        [REAL_DOCKER, "compose", "--env-file", str(worktree / ".env"), "-f", "-", "config", "--environment"],
        input="services: {}\n",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert f"{key}={expected}" in resolved


@needs_real_compose
@pytest.mark.parametrize("key", SECRETS)
def test_real_compose_unset_interpolation_in_dotenv_still_gets_a_generated_secret(tmp_path, key):
    """``KEY=${UNSET}`` is empty to Compose, so the script must generate."""
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text(f"{key}=${{UNSET_DEPLOY_SECRET}}\n", encoding="utf-8")

    _, observed, _, _, home = _run_deploy_build(tmp_path, worktree, real_docker=REAL_DOCKER)

    assert GENERATED.fullmatch(observed[key]), observed[key]
    assert (home / PERSISTED_FILE[key]).exists()


@needs_real_compose
@pytest.mark.parametrize("key", SECRETS)
def test_real_compose_empty_shell_export_still_gets_a_generated_secret(tmp_path, key):
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text(f"{key}=from-dotenv\n", encoding="utf-8")

    _, observed, _, _, _ = _run_deploy_build(tmp_path, worktree, real_docker=REAL_DOCKER, shell_env={key: ""})

    assert GENERATED.fullmatch(observed[key]), observed[key]
