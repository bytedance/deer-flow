"""``E2BSandboxProvider`` — DeerFlow :class:`SandboxProvider` for e2b cloud.

Configuration is read from :class:`SandboxConfig`. E2B reports unknown
provider fields during startup.

.. code-block:: yaml

    sandbox:
      use: deerflow.community.e2b_sandbox:E2BSandboxProvider
      api_key: $E2B_API_KEY            # required (or via E2B_API_KEY env var)
      template: code-interpreter-v1     # default: e2b code-interpreter template
      domain: e2b.dev                  # optional; for self-hosted e2b
      idle_timeout: 1800               # forwarded to ``set_timeout``
      replicas: 3                      # max capacity (active + warm)
      overflow_policy: wait            # wait | reject | burst (default: wait)
      acquire_timeout: 30              # seconds for ``wait`` policy (default: 30)
      burst_limit: 2                   # extra slots for ``burst`` policy (default: 0)
      reconciliation_interval_seconds: 60
      reconciliation_grace_seconds: 120
      reconciliation_orphan_ttl_seconds: 3600
      reconciliation_max_pages: 10
      reconciliation_max_items: 200
      reconciliation_max_seconds: 15
      ownership:
        type: redis                    # shares ownership and capacity across Gateways
        redis_url: redis://redis:6379/0
      mounts:                          # one-shot uploads on sandbox start
        - host_path: /data/skills
          container_path: /home/user/skills
          read_only: true
      environment:                     # forwarded as e2b ``envs`` on create
        OPENAI_API_KEY: $OPENAI_API_KEY
"""

from __future__ import annotations

import asyncio
import atexit
import hashlib
import json
import logging
import os
import shlex
import signal
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import partial
from pathlib import Path
from typing import Any

from e2b import SandboxQuery
from e2b_code_interpreter import Sandbox as E2BClientSandbox

from deerflow.config import get_app_config
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.sandbox.exceptions import SandboxCapacityExceededError
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider

from ..aio_sandbox.ownership import (
    OwnershipBackendError,
    RenewOutcome,
    SandboxOwnershipStore,
    compute_lease_ttl,
    generate_owner_id,
    make_sandbox_ownership_store,
    resolve_ownership_config,
)
from .capacity import (
    CapacityBackendError,
    ReserveStatus,
    make_e2b_capacity_store,
)
from .e2b_sandbox import DEFAULT_E2B_HOME_DIR, E2BSandbox, _is_sandbox_gone_error

logger = logging.getLogger(__name__)


# ── Defaults ─────────────────────────────────────────────────────────────
DEFAULT_TEMPLATE = "code-interpreter-v1"  # the public e2b code-interpreter template
DEFAULT_IDLE_TIMEOUT = 1800  # 30 minutes; passed to ``Sandbox.set_timeout``.
DEFAULT_REPLICAS = 3
DEFAULT_OVERFLOW_POLICY = "wait"  # wait | reject | burst
DEFAULT_ACQUIRE_TIMEOUT = 30  # seconds for wait policy
DEFAULT_RECONCILIATION_INTERVAL_SECONDS = 60.0
DEFAULT_RECONCILIATION_GRACE_SECONDS = 120.0
DEFAULT_RECONCILIATION_ORPHAN_TTL_SECONDS = 3600.0
DEFAULT_RECONCILIATION_MAX_PAGES = 10
DEFAULT_RECONCILIATION_MAX_ITEMS = 200
DEFAULT_RECONCILIATION_MAX_SECONDS = 15.0
# Twice the E2B SDK's 60-second create request timeout. Short ownership lease
# settings must not make an in-flight create look abandoned.
MIN_CAPACITY_RESERVATION_SECONDS = 120.0
# Hard upper bound for ``set_timeout`` (e2b currently caps at 24h on the
# free plan; passing an excessive value is rejected by the control-plane).
MAX_E2B_TIMEOUT = 24 * 60 * 60
# These limits bound Gateway work during each E2B mount upload.
_MAX_MOUNT_FILE_SIZE = 100 * 1024 * 1024
_MAX_MOUNT_TOTAL_SIZE = 512 * 1024 * 1024
_MAX_MOUNT_FILES = 2000

# Metadata keys we attach to every sandbox so we can discover ours via
# ``Sandbox.list(query={...})`` from any gateway process.
META_KEY_USER = "deer_flow_user"
META_KEY_THREAD = "deer_flow_thread"
META_KEY_PROVIDER = "deer_flow_provider"
META_KEY_GATEWAY = "deer_flow_gateway"
META_KEY_CREATED_AT = "deer_flow_created_at"
META_KEY_CAPACITY_LEDGER = "deer_flow_capacity_ledger"
META_KEY_CAPACITY_RESERVATION = "deer_flow_capacity_reservation"
META_VAL_PROVIDER = "e2b_sandbox_provider"
E2B_EXTRA_CONFIG_KEYS = frozenset(
    {
        "api_key",
        "domain",
        "home_dir",
        "reconciliation_grace_seconds",
        "reconciliation_interval_seconds",
        "reconciliation_max_items",
        "reconciliation_max_pages",
        "reconciliation_max_seconds",
        "reconciliation_orphan_ttl_seconds",
        "template",
    }
)


@dataclass
class ReconciliationStats:
    """Bounded reconciliation outcome, also suitable for metrics/logging."""

    discovered: int = 0
    adopted: int = 0
    duplicates: int = 0
    deferred: int = 0
    killed: int = 0
    dead: int = 0
    budget_exhausted: bool = False


