"""Local grep must distinguish unreadable text from an absent match."""

import ctypes
import errno
import os
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.sandbox.local.local_sandbox import LocalSandbox
from deerflow.sandbox.search import find_grep_matches
from deerflow.sandbox.tools import grep_tool


@pytest.fixture
def search_file(tmp_path, monkeypatch):
    for name in ("workspace", "uploads", "outputs"):
        (tmp_path / name).mkdir()
    target = tmp_path / "workspace" / "target.txt"
    target.write_bytes(b"needle\n")
    runtime = SimpleNamespace(
        state={
            "sandbox": {"sandbox_id": "local"},
            "thread_data": {f"{name}_path": str(tmp_path / name) for name in ("workspace", "uploads", "outputs")},
        },
        context={"thread_id": "search-io"},
    )
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda _: LocalSandbox(id="local"))

    def invoke(*, single=False, pattern="needle", **kwargs):
        path = "/mnt/user-data/workspace/target.txt" if single else "/mnt/user-data/workspace"
        return grep_tool.func(runtime=runtime, path=path, pattern=pattern, **kwargs)

    return target, invoke


@pytest.mark.parametrize("stage", ["sample", "text"])
@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO])
@pytest.mark.parametrize("single", [False, True])
def test_grep_reports_file_io_failure(search_file, monkeypatch, stage, error_number, single):
    target, invoke = search_file
    original_open = Path.open

    def failing_open(path, mode="r", *args, **kwargs):
        if path == target and (mode == "rb") == (stage == "sample"):
            raise OSError(error_number, "search read failed", str(path))
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)
    result = invoke(single=single)
    assert result.startswith("Error:"), result
    assert "No matches found" not in result
    assert str(target.parent) not in result
    with pytest.raises(OSError) as caught:
        find_grep_matches(target if single else target.parent, "needle")
    assert caught.value.errno == error_number


@pytest.mark.parametrize("stage", ["sample", "text"])
@pytest.mark.parametrize("error_number", [errno.ENOENT, errno.ENOTDIR, errno.ELOOP])
@pytest.mark.parametrize("single", [False, True])
def test_grep_keeps_disappearing_candidate_best_effort(search_file, monkeypatch, stage, error_number, single):
    target, invoke = search_file
    original_open = Path.open

    def vanished_open(path, mode="r", *args, **kwargs):
        if path == target and (mode == "rb") == (stage == "sample"):
            raise OSError(error_number, "candidate vanished after enumeration", str(path))
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", vanished_open)
    assert "No matches found" in invoke(single=single)


@pytest.mark.parametrize("single", [False, True])
def test_grep_readable_and_no_match_controls(search_file, single):
    _, invoke = search_file
    assert "Found 1 matches" in invoke(single=single)
    assert "No matches found" in invoke(single=single, pattern="absent")


def test_grep_still_excludes_binary_and_glob_filtered_files(search_file):
    target, invoke = search_file
    target.write_bytes(b"\x00needle")
    assert "No matches found" in invoke()
    target.write_bytes(b"needle\n")
    assert "No matches found" in invoke(glob="*.py")


def test_grep_does_not_publish_partial_hits_after_read_error(search_file, monkeypatch):
    target, invoke = search_file
    original_open = Path.open

    @contextmanager
    def failing_read(path, mode="r", *args, **kwargs):
        with original_open(path, mode, *args, **kwargs) as handle:
            if path != target or mode == "rb":
                yield handle
                return

            def lines():
                yield next(handle)
                raise OSError(errno.EIO, "read failed after a matching line", str(path))

            yield lines()

    monkeypatch.setattr(Path, "open", failing_read)
    result = invoke()
    assert result.startswith("Error:"), result
    assert "Found 1 matches" not in result


@contextmanager
def _exclusive_windows_file(path):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = create(str(path), 0x80000000, 0, None, 3, 0x80, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        assert close(handle)


@pytest.mark.skipif(os.name != "nt", reason="requires real Windows exclusive-share semantics")
@pytest.mark.parametrize("single", [False, True])
def test_grep_reports_real_windows_sharing_failure(search_file, single):
    target, invoke = search_file
    with _exclusive_windows_file(target):
        with pytest.raises(PermissionError):
            target.read_bytes()
        assert invoke(single=single).startswith("Error: Permission denied:")
        assert "No matches found" in invoke(glob="*.py")
    assert "Found 1 matches" in invoke(single=single)


@pytest.mark.skipif(os.name == "nt" or not hasattr(os, "geteuid") or os.geteuid() == 0, reason="requires non-root POSIX permissions")
@pytest.mark.parametrize("single", [False, True])
def test_grep_reports_real_posix_read_failure(search_file, single):
    target, invoke = search_file
    target.chmod(0)
    try:
        with pytest.raises(PermissionError):
            target.read_bytes()
        assert invoke(single=single).startswith("Error: Permission denied:")
    finally:
        target.chmod(0o600)
    assert "Found 1 matches" in invoke(single=single)
