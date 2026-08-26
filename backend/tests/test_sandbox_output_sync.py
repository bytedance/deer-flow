"""Unit tests for the shared release-time output sync core.

``deerflow.sandbox.output_sync`` is the provider-agnostic boundary that copies
artifacts from sandboxes without host bind mounts (E2B, BoxLite) back into the
per-user/per-thread host directory that the artifacts endpoint and the run
delivery scan read. These tests pin its tenant isolation, path-safety, and
resource-bound behaviour independently of any provider.
"""

from __future__ import annotations

import errno
import importlib
import json
import os
import subprocess
import time

import pytest

from deerflow.config.paths import Paths
from deerflow.sandbox.output_sync import (
    LISTING_COMPLETE_SENTINEL,
    OutputSyncLimits,
    build_bounded_listing_command,
    build_secure_bounded_read_command,
    parse_bounded_listing_output,
    parse_secure_bounded_read_output,
    sync_listing_to_host,
)

_LIMITS = OutputSyncLimits(max_file_bytes=100 * 1024 * 1024, max_total_bytes=512 * 1024 * 1024, max_files=2000, deadline_seconds=120)


class _Store:
    def __init__(self, files: dict[str, bytes]):
        self.files = files
        self.calls: list[str] = []

    def listing(self, mtime: str = "1700000000.5") -> str:
        return "".join(f"{len(data)}\t{mtime}\t{path}\0" for path, data in self.files.items())

    def download(self, virtual_path: str, max_bytes: int, timeout_seconds: float) -> bytes:
        assert timeout_seconds > 0
        self.calls.append(virtual_path)
        data = self.files[virtual_path]
        if len(data) > max_bytes:
            raise OSError(errno.EFBIG, f"download exceeds {max_bytes}-byte allowance")
        return data


def _symlink_to(target, link, *, target_is_directory=False):
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are not available: {exc}")


