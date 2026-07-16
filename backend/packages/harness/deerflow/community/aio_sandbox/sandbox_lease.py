"""Cross-process ownership leases for local AIO sandbox containers.

Docker containers are shared across gateway workers, but each worker keeps its
own in-memory warm pool. Without a shared lease, one worker's startup
reconciliation can adopt another worker's live container and later idle-destroy
it (#4206).

Leases live under ``{base_dir}/sandbox-leases/{sandbox_id}.lease`` so every
worker on the same host (or shared volume) sees the same ownership signal.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Extra seconds beyond idle_timeout so a busy owner can renew before peers
# treat the container as an orphan.
DEFAULT_LEASE_GRACE_SECONDS = 60


def generate_sandbox_worker_id() -> str:
    """Return a unique id for this provider instance: ``hostname:hex``."""
    return f"{socket.gethostname()}:{uuid.uuid4().hex}"


@dataclass(frozen=True, slots=True)
class SandboxLease:
    worker_id: str
    expires_at: float

    def is_expired(self, now: float | None = None, *, grace_seconds: float = 0) -> bool:
        ts = time.time() if now is None else now
        return ts > (self.expires_at + grace_seconds)

    def held_by_other(self, worker_id: str, now: float | None = None, *, grace_seconds: float = 0) -> bool:
        if self.worker_id == worker_id:
            return False
        return not self.is_expired(now, grace_seconds=grace_seconds)


def lease_dir(base_dir: Path) -> Path:
    return Path(base_dir) / "sandbox-leases"


def lease_path(base_dir: Path, sandbox_id: str) -> Path:
    return lease_dir(base_dir) / f"{sandbox_id}.lease"


def compute_lease_ttl(idle_timeout: float, *, grace_seconds: float = DEFAULT_LEASE_GRACE_SECONDS) -> float:
    """How long a touch keeps the lease valid.

    When idle cleanup is disabled (``idle_timeout <= 0``), use a long fixed TTL
    so multi-worker peers still observe ownership between renewals.
    """
    grace = max(0.0, float(grace_seconds))
    timeout = float(idle_timeout)
    if timeout <= 0:
        return max(3600.0, grace)
    return timeout + grace


def read_lease(path: Path) -> SandboxLease | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as e:
        logger.warning("Failed to read sandbox lease %s: %s", path, e)
        return None

    try:
        data = json.loads(raw)
        worker_id = data["worker_id"]
        expires_at = float(data["expires_at"])
        if not isinstance(worker_id, str) or not worker_id:
            return None
        return SandboxLease(worker_id=worker_id, expires_at=expires_at)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
        logger.warning("Ignoring corrupt sandbox lease %s: %s", path, e)
        return None


def write_lease(path: Path, lease: SandboxLease) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"worker_id": lease.worker_id, "expires_at": lease.expires_at}, separators=(",", ":"))
    # Atomic replace so concurrent readers never see a partial write.
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(payload)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def touch_lease(
    base_dir: Path,
    sandbox_id: str,
    worker_id: str,
    *,
    idle_timeout: float,
    grace_seconds: float = DEFAULT_LEASE_GRACE_SECONDS,
    now: float | None = None,
) -> SandboxLease:
    """Renew ownership of *sandbox_id* for this worker."""
    ts = time.time() if now is None else now
    lease = SandboxLease(
        worker_id=worker_id,
        expires_at=ts + compute_lease_ttl(idle_timeout, grace_seconds=grace_seconds),
    )
    write_lease(lease_path(base_dir, sandbox_id), lease)
    return lease


def clear_lease(base_dir: Path, sandbox_id: str, *, worker_id: str | None = None) -> None:
    """Remove the lease file.

    When *worker_id* is set, only clear if this worker currently owns the lease
    (or the lease is missing/corrupt). Prevents a peer from wiping a live owner.
    """
    path = lease_path(base_dir, sandbox_id)
    if worker_id is not None:
        current = read_lease(path)
        if current is not None and current.worker_id != worker_id and not current.is_expired():
            return
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("Failed to clear sandbox lease %s: %s", path, e)


def foreign_lease_blocks(
    base_dir: Path,
    sandbox_id: str,
    worker_id: str,
    *,
    now: float | None = None,
    grace_seconds: float = 0,
) -> bool:
    """True when another live worker holds an unexpired lease on *sandbox_id*."""
    lease = read_lease(lease_path(base_dir, sandbox_id))
    if lease is None:
        return False
    return lease.held_by_other(worker_id, now, grace_seconds=grace_seconds)
