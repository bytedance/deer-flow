"""Regression tests for docker sandbox mode detection logic."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from shutil import which

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "docker.sh"
BASH_CANDIDATES = [
    Path(r"C:\Program Files\Git\bin\bash.exe"),
    Path(which("bash")) if which("bash") else None,
]
BASH_EXECUTABLE = next(
    (str(path) for path in BASH_CANDIDATES if path is not None and path.exists() and "WindowsApps" not in str(path)),
    None,
)

if BASH_EXECUTABLE is None:
    pytestmark = pytest.mark.skip(reason="bash is required for docker.sh detection tests")


def _detect_mode_with_config(config_content: str) -> str:
    """Write config content into a temp project root and execute detect_sandbox_mode."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        (tmp_root / "config.yaml").write_text(config_content, encoding="utf-8")

        command = f"source '{SCRIPT_PATH}' && PROJECT_ROOT='{tmp_root}' && detect_sandbox_mode"

        output = subprocess.check_output(
            [BASH_EXECUTABLE, "-lc", command],
            text=True,
            encoding="utf-8",
        ).strip()

        return output


def test_detect_mode_defaults_to_local_when_config_missing():
    """No config file should default to local mode."""
    with tempfile.TemporaryDirectory() as tmpdir:
        command = f"source '{SCRIPT_PATH}' && PROJECT_ROOT='{tmpdir}' && detect_sandbox_mode"
        output = subprocess.check_output(
            [BASH_EXECUTABLE, "-lc", command],
            text=True,
            encoding="utf-8",
        ).strip()

    assert output == "local"


def test_detect_mode_local_provider():
    """Local sandbox provider should map to local mode."""
    config = """
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
""".strip()

    assert _detect_mode_with_config(config) == "local"


def test_detect_mode_aio_without_provisioner_url():
    """AIO sandbox without provisioner_url should map to aio mode."""
    config = """
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
""".strip()

    assert _detect_mode_with_config(config) == "aio"


def test_detect_mode_provisioner_with_url():
    """AIO sandbox with provisioner_url should map to provisioner mode."""
    config = """
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  provisioner_url: http://provisioner:8002
""".strip()

    assert _detect_mode_with_config(config) == "provisioner"


def test_detect_mode_ignores_commented_provisioner_url():
    """Commented provisioner_url should not activate provisioner mode."""
    config = """
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  # provisioner_url: http://provisioner:8002
""".strip()

    assert _detect_mode_with_config(config) == "aio"


def test_detect_mode_unknown_provider_falls_back_to_local():
    """Unknown sandbox provider should default to local mode."""
    config = """
sandbox:
  use: custom.module:UnknownProvider
""".strip()

    assert _detect_mode_with_config(config) == "local"


def _seed_compose_file(tmp_root: Path) -> None:
    """Give require_compose_file the file it validates."""
    (tmp_root / "docker-compose-dev.yaml").write_text("services: {}\n", encoding="utf-8")


def _seed_env_examples(tmp_root: Path) -> None:
    """Provide the templates ensure_env_files copies from."""
    (tmp_root / ".env.example").write_text("# test\n", encoding="utf-8")
    frontend = tmp_root / "frontend"
    frontend.mkdir(exist_ok=True)
    (frontend / ".env.example").write_text("# test\n", encoding="utf-8")


def _run_docker_sh(tmp_root: Path, body: str) -> None:
    """Run docker.sh against a temp checkout, stubbing the real Compose version probe.

    Keep SCRIPT_DIR at the real scripts/ directory so stop's cleanup-containers.sh
    path still resolves; only PROJECT_ROOT / DOCKER_DIR are redirected.
    """
    command = f"""
source '{SCRIPT_PATH}'
PROJECT_ROOT='{tmp_root}'
DOCKER_DIR='{tmp_root}'
require_compose_version() {{ :; }}
{body}
"""
    subprocess.check_call([BASH_EXECUTABLE, "-lc", command])


@pytest.mark.parametrize("docker_command", ["logs --gateway", "stop", "restart"])
def test_compose_commands_set_deer_flow_root_before_compose(docker_command):
    """Read-only compose commands should resolve mounts from the repository root."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        _seed_compose_file(tmp_root)
        _run_docker_sh(
            tmp_root,
            f"""
COMPOSE_CMD=capture_compose
capture_compose() {{ test "${{DEER_FLOW_ROOT:-}}" = "$PROJECT_ROOT"; }}
unset DEER_FLOW_ROOT
{docker_command}
""",
        )


@pytest.mark.parametrize("docker_command", ["logs --gateway", "stop", "restart"])
def test_read_only_commands_do_not_create_env_files(docker_command):
    """Only start may write configuration; logs/stop/restart must leave a checkout alone."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        _seed_compose_file(tmp_root)
        _seed_env_examples(tmp_root)

        _run_docker_sh(tmp_root, f"COMPOSE_CMD=true\n{docker_command}")

        assert not (tmp_root / ".env").exists(), f"{docker_command} created .env"
        assert not (tmp_root / "frontend" / ".env").exists(), f"{docker_command} created frontend/.env"


