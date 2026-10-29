"""Local file revisions retain the last complete version on publication failure."""

from __future__ import annotations

import errno
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from deerflow.sandbox.local import local_sandbox as local
from deerflow.utils import atomic_write, file_revision_metadata

requires_atomic_revision = pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="Atomic revisions are scoped to Linux/macOS")


@pytest.fixture
def sandbox(tmp_path):
    return local.LocalSandbox("local:atomic-write", [local.PathMapping("/mnt/user-data/outputs", str(tmp_path))])


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("stage", ["write", "flush", "fsync", "replace"])
@requires_atomic_revision
def test_failed_save_keeps_previous_file_and_cleans_staging(tmp_path, monkeypatch, sandbox, existing, stage):
    target = tmp_path / "report.md"
    if existing:
        target.write_bytes(b"previous report\n")
    real_open = open
    real_fdopen = os.fdopen

    def fail(*args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    class FailingWriter:
        def __init__(self, handle):
            self.handle = handle

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            try:
                if args[0] is None and stage == "flush":
                    self.flush()
            finally:
                self.handle.close()

        def write(self, content):
            if stage == "write":
                self.handle.write(content[:3])
                self.handle.flush()
                fail()
            return self.handle.write(content)

        def flush(self):
            self.handle.flush()
            if stage == "flush":
                fail()

    def wrapped_open(path, mode="r", **kwargs):
        handle = real_open(path, mode, **kwargs)
        return FailingWriter(handle) if "w" in mode else handle

    monkeypatch.setattr(local, "open", wrapped_open, raising=False)
    monkeypatch.setattr(os, "fdopen", lambda *args, **kwargs: FailingWriter(real_fdopen(*args, **kwargs)))
    if stage in {"fsync", "replace"}:
        monkeypatch.setattr(os, stage, fail)

    with pytest.raises(OSError) as error:
        sandbox.write_file("/mnt/user-data/outputs/report.md", "replacement report\n")

    assert error.value.errno == errno.ENOSPC
    assert error.value.filename == "/mnt/user-data/outputs/report.md"
    if existing:
        assert target.read_bytes() == b"previous report\n"
    else:
        assert not target.exists()
    assert set(tmp_path.iterdir()) == ({target} if existing else set())
    assert not sandbox._agent_written_paths


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("content", ["", "first\r\nsecond\r\n", "path=/mnt/user-data/outputs/data.csv\n"])
def test_successful_save_preserves_bytes_verbatim(tmp_path, sandbox, existing, content):
    target = tmp_path / "report.md"
    if existing:
        target.write_bytes(b"previous report\n")

    sandbox.write_file("/mnt/user-data/outputs/report.md", content)

    # Markdown is a document, so write_file stores it verbatim: container-path
    # translation is limited to executable content (see
    # test_local_sandbox_content_path_translation.py).
    assert target.read_bytes() == content.encode("utf-8")
    assert sandbox.read_file("/mnt/user-data/outputs/report.md") == content
    assert list(tmp_path.iterdir()) == [target]


@requires_atomic_revision
@pytest.mark.parametrize("content", ["", "new\n", "n" * (256 * 1024 + 1)], ids=["empty", "nonempty", "large-same-size"])
def test_revision_updates_modification_time(tmp_path, sandbox, content):
    target = tmp_path / "report.md"
    target.write_bytes(b"o" * max(4, len(content)))
    old_time = 946684800_000000000
    os.utime(target, ns=(old_time, old_time))

    sandbox.write_file("/mnt/user-data/outputs/report.md", content)

    assert target.stat().st_mtime_ns > old_time
    assert target.read_bytes() == content.encode("utf-8")
    assert list(tmp_path.iterdir()) == [target]


@requires_atomic_revision
@pytest.mark.parametrize("outcome", ["success", "write-error", "interrupted"])
@pytest.mark.parametrize("broken_logging", [False, True])
def test_source_close_error_preserves_publication_outcome(tmp_path, monkeypatch, outcome, broken_logging):
    target = tmp_path / "report.md"
    target.write_bytes(b"old\n")
    before = target.stat()
    real_close = os.close
    closed = []
    primary = KeyboardInterrupt("interrupted publication") if outcome == "interrupted" else OSError(errno.ENOSPC, "No space left on device")

    def close(fd):
        source = os.fstat(fd).st_ino == before.st_ino
        real_close(fd)
        if source:
            closed.append(fd)
            raise OSError(errno.EIO, "Source descriptor close failed")

    def fail_fsync(fd):
        raise primary

    warning = Mock(side_effect=RuntimeError("broken log handler") if broken_logging else None)
    monkeypatch.setattr(local.logger, "warning", warning)
    monkeypatch.setattr(os, "close", close)
    if outcome != "success":
        monkeypatch.setattr(os, "fsync", fail_fsync)

    if outcome == "success":
        local._publish_file_revision(str(target), "new\n")
    else:
        with pytest.raises(type(primary)) as error:
            local._publish_file_revision(str(target), "new\n")
        assert error.value is primary

    assert len(closed) == 1
    assert target.read_bytes() == (b"new\n" if outcome == "success" else b"old\n")
    assert list(tmp_path.iterdir()) == [target]
    warning.assert_called_once()
    assert warning.call_args.args[1] == target
    assert warning.call_args.kwargs["exc_info"] is True


def test_append_keeps_existing_inode_and_content(tmp_path, sandbox):
    target = tmp_path / "report.md"
    target.write_bytes(b"first\r\n")
    before = target.stat().st_ino
    sandbox.write_file("/mnt/user-data/outputs/report.md", "second\r\n", append=True)
    assert target.read_bytes() == b"first\r\nsecond\r\n"
    assert target.stat().st_ino == before
    assert list(tmp_path.iterdir()) == [target]


@requires_atomic_revision
def test_replacement_is_published_only_after_all_bytes_are_written(tmp_path, monkeypatch, sandbox):
    target = tmp_path / "report.md"
    target.write_bytes(b"old\n")
    replace = os.replace
    publications = []

    def observe(source, destination):
        assert target.read_bytes() == b"old\n"
        assert Path(source).read_bytes() == b"new\r\n"
        assert Path(source).parent == target.parent
        assert destination == target
        publications.append(destination)
        replace(source, destination)

    monkeypatch.setattr(os, "replace", observe)
    sandbox.write_file("/mnt/user-data/outputs/report.md", "new\r\n")
    assert publications == [target]
    assert target.read_bytes() == b"new\r\n"


def test_new_file_keeps_normal_creation_permissions(tmp_path, sandbox):
    reference = tmp_path / "reference.txt"
    reference.write_bytes(b"reference")
    sandbox.write_file("/mnt/user-data/outputs/report.md", "new\n")
    assert stat.S_IMODE((tmp_path / "report.md").stat().st_mode) == stat.S_IMODE(reference.stat().st_mode)


def test_directory_target_is_not_replaced(tmp_path, sandbox):
    target = tmp_path / "report.md"
    target.mkdir()
    with pytest.raises(OSError):
        sandbox.write_file("/mnt/user-data/outputs/report.md", "new\n")
    assert target.is_dir()
    assert list(tmp_path.iterdir()) == [target]


@requires_atomic_revision
def test_hard_link_alias_retains_previous_version(tmp_path, sandbox):
    target = tmp_path / "report.md"
    target.write_bytes(b"old\n")
    alias = tmp_path / "previous.md"
    os.link(target, alias)
    sandbox.write_file("/mnt/user-data/outputs/report.md", "new\n")
    assert target.read_bytes() == b"new\n"
    assert alias.read_bytes() == b"old\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory permissions")
