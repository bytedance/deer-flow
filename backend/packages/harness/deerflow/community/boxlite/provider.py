"""``BoxliteProvider`` — DeerFlow :class:`SandboxProvider` backed by BoxLite.

Integrates `BoxLite <https://github.com/boxlite-ai/boxlite>`_ — a daemonless,
OCI-native micro-VM runtime — as a DeerFlow sandbox backend. See
https://github.com/bytedance/deer-flow/issues/3936.

Config is read off :class:`SandboxConfig` (``extra="allow"``), so BoxLite keys
may appear under ``sandbox:`` in ``config.yaml`` even though they are not declared
on the model — see this package's ``__init__`` docstring for the full set. The
provider creates one micro-VM per ``(user, thread)`` and reuses it within the
process.
"""

from __future__ import annotations

import asyncio
import atexit
import hashlib
import logging
import threading
import time
import uuid
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any, TypeVar

from deerflow.config import get_app_config
from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider

from ..warm_pool_lifecycle import WarmPoolLifecycleMixin
from .box import BoxliteBox

if TYPE_CHECKING:
    from boxlite import SimpleBox

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_IMAGE = "python:3.12-slim"
_BOX_NAME_PREFIX = "deer-flow-boxlite-"
# DeerFlow's virtual prefixes, materialised on the box rootfs at start so the
# Sandbox file APIs (which address /mnt/user-data/...) resolve natively.
_VIRTUAL_DIRS = (
    f"{VIRTUAL_PATH_PREFIX}/workspace",
    f"{VIRTUAL_PATH_PREFIX}/uploads",
    f"{VIRTUAL_PATH_PREFIX}/outputs",
    DEFAULT_SKILLS_CONTAINER_PATH,
)


def _import_simplebox() -> type[SimpleBox]:
    """Import BoxLite's async ``SimpleBox`` lazily.

    Kept out of module import so the harness (and every other provider) installs
    without BoxLite; the dependency is only needed once this provider is selected.
    """
    try:
        from boxlite import SimpleBox
    except ImportError as e:  # pragma: no cover - depends on the optional dependency
        raise ImportError("BoxliteProvider requires the optional 'boxlite' dependency. Install it with: pip install 'deerflow-harness[boxlite]' or pip install boxlite.") from e
    return SimpleBox


def _import_sync_boxlite_runtime():
    """Import BoxLite's sync runtime lazily for startup reconciliation."""
    try:
        from boxlite import SyncBoxlite
    except ImportError as e:  # pragma: no cover - depends on the optional dependency
        raise ImportError("BoxliteProvider requires the optional 'boxlite' dependency. Install it with: pip install 'deerflow-harness[boxlite]' or pip install boxlite.") from e
    return SyncBoxlite


