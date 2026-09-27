"""Regression test: ``scripts/bump_version.sh`` must refresh ``backend/uv.lock``.

``RELEASING.md`` tells releasers that step 1 of a release is
``scripts/bump_version.sh <version>`` — "set all four fields at once, then
self-verify" — and ``verify_versions.sh`` agrees that the tree is consistent
afterwards. But ``backend/uv.lock`` records the root package's own version too
(uv normalizes ``2.1.0-rc0`` to ``2.1.0rc0``), and the script only rewrote
``pyproject.toml`` / ``package.json`` / ``Chart.yaml``. The documented release
step therefore left the lock pinned to the *previous* version.

Measured on ``3a862780`` (``main``, version ``2.1.0-rc0``) before this fix::

    $ scripts/bump_version.sh 2.2.0        # documented step, exits 0, self-verifies
    $ sed -n '/name = "deer-flow"/,+1p' backend/uv.lock
    name = "deer-flow"
    version = "2.1.0rc0"                   # still the old version
    $ cd backend && uv lock --check        # .github/workflows/lint-check.yml:59
    error: The lockfile at `uv.lock` needs to be updated, but `--check` was provided.

The release commit that the script claims is verified turns PR CI red, and
``uv sync --locked`` (``e2e-tests.yml``, ``jev-plugin-package.yml``) refuses the
tree. ``RELEASING.md`` only mentions the manual ``cd backend && uv lock`` step in
the pre-release section, so a normal release hit this every time.

The script now refreshes the lock itself and refuses to run without ``uv`` —
better an early error than a half-bumped tree whose lock CI rejects.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from support.shell import find_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_BASH = find_script_bash()

pytestmark = pytest.mark.skipif(
    SCRIPT_BASH is None or os.name == "nt",
    reason="the fake `uv` on PATH is an extensionless shebang script; Windows does not execute those",
)

# Minimal versions of the three files bump_version.sh rewrites, plus the lock
# entry uv writes for the root ("virtual") package. Only the fields the script
# touches are present, so a stray rewrite shows up as a diff.
PYPROJECT = '[project]\nname = "deer-flow"\nversion = "2.1.0-rc0"\n'
PACKAGE_JSON = '{\n  "name": "deer-flow-frontend",\n  "version": "2.1.0-rc0",\n  "private": true\n}\n'
CHART = 'apiVersion: v2\nname: deer-flow\nversion: 2.1.0-rc0\nappVersion: "2.1.0-rc0"\n'
UV_LOCK = 'version = 1\n\n[[package]]\nname = "deer-flow"\nversion = "2.1.0rc0"\nsource = { virtual = "." }\n'

# Emulates the uv behavior the release flow depends on: `uv lock` records the
# pyproject version in the root lock entry, in uv's PEP 440 form (for these
# inputs that only means dropping the `-`). The invocation is logged so the test
# can tell whether the script called uv at all.
FAKE_UV = """#!/usr/bin/env python3
import re
import sys
from pathlib import Path

log = Path(__file__).with_name("uv-calls.log")
with log.open("a", encoding="utf-8") as handle:
    handle.write("uv " + " ".join(sys.argv[1:]) + "\\n")

args = sys.argv[1:]
if args != ["lock"]:
    sys.exit(f"fake uv: unsupported invocation {args}")

root = Path.cwd()
lock_path = root / "uv.lock"
lock_text = lock_path.read_text(encoding="utf-8")
pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
declared = re.search(r'(?m)^version\\s*=\\s*"([^"]+)"', pyproject).group(1)
normalized = declared.replace("-", "")
recorded = re.search(r'(?m)^name = "deer-flow"\\nversion = "([^"]+)"', lock_text).group(1)

