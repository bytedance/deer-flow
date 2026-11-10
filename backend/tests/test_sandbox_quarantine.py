"""Quarantine follows a container generation across provider restarts."""

import multiprocessing
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.community.aio_sandbox.quarantine import SandboxQuarantine
from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo


def test_quarantine_survives_restart_and_does_not_taint_replacement(tmp_path):
    old = SandboxInfo("thread-sandbox", "http://sandbox", container_id="old-generation")
    replacement = SandboxInfo("thread-sandbox", "http://sandbox", container_id="new-generation")
    SandboxQuarantine(tmp_path, "provisioner-a").mark(old)

    restarted = SandboxQuarantine(tmp_path, "provisioner-a")
    assert restarted.contains(old)
    assert not restarted.contains(replacement)
    assert not SandboxQuarantine(tmp_path, "provisioner-b").contains(old)


def test_discovery_without_generation_cannot_bypass_quarantine(tmp_path):
    store = SandboxQuarantine(tmp_path, "provisioner")
    store.mark(SandboxInfo("thread-sandbox", "http://sandbox", container_id="old-generation"))

    assert store.contains(SandboxInfo("thread-sandbox", "http://sandbox"))
    assert not store.contains(SandboxInfo("another-thread", "http://sandbox"))


def test_quarantine_storage_failure_is_not_treated_as_safe(tmp_path, monkeypatch):
    store = SandboxQuarantine(tmp_path, "provisioner")

    def unavailable(*_args, **_kwargs):
        raise PermissionError("quarantine storage unavailable")

    monkeypatch.setattr(type(tmp_path), "stat", unavailable)
    with pytest.raises(PermissionError):
        store.contains(SandboxInfo("thread-sandbox", "http://sandbox", container_id="generation"))


def test_crash_residue_between_directory_and_record_still_fences(tmp_path):
    # mark() mkdirs the per-sandbox directory before writing the generation
    # record; a process dying in between must not silently drop the fence.
    store = SandboxQuarantine(tmp_path, "provisioner")
    directory = tmp_path / store._key("provisioner") / store._key("thread-sandbox")
    directory.mkdir(parents=True)

    assert store.contains(SandboxInfo("thread-sandbox", "http://sandbox"))
    assert store.contains(SandboxInfo("thread-sandbox", "http://sandbox", container_id="crashed-generation"))


def test_retired_quarantine_allows_replacements_without_generation(tmp_path):
    store = SandboxQuarantine(tmp_path, "provisioner")
    old = SandboxInfo("thread-sandbox", "http://sandbox")
    store.mark(old)
    store.mark(SandboxInfo(old.sandbox_id, old.sandbox_url, container_id="old-generation"))
    other = SandboxInfo("another-thread", "http://sandbox")
    store.mark(other)

    store.retire(old, snapshot=store.snapshot(old))

    restarted = SandboxQuarantine(tmp_path, "provisioner")
    assert not restarted.contains(old)
    assert not restarted.contains(SandboxInfo(old.sandbox_id, old.sandbox_url, container_id="new-generation"))
    assert restarted.contains(other)


def test_retire_replaced_generations_drops_only_absent_fences(tmp_path):
    """A live replacement proves the fenced old generation is gone; its record
    is pruned while the live generation's own fence survives."""
    store = SandboxQuarantine(tmp_path, "provisioner")
    old = SandboxInfo("thread-sandbox", "http://sandbox", container_id="old-generation")
    live = SandboxInfo("thread-sandbox", "http://sandbox", container_id="new-generation")
    store.mark(old)
    directory = tmp_path / store._key("provisioner") / store._key("thread-sandbox")

    store.retire_replaced_generations(live, snapshot=store.snapshot(live))

    assert not store.contains(old)
    assert not directory.exists()  # fully pruned, no stale record strands future creates
    directory.mkdir()  # a peer fences the live generation mid-flight
    directory.joinpath(store._key("new-generation")).touch()
    store.retire_replaced_generations(live, snapshot=store.snapshot(live))
    assert store.contains(live)


