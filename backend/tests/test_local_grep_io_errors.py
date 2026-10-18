"""Local grep must distinguish unreadable text from an absent match."""

import ctypes
import errno
import os
import socket
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.sandbox.local.local_sandbox import LocalSandbox
from deerflow.sandbox.search import find_grep_matches
from deerflow.sandbox.tools import grep_tool


@pytest.fixture
def mounted_search(tmp_path, monkeypatch):
    from deerflow.config import paths as paths_module
    from deerflow.config.sandbox_config import SandboxConfig, VolumeMountConfig
    from deerflow.sandbox.local.local_sandbox_provider import LocalSandboxProvider

    monkeypatch.setattr(paths_module, "_paths", paths_module.Paths(tmp_path / "runtime"))
    source = tmp_path / "private-host-mount"
    source.mkdir()
    target = source / "secret.txt"
    target.write_bytes(b"needle\n")
    config = SimpleNamespace(
        skills=SimpleNamespace(container_path="/mnt/skills", get_skills_path=lambda: tmp_path / "skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider", mounts=[VolumeMountConfig(host_path=str(source), container_path="/mnt/mounts/data")]),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    provider = LocalSandboxProvider()
    sandbox = provider.get(provider.acquire(None))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda _: sandbox)
    runtime = SimpleNamespace(state={"sandbox": {"sandbox_id": "local"}, "thread_data": {}}, context={"thread_id": "mounted-search"})

    def invoke(single=False):
        path = "/mnt/mounts/data" + ("/secret.txt" if single else "")
        return grep_tool.func(runtime=runtime, path=path, pattern="needle")

    return target, sandbox, invoke


@pytest.mark.parametrize("stage", ["sample", "text", "scan"])
@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO])
def test_grep_custom_mount_errors_use_virtual_paths(mounted_search, monkeypatch, stage, error_number):
    target, sandbox, invoke = mounted_search
    original_open = Path.open

    def fail_open(path, mode="r", *args, **kwargs):
        if path == target and (mode == "rb") == (stage == "sample"):
            raise OSError(error_number, "read failed", str(path))
        return original_open(path, mode, *args, **kwargs)

    def fail_walk(root, *, onerror):
        onerror(OSError(error_number, "scan failed", str(root)))
        return iter(())

    if stage == "scan":
        monkeypatch.setattr("deerflow.sandbox.search.os.walk", fail_walk)
    else:
        monkeypatch.setattr(Path, "open", fail_open)
    expected = "/mnt/mounts/data" + ("" if stage == "scan" else "/secret.txt")
    result = invoke()
    assert result.startswith("Error:"), result
    assert expected in result
    assert "private-host-mount" not in result
    with pytest.raises(OSError) as caught:
        sandbox.grep("/mnt/mounts/data", "needle")
    assert caught.value.errno == error_number
    assert caught.value.filename == expected


@pytest.mark.skipif(os.name == "nt" or not hasattr(os, "geteuid") or os.geteuid() == 0, reason="requires non-root POSIX permissions")
@pytest.mark.parametrize("single", [False, True])
def test_grep_custom_mount_real_permission_failure(mounted_search, single):
    target, _, invoke = mounted_search
    target.chmod(0)
    try:
        with pytest.raises(PermissionError):
            target.read_bytes()
        result = invoke(single)
        assert result.startswith("Error: Permission denied:"), result
        assert "/mnt/mounts/data/secret.txt" in result
        assert "private-host-mount" not in result
    finally:
        target.chmod(0o600)
    result = invoke(single)
    assert "Found 1 matches" in result
    assert "/mnt/mounts/data/secret.txt" in result
    assert "private-host-mount" not in result


@pytest.mark.parametrize("with_filenames", [False, True])
def test_grep_custom_mount_preserves_oserror_details(mounted_search, monkeypatch, with_filenames):
    target, sandbox, _ = mounted_search
    error = OSError(errno.EIO, "read failed", str(target), None, str(target.parent / "other's.txt")) if with_filenames else OSError(errno.EIO, "read failed")

    def fail_search(*args, **kwargs):
        raise error

    monkeypatch.setattr("deerflow.sandbox.local.local_sandbox.find_grep_matches", fail_search)
    with pytest.raises(OSError) as caught:
        sandbox.grep("/mnt/mounts/data", "needle")
    assert type(caught.value) is type(error)
    assert caught.value.errno == error.errno
    assert caught.value.strerror == error.strerror
    if with_filenames:
        assert caught.value.filename == "/mnt/mounts/data/secret.txt"
        assert caught.value.filename2 == "/mnt/mounts/data/other's.txt"
        assert "private-host-mount" not in str(caught.value)
    else:
        assert caught.value is error


@pytest.mark.skipif(os.name != "nt", reason="requires real Windows exclusive-share semantics")
@pytest.mark.parametrize("single", [False, True])
def test_grep_custom_mount_real_windows_sharing_failure(mounted_search, single):
    target, _, invoke = mounted_search
    with _exclusive_windows_file(target):
        result = invoke(single)
        assert result.startswith("Error: Permission denied:"), result
        assert "/mnt/mounts/data/secret.txt" in result
        assert "private-host-mount" not in result
    assert "Found 1 matches" in invoke(single)


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
    assert "/mnt/user-data/workspace/target.txt" in result
    with pytest.raises(OSError) as caught:
        find_grep_matches(target if single else target.parent, "needle")
    assert caught.value.errno == error_number