lock_path.write_text(lock_text.replace(f'version = "{recorded}"', f'version = "{normalized}"', 1), encoding="utf-8")
"""


def _write_sandbox(root: Path) -> Path:
    """Materialize a repo-shaped tree the scripts can run against."""
    (root / "scripts").mkdir(parents=True)
    (root / "backend").mkdir()
    (root / "frontend").mkdir()
    (root / "deploy" / "helm" / "deer-flow").mkdir(parents=True)

    for name in ("bump_version.sh", "verify_versions.sh"):
        shutil.copy2(REPO_ROOT / "scripts" / name, root / "scripts" / name)

    (root / "backend" / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (root / "backend" / "uv.lock").write_text(UV_LOCK, encoding="utf-8")
    (root / "frontend" / "package.json").write_text(PACKAGE_JSON, encoding="utf-8")
    (root / "deploy" / "helm" / "deer-flow" / "Chart.yaml").write_text(CHART, encoding="utf-8")
    return root


def _install_fake_uv(root: Path) -> Path:
    """Put a fake ``uv`` and the log it appends to on PATH."""
    bin_dir = root / "fake-bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(FAKE_UV, encoding="utf-8")
    uv.chmod(uv.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (bin_dir / "uv-calls.log").write_text("", encoding="utf-8")
    return bin_dir


def _run_bump(root: Path, version: str, path_prefix: Path | None = None, path: str | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if path is not None:
        env["PATH"] = path
    elif path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(
        [SCRIPT_BASH, str(root / "scripts" / "bump_version.sh"), version],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _lock_version(root: Path) -> str:
    lock = (root / "backend" / "uv.lock").read_text(encoding="utf-8")
    return lock.split('version = "', 2)[1].split('"', 1)[0]


def test_bump_version_refreshes_the_lockfile(tmp_path: Path) -> None:
    """After the documented release step the lock records the new version."""
    root = _write_sandbox(tmp_path / "repo")
    bin_dir = _install_fake_uv(root)

    result = _run_bump(root, "2.2.0", path_prefix=bin_dir)

    assert result.returncode == 0, result.stderr
    assert _lock_version(root) == "2.2.0", "backend/uv.lock still pins the previous version"
    assert (root / "backend" / "pyproject.toml").read_text(encoding="utf-8") == PYPROJECT.replace("2.1.0-rc0", "2.2.0")
    invocations = (bin_dir / "uv-calls.log").read_text(encoding="utf-8").splitlines()
    assert invocations and all(line.startswith("uv lock") for line in invocations), f"bump_version.sh never invoked uv lock: {invocations}"


def test_bump_version_normalizes_a_prerelease_into_the_lock(tmp_path: Path) -> None:
    """A prerelease keeps its `-rc` form in the sources and PEP 440 in the lock."""
    root = _write_sandbox(tmp_path / "repo")
    bin_dir = _install_fake_uv(root)

    result = _run_bump(root, "2.1.0-rc1", path_prefix=bin_dir)

    assert result.returncode == 0, result.stderr
    assert (root / "backend" / "pyproject.toml").read_text(encoding="utf-8") == PYPROJECT.replace("2.1.0-rc0", "2.1.0-rc1")
    assert _lock_version(root) == "2.1.0rc1", "uv normalizes the prerelease in the lock, and the script must let it"


def test_bump_version_refuses_to_run_without_uv(tmp_path: Path) -> None:
    """Without uv the script fails before touching anything, instead of half-bumping."""
    root = _write_sandbox(tmp_path / "repo")
    # Keep every PATH entry that does not provide a `uv`, so the script still
    # finds awk/grep/sed/python3 and can only fail on the missing uv itself.
    without_uv = [entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry and not (Path(entry) / "uv").exists()]
    path = os.pathsep.join(without_uv)
    assert shutil.which("uv", path=path) is None, "test setup: uv is still reachable on PATH"
    assert shutil.which("awk", path=path) is not None, "test setup: awk must stay reachable"

    result = _run_bump(root, "2.2.0", path=path)

    assert result.returncode != 0, "a missing uv must be an error: the lock would stay stale"
    assert "uv" in (result.stderr + result.stdout)
    assert (root / "backend" / "pyproject.toml").read_text(encoding="utf-8") == PYPROJECT, "the script edited files before checking for uv"
    assert _lock_version(root) == "2.1.0rc0"
