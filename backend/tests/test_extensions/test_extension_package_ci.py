"""Keep bundled extension package tests running when the public contract changes."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_STEP = "Test bundled extension packages that ship tests"


def _workflow() -> dict:
    # BaseLoader preserves GitHub Actions' `on` key rather than treating it as
    # YAML 1.1's boolean True.
    return yaml.load((REPO_ROOT / ".github/workflows/extension-package-check.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _test_step() -> dict:
    steps = _workflow()["jobs"]["check-packages"]["steps"]
    step = next((step for step in steps if step.get("name") == TEST_STEP), None)
    assert step is not None, f"workflow step {TEST_STEP!r} not found in extension-package-check.yml"
    return step


def _tested_packages() -> list[Path]:
    return sorted(path.parent for path in REPO_ROOT.glob("examples/deerflow-extension-*/tests"))


@pytest.mark.parametrize("event", ["push", "pull_request"])
def test_contract_and_example_changes_trigger_the_package_check(event: str) -> None:
    paths = _workflow()["on"][event]["paths"]
    assert "examples/deerflow-extension-*/**" in paths
    assert "backend/packages/extension-api/**" in paths


def test_package_tests_run_against_the_checkout_contract() -> None:
    script = _test_step()["run"]
    lines = [line.strip() for line in script.splitlines()]

    assert "for package in examples/deerflow-extension-*/; do" in lines
    assert '[ -d "${package}tests" ] || continue' in lines
    install_contract = lines.index("uv pip install -e ../../backend/packages/extension-api")
    install_package = lines.index('uv pip install -e ".[dev]"')
    assert install_contract < install_package
    for command in ("uv run --no-project pytest -q", "uv run --no-project ruff check .", "uv run --no-project ruff format --check ."):
        assert lines.index(command) > install_package


def test_every_example_with_tests_declares_the_dev_tools_ci_runs() -> None:
    packages = _tested_packages()
    assert packages, "the extension example ships package tests"
    for package in packages:
        project = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        dev = {Requirement(value).name for value in project.get("optional-dependencies", {}).get("dev", [])}
        assert {"pytest", "ruff"} <= dev, package.name