def _run_secure_bounded_read(root, relative_path: str, max_bytes: int) -> str:
    command = build_secure_bounded_read_command(str(root), relative_path, max_bytes)
    completed = subprocess.run(
        ["sh", "-lc", command],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return completed.stdout


@pytest.mark.skipif(os.name != "posix", reason="secure remote reads require POSIX openat/O_NOFOLLOW")
def test_secure_bounded_read_is_exact_and_rejects_symlink_swaps(tmp_path):
    remote_root = tmp_path / "remote root"
    nested = remote_root / "outputs" / "nested"
    nested.mkdir(parents=True)
    payload = b"ten-bytes!"
    (nested / "ok.bin").write_bytes(payload)

    output = _run_secure_bounded_read(remote_root, "outputs/nested/ok.bin", len(payload))
    assert parse_secure_bounded_read_output(output, path="outputs/nested/ok.bin") == payload
    with pytest.raises(OSError, match="incomplete payload"):
        parse_secure_bounded_read_output(output.rsplit("\n", 1)[0], path="outputs/nested/ok.bin")

    output = _run_secure_bounded_read(remote_root, "outputs/nested/ok.bin", len(payload) - 1)
    with pytest.raises(OSError) as oversized:
        parse_secure_bounded_read_output(output, path="outputs/nested/ok.bin")
    assert oversized.value.errno == errno.EFBIG

    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_bytes(b"outside-secret")
    _symlink_to(secret, nested / "final-link")
    output = _run_secure_bounded_read(remote_root, "outputs/nested/final-link", 100)
    with pytest.raises(OSError) as final_link:
        parse_secure_bounded_read_output(output, path="outputs/nested/final-link")
    assert final_link.value.errno != errno.EFBIG

    _symlink_to(outside, remote_root / "outputs" / "parent-link", target_is_directory=True)
    output = _run_secure_bounded_read(remote_root, "outputs/parent-link/secret.txt", 100)
    with pytest.raises(OSError) as parent_link:
        parse_secure_bounded_read_output(output, path="outputs/parent-link/secret.txt")
    assert parent_link.value.errno != errno.EFBIG


@pytest.fixture
def paths(monkeypatch, tmp_path) -> Paths:
    paths_mod = importlib.import_module("deerflow.config.paths")
    p = Paths(base_dir=tmp_path)
    monkeypatch.setattr(paths_mod, "get_paths", lambda: p, raising=False)
    return p


def _sync(store: _Store, *, listing: str | None = None, limits: OutputSyncLimits = _LIMITS, thread_id="t1", user_id="u1", sandbox_id="sb-1"):
    return sync_listing_to_host(
        store.listing() if listing is None else listing,
        remote_root="/mnt/user-data",
        thread_id=thread_id,
        user_id=user_id,
        sandbox_id=sandbox_id,
        manifest_name=".test-output-sync.json",
        download=store.download,
        limits=limits,
        log_prefix="test sync",
        listing_complete=True,
    )


def test_writes_nested_and_binary_files_into_thread_bucket(paths, tmp_path):
    blob = bytes(range(256)) * 2
    store = _Store({"/mnt/user-data/outputs/a/b/c.bin": blob, "/mnt/user-data/outputs/top.txt": b"hi", "/mnt/user-data/workspace/w.txt": b"w"})

    result = _sync(store)

    root = paths.thread_dir("t1", user_id="u1") / "user-data"
    assert (root / "outputs" / "a" / "b" / "c.bin").read_bytes() == blob
    assert (root / "outputs" / "top.txt").read_bytes() == b"hi"
    assert (root / "workspace" / "w.txt").read_bytes() == b"w"
    assert result.synced == 3 and result.truncated_reason is None
    # Temp files never linger and nothing lands outside the tenant bucket.
    assert not list(root.rglob("*.sync.tmp"))
    assert {p.name for p in tmp_path.iterdir()} == {"users"}


def test_uploads_and_out_of_root_entries_are_ignored(paths, tmp_path):
    store = _Store({"/mnt/user-data/uploads/u.txt": b"u", "/etc/passwd": b"x", "/mnt/user-data/outputs": b"dir?", "/home/user/outputs/other.txt": b"o", "/mnt/user-data/outputs/keep.txt": b"k"})

    result = _sync(store)

    assert store.calls == ["/mnt/user-data/outputs/keep.txt"]
    assert result.synced == 1


@pytest.mark.parametrize(
    "remote_path",
    [
        "/mnt/user-data/outputs/../../../etc/cron.d/evil",
        "/mnt/user-data/outputs/sub/../../uploads/x.txt",
        "/mnt/user-data/outputs/./dot.txt",
        "/mnt/user-data/outputs//double.txt",
        "/mnt/user-data/outputs/back\\slash.txt",
        "/mnt/user-data/outputs/",
    ],
)
def test_traversal_and_malformed_paths_are_rejected_before_download(paths, tmp_path, remote_path):
    store = _Store({remote_path: b"payload"})

    result = _sync(store)

    assert store.calls == []
    assert result.synced == 0
    assert not list((tmp_path).rglob("*.txt")) and not (tmp_path / "etc").exists()


def test_host_output_root_symlink_cannot_redirect_write(paths, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    outputs = paths.thread_dir("t1", user_id="u1") / "user-data" / "outputs"
    outputs.parent.mkdir(parents=True)
    _symlink_to(outside, outputs, target_is_directory=True)
    store = _Store({"/mnt/user-data/outputs/escaped.txt": b"payload"})

    result = _sync(store)

    assert store.calls == []
    assert result.synced == 0 and result.skipped == 1
    assert not (outside / "escaped.txt").exists()


def test_nested_host_symlink_cannot_redirect_write(paths, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    nested = paths.thread_dir("t1", user_id="u1") / "user-data" / "outputs" / "nested"
    nested.parent.mkdir(parents=True)
    _symlink_to(outside, nested, target_is_directory=True)
    store = _Store({"/mnt/user-data/outputs/nested/escaped.txt": b"payload"})

    result = _sync(store)

    assert store.calls == []
    assert result.synced == 0 and result.skipped == 1
    assert not (outside / "escaped.txt").exists()


def test_manifest_symlink_is_replaced_without_touching_target(paths, tmp_path):
    outside_manifest = tmp_path / "outside-manifest.json"
    outside_manifest.write_text("do-not-touch", encoding="utf-8")
    manifest = paths.thread_dir("t1", user_id="u1") / ".test-output-sync.json"
    manifest.parent.mkdir(parents=True)
    _symlink_to(outside_manifest, manifest)
    store = _Store({"/mnt/user-data/outputs/safe.txt": b"safe"})

    result = _sync(store)

    assert result.synced == 1
    assert outside_manifest.read_text(encoding="utf-8") == "do-not-touch"
    assert not manifest.is_symlink()
    assert json.loads(manifest.read_text(encoding="utf-8"))["sandbox_id"] == "sb-1"


@pytest.mark.parametrize("thread_id,user_id", [("../other", "u1"), ("t1", "../u2"), ("a/b", "u1"), ("t1", "")])
def test_unsafe_tenant_ids_raise_before_any_write(paths, tmp_path, thread_id, user_id):
    store = _Store({"/mnt/user-data/outputs/a.txt": b"a"})

    with pytest.raises(ValueError):
        _sync(store, thread_id=thread_id, user_id=user_id)

    assert store.calls == []
    assert list(tmp_path.iterdir()) == []


def test_user_less_thread_uses_legacy_layout(paths, tmp_path):
    store = _Store({"/mnt/user-data/outputs/a.txt": b"a"})

    _sync(store, user_id=None)

    assert (tmp_path / "threads" / "t1" / "user-data" / "outputs" / "a.txt").read_bytes() == b"a"
    assert not (tmp_path / "users").exists()


def test_manifest_skips_unchanged_files_and_prunes_deleted_ones(paths):
    store = _Store({"/mnt/user-data/outputs/a.txt": b"aaa", "/mnt/user-data/outputs/b.txt": b"bbb"})
    _sync(store)
    assert len(store.calls) == 2

    del store.files["/mnt/user-data/outputs/b.txt"]
    result = _sync(store)

    assert len(store.calls) == 2 and result.skipped == 1
    assert not (paths.thread_dir("t1", user_id="u1") / "user-data" / "outputs" / "b.txt").exists()
    manifest = json.loads((paths.thread_dir("t1", user_id="u1") / ".test-output-sync.json").read_text())
    assert manifest["sandbox_id"] == "sb-1" and set(manifest["files"]) == {"outputs/a.txt"}


def test_manifest_from_another_sandbox_is_not_trusted(paths):
    store = _Store({"/mnt/user-data/outputs/a.txt": b"aaa"})
    _sync(store, sandbox_id="sb-old")

    _sync(store, sandbox_id="sb-new")

    assert store.calls == ["/mnt/user-data/outputs/a.txt"] * 2


def test_per_file_cap_skips_oversize_artifact(paths, caplog):
    store = _Store({"/mnt/user-data/outputs/big.bin": b"x" * 11, "/mnt/user-data/outputs/ok.txt": b"ok"})

    with caplog.at_level("WARNING"):
        result = _sync(store, limits=OutputSyncLimits(max_file_bytes=10, max_total_bytes=1 << 30, max_files=100, deadline_seconds=60))

    assert store.calls == ["/mnt/user-data/outputs/ok.txt"]
    assert result.skipped == 1 and result.truncated_reason is None
    assert "oversize artefact" in caplog.text


def test_actual_download_size_enforces_per_file_cap_when_listing_is_stale(paths, caplog):
    path = "/mnt/user-data/outputs/raced.bin"
    store = _Store({path: b"x" * 11})
    stale_listing = f"2\t1700000000.5\t{path}\0"

    with caplog.at_level("WARNING"):
        result = _sync(
            store,
            listing=stale_listing,
            limits=OutputSyncLimits(
                max_file_bytes=10,
                max_total_bytes=1 << 30,
                max_files=100,
                deadline_seconds=60,
            ),
        )

    host_path = paths.thread_dir("t1", user_id="u1") / "user-data" / "outputs" / "raced.bin"
    assert store.calls == [path]
    assert not host_path.exists()
    assert result.downloaded_files == 0
    assert result.downloaded_bytes == 0
    assert result.skipped == 1
    assert "per-file byte cap" in caplog.text


def test_actual_download_size_enforces_total_cap_when_listing_is_stale(paths):
    first = "/mnt/user-data/outputs/first.bin"
    second = "/mnt/user-data/outputs/second.bin"
    store = _Store({first: b"a" * 8, second: b"b" * 8})
    stale_listing = "".join(
        [
            f"1\t1700000000.5\t{first}\0",
            f"1\t1700000000.5\t{second}\0",
        ]
    )

    result = _sync(
        store,
        listing=stale_listing,
        limits=OutputSyncLimits(
            max_file_bytes=10,
            max_total_bytes=10,
            max_files=100,
            deadline_seconds=60,
        ),
    )

    root = paths.thread_dir("t1", user_id="u1") / "user-data" / "outputs"
    assert store.calls == [first, second]
    assert (root / "first.bin").read_bytes() == b"a" * 8
    assert not (root / "second.bin").exists()
    assert result.downloaded_files == 1
    assert result.downloaded_bytes == 8
    assert result.truncated_reason == "total byte budget 10"


def test_file_count_cap_truncates_pass_and_keeps_unseen_manifest_entries(paths, caplog):
    thread_dir = paths.thread_dir("t1", user_id="u1")
    thread_dir.mkdir(parents=True)
    (thread_dir / ".test-output-sync.json").write_text(json.dumps({"version": 1, "sandbox_id": "sb-1", "files": {"outputs/unseen.txt": {"remote_size": 1, "remote_mtime_ns": 1, "host_size": 1, "host_mtime_ns": 1}}}))
    store = _Store({f"/mnt/user-data/outputs/{n}.txt": b"x" for n in "abc"})

    with caplog.at_level("WARNING"):
        result = _sync(store, limits=OutputSyncLimits(max_file_bytes=1 << 20, max_total_bytes=1 << 30, max_files=2, deadline_seconds=60))

    assert len(store.calls) == 2 and result.truncated_reason == "file count cap 2"
    assert "deferred to next release" in caplog.text
    manifest = json.loads((thread_dir / ".test-output-sync.json").read_text())
    assert "outputs/unseen.txt" in manifest["files"]


def test_total_byte_budget_and_deadline_bound_the_pass(paths):
    store = _Store({f"/mnt/user-data/outputs/{n}.txt": b"0123456789" for n in "abc"})

    by_bytes = _sync(store, limits=OutputSyncLimits(max_file_bytes=1 << 20, max_total_bytes=25, max_files=100, deadline_seconds=60))
    assert len(store.calls) == 2 and by_bytes.truncated_reason == "total byte budget 25"

    store2 = _Store({"/mnt/user-data/outputs/a.txt": b"a"})
    by_time = _sync(store2, limits=OutputSyncLimits(max_file_bytes=1 << 20, max_total_bytes=1 << 30, max_files=100, deadline_seconds=0))
    assert store2.calls == [] and by_time.truncated_reason == "time budget 0s"


def test_download_failure_skips_file_but_continues(paths, caplog):
    store = _Store({"/mnt/user-data/outputs/bad.txt": b"b", "/mnt/user-data/outputs/good.txt": b"g"})
    original = store.download

    def flaky(path, max_bytes, timeout_seconds):
        if path.endswith("bad.txt"):
            raise RuntimeError("boom")
        return original(path, max_bytes, timeout_seconds)

    with caplog.at_level("WARNING"):
        result = sync_listing_to_host(store.listing(), remote_root="/mnt/user-data", thread_id="t1", user_id="u1", sandbox_id="sb", manifest_name=".m.json", download=flaky, limits=_LIMITS)

    assert result.synced == 1 and "failed to download" in caplog.text
    assert (paths.thread_dir("t1", user_id="u1") / "user-data" / "outputs" / "good.txt").read_bytes() == b"g"


def test_unparseable_records_and_trailing_whitespace_names(paths):
    store = _Store({"/mnt/user-data/outputs/report ": b"r"})
    listing = "junk\0x\ty\t/mnt/user-data/outputs/z\0" + store.listing()

    result = _sync(store, listing=listing)

    assert result.synced == 1
    assert result.truncated_reason == "malformed remote listing"
    assert (paths.thread_dir("t1", user_id="u1") / "user-data" / "outputs" / "report ").read_bytes() == b"r"


def test_malformed_inventory_cannot_delete_manifest_backed_host_file(paths):
    store = _Store({"/mnt/user-data/outputs/still-present.txt": b"data"})
    _sync(store)

    result = _sync(store, listing="4\\t1700000000\\t/mnt/user-data/outputs/still-present.txt\0")

    host_file = paths.thread_dir("t1", user_id="u1") / "user-data" / "outputs" / "still-present.txt"
    manifest = json.loads((paths.thread_dir("t1", user_id="u1") / ".test-output-sync.json").read_text())
    assert result.truncated_reason == "malformed remote listing"
    assert host_file.read_bytes() == b"data"
    assert "outputs/still-present.txt" in manifest["files"]


def test_busybox_listing_command_uses_shell_printf_for_binary_framing():
    command = build_bounded_listing_command(
        ("/mnt/user-data/outputs",),
        _LIMITS,
        busybox_stat_fallback=True,
    )

    assert "stat -c %s" in command and "stat -c %Y" in command
    assert 'printf "%s\\t%s\\t%s\\0"' in command
    assert "stat -c '%s\\t%Y\\t%n'" not in command
    assert LISTING_COMPLETE_SENTINEL in command


def test_listing_completion_frame_is_required_and_removed():
    listing = "4\t1700000000\t/mnt/user-data/outputs/a.txt\0"

    assert parse_bounded_listing_output(listing) == (listing, False)
    assert parse_bounded_listing_output(f"{listing}{LISTING_COMPLETE_SENTINEL}\0") == (listing, True)


def test_listing_file_cap_bounds_parser_and_does_not_delete_unseen_host_files(paths):
    store = _Store({f"/mnt/user-data/outputs/{name}.txt": b"x" for name in "abc"})
    _sync(store)
    del store.files["/mnt/user-data/outputs/c.txt"]
    store.calls.clear()
    limits = OutputSyncLimits(
        max_file_bytes=1 << 20,
        max_total_bytes=1 << 30,
        max_files=100,
        deadline_seconds=60,
        max_listing_files=1,
    )

    result = _sync(store, limits=limits)

    assert result.truncated_reason == "listing file cap 1"
    assert (paths.thread_dir("t1", user_id="u1") / "user-data" / "outputs" / "c.txt").exists()


def test_listing_byte_cap_rejects_partial_record_without_pruning(paths):
    store = _Store({"/mnt/user-data/outputs/keep.txt": b"keep", "/mnt/user-data/outputs/deleted.txt": b"old"})
    _sync(store)
    del store.files["/mnt/user-data/outputs/deleted.txt"]
    listing = store.listing() + "100\t1700000000.5\t/mnt/user-data/outputs/" + ("x" * 200)
    limits = OutputSyncLimits(
        max_file_bytes=1 << 20,
        max_total_bytes=1 << 30,
        max_files=100,
        deadline_seconds=60,
        max_listing_bytes=len(store.listing().encode()) + 20,
    )

    result = _sync(store, listing=listing, limits=limits)

    assert result.truncated_reason == f"listing byte cap {limits.max_listing_bytes}"
    assert (paths.thread_dir("t1", user_id="u1") / "user-data" / "outputs" / "deleted.txt").exists()


def test_remaining_deadline_is_passed_to_download_and_timeout_truncates(paths):
    observed: list[float] = []
    store = _Store({"/mnt/user-data/outputs/a.txt": b"a"})

    def timeout_download(path, max_bytes, timeout_seconds):
        observed.append(timeout_seconds)
        raise TimeoutError(path)

    result = sync_listing_to_host(
        store.listing(),
        remote_root="/mnt/user-data",
        thread_id="t1",
        user_id="u1",
        sandbox_id="sb",
        manifest_name=".m.json",
        download=timeout_download,
        limits=OutputSyncLimits(
            max_file_bytes=1 << 20,
            max_total_bytes=1 << 30,
            max_files=100,
            deadline_seconds=60,
        ),
        deadline=time.monotonic() + 1,
    )

    assert len(observed) == 1 and 0 < observed[0] <= 1
    assert result.truncated_reason == "time budget 60s"


def test_parent_symlink_swap_cannot_redirect_atomic_write(paths, tmp_path, monkeypatch):
    store = _Store({"/mnt/user-data/outputs/nested/race.txt": b"old"})
    _sync(store)
    store.files["/mnt/user-data/outputs/nested/race.txt"] = b"new payload"

    output_sync = importlib.import_module("deerflow.sandbox.output_sync")
    original_replace = output_sync.os.replace
    nested = paths.thread_dir("t1", user_id="u1") / "user-data" / "outputs" / "nested"
    held = nested.with_name("nested-held")
    outside = tmp_path / "outside"
    outside.mkdir()
    swapped = False

    def swap_then_replace(src, dst, *args, **kwargs):
        nonlocal swapped
        if not swapped and dst == "race.txt" and kwargs.get("dst_dir_fd") is not None:
            original_replace(nested, held)
            _symlink_to(outside, nested, target_is_directory=True)
            swapped = True
        return original_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(output_sync.os, "replace", swap_then_replace)

    result = _sync(store)

    assert swapped and result.synced == 1
    assert not (outside / "race.txt").exists()
    assert (held / "race.txt").read_bytes() == b"new payload"
