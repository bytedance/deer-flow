"""Cross-instance ownership leases for shared sandbox containers (#4206)."""

# NOTE: ``RedisOwnershipStore`` is intentionally NOT imported here. ``redis`` is an
# optional extra, and this package is imported by ``aio_sandbox_provider`` at
# provider construction. Importing ``.redis`` eagerly would couple every AIO
# sandbox install to the redis package even when ownership is memory-only. It is
# imported lazily inside ``make_sandbox_ownership_store`` only when
# ``sandbox.ownership.type == "redis"``.

from .base import OwnershipBackendError, RenewOutcome, SandboxOwnershipStore
from .factory import compute_lease_ttl, generate_owner_id, make_sandbox_ownership_store, resolve_ownership_config
from .memory import MemoryOwnershipStore

__all__ = [
    "MemoryOwnershipStore",
    "OwnershipBackendError",
    "RenewOutcome",
    "SandboxOwnershipStore",
    "compute_lease_ttl",
    "generate_owner_id",
    "make_sandbox_ownership_store",
    "resolve_ownership_config",
]