def test_retire_replaced_generations_keeps_unversioned_crash_fence(tmp_path):
    store = SandboxQuarantine(tmp_path, "provisioner")
    store.mark(SandboxInfo("thread-sandbox", "http://sandbox"))  # container_id-less mark → "unknown"
    directory = tmp_path / store._key("provisioner") / store._key("thread-sandbox")

    current = SandboxInfo("thread-sandbox", "http://sandbox", container_id="new-generation")
    store.retire_replaced_generations(current, snapshot=store.snapshot(current))

    assert (directory / "unknown").exists()


def test_quarantine_keys_are_truncated_for_windows_max_path():
    # The quarantine nests three hashed path components (scope, sandbox id,
    # container id). Three full 64-char SHA-256 hexdigests exceed Windows'
    # 260-char MAX_PATH under a long root, so each key is truncated to 16 hex
    # chars (64 bits). Pin that bound so a revert can't silently re-break
    # Windows record creation while Linux CI still passes.
    assert len(SandboxQuarantine._key("thread-sandbox")) == 16
    assert len(SandboxQuarantine._key("provisioner-a")) == 16
    assert len(SandboxQuarantine._key("old-generation")) == 16


def test_mark_keeps_pending_files_within_the_existing_windows_path_budget(tmp_path, monkeypatch):
    root = tmp_path / ("x" * (180 - len(str(tmp_path)) - 1))
    assert len(str(root)) == 180
    original_open = Path.open

    def limited_open(path, *args, **kwargs):
        if len(str(path)) >= 260:
            raise FileNotFoundError("emulated Windows MAX_PATH exceeded")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", limited_open)
    store = SandboxQuarantine(root, "provisioner")
    info = SandboxInfo("thread-sandbox", "", container_id="generation")
    store.mark(info)
    store.mark(info)
    assert store.contains(info)
    store.retire(info, snapshot=store.snapshot(info))
    assert not store.contains(info)


@pytest.mark.parametrize("content", [b"", b"123", b"x" * 16, b"\xff" * 16, b"unknown"])
def test_incomplete_pending_generation_fences_reuse_and_replacement_pruning(tmp_path, content):
    store = SandboxQuarantine(tmp_path, "provisioner")
    old = SandboxInfo("thread-sandbox", "", container_id="old")
    live = SandboxInfo(old.sandbox_id, "", container_id="new")
    store.mark(old)
    (store._directory(old) / ("p" + "0" * 15)).write_bytes(content)

    restarted = SandboxQuarantine(tmp_path, "provisioner")
    assert restarted.contains(live)
    snapshot = restarted.snapshot(live)
    assert not restarted.matches(live, snapshot=snapshot)
    restarted.retire_replaced_generations(live, snapshot=snapshot)
    assert restarted.contains(live)
    restarted.retire(live, snapshot=restarted.snapshot(live))
    assert not restarted.contains(live)


def test_pending_publication_during_contains_cannot_hide_the_fence(tmp_path, monkeypatch):
    store = SandboxQuarantine(tmp_path, "provisioner")
    old = SandboxInfo("thread-sandbox", "", container_id="old")
    live = SandboxInfo(old.sandbox_id, "", container_id="new")
    store.mark(old)
    directory = store._directory(live)
    pending = directory / ("p" + "0" * 15)
    pending.write_bytes(store._key(live.container_id).encode("ascii"))
    read_bytes = Path.read_bytes

    def finish_publication(path):
        if path == pending:
            (directory / store._key(live.container_id)).write_bytes(b"new-receipt")
            pending.unlink()
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", finish_publication)
    assert store.contains(live)


