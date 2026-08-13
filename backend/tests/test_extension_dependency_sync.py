"""Contracts for installing declared Python extensions in every startup mode."""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"


def _make_recipe(path: Path, target: str) -> str:
    content = path.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(target)}:[^\n]*\n(?P<recipe>(?:\t[^\n]*\n)+)", content, re.MULTILINE)
    assert match is not None, f"missing {target!r} target in {path}"
    return match.group("recipe")


def test_extensions_dependency_group_is_part_of_the_default_sync() -> None:
    project = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert isinstance(project["dependency-groups"]["extensions"], list)
    assert set(project["tool"]["uv"]["default-groups"]) == {"dev", "extensions"}


def test_backend_make_targets_never_mutate_the_extension_lock() -> None:
    makefile = BACKEND_ROOT / "Makefile"

    assert "uv sync --locked" in _make_recipe(makefile, "install")
    for target in ("dev", "gateway"):
        recipe = _make_recipe(makefile, target)
        assert "uv run --locked uvicorn" in recipe, target
        assert "uv sync" not in recipe, target


def test_root_local_startup_syncs_the_locked_backend_before_runtime() -> None:
    root_install = _make_recipe(REPO_ROOT / "Makefile", "install")
    serve = (REPO_ROOT / "scripts" / "serve.sh").read_text(encoding="utf-8")

    assert "cd backend && uv sync --locked" in root_install
    sync_at = serve.find("uv sync --locked")
    runtime_at = serve.find("uv run --no-sync uvicorn app.gateway.app:app")
    assert sync_at != -1
    assert runtime_at > sync_at


def test_root_makefile_exposes_extension_management_commands() -> None:
    makefile = REPO_ROOT / "Makefile"

    install = _make_recipe(makefile, "extension-install")
    assert "deerflow extensions install" in install
    assert "--source-env __deerflow_extension_source__" in install
    assert "DEER_FLOW_EXTENSION_SOURCE" not in install
    assert "$(SOURCE)" not in install
    assert "uv run --frozen --no-group extensions" in install
    assert "--yes" not in install

    for target, command in (
        ("extension-list", "deerflow extensions list"),
        ("extension-enable", "deerflow extensions enable"),
        ("extension-disable", "deerflow extensions disable"),
        ("extension-remove", "deerflow extensions remove"),
    ):
        recipe = _make_recipe(makefile, target)
        assert command in recipe
        assert "uv run --frozen --no-group extensions" in recipe


def test_extension_management_bootstrap_does_not_resolve_a_broken_extension_source() -> None:
    makefile = REPO_ROOT / "Makefile"

    for target in (
        "extension-install",
        "extension-list",
        "extension-enable",
        "extension-disable",
        "extension-remove",
    ):
        recipe = _make_recipe(makefile, target)
        assert "uv run --frozen --no-group extensions" in recipe, target
        assert "--locked" not in recipe, target


