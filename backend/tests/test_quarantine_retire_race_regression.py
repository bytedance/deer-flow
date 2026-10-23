"""Red/green regression: retire() must survive a peer fencing concurrently.

`retire()` unlinks every record then calls `directory.rmdir()` unguarded.
Between `iterdir()` and `rmdir()`, a concurrent `mark()` — a peer fencing the
same logical sandbox — can create a fresh record, so `rmdir()` fails with
ENOTEMPTY and the exception escapes into `_retire_absent_quarantine`'s
teardown path. Its sibling `retire_replaced_generations()` guards the identical
`rmdir` with `try/except OSError` for exactly this reason; `retire()` does not.

Deterministic: the race is replayed by wrapping `Path.rmdir` so a peer record
lands between the `iterdir()` and the `rmdir()` call.
The `rmdir()` window above is closed. Two windows ahead of it are not, in both
`retire()` and `retire_replaced_generations()`: the `iterdir()` listing and each
`record.unlink()`. A peer running the same teardown one step ahead can remove the
directory, or one record, in exactly those windows, and the `FileNotFoundError`
then escapes the unwrapped `_retire_absent_quarantine()` call at the top of
sandbox creation. The class already reports that interleaving as a normal answer
two methods away: `_exists()` maps it to "no quarantine" and `contains()` catches
it on its own listing. The cases below replay each remaining window by
monkeypatching `Path.iterdir` or `Path.unlink`, so they stay deterministic.
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

    store.retire(info)  # must not raise

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

    getattr(store, method)(info)  # must not raise

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

    store.retire(info)  # must not raise

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

    store.retire_replaced_generations(live)  # must not raise

    assert not raced_record.exists()
    assert (directory / store._key("gen-2")).exists()
    assert directory.exists()
