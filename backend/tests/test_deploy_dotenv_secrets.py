"""deploy.sh must not shadow secrets the operator wrote to the repo-root .env.

Compose interpolates ``${BETTER_AUTH_SECRET}`` / ``${DEER_FLOW_INTERNAL_AUTH_TOKEN}``
from the shell environment first and ``--env-file`` second. deploy.sh only ever
looked at the shell before generating (or reloading a persisted) secret and
exporting it, so a value in ``.env`` -- the surface every deployment doc points
at -- was silently replaced by the auto-generated one.

Whether ``.env`` provides a value is Compose's call, not a ``KEY=VALUE`` grep:
Compose accepts ``KEY: VALUE`` lines and interpolates ``${VAR}`` inside values.
The script therefore renders a stub project whose one environment entry is
``${KEY}`` through ``docker compose config`` and reads the value back -- a
probe every Compose v2 client can answer.
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

SECRETS = ("BETTER_AUTH_SECRET", "DEER_FLOW_INTERNAL_AUTH_TOKEN", "DEER_FLOW_CREDENTIALS_KEY")
PERSISTED_FILE = {
    "BETTER_AUTH_SECRET": ".better-auth-secret",
    "DEER_FLOW_INTERNAL_AUTH_TOKEN": ".internal-auth-token",
    # Same name the Gateway itself generates under its runtime home, which is
    # this directory's bind mount: one key whichever side created it first.
    "DEER_FLOW_CREDENTIALS_KEY": ".credentials_key",
}
# A Fernet key ends in one "=" of base64 padding.
GENERATED = re.compile(r"set:[A-Za-z0-9_\-]{32,}=?")

# The fake docker answers `compose ... config` the way Compose renders the
# script's stub project: it reads the `${KEY}` reference off stdin, looks the
# key up in a canned resolved environment (what real Compose would compute for
# the .env under test) and prints the environment entry, `""` when the key is
# empty or missing -- or fails with FAKE_COMPOSE_CONFIG_RC. Every other
# invocation stands in for `compose build` and records, per secret, whether
# the variable reached its environment and with which value: "set:<value>" is
# what Compose would take from the shell, "" means Compose falls through to
# --env-file.
_FAKE_DOCKER = """#!/usr/bin/env sh
case " $* " in
  *" config "*)
    for arg in "$@"; do printf "%s\\n" "$arg"; done > "$CAPTURE_CONFIG_ARGS"
    cat > "$CAPTURE_CONFIG_STDIN"
    if [ -n "${REAL_DOCKER:-}" ]; then exec "$REAL_DOCKER" "$@" < "$CAPTURE_CONFIG_STDIN"; fi
    if [ "${FAKE_COMPOSE_CONFIG_RC:-0}" != 0 ]; then echo "fake compose: cannot load project" >&2; exit "$FAKE_COMPOSE_CONFIG_RC"; fi
    key="$(sed -n 's/.*\\${\\([A-Za-z_][A-Za-z0-9_]*\\)}.*/\\1/p' "$CAPTURE_CONFIG_STDIN" | head -n 1)"
    value=""
    [ -z "${FAKE_COMPOSE_ENVIRONMENT:-}" ] || value="$(sed -n "s/^${key}=//p" "$FAKE_COMPOSE_ENVIRONMENT" | head -n 1)"
    [ -n "$value" ] || value='""'
    printf 'name: probe\\nservices:\\n  probe:\\n    environment:\\n      DEER_FLOW_PROBE_VALUE: %s\\n    image: scratch\\n' "$value"
    exit 0
    ;;
esac
{
  printf 'BETTER_AUTH_SECRET=%s\\n' "${BETTER_AUTH_SECRET+set:}${BETTER_AUTH_SECRET:-}"
  printf 'DEER_FLOW_INTERNAL_AUTH_TOKEN=%s\\n' "${DEER_FLOW_INTERNAL_AUTH_TOKEN+set:}${DEER_FLOW_INTERNAL_AUTH_TOKEN:-}"
  printf 'DEER_FLOW_CREDENTIALS_KEY=%s\\n' "${DEER_FLOW_CREDENTIALS_KEY+set:}${DEER_FLOW_CREDENTIALS_KEY:-}"
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
    check: bool = True,
):
    """Run ``deploy.sh build`` against the fake docker and return what it observed."""
    capture_secrets = tmp_path / "secrets.txt"
    capture_args = tmp_path / "docker_args.txt"
    capture_config_args = tmp_path / "config_args.txt"
    capture_config_stdin = tmp_path / "config_stdin.yaml"
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
    env["CAPTURE_CONFIG_STDIN"] = str(capture_config_stdin)
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
        check=check,
        text=True,
        capture_output=True,
    )
    observed = {}
    if capture_secrets.exists():
        observed = dict(line.split("=", 1) for line in capture_secrets.read_text(encoding="utf-8").splitlines())
    args = capture_args.read_text(encoding="utf-8").splitlines() if capture_args.exists() else []
    config_args = capture_config_args.read_text(encoding="utf-8").splitlines() if capture_config_args.exists() else []
    config_stdin = capture_config_stdin.read_text(encoding="utf-8") if capture_config_stdin.exists() else ""
    return result, observed, args, config_args, config_stdin, Path(env["DEER_FLOW_HOME"])


