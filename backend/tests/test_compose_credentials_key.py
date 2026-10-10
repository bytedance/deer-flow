"""Both compose stacks pass ``DEER_FLOW_CREDENTIALS_KEY`` through to the Gateway.

``scripts/deploy.sh`` resolves the key (shell, ``.env``, the persisted
``$DEER_FLOW_HOME/.credentials_key``, or a freshly generated one) and Compose
interpolates it into the gateway service. ``:-`` keeps a stack started without
the deploy script quiet: an empty value makes the Gateway fall back to the same
``.credentials_key`` file under its runtime home, which is the host's
``DEER_FLOW_HOME`` bind mount.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from support.compose import DOCKER, requires_docker_compose
from support.shell import find_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATHS = {
    "prod": REPO_ROOT / "docker" / "docker-compose.yaml",
    "dev": REPO_ROOT / "docker" / "docker-compose-dev.yaml",
}
EXPECTED_ENTRY = "DEER_FLOW_CREDENTIALS_KEY=${DEER_FLOW_CREDENTIALS_KEY:-}"
BASH_EXECUTABLE = find_script_bash()
DOTENV_KEY = "u6Tp1Gk0bq8m6C2YkS9oWw7xH3fLr5eN1aZdQjVtXc4="
SHELL_KEY = "Zq3Lw8Rn2Tb6Yv1Kc5Hm9Pd4Sx7Ga0Je3Uf6Ni2Ro8M="


@pytest.mark.parametrize("variant", sorted(COMPOSE_PATHS))
def test_gateway_receives_the_credentials_key(variant: str) -> None:
    services = yaml.safe_load(COMPOSE_PATHS[variant].read_text(encoding="utf-8"))["services"]

    assert EXPECTED_ENTRY in services["gateway"]["environment"]
    assert "DEER_FLOW_HOME=/app/backend/.deer-flow" in services["gateway"]["environment"], "the fallback key file lives in the runtime home"


@pytest.mark.parametrize("variant", sorted(COMPOSE_PATHS))
def test_only_the_gateway_receives_the_credentials_key(variant: str) -> None:
    services = yaml.safe_load(COMPOSE_PATHS[variant].read_text(encoding="utf-8"))["services"]
    for name, service in services.items():
        if name == "gateway":
            continue
        environment = service.get("environment") or []
        entries = environment if isinstance(environment, list) else [f"{key}={value}" for key, value in environment.items()]
        assert not any(str(entry).startswith("DEER_FLOW_CREDENTIALS_KEY") for entry in entries), name


def _render_through_docker_start(tmp_path: Path, env_file: str, shell_value: str | None) -> dict[str, str]:
    """Render the dev gateway environment the way ``make docker-start`` interpolates it.

    ``scripts/docker.sh start`` runs Compose from ``docker/`` without
    ``--env-file``; a ``docker`` shell function swaps ``up ...`` for ``config``.
    """
    docker_dir = tmp_path / "docker"
    shutil.copytree(REPO_ROOT / "docker", docker_dir)
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / ".env").write_text("", encoding="utf-8")
    (tmp_path / ".env").write_text(env_file, encoding="utf-8")
    (tmp_path / "config.yaml").write_text("sandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\n", encoding="utf-8")
    (tmp_path / "extensions_config.json").write_text("{}", encoding="utf-8")
    rendered = tmp_path / "rendered.json"
    env = {key: value for key, value in os.environ.items() if not key.startswith(("DEER_FLOW_", "COMPOSE_", "AUTH_"))}
    if shell_value is not None:
        env["DEER_FLOW_CREDENTIALS_KEY"] = shell_value
    script = f"""
source '{REPO_ROOT / "scripts" / "docker.sh"}'
PROJECT_ROOT='{tmp_path}'
DOCKER_DIR='{docker_dir}'
require_compose_version() {{ :; }}
docker() {{
    local args=()
    for arg in "$@"; do
        [ "$arg" = up ] && break
        args+=("$arg")
    done
    command '{DOCKER}' "${{args[@]}}" config --format json > '{rendered}'
}}
start
"""
    subprocess.run([BASH_EXECUTABLE, "-c", script], env=env, capture_output=True, text=True, timeout=120, check=True)
    return json.loads(rendered.read_text(encoding="utf-8"))["services"]["gateway"]["environment"]


@requires_docker_compose
@pytest.mark.skipif(BASH_EXECUTABLE is None, reason="bash is required to run scripts/docker.sh")
@pytest.mark.parametrize(
    ("env_file", "shell_value", "expected"),
    [
        ("", None, ""),
        (f"DEER_FLOW_CREDENTIALS_KEY={DOTENV_KEY}\n", None, DOTENV_KEY),
        (f"DEER_FLOW_CREDENTIALS_KEY='{DOTENV_KEY}'\r\n", None, DOTENV_KEY),
        (f"DEER_FLOW_CREDENTIALS_KEY={DOTENV_KEY}\n", SHELL_KEY, SHELL_KEY),
    ],
    ids=["unset", "dotenv", "quoted-crlf", "shell-export-wins"],
)
def test_make_docker_start_keeps_the_dotenv_credentials_key(tmp_path, env_file: str, shell_value: str | None, expected: str):
    """The dev launcher must hand the checkout .env key to interpolation; an empty override would replace it."""
    assert _render_through_docker_start(tmp_path, env_file, shell_value)["DEER_FLOW_CREDENTIALS_KEY"] == expected
