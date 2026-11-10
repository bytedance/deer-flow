"""Retirement keeps newer fences and tolerates already-completed cleanup.

Listing happens in the pre-proof snapshot. Direct filesystem mutations replay
older peers finishing their own cleanup or writing an empty legacy record.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deerflow.community.aio_sandbox.quarantine import SandboxQuarantine
from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo


def test_retire_survives_a_peer_fencing_between_listing_and_rmdir(tmp_path, monkeypatch):
    """A peer's mark() landing after retire()'s iterdir() must not raise out of retire().

    The fence the peer wrote is the live one; the directory must simply be left
    in place (not removed), so the peer's fence survives and teardown does not
    abort with an unhandled OSError.
    """
    store = SandboxQuarantine(tmp_path, "provisioner")
    info = SandboxInfo("thread-sandbox", "http://sandbox", container_id="gen-1")
    store.mark(info)
    directory = tmp_path / store._key("provisioner") / store._key("thread-sandbox")

    real_rmdir = Path.rmdir

    def racing_rmdir(self):
        if self == directory:
            # Peer fences the live generation right after retire() listed the dir.
            (self / store._key("gen-2")).touch()
        return real_rmdir(self)

    monkeypatch.setattr(Path, "rmdir", racing_rmdir)

    store.retire(info, snapshot=store.snapshot(info))  # must not raise

    assert directory.exists()
    assert (directory / store._key("gen-2")).exists()


@pytest.mark.parametrize("method", ["retire", "retire_replaced_generations"])
def test_teardown_survives_the_directory_disappearing_before_the_listing(tmp_path, monkeypatch, method):
    """A peer finishing its teardown first leaves nothing to remove, and must not raise.

    `_exists()` reported the directory, then the peer unlinked every record and
    removed it, so the listing itself fails with FileNotFoundError. The
    `contains()` listing two methods above already treats this exact
    interleaving as "the fence is gone"; neither teardown loop does.
    """
    store = SandboxQuarantine(tmp_path, "provisioner")
    info = SandboxInfo("thread-sandbox", "http://sandbox", container_id="gen-1")
    store.mark(info)
    directory = tmp_path / store._key("provisioner") / store._key("thread-sandbox")

    real_iterdir = Path.iterdir
    raced = []

    def racing_iterdir(self):
        if self == directory and not raced:
            raced.append(self)
            # The peer's retire() completes inside our own teardown window.
            for record in list(real_iterdir(self)):
                record.unlink()
            Path.rmdir(self)
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", racing_iterdir)

    getattr(store, method)(info, snapshot=store.snapshot(info))  # must not raise

    assert not directory.exists()


def test_retire_survives_a_record_disappearing_mid_loop(tmp_path, monkeypatch):
    """A peer's unlink landing between the listing and ours must not abort the loop.

    Two generations are fenced. The peer drops the first record after `retire()`
    listed the directory, so `record.unlink()` fails on a name that is already
    gone while the second record and the `rmdir()` still need the loop to finish.
    """
    store = SandboxQuarantine(tmp_path, "provisioner")
    info = SandboxInfo("thread-sandbox", "http://sandbox", container_id="gen-1")
    for container_id in ("gen-1", "gen-2"):
        store.mark(SandboxInfo("thread-sandbox", "http://sandbox", container_id=container_id))
    directory = tmp_path / store._key("provisioner") / store._key("thread-sandbox")
    raced_record = directory / store._key("gen-1")

    real_unlink = Path.unlink
    raced = []

    def racing_unlink(self):
        if self == raced_record and not raced:
            raced.append(self)
            real_unlink(self)
        return real_unlink(self)

    monkeypatch.setattr(Path, "unlink", racing_unlink)

    store.retire(info, snapshot=store.snapshot(info))  # must not raise

    assert not raced_record.exists()
    # The loop reached the second record, so the emptied directory was removed.
    assert not directory.exists()


def test_retire_replaced_generations_keeps_the_live_fence_when_a_peer_drops_a_stale_one_first(tmp_path, monkeypatch):
    """The prune path must survive losing a stale record mid-loop and still keep the live fence.

    `retire_replaced_generations()` skips the live generation's record by design.
    A peer unlinking the stale record first raises inside the loop, before the
    live record is even reached, so the prune aborts with FileNotFoundError.
    """
    store = SandboxQuarantine(tmp_path, "provisioner")
    stale = SandboxInfo("thread-sandbox", "http://sandbox", container_id="gen-1")
    live = SandboxInfo("thread-sandbox", "http://sandbox", container_id="gen-2")
    store.mark(stale)
    store.mark(live)
    directory = tmp_path / store._key("provisioner") / store._key("thread-sandbox")
    raced_record = directory / store._key("gen-1")

    real_unlink = Path.unlink
    raced = []

    def racing_unlink(self):
        if self == raced_record and not raced:
            raced.append(self)
            real_unlink(self)
        return real_unlink(self)

    monkeypatch.setattr(Path, "unlink", racing_unlink)

    store.retire_replaced_generations(live, snapshot=store.snapshot(live))  # must not raise

    assert not raced_record.exists()
    assert (directory / store._key("gen-2")).exists()
    assert directory.exists()