@pytest.mark.parametrize("method", ["retire", "retire_replaced_generations"])
def test_retirement_keeps_generations_marked_after_the_snapshot(tmp_path, method):
    store = SandboxQuarantine(tmp_path, "provisioner")
    old = SandboxInfo("thread-sandbox", "", container_id="old")
    observed = SandboxInfo(old.sandbox_id, "", container_id="observed")
    new = SandboxInfo(old.sandbox_id, "", container_id="new")
    store.mark(old)
    snapshot = store.snapshot(old)
    store.mark(new)

    getattr(store, method)(observed, snapshot=snapshot)

    assert store.contains(new)
    assert not store.contains(old)


@pytest.mark.parametrize("generation", ["same-generation", None], ids=["known", "unknown"])
@pytest.mark.parametrize("legacy", [False, True], ids=["receipt", "legacy-empty"])
def test_retirement_keeps_a_new_mark_with_the_same_record_name(tmp_path, generation, legacy):
    store = SandboxQuarantine(tmp_path, "provisioner")
    info = SandboxInfo("thread-sandbox", "", container_id=generation)
    store.mark(info)
    if legacy:
        record_name = store._key(generation) if generation else "unknown"
        (store._directory(info) / record_name).write_bytes(b"")
    old_snapshot = store.snapshot(info)
    store.mark(info)
    new_snapshot = store.snapshot(info)

    store.retire(info, snapshot=old_snapshot)

    assert store.contains(info)
    assert store.snapshot(info).records == new_snapshot.records
    # A later cleanup with a new absence proof can retire that newer receipt.
    store.retire(info, snapshot=store.snapshot(info))
    assert not store.contains(info)


def test_snapshot_read_failure_retains_the_quarantine(tmp_path, monkeypatch):
    store = SandboxQuarantine(tmp_path, "provisioner")
    info = SandboxInfo("thread-sandbox", "", container_id="generation")
    store.mark(info)

    def unavailable(_path):
        raise PermissionError("receipt storage unavailable")

    monkeypatch.setattr(Path, "read_bytes", unavailable)
    with pytest.raises(PermissionError, match="receipt storage unavailable"):
        store.snapshot(info)
    assert store.contains(info)


@pytest.mark.parametrize("failure", ["first-fsync", "sidecar-fsync", "receipt-fsync", "publish"])
@pytest.mark.parametrize("generation", ["new-generation", None], ids=["known", "unknown"])
def test_failed_mark_stays_fenced_with_older_generation_records(tmp_path, monkeypatch, failure, generation):
    from deerflow.community.aio_sandbox import quarantine as module

    store = SandboxQuarantine(tmp_path, "provisioner")
    old = SandboxInfo("thread-sandbox", "", container_id="old-generation")
    new = SandboxInfo(old.sandbox_id, "", container_id=generation)
    discovered = SandboxInfo(old.sandbox_id, "", container_id=generation or "discovered-generation")
    store.mark(old)
    stale_snapshot = store.snapshot(old)
    fsync = module.os.fsync
    failures = []
    sync_count = 0

    def fail_sync(fd):
        nonlocal sync_count
        sync_count += 1
        if sync_count == {"first-fsync": 1, "sidecar-fsync": 2, "receipt-fsync": 3}.get(failure):
            failures.append(True)
            raise OSError("receipt storage unavailable")
        fsync(fd)

    def fail_publish(*_args):
        failures.append(True)
        raise OSError("receipt storage unavailable")

    with monkeypatch.context() as patcher:
        patcher.setattr(module.os, "fsync", fail_sync)
        if failure == "publish":
            patcher.setattr(module.os, "replace", fail_publish)
        with pytest.raises(OSError, match="receipt storage unavailable"):
            store.mark(new)
    assert failures == [True]
    restarted = SandboxQuarantine(tmp_path, "provisioner")
    assert restarted.contains(discovered), "a failed mark must remain visible after restart"
    restarted.retire(old, snapshot=stale_snapshot)
    assert restarted.contains(discovered), "an old cleanup must retain an unfinished new mark"
    restarted.retire(new, snapshot=restarted.snapshot(new))
    assert not restarted.contains(new), "a new absence proof can finish interrupted marking"


