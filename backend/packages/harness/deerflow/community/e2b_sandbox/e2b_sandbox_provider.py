"""``E2BSandboxProvider`` — DeerFlow :class:`SandboxProvider` for e2b cloud.

Configuration is read from :class:`SandboxConfig` (which has
``extra="allow"``), so any keys below can appear under ``sandbox:`` in
``config.yaml`` even though they are not declared on the model:

.. code-block:: yaml

    sandbox:
      use: deerflow.community.e2b_sandbox:E2BSandboxProvider
      api_key: $E2B_API_KEY            # required (or via E2B_API_KEY env var)
      template: code-interpreter-v1     # default: e2b code-interpreter template
      domain: e2b.dev                  # optional; for self-hosted e2b
      idle_timeout: 600                # forwarded to ``set_timeout``
      replicas: 3                      # max concurrent sandboxes
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
import logging
import os
import shlex
import signal
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

from e2b_code_interpreter import Sandbox as E2BClientSandbox

from deerflow.config import get_app_config
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider

from .e2b_sandbox import DEFAULT_E2B_HOME_DIR, E2BSandbox, _is_sandbox_gone_error

logger = logging.getLogger(__name__)


# ── Defaults ─────────────────────────────────────────────────────────────
DEFAULT_TEMPLATE = "code-interpreter-v1"  # the public e2b code-interpreter template
DEFAULT_IDLE_TIMEOUT = 1800  # 30 minutes; passed to ``Sandbox.set_timeout``.
DEFAULT_REPLICAS = 3
# Hard upper bound for ``set_timeout`` (e2b currently caps at 24h on the
# free plan; passing an excessive value is rejected by the control-plane).
MAX_E2B_TIMEOUT = 24 * 60 * 60

# Metadata keys we attach to every sandbox so we can discover ours via
# ``Sandbox.list(query={...})`` from any gateway process.
META_KEY_USER = "deer_flow_user"
META_KEY_THREAD = "deer_flow_thread"
META_KEY_PROVIDER = "deer_flow_provider"
META_VAL_PROVIDER = "e2b_sandbox_provider"


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
        # Per-(user,thread) lock to serialise acquire() against itself.
        self._thread_locks: dict[tuple[str, str], threading.Lock] = {}
        # Warm pool: released sandboxes whose remote micro-VM is still alive.
        # ``OrderedDict`` maintains insertion / move_to_end order for LRU.
        self._warm_pool: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._shutdown_called = False

        self._config = self._load_config()

        atexit.register(self.shutdown)
        self._register_signal_handlers()

    def _load_config(self) -> dict[str, Any]:
        """Read e2b options off ``SandboxConfig`` (``extra="allow"``)."""
        sandbox_config = get_app_config().sandbox

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
        replicas = DEFAULT_REPLICAS if replicas is None else max(1, int(replicas))

        return {
            "api_key": api_key,
            "template": _opt("template") or _opt("image") or DEFAULT_TEMPLATE,
            "domain": _opt("domain"),
            "home_dir": _opt("home_dir") or DEFAULT_E2B_HOME_DIR,
            "idle_timeout": idle_timeout,
            "replicas": replicas,
            "mounts": _opt("mounts") or [],
            "environment": self._resolve_env_vars(_opt("environment") or {}),
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
        return await asyncio.to_thread(self.acquire, thread_id, user_id=effective_user_id)

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
            return None

        try:
            self._refresh_remote_timeout(sandbox.client)
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("Failed to refresh timeout on reuse: %s", e)

        logger.info(
            "Reusing in-process e2b sandbox %s for user/thread %s/%s",
            sid,
            user_id,
            thread_id,
        )
        return sid

    def _reclaim_warm_pool_sandbox(self, thread_id: str, *, user_id: str) -> str | None:
        key = self._thread_key(thread_id, user_id)
        seed = self._stable_seed(thread_id, user_id)
        with self._lock:
            target_id = next(
                (sid for sid, (s, _) in self._warm_pool.items() if s == seed),
                None,
            )
            if target_id is None:
                return None
            self._warm_pool.pop(target_id)

        sandbox_cls = self._get_sandbox_cls()
        try:
            client = self._reconnect_client(sandbox_cls, target_id)
        except Exception as e:
            logger.warning(
                "Warm-pool e2b sandbox %s failed to reconnect, dropping: %s",
                target_id,
                e,
            )
            return None

        # Verify the reconnected client actually corresponds to a live VM.
        # ``Sandbox.connect`` succeeds for paused/expired sandboxes too on
        # some SDK versions, but the very next command then fails with
        # "sandbox not found" mid-tool-call. Pinging here moves that failure
        # into the acquire path, where we cleanly fall back to creating a
        # fresh sandbox.
        if not self._client_alive(client):
            logger.warning(
                "Warm-pool e2b sandbox %s is no longer alive (reaped by control plane); dropping and falling back to create",
                target_id,
            )
            self._safe_close_client(client)
            return None

        self._refresh_remote_timeout(client)
        try:
            self._bootstrap_sandbox_paths(client)
        except Exception as e:
            logger.debug("bootstrap on warm-pool reclaim failed: %s", e)
        sandbox = E2BSandbox(id=target_id, client=client, home_dir=self._config["home_dir"])
        with self._lock:
            self._sandboxes[target_id] = sandbox
            self._thread_sandboxes[key] = target_id
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
        list_kwargs = self._common_kwargs()
        try:
            running = sandbox_cls.list(  # type: ignore[attr-defined]
                query={
                    "metadata": {
                        META_KEY_PROVIDER: META_VAL_PROVIDER,
                        META_KEY_USER: user_id,
                        META_KEY_THREAD: thread_id,
                    }
                },
                **list_kwargs,
            )
        except TypeError:
            try:
                running = sandbox_cls.list(
                    metadata={
                        META_KEY_PROVIDER: META_VAL_PROVIDER,
                        META_KEY_USER: user_id,
                        META_KEY_THREAD: thread_id,
                    },
                    **list_kwargs,
                )
            except Exception as e:
                logger.debug("e2b Sandbox.list() unavailable, skipping discovery: %s", e)
                return None
        except Exception as e:
            logger.debug(
                "e2b Sandbox.list() raised while discovering thread %s: %s",
                thread_id,
                e,
            )
            return None

        # Pick the first matching candidate; tolerate either ``SandboxInfo``
        # objects with ``sandbox_id`` or plain dicts.
        # Normalise the return value of ``Sandbox.list()``:
        #   * Older SDKs (<= 1.x) returned a plain ``list[SandboxInfo]`` — directly iterable.
        #   * e2b-code-interpreter >= 2.x returns a ``SandboxPaginator`` exposing
        #     ``has_next: bool`` and ``next_items() -> list[SandboxInfo]`` instead
        #     of being iterable. Walking pages keeps discovery correct when the
        #     org has more sandboxes than fit in a single page.
        def _iter_running(obj):
            if obj is None:
                return
            if hasattr(obj, "next_items") and hasattr(obj, "has_next"):
                for _ in range(50):
                    try:
                        page = obj.next_items()
                    except Exception as exc:
                        logger.debug("SandboxPaginator.next_items() failed: %s", exc)
                        return
                    if not page:
                        return
                    yield from page
                    if not getattr(obj, "has_next", False):
                        return
                return
            try:
                yield from obj
            except TypeError:
                logger.debug("Sandbox.list() returned non-iterable %s; ignoring", type(obj).__name__)

        target_id: str | None = None
        for entry in _iter_running(running):
            sid = getattr(entry, "sandbox_id", None) or (entry.get("sandbox_id") if isinstance(entry, dict) else None)
            metadata = getattr(entry, "metadata", None) or (entry.get("metadata") if isinstance(entry, dict) else {}) or {}
            if metadata.get(META_KEY_USER) != user_id:
                continue
            if metadata.get(META_KEY_THREAD) != thread_id:
                continue
            target_id = sid
            break

        if not target_id:
            return None

        try:
            client = self._reconnect_client(sandbox_cls, target_id)
        except Exception as e:
            logger.warning(
                "Discovered e2b sandbox %s could not be reconnected: %s",
                target_id,
                e,
            )
            return None

        if not self._client_alive(client):
            logger.warning(
                "Discovered e2b sandbox %s is no longer alive; falling back to create",
                target_id,
            )
            self._safe_close_client(client)
            return None

        self._refresh_remote_timeout(client)
        try:
            self._bootstrap_sandbox_paths(client)
        except Exception as e:
            logger.debug("bootstrap on remote discovery failed: %s", e)
        sandbox = E2BSandbox(id=target_id, client=client, home_dir=self._config["home_dir"])
        with self._lock:
            self._sandboxes[target_id] = sandbox
            self._thread_sandboxes[self._thread_key(thread_id, user_id)] = target_id
        logger.info(
            "Discovered remote e2b sandbox %s for user/thread %s/%s (seed=%s)",
            target_id,
            user_id,
            thread_id,
            seed,
        )
        return target_id

    def _create_sandbox(self, thread_id: str | None, *, user_id: str) -> str:
        """Allocate a fresh e2b sandbox and hydrate it with configured mounts."""
        replicas = int(self._config["replicas"])
        with self._lock:
            in_use = len(self._sandboxes) + len(self._warm_pool)
        if in_use >= replicas:
            evicted = self._evict_oldest_warm()
            if evicted is None:
                logger.warning(
                    "All %d e2b replica slots are in active use; creating a new sandbox beyond the soft limit (active=%d, warm=%d)",
                    replicas,
                    len(self._sandboxes),
                    len(self._warm_pool),
                )

        sandbox_cls = self._get_sandbox_cls()
        metadata: dict[str, str] = {
            META_KEY_PROVIDER: META_VAL_PROVIDER,
        }
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
            raise

        sandbox_id: str = getattr(client, "sandbox_id", None) or str(uuid.uuid4())[:8]

        # Materialise DeerFlow's virtual path layout (/mnt/user-data/...) inside
        # the e2b VM. Without this step shell commands the agent emits — which
        # use the same /mnt/user-data prefix as LocalSandbox / AioSandbox — fail
        # with PermissionError because /mnt is owned by root in the e2b
        # template. See the path-mapping note in :class:`E2BSandbox`.
        try:
            self._bootstrap_sandbox_paths(client)
        except Exception as e:
            logger.warning(
                "Failed to bootstrap virtual paths in e2b sandbox %s: %s",
                sandbox_id,
                e,
            )

        # One-shot mount uploads.  e2b has no host bind-mount, so we copy
        # files from ``host_path`` into ``container_path`` at sandbox start.
        try:
            self._apply_mounts(client)
        except Exception as e:
            logger.warning("Failed to apply some mounts to e2b sandbox %s: %s", sandbox_id, e)

        sandbox = E2BSandbox(id=sandbox_id, client=client, home_dir=self._config["home_dir"])
        with self._lock:
            self._sandboxes[sandbox_id] = sandbox
            if thread_id:
                self._thread_sandboxes[self._thread_key(thread_id, user_id)] = sandbox_id

        logger.info(
            "Created e2b sandbox %s for user/thread %s/%s (template=%s, replicas=%d)",
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

    def _reconnect_client(self, sandbox_cls: type[E2BClientSandbox], sandbox_id: str) -> E2BClientSandbox:
        """Connect to an existing e2b sandbox by id, with consistent kwargs."""
        return sandbox_cls.connect(sandbox_id, **self._common_kwargs())  # type: ignore[attr-defined]

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
        with passwordless sudo, so the ``sudo`` calls below succeed without
        interactive prompts. If the customer template removes that, the
        commands fail loudly here and we fall back to silently relying on the
        path remap inside ``E2BSandbox`` — agent shell commands will still
        fail, but the read/write/list APIs continue to work.
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
            logger.warning(
                "e2b bootstrap script raised: %s (agent shell commands using /mnt/user-data may fail until the VM is recycled)",
                e,
            )
            return

        stdout = getattr(result, "stdout", "") or ""
        stderr = getattr(result, "stderr", "") or ""
        exit_code = getattr(result, "exit_code", 0)
        if exit_code not in (0, None) or "BOOTSTRAP_OK" not in stdout:
            logger.warning(
                "e2b bootstrap script exited with code=%s; stderr=%s",
                exit_code,
                stderr.strip(),
            )

    def _apply_mounts(self, client: E2BClientSandbox) -> None:
        mounts = self._config.get("mounts") or []
        if not mounts:
            return
        for mount in mounts:
            try:
                host_path = Path(getattr(mount, "host_path", "") or "")
                container_path = (getattr(mount, "container_path", "") or "").rstrip("/")
                read_only = bool(getattr(mount, "read_only", False))
            except AttributeError:
                host_path = Path(mount.get("host_path", ""))
                container_path = (mount.get("container_path", "") or "").rstrip("/")
                read_only = bool(mount.get("read_only", False))

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

        We only mirror files whose host-side counterpart is missing or has a
        different size — this gives an effective per-file dedup with a single
        round-trip per release for unchanged trees, and avoids re-downloading
        large generated files (e.g. PDFs, datasets) on every tool turn that
        triggers a release.

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

        thread_root = paths.thread_dir(thread_id, user_id=user_id) / "user-data"
        host_targets: dict[str, Path] = {sub: thread_root / sub for sub in self._SYNC_BACK_SUBDIRS}

        # Build a single shell command that lists all files in the sync dirs
        # with size + path, NUL-separated for safe parsing of weird filenames.
        # find -printf '%s\t%p\0' keeps us to one round-trip regardless of
        # how many subdirs we mirror.
        #
        # We list using the *physical* /home/user paths (the bootstrap symlink
        # /mnt/user-data -> /home/user follows transparently), then translate
        # each hit back to the /mnt/user-data prefix before calling
        # ``E2BSandbox.download_file``: that method enforces a security check
        # that the path is under ``VIRTUAL_PATH_PREFIX`` (/mnt/user-data) and
        # internally re-resolves it to /home/user via ``_resolve_path``.
        find_targets = " ".join(shlex.quote(f"{home_dir}/{sub}") for sub in self._SYNC_BACK_SUBDIRS)
        list_cmd = f'for d in {find_targets}; do   [ -d "$d" ] && find "$d" -type f -printf \'%s\\t%p\\0\' 2>/dev/null; done'

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
            return

        synced = 0
        skipped = 0
        from .e2b_sandbox import _MAX_DOWNLOAD_SIZE

        for entry in stdout.split("\0"):
            entry = entry.strip()
            if not entry:
                continue
            try:
                size_str, remote_path = entry.split("\t", 1)
                remote_size = int(size_str)
            except ValueError:
                logger.debug("e2b sync: unparseable entry %r", entry)
                continue

            if remote_size > _MAX_DOWNLOAD_SIZE:
                logger.warning(
                    "e2b sync: skipping oversize artefact %s (%d bytes > %d cap)",
                    remote_path,
                    remote_size,
                    _MAX_DOWNLOAD_SIZE,
                )
                skipped += 1
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

            try:
                if host_path.exists() and host_path.stat().st_size == remote_size:
                    skipped += 1
                    continue
            except OSError:
                pass

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

            try:
                host_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = host_path.with_name(host_path.name + ".e2bsync.tmp")
                tmp_path.write_bytes(data)
                tmp_path.replace(host_path)
                synced += 1
            except OSError as e:
                logger.warning("e2b sync: failed to write %s on host: %s", host_path, e)

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
        if src.is_file():
            target = f"{dest_dir}/{src.name}"
            with src.open("rb") as fh:
                client.files.write(target, fh.read())
            if read_only:
                try:
                    client.commands.run(f"chmod a-w {shlex.quote(target)}")
                except Exception:
                    pass
            return

        for path in src.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(src).as_posix()
            target = f"{dest_dir}/{rel}"
            try:
                make_dir = getattr(client.files, "make_dir", None)
                if callable(make_dir):
                    parent = target.rsplit("/", 1)[0]
                    if parent and parent != dest_dir:
                        make_dir(parent)
            except Exception:
                pass
            with path.open("rb") as fh:
                client.files.write(target, fh.read())
        if read_only:
            try:
                client.commands.run(f"chmod -R a-w {shlex.quote(dest_dir)}")
            except Exception:
                pass

    def _evict_oldest_warm(self) -> str | None:
        with self._lock:
            if not self._warm_pool:
                return None
            evict_id, (_, _) = self._warm_pool.popitem(last=False)

        try:
            client = self._reconnect_client(self._get_sandbox_cls(), evict_id)
        except Exception as e:
            logger.warning(
                "Evicted warm-pool e2b sandbox %s could not be reconnected for kill: %s",
                evict_id,
                e,
            )
            return evict_id

        try:
            kill = getattr(client, "kill", None)
            if callable(kill):
                kill()
        except Exception as e:
            logger.warning("Failed to kill evicted e2b sandbox %s: %s", evict_id, e)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
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
        sandbox: E2BSandbox | None = None
        seed: str | None = None

        with self._lock:
            sandbox = self._sandboxes.pop(sandbox_id, None)
            # Find the (user, thread) the sandbox was bound to.
            removed_keys = [key for key, sid in self._thread_sandboxes.items() if sid == sandbox_id]
            for key in removed_keys:
                self._thread_sandboxes.pop(key, None)
            if removed_keys:
                user_id, thread_id = removed_keys[0]
                seed = self._stable_seed(thread_id, user_id)

        if sandbox is None:
            return

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
            self._refresh_remote_timeout(sandbox.client)
        except Exception as e:
            logger.debug("Failed to refresh timeout during release: %s", e)

        try:
            sandbox.close()
        except Exception as e:
            logger.warning("Error closing e2b sandbox %s during release: %s", sandbox_id, e)

        with self._lock:
            self._warm_pool[sandbox_id] = (seed or "", time.time())
            self._warm_pool.move_to_end(sandbox_id)
        logger.info("Released e2b sandbox %s to warm pool", sandbox_id)

    def _kill_and_close(self, sandbox: E2BSandbox) -> None:
        client = getattr(sandbox, "_client", None)
        if client is not None:
            kill = getattr(client, "kill", None)
            if callable(kill):
                try:
                    kill()
                except Exception as e:
                    logger.debug(
                        "kill() on e2b sandbox %s raised (probably already gone): %s",
                        sandbox.id,
                        e,
                    )
        try:
            sandbox.close()
        except Exception:
            pass

    def reset(self) -> None:
        with self._lock:
            self._sandboxes.clear()
            self._thread_sandboxes.clear()
            self._thread_locks.clear()
            self._warm_pool.clear()

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown_called:
                return
            self._shutdown_called = True
            active = list(self._sandboxes.items())
            warm_ids = list(self._warm_pool.keys())
            self._sandboxes.clear()
            self._warm_pool.clear()
            self._thread_sandboxes.clear()

        logger.info(
            "Shutting down E2BSandboxProvider: %d active + %d warm sandboxes",
            len(active),
            len(warm_ids),
        )

        for sandbox_id, sandbox in active:
            try:
                kill = getattr(sandbox.client, "kill", None)
                if callable(kill):
                    kill()
            except Exception as e:
                logger.warning(
                    "Failed to kill active e2b sandbox %s during shutdown: %s",
                    sandbox_id,
                    e,
                )
            try:
                sandbox.close()
            except Exception:
                pass

        sandbox_cls = self._get_sandbox_cls()
        for sandbox_id in warm_ids:
            try:
                client = self._reconnect_client(sandbox_cls, sandbox_id)
            except Exception as e:
                logger.warning(
                    "Failed to reconnect warm-pool e2b sandbox %s for shutdown: %s",
                    sandbox_id,
                    e,
                )
                continue
            try:
                kill = getattr(client, "kill", None)
                if callable(kill):
                    kill()
            except Exception as e:
                logger.warning(
                    "Failed to kill warm-pool e2b sandbox %s during shutdown: %s",
                    sandbox_id,
                    e,
                )
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
