"""Cover the custom-skill mutation and AIO metadata Windows locks.

Both paths retry contention beyond ``LK_LOCK``'s roughly ten-second cap.
Runtime-config locking is covered separately by PR #6888; extension-config
and projection locking (including nested skill projection) belong to #6912.
This module does not claim coverage or conversion of those three paths.
"""

from __future__ import annotations

import errno
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


class _FakeMsvcrt:
    LK_UNLCK = 0
    LK_LOCK = 1
    LK_NBLCK = 2

    def __init__(self, *, failures: int = 0, error_number: int = errno.EACCES) -> None:
        self.failures = failures
        self.error_number = error_number
        self.calls: list[tuple[int, int, int]] = []

    def locking(self, fd: int, mode: int, size: int) -> None:
        self.calls.append((fd, mode, size))
        if mode == self.LK_UNLCK:
            return
        attempts = sum(call[1] != self.LK_UNLCK for call in self.calls)
        if attempts <= self.failures:
            raise OSError(self.error_number, "Lock unavailable")


def _patch_windows_lock(module, monkeypatch: pytest.MonkeyPatch, fake: _FakeMsvcrt) -> None:
    monkeypatch.setattr(module, "fcntl", None)
    monkeypatch.setattr(module, "msvcrt", fake, raising=False)
    real_retry = module.retry_until_locked

    def retry(acquire, **kwargs):
        return real_retry(acquire, sleep=lambda _: None, **kwargs)

    monkeypatch.setattr(module, "retry_until_locked", retry)


def _exercise_lock(module_name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: _FakeMsvcrt) -> Path:
    """Acquire one of the two scoped locks and return its sidecar path."""
    import importlib

    module = importlib.import_module(module_name)
    _patch_windows_lock(module, monkeypatch, fake)

    if module_name.endswith("routers.skills"):
        custom_root = tmp_path / "custom"
        storage = SimpleNamespace(get_user_custom_root=lambda: custom_root)
        with module._custom_skill_mutation(storage):
            pass
        return custom_root.parent / f".{custom_root.name}.mutation.lock"

    if module_name.endswith("aio_sandbox_provider"):
        lock_path = tmp_path / "sandbox.lock"
        with lock_path.open("a", encoding="utf-8") as lock_file:
            module._lock_file_exclusive(lock_file)
            module._unlock_file(lock_file)
        return lock_path

    raise AssertionError(f"unhandled lock module: {module_name}")


LOCK_MODULES = (
    "app.gateway.routers.skills",
    "deerflow.community.aio_sandbox.aio_sandbox_provider",
)


@pytest.mark.parametrize("module_name", LOCK_MODULES)
def test_remaining_windows_locks_retry_contention(
    module_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeMsvcrt(failures=3)

    sidecar = _exercise_lock(module_name, tmp_path, monkeypatch, fake)

    assert [mode for _, mode, _ in fake.calls] == [fake.LK_NBLCK] * 4 + [fake.LK_UNLCK]
    assert [size for _, _, size in fake.calls] == [1] * 5
    assert sidecar.read_bytes()[:1] == b"\0"


@pytest.mark.parametrize("module_name", LOCK_MODULES)
def test_remaining_windows_locks_propagate_permanent_errors(
    module_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    module = importlib.import_module(module_name)
    fake = _FakeMsvcrt(failures=1, error_number=errno.EBADF)
    _patch_windows_lock(module, monkeypatch, fake)

    def acquire_once() -> None:
        if module_name.endswith("routers.skills"):
            root = tmp_path / "custom"
            storage = SimpleNamespace(get_user_custom_root=lambda: root)
            with module._custom_skill_mutation(storage):
                pytest.fail("permanent lock errors must not enter the critical section")
        else:
            lock_path = tmp_path / "sandbox.lock"
            with lock_path.open("a", encoding="utf-8") as lock_file:
                module._lock_file_exclusive(lock_file)

    with pytest.raises(OSError) as caught:
        acquire_once()

    assert caught.value.errno == errno.EBADF
    assert [mode for _, mode, _ in fake.calls] == [fake.LK_NBLCK]


@pytest.mark.parametrize("module_name", LOCK_MODULES)
def test_remaining_windows_locks_never_call_blocking_mode(
    module_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeMsvcrt()
    _exercise_lock(module_name, tmp_path, monkeypatch, fake)

    assert all(mode != fake.LK_LOCK for _, mode, _ in fake.calls)


_NATIVE_WORKER = """
import importlib
import msvcrt
import sys
import time
from pathlib import Path
from types import SimpleNamespace

mode, module_name, target, signals = sys.argv[1:]
target, signals = Path(target), Path(signals)
if mode == "holder":
    with target.open("a+b") as stream:
        stream.write(b"\\0")
        stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            (signals / "ready").touch()
            while not (signals / "release").exists():
                time.sleep(0.02)
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
else:
    module = importlib.import_module(module_name)
    (signals / "attempting").touch()
    if module_name.endswith("routers.skills"):
        storage = SimpleNamespace(get_user_custom_root=lambda: target)
        with module._custom_skill_mutation(storage):
            (signals / "acquired").touch()
    else:
        with target.open("a", encoding="utf-8") as stream:
            module._lock_file_exclusive(stream)
            try:
                (signals / "acquired").touch()
            finally:
                module._unlock_file(stream)
"""


def _await_signal(path: Path, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 30
    while not path.exists():
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            pytest.fail(f"lock worker exited before {path.name}: {stdout}\n{stderr}")
        if time.monotonic() >= deadline:
            pytest.fail(f"lock worker did not signal {path.name}")
        time.sleep(0.02)


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows byte-range locks")
@pytest.mark.parametrize("module_name", LOCK_MODULES)
def test_native_windows_lock_waits_beyond_blocking_retry_limit(module_name: str, tmp_path: Path) -> None:
    """A real peer holds the byte beyond LK_LOCK's limit, then releases it."""
    target = tmp_path / ("custom" if module_name.endswith("routers.skills") else "sandbox.lock")
    sidecar = tmp_path / ".custom.mutation.lock" if module_name.endswith("routers.skills") else target
    backend = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(backend), str(backend / "packages" / "harness"), env.get("PYTHONPATH", "")))
    processes: list[subprocess.Popen[str]] = []
    try:
        for mode, path, signal in (("holder", sidecar, "ready"), ("contender", target, "attempting")):
            process = subprocess.Popen(
                [sys.executable, "-c", _NATIVE_WORKER, mode, module_name, str(path), str(tmp_path)],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            processes.append(process)
            _await_signal(tmp_path / signal, process)

        contender = processes[1]
        with pytest.raises(subprocess.TimeoutExpired):
            contender.wait(timeout=12)
        assert not (tmp_path / "acquired").exists()
        (tmp_path / "release").touch()

        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            assert process.returncode == 0, f"{stdout}\n{stderr}"
        assert (tmp_path / "acquired").exists()
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
