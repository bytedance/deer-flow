"""Regression for #3459 / #3454 — dev gateway reload-exclude must not crash.

#3426 switched the dev gateway's ``--reload-exclude`` patterns from relative
(``sandbox/``) to absolute (``$REPO_ROOT/backend/sandbox``). uvicorn only
excludes such a path directly when it already exists as a directory; otherwise
it falls back to ``Path.cwd().glob(pattern)``, and on **Python 3.12**
``pathlib.Path.glob()`` raises ``NotImplementedError: Non-relative patterns are
unsupported`` for an absolute pattern. ``serve.sh`` created the ``.deer-flow``
excludes but not ``backend/sandbox``, so a fresh checkout crashed ``make dev``
on startup.

Two layers of coverage:

* ``test_*_resolve_*`` exercises uvicorn's real ``resolve_reload_patterns`` to
  pin the failure mode and the fix's mechanism.
* ``test_launcher_precreates_every_absolute_reload_exclude`` enforces the actual
  invariant on both launchers: every absolute exclude dir is ``mkdir -p``'d
  before uvicorn starts. This encodes the root cause, so any future absolute
  exclude that forgets its ``mkdir`` fails here.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from uvicorn.config import resolve_reload_patterns

REPO_ROOT = Path(__file__).resolve().parents[2]

LAUNCHERS = {
    "scripts/serve.sh": REPO_ROOT / "scripts" / "serve.sh",
    "docker/dev-entrypoint.sh": REPO_ROOT / "docker" / "dev-entrypoint.sh",
}


def _reload_exclude_values(script: str) -> list[str]:
    """Pull every ``--reload-exclude=<value>`` token, stripped of quoting."""
    values = []
    for raw in re.findall(r"--reload-exclude=(\S+)", script):
        values.append(raw.strip().strip("'\""))
    return values


def _mkdir_text(script: str) -> str:
    """Concatenate every ``mkdir -p`` line so we can test membership."""
    return "\n".join(line for line in script.splitlines() if "mkdir -p" in line)


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="pathlib accepts absolute glob patterns on 3.13+, so the crash is 3.12-only",
)
def test_resolve_reload_patterns_crashes_on_missing_absolute_dir(tmp_path):
    """The exact #3454 failure: absolute exclude + missing dir on Python 3.12."""
    missing = tmp_path / "sandbox"  # absolute path that does not exist yet
    assert not missing.exists()
    with pytest.raises(NotImplementedError):
        resolve_reload_patterns([str(missing)], [])


def test_resolve_reload_patterns_is_safe_once_dir_exists(tmp_path):
    """The fix's mechanism: a pre-created dir takes uvicorn's is_dir() path."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    _patterns, directories = resolve_reload_patterns([str(sandbox)], [])
    resolved = {d.resolve() for d in directories}
    assert sandbox.resolve() in resolved


@pytest.mark.parametrize("name", list(LAUNCHERS))
def test_launcher_precreates_every_absolute_reload_exclude(name):
    """Every absolute ``--reload-exclude`` dir must be ``mkdir -p``'d first.

    Relative glob patterns (``*.pyc``, ``__pycache__``) are safe and skipped;
    anything anchored at ``/`` or a shell variable is an absolute path that
    uvicorn would glob — and crash on — unless it already exists.
    """
    script = LAUNCHERS[name].read_text(encoding="utf-8")
    mkdir_text = _mkdir_text(script)

    absolute_excludes = [v for v in _reload_exclude_values(script) if v.startswith(("/", "$"))]
    assert absolute_excludes, f"{name}: expected at least one absolute reload-exclude"

    for value in absolute_excludes:
        assert value in mkdir_text, f"{name}: absolute reload-exclude {value!r} is never created via 'mkdir -p'"