def test_unwritable_parent_fails_without_destroying_previous_file(tmp_path, sandbox):
    target = tmp_path / "report.md"
    target.write_bytes(b"old\n")
    mode = stat.S_IMODE(tmp_path.stat().st_mode)
    tmp_path.chmod(0o555)
    try:
        if os.access(tmp_path, os.W_OK):
            pytest.skip("current user can write read-only directories")
        with pytest.raises(PermissionError):
            sandbox.write_file("/mnt/user-data/outputs/report.md", "new\n")
        assert target.read_bytes() == b"old\n"
    finally:
        tmp_path.chmod(mode)


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_overwrite_preserves_permission_bits(tmp_path, sandbox):
    target = tmp_path / "run.sh"
    target.write_bytes(b"old\n")
    target.chmod(0o750)
    sandbox.write_file("/mnt/user-data/outputs/run.sh", "new\n")
    assert target.read_bytes() == b"new\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o750


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_read_only_target_is_not_bypassed_by_writable_parent(tmp_path, sandbox):
    target = tmp_path / "report.md"
    target.write_bytes(b"old\n")
    target.chmod(0o444)
    try:
        if os.access(target, os.W_OK):
            pytest.skip("current user can write read-only files")
        with pytest.raises(PermissionError):
            sandbox.write_file("/mnt/user-data/outputs/report.md", "new\n")
        assert target.read_bytes() == b"old\n"
        assert list(tmp_path.iterdir()) == [target]
    finally:
        target.chmod(0o644)