class _EventLoopThread:
    """A private asyncio event loop running on a dedicated daemon thread.

    BoxLite is async-native and its box handles are loop-affine, while DeerFlow's
    ``Sandbox`` contract is synchronous and may be invoked from arbitrary
    ``asyncio.to_thread`` workers. Owning one loop here and marshalling every
    coroutine onto it via ``run_coroutine_threadsafe`` gives a stable, thread-safe
    bridge without BoxLite's greenlet sync facade (which refuses to run inside an
    async context and is thread-affine).
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run_forever, name="boxlite-loop", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def _run_forever(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.call_soon(self._ready.set)
        self._loop.run_forever()

    def run(self, coro: Awaitable[T], *, timeout: float | None = None) -> T:
        if self._loop is None:
            raise RuntimeError("BoxLite event loop is not ready")
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def close(self) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        wake = getattr(self._loop, "_write_to_self", None)
        if wake is not None:
            wake()
        self._thread.join(timeout=5)
        if not self._loop.is_running():
            self._loop.close()


class _SyncBoxAdapter:
    """Adapt a sync BoxLite ``Box`` handle to the async ``SimpleBox`` methods we use."""

    def __init__(self, runtime: Any, box: Any) -> None:
        self._runtime = runtime
        self._box = box

    async def exec(
        self,
        cmd: str,
        *args: str,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: float | None = None,
        cwd: str | None = None,
    ) -> Any:
        return self._box.exec(
            cmd,
            *args,
            env=env,
            user=user,
            timeout=timeout,
            cwd=cwd,
        )

    async def stop(self) -> None:
        try:
            self._box.stop()
        finally:
            self._runtime.stop()


def _run_sync_adapter[T](coro: Awaitable[T], *, timeout: float | None = None) -> T:
    """Run sync-adapter coroutines without using the BoxLite async loop."""
    if timeout is None:
        return asyncio.run(coro)
    return asyncio.run(asyncio.wait_for(coro, timeout=timeout))


class BoxliteProvider(WarmPoolLifecycleMixin[BoxliteBox], SandboxProvider):
    """Run each DeerFlow sandbox as a BoxLite micro-VM."""

    uses_thread_data_mounts = False
    needs_upload_permission_adjustment = True
    _idle_checker_thread_name = "boxlite-idle-reaper"

    @staticmethod
    def _sandbox_id(thread_id: str, user_id: str) -> str:
        """Deterministic sandbox ID from user/thread scope.

        Includes user_id so a box created for one user's bucket cannot be
        reclaimed by another user's thread with the same thread_id.
        """
        return hashlib.sha256(f"{user_id}:{thread_id}".encode()).hexdigest()[:8]

    # ── Provider ────────────────────────────────────────────────────────

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._boxes: dict[str, BoxliteBox] = {}
        self._thread_boxes: dict[tuple[str, str], str] = {}
        self._warm_pool: dict[str, tuple[BoxliteBox, float]] = {}
        self._skip_health_check_warm_ids: set[str] = set()
        self._acquire_locks: dict[str, threading.Lock] = {}
        self._idle_checker_stop = threading.Event()
        self._idle_checker_thread: threading.Thread | None = None
        self._shutdown_called = False
        self._config = self._load_config()
        self._loop = _EventLoopThread()
        atexit.register(self.shutdown)
        self._reconcile_orphans()
        self._start_idle_checker()

    def _load_config(self) -> dict[str, Any]:
        sandbox_config = get_app_config().sandbox

        def _opt(name: str, default: Any = None) -> Any:
            return getattr(sandbox_config, name, default)

        # $VARS in config.yaml are already resolved by AppConfig.resolve_env_variables
        # (which raises on a missing var), so the environment dict is used as-is.
        replicas = _opt("replicas")
        idle_timeout = _opt("idle_timeout")
        health_check_skip_seconds = _opt("health_check_skip_seconds")
        return {
            "image": _opt("image") or DEFAULT_IMAGE,
            "memory_mib": _opt("memory_mib"),
            "cpus": _opt("cpus"),
            "environment": dict(_opt("environment") or {}),
            "replicas": replicas if replicas is not None else self.DEFAULT_REPLICAS,
            "idle_timeout": idle_timeout if idle_timeout is not None else self.DEFAULT_IDLE_TIMEOUT,
            "health_check_skip_seconds": float(health_check_skip_seconds if health_check_skip_seconds is not None else 0.0),
        }

    @staticmethod
    def _thread_key(thread_id: str, user_id: str | None) -> tuple[str, str]:
        return (user_id or "", thread_id)

    @staticmethod
    def _box_name(sandbox_id: str) -> str:
        return f"{_BOX_NAME_PREFIX}{sandbox_id}"

    @staticmethod
    def _sandbox_id_from_box_name(name: str | None) -> str | None:
        if not name or not name.startswith(_BOX_NAME_PREFIX):
            return None
        sandbox_id = name[len(_BOX_NAME_PREFIX) :]
        return sandbox_id or None

    def _lock_for_sandbox(self, sandbox_id: str) -> threading.Lock:
        """Return the per-sandbox acquire lock for a deterministic sandbox id."""
        with self._lock:
            lock = self._acquire_locks.get(sandbox_id)
            if lock is None:
                lock = threading.Lock()
                self._acquire_locks[sandbox_id] = lock
            return lock

    def _start_idle_checker(self) -> None:
        """Start idle cleanup when enabled; idle_timeout=0 keeps it disabled."""
        if self._config["idle_timeout"] <= 0:
            return
        super()._start_idle_checker()

    def _active_count_locked(self) -> int:
        """Return active BoxLite box count while ``_lock`` is held."""
        return len(self._boxes)

    def _destroy_warm_entry(self, sandbox_id: str, entry: BoxliteBox, *, reason: str) -> None:
        """Close a removed warm-pool entry and log with context."""
        with self._lock:
            self._skip_health_check_warm_ids.discard(sandbox_id)
        try:
            entry.close()
            if reason == "idle_timeout":
                logger.info("Idle reaper destroyed expired warm-pool box %s", sandbox_id)
            elif reason == "replica_enforcement":
                logger.info("Replica enforcement evicted oldest warm-pool box %s", sandbox_id)
            else:
                logger.info("Destroyed warm-pool box %s (reason=%s)", sandbox_id, reason)
        except Exception as e:
            if reason == "idle_timeout":
                logger.warning("Error closing expired BoxLite box %s: %s", sandbox_id, e)
            elif reason == "replica_enforcement":
                logger.warning("Error closing evicted BoxLite box %s: %s", sandbox_id, e)
            else:
                logger.warning("Error closing BoxLite box %s (reason=%s): %s", sandbox_id, reason, e)

    def _invalidate_box(self, sandbox_id: str, reason: str) -> None:
        """Destroy and deregister a box after a terminal command-path failure."""
        box_to_close: BoxliteBox | None = None
        with self._lock:
            active_box = self._boxes.pop(sandbox_id, None)
            warm_entry = self._warm_pool.pop(sandbox_id, None)
            self._skip_health_check_warm_ids.discard(sandbox_id)
            for key in [k for k, sid in self._thread_boxes.items() if sid == sandbox_id]:
                self._thread_boxes.pop(key, None)
            box_to_close = active_box or (warm_entry[0] if warm_entry is not None else None)

        if box_to_close is None:
            logger.warning("BoxLite box %s failed terminally but was not tracked: %s", sandbox_id, reason)
            return

        logger.warning("Invalidating BoxLite box %s after terminal failure: %s", sandbox_id, reason)
        box_to_close.close()

    def _reconcile_orphans(self) -> None:
        """Adopt DeerFlow-owned BoxLite boxes left by a previous provider/process.

        BoxLite boxes are discovered by a DeerFlow-specific name prefix. Adopted
        boxes enter the warm pool so the normal idle reaper can reclaim them.
        """
        try:
            adopted = self._adopt_existing_boxes()
        except ImportError:
            logger.debug("BoxLite is not installed; skipping startup reconciliation")
            return
        except Exception as e:
            logger.warning("Failed to reconcile existing BoxLite boxes: %s", e)
            return

        if adopted:
            logger.info("Startup reconciliation adopted %s BoxLite box(es)", adopted)

    def _adopt_existing_boxes(self) -> int:
        runtime_cls = _import_sync_boxlite_runtime()
        now = time.time()
        adopted = 0

        list_runtime = runtime_cls.default().start()
        try:
            infos = list_runtime.list_info()
        finally:
            list_runtime.stop()

        for info in infos:
            name = getattr(info, "name", None)
            sandbox_id = self._sandbox_id_from_box_name(name)
            if sandbox_id is None:
                continue
            with self._lock:
                if sandbox_id in self._boxes or sandbox_id in self._warm_pool:
                    continue

            box_runtime = runtime_cls.default().start()
            try:
                box = box_runtime.get(name)
            except Exception as e:
                box_runtime.stop()
                logger.warning("Failed to retrieve existing BoxLite box %s: %s", name, e)
                continue
            if box is None:
                box_runtime.stop()
                continue

            wrapped = BoxliteBox(sandbox_id, _SyncBoxAdapter(box_runtime, box), _run_sync_adapter, default_env=self._config["environment"], on_terminal_failure=self._invalidate_box)
            with self._lock:
                if sandbox_id in self._boxes or sandbox_id in self._warm_pool:
                    box_runtime.stop()
                    continue
                self._warm_pool[sandbox_id] = (wrapped, now)
                adopted += 1
            logger.info("Adopted existing BoxLite box %s (%s) into warm pool", sandbox_id, name)

        return adopted

    # ── Acquire / release ────────────────────────────────────────────────

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        if thread_id is None:
            sandbox_id = str(uuid.uuid4())[:8]
            box = self._create_box(sandbox_id)
            with self._lock:
                self._boxes[box.id] = box
            return box.id

        key = self._thread_key(thread_id, user_id)
        sandbox_id = self._sandbox_id(thread_id, user_id)
        acquire_lock = self._lock_for_sandbox(sandbox_id)
        with acquire_lock:
            with self._lock:
                existing = self._thread_boxes.get(key)
                if existing is not None and existing in self._boxes:
                    return existing

            reclaimed = self._reclaim_warm_pool(sandbox_id)
            if reclaimed is not None:
                with self._lock:
                    self._thread_boxes[key] = reclaimed
                return reclaimed

            box = self._create_box(sandbox_id)
            with self._lock:
                self._boxes[box.id] = box
                self._thread_boxes[key] = box.id
            return box.id

    def _create_box(self, sandbox_id: str) -> BoxliteBox:
        # Enforce replica limit: evict oldest warm-pool box if active + warm boxes are at capacity.
        replicas, total = self._replica_count()
        if total >= replicas:
            evicted = self._evict_oldest_warm()
            self._log_replicas_soft_cap(replicas, sandbox_id, evicted)
        simplebox_cls = _import_simplebox()
        mkdir_cmd = "mkdir -p " + " ".join(_VIRTUAL_DIRS)

        async def _make() -> SimpleBox:
            box = simplebox_cls(
                name=self._box_name(sandbox_id),
                image=self._config["image"],
                memory_mib=self._config["memory_mib"],
                cpus=self._config["cpus"],
            )
            await box.start()
            # Materialise DeerFlow's virtual prefixes so file ops resolve natively.
            await box.exec("sh", "-lc", mkdir_cmd)
            return box

        box = self._loop.run(_make())
        logger.info("Created BoxLite box %s (name=%s, image=%s)", sandbox_id, self._box_name(sandbox_id), self._config["image"])
        return BoxliteBox(sandbox_id, box, self._loop.run, default_env=self._config["environment"], on_terminal_failure=self._invalidate_box)

    def get(self, sandbox_id: str) -> Sandbox | None:
        with self._lock:
            return self._boxes.get(sandbox_id)

    def release(self, sandbox_id: str) -> None:
        """Release a sandbox into the warm pool — VM stays running.

        The box is moved from _boxes to _warm_pool; _thread_boxes entries are
        cleared so the thread no longer holds an active reference. The VM is
        NOT stopped unless shutdown has already begun.
        """
        close_box: BoxliteBox | None = None
        with self._lock:
            box = self._boxes.pop(sandbox_id, None)
            for key in [k for k, sid in self._thread_boxes.items() if sid == sandbox_id]:
                self._thread_boxes.pop(key, None)
            if box is None:
                return
            if self._shutdown_called:
                close_box = box
                self._skip_health_check_warm_ids.discard(sandbox_id)
            else:
                self._warm_pool[sandbox_id] = (box, time.time())
                self._skip_health_check_warm_ids.add(sandbox_id)

        if close_box is not None:
            close_box.close()
            logger.info("Closed released sandbox %s because shutdown is in progress", sandbox_id)
        else:
            logger.info("Released sandbox %s to warm pool (VM still running)", sandbox_id)

    def _reclaim_warm_pool(self, sandbox_id: str) -> str | None:
        """Try to reclaim a warm-pool box by sandbox_id.

        Returns sandbox_id on success, None if not found or dead.

        Only boxes that *this provider instance* placed in the warm pool via
        ``release()`` may skip the health check when reclaimed shortly after
        release; startup-adopted/orphaned boxes always validate before reuse.
        """

        with self._lock:
            if sandbox_id not in self._warm_pool:
                return None
            box, released_at = self._warm_pool[sandbox_id]
            skip_eligible = sandbox_id in self._skip_health_check_warm_ids

        skip_seconds = self._config.get("health_check_skip_seconds", 0.0)
        if skip_eligible and skip_seconds > 0 and (time.time() - released_at) < skip_seconds:
            # Recently released by this provider — promote directly without a
            # health-check round trip, but never return an adapter that this
            # process already knows is closed.
            with self._lock:
                warm_entry = self._warm_pool.pop(sandbox_id, None)
                if warm_entry is None:
                    return None  # Raced with another thread
                self._skip_health_check_warm_ids.discard(sandbox_id)
                box, _ = warm_entry
                if box.is_closed:
                    logger.warning("Warm-pool box %s was closed before skipped health check reclaim", sandbox_id)
                    close_box = box
                else:
                    close_box = None
                    self._boxes[sandbox_id] = box
            if close_box is not None:
                close_box.close()
                return None
            logger.debug(
                "Reclaimed warm-pool box %s (skipped health check, age=%.1fs)",
                sandbox_id,
                time.time() - released_at,
            )
            return sandbox_id

        # Health check: run a simple command to verify the VM is alive
        try:
            result = box.execute_command("echo ok", timeout=5)
            if "ok" not in result:
                logger.warning("Warm pool box %s health check failed: %s", sandbox_id, result)
                with self._lock:
                    warm_entry = self._warm_pool.pop(sandbox_id, None)
                if warm_entry is not None:
                    self._destroy_warm_entry(sandbox_id, warm_entry[0], reason="health_check_failed")
                return None
        except Exception as e:
            logger.warning("Warm pool box %s health check error: %s", sandbox_id, e)
            with self._lock:
                warm_entry = self._warm_pool.pop(sandbox_id, None)
            if warm_entry is not None:
                self._destroy_warm_entry(sandbox_id, warm_entry[0], reason="health_check_failed")
            return None

        # Promote from warm pool to active
        with self._lock:
            warm_entry = self._warm_pool.pop(sandbox_id, None)
            if warm_entry is None:
                return None  # Raced with another thread
            self._skip_health_check_warm_ids.discard(sandbox_id)
            box, _ = warm_entry
            self._boxes[sandbox_id] = box

        logger.info("Reclaimed warm-pool box %s", sandbox_id)
        return sandbox_id

    def reset(self) -> None:
        """Release tracked BoxLite VMs to this instance's warm-pool cleanup.

        ``reset_sandbox_provider()`` drops the provider singleton and calls this
        lightweight hook so config changes take effect on the next provider
        construction. Teardown belongs to ``shutdown()``; reset intentionally
        leaves running VMs alive, but keeps them visible to this instance's idle
        reaper and atexit shutdown instead of orphaning them.
        """
        with self._lock:
            now = time.time()
            for sandbox_id, box in self._boxes.items():
                self._warm_pool.setdefault(sandbox_id, (box, now))
                self._skip_health_check_warm_ids.discard(sandbox_id)
            self._boxes.clear()
            self._thread_boxes.clear()
            self._acquire_locks.clear()

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown_called:
                return
            self._shutdown_called = True

        self._stop_idle_checker()

        with self._lock:
            active = list(self._boxes.values())
            warm = [box for box, _ in self._warm_pool.values()]
            self._boxes.clear()
            self._warm_pool.clear()
            self._thread_boxes.clear()
            self._acquire_locks.clear()
            self._skip_health_check_warm_ids.clear()

        for box in active + warm:
            try:
                box.close()
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("Error closing BoxLite box %s during shutdown: %s", box.id, e)
        self._loop.close()
