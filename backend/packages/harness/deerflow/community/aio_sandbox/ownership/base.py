"""Ownership store contract for shared sandbox containers (#4206).

Gateway instances share sandbox containers but each keeps its own in-memory warm
pool. Without shared ownership state, one instance's startup reconciliation
adopts a container another instance is actively using and later idle-destroys it,
so tool calls fail with 502 / connection refused.

A lease answers "**which instance is responsible for reaping this container?**",
not "which instance may use it". That distinction drives the whole interface:

* A container is deterministic per (user, thread), so consecutive turns of one
  thread legitimately land on different instances. The instance now serving the
  thread :meth:`take` s the lease from whoever held it — refusing because a peer
  still held it would strand the thread until that lease expired.
* Reaping is the opposite. :meth:`claim` succeeds only when the container is
  unowned or already ours, so an instance can never adopt (and later
  idle-destroy) a container a live peer is responsible for. That is #4206.

**A lease has two states, and that is what makes the destroy window safe.**
`own:` means "I am responsible for this container"; `del:` means "I am tearing
this container down". A takeover (:meth:`take`) is refused against a `del:`
lease, so a container cannot be re-acquired between a destroy path's claim and
its container stop — the window the deleted per-sandbox flock guard used to
cover. Without the two states an unconditional `take` would silently overwrite a
destroyer's claim and the peer's stop would land on a container the new owner had
already handed to an agent.

Contract notes for implementers:

* Every method is **synchronous**. Unlike ``StreamBridge`` (whose async API exists
  because it is driven from the event loop), ownership is driven from
  ``AioSandboxProvider.__init__``, the background idle/renewal threads, and the
  sync ``release()`` path. Sandbox tool paths that *do* run on the event loop
  (``get()``) deliberately never touch the store, and async acquire paths offload
  registration through ``asyncio.to_thread``.
* Methods **raise** ``OwnershipBackendError`` on backend failure rather than
  returning a falsy value. Callers must fail closed: a sandbox whose ownership
  could not be published is not safe to hand out, and a container whose ownership
  cannot be proven free is not safe to destroy. A ``False`` return means
  "definitively not ours"; raising means "unknown".
"""

from __future__ import annotations

import abc
import enum


class OwnershipBackendError(RuntimeError):
    """The ownership backend could not answer.

    Distinct from a definitive "not ours" (``False``): this means ownership is
    *unknown*, so callers must fail closed rather than assume the container is
    free.
    """


class RenewOutcome(enum.Enum):
    """Why a renewal did or did not succeed.

    ``LAPSED`` and ``LOST`` must not be collapsed into one falsy value. A lapsed
    lease is *absent* — nobody took it, so re-establishing it is safe and is what
    keeps a Redis restart from dropping every live sandbox fleet-wide. A lost
    lease belongs to a peer, and re-taking it is the #4206 cross-instance kill.
    """

    #: Still ours; TTL refreshed.
    RENEWED = "renewed"
    #: No lease present (expired, or the store lost its state). Free to re-claim.
    LAPSED = "lapsed"
    #: A peer holds it, or it is being torn down. Do not re-take.
    LOST = "lost"


class SandboxOwnershipStore(abc.ABC):
    """Cross-instance ownership leases for sandbox containers."""

    #: Whether this store coordinates instances beyond the current process.
    #: ``False`` means peers cannot see our leases, so every container looks like
    #: an orphan to them — single-instance deployments only.
    supports_cross_process: bool = False

    @property
    @abc.abstractmethod
    def owner_id(self) -> str:
        """This instance's owner id, as written into leases."""

    @abc.abstractmethod
    def take(self, sandbox_id: str) -> bool:
        """Take responsibility for *sandbox_id* on the acquire path.

        Takes over from a live peer: a turn for this container's thread has
        routed here, and the previous owner learns to stop tracking it when its
        next renewal reports ``LOST``. It must not destroy it — see
        ``AioSandboxProvider._forget_lost_sandbox``.

        Refuses only a container that is being torn down, which is what closes
        the destroy → re-acquire window.

        Returns:
            ``True`` when this instance owns the lease afterwards.
            ``False`` when the container is being destroyed and must not be used.

        Raises:
            OwnershipBackendError: ownership could not be published. Callers must
                fail closed — an unpublished sandbox is not safe to hand out,
                because peers will see it as an orphan.
        """

    @abc.abstractmethod
    def claim(self, sandbox_id: str, *, for_destroy: bool = False) -> bool:
        """Take ownership of *sandbox_id* only if it is unowned or already ours.

        Exclusive: succeeds only when the container is unowned or already ours,
        which is what gates every adopt/reap path.

        Exclusive against **peers**, not against the caller's own process: a
        claim against our own ``own:`` lease succeeds by design, which is what
        lets a destroy path claim what it already owns. Same-process exclusion
        between an instance's reaper threads and its own acquire path is the
        provider's job, not this store's (``_reserve_local_teardown``).

        One exception, so ``for_destroy`` cannot be silently unwound: a
        **non**-destroy claim against our own ``del:`` lease is refused. The stop
        it marks is already in flight and cannot be recalled, so downgrading the
        marker would let a :meth:`take` hand out a container that is about to
        die.

        The read-modify-write must not interleave. On redis that is Lua (one
        script, server-side); the memory store serializes on a process-local lock
        and is single-instance anyway, so "different instances" cannot arise
        there. Note what is *not* verified: the contract suite drives sequential
        calls, so it pins the exclusion predicate, not the atomicity — and CI
        runs the memory tier only, so the Lua that carries it never executes on
        the merge gate.

        Args:
            for_destroy: mark the lease as a teardown in progress, so a
                concurrent :meth:`take` is refused for as long as it is held.
                Destroy paths must set this; the marker is cleared by
                :meth:`release` once the container is stopped, and expires with
                the TTL if the destroyer dies mid-stop.

        Returns:
            ``True`` when this instance owns the lease afterwards.
            ``False`` when a live peer holds it.

        Raises:
            OwnershipBackendError: ownership could not be determined.
        """

    @abc.abstractmethod
    def renew(self, sandbox_id: str) -> RenewOutcome:
        """Refresh our lease on *sandbox_id*.

        Deliberately does not re-acquire on its own — the caller decides, because
        only the caller can tell a safe re-establish (``LAPSED``) from a
        cross-instance steal (``LOST``).

        Raises:
            OwnershipBackendError: ownership could not be determined.
        """

    @abc.abstractmethod
    def release(self, sandbox_id: str) -> None:
        """Drop our lease on *sandbox_id*, in either state.

        A no-op when the lease is not ours, so a peer's live lease is never
        cleared. Best-effort: an expiring lease reaches the same state.

        Raises:
            OwnershipBackendError: the release could not be published.
        """

    @abc.abstractmethod
    def owner(self, sandbox_id: str) -> str | None:
        """Return the current owner id of *sandbox_id*, or ``None`` if unowned.

        Read-only: unlike :meth:`claim`, this never takes ownership. Use it to
        inspect (tests, logging) rather than to gate a destroy — a read is stale
        the moment it returns, whereas a successful claim keeps peers out.

        Raises:
            OwnershipBackendError: ownership could not be read.
        """

    def close(self) -> None:
        """Release backend resources. Default is a no-op."""