def test_read_only_mapping_is_still_rejected(tmp_path):
    target = tmp_path / "report.md"
    target.write_bytes(b"old\n")
    sandbox = local.LocalSandbox("local:readonly", [local.PathMapping("/mnt/user-data/outputs", str(tmp_path), read_only=True)])
    with pytest.raises(OSError) as error:
        sandbox.write_file("/mnt/user-data/outputs/report.md", "new\n")
    assert error.value.errno == errno.EROFS
    assert target.read_bytes() == b"old\n"


@pytest.mark.parametrize("mapped", [False, True])
def test_symlink_write_updates_target_not_link(tmp_path, sandbox, mapped):
    from support.symlinks import symlink_or_skip

    target = tmp_path / "report.md"
    target.write_bytes(b"old\n")
    alias = tmp_path / "alias.md"
    symlink_or_skip(alias, target)
    path = "/mnt/user-data/outputs/alias.md" if mapped else str(alias)
    sandbox.write_file(path, "new\n")
    assert alias.is_symlink()
    assert target.read_bytes() == b"new\n"
    assert alias.read_bytes() == b"new\n"


def test_max_length_filename_can_be_overwritten(tmp_path, sandbox):
    name = "r" * 240 + ".md"
    target = tmp_path / name
    target.write_bytes(b"old\n")
    sandbox.write_file(f"/mnt/user-data/outputs/{name}", "new\n")
    assert target.read_bytes() == b"new\n"
    assert list(tmp_path.iterdir()) == [target]


