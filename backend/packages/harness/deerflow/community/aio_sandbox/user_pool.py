"""Opt-in, single-Gateway user pools with serial conversation leases.

Users are container boundaries. Ordinary conversations share their user's runtime;
explicit Agent skill allowlists retain the original per-thread container boundary.
"""

import asyncio
import hashlib
import json
import logging
import shlex
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, copy_context

from deerflow.config import get_app_config
from deerflow.config.paths import get_paths, join_host_path
from deerflow.sandbox.sandbox import Sandbox

from .aio_sandbox_provider import AioSandboxProvider
from .local_backend import LocalContainerBackend
from .subnet_pool import cleanup_orphan_networks

logger = logging.getLogger(__name__)
_cancel_event = ContextVar("user_sandbox_acquire_cancel", default=None)
_acquire_deadline = ContextVar("user_sandbox_acquire_deadline", default=None)
_prewarming = ContextVar("user_sandbox_prewarming", default=False)


class _PrewarmSkipped(Exception):
    """Optional warmup yielded to foreground work."""


def _check_cancelled():
    event = _cancel_event.get()
    if event is not None and event.is_set():
        raise InterruptedError("Sandbox acquisition cancelled")
    deadline = _acquire_deadline.get()
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("等待沙箱超时，请稍后重试。")


class UserAdmission:
    def __init__(self, timeout: float):
        self.timeout = timeout
        self.condition = threading.Condition(threading.RLock())
        self.active: dict[str, str] = {}
        self.closed = False

    def acquire(self, user: str, thread: str) -> bool:
        deadline = _acquire_deadline.get() or time.monotonic() + self.timeout
        with self.condition:
            if self.closed:
                raise RuntimeError("Sandbox admission is closed")
            if _prewarming.get() and user in self.active:
                raise _PrewarmSkipped()
            while user in self.active and self.active[user] != thread:
                _check_cancelled()
                if self.closed:
                    raise RuntimeError("Sandbox admission is closed")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("当前用户的上一项任务尚未结束，等待沙箱超时，请稍后重试。")
                self.condition.wait(min(remaining, 1))
            fresh = user not in self.active
            self.active[user] = thread
            return fresh

    def release(self, user: str, thread: str):
        with self.condition:
            if self.active.get(user) == thread:
                del self.active[user]
            self.condition.notify_all()


class UserSandboxView(Sandbox):
    persistent_shell_sessions = True

    def __init__(self, id: str, physical: Sandbox):
        super().__init__(id)
        self.physical = physical
        self._scopes: set[str] = set()
        self._scope_lock = threading.Lock()

    @property
    def base_url(self):
        return self.physical.base_url

    def execute_command(self, command, env=None, timeout=None):
        return self.execute_command_in_scope(command, env=env, timeout=timeout)

    def execute_command_in_scope(self, command, *, scope_id=None, env=None, timeout=None):
        scope = f"{self.id}:{scope_id or 'lead'}"
        if env:
            return self.physical.execute_command_in_scope("cd /mnt/user-data/workspace && " + command, scope_id=scope, env={**env, "DEERFLOW_SANDBOX_TASK": self.id}, timeout=timeout)
        with self._scope_lock:
            if scope not in self._scopes:
                self.physical.execute_command_in_scope(f"export DEERFLOW_SANDBOX_TASK={shlex.quote(self.id)}; cd /mnt/user-data/workspace", scope_id=scope)
                self._scopes.add(scope)
        return self.physical.execute_command_in_scope(command, scope_id=scope, env=env, timeout=timeout)

    def release_command_scope(self, scope_id):
        scope = f"{self.id}:{scope_id}"
        self.physical.release_command_scope(scope)
        with self._scope_lock:
            self._scopes.discard(scope)

    def close(self):
        with self._scope_lock:
            scopes, self._scopes = self._scopes, set()
        for scope in scopes:
            self.physical.release_command_scope(scope)

    def read_file(self, path, start_line=None, end_line=None):
        return self.physical.read_file(path, start_line=start_line, end_line=end_line)

    def download_file(self, path):
        return self.physical.download_file(path)

    def list_dir(self, path, max_depth=2):
        return self.physical.list_dir(path, max_depth=max_depth)

    def write_file(self, path, content, append=False):
        return self.physical.write_file(path, content, append=append)

    def update_file(self, path, content):
        return self.physical.update_file(path, content)

    def glob(self, path, pattern, *, include_dirs=False, max_results=200):
        return self.physical.glob(path, pattern, include_dirs=include_dirs, max_results=max_results)

    def grep(self, path, pattern, *, glob=None, literal=False, case_sensitive=False, max_results=100):
        return self.physical.grep(path, pattern, glob=glob, literal=literal, case_sensitive=case_sensitive, max_results=max_results)