@pytest.mark.skipif(os.name == "nt", reason="CIFS flock descriptor contract is POSIX-only")
def test_mark_syncs_the_locked_file_through_its_own_descriptor(tmp_path, monkeypatch):
    import fcntl

    from deerflow.community.aio_sandbox import quarantine as module

    flock, fsync = fcntl.flock, module.os.fsync
    lock_owner = []

    def tracked_lock(fd, operation):
        flock(fd, operation)
        if operation == fcntl.LOCK_UN:
            lock_owner.clear()
        else:
            lock_owner[:] = [fd]

    def mandatory_sync(fd):
        owner = lock_owner[0]
        if os.fstat(fd).st_ino == os.fstat(owner).st_ino and fd != owner:
            raise PermissionError("CIFS rejects IO through a separately opened descriptor")
        fsync(fd)

    monkeypatch.setattr(fcntl, "flock", tracked_lock)
    monkeypatch.setattr(module.os, "fsync", mandatory_sync)
    store = SandboxQuarantine(tmp_path, "provisioner")
    info = SandboxInfo("thread-sandbox", "", container_id="generation")
    store.mark(info)
    assert store.contains(info)
    store.retire(info, snapshot=store.snapshot(info))
    assert not store.contains(info)


@pytest.mark.parametrize("finish", ["rmdir", "changed-identity"])
def test_retirement_reports_lease_loss_during_its_last_storage_operation(tmp_path, monkeypatch, finish):
    store = SandboxQuarantine(tmp_path, "provisioner")
    info = SandboxInfo("thread-sandbox", "", container_id="generation")
    store.mark(info)
    snapshot = store.snapshot(info)
    directory = store._directory(info)
    lost = threading.Event()
    stat, rmdir = Path.stat, Path.rmdir

    def changed_identity(path, *args, **kwargs):
        result = stat(path, *args, **kwargs)
        if path == directory:
            lost.set()
            return SimpleNamespace(st_dev=result.st_dev, st_ino=result.st_ino + 1)
        return result

    def finish_removal(path):
        rmdir(path)
        if path == directory:
            lost.set()

    def check():
        if lost.is_set():
            raise RuntimeError("teardown lease lost")

    monkeypatch.setattr(Path, "stat" if finish == "changed-identity" else "rmdir", changed_identity if finish == "changed-identity" else finish_removal)
    with pytest.raises(RuntimeError, match="teardown lease lost"):
        store.retire(info, snapshot=snapshot, check=check)


@pytest.mark.parametrize("empty_snapshot", [False, True], ids=["old-record", "old-crash-residue"])
def test_retirement_keeps_a_recreated_crash_residue_directory(tmp_path, monkeypatch, empty_snapshot):
    from deerflow.community.aio_sandbox import quarantine as quarantine_module

    store = SandboxQuarantine(tmp_path, "provisioner")
    old = SandboxInfo("thread-sandbox", "", container_id="old")
    new = SandboxInfo(old.sandbox_id, "", container_id="new")
    if empty_snapshot:
        store._directory(old).mkdir(parents=True)
    else:
        store.mark(old)
    stale_snapshot = store.snapshot(old)
    store.retire(old, snapshot=store.snapshot(old))

    def failed_write(**_kwargs):
        raise OSError("record staging failed")

    monkeypatch.setattr(quarantine_module.tempfile, "mkstemp", failed_write)
    with pytest.raises(OSError, match="record staging failed"):
        store.mark(new)
    assert store.contains(new)

    store.retire(old, snapshot=stale_snapshot)

    assert store.contains(new), "stale cleanup removed the replacement's empty-directory fence"