def _other(key: str) -> str:
    return next(secret for secret in SECRETS if secret != key)


# ── The script asks Compose, and trusts its answer ──────────────────────────


def test_deploy_asks_compose_to_interpolate_the_secret_like_the_real_project(tmp_path):
    """The probe renders ``${KEY}`` with the same --env-file and project directory as the real command."""
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text("BETTER_AUTH_SECRET=from-dotenv\n", encoding="utf-8")

    _, _, args, config_args, config_stdin, _ = _run_deploy_build(tmp_path, worktree, compose_environment={"BETTER_AUTH_SECRET": "from-dotenv", "DEER_FLOW_INTERNAL_AUTH_TOKEN": "x"})

    assert config_args[:1] == ["compose"]
    assert "config" in config_args
    assert "--env-file" in config_args
    assert config_args[config_args.index("--env-file") + 1] == args[args.index("--env-file") + 1]
    # The probe resolves the default .env from the same project directory as
    # the real command (the compose file's directory), not from the cwd.
    assert "--project-directory" in config_args
    probe_dir = config_args[config_args.index("--project-directory") + 1]
    assert Path(probe_dir).resolve() == Path(args[args.index("-f") + 1]).resolve().parent
    # The stub project on stdin is what gets interpolated: it must reference
    # the secret and nothing from the real compose file.
    assert config_args[config_args.index("-f") + 1] == "-"
    # Each probe replaces the captured stub; the last secret resolved is the last one probed.
    assert f"${{{SECRETS[-1]}}}" in config_stdin
    assert "docker-compose.yaml" not in config_stdin


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

    result, observed, args, _, _, home = _run_deploy_build(tmp_path, worktree, compose_environment={key: "from-dotenv"})

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

    _, observed, _, _, _, home = _run_deploy_build(tmp_path, worktree, compose_environment={key: "", _other(key): "x"})

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

    _, observed, _, _, _, _ = _run_deploy_build(tmp_path, worktree, compose_environment={key: "from-dotenv"})

    assert observed[key] == "", f"the persisted secret shadowed the .env value: {observed[key]!r}"


@pytest.mark.parametrize("key", SECRETS)
def test_deploy_still_generates_and_persists_a_secret_when_dotenv_has_none(tmp_path, key):
    """Without an operator value the script keeps its generate-once contract."""
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text(f"{_other(key)}=x\nPORT=2026\n", encoding="utf-8")

    _, observed, _, _, _, home = _run_deploy_build(tmp_path, worktree, compose_environment={_other(key): "x", "PORT": "2026"})

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

    _, observed, _, _, _, home = _run_deploy_build(tmp_path, worktree, compose_environment={key: "from-shell"}, shell_env={key: "from-shell"})

    assert observed[key] == "set:from-shell"
    assert not (home / PERSISTED_FILE[key]).exists()


@pytest.mark.parametrize("key", SECRETS)
def test_deploy_treats_an_empty_shell_export_as_missing_not_as_dotenv_provided(tmp_path, key):
    """Compose lets an exported-but-empty shell variable outrank .env.

    Compose renders that as ``""``; leaving it alone would hand the stack an
    empty secret, so the script must still generate one (and export it).
    """
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text(f"{key}=from-dotenv\n", encoding="utf-8")

    _, observed, _, _, _, home = _run_deploy_build(tmp_path, worktree, compose_environment={key: ""}, shell_env={key: ""})

    assert GENERATED.fullmatch(observed[key]), observed[key]
    assert (home / PERSISTED_FILE[key]).exists()


def test_deploy_stops_when_compose_cannot_interpolate_instead_of_guessing(tmp_path):
    """A failing probe must not silently fall through to a generated, shadowing secret."""
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text("BETTER_AUTH_SECRET=from-dotenv\n", encoding="utf-8")

    result, observed, args, config_args, _, home = _run_deploy_build(tmp_path, worktree, compose_config_rc=15, check=False)

    assert config_args, "the script must have asked Compose"
    assert result.returncode != 0
    assert "could not resolve BETTER_AUTH_SECRET" in result.stderr
    assert "fake compose: cannot load project" in result.stderr
    assert not args, "no build was attempted"
    assert not observed
    assert not (home / PERSISTED_FILE["BETTER_AUTH_SECRET"]).exists()


# ── Against real Compose clients, when installed ────────────────────────────


def _compose_clients() -> list[tuple[str, str]]:
    """The `docker` CLI plus any standalone binaries named in DEER_FLOW_TEST_COMPOSE_BINARIES."""
    clients: list[tuple[str, str]] = []
    docker = shutil.which("docker")
    if docker and _renders_stub_project([docker, "compose"]):
        clients.append(("docker", docker))
    for binary in filter(None, os.environ.get("DEER_FLOW_TEST_COMPOSE_BINARIES", "").split(os.pathsep)):
        if _renders_stub_project([binary]):
            clients.append((Path(binary).name, binary))
    return clients


