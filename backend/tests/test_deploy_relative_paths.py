"""Production host paths must resolve from the checkout for both Bash and Compose."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from support.shell import find_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]
BASH = find_script_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="repo shell-script tests need Git Bash on Windows")
PATH_KEYS = ("DEER_FLOW_HOME", "DEER_FLOW_CONFIG_PATH", "DEER_FLOW_EXTENSIONS_CONFIG_PATH")


def _run_deploy(tmp_path: Path, overrides: dict[str, str | None], command: str = "build", *, use_default_paths: bool = False):
    worktree = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "scripts", worktree / "scripts")
    shutil.copytree(REPO_ROOT / "docker", worktree / "docker")
    expected = (
        {
            "DEER_FLOW_HOME": worktree / "backend" / ".deer-flow",
            "DEER_FLOW_CONFIG_PATH": worktree / "config.yaml",
            "DEER_FLOW_EXTENSIONS_CONFIG_PATH": worktree / "extensions_config.json",
        }
        if use_default_paths
        else {
            "DEER_FLOW_HOME": worktree / "runtime home",
            "DEER_FLOW_CONFIG_PATH": worktree / "settings" / "config.yaml",
            "DEER_FLOW_EXTENSIONS_CONFIG_PATH": worktree / "settings" / "extensions_config.json",
        }
    )
    expected["DEER_FLOW_HOME"].mkdir(parents=True)
    expected["DEER_FLOW_CONFIG_PATH"].parent.mkdir(parents=True, exist_ok=True)
    expected["DEER_FLOW_CONFIG_PATH"].write_text("sandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\n", encoding="utf-8")
    expected["DEER_FLOW_EXTENSIONS_CONFIG_PATH"].write_text('{"mcpServers":{},"skills":{}}\n', encoding="utf-8")
    # Existing state must be read from the directory Compose will actually mount.
    (expected["DEER_FLOW_HOME"] / ".credentials_key").write_text("existing-test-key\n", encoding="utf-8")
    capture = tmp_path / "paths.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/usr/bin/env sh\n"
        'case " $* " in\n'
        '  *" config "*) printf \'      DEER_FLOW_PROBE_VALUE: ""\\n\' ;;\n'
        '  *) printf "%s\\n" "$DEER_FLOW_HOME" "$DEER_FLOW_CONFIG_PATH" "$DEER_FLOW_EXTENSIONS_CONFIG_PATH" "$DEER_FLOW_CREDENTIALS_KEY" > "$CAPTURE_PATHS" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env = os.environ.copy()
    for key in ("DEER_FLOW_CREDENTIALS_KEY", "DEER_FLOW_COMPOSE_ENV_FILE"):
        env.pop(key, None)
    env.update({key: path.as_posix() for key, path in expected.items()})
    env.update(
        PATH=f"{bin_dir}{os.pathsep}{env['PATH']}",
        CAPTURE_PATHS=str(capture),
        BETTER_AUTH_SECRET="test-better-auth",
        DEER_FLOW_INTERNAL_AUTH_TOKEN="test-internal-auth",
        UV_EXTRAS="redis",
    )
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    # The launcher may be called from anywhere; its relative paths belong to the checkout.
    caller = tmp_path / "outside"
    caller.mkdir()
    result = subprocess.run(
        [BASH, str(worktree / "scripts" / "deploy.sh"), command],
        cwd=caller,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    values = capture.read_text(encoding="utf-8").splitlines()
    return worktree, expected, dict(zip(PATH_KEYS, values[:3], strict=True)), values[3], result


@pytest.mark.parametrize("key", PATH_KEYS)
@pytest.mark.parametrize("with_dot", [False, True], ids=["bare-relative", "dot-relative"])
def test_deploy_exports_relative_host_paths_from_checkout(tmp_path, key, with_dot):
    relative = {"DEER_FLOW_HOME": "runtime home", "DEER_FLOW_CONFIG_PATH": "settings/config.yaml", "DEER_FLOW_EXTENSIONS_CONFIG_PATH": "settings/extensions_config.json"}[key]
    if with_dot:
        relative = f"./{relative}"
    _, expected, observed, credentials_key, _ = _run_deploy(tmp_path, {key: relative})
    assert Path(observed[key]).is_absolute(), observed
    assert Path(observed[key]).resolve() == expected[key].resolve()
    assert credentials_key == "existing-test-key"


def test_deploy_preserves_absolute_host_paths(tmp_path):
    _, expected, observed, credentials_key, _ = _run_deploy(tmp_path, {})
    assert {key: Path(value).resolve() for key, value in observed.items()} == {key: path.resolve() for key, path in expected.items()}
    assert credentials_key == "existing-test-key"


def test_deploy_down_resolves_relative_paths_without_requiring_files(tmp_path):
    _, _, observed, _, _ = _run_deploy(tmp_path, {"DEER_FLOW_HOME": "./absent home", "DEER_FLOW_CONFIG_PATH": "./missing.yaml", "DEER_FLOW_EXTENSIONS_CONFIG_PATH": "./missing.json"}, command="down")
    assert all(Path(value).is_absolute() for value in observed.values()), observed


def _assert_real_compose_mounts(tmp_path, worktree, expected, observed):
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose is not installed")
    docker_config = tmp_path / "empty-docker-config"
    docker_config.mkdir()
    probe = subprocess.run([docker, "--config", str(docker_config), "compose", "version"], capture_output=True, text=True, check=False)
    if probe.returncode:
        pytest.skip("Docker Compose is not available")
    env = {**os.environ, **observed, "BETTER_AUTH_SECRET": "test-better-auth", "DEER_FLOW_INTERNAL_AUTH_TOKEN": "test-internal-auth", "DEER_FLOW_REPO_ROOT": str(worktree)}
    rendered = subprocess.run(
        [docker, "--config", str(docker_config), "compose", "-p", "relative-path-regression", "-f", str(worktree / "docker" / "docker-compose.yaml"), "config", "--format", "json"],
        cwd=worktree,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    gateway = json.loads(rendered.stdout)["services"]["gateway"]
    mounts = {volume["target"]: Path(volume["source"]).resolve() for volume in gateway["volumes"] if volume["type"] == "bind"}
    assert mounts["/app/backend/.deer-flow"] == expected["DEER_FLOW_HOME"].resolve()
    assert mounts["/app/backend/config.yaml"] == expected["DEER_FLOW_CONFIG_PATH"].resolve()
    assert mounts["/app/backend/extensions_config.json"] == expected["DEER_FLOW_EXTENSIONS_CONFIG_PATH"].resolve()
    assert Path(gateway["environment"]["DEER_FLOW_HOST_BASE_DIR"]).resolve() == expected["DEER_FLOW_HOME"].resolve()


def test_real_compose_mounts_the_same_paths_the_launcher_uses(tmp_path):
    worktree, expected, observed, _, _ = _run_deploy(tmp_path, {"DEER_FLOW_HOME": "./runtime home", "DEER_FLOW_CONFIG_PATH": "./settings/config.yaml", "DEER_FLOW_EXTENSIONS_CONFIG_PATH": "./settings/extensions_config.json"})
    _assert_real_compose_mounts(tmp_path, worktree, expected, observed)


@pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
def test_deploy_defaults_mount_the_checkout_paths(tmp_path, value):
    worktree, expected, observed, credentials_key, _ = _run_deploy(tmp_path, {key: value for key in PATH_KEYS}, use_default_paths=True)
    assert all(Path(path).is_absolute() for path in observed.values()), observed
    assert {key: Path(path).resolve() for key, path in observed.items()} == {key: path.resolve() for key, path in expected.items()}
    assert credentials_key == "existing-test-key"
    _assert_real_compose_mounts(tmp_path, worktree, expected, observed)