def test_failed_remark_keeps_existing_empty_directory_fence(tmp_path, monkeypatch):
    from deerflow.community.aio_sandbox import quarantine as quarantine_module

    store = SandboxQuarantine(tmp_path, "provisioner")
    info = SandboxInfo("thread-sandbox", "")
    store._directory(info).mkdir(parents=True)
    snapshot = store.snapshot(info)

    def failed_write(**_kwargs):
        raise OSError("record staging failed")

    monkeypatch.setattr(quarantine_module.tempfile, "mkstemp", failed_write)
    with pytest.raises(OSError, match="record staging failed"):
        store.mark(info)
    store.retire(info, snapshot=snapshot)
    assert store.contains(info)


def test_failed_remark_fence_survives_coarse_directory_timestamps(tmp_path, monkeypatch):
    from deerflow.community.aio_sandbox import quarantine as quarantine_module

    store = SandboxQuarantine(tmp_path, "provisioner")
    info = SandboxInfo("thread-sandbox", "")
    directory = store._directory(info)
    directory.mkdir(parents=True)
    stat = Path.stat

    def coarse_stat(path, *args, **kwargs):
        result = stat(path, *args, **kwargs)
        if path == directory:
            return SimpleNamespace(st_dev=result.st_dev, st_ino=result.st_ino, st_mode=result.st_mode, st_mtime_ns=0, st_ctime_ns=0)
        return result

    def failed_write(**_kwargs):
        raise OSError("record staging failed")

    monkeypatch.setattr(Path, "stat", coarse_stat)
    snapshot = store.snapshot(info)
    monkeypatch.setattr(quarantine_module.tempfile, "mkstemp", failed_write)
    with pytest.raises(OSError, match="record staging failed"):
        store.mark(info)
    store.retire(info, snapshot=snapshot)
    assert store.contains(info)


