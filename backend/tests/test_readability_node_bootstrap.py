"""Windows bootstrap for readabilipy's Node extractor.

readabilipy probes npm with ``subprocess.run(["npm", "version"])`` and runs
``npm install`` the same way. On Windows both raise ``FileNotFoundError``
because npm ships as ``npm.cmd`` and CreateProcess does not consult PATHEXT,
so ``node_modules`` never gets installed and every web_fetch silently falls
back to the pure-Python extractor. deer-flow resolves npm through
``shutil.which`` (PATHEXT-aware) and performs the install once, mirroring
``readabilipy.utils.run_npm_install``.
"""

import os
import subprocess

import pytest

from deerflow.utils import readability as readability_module


@pytest.fixture(autouse=True)
def fresh_bootstrap_state(monkeypatch):
    """Other tests in the suite may have run the real bootstrap already."""
    monkeypatch.setattr(readability_module, "_readability_bootstrap_attempted", False)


@pytest.fixture
def fake_readabilipy(monkeypatch, tmp_path):
    """Point the bootstrap at a fake readabilipy javascript directory."""
    jsdir = tmp_path / "javascript"
    jsdir.mkdir()
    (jsdir / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(readability_module, "_readabilipy_js_dir", lambda: jsdir)
    return jsdir


def test_bootstrap_resolves_npm_through_pathtext(monkeypatch, tmp_path, fake_readabilipy):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(readability_module.shutil, "which", lambda name: r"C:\Node\npm.cmd" if name == "npm" else None)
    monkeypatch.setattr(readability_module.subprocess, "run", fake_run)

    readability_module._bootstrap_readability_js()

    assert calls, "bootstrap did not run npm install"
    argv, kwargs = calls[0]
    assert argv == [r"C:\Node\npm.cmd", "install"]
    assert kwargs.get("cwd") == fake_readabilipy


def test_bootstrap_without_npm_leaves_probe_alone(monkeypatch, fake_readabilipy):
    def fail_run(*args, **kwargs):
        raise AssertionError("npm install attempted without npm on PATH")

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(readability_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(readability_module.subprocess, "run", fail_run)

    readability_module._bootstrap_readability_js()


def test_bootstrap_skipped_on_posix(monkeypatch, fake_readabilipy):
    def fail_run(*args, **kwargs):
        raise AssertionError("npm install attempted on POSIX")

    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(readability_module.shutil, "which", lambda name: r"/usr/bin/npm")
    monkeypatch.setattr(readability_module.subprocess, "run", fail_run)

    readability_module._bootstrap_readability_js()


def test_bootstrap_runs_at_most_once(monkeypatch, fake_readabilipy):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1)

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(readability_module.shutil, "which", lambda name: r"C:\Node\npm.cmd")
    monkeypatch.setattr(readability_module.subprocess, "run", fake_run)

    readability_module._bootstrap_readability_js()
    readability_module._bootstrap_readability_js()

    assert len(calls) == 1, "bootstrap retried after a failed install"
    assert readability_module._readability_bootstrap_attempted is True


def test_bootstrap_tolerates_install_errors(monkeypatch, fake_readabilipy):
    def fake_run(argv, **kwargs):
        raise OSError("npm exploded")

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(readability_module.shutil, "which", lambda name: r"C:\Node\npm.cmd")
    monkeypatch.setattr(readability_module.subprocess, "run", fake_run)

    # Must not raise: the pure-Python fallback remains available.
    readability_module._bootstrap_readability_js()
    assert readability_module._readability_bootstrap_attempted is True


def test_probe_recovers_after_bootstrap(monkeypatch, fake_readabilipy):
    """A failed first probe must re-run once node_modules appears."""
    probe_state = {"node_modules": False}

    def fake_have_node():
        return probe_state["node_modules"]

    installed = []

    def fake_run(argv, **kwargs):
        installed.append(argv)
        (fake_readabilipy / "node_modules").mkdir()
        probe_state["node_modules"] = True
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(readability_module.shutil, "which", lambda name: r"C:\Node\npm.cmd")
    monkeypatch.setattr(readability_module.subprocess, "run", fake_run)
    monkeypatch.setattr(readability_module, "_readabilipy_have_node", fake_have_node)
    monkeypatch.setattr(readability_module, "_readability_js_available_cached", None)

    assert readability_module._readability_js_available() is True
    assert installed, "probe did not trigger the Windows npm bootstrap"
