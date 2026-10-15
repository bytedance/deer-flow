"""Regression test keeping host-local data out of the Docker build context.

``backend/Dockerfile`` copies the backend tree wholesale (``COPY backend ./backend``),
so every path under ``backend/`` that ``.dockerignore`` does not exclude is shipped
into the image. The runtime directories are written by a *running* DeerFlow, not by
a build or local deployment:

- Exact ``.env`` files hold deployment secrets at the repository root and in
  the backend/frontend projects.
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

None of these paths has tracked content, so excluding them costs the build nothing.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERIGNORE = REPO_ROOT / ".dockerignore"

# Host-local runtime and secret paths that must never enter the build context.
HOST_LOCAL_PATHS = [
    ".env",
    "backend/.env",
    "frontend/.env",
    ".deer-flow/integrations/skills/provider/pack/SKILL.md",
    "backend/.deer-flow/data/deerflow.db",
    "backend/.deer-flow/.jwt_secret",
    "backend/.deer-flow/users/some-user/agents/my-agent/config.yaml",
    "backend/sandbox/some-thread/scratch.py",
]

# Paths the build genuinely needs; the exclusions must not swallow them.
BUILD_INPUT_PATHS = [
    ".env.example",
    "frontend/.env.example",
    "backend/pyproject.toml",
    "backend/app/gateway/app.py",
    "backend/packages/harness/deerflow/config/extensions_config.py",
]


def _ignore_patterns() -> list[str]:
    lines = DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def _pattern_matches(pattern: str, path: str) -> bool:
    """Whether one non-negated pattern matches *path*.

    This intentionally models the pattern shapes used by this repository rather
    than reimplementing Docker's full matcher: root-relative names/globs,
    directory prefixes, trailing ``/**``, and leading ``**/name`` patterns.
    """
    pattern = pattern.rstrip("/")
    if pattern.startswith("**/"):
        name = pattern[3:]
        return name in PurePosixPath(path).parts
    if pattern.endswith("/**"):
        pattern = pattern[:-3].rstrip("/")
    if "/" not in pattern:
        root_name = PurePosixPath(path).parts[0]
        return fnmatchcase(root_name, pattern)
    prefix = f"{pattern}/"
    return path == pattern or path.startswith(prefix)


def _is_excluded(patterns: list[str], path: str) -> bool:
    """Resolve Docker's last-matching-pattern-wins exclusion state."""
    excluded = False
    for raw_pattern in patterns:
        negated = raw_pattern.startswith("!")
        pattern = raw_pattern[1:] if negated else raw_pattern
        if _pattern_matches(pattern, path):
            excluded = not negated
    return excluded


@pytest.mark.parametrize(
    ("patterns", "expected"),
    [
        (["backend/runtime.json", "!backend/runtime.json"], False),
        (["!backend/runtime.json", "backend/runtime.json"], True),
    ],
)
def test_exclusion_uses_last_matching_pattern(patterns: list[str], expected: bool) -> None:
    assert _is_excluded(patterns, "backend/runtime.json") is expected


@pytest.mark.parametrize("local_path", HOST_LOCAL_PATHS)
def test_host_local_data_is_excluded_from_build_context(local_path: str) -> None:
    patterns = _ignore_patterns()
    assert _is_excluded(patterns, local_path), f"{local_path} would be copied into the image; add a .dockerignore entry covering it"


@pytest.mark.parametrize("build_input", BUILD_INPUT_PATHS)
def test_build_inputs_are_still_included(build_input: str) -> None:
    patterns = _ignore_patterns()
    assert not _is_excluded(patterns, build_input), f"{build_input} is needed by the build but is excluded"
