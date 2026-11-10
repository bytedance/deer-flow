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
- ``config.yaml`` (and the ``config.yaml.bak`` that ``make config-upgrade`` writes
  beside it), ``extensions_config.json`` and legacy ``mcp_config.json`` hold model
  API keys and MCP credentials. The resolvers still read them from the legacy
  ``backend/`` location, where ``COPY backend ./backend`` would ship them.
- ``.env*.local`` files hold local overrides; ``frontend/.env.local`` is the
  documented place for ``BETTER_AUTH_SECRET``, and ``COPY frontend ./frontend``
  ships it into the image that ``next build`` and ``next start`` read it from.
  ``frontend/*.pem`` is the mkcert key pair for local HTTPS.
- Extension snapshots under ``backend/extensions/sources/`` are re-included
  wholesale, so the files the extension manager refuses to snapshot are excluded
  again after that re-inclusion; a hand-edited snapshot cannot carry them in.

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

import re
from pathlib import Path, PurePosixPath

import pytest

from deerflow.extensions import manager as extension_manager

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
    "config.yaml",
    "config.yaml.bak",
    "extensions_config.json",
    "mcp_config.json",
    "backend/config.yaml",
    "backend/config.yaml.bak",
    "backend/extensions_config.json",
    "backend/mcp_config.json",
    "frontend/.env.local",
    "frontend/.env.production.local",
    "backend/.env.local",
    "frontend/localhost.pem",
    "frontend/localhost-key.pem",
    "backend/extensions/sources/demo/.env",
    "backend/extensions/sources/demo/.env.local",
    "backend/extensions/sources/demo/src/demo/certs/client.pem",
]

# Paths the build genuinely needs; the exclusions must not swallow them.
BUILD_INPUT_PATHS = [
    ".env.example",
    "frontend/.env.example",
    "backend/pyproject.toml",
    "backend/app/gateway/app.py",
    "backend/packages/harness/deerflow/config/extensions_config.py",
    "backend/packages/harness/deerflow/config/app_config.py",
    "frontend/src/env.js",
    "backend/extensions/sources/demo/pyproject.toml",
    "backend/extensions/sources/demo/README.md",
    "backend/extensions/sources/demo/src/demo/__init__.py",
    "backend/extensions/sources/demo/src/demo/_native.so",
]

# A directory inside an extension snapshot; refused files must stay out at any depth.
SNAPSHOT_ROOT = "backend/extensions/sources/demo/src/demo"


def _ignore_patterns() -> list[str]:
    lines = DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    """Translate one pattern the way Docker's matcher does.

    ``**`` spans any number of path segments, ``*`` and ``?`` stay within one
    segment, ``[...]`` is a character class, and every pattern is anchored at
    the build-context root.
    """
    out: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            out.append(".*")
            index += 2
        elif pattern[index] == "*":
            out.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            out.append("[^/]")
            index += 1
        elif pattern[index] == "[" and (end := pattern.find("]", index)) != -1:
            body = pattern[index + 1 : end]
            out.append("[" + ("^" + body[1:] if body.startswith(("!", "^")) else body) + "]")
            index = end + 1
        else:
            out.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(out) + r"\Z")


def _pattern_matches(pattern: str, path: str) -> bool:
    """Whether one non-negated pattern matches *path* or one of its parent directories."""
    regex = _pattern_regex(pattern.rstrip("/"))
    parts = PurePosixPath(path).parts
    return any(regex.match("/".join(parts[:depth])) for depth in range(1, len(parts) + 1))


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


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("config.yaml", "config.yaml", True),
        ("config.yaml", "backend/config.yaml", False),
        ("frontend/*.pem", "frontend/localhost.pem", True),
        ("frontend/*.pem", "frontend/certs/localhost.pem", False),
        ("**/.env*.local", "frontend/.env.local", True),
        ("**/.env*.local", ".env.example", False),
        ("backend/extensions/sources/**/.env", "backend/extensions/sources/demo/.env", True),
        ("backend/extensions/sources/**/.env", "backend/extensions/sources/demo/a/b/.env", True),
        ("**/.deer-flow/", "backend/.deer-flow/data/deerflow.db", True),
        ("*.py[cod]", "module.pyc", True),
        ("*.py[cod]", "backend/module.pyc", False),
    ],
)
def test_pattern_matcher_models_docker(pattern: str, path: str, expected: bool) -> None:
    assert _pattern_matches(pattern, path) is expected


@pytest.mark.parametrize("local_path", HOST_LOCAL_PATHS)
def test_host_local_data_is_excluded_from_build_context(local_path: str) -> None:
    patterns = _ignore_patterns()
    assert _is_excluded(patterns, local_path), f"{local_path} would be copied into the image; add a .dockerignore entry covering it"


@pytest.mark.parametrize("build_input", BUILD_INPUT_PATHS)
def test_build_inputs_are_still_included(build_input: str) -> None:
    patterns = _ignore_patterns()
    assert not _is_excluded(patterns, build_input), f"{build_input} is needed by the build but is excluded"


def test_frontend_unit_tests_are_excluded_from_build_context() -> None:
    patterns = _ignore_patterns()
    path = "frontend/tests/unit/core/extensions/bookmarks.test.ts"
    assert _is_excluded(patterns, path), f"{path} imports examples/ outside the frontend Docker build context"


@pytest.mark.parametrize(
    "name",
    [".env", ".env.local", ".env.production", *sorted(extension_manager._SENSITIVE_FILENAMES), *(f"secret{suffix}" for suffix in sorted(extension_manager._SENSITIVE_SUFFIXES))],
)
def test_files_the_extension_manager_refuses_stay_out_of_snapshots(name: str) -> None:
    patterns = _ignore_patterns()
    assert _is_excluded(patterns, f"{SNAPSHOT_ROOT}/{name}"), f"extension snapshots are re-included wholesale; exclude {name} after the re-inclusion"
