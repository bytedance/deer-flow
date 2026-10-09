"""Production Compose dotenv selection is explicit and shared by all consumers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest
import test_deploy_dotenv_secrets as deploy_secret_tests
from test_deploy_dotenv_secrets import BASH, _run_deploy_build, _worktree
from test_deploy_home_writability import _run_deploy
from test_deploy_home_writability import deploy_fixture as deploy_fixture

pytestmark = pytest.mark.skipif(BASH is None, reason="repo shell-script tests need Git Bash on Windows")


@pytest.mark.parametrize("selector_kind", ["relative", "absolute", "spaces"])
def test_deploy_selects_one_env_file_for_build_and_secret_probe(tmp_path, selector_kind):
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text("UV_EXTRAS=redis\n", encoding="utf-8")
    selected = worktree / ("profiles/stage.env" if selector_kind != "spaces" else "profiles with spaces/stage env")
    selected.parent.mkdir()
    selected.write_text("UV_EXTRAS=discord\n", encoding="utf-8")
    selector = str(selected) if selector_kind == "absolute" else str(selected.relative_to(worktree))

    _, _, args, config_args, _, _ = _run_deploy_build(
        tmp_path,
        worktree,
        shell_env={"DEER_FLOW_COMPOSE_ENV_FILE": selector},
        compose_environment={"BETTER_AUTH_SECRET": "test-auth", "DEER_FLOW_INTERNAL_AUTH_TOKEN": "test-internal"},
    )

    assert "--env-file" in args
    env_arg = args[args.index("--env-file") + 1]
    assert config_args[config_args.index("--env-file") + 1] == env_arg
    probe = subprocess.run(
        [BASH, "-c", 'test -f "$1" && cmp -s "$1" "$2"', "--", env_arg, str(selected)],
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert probe.returncode == 0, "Compose and its secret probe must read the selected file"


@pytest.mark.parametrize("invalid_kind", ["missing", "directory"])
def test_deploy_rejects_invalid_explicit_env_file_before_docker(tmp_path, invalid_kind):
    worktree = _worktree(tmp_path)
    selected = worktree / "stage.env"
    if invalid_kind == "directory":
        selected.mkdir()

    result, _, args, config_args, _, _ = _run_deploy_build(
        tmp_path,
        worktree,
        shell_env={"DEER_FLOW_COMPOSE_ENV_FILE": str(selected)},
        compose_environment={"BETTER_AUTH_SECRET": "test-auth", "DEER_FLOW_INTERNAL_AUTH_TOKEN": "test-internal"},
        check=False,
    )

    assert result.returncode != 0
    assert "DEER_FLOW_COMPOSE_ENV_FILE" in result.stderr
    assert not args
    assert not config_args


def test_deploy_reads_uv_extras_from_selected_env_file(tmp_path):
    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text("UV_EXTRAS=redis\n", encoding="utf-8")
    selected = worktree / "stage.env"
    selected.write_text("UV_EXTRAS=discord\n", encoding="utf-8")
    capture = tmp_path / "selected-extras.txt"
    docker = tmp_path / "bin" / "docker"
    docker.parent.mkdir()
    docker.write_text(
        '#!/usr/bin/env sh\nprintf "%s" "${UV_EXTRAS:-}" > "$CAPTURE_EXTRAS"\nexit 0\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env = os.environ.copy()
    env.pop("UV_EXTRAS", None)
    env.update(
        PATH=f"{docker.parent}{os.pathsep}{env['PATH']}",
        DEER_FLOW_COMPOSE_ENV_FILE=str(selected),
        DEER_FLOW_HOME=str(tmp_path / "home"),
        BETTER_AUTH_SECRET="test-auth",
        DEER_FLOW_INTERNAL_AUTH_TOKEN="test-internal",
        CAPTURE_EXTRAS=str(capture),
    )

    result = subprocess.run(
        [BASH, str(worktree / "scripts/deploy.sh"), "build"],
        cwd=worktree,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert capture.read_text(encoding="utf-8") == "discord"


@pytest.mark.parametrize("use_selector", [False, True, ""], ids=["default", "selected", "empty"])
def test_compose_uses_selected_env_for_gateway_and_provisioner(tmp_path, use_selector):
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("real Docker Compose CLI required to render the production project")
    version = subprocess.run([docker, "compose", "version"], capture_output=True, check=False, timeout=15)
    if version.returncode:
        pytest.skip("Docker Compose plugin unavailable")

    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text("DEERFLOW_ENV_SELECTION_TEST=default\n", encoding="utf-8")
    selected = worktree / "stage.env"
    selected.write_text("DEERFLOW_ENV_SELECTION_TEST=stage\n", encoding="utf-8")
    env = os.environ.copy()
    env.pop("DEER_FLOW_COMPOSE_ENV_FILE", None)
    if use_selector == "":
        env["DEER_FLOW_COMPOSE_ENV_FILE"] = ""
    elif use_selector:
        env["DEER_FLOW_COMPOSE_ENV_FILE"] = str(selected)
    env.update(
        DEER_FLOW_HOME=str(tmp_path / "home"),
        DEER_FLOW_CONFIG_PATH=str(worktree / "config.yaml"),
        DEER_FLOW_EXTENSIONS_CONFIG_PATH=str(worktree / "extensions_config.json"),
        BETTER_AUTH_SECRET="test-auth",
        DEER_FLOW_INTERNAL_AUTH_TOKEN="test-internal",
    )
    result = subprocess.run(
        [docker, "compose", "--env-file", str(selected if use_selector else worktree / ".env"), "-f", str(worktree / "docker/docker-compose.yaml"), "config", "--format", "json"],
        cwd=worktree,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    for service in ("gateway", "provisioner"):
        assert config["services"][service]["environment"]["DEERFLOW_ENV_SELECTION_TEST"] == ("stage" if use_selector else "default")


def test_deploy_down_still_works_when_selected_env_file_was_removed(deploy_fixture):
    worktree, env, home, capture = deploy_fixture
    env["DEER_FLOW_COMPOSE_ENV_FILE"] = str(worktree / "profiles/missing.env")
    env.pop("BETTER_AUTH_SECRET")
    env.pop("DEER_FLOW_INTERNAL_AUTH_TOKEN")

    result = _run_deploy(deploy_fixture, "down")

    assert result.returncode == 0, result.stderr
    assert capture.read_text(encoding="utf-8").splitlines()[-1] == "down"
    assert not list(home.iterdir())


def test_deploy_env_file_reaches_containers_through_real_compose(tmp_path, monkeypatch):
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("real Docker Compose CLI required for the native launcher probe")
    version = subprocess.run([docker, "compose", "version"], capture_output=True, check=False, timeout=15)
    if version.returncode:
        pytest.skip("Docker Compose plugin unavailable")

    worktree = _worktree(tmp_path)
    (worktree / ".env").write_text("NOT_A_SECRET=default\n", encoding="utf-8")
    selected = worktree / "profiles with spaces" / "stage env"
    selected.parent.mkdir()
    selected.write_text("BETTER_AUTH_SECRET=test-auth\nDEER_FLOW_INTERNAL_AUTH_TOKEN=test-internal\nDEERFLOW_ENV_SELECTION_TEST=stage\n", encoding="utf-8")

    rendered = tmp_path / "rendered-project.json"
    stub = deploy_secret_tests._FAKE_DOCKER.replace("#!/usr/bin/env sh", "#!/usr/bin/env bash", 1)
    prefix, suffix = stub.rsplit("exit 0\n", 1)
    stub = (
        prefix
        + """args=()
for arg in "$@"; do
    [ "$arg" != "build" ] || break
    args+=("$arg")
done
"$REAL_DOCKER" "${args[@]}" config --format json > "$CAPTURE_RENDERED_PROJECT"
exit 0
"""
        + suffix
    )
    monkeypatch.setattr(deploy_secret_tests, "_FAKE_DOCKER", stub)

    _, observed, _, _, _, home = _run_deploy_build(
        tmp_path,
        worktree,
        shell_env={"DEER_FLOW_COMPOSE_ENV_FILE": str(selected), "CAPTURE_RENDERED_PROJECT": str(rendered)},
        real_docker=docker,
    )
    project = json.loads(rendered.read_text(encoding="utf-8"))
    for service in ("gateway", "provisioner"):
        assert project["services"][service]["environment"]["DEERFLOW_ENV_SELECTION_TEST"] == "stage"

    assert observed["BETTER_AUTH_SECRET"] == ""
    assert observed["DEER_FLOW_INTERNAL_AUTH_TOKEN"] == ""
    assert not list(home.iterdir()), "Selected dotenv secrets must not be replaced with generated secrets"