@pytest.mark.parametrize("docker_command", ["logs --gateway", "stop", "restart"])
def test_read_only_commands_run_without_env_examples(docker_command):
    """A missing .env.example must never block stopping or inspecting containers."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        _seed_compose_file(tmp_root)

        _run_docker_sh(tmp_root, f"COMPOSE_CMD=true\n{docker_command}")


def test_ensure_env_files_copies_from_examples():
    """start's env-file step should create .env files from their examples when missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        _seed_env_examples(tmp_root)

        command = f"""
source '{SCRIPT_PATH}'
PROJECT_ROOT='{tmp_root}'
ensure_env_files
"""
        subprocess.check_call([BASH_EXECUTABLE, "-lc", command])

        assert (tmp_root / ".env").is_file()
        assert (tmp_root / "frontend" / ".env").is_file()
        assert (tmp_root / ".env").read_text(encoding="utf-8") == "# test\n"
        assert (tmp_root / "frontend" / ".env").read_text(encoding="utf-8") == "# test\n"


def test_ensure_env_files_leaves_existing_env_untouched():
    """ensure_env_files must not overwrite an already-present .env."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        _seed_env_examples(tmp_root)
        (tmp_root / ".env").write_text("KEEP=me\n", encoding="utf-8")
        frontend = tmp_root / "frontend"
        (frontend / ".env").write_text("KEEP=frontend\n", encoding="utf-8")

        command = f"""
source '{SCRIPT_PATH}'
PROJECT_ROOT='{tmp_root}'
ensure_env_files
"""
        subprocess.check_call([BASH_EXECUTABLE, "-lc", command])

        assert (tmp_root / ".env").read_text(encoding="utf-8") == "KEEP=me\n"
        assert (frontend / ".env").read_text(encoding="utf-8") == "KEEP=frontend\n"


@pytest.mark.parametrize(
    ("reported_version", "expected_returncode"),
    [
        ("2.23.3", 1),
        ("2.5.0", 1),
        ("2.24.0", 0),
        ("v2.40.2-desktop.1", 0),
        ("3.0.1", 0),
        ("", 0),  # undetectable: warn, but do not block
    ],
)
def test_require_compose_version_enforces_minimum(reported_version, expected_returncode):
    """Old clients get our actionable message instead of a raw Compose parser error."""
    # Stub both binaries so an empty plugin probe cannot fall through to the
    # real hyphenated docker-compose installed on the developer machine.
    command = f"""
source '{SCRIPT_PATH}'
docker() {{ echo '{reported_version}'; }}
docker-compose() {{ echo '{reported_version}'; }}
require_compose_version
"""
    result = subprocess.run(
        [BASH_EXECUTABLE, "-lc", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == expected_returncode, result.stdout + result.stderr
    if expected_returncode != 0:
        assert "too old" in result.stdout
        assert "docs.docker.com/compose/install" in result.stdout


def test_require_compose_version_falls_back_to_hyphenated_binary():
    """Plugin missing + docker-compose 2.24: version check passes and stop uses that binary.

    Regression for the half-fallback where require_compose_version accepted
    docker-compose but COMPOSE_CMD stayed hardcoded to `docker compose`.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        _seed_compose_file(tmp_root)
        marker = tmp_root / "hyphenated_invoke.txt"

        command = f"""
source '{SCRIPT_PATH}'
PROJECT_ROOT='{tmp_root}'
DOCKER_DIR='{tmp_root}'
docker() {{
  if [ "$1" = compose ]; then
    echo "docker: unknown command" >&2
    return 1
  fi
  command docker "$@"
}}
docker-compose() {{
  if [ "$1" = version ]; then
    echo '2.24.0'
    return 0
  fi
  # Real wrapper ops (down/logs/...) must hit this binary, not `docker compose`.
  printf '%s\n' "$*" > '{marker}'
}}
unset DEER_FLOW_ROOT
stop
"""
        result = subprocess.run(
            [BASH_EXECUTABLE, "-lc", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert marker.is_file(), "stop never invoked docker-compose for the compose operation"
        assert "down" in marker.read_text(encoding="utf-8")


def test_require_compose_version_rejects_old_hyphenated_binary():
    """An old docker-compose binary must still fail the floor check."""
    command = f"""
source '{SCRIPT_PATH}'
docker() {{
  if [ "$1" = compose ]; then
    return 1
  fi
  command docker "$@"
}}
docker-compose() {{ echo '2.23.3'; }}
require_compose_version
"""
    result = subprocess.run(
        [BASH_EXECUTABLE, "-lc", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "too old" in result.stdout
