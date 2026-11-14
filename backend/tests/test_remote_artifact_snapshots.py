"""Execute the remote snapshot protocol against real POSIX files, offline."""

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
from deerflow_extension_api import AgentRunError

from app.gateway.extension_artifacts import MAX_BYTES

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Descriptor-confined snapshots require POSIX")


@pytest.fixture
def remote(tmp_path):
    root = tmp_path / "remote"
    root.mkdir()

    def command(script, **kwargs):
        # The transport is replaced, not the script executed in the sandbox.
        result = subprocess.run(script.replace("python3 ", sys.executable + " ", 1), shell=True, capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        return result.stdout

    return SimpleNamespace(artifact_root=str(root), execute_command=command)


@pytest.mark.parametrize("replacement", ["edit", "symlink", "directory", "hardlink"])
def test_remote_publication_reuses_exact_bytes_and_preserves_changed_destinations(remote, tmp_path, replacement):
    from deerflow.sandbox.artifact_snapshot import publish_snapshot

    content = b"\x00\xff" * 40000
    name = 'report-"文件.bin'
    publish_snapshot(remote, name, content)
    publish_snapshot(remote, name, content)
    target = tmp_path / "remote/uploads" / name
    assert target.read_bytes() == content
    unrelated = tmp_path / "unrelated"
    unrelated.write_bytes(b"private")
    target.unlink()
    if replacement == "edit":
        target.write_bytes(b"recipient edit")
    elif replacement == "symlink":
        target.symlink_to(unrelated)
    elif replacement == "directory":
        target.mkdir()
    else:
        import os

        os.link(unrelated, target)
    with pytest.raises(AgentRunError):
        publish_snapshot(remote, name, content)
    assert unrelated.read_bytes() == b"private"
    if replacement == "edit":
        assert target.read_bytes() == b"recipient edit"
    assert not list(target.parent.glob(".artifact-*.part"))


def test_remote_snapshots_reject_parent_symlinks(remote, tmp_path):
    from deerflow.sandbox.artifact_snapshot import publish_snapshot, read_snapshot

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "report.txt").write_bytes(b"private")
    (tmp_path / "remote/uploads").symlink_to(outside, target_is_directory=True)
    (tmp_path / "remote/outputs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(AgentRunError):
        publish_snapshot(remote, "report.txt", b"replacement")
    with pytest.raises(AgentRunError):
        read_snapshot(remote, "report.txt")
    assert (outside / "report.txt").read_bytes() == b"private"


@pytest.mark.parametrize("size", [0, 40000, MAX_BYTES, MAX_BYTES + 1])
def test_remote_capture_reads_exact_bounded_binary_bytes(remote, tmp_path, size):
    from deerflow.sandbox.artifact_snapshot import read_snapshot

    outputs = tmp_path / "remote/outputs"
    outputs.mkdir()
    content = bytes(range(256)) * (size // 256) + b"x" * (size % 256)
    (outputs / "report.bin").write_bytes(content)
    if size > MAX_BYTES:
        with pytest.raises(AgentRunError):
            read_snapshot(remote, "report.bin")
    else:
        assert read_snapshot(remote, "report.bin") == content


def test_remote_capture_rejects_replacement_between_chunks(remote, tmp_path):
    from deerflow.sandbox.artifact_snapshot import read_snapshot

    outputs = tmp_path / "remote/outputs"
    outputs.mkdir()
    target = outputs / "report.txt"
    target.write_bytes(b"a" * 100000)
    original = remote.execute_command
    count = 0

    def command(script, **kwargs):
        nonlocal count
        result = original(script, **kwargs)
        count += 1
        if count == 1:
            target.write_bytes(b"b" * 100000)
        return result

    remote.execute_command = command
    with pytest.raises(AgentRunError):
        read_snapshot(remote, "report.txt")


def test_shared_outputs_keep_larger_bytes_and_nested_paths(remote):
    from deerflow.sandbox.artifact_snapshot import publish_snapshot, read_snapshot

    content = b"x" * (MAX_BYTES + 1)
    publish_snapshot(remote, "charts/report.bin", content, area="outputs", max_bytes=3 * 1024 * 1024)
    assert read_snapshot(remote, "charts/report.bin", max_bytes=3 * 1024 * 1024) == content
    with pytest.raises(AgentRunError):
        read_snapshot(remote, "charts/report.bin")