def test_frozen_management_bootstrap_installs_core_without_reading_a_missing_extension(
    tmp_path: Path,
) -> None:
    project = tmp_path / "backend"
    wheels = tmp_path / "wheels"
    project.mkdir()
    wheels.mkdir()

    def _write_wheel(distribution: str, module: str) -> Path:
        wheel = wheels / f"{distribution.replace('-', '_')}-1.0.0-py3-none-any.whl"
        dist_info = f"{distribution.replace('-', '_')}-1.0.0.dist-info"
        records = {
            f"{module}/__init__.py": "VALUE = 'installed'\n",
            f"{dist_info}/METADATA": f"Metadata-Version: 2.1\nName: {distribution}\nVersion: 1.0.0\n",
            f"{dist_info}/WHEEL": "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        }
        records[f"{dist_info}/RECORD"] = "".join(f"{name},,\n" for name in (*records, f"{dist_info}/RECORD"))
        with zipfile.ZipFile(wheel, "w") as archive:
            for name, content in records.items():
                archive.writestr(name, content)
        return wheel

    core_wheel = _write_wheel("bootstrap-core", "bootstrap_core")
    missing_extension = _write_wheel("broken-extension", "broken_extension")
    (project / "pyproject.toml").write_text(
        f"""\
[project]
name = "bootstrap-host"
version = "0.0.0"
requires-python = ">=3.12"
dependencies = ["bootstrap-core @ {core_wheel.as_uri()}"]

[dependency-groups]
extensions = ["broken-extension @ {missing_extension.as_uri()}"]
""",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["UV_CACHE_DIR"] = str(tmp_path / "uv-cache")
    subprocess.run(["uv", "lock"], cwd=project, env=environment, check=True, capture_output=True)
    missing_extension.unlink()

    completed = subprocess.run(
        [
            "uv",
            "run",
            "--frozen",
            "--no-group",
            "extensions",
            "python",
            "-c",
            "import bootstrap_core; assert bootstrap_core.VALUE == 'installed'",
        ],
        cwd=project,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_root_extension_shortcuts_are_cross_platform_and_keep_trust_confirmation() -> None:
    makefile = REPO_ROOT / "Makefile"

    for target in (
        "extension-install",
        "extension-enable",
        "extension-disable",
        "extension-remove",
    ):
        recipe = _make_recipe(makefile, target)
        assert "test -n" not in recipe, target
        assert "usage: make" in recipe, target

    assert "--yes" not in _make_recipe(makefile, "extension-install")


def test_root_extension_shortcuts_reject_ambient_environment_arguments() -> None:
    environment = os.environ.copy()

    for target, variable in (("extension-install", "SOURCE"), ("extension-enable", "NAME")):
        environment[variable] = "ambient-value"
        result = subprocess.run(
            ["make", "--no-print-directory", "-n", target],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 2, target
        assert f"usage: make {target}" in result.stderr, target


@pytest.mark.parametrize(
    ("target", "variable", "env_option"),
    [
        ("extension-install", "SOURCE", "--source-env __deerflow_extension_source__"),
        ("extension-enable", "NAME", "--name-env __deerflow_extension_name__"),
        ("extension-disable", "NAME", "--name-env __deerflow_extension_name__"),
        ("extension-remove", "NAME", "--name-env __deerflow_extension_name__"),
    ],
)
def test_root_extension_shortcuts_keep_command_line_arguments_out_of_the_shell_recipe(
    target: str,
    variable: str,
    env_option: str,
) -> None:
    marker = "EXTENSION_WRAPPER_INJECTION"
    malicious_value = f'"; printf {marker}; #$(shell printf {marker})'

    result = subprocess.run(
        ["make", "--no-print-directory", "-n", target, f"{variable}={malicious_value}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert marker not in result.stdout
    assert env_option in result.stdout
    assert "$DEER_FLOW_EXTENSION_" not in result.stdout
    assert "%DEER_FLOW_EXTENSION_" not in result.stdout


@pytest.mark.parametrize(
    ("target", "variable", "env_option"),
    [
        ("extension-install", "SOURCE", "--source-env __deerflow_extension_source__"),
        ("extension-enable", "NAME", "--name-env __deerflow_extension_name__"),
        ("extension-disable", "NAME", "--name-env __deerflow_extension_name__"),
        ("extension-remove", "NAME", "--name-env __deerflow_extension_name__"),
    ],
)
def test_root_extension_shortcuts_keep_values_out_of_the_cmd_recipe_on_windows(
    target: str,
    variable: str,
    env_option: str,
) -> None:
    marker = "EXTENSION_WRAPPER_INJECTION"
    malicious_value = f'"; printf {marker}; #$(shell printf {marker})'

    result = subprocess.run(
        [
            "make",
            "--no-print-directory",
            "-n",
            "OS=Windows_NT",
            target,
            f"{variable}={malicious_value}",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert marker not in result.stdout
    assert env_option in result.stdout
    assert "$DEER_FLOW_EXTENSION_" not in result.stdout
    assert "%DEER_FLOW_EXTENSION_" not in result.stdout


def test_docker_dev_entrypoint_syncs_the_lock_before_runtime() -> None:
    entrypoint = (REPO_ROOT / "docker" / "dev-entrypoint.sh").read_text(encoding="utf-8")

    sync_at = entrypoint.find("uv sync --locked --all-packages")
    runtime_at = entrypoint.find("uv run --no-sync uvicorn app.gateway.app:app")
    assert sync_at != -1
    assert runtime_at > sync_at


def test_docker_image_builds_from_the_lock_and_never_syncs_at_runtime() -> None:
    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")
    production_compose = (REPO_ROOT / "docker" / "docker-compose.yaml").read_text(encoding="utf-8")

    assert "uv sync --locked --extra redis" in dockerfile
    assert "ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.1" in dockerfile
    assert dockerfile.count("uv run --no-sync uvicorn app.gateway.app:app") == 2
    assert "uv run --no-sync uvicorn app.gateway.app:app" in production_compose
    for compose_name in ("docker-compose.yaml", "docker-compose-dev.yaml"):
        compose = (REPO_ROOT / "docker" / compose_name).read_text(encoding="utf-8")
        assert "ghcr.io/astral-sh/uv:0.11.1" in compose


def test_docker_context_keeps_every_managed_extension_artifact() -> None:
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")

    reinclusion = "!backend/extensions/sources/**"
    assert reinclusion in dockerignore
    assert dockerignore.rfind(reinclusion) > dockerignore.rfind("*.md")
    assert dockerignore.rfind(reinclusion) > dockerignore.rfind("assets/")
    assert dockerignore.rfind(reinclusion) > dockerignore.rfind("*.so")


def test_docker_builder_can_resolve_locked_git_extensions() -> None:
    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")

    builder_packages = re.search(
        r"apt-get install -y \\\n(?P<packages>.*?)    && mkdir -p /etc/apt/keyrings",
        dockerfile,
        re.DOTALL,
    )
    assert builder_packages is not None
    assert re.search(r"^\s*git\s+\\$", builder_packages.group("packages"), re.MULTILINE)
