"""``BoxdSandboxProvider``: DeerFlow :class:`SandboxProvider` backed by boxd.

Runs each DeerFlow sandbox as an isolated `boxd <https://boxd.sh?ref=deer-flow>`_
machine: a full Ubuntu microVM with a persistent disk. The provider creates
one machine per ``(user, thread)``, reuses it within the process, and parks
released machines in a warm pool (shared :class:`WarmPoolLifecycleMixin`
machinery) for fast reclaim. The idle reaper deletes warm machines after
``idle_timeout``.

A fresh machine for a thread gets the thread's Gateway-side files (uploads,
outputs, workspace) and the skills projection before it is handed out.
Release mirrors ``/mnt/user-data/outputs`` back to the Gateway, so artifacts
stay downloadable after the machine is gone.

Config is read off :class:`SandboxConfig` (``extra="allow"``); see this
package's ``__init__`` docstring for the full set. The ``boxd`` SDK is imported
lazily, so the harness installs without it.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import math
import os
import posixpath
import shlex
import stat
import tarfile
import tempfile
import threading
import time
import unicodedata
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from deerflow.community.provider_credentials import resolve_api_key
from deerflow.config import get_app_config
from deerflow.sandbox.acquire_serialization import AcquireSerializer, AcquireSerializerClosed
from deerflow.sandbox.download import DEFAULT_DOWNLOAD_LIMIT
from deerflow.sandbox.identity import derive_sandbox_scope_token
from deerflow.sandbox.sandbox import Sandbox, _validate_extra_env
from deerflow.sandbox.sandbox_provider import SandboxProvider

from ..warm_pool_lifecycle import WarmPoolLifecycleMixin
from .boxd_sandbox import DEFAULT_COMMAND_TIMEOUT, BoxdSandbox

if TYPE_CHECKING:
    from boxd import Boxd

    from deerflow.skills.projection import SkillProjectionPaths

logger = logging.getLogger(__name__)

DEFAULT_NAME_PREFIX = "deer-flow-"
DEFAULT_READY_TIMEOUT = 120.0
USER_DATA_ROOT = "/mnt/user-data"
OUTPUTS_ROOT = f"{USER_DATA_ROOT}/outputs"
SKILL_CATEGORIES = ("public", "custom", "legacy", "integrations")
# Machine sizes boxd offers, as vCPU -> memory in GiB.
MACHINE_SIZES = {1: 4, 2: 8, 4: 16, 8: 32}
VALID_REGIONS = frozenset({"fra", "nyc"})
_BOOTSTRAP_TIMEOUT = 60.0
_UPLOAD_EXTRACT_TIMEOUT = 300.0
# Deadline for each unary SDK call; an upload of up to 128 MiB is one call.
_CLIENT_TIMEOUT = 180.0
_LABEL_APP = "deer-flow"
_LABEL_SCOPE = "deer-flow-scope"
_LABEL_GENERATION = "deer-flow-generation"
_PROTECTED_ROOTS = ("/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/proc", "/root", "/run", "/sbin", "/sys", "/usr", "/var")
_WINDOWS_RESERVED_NAMES = frozenset({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {f"{prefix}{digit}" for prefix in ("COM", "LPT") for digit in "123456789¹²³"})


def _import_client() -> type[Boxd]:
    """Import boxd's ``Boxd`` client lazily (optional dependency)."""
    try:
        from boxd import Boxd
    except ImportError as e:  # pragma: no cover - depends on the optional dependency
        raise ImportError("BoxdSandboxProvider requires the optional 'boxd' dependency. Install it with: pip install 'deerflow-harness[boxd]' or pip install 'boxd>=0.3.2'.") from e
    return Boxd


def _validate_skills_root(container_path: str) -> str:
    """The skills categories are replaced recursively, so the root must be a dedicated path."""
    normalized = posixpath.normpath(container_path or "")
    if not normalized.startswith("/") or normalized == "/" or normalized != (container_path or "").rstrip("/"):
        raise ValueError(f"skills.container_path {container_path!r} is not a safe boxd skills root: use a normalized absolute path such as /mnt/skills")
    if normalized in {"/home", "/home/boxd", "/mnt", "/tmp"} or any(normalized == root or normalized.startswith(f"{root}/") for root in _PROTECTED_ROOTS):
        raise ValueError(f"skills.container_path {container_path!r} is not a safe boxd skills root: it is a system directory")
    if normalized == USER_DATA_ROOT or normalized.startswith(f"{USER_DATA_ROOT}/") or USER_DATA_ROOT.startswith(f"{normalized}/"):
        raise ValueError(f"skills.container_path {container_path!r} must not overlap {USER_DATA_ROOT}")
    return normalized


class _ShutdownIncompleteError(RuntimeError):
    """Cleanup still owns acquisitions or machine deletions that need a retry."""