def test_snapshot_lock_wait_aborts_after_lease_loss(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from deerflow.community.aio_sandbox import quarantine as quarantine_module

    store = SandboxQuarantine(tmp_path, "provisioner")
    info = SandboxInfo("thread-sandbox", "", container_id="generation")
    store.mark(info)
    writing, finish, checked, lost = (threading.Event() for _ in range(4))
    fsync = quarantine_module.os.fsync
    errors = []

    def pause_write(descriptor):
        fsync(descriptor)
        writing.set()
        assert finish.wait(10), "mark was not resumed"

    def mark():
        try:
            SandboxQuarantine(tmp_path, "provisioner").mark(info)
        except BaseException as error:
            errors.append(error)

    def check():
        checked.set()
        if lost.is_set():
            raise RuntimeError("teardown lease lost")

    monkeypatch.setattr(quarantine_module.os, "fsync", pause_write)
    marker = threading.Thread(target=mark)
    executor = ThreadPoolExecutor(max_workers=1)
    marker.start()
    try:
        assert writing.wait(10)
        snapshot = executor.submit(store.snapshot, info, check=check)
        assert checked.wait(5)
        lost.set()
        with pytest.raises(RuntimeError, match="teardown lease lost"):
            snapshot.result(timeout=5)
        assert marker.is_alive(), "snapshot only noticed lease loss after the lock was released"
    finally:
        finish.set()
        marker.join(10)
        executor.shutdown(wait=True)
    assert not errors
    assert store.contains(info)


@pytest.mark.parametrize("operation", ["snapshot", "retire"])
@pytest.mark.parametrize("record_count", [1, 2])
def test_receipt_reads_stop_when_lease_loss_is_confirmed(tmp_path, monkeypatch, operation, record_count):
    store = SandboxQuarantine(tmp_path, "provisioner")
    infos = [SandboxInfo("thread-sandbox", "", container_id=f"generation-{index}") for index in range(record_count)]
    for info in infos:
        store.mark(info)
    snapshot = store.snapshot(infos[0])
    if operation == "retire":
        for info in infos:
            store.mark(info)  # Every captured receipt now mismatches.
    lost = threading.Event()
    reads = []
    read_bytes = Path.read_bytes

    def observe_read(path):
        receipt = read_bytes(path)
        reads.append(path)
        lost.set()
        return receipt

    def check():
        if lost.is_set():
            raise RuntimeError("teardown lease lost")

    monkeypatch.setattr(Path, "read_bytes", observe_read)
    with pytest.raises(RuntimeError, match="teardown lease lost"):
        if operation == "snapshot":
            store.snapshot(infos[0], check=check)
        else:
            store.retire(infos[0], snapshot=snapshot, check=check)
    assert len(reads) == 1
    assert all(store.contains(info) for info in infos)


def _mark_quarantine_in_peer(root, info, started, finished):
    store = SandboxQuarantine(root, "provisioner")
    started.set()
    store.mark(info)
    finished.set()


def _crash_before_receipt_publication(root, info):
    from deerflow.community.aio_sandbox import quarantine as module

    module.os.replace = lambda *_args: os._exit(71)
    SandboxQuarantine(root, "provisioner").mark(info)


@pytest.mark.parametrize("generation", ["new-generation", None], ids=["known", "unknown"])
def test_interrupted_mark_survives_peer_cleanup(tmp_path, generation):
    store = SandboxQuarantine(tmp_path, "provisioner")
    old = SandboxInfo("thread-sandbox", "", container_id="old-generation")
    new = SandboxInfo(old.sandbox_id, "", container_id=generation)
    discovered = SandboxInfo(old.sandbox_id, "", container_id=generation or "discovered-generation")
    store.mark(old)
    stale = store.snapshot(old)
    peer = multiprocessing.get_context("spawn").Process(target=_crash_before_receipt_publication, args=(tmp_path, new))
    peer.start()
    try:
        peer.join(15)
        assert peer.exitcode == 71, "the peer did not stop at receipt publication"
        restarted = SandboxQuarantine(tmp_path, "provisioner")
        assert restarted.contains(discovered)
        restarted.retire(old, snapshot=stale)
        assert restarted.contains(discovered)
        restarted.retire_replaced_generations(discovered, snapshot=restarted.snapshot(discovered))
        assert restarted.contains(discovered)
        restarted.retire(discovered, snapshot=restarted.snapshot(discovered))
        assert not restarted.contains(discovered)
    finally:
        if peer.is_alive():
            peer.terminate()
        peer.join(10)


def test_mark_and_receipt_comparison_are_serialized_across_processes(tmp_path, monkeypatch):
    store = SandboxQuarantine(tmp_path, "provisioner")
    info = SandboxInfo("thread-sandbox", "")
    store.mark(info)
    snapshot = store.snapshot(info)
    compared, finish = threading.Event(), threading.Event()
    context = multiprocessing.get_context("spawn")
    peer_started, peer_finished = context.Event(), context.Event()
    peer = context.Process(target=_mark_quarantine_in_peer, args=(tmp_path, info, peer_started, peer_finished))
    errors = []
    read_bytes = Path.read_bytes

    def pause_comparison(path):
        receipt = read_bytes(path)
        if threading.current_thread() is retiring:
            compared.set()
            assert finish.wait(10), "receipt comparison was not resumed"
        return receipt

    def retire():
        try:
            store.retire(info, snapshot=snapshot)
        except BaseException as error:
            errors.append(error)

    retiring = threading.Thread(target=retire)
    monkeypatch.setattr(Path, "read_bytes", pause_comparison)
    retiring.start()
    try:
        assert compared.wait(10)
        peer.start()
        assert peer_started.wait(10)
        assert not peer_finished.wait(0.1), "mark replaced a record between comparison and unlink"
        finish.set()
        retiring.join(10)
        peer.join(10)
        assert not retiring.is_alive() and peer.exitcode == 0
        assert not errors
        assert peer_finished.is_set()
        assert SandboxQuarantine(tmp_path, "provisioner").contains(info)
    finally:
        finish.set()
        retiring.join(10)
        if peer.pid is not None:
            peer.join(10)
            if peer.is_alive():
                peer.terminate()
                peer.join(10)
