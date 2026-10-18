"""Exercise startup config admission before real optional dependency detection."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from support.shell import require_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]

# Keep the complete launcher and detector, replacing process/service operations.
# Stop at dependency synchronization, before any service can be launched.
_PRELUDE = """
git() { return 1; }
lsof() { return 1; }
pgrep() { return 1; }
nginx() { return 0; }
sleep() { return 0; }
python3() { "$TEST_PYTHON" "$@"; }
env() {
    if [ "$1" = python3 ]; then shift; python3 "$@"; else command env "$@"; fi
}
uv() { printf '%s\\n' "$@" > "$TEST_UV_ARGS"; return 73; }
source "$1" "$2"
"""


@pytest.mark.parametrize("mode", ["--dev", "--prod"])
@pytest.mark.parametrize("config_source", ["project-env", "project-dotenv", "explicit", "checkout", "legacy", "missing", "project-directory"])
def test_serve_config_presence_reaches_dependency_sync(tmp_path: Path, mode: str, config_source: str) -> None:
    bash = require_script_bash()
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    (checkout / "backend").mkdir()
    for name in ("serve.sh", "detect_uv_extras.py"):
        shutil.copy2(REPO_ROOT / "scripts" / name, scripts / name)
    (scripts / "nginx-local-conf.sh").write_text("printf 'test-nginx.conf\\n'\n", encoding="utf-8")
    (scripts / "cleanup-containers.sh").write_text("exit 0\n", encoding="utf-8")
    (scripts / "config-upgrade.sh").write_text('printf upgraded > "$TEST_UPGRADE_MARKER"\n', encoding="utf-8")

    env = os.environ.copy()
    for key in (
        "DEER_FLOW_CONFIG_PATH",
        "DEER_FLOW_PROJECT_ROOT",
        "DEER_FLOW_HOME",
        "DEER_FLOW_ENV_FILE",
        "DEER_FLOW_STREAM_BRIDGE_REDIS_URL",
        "DEER_FLOW_SANDBOX_OWNERSHIP_REDIS_URL",
        "UV_EXTRAS",
        "BASH_ENV",
        "ENV",
    ):
        env.pop(key, None)
    project = tmp_path / "external project"
    project.mkdir()
    env["DEER_FLOW_PROJECT_ROOT"] = project.as_posix()
    expected_extras = []
    if config_source in {"project-env", "project-dotenv"}:
        (project / "config.yaml").write_text("models:\n  - use: langchain_ollama:ChatOllama\n", encoding="utf-8")
        expected_extras = ["--extra", "ollama"]
        if config_source == "project-dotenv":
            env.pop("DEER_FLOW_PROJECT_ROOT")
            (checkout / ".env").write_text(f"DEER_FLOW_PROJECT_ROOT={shlex.quote(project.as_posix())}\n", encoding="utf-8")
    elif config_source == "project-directory":
        (project / "config.yaml").mkdir()
    elif config_source != "missing":
        config = {"explicit": tmp_path / "explicit.yaml", "checkout": checkout / "config.yaml", "legacy": checkout / "backend" / "config.yaml"}[config_source]
        config.write_text("database:\n  backend: sqlite\n", encoding="utf-8")
        if config_source == "explicit":
            env["DEER_FLOW_CONFIG_PATH"] = config.as_posix()

    marker = tmp_path / "upgrade.txt"
    uv_args = tmp_path / "uv-args.txt"
    env.update(TEST_PYTHON=Path(sys.executable).as_posix(), TEST_UPGRADE_MARKER=marker.as_posix(), TEST_UV_ARGS=uv_args.as_posix())
    result = subprocess.run(
        [bash, "-c", _PRELUDE, "startup-config-test", (scripts / "serve.sh").as_posix(), mode],
        cwd=checkout,
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    if config_source in {"missing", "project-directory"}:
        assert "No DeerFlow config file found" in result.stdout
        assert not marker.exists()
        assert not uv_args.exists()
    else:
        assert "No DeerFlow config file found" not in result.stdout, result.stdout + result.stderr
        assert marker.read_text(encoding="utf-8") == "upgraded"
        assert uv_args.read_text(encoding="utf-8").splitlines() == ["sync", "--locked", "--quiet", "--all-packages", *expected_extras]
        assert "Backend dependency install failed" in result.stdout
