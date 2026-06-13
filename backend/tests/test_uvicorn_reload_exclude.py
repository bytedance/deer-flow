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
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from uvicorn.config import resolve_reload_patterns

REPO_ROOT = Path(__file__).resolve().parents[2]

LAUNCHERS = {
    "scripts/serve.sh": REPO_ROOT / "scripts" / "serve.sh",
    "docker/dev-entrypoint.sh": REPO_ROOT / "docker" / "dev-entrypoint.sh",
}

# Shell terminators / redirects that end a simple command's argument list.
_CMD_BOUNDARY = re.compile(r"[;&|<>]")


def _logical_lines(script: str) -> list[str]:
    """Fold ``\\``-continuations and drop comment lines, yielding logical lines.

    A ``mkdir`` or ``--reload-exclude`` list split across lines with a trailing
    backslash becomes one line here, so an argument on a continuation line can't
    be silently dropped by per-line scanning.
    """
    folded = script.replace("\\\n", " ")
    return [line for line in folded.splitlines() if not line.lstrip().startswith("#")]


def _shlex(fragment: str) -> list[str]:
    """Tokenize a shell fragment (quotes stripped, ``$VAR`` kept literal,
    trailing ``# comment`` honored); tolerate pathological quoting."""
    try:
        return shlex.split(fragment, comments=True)
    except ValueError:
        return fragment.split()


# ``--reload-exclude`` followed by ``=`` or whitespace, then a value that is a
# single-quoted group, a double-quoted group, or a bare token. The quoted
# alternatives match a *balanced* pair first, so serve.sh's surrounding
# ``GATEWAY_EXTRA_FLAGS="..."`` closing quote is never swallowed into the value.
_RELOAD_EXCLUDE = re.compile(r"""--reload-exclude[=\s]+('[^']*'|"[^"]*"|[^\s'"]+)""")


def _reload_exclude_values(script: str) -> list[str]:
    """Every ``--reload-exclude`` value, with surrounding quotes removed.

    Handles both CLI forms (``--reload-exclude=<value>`` and the space form
    ``--reload-exclude <value>``) and both shell quotings the launchers use:

    * ``docker/dev-entrypoint.sh`` puts each flag on its own line.
    * ``scripts/serve.sh`` packs every flag into a single double-quoted
      ``GATEWAY_EXTRA_FLAGS="... --reload-exclude='$X' ..."`` assignment. A
      whole-line ``shlex`` would collapse that assignment into one token and
      find no flags (this is what regressed serve.sh in CI); matching balanced
      inner quotes here keeps the assignment's closing ``"`` out of the value,
      so every exclude — including the last ``$BACKEND_RUNTIME_HOME`` — is seen.
    """
    values: list[str] = []
    for line in _logical_lines(script):
        for raw in _RELOAD_EXCLUDE.findall(line):
            values.append(raw.strip("\"'"))
    return values


def _mkdir_dirs(script: str) -> set[str]:
    """Exact set of directories created by every ``mkdir`` command.

    Tokenizes each ``mkdir`` argument list rather than substring-matching, so
    ``/app/backend/sandbox`` is not falsely considered created by, say,
    ``mkdir -p /app/backend/sandbox-other``.
    """
    dirs: set[str] = set()
    for line in _logical_lines(script):
        match = re.search(r"\bmkdir\b(.*)", line)
        if not match:
            continue
        args = _CMD_BOUNDARY.split(match.group(1), maxsplit=1)[0]
        for token in _shlex(args):
            if token.startswith("-"):  # skip flags such as -p
                continue
            dirs.add(token)
    return dirs


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
    """Every absolute ``--reload-exclude`` dir must be created by ``mkdir`` first.

    Relative glob patterns (``*.pyc``, ``__pycache__``) are safe and skipped;
    anything anchored at ``/`` or a shell variable is an absolute path that
    uvicorn would glob — and crash on — unless it already exists. Membership is
    an exact match against the parsed ``mkdir`` argument set (not a substring
    test), so a path-prefix can't produce a false pass.
    """
    script = LAUNCHERS[name].read_text(encoding="utf-8")
    created = _mkdir_dirs(script)

    absolute_excludes = [v for v in _reload_exclude_values(script) if v.startswith(("/", "$"))]
    assert absolute_excludes, f"{name}: expected at least one absolute reload-exclude"

    for value in absolute_excludes:
        assert value in created, f"{name}: absolute reload-exclude {value!r} is never created via mkdir (created dirs: {sorted(created)})"


@pytest.mark.parametrize("name", list(LAUNCHERS))
def test_sandbox_mkdir_precedes_uvicorn_launch(name):
    """The sandbox mkdir must come before the uvicorn launch, not just exist.

    ``_mkdir_dirs`` only proves the mkdir is present somewhere; this pins script
    order so a future edit can't move (or guard) the mkdir below the launch and
    silently reintroduce the #3454 crash on a fresh checkout. ``uv run uvicorn``
    matches the launch but not serve.sh's ``stop_all`` kill line.
    """
    lines = LAUNCHERS[name].read_text(encoding="utf-8").splitlines()
    launch_idx = next((i for i, ln in enumerate(lines) if "uv run uvicorn" in ln), None)
    mkdir_idx = next((i for i, ln in enumerate(lines) if re.search(r"\bmkdir\b", ln) and "sandbox" in ln), None)

    assert launch_idx is not None, f"{name}: could not locate the 'uv run uvicorn' launch line"
    assert mkdir_idx is not None, f"{name}: could not locate the sandbox mkdir line"
    assert mkdir_idx < launch_idx, f"{name}: sandbox mkdir (line {mkdir_idx + 1}) must precede uvicorn launch (line {launch_idx + 1})"


def test_precreated_sandbox_artifacts_are_gitignored():
    """backend/sandbox is runtime state — its contents must stay out of git so
    sandbox artifacts can't be accidentally committed (matches the reload-exclude
    intent). A content path is existence-independent, unlike the bare dir path.

    Guards against the inaccurate "gitignored" claim by making it verifiable.
    """
    probe = "backend/sandbox/__artifact_probe__"
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", probe],
        capture_output=True,
    )
    if result.returncode == 128:  # not a git checkout (e.g. packaged install)
        pytest.skip("not inside a git working tree")
    assert result.returncode == 0, "backend/sandbox/* should be gitignored (see backend/.gitignore '/sandbox/')"
