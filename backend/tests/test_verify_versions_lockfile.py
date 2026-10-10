"""Regression test: the release gate must reject a stale ``backend/uv.lock``.

``scripts/verify_versions.sh`` gates every ``v*`` publish (``chart.yaml`` and
``container.yaml`` through ``verify-versions.yml``), but it compared only
``Chart.yaml``, ``pyproject.toml`` and ``package.json``. ``backend/uv.lock``
records the root package version too, and ``backend/Dockerfile`` installs with
``uv sync --locked``. Bumping the three text sources by hand therefore passed
the gate::

    $ scripts/verify_versions.sh 2.2.0
    OK — all version sources agree on 2.2.0.
    $ cd backend && uv sync --locked --extra redis --extra postgres
    The lockfile at `uv.lock` needs to be updated, but `--locked` was provided.

On a tag, the chart and the frontend and provisioner images published while the
backend image build failed, and the immutable chart version meant the fix
needed a new version number. ``uv lock --check`` in lint CI does not run on
tags.

The gate now asks uv itself (``uv lock --check``), which owns the PEP 440
normalization (``2.1.0-rc0`` is stored as ``2.1.0rc0``), and refuses to pass
without uv.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml
from support.shell import find_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_BASH = find_script_bash()
VERIFY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "verify-versions.yml"

pytestmark = pytest.mark.skipif(
    SCRIPT_BASH is None or os.name == "nt",
    reason="the fake `uv` on PATH is an extensionless shebang script; Windows does not execute those",
)

# Fake `uv lock --check`: the lock is current when its root entry records the
# pyproject version in uv's PEP 440 form (for these inputs, without the `-`).
# The invocation and its working directory are logged so a test can tell
# whether the gate asked uv at all, and from backend/.
FAKE_UV = """#!/usr/bin/env python3
import os
import re
import sys
from pathlib import Path

log = Path(__file__).with_name("uv-calls.log")
with log.open("a", encoding="utf-8") as handle:
    handle.write(os.getcwd() + " uv " + " ".join(sys.argv[1:]) + "\\n")

if sys.argv[1:] != ["lock", "--check"]:
    sys.exit(f"fake uv: unsupported invocation {sys.argv[1:]}")

root = Path.cwd()
declared = re.search(r'(?m)^version\\s*=\\s*"([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8")).group(1)
recorded = re.search(r'(?m)^name = "deer-flow"\\nversion = "([^"]+)"', (root / "uv.lock").read_text(encoding="utf-8")).group(1)
if recorded != declared.replace("-", ""):
    sys.exit("The lockfile at `uv.lock` needs to be updated, but `--check` was provided. To update the lockfile, run `uv lock`.")
print("Resolved 1 package")
"""


def _write_sandbox(root: Path, *, sources: str, lock: str) -> Path:
    """A repo-shaped tree with every version source at ``sources`` and the lock at ``lock``."""
    (root / "scripts").mkdir(parents=True)
    (root / "backend").mkdir()
    (root / "frontend").mkdir()
    (root / "deploy" / "helm" / "deer-flow").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "scripts" / "verify_versions.sh", root / "scripts" / "verify_versions.sh")

    (root / "backend" / "pyproject.toml").write_text(f'[project]\nname = "deer-flow"\nversion = "{sources}"\n', encoding="utf-8")
    (root / "backend" / "uv.lock").write_text(
        f'version = 1\n\n[[package]]\nname = "deer-flow"\nversion = "{lock}"\nsource = {{ virtual = "." }}\n',
        encoding="utf-8",
    )
    (root / "frontend" / "package.json").write_text(f'{{\n  "name": "deer-flow-frontend",\n  "version": "{sources}"\n}}\n', encoding="utf-8")
    (root / "deploy" / "helm" / "deer-flow" / "Chart.yaml").write_text(
        f'apiVersion: v2\nname: deer-flow\nversion: {sources}\nappVersion: "{sources}"\n',
        encoding="utf-8",
    )
    return root


def _install_fake_uv(root: Path) -> Path:
    bin_dir = root / "fake-bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(FAKE_UV, encoding="utf-8")
    uv.chmod(uv.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (bin_dir / "uv-calls.log").write_text("", encoding="utf-8")
    return bin_dir


def _run_verify(root: Path, *args: str, path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [SCRIPT_BASH, str(root / "scripts" / "verify_versions.sh"), *args],
        cwd=root,
        env={**os.environ, "PATH": path},
        capture_output=True,
        text=True,
        check=False,
    )


def _with_fake_uv(bin_dir: Path) -> str:
    return f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


def _uv_calls(bin_dir: Path) -> list[str]:
    return (bin_dir / "uv-calls.log").read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(("sources", "lock"), [("2.2.0", "2.2.0"), ("2.1.0-rc1", "2.1.0rc1")], ids=["release", "prerelease"])
def test_gate_passes_when_the_lock_matches(tmp_path: Path, sources: str, lock: str):
    root = _write_sandbox(tmp_path / "repo", sources=sources, lock=lock)
    bin_dir = _install_fake_uv(root)

    result = _run_verify(root, sources, path=_with_fake_uv(bin_dir))

    assert result.returncode == 0, result.stderr
    assert f"backend/uv.lock:        {lock}" in result.stdout
    assert _uv_calls(bin_dir) == [f"{(root / 'backend').resolve()} uv lock --check"]


@pytest.mark.parametrize("args", [("2.2.0",), ()], ids=["against-tag", "mutual"])
def test_gate_rejects_a_lock_left_on_the_previous_version(tmp_path: Path, args: tuple[str, ...]):
    """The three text sources were bumped by hand; the lock was not."""
    root = _write_sandbox(tmp_path / "repo", sources="2.2.0", lock="2.2.0.dev0")
    bin_dir = _install_fake_uv(root)

    result = _run_verify(root, *args, path=_with_fake_uv(bin_dir))

    assert result.returncode == 1
    assert "::error::backend/uv.lock is out of date" in result.stderr
    assert "needs to be updated" in result.stderr, "uv's own explanation should reach the job log"
    assert "Tip: run scripts/bump_version.sh" in result.stderr
    assert "OK —" not in result.stdout


def test_gate_refuses_to_pass_without_uv(tmp_path: Path):
    """Skipping the lock check when uv is absent would reopen the gap silently."""
    root = _write_sandbox(tmp_path / "repo", sources="2.2.0", lock="2.2.0")
    # Keep every PATH entry that does not provide a `uv`, so the script still
    # finds awk/grep and can only fail on the missing uv itself.
    without_uv = os.pathsep.join(entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry and not (Path(entry) / "uv").exists())
    assert shutil.which("uv", path=without_uv) is None, "test setup: uv is still reachable on PATH"
    assert shutil.which("awk", path=without_uv) is not None, "test setup: awk must stay reachable"

    result = _run_verify(root, "2.2.0", path=without_uv)

    assert result.returncode == 1
    assert "::error::uv is required to check backend/uv.lock" in result.stderr


def test_release_gate_workflow_installs_uv_before_verifying():
    steps = yaml.safe_load(VERIFY_WORKFLOW.read_text(encoding="utf-8"))["jobs"]["verify-versions"]["steps"]
    setup_uv = [index for index, step in enumerate(steps) if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")]
    verify = [index for index, step in enumerate(steps) if "scripts/verify_versions.sh" in str(step.get("run", ""))]

    assert setup_uv and verify, f"verify-versions.yml must install uv and run verify_versions.sh: {steps}"
    assert setup_uv[0] < verify[0], "uv must be installed before the gate runs its lock check"
