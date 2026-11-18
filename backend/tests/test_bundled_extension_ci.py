"""Keep the bundled extension CI wired to the marker and the Makefile targets."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "backend/tests"
WORKFLOW = REPO_ROOT / ".github/workflows/bundled-extension-tests.yml"
MAKEFILE = REPO_ROOT / "backend/Makefile"
MARKER = "bundled_extension"

# The marked suites load the bundled examples into these host subtrees, so a
# change there has to run them even though the core shards no longer do.
PAYLOAD_PATHS = [
    "examples/deerflow-extension-*/**",
    "backend/packages/**",
    "backend/app/gateway/**",
]

# Shared test infrastructure the marked modules may use.
SHARED_TEST_PATHS = [
    "backend/tests/conftest.py",
    "backend/tests/support/**",
]


def _workflow() -> dict:
    # BaseLoader preserves GitHub Actions' `on` key rather than treating it as
    # YAML 1.1's boolean True.
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _marked_modules() -> set[str]:
    # Parse the assignment instead of grepping: this file mentions the marker in
    # strings, and a marked module may live in a subdirectory.
    marked = set()
    for path in TESTS_DIR.rglob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets):
                if "bundled_extension" in ast.dump(node.value):
                    marked.add(path.relative_to(TESTS_DIR).as_posix())
    return marked


@pytest.mark.parametrize("event", ["push", "pull_request"])
def test_each_event_triggers_on_the_bundled_payloads(event: str) -> None:
    paths = _workflow()["on"][event]["paths"]

    for path in PAYLOAD_PATHS:
        assert path in paths, f"{path} is missing from the {event} paths filter"


@pytest.mark.parametrize("event", ["push", "pull_request"])
def test_each_marked_module_is_listed_in_the_trigger_paths(event: str) -> None:
    paths = _workflow()["on"][event]["paths"]
    marked = _marked_modules()

    assert marked, "no module carries the marker"
    for path in SHARED_TEST_PATHS:
        assert path in paths, f"the {event} filter must cover {path}"
    for module in sorted(marked):
        assert f"backend/tests/{module}" in paths, f"{module} carries the marker but is not in the {event} trigger paths"


@pytest.mark.parametrize("event", ["push", "pull_request"])
def test_the_filter_does_not_cover_all_of_the_backend(event: str) -> None:
    paths = _workflow()["on"][event]["paths"]

    # Broad backend subtrees would run the bundled suites for unrelated Gateway
    # or test changes; the marked modules only import app.gateway.
    assert "backend/tests/**" not in paths
    assert "backend/app/**" not in paths
    assert "backend/app/gateway/**" in paths


def test_the_workflow_supersedes_in_flight_runs() -> None:
    concurrency = _workflow()["concurrency"]

    # A rapid push must supersede the in-flight run instead of queuing another
    # full dependency install, as the sibling workflows do.
    assert concurrency["group"].startswith("bundled-extension-tests-")
    assert "${{ github.event.pull_request.number || github.ref }}" in concurrency["group"]
    assert concurrency["cancel-in-progress"] == "true"


def test_the_job_runs_the_bundled_target_in_the_backend() -> None:
    steps = _workflow()["jobs"]["bundled-extension-tests"]["steps"]
    step = next((item for item in steps if item.get("run") == "make test-bundled-extensions"), None)

    assert step is not None, "the workflow must run make test-bundled-extensions"
    assert step["working-directory"] == "backend"


def test_core_and_bundled_selections_stay_complementary() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")

    # Core shards and their duration baseline exclude the marker; the bundled
    # target selects exactly it. Renaming either side must fail here.
    assert makefile.count('-m "not live and not bundled_extension"') == 2
    assert makefile.count('-m "bundled_extension and not live"') == 1


def test_marker_is_registered() -> None:
    project = tomllib.loads((REPO_ROOT / "backend/pyproject.toml").read_text(encoding="utf-8"))
    markers = project["tool"]["pytest"]["ini_options"]["markers"]

    assert any(marker.startswith(f"{MARKER}:") for marker in markers), f"{MARKER} must be a registered pytest marker"