def _darwin_acl_bytes(path):
    """Compare native ACL data without DirectoryService's display-name lookup."""
    import ctypes

    library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    signatures = {
        "acl_get_file": ([ctypes.c_char_p, ctypes.c_int], ctypes.c_void_p),
        "acl_size": ([ctypes.c_void_p], ctypes.c_ssize_t),
        "acl_copy_ext": ([ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ssize_t], ctypes.c_ssize_t),
        "acl_free": ([ctypes.c_void_p], ctypes.c_int),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(library, name)
        function.argtypes = arguments
        function.restype = result
    acl = library.acl_get_file(os.fsencode(path), 0x100)
    if not acl:
        assert ctypes.get_errno() == errno.ENOENT
        return b""
    try:
        size = library.acl_size(acl)
        assert size > 0
        buffer = ctypes.create_string_buffer(size)
        written = library.acl_copy_ext(buffer, acl, size)
        assert written == size
        return buffer.raw
    finally:
        assert library.acl_free(acl) == 0


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS extended ACL regression")
def test_overwrite_preserves_existing_extended_acl(tmp_path, sandbox):
    target = tmp_path / "report.md"
    target.write_bytes(b"old\n")
    empty = _darwin_acl_bytes(target)
    subprocess.run(["chmod", "+a", "nobody deny read", str(target)], check=True, capture_output=True)
    before = _darwin_acl_bytes(target)
    assert before != empty, "The fixture must install an actual ACL"

    sandbox.write_file("/mnt/user-data/outputs/report.md", "new\n")

    after = _darwin_acl_bytes(target)
    assert after == before
    assert target.read_bytes() == b"new\n"

    # Keep the comparison sensitive to both lost and changed permissions.
    subprocess.run(["chmod", "-N", str(target)], check=True, capture_output=True)
    assert _darwin_acl_bytes(target) == empty
    subprocess.run(["chmod", "+a", "nobody deny write", str(target)], check=True, capture_output=True)
    assert _darwin_acl_bytes(target) != before


@requires_atomic_revision
def test_existing_private_file_is_staged_privately(tmp_path, sandbox, monkeypatch):
    target = tmp_path / "report.md"
    target.write_bytes(b"private old report\n")
    target.chmod(0o600)
    fdopen = os.fdopen
    observed = []

    def inspect(fd, *args, **kwargs):
        mode = stat.S_IMODE(os.fstat(fd).st_mode)
        observed.append(mode)
        assert mode == 0o600
        return fdopen(fd, *args, **kwargs)

    monkeypatch.setattr(os, "fdopen", inspect)
    sandbox.write_file("/mnt/user-data/outputs/report.md", "private new report\n")
    assert observed == [0o600]


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS inherited ACL regression")
def test_replacement_does_not_inherit_new_access_grants(tmp_path, sandbox):
    target = tmp_path / "report.md"
    target.write_bytes(b"private old report\n")
    target.chmod(0o600)
    subprocess.run(["chmod", "+a", "nobody allow read,file_inherit", str(tmp_path)], check=True, capture_output=True)
    try:
        sandbox.write_file("/mnt/user-data/outputs/report.md", "private new report\n")
        acl = subprocess.check_output(["ls", "-le", str(target)], text=True).splitlines()[1:]
        assert acl == []
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    finally:
        subprocess.run(["chmod", "-N", str(tmp_path)], check=True, capture_output=True)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS extended attributes")
def test_overwrite_preserves_extended_attributes(tmp_path, sandbox):
    target = tmp_path / "report.md"
    target.write_bytes(b"old\n")
    subprocess.run(["xattr", "-w", "user.deerflow-test", "retain-me", str(target)], check=True, capture_output=True)
    sandbox.write_file("/mnt/user-data/outputs/report.md", "new\n")
    attribute = subprocess.check_output(["xattr", "-p", "user.deerflow-test", str(target)], text=True)
    assert attribute.strip() == "retain-me"


@requires_atomic_revision
def test_metadata_failure_leaves_previous_file_untouched(tmp_path, sandbox, monkeypatch):
    target = tmp_path / "report.md"
    target.write_bytes(b"old\n")
    before = target.stat()

    def fail(source, destination):
        assert os.fstat(source).st_ino == before.st_ino
        assert os.fstat(destination).st_size == 0
        raise PermissionError(errno.EACCES, "Cannot preserve file permissions")

    monkeypatch.setattr(atomic_write, "preserve_revision_metadata", fail)
    with pytest.raises(PermissionError):
        sandbox.write_file("/mnt/user-data/outputs/report.md", "new\n")
    assert target.read_bytes() == b"old\n"
    assert target.stat().st_ino == before.st_ino
    assert list(tmp_path.iterdir()) == [target]


@requires_atomic_revision
def test_metadata_is_installed_before_staging_content(tmp_path, sandbox, monkeypatch):
    target = tmp_path / "report.md"
    target.write_bytes(b"old\n")
    target.chmod(0o640)
    prepare = atomic_write.preserve_revision_metadata
    called = []

    def observe(source, destination):
        assert os.fstat(destination).st_size == 0
        prepare(source, destination)
        assert stat.S_IMODE(os.fstat(destination).st_mode) == 0o640
        called.append(destination)

    monkeypatch.setattr(atomic_write, "preserve_revision_metadata", observe)
    sandbox.write_file("/mnt/user-data/outputs/report.md", "new\n")
    assert len(called) == 1
    assert target.read_bytes() == b"new\n"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS explicit deny-write ACL")
def test_target_acl_write_denial_is_not_bypassed(tmp_path, sandbox):
    import pwd

    target = tmp_path / "report.md"
    target.write_bytes(b"old\n")
    user = pwd.getpwuid(os.getuid()).pw_name
    subprocess.run(["chmod", "+a", f"{user} deny write", str(target)], check=True, capture_output=True)
    try:
        with pytest.raises(PermissionError):
            sandbox.write_file("/mnt/user-data/outputs/report.md", "new\n")
        assert target.read_bytes() == b"old\n"
        assert list(tmp_path.iterdir()) == [target]
    finally:
        subprocess.run(["chmod", "-N", str(target)], check=True, capture_output=True)


@pytest.mark.skipif(sys.platform != "linux", reason="Native Linux xattr and POSIX ACL contract")
def test_linux_overwrite_preserves_acl_and_attributes(tmp_path, sandbox):
    import struct

    target = tmp_path / "report.md"
    target.write_bytes(b"old\n")
    # Linux posix_acl_xattr_header(version=2), followed by tag/perm/id entries.
    entries = [(1, 6, 0xFFFFFFFF), (2, 0, 65534), (4, 0, 0xFFFFFFFF), (16, 4, 0xFFFFFFFF), (32, 0, 0xFFFFFFFF)]
    acl = struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *entry) for entry in entries)
    os.setxattr(target, "system.posix_acl_access", acl)
    os.setxattr(target, "user.deerflow-test", b"retain-me")
    before = {name: os.getxattr(target, name) for name in os.listxattr(target)}
    sandbox.write_file("/mnt/user-data/outputs/report.md", "new\n")
    assert {name: os.getxattr(target, name) for name in os.listxattr(target)} == before
    assert target.read_bytes() == b"new\n"


