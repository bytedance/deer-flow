"""AIO Sandbox Provider — orchestrates sandbox lifecycle with pluggable backends.

This provider composes:
- SandboxBackend: how sandboxes are provisioned (local container vs remote/K8s)

The provider itself handles:
- In-process caching for fast repeated access
- Idle timeout management
- Graceful shutdown with signal handling
- Mount computation (thread-specific, skills)
"""

import asyncio
import atexit
import contextlib
import hashlib
import logging
import os
import signal
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]
    import msvcrt

from deerflow.community.warm_pool_lifecycle import (
    DEFAULT_IDLE_TIMEOUT,
    DEFAULT_REPLICAS,
    WarmPoolLifecycleMixin,
)
from deerflow.community.warm_pool_lifecycle import (
    IDLE_CHECK_INTERVAL as _SHARED_IDLE_CHECK_INTERVAL,
)
from deerflow.config import get_app_config
from deerflow.config.paths import VIRTUAL_PATH_PREFIX, get_paths, join_host_path
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider
from deerflow.skills.storage import user_should_see_legacy_skills

from .aio_sandbox import AioSandbox
from .backend import SandboxBackend, wait_for_sandbox_ready, wait_for_sandbox_ready_async
from .local_backend import LocalContainerBackend
from .ownership import (
    OwnershipBackendError,
    RenewOutcome,
    SandboxOwnershipStore,
    compute_lease_ttl,
    generate_owner_id,
    make_sandbox_ownership_store,
    resolve_ownership_config,
)
from .remote_backend import RemoteSandboxBackend
from .sandbox_info import SandboxInfo

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_IMAGE = "enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest"
DEFAULT_PORT = 8080
DEFAULT_CONTAINER_PREFIX = "deer-flow-sandbox"
IDLE_CHECK_INTERVAL = _SHARED_IDLE_CHECK_INTERVAL
THREAD_LOCK_EXECUTOR_WORKERS = min(32, (os.cpu_count() or 1) + 4)
_THREAD_LOCK_EXECUTOR = ThreadPoolExecutor(max_workers=THREAD_LOCK_EXECUTOR_WORKERS, thread_name_prefix="sandbox-lock-wait")
atexit.register(_THREAD_LOCK_EXECUTOR.shutdown, wait=False, cancel_futures=True)


class SandboxBeingDestroyedError(RuntimeError):
    """A peer is tearing this container down, so it must not be handed out.

    Raised on the acquire path when the ownership lease is in its teardown state.
    The caller drops the container from tracking and lets the normal
    discover-or-create path provision a fresh one, rather than handing an agent a
    sandbox that is about to stop underneath it.
    """

    def __init__(self, sandbox_id: str) -> None:
        super().__init__(f"sandbox {sandbox_id} is being destroyed by another instance")
        self.sandbox_id = sandbox_id


def _lock_file_exclusive(lock_file) -> None:
    if fcntl is not None:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        return

    lock_file.seek(0)
    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)


def _unlock_file(lock_file) -> None:
    if fcntl is not None:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        return

    lock_file.seek(0)
    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def _open_lock_file(lock_path):
    return open(lock_path, "a", encoding="utf-8")


async def _acquire_thread_lock_async(lock: threading.Lock) -> None:
    """Acquire a threading.Lock without polling or using the default executor."""
    loop = asyncio.get_running_loop()
    acquire_future = loop.run_in_executor(_THREAD_LOCK_EXECUTOR, lock.acquire, True)

    try:
        acquired = await asyncio.shield(acquire_future)
    except asyncio.CancelledError:
        acquire_future.add_done_callback(lambda task: _release_cancelled_lock_acquire(lock, task))
        raise

    if not acquired:
        raise RuntimeError("Failed to acquire sandbox thread lock")


def _release_cancelled_lock_acquire(lock: threading.Lock, task: asyncio.Future[bool]) -> None:
    """Release a lock acquired after its awaiting coroutine was cancelled."""
    if task.cancelled():
        return

    try:
        acquired = task.result()
    except Exception as e:
        logger.warning(f"Cancelled sandbox lock acquisition finished with error: {e}")
        return

    if acquired:
        lock.release()