class UserAioSandboxProvider(AioSandboxProvider):
    cancellation_safe_acquire = True

    def __init__(self):
        config = get_app_config().sandbox
        if not get_paths().pooled_user_data:
            raise RuntimeError("User sandboxes require the offline user_storage.migrate_user_data migration and a Gateway restart")
        if getattr(config, "provisioner_url", None) or (config.ownership is not None and config.ownership.type != "memory"):
            raise ValueError("User sandbox pools currently require one Gateway process and local Docker with memory ownership")
        self._admission = UserAdmission(config.acquire_timeout)
        self._pool_creation = threading.Lock()
        self._views: dict[str, tuple[UserSandboxView, str, str, str]] = {}
        self._pool_roots: set[tuple[str, str]] = set()
        self._fallback_users: dict[str, tuple[str, str]] = {}
        self._closing = False
        self._shutdown_lock = threading.Lock()
        self._pool_shutdown_complete = False
        self._view_created: dict[str, float] = {}
        self._wait_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="user-sandbox-admission")
        self._wait_slots = threading.BoundedSemaphore(64)
        from .aio_sandbox_provider import _open_lock_file, fcntl

        self._instance_lease = _open_lock_file(get_paths().base_dir / ".user-sandbox-gateway.lock")
        try:
            if fcntl is not None:
                fcntl.flock(self._instance_lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                import msvcrt

                self._instance_lease.seek(0)
                msvcrt.locking(self._instance_lease.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self._instance_lease.close()
            self._wait_executor.shutdown(wait=False)
            raise RuntimeError("Another Gateway owns this user sandbox pool; run one Gateway worker") from None
        try:
            super().__init__()
        except BaseException:
            self._instance_lease.close()
            self._wait_executor.shutdown(wait=False)
            raise
        if not isinstance(self._backend, LocalContainerBackend) or self._ownership.supports_cross_process:
            self.shutdown()
            raise ValueError("User sandbox pools require local Docker and a single Gateway")

    @staticmethod
    def pool_thread(user_id: str) -> str:
        return "sandbox-pool-" + hashlib.sha256(user_id.encode()).hexdigest()[:24]

    @staticmethod
    def _has_explicit_policy(thread_id: str, user_id: str) -> bool:
        manifest = get_paths().thread_skills_view_dir(thread_id, user_id=user_id) / ".projection-manifest.json"
        if not manifest.exists():
            return False
        value = json.loads(manifest.read_text(encoding="utf-8"))
        if "allowed_skills" not in value:
            raise RuntimeError("Invalid thread skill projection manifest")
        return value["allowed_skills"] is not None

    def _prepare_pool_skills(self, user_id: str, thread_id: str):
        from deerflow.skills.projection import ensure_thread_skill_projection
        from deerflow.skills.storage import get_or_new_user_skill_storage

        storage = get_or_new_user_skill_storage(user_id, app_config=get_app_config())
        ensure_thread_skill_projection(storage, thread_id, None)

    def _get_thread_mounts(self, thread_id, *, user_id=None):
        if (user_id, thread_id) not in self._pool_roots:
            return super()._get_thread_mounts(thread_id, user_id=user_id)
        paths = get_paths()
        paths.ensure_thread_dirs(thread_id, user_id=user_id)
        host_user = join_host_path(paths._host_base_dir_str(), "users", user_id)
        return [(join_host_path(host_user, "sandbox-data"), "/mnt/deerflow-data", False), (join_host_path(host_user, "sandbox-acp"), "/mnt/deerflow-acp", True)]

    def _activate_thread(self, physical_id, thread_id, user_id):
        paths = get_paths()
        paths.ensure_thread_dirs(thread_id, user_id=user_id)
        # Operator-controlled setup uses argv, never interpolated shell code.
        script = """import pathlib, sys
thread = sys.argv[1]
for name, root in [('user-data', 'deerflow-data'), ('acp-workspace', 'deerflow-acp')]:
    link = pathlib.Path('/mnt') / name
    target = pathlib.Path('/mnt') / root / thread
    if not target.is_dir():
        raise RuntimeError('Thread data mount is missing')
    if link.is_symlink():
        link.unlink()
    elif link.exists():
        link.rmdir()
    link.symlink_to(target, target_is_directory=True)
"""
        container = self._sandbox_infos[physical_id].container_name
        result = subprocess.run(["docker", "exec", "--user", "0", container, "python", "-c", script, thread_id], capture_output=True, text=True, encoding="utf-8", timeout=30)
        if result.returncode:
            raise RuntimeError("Cannot activate the user's conversation workspace")

    def _process_snapshot(self, physical_id, task_id):
        container = self._sandbox_infos[physical_id].container_name
        script = """import json, os, pathlib, sys
rows = []
marker = ('DEERFLOW_SANDBOX_TASK=' + sys.argv[1]).encode()
for p in pathlib.Path('/proc').iterdir():
    if not p.name.isdigit() or int(p.name) == os.getpid():
        continue
    try:
        fields = (p / 'stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] != 'Z' and marker in (p / 'environ').read_bytes().split(b'\\0'):
            rows.append([int(p.name), int(fields[19])])
    except (OSError, ValueError, IndexError):
        pass
print(json.dumps(rows))
"""
        result = subprocess.run(["docker", "exec", "--user", "0", container, "python", "-c", script, task_id], capture_output=True, text=True, encoding="utf-8", timeout=15)
        if result.returncode:
            raise RuntimeError("Cannot verify pooled sandbox process cleanup")
        return {tuple(row) for row in json.loads(result.stdout)}

    def _close_user_terminals(self, physical_id):
        # AIO's cleanup endpoint can leave a replacement default tmux shell.
        # With all conversation leases drained, stop that terminal server too;
        # the AIO terminal service recreates it on the next shell request.
        container = self._sandbox_infos[physical_id].container_name
        script = """import os, pathlib, signal
for p in pathlib.Path('/proc').iterdir():
    if not p.name.isdigit():
        continue
    try:
        if (p / 'comm').read_text().strip() == 'tmux: server':
            os.kill(int(p.name), signal.SIGTERM)
    except (OSError, ValueError):
        pass
"""
        result = subprocess.run(["docker", "exec", "--user", "0", container, "python", "-c", script], capture_output=True, text=True, encoding="utf-8", timeout=15)
        if result.returncode:
            raise RuntimeError("Cannot close the user's terminal sessions")

    def acquire(self, thread_id=None, *, user_id=None):
        token = _acquire_deadline.set(_acquire_deadline.get() or time.monotonic() + self._admission.timeout)
        try:
            return self._acquire(thread_id, user_id=user_id)
        finally:
            _acquire_deadline.reset(token)

    def _acquire(self, thread_id=None, *, user_id=None):
        _check_cancelled()
        if thread_id is None:
            raise ValueError("User sandbox pools require an authenticated user and thread")
        user = self._effective_acquire_user_id(user_id)
        get_paths().thread_dir(thread_id, user_id=user)  # Validate before Docker argv/mounts.
        fresh = self._admission.acquire(user, thread_id)
        physical_id = None
        try:
            if self._closing:
                raise RuntimeError("Sandbox provider is shutting down")
            _check_cancelled()
            if self._has_explicit_policy(thread_id, user):
                physical_id = super().acquire(thread_id, user_id=user)
                self._fallback_users[physical_id] = (user, thread_id)
                return physical_id
            pool_thread = self.pool_thread(user)
            self._pool_roots.add((user, pool_thread))
            self._prepare_pool_skills(user, pool_thread)
            view_id = "user-view-" + hashlib.sha256(f"{user}:{thread_id}".encode()).hexdigest()[:24]
            with self._admission.condition:
                if view_id in self._views:
                    return view_id
            physical_id = super().acquire(pool_thread, user_id=user)
            self._activate_thread(physical_id, thread_id, user)
            physical = super().get(physical_id)
            if physical is None:
                raise RuntimeError("User sandbox became unavailable during acquisition")
            # Warm AIO's terminal service before the first user command.
            physical.execute_command_in_scope("true", scope_id="pool-bootstrap")
            physical.release_command_scope("pool-bootstrap")
            with self._admission.condition:
                self._views[view_id] = (UserSandboxView(view_id, physical), physical_id, user, thread_id)
                self._view_created[view_id] = time.monotonic()
            return view_id
        except BaseException:
            if physical_id and fresh:
                super().release(physical_id)
            if fresh:
                self._admission.release(user, thread_id)
            raise

    async def acquire_async(self, thread_id=None, *, user_id=None):
        if not self._wait_slots.acquire(blocking=False):
            raise RuntimeError("沙箱等待队列已满，请稍后重试。")
        cancelled = threading.Event()
        deadline = time.monotonic() + self._admission.timeout

        def acquire():
            token = _cancel_event.set(cancelled)
            deadline_token = _acquire_deadline.set(deadline)
            try:
                return self.acquire(thread_id, user_id=user_id)
            finally:
                _cancel_event.reset(token)
                _acquire_deadline.reset(deadline_token)
                self._wait_slots.release()

        try:
            future = asyncio.get_running_loop().run_in_executor(self._wait_executor, copy_context().run, acquire)
        except BaseException:
            self._wait_slots.release()
            raise
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError as cancellation:
            cancelled.set()
            with self._admission.condition:
                self._admission.condition.notify_all()
            while not future.done():
                try:
                    await asyncio.shield(future)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not future.cancelled() and future.exception() is None:
                from deerflow.sandbox.lease import _drain_task_after_cancellation

                rollback = asyncio.create_task(asyncio.to_thread(self.release, future.result()))
                try:
                    await _drain_task_after_cancellation(rollback)
                except Exception:
                    logger.exception("Cancelled user sandbox acquisition rollback failed")
            raise cancellation

    def get(self, sandbox_id):
        with self._admission.condition:
            entry = self._views.get(sandbox_id)
        if entry:
            return entry[0] if super().get(entry[1]) is not None else None
        if sandbox_id.startswith("user-view-"):
            return None
        return super().get(sandbox_id)

    def release(self, sandbox_id):
        with self._admission.condition:
            entry = self._views.pop(sandbox_id, None)
            self._view_created.pop(sandbox_id, None)
            fallback = self._fallback_users.pop(sandbox_id, None)
        if entry:
            view, physical_id, user, thread = entry
            try:
                view.close()
                # Shell cleanup is best effort in the SDK. Never hand remaining
                # task processes a new conversation's /mnt/user-data symlink.
                try:
                    self._close_user_terminals(physical_id)
                    remaining = self._process_snapshot(physical_id, view.id)
                    if remaining:
                        time.sleep(0.2)
                        remaining &= self._process_snapshot(physical_id, view.id)
                except Exception:
                    remaining = {(-1, -1)}
                if remaining:
                    logger.info("Recycling user sandbox %s after task process cleanup", physical_id)
                    super().destroy(physical_id)
                else:
                    super().release(physical_id)
            finally:
                self._admission.release(user, thread)
        else:
            try:
                super().release(sandbox_id)
            finally:
                if fallback:
                    self._admission.release(*fallback)
        with self._admission.condition:
            self._admission.condition.notify_all()

    def _create_sandbox(self, thread_id, sandbox_id, *, user_id=None):
        deadline = _acquire_deadline.get() or time.monotonic() + self._admission.timeout
        while True:
            _check_cancelled()
            if not self._pool_creation.acquire(blocking=False):
                if _prewarming.get():
                    raise _PrewarmSkipped()
            else:
                try:
                    with self._lock:
                        total = len(self._sandbox_infos) + len(self._warm_pool)
                    if total >= int(self._config["replicas"]):
                        if _prewarming.get():
                            raise _PrewarmSkipped()
                        self._evict_oldest_warm()
                        with self._lock:
                            total = len(self._sandbox_infos) + len(self._warm_pool)
                    if total < int(self._config["replicas"]):
                        return super()._create_sandbox(thread_id, sandbox_id, user_id=user_id)
                finally:
                    self._pool_creation.release()
            remaining = deadline - time.monotonic()
            if remaining <= 0 or self._closing:
                raise TimeoutError("沙箱并发已达到上限，等待执行资源超时，请稍后重试。")
            with self._admission.condition:
                self._admission.condition.wait(min(remaining, 1))

    def _cleanup_idle_resources(self, idle_timeout):
        from deerflow.sandbox.lease import get_sandbox_lease_manager

        manager = get_sandbox_lease_manager(self)
        with self._admission.condition:
            entries = list(self._views.items())
        for view_id, (_, physical_id, _, _) in entries:
            if manager.has_holders(view_id) or time.monotonic() - self._view_created.get(view_id, time.monotonic()) < 60:
                with self._lock:
                    self._last_activity[physical_id] = time.time()
            else:
                self.release(view_id)
        super()._cleanup_idle_resources(idle_timeout)
        if self._pool_creation.acquire(blocking=False):
            try:
                removed = cleanup_orphan_networks(self._config["container_prefix"])
                if removed:
                    logger.info("Removed %s orphaned user-sandbox networks", len(removed))
            except Exception:
                logger.warning("Could not reconcile orphaned user-sandbox networks", exc_info=True)
            finally:
                self._pool_creation.release()

    def sync_agent_skills(self, sandbox_id, *, thread_id, user_id, projection):
        if sandbox_id.startswith("user-view-"):
            if self._has_explicit_policy(thread_id, user_id):
                raise RuntimeError("Agent policy changed: start a new isolated sandbox execution")
            self._prepare_pool_skills(user_id, self.pool_thread(user_id))

    def _physical_id(self, sandbox_id):
        with self._admission.condition:
            entry = self._views.get(sandbox_id)
        return entry[1] if entry else sandbox_id

    def consume_network_policy_events(self, sandbox_id):
        return super().consume_network_policy_events(self._physical_id(sandbox_id))

    def deny_pending_network_policy_events(self, sandbox_id):
        return super().deny_pending_network_policy_events(self._physical_id(sandbox_id))

    def decide_network_policy_request(self, sandbox_id, request_id, decision):
        return super().decide_network_policy_request(self._physical_id(sandbox_id), request_id, decision)

    def prewarm(self, user_id):
        with self._admission.condition:
            if user_id in self._admission.active or self._closing:
                return
        # Login prewarm never queues behind running work or evicts another user.
        with self._pool_creation:
            with self._lock:
                if len(self._sandbox_infos) + len(self._warm_pool) >= int(self._config["replicas"]):
                    return
        token = _prewarming.set(True)
        try:
            sandbox_id = self.acquire("sandbox-prewarm", user_id=user_id)
            self.release(sandbox_id)
        except _PrewarmSkipped:
            pass
        finally:
            _prewarming.reset(token)

    async def prewarm_async(self, user_id):
        import uuid

        from deerflow.sandbox.lease import get_sandbox_lease_manager

        with self._admission.condition:
            if user_id in self._admission.active or self._closing:
                return
        with self._lock:
            if len(self._sandbox_infos) + len(self._warm_pool) >= int(self._config["replicas"]):
                return
        manager = get_sandbox_lease_manager(self)
        owner = "prewarm:" + uuid.uuid4().hex
        token = _prewarming.set(True)
        try:
            await manager.acquire_async(owner, "sandbox-prewarm", user_id=user_id)
        except _PrewarmSkipped:
            pass
        finally:
            try:
                await manager.release_async(owner)
            finally:
                _prewarming.reset(token)

    def reset(self):
        self.shutdown()

    def shutdown(self):
        with self._shutdown_lock:
            if self._pool_shutdown_complete:
                return
            self._closing = True
            with self._admission.condition:
                self._admission.closed = True
                self._admission.condition.notify_all()
            self._wait_executor.shutdown(wait=True, cancel_futures=True)
            super().shutdown()
            if getattr(self, "_instance_lease", None) is not None:
                self._instance_lease.close()
            self._pool_shutdown_complete = True