def test_other_hosts_keep_existing_in_place_behavior(tmp_path, sandbox, monkeypatch):
    from types import SimpleNamespace

    target = tmp_path / "report.md"
    target.write_bytes(b"old\n")
    before = target.stat().st_ino
    monkeypatch.setattr(local, "sys", SimpleNamespace(platform="other"))
    sandbox.write_file("/mnt/user-data/outputs/report.md", "new\n")
    assert target.stat().st_ino == before
    assert target.read_bytes() == b"new\n"


@requires_atomic_revision
def test_privileged_file_is_not_republished_with_stale_privileges(tmp_path, sandbox):
    target = tmp_path / "run.sh"
    target.write_bytes(b"old\n")
    target.chmod(0o4750)
    try:
        with pytest.raises(OSError) as error:
            sandbox.write_file("/mnt/user-data/outputs/run.sh", "new\n")
        assert error.value.errno == errno.ENOTSUP
        assert target.read_bytes() == b"old\n"
        assert stat.S_IMODE(target.stat().st_mode) == 0o4750
        assert list(tmp_path.iterdir()) == [target]
    finally:
        target.chmod(0o600)


def test_linux_metadata_copy_replaces_inherited_attributes(monkeypatch):
    from types import SimpleNamespace

    attributes = {1: {"system.posix_acl_access": b"source-acl", "user.tag": b"tag"}, 2: {"user.inherited": b"unexpected"}}
    monkeypatch.setattr(
        file_revision_metadata,
        "os",
        SimpleNamespace(
            listxattr=lambda fd: list(attributes[fd]),
            getxattr=lambda fd, name: attributes[fd][name],
            setxattr=lambda fd, name, value: attributes[fd].__setitem__(name, value),
            removexattr=lambda fd, name: attributes[fd].pop(name),
        ),
    )
    file_revision_metadata._copy_linux_metadata(1, 2)
    assert attributes[2] == attributes[1]


def test_linux_metadata_error_is_not_ignored(monkeypatch):
    from types import SimpleNamespace

    def fail(fd):
        raise PermissionError(errno.EACCES, "Metadata unavailable")

    monkeypatch.setattr(file_revision_metadata, "os", SimpleNamespace(listxattr=fail))
    with pytest.raises(PermissionError):
        file_revision_metadata._copy_linux_metadata(1, 2)


@pytest.mark.parametrize("attribute", ["security.capability", "security.ima", "security.evm"])
def test_linux_content_bound_privileges_are_not_copied(monkeypatch, attribute):
    from types import SimpleNamespace

    monkeypatch.setattr(file_revision_metadata, "os", SimpleNamespace(listxattr=lambda fd: [attribute]))
    with pytest.raises(OSError) as error:
        file_revision_metadata._copy_linux_metadata(1, 2)
    assert error.value.errno == errno.ENOTSUP


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS metadata API error handling")
@pytest.mark.parametrize("stage", ["read_acl", "empty_acl", "set_acl", "xattr"])
def test_native_metadata_errors_abort_publication(tmp_path, sandbox, monkeypatch, stage):
    import ctypes
    from types import SimpleNamespace

    target = tmp_path / "report.md"
    target.write_bytes(b"old\n")
    freed = []

    def get_acl(*args):
        if stage in {"read_acl", "empty_acl"}:
            ctypes.set_errno(errno.EACCES if stage == "read_acl" else errno.ENOENT)
            return None
        return 1

    def empty_acl(*args):
        ctypes.set_errno(errno.ENOMEM)
        return None

    def set_acl(*args):
        ctypes.set_errno(errno.EACCES)
        return -1 if stage == "set_acl" else 0

    def copy_xattrs(*args):
        ctypes.set_errno(errno.EACCES)
        return -1

    library = SimpleNamespace(acl_get_fd_np=get_acl, acl_init=empty_acl, acl_set_fd_np=set_acl, acl_free=freed.append, fcopyfile=copy_xattrs)
    monkeypatch.setattr(file_revision_metadata, "_darwin_library", lambda: library)
    with pytest.raises(OSError) as error:
        sandbox.write_file("/mnt/user-data/outputs/report.md", "new\n")
    assert error.value.errno == (errno.ENOMEM if stage == "empty_acl" else errno.EACCES)
    assert target.read_bytes() == b"old\n"
    assert list(tmp_path.iterdir()) == [target]
    assert freed == ([1] if stage in {"set_acl", "xattr"} else [])