@pytest.mark.parametrize("stage", ["sample", "text"])
@pytest.mark.parametrize(
    "error_number", [errno.ENOENT, errno.ENOTDIR, errno.ELOOP, errno.EISDIR, pytest.param(getattr(errno, "ESTALE", None), marks=pytest.mark.skipif(not hasattr(errno, "ESTALE"), reason="ESTALE is unavailable on this platform"))]
)
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


@pytest.mark.skipif(os.name == "nt" or not hasattr(socket, "AF_UNIX"), reason="requires POSIX Unix-domain socket stat semantics")
@pytest.mark.parametrize("pattern, expected", [("needle", "Found 1 matches"), ("absent", "No matches found")])
def test_grep_skips_real_socket_and_searches_regular_files(search_file, monkeypatch, pattern, expected):
    target, invoke = search_file
    # Bind a short relative path to stay within Unix socket path length limits.
    monkeypatch.chdir(target.parent)
    with socket.socket(socket.AF_UNIX) as server:
        server.bind("service.sock")
        assert expected in invoke(pattern=pattern)
        matches, truncated = find_grep_matches(target.parent, pattern)
        assert [match.path for match in matches] == ([str(target)] if pattern == "needle" else [])
        assert not truncated


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


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX EISDIR from opening a directory")
@pytest.mark.parametrize("stage", ["sample", "text"])
@pytest.mark.parametrize("single", [False, True])
def test_grep_skips_real_file_replaced_by_directory(search_file, monkeypatch, stage, single):
    target, invoke = search_file
    original_open = Path.open
    replaced = False

    def replace_before_open(path, mode="r", *args, **kwargs):
        nonlocal replaced
        if path == target and not replaced and (mode == "rb") == (stage == "sample"):
            target.unlink()
            target.mkdir()
            replaced = True
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", replace_before_open)
    assert "No matches found" in invoke(single=single)
    assert replaced and target.is_dir()


@pytest.mark.parametrize(
    "error_number", [errno.ENOENT, errno.ENOTDIR, errno.ELOOP, errno.EISDIR, pytest.param(getattr(errno, "ESTALE", None), marks=pytest.mark.skipif(not hasattr(errno, "ESTALE"), reason="ESTALE is unavailable on this platform"))]
)
def test_grep_skips_disappearing_directory_scan(search_file, monkeypatch, error_number):
    target, invoke = search_file
    original_walk = os.walk

    def failed_walk(root, *, onerror=None):
        if onerror is not None:
            onerror(OSError(error_number, "directory changed during scan", str(root / "gone")))
        yield from original_walk(root)

    monkeypatch.setattr("deerflow.sandbox.search.os.walk", failed_walk)
    assert "Found 1 matches" in invoke()


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO, None])
def test_grep_reports_directory_scan_failure(search_file, monkeypatch, error_number):
    target, invoke = search_file
    original_walk = os.walk

    def failed_walk(root, *, onerror=None):
        if onerror is not None:
            onerror(OSError(error_number, "directory scan failed", str(root / "blocked")))
        yield from original_walk(root)

    monkeypatch.setattr("deerflow.sandbox.search.os.walk", failed_walk)
    result = invoke()
    assert result.startswith("Error:"), result
    assert "/mnt/user-data/workspace/blocked" in result
    assert str(target.parent) not in result
    assert "Found 1 matches" not in result


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO])
def test_grep_masks_both_os_error_filenames(search_file, monkeypatch, error_number):
    target, invoke = search_file
    original_open = Path.open

    def failing_open(path, mode="r", *args, **kwargs):
        if path == target:
            raise OSError(error_number, "read failed", str(target), None, str(target.with_name("other's.txt")))
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)
    result = invoke()
    assert "/mnt/user-data/workspace/target.txt" in result
    assert "/mnt/user-data/workspace/other's.txt" in result
    assert str(target.parent) not in result
    assert str(target.parent).replace("\\", "\\\\") not in result


def test_grep_permission_error_without_filename_keeps_requested_path(search_file, monkeypatch):
    target, invoke = search_file
    original_open = Path.open

    def failing_open(path, mode="r", *args, **kwargs):
        if path == target:
            raise PermissionError("read blocked without a filename")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)
    assert invoke() == "Error: Permission denied: /mnt/user-data/workspace"


@pytest.mark.skipif(os.name == "nt" or not hasattr(os, "geteuid") or os.geteuid() == 0, reason="requires non-root POSIX directory permissions")
@pytest.mark.parametrize("root_unreadable", [False, True])
def test_grep_reports_real_unreadable_directory(search_file, root_unreadable):
    target, invoke = search_file
    blocked = target.parent if root_unreadable else target.parent / "blocked"
    if not root_unreadable:
        blocked.mkdir()
        (blocked / "private.txt").write_text("needle\n", encoding="utf-8")
    blocked.chmod(0)
    try:
        with pytest.raises(PermissionError):
            list(blocked.iterdir())
        result = invoke()
        assert result.startswith("Error: Permission denied:"), result
        expected = "/mnt/user-data/workspace" + ("" if root_unreadable else "/blocked")
        assert expected in result
        assert str(target.parent) not in result
        assert "No matches found" not in result and "Found 1 matches" not in result
    finally:
        blocked.chmod(0o700)
    assert "Found" in invoke()


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
        result = invoke(single=single)
        assert result.startswith("Error: Permission denied:")
        assert "/mnt/user-data/workspace/target.txt" in result
        assert str(target.parent) not in result
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
        result = invoke(single=single)
        assert result.startswith("Error: Permission denied:")
        assert "/mnt/user-data/workspace/target.txt" in result
        assert str(target.parent) not in result
    finally:
        target.chmod(0o600)
    assert "Found 1 matches" in invoke(single=single)
