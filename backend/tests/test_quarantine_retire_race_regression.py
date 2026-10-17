"""Red/green regression: retire() must survive a peer fencing concurrently.

`retire()` unlinks every record then calls `directory.rmdir()` unguarded.
Between `iterdir()` and `rmdir()`, a concurrent `mark()` — a peer fencing the
same logical sandbox — can create a fresh record, so `rmdir()` fails with
ENOTEMPTY and the exception escapes into `_retire_absent_quarantine`'s
teardown path. Its sibling `retire_replaced_generations()` guards the identical
`rmdir` with `try/except OSError` for exactly this reason; `retire()` does not.

Deterministic: the race is replayed by wrapping `Path.rmdir` so a peer record
lands between the `iterdir()` and the `rmdir()` call.
"""

from __future__ import annotations

from pathlib import Path

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
