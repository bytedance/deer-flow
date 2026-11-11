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
    monkeypatch.setattr(readability_module, "_readability_js_available_cached", None)
    monkeypatch.setattr(readability_module, "_readability_js_launch_failed", False)


@pytest.fixture
def fake_readabilipy(monkeypatch, tmp_path):
    """Point the bootstrap at a fake readabilipy javascript directory."""
    jsdir = tmp_path / "javascript"
    jsdir.mkdir()
    (jsdir / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(readability_module, "_readabilipy_js_dir", lambda: jsdir)
    return jsdir


class FakeInstallProcess:
    """Stands in for Popen on npm.cmd with configurable phase behavior."""

    kind = "success"

    def __init__(self, argv, **kwargs):
        self.args = argv
        self.pid = 4321
        self.kwargs = kwargs
        self.returncode = 0
        self.communicate_timeouts = []
        self.killed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def communicate(self, timeout=None):
        self.communicate_timeouts.append(timeout)
        if self.kind == "timeout":
            raise subprocess.TimeoutExpired(self.args, timeout)
        if self.kind == "timeout_drain_blocks":
            if len(self.communicate_timeouts) == 1:
                raise subprocess.TimeoutExpired(self.args, timeout)
            self.returncode = 1
            return (None, b"")
        return (None, b"npm stderr")

    def poll(self):
        return self.returncode if not self.kind.startswith("timeout") else None

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture
def install_processes(monkeypatch):
    """Swap Popen for FakeInstallProcess; returns (processes, taskkills)."""
    processes = []
    taskkills = []

    def fake_popen(argv, **kwargs):
        process = FakeInstallProcess(argv, **kwargs)
        processes.append(process)
        return process

    def fake_run(argv, **kwargs):
        taskkills.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(readability_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(readability_module.subprocess, "run", fake_run)
    return processes, taskkills


def test_bootstrap_resolves_npm_through_pathtext(monkeypatch, tmp_path, fake_readabilipy, install_processes):
    install_processes, _taskkills = install_processes
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(readability_module.shutil, "which", lambda name: r"C:\Node\npm.cmd" if name == "npm" else None)

    readability_module._bootstrap_readability_js()

    assert install_processes, "bootstrap did not run npm install"
    process = install_processes[0]
    assert process.args == [r"C:\Node\npm.cmd", "install"]
    assert process.kwargs.get("cwd") == fake_readabilipy


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


def test_bootstrap_runs_at_most_once(monkeypatch, fake_readabilipy, install_processes):
    install_processes, taskkills = install_processes
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(readability_module.shutil, "which", lambda name: r"C:\Node\npm.cmd")

    def failing_popen(argv, **kwargs):
        process = FakeInstallProcess(argv, **kwargs)
        process.kind = "timeout"
        process.returncode = 1
        install_processes.append(process)
        return process

    monkeypatch.setattr(readability_module.subprocess, "Popen", failing_popen)

    readability_module._bootstrap_readability_js()
    readability_module._bootstrap_readability_js()

    assert len(install_processes) == 1, "bootstrap retried after a failed install"
    assert readability_module._readability_bootstrap_attempted is True


def test_bootstrap_tolerates_install_errors(monkeypatch, fake_readabilipy):
    def exploding_popen(argv, **kwargs):
        raise OSError("npm exploded")

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(readability_module.shutil, "which", lambda name: r"C:\Node\npm.cmd")
    monkeypatch.setattr(readability_module.subprocess, "Popen", exploding_popen)

    # Must not raise: the pure-Python fallback remains available.
    readability_module._bootstrap_readability_js()
    assert readability_module._readability_bootstrap_attempted is True


def test_probe_recovers_after_bootstrap(monkeypatch, fake_readabilipy):
    """A failed first probe must re-run once node_modules appears."""
    probe_state = {"node_modules": False}

    def fake_have_node():
        return probe_state["node_modules"]

    installed = []

    def fake_popen(argv, **kwargs):
        installed.append(argv)

        def plain_communicate(self, timeout=None):
            (fake_readabilipy / "node_modules").mkdir()
            probe_state["node_modules"] = True
            return (None, b"")

        process = FakeInstallProcess(argv, **kwargs)
        process.kind = "success"
        process.communicate = plain_communicate.__get__(process)
        return process

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(readability_module.shutil, "which", lambda name: r"C:\Node\npm.cmd")
    monkeypatch.setattr(readability_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(readability_module, "_readabilipy_have_node", fake_have_node)

    assert readability_module._readability_js_available() is True
    assert installed, "probe did not trigger the Windows npm bootstrap"


def test_bootstrap_skips_when_node_modules_present(monkeypatch, fake_readabilipy):
    (fake_readabilipy / "node_modules").mkdir()

    def fail_run(*args, **kwargs):
        raise AssertionError("npm install attempted with node_modules already present")

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(readability_module.shutil, "which", lambda name: r"C:\Node\npm.cmd")
    monkeypatch.setattr(readability_module.subprocess, "run", fail_run)

    readability_module._bootstrap_readability_js()


def test_bootstrap_skips_without_package_json(monkeypatch, fake_readabilipy):
    (fake_readabilipy / "package.json").unlink()

    def fail_run(*args, **kwargs):
        raise AssertionError("npm install attempted without a package.json")

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(readability_module.shutil, "which", lambda name: r"C:\Node\npm.cmd")
    monkeypatch.setattr(readability_module.subprocess, "run", fail_run)

    readability_module._bootstrap_readability_js()


def test_bootstrap_install_times_out(monkeypatch, fake_readabilipy, install_processes):
    install_processes, taskkills = install_processes
    """A hung npm must be killed as a tree and drained with a deadline."""
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(readability_module.shutil, "which", lambda name: r"C:\Node\npm.cmd")

    def hung_popen(argv, **kwargs):
        process = FakeInstallProcess(argv, **kwargs)
        process.kind = "timeout"
        install_processes.append(process)
        return process

    monkeypatch.setattr(readability_module.subprocess, "Popen", hung_popen)

    # TimeoutExpired subclasses SubprocessError: must be swallowed like any
    # other install failure so the pure-Python fallback remains.
    readability_module._bootstrap_readability_js()

    process = install_processes[0]
    assert process.communicate_timeouts[0] == 120, "npm install ran without the 120s cap"
    assert taskkills, "timed-out install was not killed as a process tree"
    assert taskkills[0][:2] == ["taskkill", "/PID"] and "/T" in taskkills[0] and "/F" in taskkills[0]
    # The post-kill drain must itself be bounded (surviving node.exe may hold
    # the stderr pipe open forever).
    assert process.communicate_timeouts[1] is not None and process.communicate_timeouts[1] < 120
    assert readability_module._readability_bootstrap_attempted is True


def test_bootstrap_timeout_drain_blocks(monkeypatch, fake_readabilipy, install_processes):
    install_processes, taskkills = install_processes
    """A surviving child holding stderr open must not wedge the bootstrap."""
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(readability_module.shutil, "which", lambda name: r"C:\Node\npm.cmd")

    def wedged_popen(argv, **kwargs):
        process = FakeInstallProcess(argv, **kwargs)
        process.kind = "timeout_drain_blocks"
        install_processes.append(process)
        return process

    monkeypatch.setattr(readability_module.subprocess, "Popen", wedged_popen)

    readability_module._bootstrap_readability_js()

    process = install_processes[0]
    assert len(process.communicate_timeouts) == 2, "bootstrap did not give up on the undrainable pipe"
    assert readability_module._readability_bootstrap_attempted is True