class E2BSandboxProvider(SandboxProvider):
    """Sandbox provider backed by the e2b code-interpreter cloud SDK."""

    # e2b sandboxes are remote: there is no shared host filesystem with the
    # gateway, so the framework must explicitly sync uploaded files (the
    # remote backend in AioSandboxProvider sets the same flag).
    uses_thread_data_mounts = False
    needs_upload_permission_adjustment = True

    # ── Construction & config ────────────────────────────────────────────

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Active sandboxes, keyed by DeerFlow-side sandbox id (== e2b id).
        self._sandboxes: dict[str, E2BSandbox] = {}
        # (user_id, thread_id) -> sandbox id for fast in-process lookup.
        self._thread_sandboxes: dict[tuple[str, str], str] = {}
        # Per-(user,thread) lock to serialise acquire() and release() state
        # transitions without holding the provider-wide lock across remote IO.
        self._thread_locks: dict[tuple[str, str], threading.Lock] = {}
        # Warm pool: released sandboxes whose remote micro-VM is still alive.
        # ``OrderedDict`` maintains insertion / move_to_end order for LRU.
        self._warm_pool: OrderedDict[str, tuple[str, float]] = OrderedDict()
        # Evictions with unknown remote state. Each id keeps its transition
        # slot until a later eviction attempt confirms destruction.
        self._eviction_tombstones: set[str] = set()
        # IDs currently reconnecting or stopping. This grants one retry owner
        # to each tombstone and prevents a second call from freeing its slot.
        self._evictions_in_progress: set[str] = set()
        # Remote IDs that are between tracked lifecycle states. Shutdown uses
        # this set to retain cleanup visibility during remote calls.
        self._remote_ops_in_progress: set[str] = set()
        # Discovery can find a VM that another Gateway still uses.
        # Shutdown closes these clients but does not destroy their VMs.
        self._unowned_remote_ops_in_progress: set[str] = set()
        # In-flight creates that have reserved capacity but not yet committed
        # to ``_sandboxes``.  Guarded by ``_lock``.
        self._reserved_slots = 0
        self._transitioning_slots = 0
        self._capacity_cond = threading.Condition(self._lock)
        self._shutdown_called = False
        self._owned_sandbox_ids: set[str] = set()
        self._acquire_inflight: set[str] = set()
        self._orphan_first_seen: dict[str, float] = {}
        self._maintenance_stop = threading.Event()
        self._lease_thread: threading.Thread | None = None
        self._reconcile_thread: threading.Thread | None = None
        self._owner_id = generate_owner_id()

        self._config = self._load_config()
        acquire_workers = max(4, min(32, self._capacity_limit() + 1))
        self._acquire_executor = ThreadPoolExecutor(
            max_workers=acquire_workers,
            thread_name_prefix="e2b-sandbox-acquire",
        )
        self._ownership_config = resolve_ownership_config(
            self._config.get("ownership"),
            stream_bridge=self._config.get("stream_bridge"),
        )
        self._ownership: SandboxOwnershipStore = make_sandbox_ownership_store(
            self._ownership_config,
            owner_id=self._owner_id,
        )
        self._deployment_capacity = make_e2b_capacity_store(
            self._ownership_config,
            hard_limit=self._capacity_limit(),
        )
        if not self._ownership.supports_cross_process:
            logger.warning("E2B sandbox ownership is process-local. Multi-worker gateways must configure sandbox.ownership.type: redis for safe reconciliation.")

        atexit.register(self.shutdown)
        self._register_signal_handlers()
        self._start_maintenance_threads()

    def _load_config(self) -> dict[str, Any]:
        """Read e2b options off ``SandboxConfig`` (``extra="allow"``)."""
        sandbox_config = get_app_config().sandbox
        unknown_keys = sorted(set(getattr(sandbox_config, "model_extra", None) or {}) - E2B_EXTRA_CONFIG_KEYS)
        if unknown_keys:
            logger.warning(
                "E2BSandboxProvider: unknown sandbox config fields: %s",
                ", ".join(unknown_keys),
            )

        def _opt(name: str, default: Any = None) -> Any:
            return getattr(sandbox_config, name, default)

        api_key = _opt("api_key") or os.environ.get("E2B_API_KEY")
        if not api_key:
            logger.warning("E2BSandboxProvider: no api_key configured (set sandbox.api_key in config.yaml or the E2B_API_KEY environment variable). The SDK will fail on the first acquire() until this is provided.")

        idle_timeout = _opt("idle_timeout")
        if idle_timeout is None:
            idle_timeout = DEFAULT_IDLE_TIMEOUT
        idle_timeout = max(0, min(int(idle_timeout), MAX_E2B_TIMEOUT))

        replicas = _opt("replicas")
        replicas = DEFAULT_REPLICAS if replicas is None else int(replicas)

        overflow_policy = _opt("overflow_policy") or DEFAULT_OVERFLOW_POLICY
        if overflow_policy not in ("wait", "reject", "burst"):
            logger.warning("E2BSandboxProvider: invalid overflow_policy %r; falling back to %r", overflow_policy, DEFAULT_OVERFLOW_POLICY)
            overflow_policy = DEFAULT_OVERFLOW_POLICY

        acquire_timeout = _opt("acquire_timeout")
        if acquire_timeout is None:
            acquire_timeout = DEFAULT_ACQUIRE_TIMEOUT
        else:
            acquire_timeout = max(1, int(acquire_timeout))

        burst_limit_raw = _opt("burst_limit")
        burst_limit = max(0, int(burst_limit_raw)) if burst_limit_raw is not None else 0
        if overflow_policy == "burst" and burst_limit == 0:
            logger.warning("E2BSandboxProvider: overflow_policy is 'burst' but burst_limit is 0; falling back to 'reject'")
            overflow_policy = "reject"

        return {
            "api_key": api_key,
            "template": _opt("template") or _opt("image") or DEFAULT_TEMPLATE,
            "domain": _opt("domain"),
            "home_dir": _opt("home_dir") or DEFAULT_E2B_HOME_DIR,
            "idle_timeout": idle_timeout,
            "replicas": replicas,
            "overflow_policy": overflow_policy,
            "acquire_timeout": acquire_timeout,
            "burst_limit": burst_limit,
            "mounts": _opt("mounts") or [],
            "environment": self._resolve_env_vars(_opt("environment") or {}),
            "ownership": _opt("ownership"),
            "stream_bridge": getattr(get_app_config(), "stream_bridge", None),
            "reconciliation_interval_seconds": max(
                1.0,
                float(_opt("reconciliation_interval_seconds", DEFAULT_RECONCILIATION_INTERVAL_SECONDS)),
            ),
            "reconciliation_grace_seconds": max(
                0.0,
                float(_opt("reconciliation_grace_seconds", DEFAULT_RECONCILIATION_GRACE_SECONDS)),
            ),
            "reconciliation_orphan_ttl_seconds": max(
                0.0,
                float(_opt("reconciliation_orphan_ttl_seconds", DEFAULT_RECONCILIATION_ORPHAN_TTL_SECONDS)),
            ),
            "reconciliation_max_pages": max(
                1,
                int(_opt("reconciliation_max_pages", DEFAULT_RECONCILIATION_MAX_PAGES)),
            ),
            "reconciliation_max_items": max(
                1,
                int(_opt("reconciliation_max_items", DEFAULT_RECONCILIATION_MAX_ITEMS)),
            ),
            "reconciliation_max_seconds": max(
                0.1,
                float(_opt("reconciliation_max_seconds", DEFAULT_RECONCILIATION_MAX_SECONDS)),
            ),
        }

    @staticmethod
    def _resolve_env_vars(env_config: dict[str, str]) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for key, value in env_config.items():
            if isinstance(value, str) and value.startswith("$"):
                resolved[key] = os.environ.get(value[1:], "")
            else:
                resolved[key] = "" if value is None else str(value)
        return resolved

    def _get_sandbox_cls(self) -> type[E2BClientSandbox]:
        """Return the e2b SDK Sandbox class."""
        return E2BClientSandbox

    # ── Identity helpers ────────────────────────────────────────────────

    @staticmethod
    def _effective_acquire_user_id(user_id: str | None) -> str:
        return user_id or get_effective_user_id()

    @staticmethod
    def _thread_key(thread_id: str, user_id: str) -> tuple[str, str]:
        return (user_id, thread_id)

    @staticmethod
    def _stable_seed(thread_id: str, user_id: str) -> str:
        return hashlib.sha256(f"{user_id}:{thread_id}".encode()).hexdigest()[:16]

    def _metadata_matches_capacity_ledger(
        self,
        metadata: dict[str, Any],
    ) -> bool:
        """Include this ledger and legacy sandboxes that predate the tag."""
        store = self._deployment_capacity
        if store is None:
            return True
        remote_ledger = metadata.get(META_KEY_CAPACITY_LEDGER)
        return remote_ledger in (None, "", store.key)

    @staticmethod
    def _capacity_reservation_from_metadata(
        metadata: dict[str, Any],
    ) -> str | None:
        token = metadata.get(META_KEY_CAPACITY_RESERVATION)
        return token if isinstance(token, str) and token else None

    # ── Signal / shutdown handling ───────────────────────────────────────

    def _register_signal_handlers(self) -> None:
        try:
            self._original_sigterm = signal.getsignal(signal.SIGTERM)
            self._original_sigint = signal.getsignal(signal.SIGINT)
            self._original_sighup = signal.getsignal(signal.SIGHUP) if hasattr(signal, "SIGHUP") else None
        except (ValueError, OSError):
            return

        def _handler(signum, frame):
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

        for sig_name in ("SIGTERM", "SIGINT", "SIGHUP"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                logger.debug(
                    "Could not register %s handler (likely not running on main thread)",
                    sig_name,
                )

    def _get_thread_lock(self, thread_id: str, user_id: str) -> threading.Lock:
        key = self._thread_key(thread_id, user_id)
        with self._lock:
            lock = self._thread_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._thread_locks[key] = lock
            return lock

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        effective_user_id = self._effective_acquire_user_id(user_id)
        if thread_id:
            with self._get_thread_lock(thread_id, effective_user_id):
                return self._acquire_internal(thread_id, user_id=effective_user_id)
        return self._acquire_internal(thread_id, user_id=effective_user_id)

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        effective_user_id = self._effective_acquire_user_id(user_id)
        loop = asyncio.get_running_loop()
        acquire = partial(self.acquire, thread_id, user_id=effective_user_id)
        return await loop.run_in_executor(self._acquire_executor, acquire)

    def _acquire_internal(self, thread_id: str | None, *, user_id: str) -> str:
        if thread_id:
            cached = self._reuse_in_process_sandbox(thread_id, user_id=user_id)
            if cached is not None:
                return cached

        if thread_id:
            reclaimed = self._reclaim_warm_pool_sandbox(thread_id, user_id=user_id)
            if reclaimed is not None:
                return reclaimed

        if thread_id:
            discovered = self._discover_remote_sandbox(thread_id, user_id=user_id)
            if discovered is not None:
                return discovered
        return self._create_sandbox(thread_id, user_id=user_id)

    def _reuse_in_process_sandbox(self, thread_id: str, *, user_id: str) -> str | None:
        key = self._thread_key(thread_id, user_id)
        with self._lock:
            sid = self._thread_sandboxes.get(key)
            if sid is None:
                return None
            sandbox = self._sandboxes.get(sid)
            if sandbox is None:
                # The mapping pointed at a dead entry — clean it up.
                self._thread_sandboxes.pop(key, None)
                return None

        # Drop the cached entry if the e2b VM has been reaped (control-plane
        # idle-timeout, manual pause, etc.).  We learn about this either via
        # ``execute_command`` flipping ``is_dead`` from a previous tool call,
        # or by an explicit ping below — without this check the agent loops
        # for ever on "sandbox not found" errors before the next acquire
        # finally rebuilds the sandbox.
        if sandbox.is_dead or not sandbox.ping():
            logger.warning(
                "In-process e2b sandbox %s is dead (reaped by e2b control plane); evicting cache so acquire() can rebuild a fresh sandbox",
                sid,
            )
            with self._lock:
                self._sandboxes.pop(sid, None)
                self._thread_sandboxes.pop(key, None)
            try:
                sandbox.close()
            except Exception:
                pass
            self._release_deployment_sandbox(sid)
            return None

        try:
            self._refresh_remote_timeout(sandbox.client)
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("Failed to refresh timeout on reuse: %s", e)
        self._publish_ownership(sid)
        with self._lock:
            self._acquire_inflight.discard(sid)

        logger.info(
            "Reusing in-process e2b sandbox %s for user/thread %s/%s",
            sid,
            user_id,
            thread_id,
        )
        return sid

    def _reclaim_warm_pool_sandbox(self, thread_id: str, *, user_id: str) -> str | None:
        """Reclaim a warm-pool sandbox, holding a transitioning slot throughout.

        The warm-pool entry is popped and a transitioning slot is taken
        immediately.  The slot is committed to active when the sandbox is
        registered in ``_sandboxes``, or freed if the reclaim fails.
        If the provider shut down during the transition, the VM is killed.
        """
        seed = self._stable_seed(thread_id, user_id)
        with self._lock:
            target_id = next(
                (sid for sid, (s, _) in self._warm_pool.items() if s == seed),
                None,
            )
            if target_id is None:
                return None
            self._warm_pool.pop(target_id)
            self._begin_transition_locked()
            self._remote_ops_in_progress.add(target_id)

        try:
            client = self._reconnect_live_client(self._get_sandbox_cls(), target_id)
        except Exception as e:
            logger.warning(
                "Warm-pool e2b sandbox %s failed to reconnect, dropping: %s",
                target_id,
                e,
            )
            self._complete_transition_remote_op(target_id, remote_destroyed=False)
            return None

        if client is None:
            logger.warning(
                "Warm-pool e2b sandbox %s is no longer alive (reaped by control plane); dropping and falling back to create",
                target_id,
            )
            self._complete_transition_remote_op(target_id, remote_destroyed=True)
            return None

        try:
            self._publish_ownership(target_id)
        except Exception:
            self._complete_transition_remote_op(target_id, remote_destroyed=False)
            self._safe_close_client(client)
            raise

        self._refresh_remote_timeout(client)
        bootstrap_error, remote_destroyed = self._bootstrap_or_discard(client, target_id)
        if bootstrap_error is not None:
            self._complete_transition_remote_op(target_id, remote_destroyed=remote_destroyed)
            return None

        discard_after_shutdown = False
        with self._lock:
            if self._shutdown_called:
                logger.info(
                    "Provider shut down during reclaim of sandbox %s; killing VM",
                    target_id,
                )
                discard_after_shutdown = True
            else:
                self._remote_ops_in_progress.discard(target_id)
                self._register_connected_sandbox(target_id, client, thread_id=thread_id, user_id=user_id)
                self._end_transition_locked()

        if discard_after_shutdown:
            if self._claim_ownership(target_id, for_destroy=True):
                self._kill_client(client)
                self._release_ownership(target_id)
            self._safe_close_client(client)
            return None
        logger.info(
            "Reclaimed warm-pool e2b sandbox %s for user/thread %s/%s",
            target_id,
            user_id,
            thread_id,
        )
        return target_id

    def _discover_remote_sandbox(self, thread_id: str, *, user_id: str) -> str | None:
        """Look for a running e2b sandbox tagged with this (user, thread).

        Other gateway processes (or this process before a restart) may have
        created the sandbox already.  e2b sandboxes survive across reconnects
        as long as the server-side timeout has not fired.
        """
        sandbox_cls = self._get_sandbox_cls()
        seed = self._stable_seed(thread_id, user_id)
        entries, _, _ = self._list_remote_entries(
            {
                META_KEY_PROVIDER: META_VAL_PROVIDER,
                META_KEY_USER: user_id,
                META_KEY_THREAD: thread_id,
            }
        )
        candidates = sorted(
            (
                (sandbox_id, metadata)
                for entry in entries
                if (sandbox_id := self._entry_id(entry)) and (metadata := self._entry_metadata(entry)).get(META_KEY_USER) == user_id and metadata.get(META_KEY_THREAD) == thread_id and self._metadata_matches_capacity_ledger(metadata)
            ),
            key=lambda item: (item[1].get(META_KEY_CREATED_AT, ""), item[0]),
        )
        for target_id, metadata in candidates:
            adopted = self._adopt_remote_candidate(
                sandbox_cls,
                target_id,
                thread_id=thread_id,
                user_id=user_id,
                seed=seed,
                capacity_reservation=(self._capacity_reservation_from_metadata(metadata)),
            )
            if adopted is not None:
                return adopted
        return None

    def _adopt_remote_candidate(
        self,
        sandbox_cls: type[E2BClientSandbox],
        target_id: str,
        *,
        thread_id: str,
        user_id: str,
        seed: str,
        capacity_reservation: str | None = None,
    ) -> str | None:
        """Try to adopt one discovered candidate without harming peer-owned VMs."""

        try:
            client = self._reconnect_live_client(sandbox_cls, target_id)
        except Exception as e:
            logger.warning(
                "Discovered e2b sandbox %s could not be reconnected: %s",
                target_id,
                e,
            )
            return None

        if client is None:
            logger.warning(
                "Discovered e2b sandbox %s is no longer alive; falling back to create",
                target_id,
            )
            return None

        try:
            self._track_deployment_sandbox(
                target_id,
                reservation_token=capacity_reservation,
            )
            self._reserve_capacity(
                thread_id,
                user_id,
                remote_id=target_id,
                remote_owned=False,
            )
        except SandboxCapacityExceededError as error:
            if error.reason == "shutdown":
                logger.info(
                    "Discovered e2b sandbox %s while the provider is shutting down; not adopting it",
                    target_id,
                )
            else:
                logger.info(
                    "Discovered e2b sandbox %s, but capacity is full; not adopting it",
                    target_id,
                )
            self._safe_close_client(client)
            raise

        with self._lock:
            shutdown_before_ownership = self._shutdown_called
        if shutdown_before_ownership:
            self._complete_reserved_remote_op(target_id, remote_destroyed=False)
            self._safe_close_client(client)
            return None

        try:
            self._publish_ownership(target_id)
        except Exception:
            self._complete_reserved_remote_op(target_id, remote_destroyed=False)
            self._safe_close_client(client)
            raise

        self._refresh_remote_timeout(client)
        bootstrap_error, remote_destroyed = self._bootstrap_or_discard(client, target_id)
        if bootstrap_error is not None:
            self._complete_reserved_remote_op(target_id, remote_destroyed=remote_destroyed)
            return None

        discard_after_shutdown = False
        with self._lock:
            if self._shutdown_called:
                discard_after_shutdown = True
            else:
                self._unowned_remote_ops_in_progress.discard(target_id)
                self._register_connected_sandbox(target_id, client, thread_id=thread_id, user_id=user_id)
                self._commit_capacity()
        if discard_after_shutdown:
            if self._claim_ownership(target_id, for_destroy=True):
                self._kill_client(client)
                self._release_ownership(target_id)
            self._safe_close_client(client)
            return None
        logger.info(
            "Discovered remote e2b sandbox %s for user/thread %s/%s (seed=%s)",
            target_id,
            user_id,
            thread_id,
            seed,
        )
        return target_id

    # ── Capacity reservation ──────────────────────────────────────────────
    #
    # Every sandbox holds one *slot*.  A slot is in exactly one of four states:
    #
    #   reserved      _reserved_slots             create in flight, not yet in _sandboxes
    #   active        _sandboxes                  serving a thread
    #   warm          _warm_pool                  released, parked for reuse
    #   transitioning _transitioning_slots        being moved between states
    #
    # Total = _reserved_slots + len(_sandboxes) + len(_warm_pool) + _transitioning_slots
    #
    # The ``transitioning`` bucket closes the window where a sandbox has been
    # removed from ``_sandboxes`` (or ``_warm_pool``) but not yet parked in its
    # destination.  Without it, ``_release_internal`` (active → warm),
    # ``_reclaim_warm_pool_sandbox`` (warm → active), and ``_evict_oldest_warm``
    # (warm → destroyed) all temporarily appear to have *zero* slots occupied,
    # letting a concurrent acquire reserve a new slot and exceed the configured
    # ``replicas``.

    def _total_capacity_used_locked(self) -> int:
        """Return reserved + active + warm + transitioning (``_lock`` must be held)."""
        return self._reserved_slots + len(self._sandboxes) + len(self._warm_pool) + self._transitioning_slots

    def _capacity_limit(self) -> int:
        """Hard ceiling for reserved + active + warm + transitioning slots."""
        replicas = int(self._config["replicas"])
        if self._config["overflow_policy"] == "burst":
            return replicas + int(self._config["burst_limit"])
        return replicas

    def _begin_transition_locked(self) -> None:
        """Increment the transitioning counter (``_lock`` must be held).

        Call before removing a sandbox from ``_sandboxes`` or ``_warm_pool``
        so the slot is still counted while the transition is in flight.
        """
        self._transitioning_slots += 1

    def _end_transition_locked(self) -> None:
        """Decrement the transitioning counter (``_lock`` must be held).

        Call after the transition completes — either the slot has been parked
        in its destination dict or the sandbox has been destroyed.
        """
        if self._transitioning_slots > 0:
            self._transitioning_slots -= 1
            self._capacity_cond.notify_all()

    def _free_transitioning_slot(self) -> None:
        """Release a transitioning slot after the sandbox was destroyed."""
        with self._lock:
            self._end_transition_locked()

    def _capacity_reservation_max_age_ms(self) -> int:
        configured = compute_lease_ttl(self._ownership_config) + float(self._config["reconciliation_grace_seconds"])
        return int(max(configured, MIN_CAPACITY_RESERVATION_SECONDS) * 1_000)

    def _capacity_error(
        self,
        message: str,
        *,
        reason: str = "capacity",
    ) -> SandboxCapacityExceededError:
        with self._lock:
            return SandboxCapacityExceededError(
                message,
                active=len(self._sandboxes),
                warm=len(self._warm_pool),
                reserved=self._reserved_slots,
                replicas=int(self._config["replicas"]),
                reason=reason,
            )

    def _track_deployment_sandbox(
        self,
        sandbox_id: str,
        *,
        reservation_token: str | None = None,
        required: bool = True,
    ) -> None:
        store = self._deployment_capacity
        if store is None:
            return
        try:
            store.track(
                sandbox_id,
                reservation_token=reservation_token,
            )
        except CapacityBackendError as error:
            if required:
                raise self._capacity_error(
                    f"Deployment-wide E2B capacity is unavailable; cannot safely track sandbox {sandbox_id}",
                    reason="capacity_backend",
                ) from error
            logger.warning(
                "Could not track E2B sandbox %s in deployment capacity; reconciliation will retry: %s",
                sandbox_id,
                error,
            )

    def _release_deployment_sandbox(self, sandbox_id: str) -> None:
        store = self._deployment_capacity
        if store is None:
            return
        try:
            store.release(sandbox_id)
        except CapacityBackendError as error:
            logger.warning(
                "Could not release deployment capacity for destroyed E2B sandbox %s; reconciliation will retry: %s",
                sandbox_id,
                error,
            )

    def _reserve_capacity(
        self,
        thread_id: str | None,
        user_id: str,
        *,
        remote_id: str | None = None,
        remote_owned: bool = True,
    ) -> str | None:
        """Reserve local capacity, then deployment capacity for a new VM."""
        store = self._deployment_capacity
        policy = self._config["overflow_policy"]
        timeout = float(self._config["acquire_timeout"])
        deadline = time.monotonic() + timeout
        token = uuid.uuid4().hex if store is not None and remote_id is None else None

        while True:
            self._reserve_local_capacity(
                thread_id,
                user_id,
                remote_id=remote_id,
                remote_owned=remote_owned,
                deadline=deadline,
            )
            if store is None or remote_id is not None:
                return token

            assert token is not None
            backend_error = None
            try:
                status = store.reserve(token)
            except CapacityBackendError as error:
                backend_error = error
                status = None
            if status is ReserveStatus.GRANTED:
                return token
            self._release_capacity()
            if status is ReserveStatus.FULL and self._evict_oldest_warm() is not None:
                continue

            if policy != "wait":
                if backend_error is not None:
                    raise self._capacity_error(
                        "Deployment-wide E2B capacity is unavailable",
                        reason="capacity_backend",
                    ) from backend_error
                if status is ReserveStatus.NOT_READY:
                    raise self._capacity_error(
                        "Deployment-wide E2B capacity is initializing",
                        reason="capacity_initializing",
                    )
                raise self._capacity_error("Deployment-wide E2B capacity is full")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise self._capacity_error(f"Timed out after {timeout}s waiting for deployment-wide E2B capacity")
            with self._capacity_cond:
                self._capacity_cond.wait(timeout=min(remaining, 1.0))

    def _reserve_local_capacity(
        self,
        thread_id: str | None,
        user_id: str,
        *,
        remote_id: str | None = None,
        remote_owned: bool = True,
        deadline: float | None = None,
    ) -> None:
        """Acquire the existing process-local lifecycle slot."""
        policy = self._config["overflow_policy"]
        timeout = float(self._config["acquire_timeout"])
        deadline = deadline or time.monotonic() + timeout

        while True:
            with self._lock:
                if self._shutdown_called:
                    raise SandboxCapacityExceededError(
                        "Sandbox provider is shutting down; cannot acquire capacity",
                        replicas=int(self._config["replicas"]),
                        retry_after_seconds=30.0,
                        reason="shutdown",
                    )

            with self._lock:
                if self._shutdown_called:
                    raise SandboxCapacityExceededError(
                        "Sandbox provider is shutting down; cannot acquire capacity",
                        replicas=int(self._config["replicas"]),
                        retry_after_seconds=30.0,
                        reason="shutdown",
                    )
                cap = self._capacity_limit()
                if self._total_capacity_used_locked() < cap:
                    self._reserved_slots += 1
                    if remote_id is not None:
                        remote_ops = self._remote_ops_in_progress if remote_owned else self._unowned_remote_ops_in_progress
                        remote_ops.add(remote_id)
                    return

            evicted = self._evict_oldest_warm()
            if evicted is not None:
                with self._lock:
                    if self._shutdown_called:
                        raise SandboxCapacityExceededError(
                            "Sandbox provider shut down while acquiring capacity",
                            replicas=int(self._config["replicas"]),
                            retry_after_seconds=30.0,
                            reason="shutdown",
                        )
                    if self._total_capacity_used_locked() < cap:
                        self._reserved_slots += 1
                        if remote_id is not None:
                            remote_ops = self._remote_ops_in_progress if remote_owned else self._unowned_remote_ops_in_progress
                            remote_ops.add(remote_id)
                        return

            with self._lock:
                if self._shutdown_called:
                    raise SandboxCapacityExceededError(
                        "Sandbox provider is shutting down; cannot acquire capacity",
                        replicas=int(self._config["replicas"]),
                        retry_after_seconds=30.0,
                        reason="shutdown",
                    )
                used = self._total_capacity_used_locked()
                cap = self._capacity_limit()

                if used >= cap:
                    if policy == "reject":
                        raise SandboxCapacityExceededError(
                            f"All {cap} sandbox capacity slots are in use and overflow_policy is 'reject'",
                            active=len(self._sandboxes),
                            warm=len(self._warm_pool),
                            reserved=self._reserved_slots,
                            replicas=int(self._config["replicas"]),
                        )

                    if policy == "burst":
                        raise SandboxCapacityExceededError(
                            f"All {cap} sandbox capacity slots are in use (replicas={self._config['replicas']}, burst={self._config['burst_limit']})",
                            active=len(self._sandboxes),
                            warm=len(self._warm_pool),
                            reserved=self._reserved_slots,
                            replicas=int(self._config["replicas"]),
                        )

                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise SandboxCapacityExceededError(
                            f"Timed out after {timeout}s waiting for a sandbox capacity slot (replicas={self._config['replicas']}, active={len(self._sandboxes)}, warm={len(self._warm_pool)}, reserved={self._reserved_slots})",
                            active=len(self._sandboxes),
                            warm=len(self._warm_pool),
                            reserved=self._reserved_slots,
                            replicas=int(self._config["replicas"]),
                        )
                    self._capacity_cond.wait(timeout=min(remaining, 1.0))

    def _release_capacity(self) -> None:
        """Release a reserved slot (call on create failure or destroy)."""
        with self._lock:
            if self._reserved_slots > 0:
                self._reserved_slots -= 1
            self._capacity_cond.notify_all()

    def _complete_transition_remote_op(self, sandbox_id: str, *, remote_destroyed: bool) -> None:
        """Finish a remote operation that already owns a transition slot."""
        with self._lock:
            if sandbox_id not in self._remote_ops_in_progress:
                return
            self._remote_ops_in_progress.discard(sandbox_id)
            if self._shutdown_called:
                return
            if remote_destroyed:
                self._end_transition_locked()
            else:
                self._eviction_tombstones.add(sandbox_id)

    def _track_reserved_remote_op(self, sandbox_id: str) -> bool:
        """Make a reserved remote ID visible to shutdown."""
        with self._lock:
            if self._shutdown_called:
                return False
            self._remote_ops_in_progress.add(sandbox_id)
            return True

    def _complete_reserved_remote_op(self, sandbox_id: str, *, remote_destroyed: bool) -> None:
        """Finish a remote operation that owns a reserved slot."""
        with self._lock:
            tracked = sandbox_id in self._remote_ops_in_progress
            tracked_unowned = sandbox_id in self._unowned_remote_ops_in_progress
            if not tracked and not tracked_unowned:
                return
            self._remote_ops_in_progress.discard(sandbox_id)
            self._unowned_remote_ops_in_progress.discard(sandbox_id)
            if self._shutdown_called:
                return
            if self._reserved_slots > 0:
                self._reserved_slots -= 1
            if remote_destroyed:
                self._capacity_cond.notify_all()
            else:
                self._begin_transition_locked()
                self._eviction_tombstones.add(sandbox_id)
            self._capacity_cond.notify_all()

    def _commit_capacity(self) -> None:
        """Convert a reserved slot to a committed active slot.

        The reservation is dropped and the newly-created sandbox fills the
        slot.  Must be called inside the same critical section that inserts
        into ``_sandboxes``.
        """
        if self._reserved_slots > 0:
            self._reserved_slots -= 1

    def _create_sandbox(self, thread_id: str | None, *, user_id: str) -> str:
        """Allocate a fresh e2b sandbox and hydrate it with configured mounts.

        Capacity is enforced atomically via :meth:`_reserve_capacity`.
        """
        reservation_token = self._reserve_capacity(thread_id, user_id)

        sandbox_cls = self._get_sandbox_cls()
        metadata: dict[str, str] = {
            META_KEY_PROVIDER: META_VAL_PROVIDER,
            META_KEY_GATEWAY: self._owner_id,
            META_KEY_CREATED_AT: str(time.time()),
        }
        if self._deployment_capacity is not None:
            metadata[META_KEY_CAPACITY_LEDGER] = self._deployment_capacity.key
        if reservation_token is not None:
            metadata[META_KEY_CAPACITY_RESERVATION] = reservation_token
        if thread_id:
            metadata[META_KEY_USER] = user_id
            metadata[META_KEY_THREAD] = thread_id

        create_kwargs: dict[str, Any] = {
            "template": self._config["template"],
            "metadata": metadata,
            **self._common_kwargs(),
        }
        if self._config["idle_timeout"] > 0:
            create_kwargs["timeout"] = self._config["idle_timeout"]
        if self._config["environment"]:
            create_kwargs["envs"] = self._config["environment"]

        try:
            client = sandbox_cls.create(**create_kwargs)  # type: ignore[attr-defined]
        except Exception as e:
            logger.error("Failed to create e2b sandbox: %s", e)
            self._release_capacity()
            raise

        sandbox_id: str = getattr(client, "sandbox_id", None) or str(uuid.uuid4())[:8]
        self._track_deployment_sandbox(
            sandbox_id,
            reservation_token=reservation_token,
            required=False,
        )
        if not self._track_reserved_remote_op(sandbox_id):
            kill_error = self._kill_client(client)
            cleanup_confirmed = kill_error is None
            self._safe_close_client(client)
            if kill_error is not None:
                with self._lock:
                    self._remote_ops_in_progress.add(sandbox_id)
                try:
                    retry_client = self._reconnect_client(sandbox_cls, sandbox_id)
                except Exception as reconnect_error:
                    logger.warning(
                        "Failed to reconnect e2b sandbox %s after shutdown cleanup failed: %s",
                        sandbox_id,
                        reconnect_error,
                    )
                else:
                    retry_error = self._kill_client(retry_client)
                    self._safe_close_client(retry_client)
                    if retry_error is None:
                        cleanup_confirmed = True
                        with self._lock:
                            self._remote_ops_in_progress.discard(sandbox_id)
                    else:
                        logger.warning(
                            "Failed to kill e2b sandbox %s after reconnecting during shutdown: %s",
                            sandbox_id,
                            retry_error,
                        )
            if cleanup_confirmed:
                message = f"Sandbox provider shut down during sandbox creation; cleaned up remote sandbox {sandbox_id}"
            else:
                message = f"Sandbox provider shut down during sandbox creation; could not confirm cleanup for remote sandbox {sandbox_id}"
            raise SandboxCapacityExceededError(
                message,
                replicas=int(self._config["replicas"]),
                retry_after_seconds=30.0,
                reason="shutdown",
            )

        try:
            self._publish_ownership(sandbox_id)
        except Exception:
            remote_destroyed = False
            if self._claim_ownership(sandbox_id, for_destroy=True):
                remote_destroyed = self._kill_client(client) is None
                self._release_ownership(sandbox_id)
            self._safe_close_client(client)
            self._complete_reserved_remote_op(sandbox_id, remote_destroyed=remote_destroyed)
            raise

        # Materialise DeerFlow's virtual path layout (/mnt/user-data/...) inside
        # the e2b VM. Without this step shell commands the agent emits — which
        # use the same /mnt/user-data prefix as LocalSandbox / AioSandbox — fail
        # with PermissionError because /mnt is owned by root in the e2b
        # template. See the path-mapping note in :class:`E2BSandbox`.
        bootstrap_error, remote_destroyed = self._bootstrap_or_discard(client, sandbox_id)
        if bootstrap_error is not None:
            self._complete_reserved_remote_op(sandbox_id, remote_destroyed=remote_destroyed)
            raise RuntimeError(f"Failed to bootstrap e2b sandbox {sandbox_id}") from bootstrap_error

        # One-shot mount uploads.  e2b has no host bind-mount, so we copy
        # files from ``host_path`` into ``container_path`` at sandbox start.
        try:
            self._apply_mounts(client, user_id=user_id)
        except Exception as e:
            logger.warning("Failed to apply some mounts to e2b sandbox %s: %s", sandbox_id, e)

        sandbox = E2BSandbox(id=sandbox_id, client=client, home_dir=self._config["home_dir"])

        # Commit atomically.  If the provider shut down during bootstrap or
        # mounts, kill the VM rather than parking it under ``_sandboxes``
        # where the next shutdown won't see it.
        should_kill = False
        with self._lock:
            if self._shutdown_called:
                should_kill = True
            else:
                self._remote_ops_in_progress.discard(sandbox_id)
                self._commit_capacity()
                self._sandboxes[sandbox_id] = sandbox
                if thread_id:
                    self._thread_sandboxes[self._thread_key(thread_id, user_id)] = sandbox_id

        if should_kill:
            if self._claim_ownership(sandbox_id, for_destroy=True):
                self._kill_client(client)
                self._release_ownership(sandbox_id)
            self._safe_close_client(client)
            raise SandboxCapacityExceededError(
                f"Sandbox provider shut down during sandbox creation; killed remote sandbox {sandbox_id}",
                replicas=int(self._config["replicas"]),
                retry_after_seconds=30.0,
                reason="shutdown",
            )

        replicas = self._config["replicas"]
        logger.info(
            "Created e2b sandbox %s for user/thread %s/%s (template=%s, replicas=%s)",
            sandbox_id,
            user_id,
            thread_id,
            self._config["template"],
            replicas,
        )
        return sandbox_id

    def _common_kwargs(self) -> dict[str, Any]:
        """Kwargs shared by ``Sandbox.create``, ``Sandbox.connect`` and ``Sandbox.list``."""
        kwargs: dict[str, Any] = {}
        if self._config["api_key"]:
            kwargs["api_key"] = self._config["api_key"]
        if self._config["domain"]:
            kwargs["domain"] = self._config["domain"]
        return kwargs

    @staticmethod
    def _entry_id(entry: Any) -> str | None:
        value = getattr(entry, "sandbox_id", None)
        if value is None and isinstance(entry, dict):
            value = entry.get("sandbox_id")
        return str(value) if value else None

    @staticmethod
    def _entry_metadata(entry: Any) -> dict[str, Any]:
        value = getattr(entry, "metadata", None)
        if value is None and isinstance(entry, dict):
            value = entry.get("metadata")
        return value if isinstance(value, dict) else {}

    def _list_remote_entries(
        self,
        metadata: dict[str, str],
    ) -> tuple[list[Any], bool, bool]:
        """List E2B entries and report budget exhaustion and completeness."""
        sandbox_cls = self._get_sandbox_cls()
        try:
            query = SandboxQuery(metadata=metadata)
            result = sandbox_cls.list(query=query, **self._common_kwargs())  # type: ignore[attr-defined]
        except Exception as e:
            logger.warning("E2B reconciliation list failed: %s", e)
            return [], False, False

        max_pages = int(self._config["reconciliation_max_pages"])
        max_items = int(self._config["reconciliation_max_items"])
        deadline = time.monotonic() + float(self._config["reconciliation_max_seconds"])
        entries: list[Any] = []
        exhausted = False
        complete = True

        if hasattr(result, "next_items") and hasattr(result, "has_next"):
            for page_number in range(max_pages):
                if time.monotonic() >= deadline or len(entries) >= max_items:
                    exhausted = True
                    break
                try:
                    page = result.next_items()
                except Exception as e:
                    logger.warning("E2B reconciliation paginator failed: %s", e)
                    complete = False
                    break
                if not page:
                    break
                room = max_items - len(entries)
                entries.extend(list(page)[:room])
                if len(page) > room:
                    exhausted = True
                    break
                if not getattr(result, "has_next", False):
                    break
                if page_number + 1 >= max_pages:
                    exhausted = True
        else:
            try:
                all_entries = list(result or [])
            except TypeError:
                logger.warning("E2B Sandbox.list returned non-iterable %s", type(result).__name__)
                return [], False, False
            entries = all_entries[:max_items]
            exhausted = len(all_entries) > max_items

        if time.monotonic() >= deadline:
            exhausted = True
        if exhausted:
            complete = False
        return entries, exhausted, complete

    def _publish_ownership(self, sandbox_id: str) -> None:
        """Publish acquire-side ownership before exposing a sandbox locally."""
        with self._lock:
            self._acquire_inflight.add(sandbox_id)
        try:
            if not self._ownership.take(sandbox_id):
                raise RuntimeError(f"E2B sandbox {sandbox_id} is being destroyed")
        except Exception:
            with self._lock:
                self._acquire_inflight.discard(sandbox_id)
            raise
        with self._lock:
            self._owned_sandbox_ids.add(sandbox_id)

    def _claim_ownership(self, sandbox_id: str, *, for_destroy: bool = False) -> bool:
        """Exclusively claim an unowned sandbox, failing closed on store errors."""
        try:
            claimed = self._ownership.claim(sandbox_id, for_destroy=for_destroy)
        except OwnershipBackendError as e:
            logger.warning("E2B ownership claim failed for %s: %s", sandbox_id, e)
            return False
        if claimed:
            with self._lock:
                self._owned_sandbox_ids.add(sandbox_id)
        return claimed

    def _release_ownership(self, sandbox_id: str) -> None:
        try:
            self._ownership.release(sandbox_id)
        except OwnershipBackendError as e:
            logger.warning("Failed to release E2B ownership for %s: %s", sandbox_id, e)
        with self._lock:
            self._owned_sandbox_ids.discard(sandbox_id)
            self._acquire_inflight.discard(sandbox_id)

    def _forget_local_sandbox(self, sandbox_id: str) -> None:
        """Forget a lease taken by a peer without touching the remote VM."""
        with self._lock:
            if sandbox_id in self._acquire_inflight:
                return
            sandbox = self._sandboxes.pop(sandbox_id, None)
            self._warm_pool.pop(sandbox_id, None)
            self._owned_sandbox_ids.discard(sandbox_id)
            for key, sid in list(self._thread_sandboxes.items()):
                if sid == sandbox_id:
                    self._thread_sandboxes.pop(key, None)
        if sandbox is not None:
            try:
                sandbox.close()
            except Exception:
                pass

    def _refresh_owned_leases(self) -> None:
        with self._lock:
            sandbox_ids = list(self._owned_sandbox_ids)
        for sandbox_id in sandbox_ids:
            try:
                outcome = self._ownership.renew(sandbox_id)
            except OwnershipBackendError as e:
                logger.warning("Could not renew E2B ownership for %s; will retry: %s", sandbox_id, e)
                continue
            if outcome is RenewOutcome.RENEWED:
                continue
            if outcome is RenewOutcome.LAPSED:
                try:
                    if self._ownership.claim(sandbox_id):
                        continue
                except OwnershipBackendError as e:
                    logger.warning("Could not re-establish E2B ownership for %s: %s", sandbox_id, e)
                    continue
            logger.info("E2B sandbox %s ownership moved to a peer; forgetting local client", sandbox_id)
            self._forget_local_sandbox(sandbox_id)

    def _start_maintenance_threads(self) -> None:
        def renew() -> None:
            interval = self._ownership_config.renewal_interval_seconds
            while not self._maintenance_stop.wait(interval):
                self._refresh_owned_leases()

        def reconcile() -> None:
            interval = float(self._config["reconciliation_interval_seconds"])
            while not self._maintenance_stop.is_set():
                try:
                    self._reconcile_remote_sandboxes()
                except Exception:
                    logger.exception("Periodic E2B sandbox reconciliation failed")
                if self._maintenance_stop.wait(interval):
                    break

        self._lease_thread = threading.Thread(target=renew, name="e2b-lease-renewal", daemon=True)
        self._reconcile_thread = threading.Thread(target=reconcile, name="e2b-reconciliation", daemon=True)
        self._lease_thread.start()
        self._reconcile_thread.start()

    def _reserve_reconciliation_capacity(
        self,
        sandbox_id: str,
        *,
        reservation_token: str | None = None,
    ) -> bool:
        """Reserve one local slot for adoption without blocking maintenance."""
        try:
            self._track_deployment_sandbox(
                sandbox_id,
                reservation_token=reservation_token,
            )
        except SandboxCapacityExceededError as error:
            logger.warning("Could not track discovered E2B sandbox %s: %s", sandbox_id, error)
            return False
        with self._lock:
            if self._shutdown_called or self._total_capacity_used_locked() >= self._capacity_limit():
                return False
            self._reserved_slots += 1
            self._unowned_remote_ops_in_progress.add(sandbox_id)
            self._acquire_inflight.add(sandbox_id)
            return True

    def _reconcile_remote_sandboxes(self, *, now: float | None = None) -> ReconciliationStats:
        """Adopt canonical E2B sandboxes and safely reap duplicates/orphans."""
        observed_at = time.monotonic() if now is None else now
        deadline = time.monotonic() + float(self._config["reconciliation_max_seconds"])
        stats = ReconciliationStats()
        capacity_revision = None
        capacity_store = self._deployment_capacity
        if capacity_store is not None:
            try:
                capacity_revision = capacity_store.revision()
            except CapacityBackendError as error:
                logger.warning(
                    "Could not read E2B capacity before reconciliation: %s",
                    error,
                )

        entries, stats.budget_exhausted, inventory_complete = self._list_remote_entries({META_KEY_PROVIDER: META_VAL_PROVIDER})
        entries = [entry for entry in entries if self._metadata_matches_capacity_ledger(self._entry_metadata(entry))]
        stats.discovered = len(entries)

        if capacity_store is not None and capacity_revision is not None:
            records = {sandbox_id: self._capacity_reservation_from_metadata(self._entry_metadata(entry)) for entry in entries if (sandbox_id := self._entry_id(entry))}
            try:
                applied = capacity_store.reconcile(
                    expected_revision=capacity_revision,
                    remote_sandboxes=records,
                    complete=inventory_complete,
                    reservation_max_age_ms=self._capacity_reservation_max_age_ms(),
                )
                if not applied:
                    logger.debug("E2B capacity inventory became stale during reconciliation; retrying on the next pass")
            except CapacityBackendError as error:
                logger.warning(
                    "Could not apply E2B capacity inventory: %s",
                    error,
                )

        groups: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = {}
        orphans: list[tuple[str, dict[str, Any]]] = []
        present_ids: set[str] = set()

        for entry in entries:
            sandbox_id = self._entry_id(entry)
            if not sandbox_id:
                continue
            present_ids.add(sandbox_id)
            metadata = self._entry_metadata(entry)
            user_id = metadata.get(META_KEY_USER)
            thread_id = metadata.get(META_KEY_THREAD)
            if isinstance(user_id, str) and user_id and isinstance(thread_id, str) and thread_id:
                groups.setdefault((user_id, thread_id), []).append((sandbox_id, metadata))
            else:
                orphans.append((sandbox_id, metadata))

        for (user_id, thread_id), candidates in groups.items():
            candidates.sort(key=lambda item: (item[1].get(META_KEY_CREATED_AT, ""), item[0]))
            with self._lock:
                local_id = self._thread_sandboxes.get((user_id, thread_id))
            if local_id:
                candidates.sort(key=lambda item: item[0] != local_id)

            live: list[tuple[str, dict[str, Any], E2BClientSandbox]] = []
            for sandbox_id, metadata in candidates:
                if time.monotonic() >= deadline:
                    stats.budget_exhausted = True
                    break
                try:
                    client = self._reconnect_live_client(self._get_sandbox_cls(), sandbox_id)
                except Exception as e:
                    logger.debug("Could not probe E2B sandbox %s during reconciliation: %s", sandbox_id, e)
                    continue
                if client is None:
                    stats.dead += 1
                    continue
                live.append((sandbox_id, metadata, client))

            if not live:
                continue
            stats.duplicates += max(0, len(live) - 1)
            canonical_id, canonical_metadata, canonical_client = live[0]
            with self._lock:
                already_local = canonical_id in self._sandboxes
            if already_local:
                self._safe_close_client(canonical_client)
            elif not self._reserve_reconciliation_capacity(
                canonical_id,
                reservation_token=self._capacity_reservation_from_metadata(canonical_metadata),
            ):
                self._safe_close_client(canonical_client)
                stats.deferred += 1
            elif not self._claim_ownership(canonical_id):
                self._complete_reserved_remote_op(canonical_id, remote_destroyed=False)
                with self._lock:
                    self._acquire_inflight.discard(canonical_id)
                self._safe_close_client(canonical_client)
                stats.deferred += 1
            else:
                bootstrap_error, remote_destroyed = self._bootstrap_or_discard(canonical_client, canonical_id)
                if bootstrap_error is not None:
                    self._complete_reserved_remote_op(canonical_id, remote_destroyed=remote_destroyed)
                    with self._lock:
                        self._acquire_inflight.discard(canonical_id)
                    stats.deferred += 1
                else:
                    discard_after_shutdown = False
                    with self._lock:
                        if self._shutdown_called:
                            discard_after_shutdown = True
                        else:
                            self._owned_sandbox_ids.add(canonical_id)
                            self._unowned_remote_ops_in_progress.discard(canonical_id)
                            self._register_connected_sandbox(
                                canonical_id,
                                canonical_client,
                                thread_id=thread_id,
                                user_id=user_id,
                            )
                            self._commit_capacity()
                    if discard_after_shutdown:
                        if self._claim_ownership(canonical_id, for_destroy=True):
                            self._kill_client(canonical_client)
                            self._release_ownership(canonical_id)
                        self._safe_close_client(canonical_client)
                    else:
                        stats.adopted += 1

            for sandbox_id, _metadata, client in live[1:]:
                first_seen = self._orphan_first_seen.setdefault(sandbox_id, observed_at)
                if observed_at - first_seen < float(self._config["reconciliation_grace_seconds"]):
                    self._safe_close_client(client)
                    stats.deferred += 1
                    continue
                if not self._claim_ownership(sandbox_id, for_destroy=True):
                    self._safe_close_client(client)
                    stats.deferred += 1
                    continue
                if error := self._kill_client(client):
                    logger.warning("Failed to kill duplicate E2B sandbox %s: %s", sandbox_id, error)
                    self._release_ownership(sandbox_id)
                    stats.deferred += 1
                else:
                    stats.killed += 1
                    self._orphan_first_seen.pop(sandbox_id, None)
                    self._forget_local_sandbox(sandbox_id)
                    self._release_ownership(sandbox_id)
                self._safe_close_client(client)

        for sandbox_id, metadata in orphans:
            if time.monotonic() >= deadline:
                stats.budget_exhausted = True
                break
            first_seen = self._orphan_first_seen.setdefault(sandbox_id, observed_at)
            created_at = metadata.get(META_KEY_CREATED_AT)
            try:
                age = time.time() - float(created_at) if created_at is not None else observed_at - first_seen
            except (TypeError, ValueError):
                age = observed_at - first_seen
            if age < float(self._config["reconciliation_orphan_ttl_seconds"]):
                stats.deferred += 1
                continue
            if not self._claim_ownership(sandbox_id, for_destroy=True):
                stats.deferred += 1
                continue
            try:
                client = self._reconnect_client(self._get_sandbox_cls(), sandbox_id)
            except Exception:
                self._release_ownership(sandbox_id)
                continue
            if error := self._kill_client(client):
                logger.warning("Failed to kill orphan E2B sandbox %s: %s", sandbox_id, error)
                self._release_ownership(sandbox_id)
                stats.deferred += 1
            else:
                stats.killed += 1
                self._orphan_first_seen.pop(sandbox_id, None)
                self._forget_local_sandbox(sandbox_id)
                self._release_ownership(sandbox_id)
            self._safe_close_client(client)

        for sandbox_id in set(self._orphan_first_seen) - present_ids:
            self._orphan_first_seen.pop(sandbox_id, None)
        logger.info(
            "E2B reconciliation: discovered=%d adopted=%d duplicates=%d deferred=%d killed=%d dead=%d budget_exhausted=%s",
            stats.discovered,
            stats.adopted,
            stats.duplicates,
            stats.deferred,
            stats.killed,
            stats.dead,
            stats.budget_exhausted,
        )
        return stats

    def _reconnect_client(self, sandbox_cls: type[E2BClientSandbox], sandbox_id: str) -> E2BClientSandbox:
        """Connect to an existing e2b sandbox by id, with consistent kwargs."""
        return sandbox_cls.connect(sandbox_id, **self._common_kwargs())  # type: ignore[attr-defined]

    def _reconnect_live_client(
        self,
        sandbox_cls: type[E2BClientSandbox],
        sandbox_id: str,
    ) -> E2BClientSandbox | None:
        """Reconnect to *sandbox_id* and reject clients for reaped VMs.

        ``Sandbox.connect`` may succeed even after the E2B control plane has
        reaped the VM. Closing that host-side client before returning ``None``
        keeps both acquire paths from leaking a connection.
        """
        try:
            client = self._reconnect_client(sandbox_cls, sandbox_id)
        except Exception as error:
            if _is_sandbox_gone_error(error):
                self._release_deployment_sandbox(sandbox_id)
            raise
        if self._client_alive(client):
            return client
        self._safe_close_client(client)
        self._release_deployment_sandbox(sandbox_id)
        return None

    def _register_connected_sandbox(
        self,
        sandbox_id: str,
        client: E2BClientSandbox,
        *,
        thread_id: str | None,
        user_id: str,
    ) -> None:
        """Track a live reconnected sandbox under its thread ownership.

        The caller must hold ``self._lock``.
        """
        sandbox = E2BSandbox(id=sandbox_id, client=client, home_dir=self._config["home_dir"])
        self._sandboxes[sandbox_id] = sandbox
        self._warm_pool.pop(sandbox_id, None)
        if thread_id:
            self._thread_sandboxes[self._thread_key(thread_id, user_id)] = sandbox_id
        self._acquire_inflight.discard(sandbox_id)

    def _refresh_remote_timeout(self, client: E2BClientSandbox) -> None:
        """Push the configured idle timeout to the e2b control plane."""
        idle_timeout = int(self._config["idle_timeout"])
        if idle_timeout <= 0:
            return
        set_timeout = getattr(client, "set_timeout", None)
        if not callable(set_timeout):
            return
        try:
            set_timeout(idle_timeout)
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("Failed to set timeout on e2b sandbox: %s", e)

    @staticmethod
    def _client_alive(client: E2BClientSandbox) -> bool:
        """Best-effort liveness probe for a freshly reconnected e2b client.

        ``Sandbox.connect`` may succeed against a paused/expired sandbox on
        some SDK versions — the failure only surfaces on the first command.
        We send a trivial ``true`` shell command here so the failure happens
        in the acquire path (where we can transparently fall through to
        creating a fresh sandbox) instead of mid-tool-call (where the agent
        would see a confusing "sandbox not found" stack trace).

        Returns ``True`` if the command succeeds, ``False`` if it raises a
        "sandbox not found / paused" error.  Other transient errors are
        treated as alive so a single network blip does not nuke the cache.
        """
        try:
            client.commands.run("true")
            return True
        except Exception as e:
            if _is_sandbox_gone_error(e):
                return False
            logger.debug("e2b client liveness probe non-fatal error: %s", e)
            return True

    @staticmethod
    def _safe_close_client(client: E2BClientSandbox | None) -> None:
        """Close the host-side HTTP client of *client* without ever raising.

        Used in cleanup paths where we already know the e2b VM is unreachable
        (paused/expired) and we just want to release sockets in the gateway
        process.  Any exception is logged at debug level and swallowed.
        """
        if client is None:
            return
        for attr in ("close", "_transport"):
            target = getattr(client, attr, None)
            if target is None:
                continue
            close = target if callable(target) else getattr(target, "close", None)
            if not callable(close):
                continue
            try:
                close()
                return
            except Exception as e:  # pragma: no cover - defensive
                logger.debug("e2b client close raised: %s", e)
                return

    def _bootstrap_or_discard(self, client: E2BClientSandbox, sandbox_id: str) -> tuple[Exception | None, bool]:
        """Bootstrap a sandbox and report whether cleanup destroyed the VM."""
        try:
            self._bootstrap_sandbox_paths(client)
        except Exception as e:
            logger.exception("Failed to bootstrap e2b sandbox %s. Discarding the unusable sandbox.", sandbox_id)
            remote_destroyed = False
            if self._claim_ownership(sandbox_id, for_destroy=True):
                kill_error = self._kill_client(client)
                remote_destroyed = kill_error is None
                if kill_error:
                    logger.warning("Failed to kill e2b sandbox %s after bootstrap failure: %s", sandbox_id, kill_error)
                self._release_ownership(sandbox_id)
            else:
                logger.info(
                    "Not killing E2B sandbox %s after bootstrap failure because a peer owns it",
                    sandbox_id,
                )
            self._safe_close_client(client)
            return e, remote_destroyed
        return None, True

    def _bootstrap_sandbox_paths(self, client: E2BClientSandbox) -> None:
        """Materialise DeerFlow's virtual path layout inside the e2b VM.

        The local / docker sandboxes expose ``/mnt/user-data/{workspace,uploads,
        outputs}`` and ``/mnt/acp-workspace`` as writable directories, and the
        agent prompts (and the lead-agent system prompt in particular) instruct
        the model to write outputs there. e2b's default ``code-interpreter``
        template runs as the unprivileged ``user`` (uid 1000) with ``/mnt``
        owned by ``root``, so any ``mkdir -p /mnt/user-data/...`` issued by
        the agent fails with ``Permission denied``.

        We fix that once at sandbox start by:

        1. Creating ``/home/user/{workspace,uploads,outputs}`` as the real,
           writable backing directories (they live under the agent's HOME so
           there is no permission issue).
        2. Symlinking ``/mnt/user-data`` to ``/home/user`` and
           ``/mnt/acp-workspace`` to ``/home/user/acp-workspace`` via ``sudo``,
           so commands using the documented ``/mnt/...`` paths "just work" and
           land in the same physical location :class:`E2BSandbox._resolve_path`
           already remaps to.
        3. Chowning the symlinks (and ``/mnt`` itself if needed) so subsequent
           writes through the symlink target succeed.

        The e2b code-interpreter template puts ``user`` in the ``sudo`` group
        with passwordless sudo. Custom templates must provide equivalent
        permissions. Bootstrap failure makes the sandbox unusable. The
        provider discards it instead of returning a partially functional VM.
        """
        # Use the configured ``home_dir`` so a custom template can move HOME.
        home_dir = self._config["home_dir"].rstrip("/") or "/home/user"
        bootstrap_script = (
            f"set -e; "
            f"mkdir -p {shlex.quote(home_dir)}/workspace "
            f"{shlex.quote(home_dir)}/uploads "
            f"{shlex.quote(home_dir)}/outputs "
            f"{shlex.quote(home_dir)}/acp-workspace; "
            # /mnt/user-data -> $home_dir
            f"if [ ! -e /mnt/user-data ] || [ -L /mnt/user-data ]; then "
            f"  sudo ln -sfn {shlex.quote(home_dir)} /mnt/user-data; "
            f"fi; "
            # /mnt/acp-workspace -> $home_dir/acp-workspace
            f"if [ ! -e /mnt/acp-workspace ] || [ -L /mnt/acp-workspace ]; then "
            f"  sudo ln -sfn {shlex.quote(home_dir)}/acp-workspace /mnt/acp-workspace; "
            f"fi; "
            # /mnt/skills is left alone here; the optional ``mounts`` config
            # uploads its content via _apply_mounts and creates the directory
            # on demand. We only ensure that /mnt itself is traversable.
            f"sudo chmod a+rx /mnt 2>/dev/null || true; "
            f"echo BOOTSTRAP_OK"
        )

        try:
            result = client.commands.run(bootstrap_script)
        except Exception as e:
            raise RuntimeError("e2b bootstrap script raised") from e

        stdout = getattr(result, "stdout", "") or ""
        stderr = getattr(result, "stderr", "") or ""
        exit_code = getattr(result, "exit_code", 0)
        if exit_code not in (0, None) or "BOOTSTRAP_OK" not in stdout:
            raise RuntimeError(f"e2b bootstrap script failed with exit code {exit_code}; stderr={stderr.strip()}")

    def _skill_projection_mounts(self, user_id: str) -> list[tuple[Path, str, bool]]:
        """Best-effort: a projection failure must not drop configured mounts too.

        Unlike Local/AIO's ``_ensure_skills_projection``, this used to raise
        straight out of ``_apply_mounts`` before the configured-mounts loop
        ran, so a projection hiccup dropped the operator's own mounts as
        collateral damage (only caught by ``create()``'s outer warning, with
        no mounts applied at all). Swallowing here keeps the two mount
        sources independent, matching the other two providers.
        """
        from deerflow.skills.projection import ensure_skill_projections
        from deerflow.skills.storage import get_or_new_user_skill_storage

        try:
            config = get_app_config()
            storage = get_or_new_user_skill_storage(user_id, app_config=config)
            projection = ensure_skill_projections(storage)
            container_root = config.skills.container_path.rstrip("/")
            return [
                (projection.public, f"{container_root}/public", True),
                (projection.custom, f"{container_root}/custom", True),
                (projection.legacy, f"{container_root}/legacy", True),
                (projection.integrations, f"{container_root}/integrations", True),
            ]
        except Exception as exc:
            logger.warning("Could not ensure skills projection for user %s: %s", user_id, exc, exc_info=True)
            return []

    def _apply_mounts(self, client: E2BClientSandbox, *, user_id: str | None = None) -> None:
        effective_user_id = user_id or get_effective_user_id()
        projection_mounts = self._skill_projection_mounts(effective_user_id)
        configured_mounts = self._config.get("mounts") or []
        skills_root = get_app_config().skills.container_path.rstrip("/")

        mounts: list[tuple[Path, str, bool]] = list(projection_mounts)
        for mount in configured_mounts:
            try:
                host_path = Path(getattr(mount, "host_path", "") or "")
                container_path = (getattr(mount, "container_path", "") or "").rstrip("/")
                read_only = bool(getattr(mount, "read_only", False))
            except AttributeError:
                host_path = Path(mount.get("host_path", ""))
                container_path = (mount.get("container_path", "") or "").rstrip("/")
                read_only = bool(mount.get("read_only", False))

            if container_path == skills_root or container_path.startswith(skills_root + "/"):
                logger.warning("Skipping e2b mount that conflicts with managed skills projection: %s", container_path)
                continue
            mounts.append((host_path, container_path, read_only))

        for host_path, container_path, read_only in mounts:
            if not host_path.exists():
                logger.warning("Skipping e2b mount: host_path %s does not exist", host_path)
                continue
            if not container_path.startswith("/"):
                logger.warning(
                    "Skipping e2b mount: container_path %s must be absolute",
                    container_path,
                )
                continue

            try:
                make_dir = getattr(client.files, "make_dir", None)
                if callable(make_dir):
                    make_dir(container_path)
            except Exception as e:
                logger.debug("make_dir(%s) failed (continuing): %s", container_path, e)

            try:
                self._upload_tree(client, host_path, container_path, read_only)
            except Exception as e:
                logger.warning("Failed to upload mount %s -> %s: %s", host_path, container_path, e)

    # ── Output mirroring ────────────────────────────────────────────────
    _SYNC_BACK_SUBDIRS = ("outputs", "workspace")
    _SYNC_MANIFEST_NAME = ".e2b-output-sync.json"

    # Aggregate ceilings for a single release-time output-sync pass, layered on
    # top of the per-file ``_MAX_DOWNLOAD_SIZE`` cap. The per-file cap bounds one
    # artefact; these bound the whole pass so a pathological outputs tree
    # (thousands of files, or many sub-cap files summing to gigabytes, or a slow
    # VM) cannot make release download unboundedly. When a ceiling is hit the
    # pass stops early, logs what it dropped, and leaves the manifest un-pruned
    # so files it never reached are reconciled on the next release rather than
    # being forgotten.
    _MAX_SYNC_TOTAL_BYTES = 512 * 1024 * 1024  # total bytes downloaded per pass
    _MAX_SYNC_FILES = 2000  # files downloaded per pass
    _SYNC_DEADLINE_SECONDS = 120  # wall-clock budget per pass

    @staticmethod
    def _load_sync_manifest(manifest_path: Path, sandbox_id: str) -> tuple[dict[str, dict[str, int]], bool]:
        """Load verified remote and host versions from a prior output sync."""
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}, False
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("e2b sync: failed to load manifest %s: %s", manifest_path, e)
            return {}, True

        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("files"), dict):
            logger.warning("e2b sync: ignoring invalid manifest %s", manifest_path)
            return {}, True
        if data.get("sandbox_id") != sandbox_id:
            logger.debug("e2b sync: ignoring manifest from another sandbox %s", manifest_path)
            return {}, True

        files: dict[str, dict[str, int]] = {}
        for key, value in data["files"].items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            required = ("remote_size", "remote_mtime_ns", "host_size", "host_mtime_ns")
            if all(isinstance(value.get(field), int) for field in required):
                files[key] = {field: value[field] for field in required}
        return files, False

    @staticmethod
    def _write_sync_manifest(
        manifest_path: Path,
        sandbox_id: str,
        files: dict[str, dict[str, int]],
    ) -> None:
        """Atomically store output-sync versions after host files are written."""
        try:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = manifest_path.with_name(f"{manifest_path.name}.tmp")
            tmp_path.write_text(
                json.dumps({"version": 1, "sandbox_id": sandbox_id, "files": files}, sort_keys=True),
                encoding="utf-8",
            )
            tmp_path.replace(manifest_path)
        except OSError as e:
            logger.warning("e2b sync: failed to write manifest %s: %s", manifest_path, e)

    def _sync_outputs_to_host(
        self,
        sandbox: E2BSandbox,
        *,
        thread_id: str,
        user_id: str,
    ) -> None:
        """Mirror agent artifacts from the e2b VM back to host thread dirs.

        DeerFlow's ``/api/threads/{tid}/artifacts/...`` endpoint resolves
        files against the host-side per-thread ``user-data/`` tree (see
        :meth:`Paths.sandbox_outputs_dir`). LocalSandbox writes there
        directly via path mappings, so the endpoint just works for the
        local provider. The e2b VM has no shared host filesystem, so we
        explicitly pull artifacts back at release time.

        We mirror files whose host-side counterpart is missing, has a different
        size, or has a different remote modification time. A thread-local
        manifest stores the remote version and the actual host metadata after
        each write. This avoids false updates on host filesystems that round
        modification times.

        The remote file is the source of truth. The next sync overwrites a
        host-side edit when its size or modification time differs.

        Failures are logged at WARNING level but never raised: artifact
        download is non-critical for sandbox lifecycle, and we already log
        the underlying e2b SDK errors elsewhere.
        """
        from deerflow.config.paths import get_paths  # lazy import to avoid cycles

        client = sandbox.client
        if client is None:
            logger.debug("Skip output sync: e2b client already closed for sandbox %s", sandbox.id)
            return

        home_dir = sandbox.home_dir.rstrip("/") or "/home/user"
        paths = get_paths()

        thread_dir = paths.thread_dir(thread_id, user_id=user_id)
        thread_root = thread_dir / "user-data"
        host_targets: dict[str, Path] = {sub: thread_root / sub for sub in self._SYNC_BACK_SUBDIRS}
        manifest_path = thread_dir / self._SYNC_MANIFEST_NAME
        remote_sandbox_id = sandbox.sandbox_id
        manifest, manifest_dirty = self._load_sync_manifest(manifest_path, remote_sandbox_id)

        # Build a single shell command that lists all files in the sync dirs
        # with size, modification time, and path, NUL-separated for safe
        # parsing of weird filenames. This keeps us to one round-trip
        # regardless of how many subdirs we mirror.
        #
        # We list using the *physical* /home/user paths (the bootstrap symlink
        # /mnt/user-data -> /home/user follows transparently), then translate
        # each hit back to the /mnt/user-data prefix before calling
        # ``E2BSandbox.download_file``: that method enforces a security check
        # that the path is under ``VIRTUAL_PATH_PREFIX`` (/mnt/user-data) and
        # internally re-resolves it to /home/user via ``_resolve_path``.
        find_targets = " ".join(shlex.quote(f"{home_dir}/{sub}") for sub in self._SYNC_BACK_SUBDIRS)
        list_cmd = f'for d in {find_targets}; do   [ -d "$d" ] && find "$d" -type f -printf \'%s\\t%T@\\t%p\\0\' 2>/dev/null; done'

        try:
            result = client.commands.run(list_cmd)
        except Exception as e:
            logger.warning("e2b sync: list command failed: %s", e)
            if _is_sandbox_gone_error(e):
                with sandbox._lock:
                    sandbox._dead = True
            return

        stdout = getattr(result, "stdout", "") or ""
        if not stdout:
            if manifest or manifest_dirty:
                self._write_sync_manifest(manifest_path, remote_sandbox_id, {})
            return

        synced = 0
        skipped = 0
        seen_manifest_keys: set[str] = set()
        from .e2b_sandbox import _MAX_DOWNLOAD_SIZE

        # Aggregate budget for this pass (see the _MAX_SYNC_* class constants).
        downloaded_bytes = 0
        downloaded_files = 0
        truncated_reason: str | None = None
        deadline = time.monotonic() + self._SYNC_DEADLINE_SECONDS

        for entry in stdout.split("\0"):
            if time.monotonic() >= deadline:
                truncated_reason = f"time budget {self._SYNC_DEADLINE_SECONDS}s"
                break
            entry = entry.strip()
            if not entry:
                continue
            try:
                size_str, remote_mtime_str, remote_path = entry.split("\t", 2)
                remote_size = int(size_str)
                remote_mtime_ns = int(Decimal(remote_mtime_str) * 1_000_000_000)
            except (InvalidOperation, ValueError):
                logger.debug("e2b sync: unparseable entry %r", entry)
                continue

            # Determine which subdir this file belongs to so we can compute
            # the relative path on the host side.  remote_path is absolute,
            # e.g. /home/user/outputs/foo/bar.pdf
            sub_match: tuple[str, Path, str] | None = None
            for sub, host_root in host_targets.items():
                prefix = f"{home_dir}/{sub}/"
                if remote_path == f"{home_dir}/{sub}":
                    continue
                if remote_path.startswith(prefix):
                    rel = remote_path[len(prefix) :]
                    virtual_path = f"/mnt/user-data/{sub}/{rel}"
                    sub_match = (sub, host_root / rel, virtual_path)
                    break
            if sub_match is None:
                continue
            _sub, host_path, virtual_path = sub_match
            manifest_key = host_path.relative_to(thread_root).as_posix()
            seen_manifest_keys.add(manifest_key)

            if remote_size > _MAX_DOWNLOAD_SIZE:
                logger.warning(
                    "e2b sync: skipping oversize artefact %s (%d bytes > %d cap)",
                    remote_path,
                    remote_size,
                    _MAX_DOWNLOAD_SIZE,
                )
                skipped += 1
                continue

            try:
                host_stat = host_path.stat()
                entry = manifest.get(manifest_key)
                if entry == {
                    "remote_size": remote_size,
                    "remote_mtime_ns": remote_mtime_ns,
                    "host_size": host_stat.st_size,
                    "host_mtime_ns": host_stat.st_mtime_ns,
                }:
                    skipped += 1
                    continue
            except OSError:
                pass

            if downloaded_files >= self._MAX_SYNC_FILES:
                truncated_reason = f"file count cap {self._MAX_SYNC_FILES}"
                break
            if downloaded_bytes + remote_size > self._MAX_SYNC_TOTAL_BYTES:
                truncated_reason = f"total byte budget {self._MAX_SYNC_TOTAL_BYTES}"
                break

            try:
                data = sandbox.download_file(virtual_path)
            except Exception as e:
                logger.warning(
                    "e2b sync: failed to download %s from sandbox %s: %s",
                    virtual_path,
                    sandbox.id,
                    e,
                )
                continue
            # Count the download against the budget regardless of the host-side
            # write below: the remote round-trip is the resource being bounded.
            downloaded_files += 1
            downloaded_bytes += remote_size

            try:
                host_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = host_path.with_name(host_path.name + ".e2bsync.tmp")
                tmp_path.write_bytes(data)
                os.utime(tmp_path, ns=(remote_mtime_ns, remote_mtime_ns))
                tmp_path.replace(host_path)
                host_stat = host_path.stat()
                manifest[manifest_key] = {
                    "remote_size": remote_size,
                    "remote_mtime_ns": remote_mtime_ns,
                    "host_size": host_stat.st_size,
                    "host_mtime_ns": host_stat.st_mtime_ns,
                }
                manifest_dirty = True
                synced += 1
            except OSError as e:
                logger.warning("e2b sync: failed to write %s on host: %s", host_path, e)

        # A truncated pass did not observe every remote file, so
        # ``seen_manifest_keys`` is incomplete; pruning "stale" entries here
        # would forget files we simply never reached. Skip pruning and let the
        # next release reconcile them (freshly downloaded entries are still
        # written below).
        stale_keys = set(manifest) - seen_manifest_keys
        if stale_keys and truncated_reason is None:
            for key in stale_keys:
                manifest.pop(key)
            manifest_dirty = True

        if manifest_dirty:
            self._write_sync_manifest(manifest_path, remote_sandbox_id, manifest)

        if truncated_reason is not None:
            logger.warning(
                "e2b sync: sandbox=%s thread=%s truncated (%s); downloaded=%d files/%d bytes this pass, remaining artefacts deferred to next release",
                sandbox.id,
                thread_id,
                truncated_reason,
                downloaded_files,
                downloaded_bytes,
            )

        if synced or skipped:
            logger.info(
                "e2b sync: sandbox=%s thread=%s synced=%d skipped=%d",
                sandbox.id,
                thread_id,
                synced,
                skipped,
            )

    @staticmethod
    def _upload_tree(
        client: E2BClientSandbox,
        src: Path,
        dest_dir: str,
        read_only: bool,
    ) -> None:
        """Recursively upload ``src`` into ``dest_dir`` inside the sandbox."""
        started_at = time.monotonic()
        source_is_file = src.is_file()
        files: list[tuple[Path, str, int]] = []
        total_size = 0

        def add_file(path: Path, target: str) -> None:
            nonlocal total_size
            file_size = path.stat().st_size
            if file_size > _MAX_MOUNT_FILE_SIZE:
                raise ValueError(f"Mount file {path} is {file_size} bytes and exceeds the {_MAX_MOUNT_FILE_SIZE}-byte file limit")
            if len(files) >= _MAX_MOUNT_FILES:
                raise ValueError(f"Mount {src} contains more than {_MAX_MOUNT_FILES} files and exceeds the {_MAX_MOUNT_FILES}-file limit")
            total_size += file_size
            if total_size > _MAX_MOUNT_TOTAL_SIZE:
                raise ValueError(f"Mount {src} is at least {total_size} bytes and exceeds the {_MAX_MOUNT_TOTAL_SIZE}-byte total limit")
            files.append((path, target, file_size))

        if source_is_file:
            add_file(src, f"{dest_dir}/{src.name}")
        else:
            for path in src.rglob("*"):
                if path.is_file():
                    rel = path.relative_to(src).as_posix()
                    add_file(path, f"{dest_dir}/{rel}")

        for path, target, expected_size in files:
            try:
                make_dir = getattr(client.files, "make_dir", None)
                if callable(make_dir):
                    parent = target.rsplit("/", 1)[0]
                    if parent and parent != dest_dir:
                        make_dir(parent)
            except Exception:
                pass
            with path.open("rb") as fh:
                actual_size = os.fstat(fh.fileno()).st_size
                if actual_size != expected_size:
                    raise ValueError(f"Mount file {path} changed during upload preflight")
                client.files.write(target, fh)
        if read_only:
            try:
                chmod_target = files[0][1] if source_is_file else dest_dir
                chmod_flag = "" if source_is_file else "-R "
                client.commands.run(f"chmod {chmod_flag}a-w {shlex.quote(chmod_target)}")
            except Exception:
                pass
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        logger.info(
            "e2b mount upload: source=%s destination=%s files=%d bytes=%d elapsed_ms=%d",
            src,
            dest_dir,
            len(files),
            total_size,
            elapsed_ms,
        )

    def _evict_oldest_warm(self) -> str | None:
        """Evict the oldest warm entry, holding a transitioning slot.

        The warm entry is popped and a transitioning slot is taken.  The slot
        stays occupied until the control plane confirms the VM is gone.
        """
        with self._lock:
            retryable = self._eviction_tombstones - self._evictions_in_progress
            if retryable:
                evict_id = next(iter(retryable))
                self._evictions_in_progress.add(evict_id)
            elif self._warm_pool:
                evict_id, (_, _) = self._warm_pool.popitem(last=False)
                self._eviction_tombstones.add(evict_id)
                self._evictions_in_progress.add(evict_id)
                self._begin_transition_locked()
            else:
                return None

        if not self._claim_ownership(evict_id, for_destroy=True):
            logger.info("Deferring warm-pool eviction for %s because a peer owns it", evict_id)
            self._forget_local_sandbox(evict_id)
            with self._lock:
                if evict_id in self._evictions_in_progress:
                    self._evictions_in_progress.discard(evict_id)
                    self._eviction_tombstones.discard(evict_id)
                    self._end_transition_locked()
            return evict_id
        try:
            client = self._reconnect_live_client(self._get_sandbox_cls(), evict_id)
        except Exception as e:
            logger.warning(
                "Evicted warm-pool e2b sandbox %s could not be reconnected for kill: %s",
                evict_id,
                e,
            )
            with self._lock:
                if evict_id in self._evictions_in_progress:
                    self._evictions_in_progress.discard(evict_id)
                    if not self._shutdown_called:
                        self._eviction_tombstones.add(evict_id)
            self._release_ownership(evict_id)
            return None

        if client is None:
            with self._lock:
                if evict_id in self._evictions_in_progress:
                    self._evictions_in_progress.discard(evict_id)
                    self._eviction_tombstones.discard(evict_id)
                    self._end_transition_locked()
            self._release_ownership(evict_id)
            logger.info("Evicted warm-pool e2b sandbox %s was already gone", evict_id)
            return evict_id

        if error := self._kill_client(client):
            logger.warning("Failed to kill evicted e2b sandbox %s: %s", evict_id, error)
            self._safe_close_client(client)
            with self._lock:
                if evict_id in self._evictions_in_progress:
                    self._evictions_in_progress.discard(evict_id)
                    if not self._shutdown_called:
                        self._eviction_tombstones.add(evict_id)
            self._release_ownership(evict_id)
            return None

        self._safe_close_client(client)
        with self._lock:
            if evict_id in self._evictions_in_progress:
                self._evictions_in_progress.discard(evict_id)
                self._eviction_tombstones.discard(evict_id)
                self._end_transition_locked()
        self._release_ownership(evict_id)
        logger.info("Evicted warm-pool e2b sandbox %s", evict_id)
        return evict_id

    def get(self, sandbox_id: str) -> Sandbox | None:
        with self._lock:
            return self._sandboxes.get(sandbox_id)

    def release(self, sandbox_id: str) -> None:
        """Park a sandbox in the warm pool while keeping the cloud VM alive.

        e2b sandboxes have a server-enforced timeout — we refresh it here so
        the warm-pool entry stays valid for at least one ``idle_timeout``
        window after release.
        """
        with self._lock:
            thread_key = next(
                (key for key, sid in self._thread_sandboxes.items() if sid == sandbox_id),
                None,
            )

        if thread_key is None:
            self._release_internal(sandbox_id)
            return

        user_id, thread_id = thread_key
        with self._get_thread_lock(thread_id, user_id):
            self._release_internal(sandbox_id)

    def _release_internal(self, sandbox_id: str) -> None:
        """Complete one release while the thread transition lock is held.

        The active slot becomes a *transitioning* slot the moment the sandbox
        is removed from ``_sandboxes``. It stays counted through output sync
        and timeout refresh. The transition ends when the VM enters its
        destination or destruction completes. Shutdown kills the VM instead
        of parking it in ``_warm_pool``.
        """
        sandbox: E2BSandbox | None = None
        seed: str | None = None
        removed_keys: list[tuple[str, str]] = []
        transition_slot_held = False

        with self._lock:
            sandbox = self._sandboxes.pop(sandbox_id, None)
            if sandbox is None:
                return
            self._begin_transition_locked()
            transition_slot_held = True
            removed_keys = [key for key, sid in self._thread_sandboxes.items() if sid == sandbox_id]
            for key in removed_keys:
                self._thread_sandboxes.pop(key, None)
            if removed_keys:
                user_id, thread_id = removed_keys[0]
                seed = self._stable_seed(thread_id, user_id)

        # E2BSandbox.close() clears its client reference. Keep this reference
        # so a shutdown that races release can still kill the remote VM.
        client = sandbox.client

        try:
            if sandbox.is_dead:
                logger.info(
                    "Releasing dead e2b sandbox %s; skipping output sync and warm pool, killing remote VM",
                    sandbox_id,
                )
                self._kill_and_close(sandbox)
                return

            sync_failed_due_to_dead_vm = False
            if seed is not None and removed_keys:
                user_id_sync, thread_id_sync = removed_keys[0]
                try:
                    self._sync_outputs_to_host(sandbox, thread_id=thread_id_sync, user_id=user_id_sync)
                except Exception as e:  # pragma: no cover - defensive
                    logger.warning(
                        "Failed to mirror e2b sandbox %s outputs to host: %s",
                        sandbox_id,
                        e,
                    )
                if sandbox.is_dead:
                    sync_failed_due_to_dead_vm = True

            if sync_failed_due_to_dead_vm:
                logger.info(
                    "Sandbox %s was reaped during release; not parking in warm pool",
                    sandbox_id,
                )
                self._kill_and_close(sandbox)
                return

            try:
                self._refresh_remote_timeout(client)
            except Exception as e:
                logger.debug("Failed to refresh timeout during release: %s", e)

            with self._lock:
                should_kill = self._shutdown_called
                if not should_kill:
                    self._warm_pool[sandbox_id] = (seed or "", time.time())
                    self._warm_pool.move_to_end(sandbox_id)
                    self._end_transition_locked()
                    transition_slot_held = False
                    logger.info("Released e2b sandbox %s to warm pool", sandbox_id)

            if should_kill:
                logger.info(
                    "Provider shut down during release of sandbox %s; killing instead of parking in warm pool",
                    sandbox_id,
                )
                if self._claim_ownership(sandbox_id, for_destroy=True):
                    if error := self._kill_client(client):
                        logger.debug("Failed to kill e2b sandbox %s during release: %s", sandbox_id, error)
                    self._release_ownership(sandbox_id)
                self._safe_close_client(client)
                return

            try:
                sandbox.close()
            except Exception as e:
                logger.warning("Error closing e2b sandbox %s during release: %s", sandbox_id, e)
        finally:
            if transition_slot_held:
                self._free_transitioning_slot()

    def _kill_and_close(self, sandbox: E2BSandbox) -> None:
        if not self._claim_ownership(sandbox.id, for_destroy=True):
            logger.info("Not killing E2B sandbox %s because a peer owns it", sandbox.id)
            try:
                sandbox.close()
            except Exception:
                pass
            return
        if error := self._kill_client(getattr(sandbox, "_client", None)):
            logger.debug(
                "kill() on e2b sandbox %s raised (probably already gone): %s",
                sandbox.id,
                error,
            )
        self._release_ownership(sandbox.id)
        try:
            sandbox.close()
        except Exception:
            pass

    def _kill_client(
        self,
        client: E2BClientSandbox | None,
    ) -> Exception | None:
        """Kill a remote VM and return an exception for the caller to log."""
        if client is None:
            return RuntimeError("Cannot confirm remote VM destruction without a client")
        sandbox_id = getattr(client, "sandbox_id", None)
        try:
            kill = getattr(client, "kill", None)
            if not callable(kill):
                return RuntimeError("Cannot confirm remote VM destruction without a callable kill method")
            kill()
        except Exception as e:
            return e
        if sandbox_id is not None:
            self._release_deployment_sandbox(sandbox_id)
        return None

    def reset(self) -> None:
        """Destroy tracked E2B VMs and make this detached provider unusable."""
        self.shutdown()

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown_called:
                return
            self._shutdown_called = True
        self._maintenance_stop.set()
        for thread in (self._lease_thread, self._reconcile_thread):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=max(5.0, float(self._config["reconciliation_max_seconds"]) + 1.0))
        with self._lock:
            active = list(self._sandboxes.items())
            warm_ids = list(self._warm_pool.keys() | self._eviction_tombstones | self._remote_ops_in_progress)
            owned_ids = set(self._owned_sandbox_ids)
            self._sandboxes.clear()
            self._warm_pool.clear()
            self._eviction_tombstones.clear()
            self._evictions_in_progress.clear()
            self._remote_ops_in_progress.clear()
            self._unowned_remote_ops_in_progress.clear()
            self._thread_sandboxes.clear()
            self._thread_locks.clear()
            self._owned_sandbox_ids.clear()
            self._acquire_inflight.clear()
            self._orphan_first_seen.clear()
            self._reserved_slots = 0
            self._transitioning_slots = 0
            self._capacity_cond.notify_all()

        executor = getattr(self, "_acquire_executor", None)
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

        logger.info(
            "Shutting down E2BSandboxProvider: %d active + %d warm sandboxes",
            len(active),
            len(warm_ids),
        )

        for sandbox_id, sandbox in active:
            if sandbox_id in owned_ids and self._claim_ownership(sandbox_id, for_destroy=True):
                if error := self._kill_client(sandbox.client):
                    logger.warning(
                        "Failed to kill active e2b sandbox %s during shutdown: %s",
                        sandbox_id,
                        error,
                    )
                self._release_ownership(sandbox_id)
            try:
                sandbox.close()
            except Exception:
                pass

        sandbox_cls = self._get_sandbox_cls()
        for sandbox_id in warm_ids:
            if sandbox_id not in owned_ids:
                continue
            if not self._claim_ownership(sandbox_id, for_destroy=True):
                continue
            try:
                client = self._reconnect_client(sandbox_cls, sandbox_id)
            except Exception as e:
                logger.warning(
                    "Failed to reconnect warm-pool e2b sandbox %s for shutdown: %s",
                    sandbox_id,
                    e,
                )
                self._release_ownership(sandbox_id)
                continue
            if error := self._kill_client(client):
                logger.warning(
                    "Failed to kill warm-pool e2b sandbox %s during shutdown: %s",
                    sandbox_id,
                    error,
                )
            self._release_ownership(sandbox_id)
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        try:
            self._ownership.close()
        except Exception as e:
            logger.warning("Failed to close E2B ownership store: %s", e)
        if self._deployment_capacity is not None:
            try:
                self._deployment_capacity.close()
            except Exception as e:
                logger.warning(
                    "Failed to close E2B deployment capacity store: %s",
                    e,
                )