class _AcquireTicket:
    """Hands an acquire's result to a caller that may have been cancelled."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.abandoned = False
        self.sandbox_id: str | None = None


class _UploadBudget:
    """File-count and byte limits for one tar upload into a machine."""

    def __init__(self, max_files: int, max_bytes: int) -> None:
        self.max_files = max_files
        self.max_bytes = max_bytes
        self.files = 0
        self.bytes = 0

    def admit(self, size: int) -> bool:
        if self.files + 1 > self.max_files or self.bytes + size > self.max_bytes:
            return False
        self.files += 1
        self.bytes += size
        return True


class BoxdSandboxProvider(WarmPoolLifecycleMixin[BoxdSandbox], SandboxProvider):
    """Run each DeerFlow sandbox as an isolated boxd machine."""

    uses_thread_data_mounts = False
    needs_upload_permission_adjustment = True
    # The machine sees only the skills uploaded into it, so a per-Agent
    # projection from sync_agent_skills cannot be bypassed from the shell.
    supports_agent_skill_isolation = True
    _idle_checker_thread_name = "boxd-idle-reaper"
    _MAX_SYNC_FILES = 2000
    _MAX_SYNC_TOTAL_BYTES = 512 * 1024 * 1024
    _MAX_SYNC_LISTING_BYTES = 512 * 1024
    _SYNC_DEADLINE_SECONDS = 120.0
    _MAX_UPLOAD_FILES = 5000
    _MAX_UPLOAD_BYTES = 128 * 1024 * 1024
    _UPLOAD_CHUNK_BYTES = 1024 * 1024

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sandboxes: dict[str, BoxdSandbox] = {}
        self._thread_sandboxes: dict[tuple[str, str], str] = {}
        self._warm_pool: dict[str, tuple[BoxdSandbox, float]] = {}
        self._acquire_serializer: AcquireSerializer[str] = AcquireSerializer(thread_name_prefix="boxd-acquire-wait")
        self._idle_checker_stop = threading.Event()
        self._idle_checker_thread: threading.Thread | None = None
        self._shutdown_called = False
        self._shutdown_complete = False
        self._shutdown_lock = threading.Lock()
        self._accepting = True
        self._acquires = 0
        # Keyed by object identity, including wrappers for failed creates.
        self._pending_closes: dict[int, BoxdSandbox] = {}
        self._closing: set[int] = set()
        # Callers that received each active sandbox and have not released it.
        self._claims: dict[str, int] = {}
        self._client: Boxd | None = None
        self._config = self._load_config()
        atexit.register(self._shutdown_at_exit)
        self._start_idle_checker()

    # ── Config ───────────────────────────────────────────────────────────

    @staticmethod
    def _optional_int(name: str, value: Any, *, minimum: int) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"sandbox.{name} must be an integer >= {minimum}")
        return value

    @staticmethod
    def _memory_gib(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        text = str(value).strip().upper().removesuffix("IB").removesuffix("B").removesuffix("G")
        if text.isdigit():
            return int(text)
        raise ValueError("sandbox.memory must be a size such as 8G")

    def _load_config(self) -> dict[str, Any]:
        app_config = get_app_config()
        sandbox_config = app_config.sandbox

        def option(name: str) -> Any:
            return getattr(sandbox_config, name, None)

        # $VARS in config.yaml are already resolved by AppConfig; resolving
        # again would rewrite a secret that itself starts with $.
        environment = dict(option("environment") or {})
        _validate_extra_env(environment)

        region = option("region")
        if region is not None and region not in VALID_REGIONS:
            raise ValueError(f"sandbox.region must be one of {sorted(VALID_REGIONS)}")

        vcpu = self._optional_int("vcpu", option("vcpu"), minimum=1)
        memory = self._memory_gib(option("memory"))
        if vcpu is not None and vcpu not in MACHINE_SIZES:
            raise ValueError(f"sandbox.vcpu must be one of {sorted(MACHINE_SIZES)}")
        if memory is not None and memory not in MACHINE_SIZES.values():
            raise ValueError(f"sandbox.memory must be one of {[f'{gib}G' for gib in MACHINE_SIZES.values()]}")
        if vcpu is not None and memory is not None and MACHINE_SIZES[vcpu] != memory:
            raise ValueError(f"sandbox.vcpu={vcpu} goes with sandbox.memory={MACHINE_SIZES[vcpu]}G")
        if vcpu is not None and memory is None:
            memory = MACHINE_SIZES[vcpu]
        if memory is not None and vcpu is None:
            vcpu = next(cpu for cpu, gib in MACHINE_SIZES.items() if gib == memory)

        labels = option("labels") or {}
        if not isinstance(labels, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in labels.items()):
            raise ValueError("sandbox.labels must map strings to strings")

        name_prefix = option("name_prefix") or DEFAULT_NAME_PREFIX
        if not isinstance(name_prefix, str) or not name_prefix.replace("-", "").isalnum() or name_prefix != name_prefix.lower():
            raise ValueError("sandbox.name_prefix may hold lowercase letters, digits and '-'")

        ready_timeout = option("ready_timeout")
        try:
            ready_timeout = float(DEFAULT_READY_TIMEOUT if ready_timeout is None else ready_timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("sandbox.ready_timeout must be positive") from exc
        if not math.isfinite(ready_timeout) or ready_timeout <= 0:
            raise ValueError("sandbox.ready_timeout must be positive")

        command_timeout = option("bash_command_timeout")
        try:
            command_timeout = float(DEFAULT_COMMAND_TIMEOUT if command_timeout is None else command_timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("sandbox.bash_command_timeout must be positive") from exc
        if not math.isfinite(command_timeout) or command_timeout <= 0:
            raise ValueError("sandbox.bash_command_timeout must be positive")

        replicas = option("replicas")
        idle_timeout = option("idle_timeout")
        return {
            "command_timeout": command_timeout,
            # Blank, absent or template values read as None; the SDK then
            # reads BOXD_API_KEY from the environment.
            # A boxd-specific name, so a key configured for another provider
            # under sandbox.api_key is never sent to boxd.
            "api_key": resolve_api_key(option("boxd_api_key")),
            "org": option("org"),
            "region": region,
            "vcpu": vcpu,
            "memory": f"{memory}G" if memory is not None else None,
            "from_snapshot": option("from_snapshot"),
            "auto_suspend_timeout": self._optional_int("auto_suspend_timeout", option("auto_suspend_timeout"), minimum=0),
            "ready_timeout": ready_timeout,
            "labels": dict(labels),
            "name_prefix": name_prefix,
            "environment": environment,
            "skills_container_path": _validate_skills_root(app_config.skills.container_path),
            "replicas": replicas if replicas is not None else self.DEFAULT_REPLICAS,
            "idle_timeout": idle_timeout if idle_timeout is not None else self.DEFAULT_IDLE_TIMEOUT,
        }

    def _get_client(self) -> Boxd:
        with self._lock:
            if self._client is not None:
                return self._client
        client_cls = _import_client()
        if self._config["api_key"] is None and not os.environ.get("BOXD_API_KEY"):
            raise ValueError("BoxdSandboxProvider needs an API key: set sandbox.boxd_api_key in config.yaml or the BOXD_API_KEY environment variable")
        client = client_cls(api_key=self._config["api_key"], region=self._config["region"], timeout=_CLIENT_TIMEOUT)
        with self._lock:
            if self._client is None:
                self._client = client
            return self._client

    # ── Identity ─────────────────────────────────────────────────────────

    @staticmethod
    def _scope_from_sandbox_id(sandbox_id: str) -> str:
        # Local IDs append the machine generation to the stable scope token.
        return sandbox_id.partition("-")[0]

    @staticmethod
    def _thread_key(thread_id: str, user_id: str | None) -> tuple[str, str]:
        return (user_id or "", thread_id)

    def _machine_name(self, scope_id: str) -> str:
        # Names are unique per owner and are not free again the moment a
        # machine is deleted, so each generation gets a random suffix.
        return f"{self._config['name_prefix']}{scope_id}-{uuid.uuid4().hex[:6]}"

    # ── Warm pool plumbing ───────────────────────────────────────────────

    def _start_idle_checker(self) -> None:
        if self._config["idle_timeout"] <= 0:
            return
        super()._start_idle_checker()

    def _active_count_locked(self) -> int:
        return len(self._sandboxes) + len(self._pending_closes)

    def _cleanup_idle_resources(self, idle_timeout: float) -> None:
        self._retry_pending_closes()
        super()._cleanup_idle_resources(idle_timeout)

    def _destroy_warm_entry(self, sandbox_id: str, entry: BoxdSandbox, *, reason: str) -> None:
        self._close_quietly(entry, context=f"warm pool, reason={reason}")

    def _close_quietly(self, sandbox: BoxdSandbox, *, context: str) -> None:
        """Own deletion until it is accepted; keep failures for a later retry."""
        token = id(sandbox)
        with self._lock:
            self._pending_closes[token] = sandbox
            if token in self._closing:
                return
            self._closing.add(token)
        closed = False
        try:
            sandbox.close()
        except Exception as e:
            logger.warning("Error deleting boxd sandbox %s (%s): %s", sandbox.id, context, e)
        else:
            closed = True
        finally:
            with self._lock:
                if closed:
                    self._pending_closes.pop(token, None)
                self._closing.discard(token)

    def _retry_pending_closes(self) -> None:
        with self._lock:
            pending = list(self._pending_closes.values())
        for sandbox in pending:
            self._close_quietly(sandbox, context="retry deletion")

    def _invalidate_sandbox(self, sandbox_id: str, reason: str) -> None:
        """Deregister a sandbox whose machine is gone, and finish its cleanup."""
        scope_id = self._scope_from_sandbox_id(sandbox_id)
        with self._lock:
            current = self._sandboxes.pop(sandbox_id, None)
            if current is None:
                warm_entry = self._warm_pool.get(scope_id)
                if warm_entry is None or warm_entry[0].id != sandbox_id:
                    return
                current, _ = self._warm_pool.pop(scope_id)
            self._claims.pop(sandbox_id, None)
            for key in [key for key, value in self._thread_sandboxes.items() if value == sandbox_id]:
                self._thread_sandboxes.pop(key, None)
            self._pending_closes[id(current)] = current
        logger.warning("Invalidating boxd sandbox %s: %s", sandbox_id, reason)
        self._close_quietly(current, context="terminal failure")

    # ── Acquire ──────────────────────────────────────────────────────────

    @contextmanager
    def _acquiring(self) -> Iterator[None]:
        with self._lock:
            if not self._accepting:
                raise RuntimeError("boxd provider is retired or shutting down")
            self._acquires += 1
        try:
            yield
        finally:
            with self._lock:
                self._acquires -= 1

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        return self._acquire(thread_id, user_id)

    def _acquire(self, thread_id: str | None, user_id: str | None, ticket: _AcquireTicket | None = None) -> str:
        with self._acquiring():
            if thread_id is None:
                scope_id = uuid.uuid4().hex[:8]
                sandbox_id = self._publish_sandbox(self._create_sandbox(scope_id, thread_id=None, user_id=user_id))
            else:
                key = self._thread_key(thread_id, user_id)
                scope_id = derive_sandbox_scope_token(user_id=user_id or "", thread_id=thread_id)
                with self._acquire_serializer.hold(scope_id):
                    sandbox_id = self._acquire_scope_locked(key, scope_id, thread_id=thread_id, user_id=user_id)
        if ticket is not None:
            with ticket.lock:
                ticket.sandbox_id = sandbox_id
                abandoned = ticket.abandoned
            if abandoned:
                self._drop_claim(sandbox_id)
        return sandbox_id

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        """Acquire without blocking the event loop.

        The whole synchronous acquire (serializer wait and body) runs on the
        serializer's dedicated executor. A cancelled caller never receives the
        sandbox id, so it gives back the claim that the worker took for it,
        either right away or when the worker finishes. A sandbox whose last
        claim is given back is released to the warm pool, where the idle
        reaper deletes it. Neither path depends on the event loop.
        """
        ticket = _AcquireTicket()
        try:
            return await self._acquire_serializer.run_on_executor(partial(self._acquire, thread_id, user_id, ticket))
        except asyncio.CancelledError:
            with ticket.lock:
                ticket.abandoned = True
                sandbox_id = ticket.sandbox_id
            if sandbox_id is not None:
                # release() can transfer files and wait on the scope lock.
                threading.Thread(target=self._drop_claim, args=(sandbox_id,), name="boxd-abandoned-release", daemon=True).start()
            raise

    def _drop_claim(self, sandbox_id: str) -> None:
        """Give back the claim of a caller that never received ``sandbox_id``."""
        try:
            self.release(sandbox_id)
        except AcquireSerializerClosed:
            pass  # reset/shutdown owns the sandbox now
        except Exception:
            logger.warning("Could not release abandoned boxd sandbox %s", sandbox_id, exc_info=True)

    def _publish_sandbox(self, sandbox: BoxdSandbox, key: tuple[str, str] | None = None) -> str:
        with self._lock:
            if self._accepting:
                self._sandboxes[sandbox.id] = sandbox
                self._claims[sandbox.id] = 1
                if key is not None:
                    self._thread_sandboxes[key] = sandbox.id
                return sandbox.id
        # The worker that created the machine owns its cleanup, even when the
        # caller abandoned the await or shutdown closed admission meanwhile.
        self._close_quietly(sandbox, context="acquired after provider retirement")
        raise RuntimeError("boxd provider retired or shut down during acquire")

    def _acquire_scope_locked(self, key: tuple[str, str], scope_id: str, *, thread_id: str, user_id: str | None) -> str:
        with self._lock:
            if not self._accepting:
                raise RuntimeError("boxd provider is retired or shutting down")
            existing = self._thread_sandboxes.get(key)
            if existing is not None and existing in self._sandboxes:
                self._claims[existing] = self._claims.get(existing, 0) + 1
                return existing

        reclaimed = self._reclaim_warm_pool(scope_id)
        if reclaimed is not None:
            with self._lock:
                if not self._accepting:
                    raise RuntimeError("boxd provider retired or shut down during acquire")
                self._thread_sandboxes[key] = reclaimed
            return reclaimed

        sandbox = self._create_sandbox(scope_id, thread_id=thread_id, user_id=user_id)
        return self._publish_sandbox(sandbox, key)

    def _create_sandbox(self, scope_id: str, *, thread_id: str | None, user_id: str | None) -> BoxdSandbox:
        generation = uuid.uuid4().hex
        sandbox_id = f"{scope_id}-{generation}"
        replicas, total = self._replica_count()
        if total >= replicas:
            evicted = self._evict_oldest_warm()
            self._log_replicas_soft_cap(replicas, sandbox_id, evicted)

        client = self._get_client()
        labels = {**self._config["labels"], _LABEL_APP: "sandbox", _LABEL_SCOPE: scope_id, _LABEL_GENERATION: generation}
        create_kwargs: dict[str, Any] = {
            "org": self._config["org"],
            # The agent runs untrusted code: an isolated machine joins no
            # private network and holds no boxd credentials.
            "isolated": True,
            "labels": labels,
        }
        for name in ("region", "vcpu", "memory", "from_snapshot", "auto_suspend_timeout"):
            if self._config[name] is not None:
                create_kwargs[name] = self._config[name]
        try:
            machine = client.machines.create(self._machine_name(scope_id), **create_kwargs)
        except BaseException:
            self._delete_generation(client, generation, sandbox_id)
            raise
        sandbox = BoxdSandbox(
            sandbox_id,
            client,
            machine.id,
            region=self._config["region"],
            default_env=self._config["environment"],
            default_command_timeout=self._config["command_timeout"],
        )
        try:
            client.machines.wait_until_ready(machine.id, timeout=self._config["ready_timeout"], region=self._config["region"])
            self._bootstrap(sandbox)
            if thread_id is not None and user_id:
                self._restore_thread_files(sandbox, thread_id=thread_id, user_id=user_id)
                self._upload_shared_skills(sandbox, thread_id=thread_id, user_id=user_id)
        except BaseException:
            # Never hand out a half-prepared machine, and never leave one running.
            self._close_quietly(sandbox, context="preparation failure")
            raise
        sandbox._on_terminal_failure = self._invalidate_sandbox
        logger.info("Created boxd sandbox %s (machine %s)", sandbox_id, machine.id)
        return sandbox

    def _delete_generation(self, client: Boxd, generation: str, sandbox_id: str) -> None:
        """Delete a machine whose create raised after the server made it.

        The generation label is unique to one create call, so a match can
        only be the machine that this call asked for.
        """
        try:
            found = client.machines.list(org=self._config["org"], labels={_LABEL_GENERATION: generation}, region=self._config["region"])
        except Exception:
            logger.warning("Could not look for a boxd machine left by a failed create", exc_info=True)
            return
        for machine in found:
            if (getattr(machine, "labels", None) or {}).get(_LABEL_GENERATION) != generation:
                continue
            sandbox = BoxdSandbox(sandbox_id, client, machine.id, region=self._config["region"])
            self._close_quietly(sandbox, context="failed create")

    def _bootstrap(self, sandbox: BoxdSandbox) -> None:
        skills_root = shlex.quote(self._config["skills_container_path"])
        dirs = " ".join(shlex.quote(f"{USER_DATA_ROOT}/{name}") for name in ("workspace", "uploads", "outputs"))
        script = f'set -e; sudo -n mkdir -p -- {dirs} {skills_root}; sudo -n chown "$(id -u):$(id -g)" -- {shlex.quote(USER_DATA_ROOT)} {dirs} {skills_root}; echo BOOTSTRAP_OK'
        result = sandbox.run_shell(script, timeout=_BOOTSTRAP_TIMEOUT)
        stdout = result.stdout if isinstance(result.stdout, str) else bytes(result.stdout).decode("utf-8", "replace")
        if result.exit_code != 0 or "BOOTSTRAP_OK" not in stdout:
            raise RuntimeError(f"boxd sandbox bootstrap failed with exit code {result.exit_code}")

    # ── Host to machine transfer ─────────────────────────────────────────

    def _add_tree(self, archive: tarfile.TarFile, source: Path, arcname: str, budget: _UploadBudget) -> bool:
        """Add regular files below ``source``; skip links and special files.

        Returns False when the budget stopped the walk early.
        """

        def scan_error(error: OSError) -> None:
            raise error

        for directory, dirnames, filenames in os.walk(source, followlinks=False, onerror=scan_error):
            parent = Path(directory)
            dirnames[:] = sorted(name for name in dirnames if not (parent / name).is_symlink())
            for name in sorted(filenames):
                path = parent / name
                st = path.lstat()
                if not stat.S_ISREG(st.st_mode):
                    continue
                if not budget.admit(st.st_size):
                    return False
                rel = path.relative_to(source).as_posix()
                info = tarfile.TarInfo(f"{arcname}/{rel}")
                info.size = st.st_size
                info.mode = st.st_mode & 0o755
                info.mtime = int(st.st_mtime)
                with path.open("rb") as fh:
                    archive.addfile(info, fh)
        return True

    def _upload_trees(self, sandbox: BoxdSandbox, sources: list[tuple[Path, str]], *, dest_root: str, replace: tuple[str, ...] = ()) -> bool:
        """Upload host directories into ``dest_root`` as one tar archive.

        ``sources`` pairs a host directory with its sub-path below
        ``dest_root``. ``replace`` lists sub-paths removed before extraction.
        Returns False when the upload stopped at its size limit.
        """
        budget = _UploadBudget(self._MAX_UPLOAD_FILES, self._MAX_UPLOAD_BYTES)
        complete = True
        with tempfile.TemporaryFile() as spool:
            with tarfile.open(fileobj=spool, mode="w:gz") as archive:
                for source, arcname in sources:
                    for part in (source, *source.parents):
                        if part.is_symlink():
                            raise ValueError(f"Refusing symlinked upload root for {arcname}")
                    if not source.is_dir():
                        continue
                    if not self._add_tree(archive, source, arcname, budget):
                        complete = False
                        break
            if budget.files == 0 and not replace:
                return complete
            remote_tar = f"/tmp/deerflow-upload-{uuid.uuid4().hex}.tar.gz"

            def chunks() -> Iterator[bytes]:
                spool.seek(0)
                while chunk := spool.read(self._UPLOAD_CHUNK_BYTES):
                    yield chunk

            sandbox._call(lambda: sandbox._client.machines.fs.write(sandbox.machine_id, remote_tar, chunks(), region=sandbox._region))
        root = shlex.quote(dest_root)
        removals = " ".join(shlex.quote(f"{dest_root}/{name}") for name in replace)
        script = (
            f"set -e; trap 'rm -f {shlex.quote(remote_tar)}' EXIT; "
            f"if [ -L {root} ]; then echo 'refusing symlinked destination' >&2; exit 2; fi; "
            + (f"rm -rf -- {removals}; " if removals else "")
            + f"mkdir -p -- {root}; tar -xzf {shlex.quote(remote_tar)} -C {root} --no-same-owner; echo UPLOAD_OK"
        )
        result = sandbox.run_shell(script, timeout=_UPLOAD_EXTRACT_TIMEOUT)
        stdout = result.stdout if isinstance(result.stdout, str) else bytes(result.stdout).decode("utf-8", "replace")
        if result.exit_code != 0 or "UPLOAD_OK" not in stdout:
            raise RuntimeError(f"boxd upload into {dest_root} failed with exit code {result.exit_code}")
        return complete

    def _restore_thread_files(self, sandbox: BoxdSandbox, *, thread_id: str, user_id: str) -> None:
        """Give a fresh machine the thread's Gateway-side files.

        Uploads go first, then the workspace, then outputs (which the Gateway
        already serves). Files past the size limit are skipped with a warning,
        so a large thread still gets a sandbox. A transfer failure raises: the
        caller discards the machine instead of handing out a half-restored one.
        """
        from deerflow.config.paths import get_paths

        paths = get_paths()
        sources = [
            (paths.sandbox_uploads_dir(thread_id, user_id=user_id), "uploads"),
            (paths.sandbox_work_dir(thread_id, user_id=user_id), "workspace"),
            (paths.sandbox_outputs_dir(thread_id, user_id=user_id), "outputs"),
        ]
        if not self._upload_trees(sandbox, sources, dest_root=USER_DATA_ROOT):
            logger.warning(
                "Thread files for boxd sandbox %s exceed %d files or %d bytes; the rest were not copied into the new machine",
                sandbox.id,
                self._MAX_UPLOAD_FILES,
                self._MAX_UPLOAD_BYTES,
            )

    def _upload_shared_skills(self, sandbox: BoxdSandbox, *, thread_id: str, user_id: str) -> None:
        """Best effort: upload the user's shared skills projection.

        A thread with an Agent skill policy view gets its projection from the
        sandbox middleware through :meth:`sync_agent_skills`, so it never sees
        the shared view first.
        """
        from deerflow.config.paths import get_paths
        from deerflow.skills.projection import ensure_skill_projections
        from deerflow.skills.storage import get_or_new_user_skill_storage

        try:
            if get_paths().thread_skills_view_dir(thread_id, user_id=user_id).exists():
                return
            storage = get_or_new_user_skill_storage(user_id, app_config=get_app_config())
            projection = ensure_skill_projections(storage)
            self._upload_skills(sandbox, projection)
        except Exception as exc:
            logger.warning("Could not upload the skills projection for boxd sandbox %s: %s", sandbox.id, exc)

    def _upload_skills(self, sandbox: BoxdSandbox, projection: SkillProjectionPaths) -> None:
        sources = [(Path(getattr(projection, category)), category) for category in SKILL_CATEGORIES]
        if not self._upload_trees(sandbox, sources, dest_root=self._config["skills_container_path"], replace=SKILL_CATEGORIES):
            raise RuntimeError("Skills projection exceeds the boxd upload limit")

    def sync_agent_skills(
        self,
        sandbox_id: str,
        *,
        thread_id: str,
        user_id: str,
        projection: SkillProjectionPaths,
    ) -> None:
        """Replace the machine's skill categories with this thread's projection.

        Holds the same scope serializer as acquire and release, so no other
        lifecycle step sees a half-written skills tree.
        """
        with self._acquire_serializer.hold(self._scope_from_sandbox_id(sandbox_id)):
            with self._lock:
                sandbox = self._sandboxes.get(sandbox_id)
            if sandbox is None:
                raise RuntimeError(f"boxd sandbox {sandbox_id} is not available for skill synchronization")
            self._upload_skills(sandbox, projection)

    # ── Reuse ────────────────────────────────────────────────────────────

    def _reclaim_warm_pool(self, scope_id: str) -> str | None:
        with self._lock:
            warm_entry = self._warm_pool.get(scope_id)
        if warm_entry is None:
            return None
        sandbox = warm_entry[0]
        if not sandbox.ping():
            with self._lock:
                removed = self._warm_pool.pop(scope_id, None)
            if removed is not None:
                self._destroy_warm_entry(scope_id, removed[0], reason="health_check_failed")
            return None
        with self._lock:
            removed = self._warm_pool.pop(scope_id, None)
            if removed is None:
                return None
            admitted = self._accepting
            if admitted:
                self._sandboxes[sandbox.id] = sandbox
                self._claims[sandbox.id] = 1
        if not admitted:
            self._close_quietly(removed[0], context="reclaimed after provider retirement")
            raise RuntimeError("boxd provider retired or shut down during acquire")
        logger.info("Reclaimed warm boxd sandbox %s", sandbox.id)
        return sandbox.id

    def get(self, sandbox_id: str) -> Sandbox | None:
        with self._lock:
            return self._sandboxes.get(sandbox_id)

    # ── Release and output mirroring ─────────────────────────────────────

    def release(self, sandbox_id: str) -> None:
        """Mirror outputs to the Gateway, then park the machine in the warm pool.

        Holds the acquire serializer, so the next turn cannot reuse the
        machine while its outputs are still being copied, and keeps the active
        entry during the transfer so the reaper cannot delete it.
        """
        with self._lock:
            if sandbox_id not in self._sandboxes:
                return
        try:
            with self._acquire_serializer.hold(self._scope_from_sandbox_id(sandbox_id)):
                self._release_scope_locked(sandbox_id)
        except AcquireSerializerClosed:
            # reset/shutdown closed the serializer after the check above.
            with self._lock:
                untracked = sandbox_id not in self._sandboxes
            if not untracked:
                raise

    def _release_scope_locked(self, sandbox_id: str) -> None:
        with self._lock:
            sandbox = self._sandboxes.get(sandbox_id)
            if sandbox is None:
                return
            # Overlapping turns can hold several claims on one machine. Only the
            # LAST release parks it: mirroring outputs and re-entering the warm
            # pool while another claimant is mid-turn hands its files to a
            # stranger (#8382).
            remaining = self._claims.get(sandbox_id, 1) - 1
            if remaining > 0:
                self._claims[sandbox_id] = remaining
                return
            scope = next((key for key, value in self._thread_sandboxes.items() if value == sandbox_id), None)
        if scope is not None and scope[0]:
            try:
                self._sync_outputs_to_host(sandbox, user_id=scope[0], thread_id=scope[1])
            except Exception:
                logger.warning("Failed to synchronize boxd outputs for %s", sandbox_id, exc_info=True)
        with self._lock:
            # A terminal failure or shutdown may have untracked the sandbox
            # during the transfer. Never resurrect it in the warm pool.
            if self._sandboxes.get(sandbox_id) is not sandbox:
                return
            self._sandboxes.pop(sandbox_id)
            self._claims.pop(sandbox_id, None)
            for key in [key for key, value in self._thread_sandboxes.items() if value == sandbox_id]:
                self._thread_sandboxes.pop(key, None)
            close_now = self._shutdown_called
            if close_now:
                self._pending_closes[id(sandbox)] = sandbox
            else:
                self._warm_pool[self._scope_from_sandbox_id(sandbox_id)] = (sandbox, time.monotonic())
        if close_now:
            self._close_quietly(sandbox, context="released during shutdown")
        else:
            logger.info("Released boxd sandbox %s to the warm pool", sandbox_id)

    @staticmethod
    def _output_parts(remote_path: str) -> tuple[str, ...]:
        prefix = f"{OUTPUTS_ROOT}/"
        if not remote_path.startswith(prefix) or "\\" in remote_path:
            raise ValueError("Output path is outside the outputs directory")
        parts = remote_path[len(prefix) :].split("/")
        if any(part in {"", ".", ".."} or ":" in part or part.partition(".")[0].rstrip(" ").upper() in _WINDOWS_RESERVED_NAMES or part.endswith((" ", ".")) for part in parts):
            raise ValueError("Unsafe output path")
        return tuple(parts)

    @staticmethod
    def _output_name_key(name: str) -> str:
        return unicodedata.normalize("NFC", name.casefold())

    @classmethod
    def _ambiguous_output_paths(cls, remote_paths: list[str | None]) -> set[str]:
        # Names that differ only by case or Unicode normalization collide on
        # some hosts. A directory alias rejects all of its children.
        components: dict[tuple[int, str], tuple[str, int]] = {}
        ambiguous: set[int] = set()
        path_nodes: dict[str, list[int]] = {}
        for remote_path in remote_paths:
            if remote_path is None:
                continue
            try:
                parts = cls._output_parts(remote_path)
            except ValueError:
                continue
            parent = 0
            nodes = path_nodes.setdefault(remote_path, [])
            for part in parts:
                key = (parent, cls._output_name_key(part))
                spelling, node = components.setdefault(key, (part, len(components) + 1))
                if spelling != part:
                    ambiguous.add(node)
                nodes.append(node)
                parent = node
        return {path for path, nodes in path_nodes.items() if ambiguous.intersection(nodes)}

    @classmethod
    def _output_destination(cls, root: Path, remote_path: str) -> Path:
        parts = cls._output_parts(remote_path)
        target = root.joinpath(*PurePosixPath(*parts).parts)
        # Reject links in existing parents, including the owner/thread bucket.
        for component in reversed((target, *target.parents)):
            if component.is_symlink() or component.is_junction():
                raise ValueError("Symlinked output destination")
        parent = root
        for part in parts:
            if parent.is_dir():
                key = cls._output_name_key(part)
                with os.scandir(parent) as entries:
                    if any(entry.name != part and cls._output_name_key(entry.name) == key for entry in entries):
                        raise ValueError("Output destination aliases an existing path")
            parent = parent / part
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not stat.S_ISREG(target.stat().st_mode):
            raise ValueError("Output destination is not a regular file")
        return target

    def _list_remote_outputs(self, sandbox: BoxdSandbox, *, deadline: float) -> list[str | None] | None:
        """NUL-framed listing of output files; None when it is over the limit."""
        root = shlex.quote(OUTPUTS_ROOT)
        script = f"set -o pipefail; [ -d {root} ] && [ ! -L {root} ] || exit 0; find {root} -type f -print0 2>/dev/null | head -c {self._MAX_SYNC_LISTING_BYTES + 1}"
        result = sandbox.run_shell(script, timeout=self._SYNC_DEADLINE_SECONDS, binary=True, deadline=deadline)
        raw = result.stdout if isinstance(result.stdout, bytes) else str(result.stdout).encode("utf-8")
        if len(raw) > self._MAX_SYNC_LISTING_BYTES:
            logger.warning("boxd output listing exceeded %d bytes; skipping synchronization", self._MAX_SYNC_LISTING_BYTES)
            return None
        if result.exit_code != 0:
            # find hit an unreadable directory: keep the complete records.
            logger.warning("boxd output listing had traversal errors; synchronizing complete records")
        if raw and not raw.endswith(b"\0"):
            raw = raw[: raw.rfind(b"\0") + 1]
        paths: list[str | None] = []
        for record in filter(None, raw.split(b"\0")):
            try:
                paths.append(record.decode("utf-8"))
            except UnicodeDecodeError:
                logger.warning("Skipping non-UTF-8 boxd output %r", record)
                paths.append(None)
        return paths

    def _sync_outputs_to_host(self, sandbox: BoxdSandbox, *, thread_id: str, user_id: str) -> None:
        """Best-effort bounded mirror of the outputs directory to the Gateway."""
        from deerflow.config.paths import get_paths

        root = get_paths().sandbox_outputs_dir(thread_id, user_id=user_id)
        deadline = time.monotonic() + self._SYNC_DEADLINE_SECONDS
        remote_paths = self._list_remote_outputs(sandbox, deadline=deadline)
        if not remote_paths:
            return
        # Include records beyond the transfer cap: publishing the first of two
        # aliases would otherwise expose its bytes through both artifact URLs.
        ambiguous_paths = self._ambiguous_output_paths(remote_paths)
        total = 0
        for index, remote_path in enumerate(remote_paths):
            if index >= self._MAX_SYNC_FILES or total >= self._MAX_SYNC_TOTAL_BYTES or time.monotonic() >= deadline:
                logger.warning("boxd output synchronization stopped at its file, byte or time limit")
                break
            if remote_path is None:
                continue
            if remote_path in ambiguous_paths:
                logger.warning("Skipping ambiguous boxd output %r", remote_path)
                continue
            staged: Path | None = None
            try:
                target = self._output_destination(root, remote_path)
                data = sandbox.download_file(remote_path, max_bytes=min(DEFAULT_DOWNLOAD_LIMIT, self._MAX_SYNC_TOTAL_BYTES - total), deadline=deadline)
                total += len(data)
                with tempfile.NamedTemporaryFile(prefix=".boxd-sync-", dir=target.parent, delete=False) as output:
                    staged = Path(output.name)
                    output.write(data)
                # Check confinement again after the network call, keeping any
                # previous complete version on error.
                self._output_destination(root, remote_path)
                staged.replace(target)
            except (OSError, ValueError):
                logger.warning("Could not synchronize boxd output %r", remote_path, exc_info=True)
            finally:
                if staged is not None:
                    staged.unlink(missing_ok=True)

    # ── Teardown ─────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Park tracked sandboxes in this instance's warm pool.

        ``reset_sandbox_provider()`` drops the singleton and calls this so a
        config change applies on the next construction. The machines stay
        visible to this instance's idle reaper and atexit shutdown.
        """
        with self._lock:
            self._accepting = False
            now = time.monotonic()
            for sandbox_id, sandbox in self._sandboxes.items():
                self._warm_pool.setdefault(self._scope_from_sandbox_id(sandbox_id), (sandbox, now))
            self._sandboxes.clear()
            self._claims.clear()
            self._thread_sandboxes.clear()
            self._acquire_serializer.close()

    def _shutdown_at_exit(self) -> None:
        try:
            self.shutdown()
        except _ShutdownIncompleteError as e:
            logger.warning("%s", e)

    def shutdown(self) -> None:
        # Shutdown retries cleanup but never reopens admission. An SDK call in
        # flight cannot be cancelled: its worker keeps ownership and deletes a
        # late machine itself. Report unfinished work instead of hiding it.
        with self._shutdown_lock:
            with self._lock:
                if self._shutdown_complete:
                    return
                self._shutdown_called = True
                self._accepting = False
            self._acquire_serializer.close()
            reaper_stopped = True
            try:
                self._stop_idle_checker()
            except RuntimeError:
                # The reaper may be inside a slow delete. Delete everything
                # else now; _closing keeps the two from deleting one machine twice.
                reaper_stopped = False
            with self._lock:
                active = list(self._sandboxes.values())
                warm = [sandbox for sandbox, _ in self._warm_pool.values()]
                self._sandboxes.clear()
                self._claims.clear()
                self._warm_pool.clear()
                self._thread_sandboxes.clear()
                previous_pending = list(self._pending_closes.values())
            for sandbox in {id(box): box for box in active + warm + previous_pending}.values():
                self._close_quietly(sandbox, context="shutdown")
            with self._lock:
                if self._acquires or self._pending_closes or not reaper_stopped:
                    raise _ShutdownIncompleteError(f"boxd shutdown incomplete: {self._acquires} acquires and {len(self._pending_closes)} deletions pending, reaper stopped: {reaper_stopped}; retry shutdown")
                self._shutdown_complete = True


__all__ = ["BoxdSandboxProvider"]
