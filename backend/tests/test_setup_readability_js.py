"""Tests for the explicit Readability.js setup step (scripts/setup_readability_js.py)."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "setup_readability_js.py"
_spec = importlib.util.spec_from_file_location("setup_readability_js", _SCRIPT)
readability_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(readability_setup)


@pytest.fixture
def js_dir(tmp_path):
    directory = tmp_path / "javascript"
    directory.mkdir()
    (directory / "package.json").write_text("{}", encoding="utf-8")
    return directory


@pytest.fixture
def reviewed_lockfile(tmp_path, monkeypatch):
    lockfile = tmp_path / "reviewed" / "package-lock.json"
    lockfile.parent.mkdir()
    lockfile.write_text('{"lockfileVersion": 3, "packages": {}}', encoding="utf-8")
    monkeypatch.setattr(readability_setup, "LOCKFILE_SOURCE", lockfile)
    return lockfile


def test_install_copies_lockfile_and_runs_ci_ignore_scripts(js_dir, reviewed_lockfile):
    runs = []
    sleeps = []

    def _fake_run(cmd, **kwargs):
        runs.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")

    assert readability_setup.install_dependencies(js_dir, "C:/fake/npm.cmd", run=_fake_run, sleep=sleeps.append) is True
    # The reviewed lockfile is staged where npm ci reads it, and lifecycle
    # scripts never run.
    assert (js_dir / "package-lock.json").read_text(encoding="utf-8") == reviewed_lockfile.read_text(encoding="utf-8")
    assert runs == [["C:/fake/npm.cmd", "ci", "--ignore-scripts", "--no-audit", "--no-fund"]]
    assert sleeps == []


def test_install_retries_network_failures_with_bounded_backoff(js_dir, reviewed_lockfile, monkeypatch):
    attempts = []

    def _fake_run(cmd, **kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            # A registry/proxy outage surfaces as a nonzero exit, not a
            # Python exception.
            return subprocess.CompletedProcess(cmd, returncode=1, stdout=b"", stderr=b"npm error code ECONNREFUSED")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")

    sleeps = []

    assert readability_setup.install_dependencies(js_dir, "npm", run=_fake_run, sleep=sleeps.append) is True
    assert len(attempts) == 3
    assert sleeps == [2, 4]


def test_install_gives_up_after_bounded_attempts(js_dir, reviewed_lockfile):
    attempts = []

    def _fake_run(cmd, **kwargs):
        attempts.append(1)
        # UTF-8 box-drawing bytes must decode with replacement, not the
        # strict locale codec.
        return subprocess.CompletedProcess(cmd, returncode=1, stdout=b"", stderr=b"\xe2\x94\x80 offline \xe2\x80\x9d")

    assert readability_setup.install_dependencies(js_dir, "npm", run=_fake_run, sleep=lambda _: None) is False
    assert len(attempts) == readability_setup.MAX_INSTALL_ATTEMPTS


def test_node_dependencies_loadable_checks_require(js_dir, monkeypatch):
    runs = []

    def _fake_run(cmd, **kwargs):
        runs.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(readability_setup.subprocess, "run", _fake_run)

    assert readability_setup.node_dependencies_loadable(js_dir, "node") is True
    assert len(runs) == 1
    assert "jsdom" in runs[0][2] and "@mozilla/readability" in runs[0][2]


def test_node_dependencies_loadable_survives_crashing_node(js_dir, monkeypatch):
    def _fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, timeout=60)

    monkeypatch.setattr(readability_setup.subprocess, "run", _fake_run)

    assert readability_setup.node_dependencies_loadable(js_dir, "node") is False


def test_main_reports_missing_node_or_npm(monkeypatch):
    monkeypatch.setattr(readability_setup.shutil, "which", lambda name: None)

    assert readability_setup.main() == 1


def test_main_fails_when_installed_packages_cannot_load(monkeypatch):
    monkeypatch.setattr(readability_setup.shutil, "which", lambda name: f"fake-{name}")
    monkeypatch.setattr(readability_setup, "install_dependencies", lambda *args, **kwargs: True)
    monkeypatch.setattr(readability_setup, "node_dependencies_loadable", lambda *args, **kwargs: False)

    assert readability_setup.main() == 1


class _FakeSubprocessModule:
    """Route the script's subprocess calls through a stub while keeping the
    exception types the script catches."""

    def __init__(self, real, run):
        self.TimeoutExpired = real.TimeoutExpired
        self.CompletedProcess = real.CompletedProcess
        self._run = run

    def run(self, *args, **kwargs):
        return self._run(*args, **kwargs)
