"""Regression test keeping runtime data out of the Docker build context.

``backend/Dockerfile`` copies the backend tree wholesale (``COPY backend ./backend``),
so every path under ``backend/`` that ``.dockerignore`` does not exclude is shipped
into the image. The runtime directories are written by a *running* DeerFlow, not by
a build:

- ``DEER_FLOW_HOME`` (``backend/.deer-flow`` by default) holds the sqlite database,
  per-user agent definitions and uploads, and ``.jwt_secret``.
- ``backend/sandbox`` is the local sandbox provider's workspace root, created by
  ``backend/Makefile`` and written by agent runs.

Leaving them in the context has two consequences. Anyone who builds an image on a
host that has run DeerFlow bakes that state — including the JWT secret and the user
database — into the image. And because the Gateway container creates some of those
directories as root, the build client eventually cannot read them and the build
fails outright::

    target gateway: failed to solve: error from sender:
    open .../.deer-flow/users/<uuid>/integrations/lark-cli: permission denied

Neither directory has any tracked content, so excluding them costs the build nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERIGNORE = REPO_ROOT / ".dockerignore"

# Paths a running DeerFlow creates that must never enter the build context.
RUNTIME_PATHS = [
    "backend/.deer-flow/data/deerflow.db",
    "backend/.deer-flow/.jwt_secret",
    "backend/.deer-flow/users/some-user/agents/my-agent/config.yaml",
    "backend/sandbox/some-thread/scratch.py",
]

# Paths the build genuinely needs; the exclusions must not swallow them.
BUILD_INPUT_PATHS = [
    "backend/pyproject.toml",
    "backend/app/gateway/app.py",
    "backend/packages/harness/deerflow/config/extensions_config.py",
]


def _ignore_patterns() -> list[str]:
    lines = DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def _matches(pattern: str, path: str) -> bool:
    """Whether *pattern* excludes *path*, for the pattern shapes this file uses.

    Docker matches ``.dockerignore`` entries against context-relative paths. Only
    two shapes are needed here: a directory prefix (``backend/sandbox/``) and a
    leading ``**/`` that anchors a directory name at any depth.
    """
    if pattern.startswith("!"):
        return False
    pattern = pattern.rstrip("/")
    if pattern.startswith("**/"):
        name = pattern[3:]
        return name in Path(path).parts
    prefix = f"{pattern}/"
    return path == pattern or path.startswith(prefix)


@pytest.mark.parametrize("runtime_path", RUNTIME_PATHS)
def test_runtime_data_is_excluded_from_build_context(runtime_path: str) -> None:
    patterns = _ignore_patterns()
    assert any(_matches(pattern, runtime_path) for pattern in patterns), f"{runtime_path} would be copied into the image; add a .dockerignore entry covering it"


@pytest.mark.parametrize("build_input", BUILD_INPUT_PATHS)
def test_build_inputs_are_still_included(build_input: str) -> None:
    patterns = _ignore_patterns()
    matching = [pattern for pattern in patterns if _matches(pattern, build_input)]
    assert not matching, f"{build_input} is needed by the build but is excluded by {matching}"
