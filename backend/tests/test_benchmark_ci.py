"""Keep the benchmark script CI wired to the marker and Makefile targets."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "backend/tests"
WORKFLOW = REPO_ROOT / ".github/workflows/backend-benchmark-tests.yml"
MAKEFILE = REPO_ROOT / "backend/Makefile"
MARKER = "benchmark"

REQUIRED_PATHS = [
    "backend/scripts/benchmark/**",
    "backend/tests/conftest.py",
    "backend/tests/support/**",
    "backend/tests/test_bench_*.py",
    "backend/tests/test_benchmark_ci.py",
    "backend/pyproject.toml",
    "backend/uv.lock",
    "backend/Makefile",
    ".github/workflows/backend-benchmark-tests.yml",
]


def _workflow() -> dict:
    # BaseLoader preserves GitHub Actions' `on` key rather than YAML 1.1 bool True.
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _marked_modules() -> set[str]:
    marked = set()
    for path in TESTS_DIR.rglob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets):
                if MARKER in ast.dump(node.value):
                    marked.add(path.relative_to(TESTS_DIR).as_posix())
    return marked


def test_every_bench_test_module_carries_the_benchmark_marker() -> None:
    bench_modules = {path.relative_to(TESTS_DIR).as_posix() for path in TESTS_DIR.glob("test_bench_*.py")}
    marked = _marked_modules()

    assert bench_modules, "no test_bench_*.py modules found"
    assert marked == bench_modules


@pytest.mark.parametrize("event", ["push", "pull_request"])
def test_each_event_triggers_on_benchmark_scripts_and_tests(event: str) -> None:
    paths = _workflow()["on"][event]["paths"]

    for path in REQUIRED_PATHS:
        assert path in paths, f"{path} is missing from the {event} paths filter"


@pytest.mark.parametrize("event", ["push", "pull_request"])
def test_the_filter_does_not_cover_all_of_the_backend(event: str) -> None:
    paths = _workflow()["on"][event]["paths"]

    assert "backend/tests/**" not in paths
    assert "backend/app/**" not in paths
    assert "backend/packages/**" not in paths


def test_the_workflow_supersedes_in_flight_runs() -> None:
    concurrency = _workflow()["concurrency"]

    assert concurrency["group"].startswith("backend-benchmark-tests-")
    assert "${{ github.event.pull_request.number || github.ref }}" in concurrency["group"]
    assert concurrency["cancel-in-progress"] == "true"


def test_the_job_runs_the_benchmark_target_in_the_backend() -> None:
    steps = _workflow()["jobs"]["backend-benchmark-tests"]["steps"]
    step = next((item for item in steps if item.get("run") == "make test-benchmark"), None)

    assert step is not None, "the workflow must run make test-benchmark"
    assert step["working-directory"] == "backend"


def test_core_and_benchmark_selections_stay_complementary() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert makefile.count('-m "not live and not bundled_extension and not benchmark"') == 2
    assert makefile.count('-m "benchmark and not live"') == 1


def test_marker_is_registered() -> None:
    project = tomllib.loads((REPO_ROOT / "backend/pyproject.toml").read_text(encoding="utf-8"))
    markers = project["tool"]["pytest"]["ini_options"]["markers"]

    assert any(marker.startswith(f"{MARKER}:") for marker in markers), f"{MARKER} must be a registered pytest marker"