@requires_atomic_revision
def test_failure_to_preserve_owner_aborts_publication(tmp_path, sandbox, monkeypatch):
    from types import SimpleNamespace

    target = tmp_path / "report.md"
    target.write_bytes(b"old\n")
    before = target.stat()

    def fstat(fd):
        st = os.fstat(fd)
        if st.st_ino != before.st_ino:
            return st
        return SimpleNamespace(st_mode=st.st_mode, st_uid=st.st_uid + 1, st_gid=st.st_gid, st_dev=st.st_dev, st_flags=0)

    def fchown(fd, uid, gid):
        raise PermissionError(errno.EPERM, "Cannot preserve ownership")

    monkeypatch.setattr(file_revision_metadata, "os", SimpleNamespace(fstat=fstat, fchown=fchown))
    with pytest.raises(PermissionError):
        sandbox.write_file("/mnt/user-data/outputs/report.md", "new\n")
    assert target.read_bytes() == b"old\n"
    assert target.stat().st_uid == before.st_uid
    assert list(tmp_path.iterdir()) == [target]


_KERNEL_PROBE = r"""
import json
import resource
import signal
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from deerflow.sandbox import tools
from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping

root = Path(sys.argv[1])
entry = sys.argv[2]
limited = sys.argv[3] == "limited"
target = root / "outputs" / "report.md"
target.parent.mkdir()
target.write_bytes(b"previous report\n")
sandbox = LocalSandbox("local:atomic-write", [PathMapping("/mnt/user-data", str(root))])
runtime = SimpleNamespace(state={
    "sandbox": {"sandbox_id": sandbox.id},
    "thread_data": {f"{kind}_path": str(root / kind) for kind in ("workspace", "uploads", "outputs")},
}, context={}, config={})
path = "/mnt/user-data/outputs/report.md"
content = "new report\n" * 1000
with patch.object(tools, "ensure_sandbox_initialized", return_value=sandbox), patch.object(tools, "_get_custom_mounts", return_value=[]):
    assert tools.read_file_tool.func(runtime=runtime, path=path) == "previous report\n"
    if limited:
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024, 1024))
    if entry == "write_file":
        result = tools.write_file_tool.func(runtime=runtime, path=path, content=content)
    else:
        result = tools.str_replace_tool.func(runtime=runtime, path=path, old_str="previous report\n", new_str=content)
print(json.dumps({"result": result, "content": target.read_text(encoding="utf-8"), "files": sorted(p.name for p in target.parent.iterdir())}))
"""


@requires_atomic_revision
@pytest.mark.parametrize("entry", ["write_file", "str_replace"])
@pytest.mark.parametrize("limited", [False, True], ids=["control", "kernel-write-failure"])
def test_real_tool_entry_preserves_previous_file_on_kernel_failure(tmp_path, entry, limited):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, "-c", _KERNEL_PROBE, str(tmp_path), entry, "limited" if limited else "unlimited"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    outcome = json.loads(result.stdout.strip().splitlines()[-1])
    if limited:
        assert "File too large" in outcome["result"]
        assert outcome["content"] == "previous report\n"
    else:
        assert outcome["result"] == "OK"
        assert outcome["content"] == "new report\n" * 1000
    assert outcome["files"] == ["report.md"]