def _renders_stub_project(command: list[str]) -> bool:
    try:
        probe = subprocess.run(
            [*command, "-f", "-", "config"],
            input="services:\n  probe:\n    image: scratch\n",
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


COMPOSE_CLIENTS = _compose_clients()
real_compose = pytest.mark.parametrize(
    "client",
    [pytest.param(path, id=name) for name, path in COMPOSE_CLIENTS] or [pytest.param(None, id="none", marks=pytest.mark.skip(reason="no docker compose client installed"))],
)


@pytest.fixture
def real_docker(client: str, tmp_path: Path) -> str:
    """A `docker`-shaped entry point for the client: the CLI itself, or a shim that drops the `compose` word for a standalone binary."""
    # The Docker CLI is docker.exe on Windows: compare the stem so the CLI is
    # recognized there too. Feeding it through the standalone wrapper would
    # strip the `compose` subcommand, and the root CLI then rejects the
    # script's --env-file probe with "unknown flag: --env-file".
    if Path(client).stem.lower() == "docker":
        return client
    shim = tmp_path / "compose-shim" / "docker"
    shim.parent.mkdir()
    shim.write_text(f'#!/usr/bin/env sh\n[ "$1" = compose ] && shift\nexec "{client}" "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    return str(shim)


def _resolved_by(real_docker: str, dotenv: Path, key: str) -> str:
    rendered = subprocess.run(
        [real_docker, "compose", "--env-file", str(dotenv), "-f", "-", "config"],
        input=f"services:\n  probe:\n    image: scratch\n    environment:\n      DEER_FLOW_PROBE_VALUE: ${{{key}}}\n",
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return re.search(r"^\s*DEER_FLOW_PROBE_VALUE: (.*)$", rendered, re.M).group(1)


@real_compose
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
def test_real_compose_dotenv_forms_are_left_for_compose(tmp_path, real_docker, key, dotenv_line, expected):
    """Every spelling Compose accepts counts as provided, and Compose sees the operator's value."""
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text("OTHER=dotenv\n" + dotenv_line.format(key=key) + "\n", encoding="utf-8")

    _, observed, _, _, _, home = _run_deploy_build(tmp_path, worktree, real_docker=real_docker)

    assert observed[key] == "", f"{key} exported into the compose environment: {observed[key]!r}"
    assert not (home / PERSISTED_FILE[key]).exists()
    assert _resolved_by(real_docker, worktree / ".env", key) == expected


@real_compose
@pytest.mark.parametrize("key", SECRETS)
def test_real_compose_unset_interpolation_in_dotenv_still_gets_a_generated_secret(tmp_path, real_docker, key):
    """``KEY=${UNSET}`` is empty to Compose, so the script must generate."""
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text(f"{key}=${{UNSET_DEPLOY_SECRET}}\n", encoding="utf-8")

    _, observed, _, _, _, home = _run_deploy_build(tmp_path, worktree, real_docker=real_docker)

    assert GENERATED.fullmatch(observed[key]), observed[key]
    assert (home / PERSISTED_FILE[key]).exists()


@real_compose
@pytest.mark.parametrize("key", SECRETS)
def test_real_compose_empty_shell_export_still_gets_a_generated_secret(tmp_path, real_docker, key):
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text(f"{key}=from-dotenv\n", encoding="utf-8")

    _, observed, _, _, _, _ = _run_deploy_build(tmp_path, worktree, real_docker=real_docker, shell_env={key: ""})

    assert GENERATED.fullmatch(observed[key]), observed[key]


# ── DEER_FLOW_CREDENTIALS_KEY specifics ─────────────────────────────────────


def test_deploy_generates_a_valid_fernet_credentials_key(tmp_path):
    """The Gateway refuses a malformed key, so the generated one must parse as Fernet."""
    from cryptography.fernet import Fernet

    from deerflow.config.credentials_key import parse_credentials_keys

    worktree = _worktree(tmp_path)

    _, observed, _, _, _, home = _run_deploy_build(tmp_path, worktree, compose_environment={})

    key = observed["DEER_FLOW_CREDENTIALS_KEY"].removeprefix("set:")
    Fernet(key)
    assert parse_credentials_keys(key) == [key]
    assert (home / ".credentials_key").read_text(encoding="utf-8").strip() == key


def test_deploy_reuses_a_key_file_the_gateway_already_generated(tmp_path):
    """A stack first started without deploy.sh already has the Gateway's own key file: keep it."""
    worktree = _worktree(tmp_path)
    home = tmp_path / "deer-flow-home"
    home.mkdir()
    (home / ".credentials_key").write_text("gateway-generated-key", encoding="utf-8")

    result, observed, _, _, _, _ = _run_deploy_build(tmp_path, worktree, compose_environment={})

    assert observed["DEER_FLOW_CREDENTIALS_KEY"] == "set:gateway-generated-key"
    assert (home / ".credentials_key").read_text(encoding="utf-8") == "gateway-generated-key"
    assert "DEER_FLOW_CREDENTIALS_KEY loaded from" in result.stdout