class AioSandboxProvider(WarmPoolLifecycleMixin[SandboxInfo], SandboxProvider):
    """Sandbox provider that manages containers running the AIO sandbox.

    Architecture:
        This provider composes a SandboxBackend (how to provision), enabling:
        - Local Docker/Apple Container mode (auto-start containers)
        - Remote/K8s mode (connect to pre-existing sandbox URL)

    Configuration options in config.yaml under sandbox:
        use: deerflow.community.aio_sandbox:AioSandboxProvider
        image: <container image>
        port: 8080                      # Base port for local containers
        container_prefix: deer-flow-sandbox
        idle_timeout: 600               # Idle timeout in seconds (0 to disable)
        replicas: 3                     # Max concurrent sandbox containers (LRU eviction when exceeded)
        mounts:                         # Volume mounts for local containers
          - host_path: /path/on/host
            container_path: /path/in/container
            read_only: false
        environment:                    # Environment variables for containers
          NODE_ENV: production
          API_KEY: $MY_API_KEY
    """

    # How long `_held_teardown_lease` waits for its heartbeat thread to exit
    # before deferring the final lease release to that (still-running) thread.
    # The store's socket timeout bounds each operation, but context exit can
    # catch the heartbeat in one final refresh and must then wait for its final
    # release. Keep this above both sequential five-second operation bounds so a
    # normally timing-out refresh + release still finishes synchronously.
    _TEARDOWN_JOIN_TIMEOUT_SECONDS = 12.0

    def __init__(self):
        self._lock = threading.Lock()
        self._sandboxes: dict[str, AioSandbox] = {}  # sandbox_id -> AioSandbox instance
        self._sandbox_infos: dict[str, SandboxInfo] = {}  # sandbox_id -> SandboxInfo (for destroy)
        self._thread_sandboxes: dict[tuple[str, str], str] = {}  # (user_id, thread_id) -> sandbox_id
        self._thread_locks: dict[tuple[str, str], threading.Lock] = {}  # (user_id, thread_id) -> in-process lock
        self._last_activity: dict[str, float] = {}  # sandbox_id -> last activity timestamp
        # Warm pool: released sandboxes whose containers are still running.
        # Maps sandbox_id -> (SandboxInfo, release_timestamp).
        # Containers here can be reclaimed quickly (no cold-start) or destroyed
        # when replicas capacity is exhausted.
        self._warm_pool: dict[str, tuple[SandboxInfo, float]] = {}
        # sandbox_id -> when reconciliation first saw it running with no lease.
        # Gates adoption behind a recovery grace (see _adoptable_after_grace).
        self._unowned_since: dict[str, float] = {}
        # The two halves of same-process exclusion. The ownership store excludes
        # peers and nothing else — `claim()` and `take()` both succeed against
        # our own lease by design — so `del:` says nothing to this process's own
        # threads. See _reserve_local_teardown / _acquire_epoch.
        self._local_teardown: set[str] = set()
        self._acquire_epoch: dict[str, int] = {}
        self._acquire_epoch_counter = 0
        self._acquire_inflight: dict[str, int] = {}
        self._shutdown_called = False
        self._idle_checker_stop = threading.Event()
        self._idle_checker_thread: threading.Thread | None = None
        self._renewal_stop = threading.Event()
        self._renewal_thread: threading.Thread | None = None
        # Per-instance id used for cross-instance sandbox ownership leases (#4206).
        self._owner_id = generate_owner_id()

        self._config = self._load_config()
        self._ownership_config = resolve_ownership_config(self._config.get("ownership"), stream_bridge=self._config.get("stream_bridge"))
        self._ownership: SandboxOwnershipStore = make_sandbox_ownership_store(self._ownership_config, owner_id=self._owner_id)
        if not self._ownership.supports_cross_process:
            # Peers cannot see these leases, so every container looks like an
            # orphan to them. Say so once rather than letting #4206 resurface
            # silently on a multi-worker deployment that never set the config.
            logger.warning(
                "Sandbox ownership store cannot coordinate across processes (sandbox.ownership.type: %s). "
                "Safe for a single gateway instance only — multi-worker / load-balanced gateways sharing a "
                "container backend must set sandbox.ownership.type: redis, or peers will adopt and idle-destroy "
                "each other's live sandboxes (#4206).",
                self._ownership_config.type,
            )
        self._backend: SandboxBackend = self._create_backend()

        # Register shutdown handler
        atexit.register(self.shutdown)
        self._register_signal_handlers()

        # Reconcile orphaned containers from previous process lifecycles
        self._reconcile_orphans()

        # Renewal is independent of idle cleanup: an owner must keep proving it is
        # alive even when the idle reaper is disabled, or peers adopt its live
        # containers once the lease lapses (idle_timeout: 0 is a supported config).
        self._start_lease_renewal()

        # Start idle checker if enabled
        if self._config.get("idle_timeout", DEFAULT_IDLE_TIMEOUT) > 0:
            self._start_idle_checker()

    @property
    def uses_thread_data_mounts(self) -> bool:
        """Whether thread workspace/uploads/outputs are visible via mounts.

        Local container backends bind-mount the thread data directories, so files
        written by the gateway are already visible when the sandbox starts.
        Remote backends may require explicit file sync.
        """
        return isinstance(self._backend, LocalContainerBackend)

    # ── Factory methods ──────────────────────────────────────────────────

    def _create_backend(self) -> SandboxBackend:
        """Create the appropriate backend based on configuration.

        Selection logic (checked in order):
        1. ``provisioner_url`` set → RemoteSandboxBackend (provisioner mode)
              Provisioner dynamically creates Pods + Services in k3s.
        2. Default → LocalContainerBackend (local mode)
              Local provider manages container lifecycle directly (start/stop).
        """
        provisioner_url = self._config.get("provisioner_url")
        if provisioner_url:
            logger.info(f"Using remote sandbox backend with provisioner at {provisioner_url}")
            api_key = self._config.get("provisioner_api_key", "")
            return RemoteSandboxBackend(provisioner_url=provisioner_url, api_key=api_key)

        logger.info("Using local container sandbox backend")
        return LocalContainerBackend(
            image=self._config["image"],
            base_port=self._config["port"],
            container_prefix=self._config["container_prefix"],
            config_mounts=self._config["mounts"],
            environment=self._config["environment"],
        )

    # ── Configuration ────────────────────────────────────────────────────

    def _load_config(self) -> dict:
        """Load sandbox configuration from app config."""
        config = get_app_config()
        sandbox_config = config.sandbox

        idle_timeout = getattr(sandbox_config, "idle_timeout", None)
        replicas = getattr(sandbox_config, "replicas", None)

        return {
            "image": sandbox_config.image or DEFAULT_IMAGE,
            "port": sandbox_config.port or DEFAULT_PORT,
            "container_prefix": sandbox_config.container_prefix or DEFAULT_CONTAINER_PREFIX,
            "idle_timeout": idle_timeout if idle_timeout is not None else DEFAULT_IDLE_TIMEOUT,
            "replicas": replicas if replicas is not None else DEFAULT_REPLICAS,
            "mounts": sandbox_config.mounts or [],
            "environment": self._resolve_env_vars(sandbox_config.environment or {}),
            "ownership": getattr(sandbox_config, "ownership", None),
            # A redis stream bridge means the deployment is multi-instance, which
            # is what the ownership store must default to. Read the same source
            # the bridge's own resolver reads, not just its env var.
            "stream_bridge": getattr(config, "stream_bridge", None),
            # provisioner URL for dynamic pod management (e.g. http://provisioner:8002)
            "provisioner_url": getattr(sandbox_config, "provisioner_url", None) or "",
            "provisioner_api_key": getattr(sandbox_config, "provisioner_api_key", None) or "",
        }

    @staticmethod
    def _resolve_env_vars(env_config: dict[str, str]) -> dict[str, str]:
        """Resolve environment variable references (values starting with $)."""
        resolved = {}
        for key, value in env_config.items():
            if isinstance(value, str) and value.startswith("$"):
                env_name = value[1:]
                resolved[key] = os.environ.get(env_name, "")
            else:
                resolved[key] = str(value)
        return resolved

    # ── Cross-instance ownership leases ───────────────────────────────────

    def _publish_ownership(self, sandbox_id: str) -> None:
        """Take responsibility for *sandbox_id* on the acquire path.

        Takes over from whichever instance served this thread last — the
        container is deterministic per (user, thread), so a turn routing here is
        a legitimate handover. The previous owner's next renewal reports LOST and
        it stops tracking the container without touching it.

        Deliberately **not** fail-open. Swallowing the error and handing the
        sandbox out anyway would leave it unowned while in active use, so a peer
        would see an orphan and reap it — the exact failure this store exists to
        stop. Callers must let this propagate.

        The intent mark is published **before** the round trip, and that ordering
        is the point. ``take()`` makes the takeover durable before it returns —
        on redis the server has committed the SET while the reply is still in
        flight — so bumping the epoch afterwards leaves a window where the store
        already says the container is ours but the guard still reads as though it
        were not. A renewal holding an older ``LOST`` walks straight through it,
        drops the maps, and closes the client this call is about to hand back, so
        acquire returns an id the provider no longer tracks and ``get()`` answers
        ``None``. A guard must become visible no later than the transition it
        guards; the epoch alone cannot, because it can only be written after the
        call that performs the transition returns.

        So the two marks cover the two halves and are both needed: the intent
        mark covers "an acquire is mid-flight", the epoch covers "an acquire
        completed since you decided".

        Raises:
            SandboxBeingDestroyedError: a peer is tearing this container down, so
                it must not be handed to an agent (the destroy → re-acquire race).
            OwnershipBackendError: ownership could not be published.
        """
        with self._lock:
            self._acquire_inflight[sandbox_id] = self._acquire_inflight.get(sandbox_id, 0) + 1
        try:
            if not self._ownership.take(sandbox_id):
                raise SandboxBeingDestroyedError(sandbox_id)
            with self._lock:
                self._acquire_epoch_counter += 1
                self._acquire_epoch[sandbox_id] = self._acquire_epoch_counter
        finally:
            # A count rather than a set: acquires for one id are serialized by
            # the per-thread lock today, so a set would be equivalent — but that
            # is an assumption about a caller two layers up, and if it ever
            # stopped holding, a set would be cleared by the first finisher and
            # silently reopen this window. Counting removes the assumption.
            with self._lock:
                remaining = self._acquire_inflight.get(sandbox_id, 0) - 1
                if remaining > 0:
                    self._acquire_inflight[sandbox_id] = remaining
                else:
                    self._acquire_inflight.pop(sandbox_id, None)

    # ── Same-process exclusion (the half the store does not provide) ───────
    #
    # A lease excludes *peers*: `claim()` succeeds against our own `own:` lease
    # by design (that is what lets a destroy path claim what it already owns),
    # and `take()` succeeds against it too. So between this process's reaper
    # threads — idle checker, renewal, eviction — and its own acquire path, the
    # store provides **no exclusion at all**. Every reaper decides outside
    # `self._lock` (a store round trip must not be held under the lock that
    # guards every acquire), so each one acts on a decision an acquire may
    # already have invalidated. The two helpers below are that missing half, one
    # per direction:
    #
    #   reaping  — we are about to stop/drop it, so nothing may promote it:
    #              reserve it, and make every promote path honour the reservation
    #              exactly as it honours a peer's `del:`.
    #   forgetting — a peer legitimately owns it and must win, so the promote is
    #              the thing to detect: compare the acquire epoch we decided on.

    def _reserve_local_teardown(self, sandbox_id: str, still_reapable: Callable[[], bool]) -> bool:
        """Reserve *sandbox_id* for teardown by this process.

        ``still_reapable`` is evaluated in the **same** critical section as the
        reservation, so no acquire can slip between the last check and the mark.
        That pairing is the whole point: checking first and marking second is the
        window, not a narrower version of it.

        Consequence, and the one rule a new caller has to know: **the predicate
        runs with ``self._lock`` held**, which is a plain ``Lock``, so a predicate
        that touches the lock — directly, or via a provider method that takes it —
        deadlocks. Predicates must be cheap, non-blocking reads of the maps
        (``sandbox_id in self._warm_pool``, a ``_last_activity`` comparison). The
        constraint is stated rather than engineered around on purpose: making the
        lock reentrant to tolerate it would trade a loud hang for a quiet class of
        re-entrancy bugs everywhere else in this provider.
        """
        with self._lock:
            if sandbox_id in self._local_teardown or not still_reapable():
                return False
            self._local_teardown.add(sandbox_id)
            return True

    def _finish_local_teardown(self, sandbox_id: str) -> None:
        with self._lock:
            self._local_teardown.discard(sandbox_id)

    def _being_torn_down_locally(self, sandbox_id: str) -> bool:
        """Whether a reaper thread in *this* process holds *sandbox_id*.

        Callers must already hold ``self._lock``.
        """
        return sandbox_id in self._local_teardown

    def _acquire_epoch_of(self, sandbox_id: str) -> int:
        """Snapshot the acquire generation, so a stale decision can be detected.

        Bumped only by ``_publish_ownership`` — i.e. exactly when an acquire path
        (re)takes the lease on the way to handing the sandbox to an agent.
        Re-establishing a lapsed lease from ``_refresh_ownership`` deliberately
        does not bump it: nothing was handed out, so a reaper's decision about
        that id is still current.
        """
        with self._lock:
            return self._acquire_epoch.get(sandbox_id, 0)

    def _claim_ownership(self, sandbox_id: str, *, for_destroy: bool = False) -> bool:
        """Take (or refresh) ownership of *sandbox_id*.

        A successful claim is what makes acting on the container safe: while we
        hold the lease a peer's claim fails. With ``for_destroy`` the lease is
        additionally marked as a teardown, which a concurrent acquire-side
        ``take()`` refuses — that is what closes the ownership-check → container-
        stop window the deleted per-sandbox flock guard used to cover.

        Fails closed on a backend error: ownership unknown is treated as
        "not ours" so we neither adopt nor destroy the container.
        """
        try:
            return self._ownership.claim(sandbox_id, for_destroy=for_destroy)
        except OwnershipBackendError as e:
            logger.warning("Sandbox ownership claim failed for %s (treating as not owned): %s", sandbox_id, e)
            return False

    def _release_ownership(self, sandbox_id: str) -> None:
        try:
            self._ownership.release(sandbox_id)
        except OwnershipBackendError as e:
            # Best effort: the lease expires on its own, so a failed release
            # delays reuse rather than corrupting ownership.
            logger.warning("Failed to release sandbox ownership for %s: %s", sandbox_id, e)

    def _refresh_ownership(self, sandbox_id: str) -> bool:
        """Keep holding *sandbox_id*'s lease. False when a peer has taken it.

        A **lapsed** lease is re-established rather than treated as lost: nobody
        holds it, so re-claiming is safe, and this is what keeps a Redis restart
        (which drops every key) from evicting every live sandbox fleet-wide. A
        lease a peer actually holds is never re-taken — that is the #4206 kill.
        """
        try:
            outcome = self._ownership.renew(sandbox_id)
        except OwnershipBackendError as e:
            # Unknown, not lost: keep the sandbox and retry next tick. The TTL
            # still bounds how long a genuinely dead owner holds the lease.
            logger.warning("Could not renew sandbox ownership for %s, will retry: %s", sandbox_id, e)
            return True

        if outcome is RenewOutcome.RENEWED:
            return True
        if outcome is RenewOutcome.LAPSED:
            # Free: re-establish. This is the deliberate fail-open renewal path,
            # so it cannot use `_claim_ownership`: that helper turns a backend
            # error into False for adopt/reap callers, which would conflate an
            # outage between these two round trips with a peer takeover and
            # evict a live sandbox. Unknown means keep-and-retry here, exactly as
            # it does when the `renew()` call itself cannot answer above.
            try:
                if self._ownership.claim(sandbox_id):
                    logger.info("Re-established a lapsed ownership lease for %s", sandbox_id)
                    return True
            except OwnershipBackendError as e:
                logger.warning("Could not re-establish lapsed lease for %s, will retry: %s", sandbox_id, e)
                return True
            logger.warning("Lapsed ownership lease for %s was taken by a peer", sandbox_id)
            return False
        return False

    @contextlib.contextmanager
    def _held_teardown_lease(self, sandbox_id: str):
        """Keep *sandbox_id*'s teardown marker alive for as long as its stop runs.

        ``claim(..., for_destroy=True)`` writes the ``del:`` marker with the
        ordinary lease TTL, and normal ``renew()`` extends only ``own:`` while
        deliberately reporting a teardown as ``LOST``. Active and unhealthy
        destroy paths drop the sandbox from the maps ``_renew_owned_leases``
        iterates; the warm path keeps its entry visible until the stop succeeds,
        so ``_forget_lost_sandbox`` separately honours ``_local_teardown`` rather
        than misreading our own marker as a peer takeover. Without this heartbeat,
        a container stop that outlived the TTL let the marker lapse, a peer's
        ``take()`` succeeded against the still-running container, and the stop
        landed on the turn that had just been handed it — the very window the
        ``del:`` state exists to close, reopened by its own expiry.

        This is what the per-sandbox ``flock`` used to cover for free: a held lock
        cannot expire. A lease can, so the exclusion has to be held deliberately
        rather than assumed to outlast the work it guards. Reachable without an
        abnormal backend — the config schema bounds only ``renewal_interval_seconds``
        (> 0) and ``ttl_multiplier`` (>= 2), so a legal setting puts the TTL below a
        normal container stop, and ``LocalContainerBackend._stop_container`` passes
        no ``timeout`` to ``subprocess.run``, so a wedged daemon blocks unbounded
        even at the default 120s.

        The TTL stays finite on purpose: the heartbeat dies with the process, so a
        destroyer that crashes mid-stop still releases the container one TTL later
        instead of marking it undestroyable forever.

        The final release is the heartbeat's own last act, not the caller's. A
        refresh ``claim`` still in flight when the context exits (the socket
        timeout bounds it, but it can be mid-call) would otherwise land *after* a
        caller-side release and rewrite the ``del:`` marker on a container whose
        stop had already completed — stranding a fresh ``take()`` (or rolling back
        a fresh create) until the TTL. Releasing from inside the heartbeat, after
        its loop has stopped, sequences the release strictly after the last
        refresh, so no claim can follow it.
        """
        stop = threading.Event()

        def beat() -> None:
            interval = self._ownership_config.renewal_interval_seconds
            try:
                while not stop.wait(interval):
                    try:
                        if not self._ownership.claim(sandbox_id, for_destroy=True):
                            # Only reachable if the store lost our marker *and* a
                            # peer took it (e.g. a flush mid-stop). The stop is
                            # already in flight and cannot be recalled, so say so
                            # loudly rather than let a peer's container die without
                            # a trace.
                            logger.error(
                                "Lost the teardown exclusion for %s while its container stop was still in flight; a peer may have taken it",
                                sandbox_id,
                            )
                            return
                    except Exception as e:
                        # Broad on purpose: a refresh that raises must not kill the
                        # heartbeat and strand the marker for a stop that can run
                        # unbounded. Unknown, not lost — the marker may still be
                        # live and the TTL bounds a stale one. Retry on the next tick.
                        logger.warning("Could not refresh the teardown lease for %s, will retry: %s", sandbox_id, e)
            finally:
                # Release last, from the heartbeat itself, so an in-flight refresh
                # can never run after the marker is cleared. `release()` drops only
                # our own lease, so this is a safe no-op if a peer took it above.
                self._release_ownership(sandbox_id)

        beater = threading.Thread(target=beat, name="sandbox-teardown-lease", daemon=True)
        beater.start()
        try:
            yield
        finally:
            stop.set()
            beater.join(timeout=self._TEARDOWN_JOIN_TIMEOUT_SECONDS)
            if beater.is_alive():
                # The budget covers a normally timing-out refresh plus the final
                # release. The release is the heartbeat's job and is still
                # pending; clearing the marker here would reopen the exact race
                # this owns, so leave it — the thread will release when it
                # unblocks, or the TTL will reap it.
                logger.warning(
                    "Teardown heartbeat for %s did not exit within %.1fs; its lease release is deferred to that thread",
                    sandbox_id,
                    self._TEARDOWN_JOIN_TIMEOUT_SECONDS,
                )

    # ── Startup reconciliation ────────────────────────────────────────────

    def _adoptable_after_grace(self, sandbox_id: str, now: float) -> bool:
        """Whether *sandbox_id* has looked unowned long enough to be a real orphan.

        An absent lease normally proves the owner died and its TTL ran out. But
        the store can lose every key while every owner is alive and serving — a
        Redis restart without persistence, or eviction under ``maxmemory``
        pressure. ``_refresh_ownership`` already refuses to read that as
        abandonment (``LAPSED`` is re-established, not surrendered). Reading the
        same signal as "orphan, adopt" here would contradict it on the other
        path: whoever reconciles first would adopt every live container in the
        window before its owner's next renewal tick, that owner's renewal would
        then report ``LOST``, and it would drop a sandbox it is actively serving
        for the adopter to idle-destroy — #4206 through the back door.

        Waiting one full lease TTL rebuilds the delay the state loss erased. A
        live owner republishes within one renewal interval, which is shorter than
        the TTL by construction (``ttl_multiplier >= 2``), so only a container
        whose owner is really gone stays unowned across the whole grace.
        """
        if not self._ownership.supports_cross_process:
            # No peer can hold a lease this store would show us, so an unowned
            # container cannot be a live peer's — it is from a dead lifecycle of
            # this process. Single-instance deployments keep instant cleanup, and
            # a grace could not help a multi-worker one on this store anyway:
            # peers are invisible to each other's leases with or without it.
            return True

        try:
            current_owner = self._ownership.owner(sandbox_id)
        except OwnershipBackendError as e:
            # Unknown, not free: fail closed, same as _claim_ownership.
            logger.warning("Could not read sandbox ownership for %s during reconciliation (deferring adoption): %s", sandbox_id, e)
            return False

        if current_owner is not None:
            # Owned — by a peer, or already by us. Either way not an orphan, and
            # a live owner republishing must restart the grace rather than let a
            # stale one expire over its lease.
            self._unowned_since.pop(sandbox_id, None)
            return False

        first_seen = self._unowned_since.setdefault(sandbox_id, now)
        return now - first_seen >= compute_lease_ttl(self._ownership_config)

    def _reconcile_orphans(self) -> None:
        """Reconcile orphaned containers left by previous process lifecycles.

        On startup (and periodically from the idle checker), enumerate running
        containers matching our prefix and adopt **true orphans** into the warm
        pool.  A container is only adopted when this instance can claim its
        ownership lease — so multi-instance gateways cannot adopt and later
        idle-destroy a peer's live sandbox (#4206).

        Adopted orphans get a fresh warm-pool timestamp; the idle checker then
        destroys them if nobody re-acquires within ``idle_timeout``.  That still
        cleans containers left by a crashed process once its lease expires.

        An unowned container is not adopted on sight — it must stay unowned for a
        recovery grace first, so a store that lost its state cannot be mistaken
        for a fleet of dead owners (see ``_adoptable_after_grace``).
        """
        try:
            running = self._backend.list_running()
        except Exception as e:
            logger.warning(f"Failed to enumerate running containers during startup reconciliation: {e}")
            return

        # Forget grace timers for containers that no longer exist, so a
        # long-lived instance does not accumulate an entry per destroyed
        # container. Runs before the empty-list return so it also drains.
        running_ids = {info.sandbox_id for info in running}
        self._unowned_since = {sid: seen for sid, seen in self._unowned_since.items() if sid in running_ids}

        if not running:
            return

        current_time = time.time()
        adopted = 0
        skipped_live = 0
        deferred = 0

        for info in running:
            age = current_time - info.created_at if info.created_at > 0 else float("inf")
            if not self._adoptable_after_grace(info.sandbox_id, current_time):
                deferred += 1
                logger.debug("Deferring container %s during reconciliation: owned, or not yet past the recovery grace", info.sandbox_id)
                continue

            # Claim second: a successful claim proves the container is not a
            # peer's and locks peers out. It says nothing about *us* — it
            # succeeds against our own lease by design — so it is not a substitute
            # for the local teardown check below. The grace above is likewise a
            # precondition, not a substitute; only the claim is atomic.
            if not self._claim_ownership(info.sandbox_id):
                skipped_live += 1
                logger.debug("Skipping container %s during reconciliation: owned by another instance", info.sandbox_id)
                continue

            # Single lock acquisition per container: atomic check-and-insert.
            # Avoids a TOCTOU window between the "already tracked?" check and the
            # warm-pool insert.
            with self._lock:
                if info.sandbox_id in self._sandboxes or info.sandbox_id in self._warm_pool:
                    continue
                if self._being_torn_down_locally(info.sandbox_id):
                    # Adoption is a promote, so it needs the same reservation
                    # check as the other three. A container being torn down here
                    # is untracked and still running, which is exactly the shape
                    # this loop adopts — and neither the claim nor the grace
                    # excludes it. On `memory` the grace is skipped outright
                    # (`supports_cross_process = False`), so nothing else stands
                    # in the way there at all; adopting would park a container
                    # into the warm pool moments before its stop lands, leaving a
                    # dead entry for the next reclaim to hand out.
                    deferred += 1
                    logger.debug("Deferring container %s during reconciliation: this instance is tearing it down", info.sandbox_id)
                    continue
                self._warm_pool[info.sandbox_id] = (info, current_time)
            self._unowned_since.pop(info.sandbox_id, None)
            adopted += 1
            logger.info(f"Adopted container {info.sandbox_id} into warm pool (age: {age:.0f}s)")

        logger.info(
            "Startup reconciliation complete: %s adopted into warm pool, %s skipped (live peer ownership), %s deferred (owned or within recovery grace), %s total found",
            adopted,
            skipped_live,
            deferred,
            len(running),
        )

    # ── Deterministic ID ─────────────────────────────────────────────────

    @staticmethod
    def _effective_acquire_user_id(user_id: str | None) -> str:
        return user_id or get_effective_user_id()

    @staticmethod
    def _thread_key(thread_id: str, user_id: str) -> tuple[str, str]:
        return (user_id, thread_id)

    @staticmethod
    def _deterministic_sandbox_id(thread_id: str, user_id: str) -> str:
        """Generate a deterministic sandbox ID from user/thread scope.

        Includes user_id so a previously-created default-bucket sandbox cannot be
        reused for an auth/channel run that should mount a user-scoped bucket.
        """
        return hashlib.sha256(f"{user_id}:{thread_id}".encode()).hexdigest()[:8]

    # ── Mount helpers ────────────────────────────────────────────────────

    def _get_extra_mounts(self, thread_id: str | None, *, user_id: str | None = None) -> list[tuple[str, str, bool]]:
        """Collect all extra mounts for a sandbox (thread-specific + skills)."""
        mounts: list[tuple[str, str, bool]] = []

        if thread_id:
            mounts.extend(self._get_thread_mounts(thread_id, user_id=user_id))
            logger.info(f"Adding thread mounts for thread {thread_id}: {mounts}")

        skills_mounts = self._get_skills_mounts(user_id=user_id)
        if skills_mounts:
            mounts.extend(skills_mounts)
            logger.info(f"Adding skills mounts: {skills_mounts}")

        return mounts

    @staticmethod
    def _get_thread_mounts(thread_id: str, *, user_id: str | None = None) -> list[tuple[str, str, bool]]:
        """Get volume mounts for a thread's data directories.

        Creates directories if they don't exist (lazy initialization).
        Mount sources use host_base_dir so that when running inside Docker with a
        mounted Docker socket (DooD), the host Docker daemon can resolve the paths.
        """
        paths = get_paths()
        effective_user_id = AioSandboxProvider._effective_acquire_user_id(user_id)
        paths.ensure_thread_dirs(thread_id, user_id=effective_user_id)

        return [
            (paths.host_sandbox_work_dir(thread_id, user_id=effective_user_id), f"{VIRTUAL_PATH_PREFIX}/workspace", False),
            (paths.host_sandbox_uploads_dir(thread_id, user_id=effective_user_id), f"{VIRTUAL_PATH_PREFIX}/uploads", False),
            (paths.host_sandbox_outputs_dir(thread_id, user_id=effective_user_id), f"{VIRTUAL_PATH_PREFIX}/outputs", False),
            # ACP workspace: read-only inside the sandbox (lead agent reads results;
            # the ACP subprocess writes from the host side, not from within the container).
            (paths.host_acp_workspace_dir(thread_id, user_id=effective_user_id), "/mnt/acp-workspace", True),
        ]

    @staticmethod
    def _get_skills_mounts(*, user_id: str | None = None) -> list[tuple[str, str, bool]]:
        """Get skills directory mount configurations for three-way skills layout.

        Mirrors ``LocalSandboxProvider._build_thread_path_mappings`` for AIO
        sandboxes: public, per-user custom, and legacy (pre-migration
        global-custom) skills are mounted to separate container subdirectories so
        that ``Skill.get_container_path()`` category-aware paths resolve
        correctly inside the sandbox.

        Mount sources use ``DEER_FLOW_HOST_SKILLS_PATH`` and
        ``DEER_FLOW_HOST_BASE_DIR`` when running inside Docker (DooD) so the
        host Docker daemon can resolve the paths.
        """
        mounts: list[tuple[str, str, bool]] = []
        try:
            config = get_app_config()
            skills_path = config.skills.get_skills_path()
            container_path = config.skills.container_path

            # When running inside Docker with DooD, use host-side skills path.
            host_skills_root = os.environ.get("DEER_FLOW_HOST_SKILLS_PATH") or str(skills_path)

            # 1. Public skills: global, read-only — static, shared by all threads
            public_skills_path = skills_path / "public"
            if public_skills_path.exists():
                mounts.append(
                    (
                        join_host_path(host_skills_root, "public"),
                        f"{container_path}/public",
                        True,
                    )
                )

            # 2. Per-user custom skills: read-only, per-thread/per-user
            effective_user_id = AioSandboxProvider._effective_acquire_user_id(user_id)
            paths = get_paths()
            user_custom_path = paths.user_custom_skills_dir(effective_user_id)
            user_custom_path.mkdir(parents=True, exist_ok=True)

            host_user_custom = join_host_path(
                str(paths.host_base_dir),
                "users",
                effective_user_id,
                "skills",
                "custom",
            )
            mounts.append(
                (
                    host_user_custom,
                    f"{container_path}/custom",
                    True,
                )
            )

            # 3. Legacy (pre-migration global-custom) skills: only mount for
            #    users who have no per-user custom skills yet, mirroring
            #    ``UserScopedSkillStorage._iter_skill_files`` visibility rule.
            legacy_skills_path = skills_path / "custom"
            if user_should_see_legacy_skills(effective_user_id, host_path=str(skills_path)) and legacy_skills_path.exists():
                mounts.append(
                    (
                        join_host_path(host_skills_root, "custom"),
                        f"{container_path}/legacy",
                        True,
                    )
                )
        except Exception as e:
            logger.warning("Could not setup skills mounts: %s", e)

        return mounts

    # ── Idle timeout management ──────────────────────────────────────────

    def _cleanup_idle_resources(self, idle_timeout: float) -> None:
        """Clean AIO resources idle longer than ``idle_timeout`` seconds."""
        # Pick up containers whose peer leases expired since startup (crash path).
        self._reconcile_orphans()
        self._cleanup_idle_sandboxes(idle_timeout)

    # ── Ownership lease renewal ──────────────────────────────────────────

    def _start_lease_renewal(self) -> None:
        """Start the daemon thread that keeps this instance's leases alive.

        Deliberately not folded into the idle checker: that thread only starts
        when ``idle_timeout > 0``, so renewal riding on it silently stopped for
        ``idle_timeout: 0`` deployments — a supported config ("keep warm VMs
        until shutdown") — letting every lease lapse and reopening #4206 one TTL
        later. Liveness and reaping must not share a switch.
        """
        if self._renewal_thread is not None and self._renewal_thread.is_alive():
            return

        self._renewal_stop.clear()
        self._renewal_thread = threading.Thread(
            target=self._lease_renewal_loop,
            name="sandbox-lease-renewal",
            daemon=True,
        )
        self._renewal_thread.start()
        logger.info(
            "Started sandbox ownership renewal thread (interval: %.1fs, ttl: %.1fs)",
            self._ownership_config.renewal_interval_seconds,
            self._ownership_config.renewal_interval_seconds * self._ownership_config.ttl_multiplier,
        )

    def _stop_lease_renewal(self) -> None:
        self._renewal_stop.set()
        thread = self._renewal_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)

    def _lease_renewal_loop(self) -> None:
        interval = self._ownership_config.renewal_interval_seconds
        while not self._renewal_stop.wait(interval):
            try:
                self._renew_owned_leases()
            except Exception:
                logger.exception("Error in sandbox ownership renewal loop")

    def _renew_owned_leases(self) -> None:
        """Renew every container this instance believes it owns.

        Covers warm entries as well as active ones: a warm container is still
        ours (we hold it for fast reclaim), so letting its lease lapse would let
        a peer adopt a container we are about to hand back to its thread.

        Only a lease a **peer** now holds means the container is no longer ours;
        a lapsed one is re-established (see ``_refresh_ownership``). Conflating
        the two would evict every live sandbox on this instance the first time
        the store lost its state.
        """
        with self._lock:
            owned_ids = list(self._sandboxes.keys()) + list(self._warm_pool.keys())

        for sandbox_id in owned_ids:
            # Snapshot before the round trip: by the time `renew()` answers LOST,
            # an acquire in this process may already have taken the lease back
            # and promoted the id, and the answer is about the lease we held then.
            epoch = self._acquire_epoch_of(sandbox_id)
            if not self._refresh_ownership(sandbox_id):
                logger.warning("Lost sandbox ownership lease for %s; dropping it from this instance", sandbox_id)
                self._forget_lost_sandbox(sandbox_id, expected_epoch=epoch)

    def _forget_lost_sandbox(self, sandbox_id: str, *, expected_epoch: int | None = None) -> None:
        """Drop a sandbox whose lease we no longer hold, without touching the container.

        The container now belongs to whichever instance holds the lease, so
        stopping it here would be the very cross-instance kill this store exists
        to prevent. Only our host-side handle goes away.

        ``expected_epoch`` guards callers whose "we lost it" decision came from a
        store round trip made outside the lock. An acquire **mid-flight** counts
        too: its ``take()`` can already have made the takeover durable while the
        epoch is still unwritten, so the epoch alone would let a stale decision
        through (see ``_publish_ownership``). An acquire that re-took the lease
        in that window has already handed the sandbox to a turn — and, on the
        reuse path, handed out the *same* tracked client, so no object-identity
        check would notice. Dropping it then closes a client mid-turn and leaves
        the agent holding an id whose tool calls fail until the next turn.
        """
        with self._lock:
            # A warm teardown deliberately keeps its entry visible until the
            # backend stop succeeds. Its own `del:` marker makes `renew()` report
            # LOST, but that is not a peer takeover and must not pop the retained
            # entry — especially when the stop fails and the container remains
            # live for retry/reclaim. The teardown path removes it on success.
            if sandbox_id in self._local_teardown:
                logger.debug("Not dropping sandbox %s: this instance is tearing it down", sandbox_id)
                return
            # The in-flight check is deliberately *not* conditional on
            # `expected_epoch`. Today's epoch-less callers (the two
            # `SandboxBeingDestroyedError` handlers) cannot collide with a
            # publish for the same id — `_publish_ownership` has already cleared
            # the mark by the time they run, and acquires for one id are
            # serialized by the per-thread lock — so this changes no current
            # behaviour. It is here because "no epoch supplied" reading as "no
            # guard at all" is how the next caller of a dangerous primitive gets
            # written; an id being acquired right now must never be dropped.
            if sandbox_id in self._acquire_inflight:
                logger.info("Not dropping sandbox %s: an acquire is publishing ownership for it", sandbox_id)
                return
            if expected_epoch is not None and self._acquire_epoch.get(sandbox_id, 0) != expected_epoch:
                logger.info("Not dropping sandbox %s: this instance re-acquired it after the lease check", sandbox_id)
                return

            sandbox = self._sandboxes.pop(sandbox_id, None)
            self._sandbox_infos.pop(sandbox_id, None)
            self._last_activity.pop(sandbox_id, None)
            self._warm_pool.pop(sandbox_id, None)
            self._acquire_epoch.pop(sandbox_id, None)
            for key, mapped_id in list(self._thread_sandboxes.items()):
                if mapped_id == sandbox_id:
                    del self._thread_sandboxes[key]

        # Close the host-side HTTP client we are dropping (#2872); the container
        # itself stays up for its new owner.
        if sandbox is not None:
            try:
                sandbox.close()
            except Exception as e:
                logger.warning(f"Error closing sandbox {sandbox_id} after losing its lease: {e}")

    def _cleanup_idle_sandboxes(self, idle_timeout: float) -> None:
        current_time = time.time()
        active_to_destroy = []

        with self._lock:
            # Active sandboxes: tracked via _last_activity
            for sandbox_id, last_activity in self._last_activity.items():
                idle_duration = current_time - last_activity
                if idle_duration > idle_timeout:
                    active_to_destroy.append(sandbox_id)
                    logger.info(f"Sandbox {sandbox_id} idle for {idle_duration:.1f}s, marking for destroy")

        # Destroy active sandboxes (re-verify still idle before acting).
        #
        # The re-verify has to happen in the same critical section as the
        # teardown reservation, which is why it is handed to `_destroy_tracked`
        # as a predicate rather than run here. Checking here and destroying
        # afterwards left a window — widened by this PR from a few instructions
        # to a store round trip, since `destroy()` now claims ownership before it
        # untracks — in which a turn re-acquires the sandbox and then has its
        # container stopped underneath it.
        def still_idle(sandbox_id: str) -> bool:
            last_activity = self._last_activity.get(sandbox_id)
            if last_activity is None:
                # Already released or destroyed by another path — skip.
                logger.info(f"Sandbox {sandbox_id} already gone before idle destroy, skipping")
                return False
            if (time.time() - last_activity) < idle_timeout:
                # Re-acquired (activity updated) since the snapshot — skip.
                logger.info(f"Sandbox {sandbox_id} was re-acquired before idle destroy, skipping")
                return False
            return True

        for sandbox_id in active_to_destroy:
            try:
                logger.info(f"Destroying idle sandbox {sandbox_id}")
                self._destroy_tracked(sandbox_id, still_reapable=lambda sid=sandbox_id: still_idle(sid))
            except Exception as e:
                logger.error(f"Failed to destroy idle sandbox {sandbox_id}: {e}")

        self._reap_expired_warm(idle_timeout)

    def _reap_expired_warm(self, idle_timeout: float | None = None) -> None:
        """Destroy warm entries older than ``idle_timeout``, never a peer's live container."""
        timeout = float(self._config.get("idle_timeout", DEFAULT_IDLE_TIMEOUT) if idle_timeout is None else idle_timeout)
        if timeout <= 0:
            return

        now = time.time()
        expired: list[tuple[str, SandboxInfo]] = []
        with self._lock:
            for sandbox_id, (entry, timestamp) in self._warm_pool.items():
                if now - timestamp > timeout:
                    expired.append((sandbox_id, entry))

        # Only drop an entry from the warm pool once we know it is really going
        # away. Popping first would lose the container on a refused or
        # unanswerable claim: still running, no longer tracked by anyone. The
        # deferred pop is why the reservation is needed — the entry stays visible
        # to `_reclaim_warm_pool_sandbox` for the whole stop.
        for sandbox_id, entry in expired:
            self._destroy_warm_entry(sandbox_id, entry, reason="idle_timeout", still_reapable=lambda sid=sandbox_id: sid in self._warm_pool)

    def _evict_oldest_warm(self) -> str | None:
        """Evict the oldest warm entry this instance still owns."""
        with self._lock:
            if not self._warm_pool:
                return None
            # Snapshot oldest-first under the lock; ownership is resolved outside
            # it, since a claim can be a network round trip and the provider lock
            # guards every acquire path.
            candidates = [(sandbox_id, entry) for sandbox_id, (entry, _) in sorted(self._warm_pool.items(), key=lambda item: item[1][1])]

        for sandbox_id, entry in candidates:
            # "Still in the warm pool?" is the reapable check, and it has to run
            # in the same critical section as the reservation — checking it here
            # and reserving afterwards is exactly the window a reclaim slips
            # through. `_destroy_warm_entry` does both under one lock hold.
            if not self._destroy_warm_entry(sandbox_id, entry, reason="replica_enforcement", still_reapable=lambda sid=sandbox_id: sid in self._warm_pool):
                continue
            return sandbox_id

        return None

    # ── Signal handling ──────────────────────────────────────────────────

    def _register_signal_handlers(self) -> None:
        """Register signal handlers for graceful shutdown.

        Handles SIGTERM, SIGINT, and SIGHUP (terminal close) to ensure
        sandbox containers are cleaned up even when the user closes the terminal.
        """
        self._original_sigterm = signal.getsignal(signal.SIGTERM)
        self._original_sigint = signal.getsignal(signal.SIGINT)
        self._original_sighup = signal.getsignal(signal.SIGHUP) if hasattr(signal, "SIGHUP") else None

        def signal_handler(signum, frame):
            self.shutdown()
            if signum == signal.SIGTERM:
                original = self._original_sigterm
            elif hasattr(signal, "SIGHUP") and signum == signal.SIGHUP:
                original = self._original_sighup
            else:
                original = self._original_sigint
            if callable(original):
                original(signum, frame)
            elif original == signal.SIG_DFL:
                signal.signal(signum, signal.SIG_DFL)
                signal.raise_signal(signum)

        try:
            signal.signal(signal.SIGTERM, signal_handler)
            signal.signal(signal.SIGINT, signal_handler)
            if hasattr(signal, "SIGHUP"):
                signal.signal(signal.SIGHUP, signal_handler)
        except ValueError:
            logger.debug("Could not register signal handlers (not main thread)")

    # ── Thread locking (in-process) ──────────────────────────────────────

    def _get_thread_lock(self, thread_id: str, user_id: str) -> threading.Lock:
        """Get or create an in-process lock for a specific user/thread scope."""
        key = self._thread_key(thread_id, user_id)
        with self._lock:
            if key not in self._thread_locks:
                self._thread_locks[key] = threading.Lock()
            return self._thread_locks[key]

    def _sandbox_id_for_thread(self, thread_id: str | None, user_id: str | None) -> str:
        """Return deterministic IDs for thread sandboxes and random IDs otherwise."""
        return self._deterministic_sandbox_id(thread_id, self._effective_acquire_user_id(user_id)) if thread_id else str(uuid.uuid4())[:8]

    def _reuse_in_process_sandbox(self, thread_id: str | None, *, user_id: str | None = None, post_lock: bool = False) -> str | None:
        """Reuse an active in-process sandbox for a thread if one is still tracked."""
        if thread_id is None:
            return None

        effective_user_id = self._effective_acquire_user_id(user_id)
        key = self._thread_key(thread_id, effective_user_id)
        with self._lock:
            if key not in self._thread_sandboxes:
                return None

            existing_id = self._thread_sandboxes[key]
            if self._being_torn_down_locally(existing_id):
                # A reaper thread in this process is stopping this container.
                # Same answer as a peer's `del:` lease: cold-start instead.
                logger.info("Cached sandbox %s is being destroyed by this instance; not reusing it", existing_id)
                return None
            if existing_id in self._sandboxes:
                info = self._sandbox_infos.get(existing_id)
            else:
                del self._thread_sandboxes[key]
                return None

        alive = self._check_tracked_sandbox_alive(existing_id, info) if info is not None else True
        if alive is False:
            self._drop_unhealthy_sandbox(
                existing_id,
                "in-process cache failed health check",
                expected_info=info,
            )
            return None

        with self._lock:
            if self._thread_sandboxes.get(key) != existing_id:
                return None
            if existing_id not in self._sandboxes:
                self._thread_sandboxes.pop(key, None)
                return None

            suffix = " (post-lock check)" if post_lock else ""
            logger.info(f"Reusing in-process sandbox {existing_id} for user/thread {effective_user_id}/{thread_id}{suffix}")
            self._last_activity[existing_id] = time.time()

        # Fail closed: an OwnershipBackendError propagates rather than handing out
        # a sandbox we could not publish ownership for.
        try:
            self._publish_ownership(existing_id)
        except SandboxBeingDestroyedError:
            # A peer is stopping this container. Drop it and let the caller
            # discover-or-create a fresh one instead of handing over a sandbox
            # that is about to disappear.
            logger.info("Cached sandbox %s is being destroyed by another instance; not reusing it", existing_id)
            self._forget_lost_sandbox(existing_id)
            return None

        with self._lock:
            if self._being_torn_down_locally(existing_id):
                # The first reservation check ran before the backend health
                # check and ownership round trip. A local reaper can win while
                # either is in flight, and it deliberately keeps the entry in
                # `_sandboxes` until its destroy claim succeeds. Membership
                # alone therefore cannot prove this id is still safe to return.
                logger.info("Cached sandbox %s was reserved for teardown while publishing ownership; not reusing it", existing_id)
                return None
            if existing_id not in self._sandboxes:
                # Dropped while we were publishing. The intent mark closes the
                # window *inside* `_publish_ownership`, but not the gap before
                # it: until the mark is set a renewal's `LOST` is both current
                # and correct — the peer really did hold the lease — so the
                # forget legitimately runs and closes this client. Returning the
                # id anyway would hand back a sandbox whose `get()` is `None`.
                # Fall through instead; the caller re-discovers and builds a
                # fresh client, and the lease we just took is already ours.
                logger.info("Cached sandbox %s was dropped while publishing ownership; falling through to discovery", existing_id)
                return None
        return existing_id

    def _reclaim_warm_pool_sandbox(
        self,
        thread_id: str | None,
        sandbox_id: str,
        *,
        user_id: str | None = None,
        post_lock: bool = False,
    ) -> str | None:
        """Promote a warm-pool sandbox back to active tracking if available."""
        if thread_id is None:
            return None

        effective_user_id = self._effective_acquire_user_id(user_id)
        key = self._thread_key(thread_id, effective_user_id)
        with self._lock:
            if sandbox_id not in self._warm_pool:
                return None
            if self._being_torn_down_locally(sandbox_id):
                # The entry deliberately stays in `_warm_pool` for the whole stop
                # (so a refused claim does not lose the container), so pool
                # membership alone does not mean it is reclaimable.
                logger.info("Warm-pool sandbox %s is being destroyed by this instance; not reclaiming it", sandbox_id)
                return None

            info, _ = self._warm_pool[sandbox_id]

        alive = self._check_tracked_sandbox_alive(sandbox_id, info)
        if alive is False:
            self._drop_unhealthy_sandbox(
                sandbox_id,
                "warm-pool cache failed health check",
                expected_info=info,
            )
            return None

        # Publish ownership before the warm → active transition: a raise here must
        # not leave the sandbox tracked as active but unowned (a peer would see an
        # orphan and reap it mid-turn). On failure the entry stays warm and this
        # instance keeps its existing lease.
        try:
            self._publish_ownership(sandbox_id)
        except SandboxBeingDestroyedError:
            logger.info("Warm-pool sandbox %s is being destroyed by another instance; not reclaiming it", sandbox_id)
            self._forget_lost_sandbox(sandbox_id)
            return None

        with self._lock:
            if self._being_torn_down_locally(sandbox_id):
                # Re-checked, because the first check was before the round trip.
                # A reaper can reserve *after* our `take()` — the warm entry is
                # still there, since its pop is deferred until the stop returns —
                # then claim `del:` (which succeeds: the lease is ours, we just
                # took it) and stop the container. Whichever pop lands first
                # decides, and if ours does we install a client for a container
                # that is already stopped.
                logger.info("Warm-pool sandbox %s was claimed for teardown while publishing ownership; not reclaiming it", sandbox_id)
                return None
            warm_item = self._warm_pool.pop(sandbox_id, None)
            if warm_item is None:
                return None
            info, _ = warm_item
            sandbox = AioSandbox(id=sandbox_id, base_url=info.sandbox_url)
            self._sandboxes[sandbox_id] = sandbox
            self._sandbox_infos[sandbox_id] = info
            self._last_activity[sandbox_id] = time.time()
            self._thread_sandboxes[key] = sandbox_id

        suffix = " (post-lock check)" if post_lock else f" at {info.sandbox_url}"
        logger.info(f"Reclaimed warm-pool sandbox {sandbox_id} for user/thread {effective_user_id}/{thread_id}{suffix}")
        return sandbox_id

    def _recheck_cached_sandbox(self, thread_id: str, sandbox_id: str, *, user_id: str) -> str | None:
        """Re-check in-memory caches after acquiring the cross-process file lock."""
        return self._reuse_in_process_sandbox(thread_id, user_id=user_id, post_lock=True) or self._reclaim_warm_pool_sandbox(
            thread_id,
            sandbox_id,
            user_id=user_id,
            post_lock=True,
        )

    def _register_discovered_sandbox(self, thread_id: str, info: SandboxInfo, *, user_id: str) -> str:
        """Track a sandbox discovered through the backend.

        Raises:
            SandboxBeingDestroyedError: discovery found the container still
                running, but a peer is stopping it. Deliberately propagated
                rather than swallowed: falling through to create would collide
                with the not-yet-removed container name, and handing this one to
                an agent is exactly the mid-turn death (#4206) the store exists to
                prevent. The window is a peer's in-flight container stop, so the
                thread's next turn discovers nothing and cold-starts cleanly.
        """
        with self._lock:
            if self._being_torn_down_locally(info.sandbox_id):
                # Discovery is the fall-through once the caches miss, so it is
                # also the path a reaper's own untracking opens up. `take()` would
                # only refuse this once the reaper's `del:` claim has landed;
                # until then it succeeds against our own lease.
                raise SandboxBeingDestroyedError(info.sandbox_id)

        sandbox = AioSandbox(id=info.sandbox_id, base_url=info.sandbox_url)
        key = self._thread_key(thread_id, user_id)
        # Ownership first, so a failure cannot leave a tracked-but-unowned sandbox.
        # There is no container to roll back (we did not create it), but the
        # host-side HTTP client constructed above is ours and must not leak —
        # same close-on-failure as `_register_created_sandbox`.
        try:
            self._publish_ownership(info.sandbox_id)
            with self._lock:
                if self._being_torn_down_locally(info.sandbox_id):
                    # The pre-publish reservation check is only an early-out: a
                    # local reaper can reserve the id during the store round
                    # trip. Do not install a client for a container that reaper
                    # has already committed to stopping.
                    raise SandboxBeingDestroyedError(info.sandbox_id)
                # Active and warm are exclusive states, and only this insert can
                # violate that: a warm entry for the same id is stale the moment
                # the id becomes active. Leaving it there gives the container two
                # reapers — `_reap_expired_warm` judges it by the warm timestamp
                # and never looks at `_last_activity`, so it stops a container an
                # agent is actively using while `_sandboxes` still hands out its
                # client.
                self._warm_pool.pop(info.sandbox_id, None)
                self._sandboxes[info.sandbox_id] = sandbox
                self._sandbox_infos[info.sandbox_id] = info
                self._last_activity[info.sandbox_id] = time.time()
                self._thread_sandboxes[key] = info.sandbox_id
        except (OwnershipBackendError, SandboxBeingDestroyedError):
            try:
                sandbox.close()
            except Exception as e:
                logger.warning(f"Error closing sandbox {info.sandbox_id} after failed ownership publish: {e}")
            raise

        logger.info(f"Discovered existing sandbox {info.sandbox_id} for user/thread {user_id}/{thread_id} at {info.sandbox_url}")
        return info.sandbox_id

    def _register_created_sandbox(self, thread_id: str | None, sandbox_id: str, info: SandboxInfo, *, user_id: str | None = None) -> str:
        """Track a newly-created sandbox in the active maps."""
        sandbox = AioSandbox(id=sandbox_id, base_url=info.sandbox_url)
        # Ownership first. Unlike the discover path there IS something to roll
        # back: we just started this container, and an unowned running container
        # is exactly what a peer's reconciliation adopts. Leaking it would hand a
        # peer a container this instance is about to use.
        # SandboxBeingDestroyedError is possible even here: a peer that died
        # mid-stop leaves a teardown marker until its TTL lapses. Roll back on
        # both, or the container we just started is leaked.
        try:
            self._publish_ownership(sandbox_id)
        except (OwnershipBackendError, SandboxBeingDestroyedError):
            logger.error("Could not publish ownership for new sandbox %s; destroying it rather than leaking an unowned container", sandbox_id)
            try:
                sandbox.close()
            except Exception as e:
                logger.warning(f"Error closing sandbox {sandbox_id} during ownership rollback: {e}")
            try:
                self._backend.destroy(info)
            except Exception as e:
                logger.error("Failed to destroy unowned sandbox %s after ownership failure: %s", sandbox_id, e)
            raise

        with self._lock:
            # Same exclusivity rule as the discover path.
            self._warm_pool.pop(sandbox_id, None)
            self._sandboxes[sandbox_id] = sandbox
            self._sandbox_infos[sandbox_id] = info
            self._last_activity[sandbox_id] = time.time()
            if thread_id:
                self._thread_sandboxes[self._thread_key(thread_id, self._effective_acquire_user_id(user_id))] = sandbox_id

        logger.info(f"Created sandbox {sandbox_id} for thread {thread_id} at {info.sandbox_url}")
        return sandbox_id

    def _check_tracked_sandbox_alive(self, sandbox_id: str, info: SandboxInfo) -> bool | None:
        """Return whether a tracked sandbox appears alive, or None if unknown."""
        try:
            return self._backend.is_alive(info)
        except Exception as e:
            logger.warning(f"Failed to check sandbox {sandbox_id} health: {e}")
            return None

    def _remove_tracked_sandbox(
        self,
        sandbox_id: str,
        *,
        expected_info: SandboxInfo | None = None,
    ) -> tuple[Sandbox | None, SandboxInfo | None, bool]:
        """Remove a sandbox from in-process tracking maps.

        When expected_info is provided, removal only happens if the currently
        tracked active or warm-pool entry is the exact info object that was
        checked. This prevents a stale health-check result from deleting a
        freshly recreated sandbox with the same deterministic id.
        """
        thread_keys_to_remove: list[tuple[str, str]] = []

        with self._lock:
            active_info = self._sandbox_infos.get(sandbox_id)
            warm_item = self._warm_pool.get(sandbox_id)
            warm_info = warm_item[0] if warm_item is not None else None
            if expected_info is not None and active_info is not expected_info and warm_info is not expected_info:
                return None, None, False

            sandbox = self._sandboxes.pop(sandbox_id, None)
            info = self._sandbox_infos.pop(sandbox_id, None)
            thread_keys_to_remove = [key for key, sid in self._thread_sandboxes.items() if sid == sandbox_id]
            for key in thread_keys_to_remove:
                del self._thread_sandboxes[key]
            self._last_activity.pop(sandbox_id, None)
            self._acquire_epoch.pop(sandbox_id, None)
            if info is None and sandbox_id in self._warm_pool:
                info, _ = self._warm_pool.pop(sandbox_id)
            else:
                self._warm_pool.pop(sandbox_id, None)

        return sandbox, info, True

    def _drop_unhealthy_sandbox(self, sandbox_id: str, reason: str, *, expected_info: SandboxInfo | None = None) -> None:
        """Remove and destroy a sandbox after a definitive failed health check."""
        # Reserved for the whole path, not just the stop: this one untracks
        # first, so between the untrack and the `del:` claim an acquire misses
        # the caches and falls through to discovery, where `take()` still
        # succeeds against our own lease.
        if not self._reserve_local_teardown(sandbox_id, lambda: True):
            logger.info(f"Skipped dropping sandbox {sandbox_id}: already being torn down by this instance")
            return
        try:
            self._drop_unhealthy_reserved(sandbox_id, reason, expected_info=expected_info)
        finally:
            self._finish_local_teardown(sandbox_id)

    def _drop_unhealthy_reserved(self, sandbox_id: str, reason: str, *, expected_info: SandboxInfo | None = None) -> None:
        sandbox, info, removed = self._remove_tracked_sandbox(sandbox_id, expected_info=expected_info)
        if not removed:
            logger.info(f"Skipped dropping sandbox {sandbox_id}: tracked info changed after health check")
            return

        if sandbox is not None:
            try:
                sandbox.close()
            except Exception as e:
                logger.warning(f"Error closing unhealthy sandbox {sandbox_id}: {e}")

        if info is not None:
            # Gate this like every other reap path. The container failed a
            # definitive health check, but "definitively dead to us" is not proof
            # it is ours: a peer may have replaced the container behind this id,
            # in which case stopping it is the cross-instance kill again.
            if self._claim_ownership(sandbox_id, for_destroy=True):
                try:
                    # Held like the other two stop paths: this one untracks before
                    # claiming, so `_renew_owned_leases` cannot see the id either
                    # and nothing else would refresh the marker. The heartbeat
                    # releases the marker on exit (success or failure), so there is
                    # no caller-side release to race a late refresh.
                    with self._held_teardown_lease(sandbox_id):
                        self._backend.destroy(info)
                except Exception as e:
                    logger.warning(f"Error destroying unhealthy sandbox {sandbox_id}: {e}")
            else:
                logger.info("Not destroying unhealthy sandbox %s: owned by another instance", sandbox_id)

        logger.warning(f"Dropped unhealthy sandbox {sandbox_id}: {reason}")

    def _active_count_locked(self) -> int:
        """Return active AIO sandbox count while ``_lock`` is held."""
        return len(self._sandboxes)

    def _destroy_warm_entry(self, sandbox_id: str, entry: SandboxInfo, *, reason: str, still_reapable: Callable[[], bool]) -> bool:
        """Destroy a warm-pool sandbox using AIO-specific backend logging.

        Claiming for destroy is the exclusion against **peers**: the lease is
        marked as a teardown, so a concurrent acquire on another instance is
        refused and the container cannot be re-acquired between this decision and
        the stop. That pairing is what replaced the per-sandbox flock guard. A
        claim that fails — peer-owned or backend unavailable — fails closed and
        we do not destroy.

        It is *not* an exclusion against this process: `claim()` succeeds against
        our own `own:` lease, so a same-process reclaim that ran before it wins
        the container and this stop lands on a turn already using it. The
        reservation is that half, and it is taken before the claim — after it,
        the entry stays visible in `_warm_pool` for the whole stop, so a reclaim
        would otherwise still find it.

        ``still_reapable`` is required rather than defaulting to unconditional:
        the safe default is the one that makes a new call site think about it,
        and this signature deliberately diverges from ``WarmPoolLifecycleMixin``'s
        hook for that reason. Safe because this provider overrides both mixin
        callers (``_evict_oldest_warm`` / ``_reap_expired_warm``); if those
        overrides were ever dropped, the mixin's call would fail loudly here
        rather than silently reopen the window.

        Returns:
            ``True`` when the container was stopped and the caller should drop
            its warm-pool entry; ``False`` when it is still running.
        """
        if not self._reserve_local_teardown(sandbox_id, still_reapable):
            logger.info("Refusing to destroy warm-pool sandbox %s for %s: reclaimed by this instance", sandbox_id, reason)
            return False

        try:
            if not self._claim_ownership(sandbox_id, for_destroy=True):
                logger.info("Refusing to destroy warm-pool sandbox %s for %s: owned by another instance", sandbox_id, reason)
                return False

            try:
                # The marker must outlast the stop, not the TTL it was written with,
                # and is released by the heartbeat on exit. On a failed stop that
                # release matters just as much — the container is probably still up,
                # so a marker left behind would block its thread from re-acquiring it.
                with self._held_teardown_lease(sandbox_id):
                    self._backend.destroy(entry)
            except Exception as e:
                if reason == "idle_timeout":
                    logger.error(f"Failed to destroy idle warm-pool sandbox {sandbox_id}: {e}")
                elif reason == "replica_enforcement":
                    logger.error(f"Failed to destroy warm-pool sandbox {sandbox_id}: {e}")
                else:
                    logger.error(f"Failed to destroy warm-pool sandbox {sandbox_id} for {reason}: {e}")
                return False

            # Remove the entry here, inside the reservation, rather than leaving
            # it to the caller. Releasing the reservation when the stop returns
            # and popping afterwards leaves a gap in which the container is
            # already stopped, the entry is still in `_warm_pool`, and nothing
            # marks it — so a reclaim picks it up and hands out a dead container.
            # The pop stays deferred relative to the *stop* (a refused or failed
            # stop keeps the entry), just no longer relative to the reservation.
            with self._lock:
                self._warm_pool.pop(sandbox_id, None)
        finally:
            self._finish_local_teardown(sandbox_id)

        if reason == "idle_timeout":
            logger.info(f"Destroyed idle warm-pool sandbox {sandbox_id}")
        elif reason == "replica_enforcement":
            logger.info(f"Destroyed warm-pool sandbox {sandbox_id}")
        else:
            logger.info(f"Destroyed warm-pool sandbox {sandbox_id} for {reason}")
        return True

    # ── Core: acquire / get / release / shutdown ─────────────────────────

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        """Acquire a sandbox environment and return its ID.

        For the same thread_id, this method will return the same sandbox_id
        across multiple turns, multiple processes, and (with shared storage)
        multiple pods.

        Thread-safe with both in-process and cross-process locking.

        Args:
            thread_id: Optional thread ID for thread-specific configurations.

        Returns:
            The ID of the acquired sandbox environment.
        """
        effective_user_id = self._effective_acquire_user_id(user_id)
        if thread_id:
            thread_lock = self._get_thread_lock(thread_id, effective_user_id)
            with thread_lock:
                return self._acquire_internal(thread_id, user_id=effective_user_id)
        else:
            return self._acquire_internal(thread_id, user_id=effective_user_id)

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        """Acquire a sandbox environment without blocking the event loop.

        Mirrors ``acquire()`` while keeping blocking backend operations off the
        event loop and using async-native readiness polling for newly created
        sandboxes.
        """
        effective_user_id = self._effective_acquire_user_id(user_id)
        if thread_id:
            thread_lock = self._get_thread_lock(thread_id, effective_user_id)
            await _acquire_thread_lock_async(thread_lock)
            try:
                return await self._acquire_internal_async(thread_id, user_id=effective_user_id)
            finally:
                thread_lock.release()

        return await self._acquire_internal_async(thread_id, user_id=effective_user_id)

    def _acquire_internal(self, thread_id: str | None, *, user_id: str) -> str:
        """Internal sandbox acquisition with two-layer consistency.

        Layer 1: In-process cache (fastest, covers same-process repeated access)
        Layer 2: Backend discovery (covers containers started by other processes;
                 sandbox_id is deterministic from thread_id so no shared state file
                 is needed — any process can derive the same container name)
        """
        cached_id = self._reuse_in_process_sandbox(thread_id, user_id=user_id)
        if cached_id is not None:
            return cached_id

        # Deterministic ID for thread-specific, random for anonymous
        sandbox_id = self._sandbox_id_for_thread(thread_id, user_id)

        # ── Layer 1.5: Warm pool (container still running, no cold-start) ──
        reclaimed_id = self._reclaim_warm_pool_sandbox(thread_id, sandbox_id, user_id=user_id)
        if reclaimed_id is not None:
            return reclaimed_id

        # ── Layer 2: Backend discovery + create (protected by cross-process lock) ──
        # Use a file lock so that two processes racing to create the same sandbox
        # for the same thread_id serialize here: the second process will discover
        # the container started by the first instead of hitting a name-conflict.
        if thread_id:
            return self._discover_or_create_with_lock(thread_id, sandbox_id, user_id=user_id)

        return self._create_sandbox(thread_id, sandbox_id, user_id=user_id)

    async def _acquire_internal_async(self, thread_id: str | None, *, user_id: str) -> str:
        """Async counterpart to ``_acquire_internal``."""
        cached_id = await asyncio.to_thread(self._reuse_in_process_sandbox, thread_id, user_id=user_id)
        if cached_id is not None:
            return cached_id

        # Deterministic ID for thread-specific, random for anonymous
        sandbox_id = self._sandbox_id_for_thread(thread_id, user_id)

        # ── Layer 1.5: Warm pool (container still running, no cold-start) ──
        reclaimed_id = await asyncio.to_thread(self._reclaim_warm_pool_sandbox, thread_id, sandbox_id, user_id=user_id)
        if reclaimed_id is not None:
            return reclaimed_id

        # ── Layer 2: Backend discovery + create (protected by cross-process lock) ──
        if thread_id:
            return await self._discover_or_create_with_lock_async(thread_id, sandbox_id, user_id=user_id)

        return await self._create_sandbox_async(thread_id, sandbox_id, user_id=user_id)

    def _discover_or_create_with_lock(self, thread_id: str, sandbox_id: str, *, user_id: str | None = None) -> str:
        """Discover an existing sandbox or create a new one under a cross-process file lock.

        The file lock serializes concurrent sandbox creation for the same thread_id
        across multiple processes, preventing container-name conflicts.
        """
        paths = get_paths()
        effective_user_id = self._effective_acquire_user_id(user_id)
        paths.ensure_thread_dirs(thread_id, user_id=effective_user_id)
        lock_path = paths.thread_dir(thread_id, user_id=effective_user_id) / f"{sandbox_id}.lock"

        with open(lock_path, "a", encoding="utf-8") as lock_file:
            locked = False
            try:
                _lock_file_exclusive(lock_file)
                locked = True
                # Re-check in-process caches under the file lock in case another
                # thread in this process won the race while we were waiting.
                cached_id = self._recheck_cached_sandbox(thread_id, sandbox_id, user_id=effective_user_id)
                if cached_id is not None:
                    return cached_id

                # Backend discovery: another process may have created the container.
                discovered = self._backend.discover(sandbox_id)
                if discovered is not None:
                    return self._register_discovered_sandbox(thread_id, discovered, user_id=effective_user_id)

                return self._create_sandbox(thread_id, sandbox_id, user_id=effective_user_id)
            finally:
                if locked:
                    _unlock_file(lock_file)

    async def _discover_or_create_with_lock_async(self, thread_id: str, sandbox_id: str, *, user_id: str | None = None) -> str:
        """Async counterpart to ``_discover_or_create_with_lock``."""
        paths = get_paths()
        effective_user_id = self._effective_acquire_user_id(user_id)
        await asyncio.to_thread(paths.ensure_thread_dirs, thread_id, user_id=effective_user_id)
        lock_path = paths.thread_dir(thread_id, user_id=effective_user_id) / f"{sandbox_id}.lock"

        lock_file = await asyncio.to_thread(_open_lock_file, lock_path)
        locked = False
        try:
            await asyncio.to_thread(_lock_file_exclusive, lock_file)
            locked = True
            # Re-check in-process caches under the file lock in case another
            # thread in this process won the race while we were waiting.
            cached_id = await asyncio.to_thread(self._recheck_cached_sandbox, thread_id, sandbox_id, user_id=effective_user_id)
            if cached_id is not None:
                return cached_id

            # Backend discovery is sync because local discovery may inspect
            # Docker and perform a health check; keep it off the event loop.
            discovered = await asyncio.to_thread(self._backend.discover, sandbox_id)
            if discovered is not None:
                # Registration publishes ownership, which is blocking store IO
                # (filesystem or network depending on the backend) — same reason
                # every other step in this coroutine is offloaded.
                return await asyncio.to_thread(self._register_discovered_sandbox, thread_id, discovered, user_id=effective_user_id)

            return await self._create_sandbox_async(thread_id, sandbox_id, user_id=effective_user_id)
        finally:
            if locked:
                await asyncio.to_thread(_unlock_file, lock_file)
            await asyncio.to_thread(lock_file.close)

    def _create_sandbox(self, thread_id: str | None, sandbox_id: str, *, user_id: str | None = None) -> str:
        """Create a new sandbox via the backend.

        Args:
            thread_id: Optional thread ID.
            sandbox_id: The sandbox ID to use.

        Returns:
            The sandbox_id.

        Raises:
            RuntimeError: If sandbox creation or readiness check fails.
        """
        effective_user_id = self._effective_acquire_user_id(user_id)
        extra_mounts = self._get_extra_mounts(thread_id, user_id=effective_user_id)

        # Enforce replicas: only warm-pool containers count toward eviction budget.
        # Active sandboxes are in use by live threads and must not be forcibly stopped.
        replicas, total = self._replica_count()
        if total >= replicas:
            evicted = self._evict_oldest_warm()
            self._log_replicas_soft_cap(replicas, sandbox_id, evicted)

        info = self._backend.create(thread_id, sandbox_id, extra_mounts=extra_mounts or None, user_id=effective_user_id)

        # Wait for sandbox to be ready
        if not wait_for_sandbox_ready(info.sandbox_url, timeout=60):
            self._backend.destroy(info)
            raise RuntimeError(f"Sandbox {sandbox_id} failed to become ready within timeout at {info.sandbox_url}")

        return self._register_created_sandbox(thread_id, sandbox_id, info, user_id=effective_user_id)

    async def _create_sandbox_async(self, thread_id: str | None, sandbox_id: str, *, user_id: str | None = None) -> str:
        """Async counterpart to ``_create_sandbox``."""
        effective_user_id = self._effective_acquire_user_id(user_id)
        extra_mounts = await asyncio.to_thread(self._get_extra_mounts, thread_id, user_id=effective_user_id)

        # Enforce replicas: only warm-pool containers count toward eviction budget.
        # Active sandboxes are in use by live threads and must not be forcibly stopped.
        replicas, total = self._replica_count()
        if total >= replicas:
            evicted = await asyncio.to_thread(self._evict_oldest_warm)
            self._log_replicas_soft_cap(replicas, sandbox_id, evicted)

        info = await asyncio.to_thread(self._backend.create, thread_id, sandbox_id, extra_mounts=extra_mounts or None, user_id=effective_user_id)

        # Wait for sandbox to be ready without blocking the event loop.
        if not await wait_for_sandbox_ready_async(info.sandbox_url, timeout=60):
            await asyncio.to_thread(self._backend.destroy, info)
            raise RuntimeError(f"Sandbox {sandbox_id} failed to become ready within timeout at {info.sandbox_url}")

        # Registration publishes ownership (blocking store IO), so it is offloaded
        # like every other blocking step on this path.
        return await asyncio.to_thread(self._register_created_sandbox, thread_id, sandbox_id, info, user_id=effective_user_id)

    def get(self, sandbox_id: str) -> Sandbox | None:
        """Get a sandbox by ID. Updates last activity timestamp.

        Stays a pure in-memory lookup: async tool paths call this directly on the
        event loop (``ensure_sandbox_initialized_async``), so it must not touch
        the ownership store — that is blocking filesystem or network IO depending
        on the backend. Ownership is published off the event loop on
        acquire/reclaim and refreshed by the renewal thread (see
        ``_renew_owned_leases``).

        Args:
            sandbox_id: The ID of the sandbox.

        Returns:
            The sandbox instance if found, None otherwise.
        """
        with self._lock:
            sandbox = self._sandboxes.get(sandbox_id)
            if sandbox is not None:
                self._last_activity[sandbox_id] = time.time()
        return sandbox

    def release(self, sandbox_id: str) -> None:
        """Release a sandbox from active use into the warm pool.

        The container is kept running so it can be reclaimed quickly by the same
        thread on its next turn without a cold-start.  The container will only be
        stopped when the replicas limit forces eviction or during shutdown.

        The host-side HTTP client owned by the cached ``AioSandbox`` instance is
        closed before the instance is dropped (#2872). The warm-pool entry only
        stores ``SandboxInfo``, so a fresh ``AioSandbox`` (and a fresh client)
        is constructed if the container is later reclaimed.

        Args:
            sandbox_id: The ID of the sandbox to release.
        """
        info = None
        sandbox = None
        thread_keys_to_remove: list[tuple[str, str]] = []

        with self._lock:
            sandbox = self._sandboxes.pop(sandbox_id, None)
            info = self._sandbox_infos.pop(sandbox_id, None)
            thread_keys_to_remove = [key for key, sid in self._thread_sandboxes.items() if sid == sandbox_id]
            for key in thread_keys_to_remove:
                del self._thread_sandboxes[key]
            self._last_activity.pop(sandbox_id, None)
            # Park in warm pool — container keeps running
            if info and sandbox_id not in self._warm_pool:
                self._warm_pool[sandbox_id] = (info, time.time())

        if sandbox is not None:
            # Defense-in-depth: close() already swallows its own errors; this
            # guard only protects against a future close() that misbehaves, so
            # host-side client cleanup can never block parking in the warm pool.
            try:
                sandbox.close()
            except Exception as e:
                logger.warning(f"Error closing sandbox {sandbox_id} during release: {e}")

        # Keep the lease while warm so a peer cannot adopt+destroy before we
        # reclaim, re-establishing it if it lapsed during a long turn. Never
        # raises: the turn is already over, so a store problem must not surface
        # through after_agent, and the renewal thread (which covers warm entries)
        # is the actual guarantee — this only narrows the window.
        if info is not None:
            # Same staleness as the renewal thread: the refresh is a store round
            # trip, and the thread's next turn can reclaim this warm entry while
            # it is in flight. Only drop it if nothing re-acquired it since.
            epoch = self._acquire_epoch_of(sandbox_id)
            if not self._refresh_ownership(sandbox_id):
                logger.warning("Sandbox %s is owned by another instance; releasing it from this warm pool", sandbox_id)
                self._forget_lost_sandbox(sandbox_id, expected_epoch=epoch)

        logger.info(f"Released sandbox {sandbox_id} to warm pool (container still running)")

    def destroy(self, sandbox_id: str) -> None:
        """Destroy a sandbox: stop the container and free all resources.

        Unlike release(), this actually stops the container.  Use this for
        explicit cleanup, capacity-driven eviction, or shutdown.

        The host-side HTTP client owned by the cached ``AioSandbox`` instance is
        closed alongside backend/container destruction so no client/socket
        resources leak (#2872).

        Args:
            sandbox_id: The ID of the sandbox to destroy.
        """
        self._destroy_tracked(sandbox_id, still_reapable=lambda: True)

    def _destroy_tracked(self, sandbox_id: str, *, still_reapable: Callable[[], bool]) -> None:
        """``destroy()`` with a caller-supplied "is this still reapable" gate.

        Callers that decided to destroy *earlier* (the idle checker) pass their
        own predicate so the decision is re-validated in the same critical
        section that reserves the teardown. ``destroy()`` itself passes a
        constant: an explicit destroy is a decision made now.
        """
        if not self._reserve_local_teardown(sandbox_id, still_reapable):
            logger.info("Skipping destroy of sandbox %s: re-acquired by this instance or already being torn down", sandbox_id)
            return

        try:
            self._destroy_reserved(sandbox_id)
        finally:
            self._finish_local_teardown(sandbox_id)

    def _destroy_reserved(self, sandbox_id: str) -> None:
        # Claim before untracking. The reverse order loses the container on a
        # refused claim: still running, and no longer in any of our maps, so
        # nothing here would ever reap or reclaim it.
        if not self._claim_ownership(sandbox_id, for_destroy=True):
            logger.warning("Refusing to destroy sandbox %s: owned by another instance", sandbox_id)
            return

        sandbox, info, _ = self._remove_tracked_sandbox(sandbox_id)

        if sandbox is not None:
            # Defense-in-depth: close() already swallows its own errors; this
            # guard only protects against a future close() that misbehaves, so
            # host-side client cleanup can never block container destruction.
            try:
                sandbox.close()
            except Exception as e:
                logger.warning(f"Error closing sandbox {sandbox_id} during destroy: {e}")

        if info:
            # The marker must outlast the stop, not the TTL it was written with,
            # and the heartbeat releases it on exit — on both outcomes. On a
            # failed stop the container is probably still up, so a marker left
            # behind would refuse its own thread's `take()` until the TTL lapses;
            # the error still propagates out of the `with` (`shutdown()` logs per
            # sandbox off it), it is just no longer this method's job to release.
            with self._held_teardown_lease(sandbox_id):
                self._backend.destroy(info)
            logger.info(f"Destroyed sandbox {sandbox_id}")
        else:
            # No container to stop, so no teardown lease was held: clear the
            # marker the claim above wrote, so an untracked id cannot leave a
            # lease stuck in `del:`.
            self._release_ownership(sandbox_id)

    def shutdown(self) -> None:
        """Shutdown all sandboxes. Thread-safe and idempotent."""
        with self._lock:
            if self._shutdown_called:
                return
            self._shutdown_called = True
            sandbox_ids = list(self._sandboxes.keys())
            warm_items = list(self._warm_pool.items())
            self._warm_pool.clear()

        self._stop_idle_checker()
        # Stop renewing before destroying: the destroy paths claim ownership
        # themselves, and a renewal racing them only re-publishes leases we are
        # about to drop.
        self._stop_lease_renewal()

        logger.info(f"Shutting down {len(sandbox_ids)} active + {len(warm_items)} warm-pool sandbox(es)")

        for sandbox_id in sandbox_ids:
            try:
                self.destroy(sandbox_id)
            except Exception as e:
                logger.error(f"Failed to destroy sandbox {sandbox_id} during shutdown: {e}")

        for sandbox_id, (info, _) in warm_items:
            # Route through _destroy_warm_entry so the ownership claim and the
            # container stop stay together, as on the idle path. Unconditional
            # here: the entries were removed from `_warm_pool` under the lock
            # above, so the pool-membership predicate the other callers use would
            # refuse every one of them.
            self._destroy_warm_entry(sandbox_id, info, reason="shutdown", still_reapable=lambda: True)

        try:
            self._ownership.close()
        except Exception as e:
            logger.warning(f"Error closing sandbox ownership store during shutdown: {e}")
