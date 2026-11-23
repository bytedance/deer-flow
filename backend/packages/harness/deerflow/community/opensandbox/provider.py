"""OpenSandbox-backed community ``SandboxProvider`` for DeerFlow."""

from __future__ import annotations

import atexit
import base64
import ipaddress
import logging
import math
import os
import posixpath
import shlex
import stat
import tempfile
import threading
import time
import unicodedata
import uuid
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from datetime import timedelta
from functools import partial
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from deerflow.config import get_app_config
from deerflow.sandbox.acquire_serialization import AcquireSerializer, AcquireSerializerClosed
from deerflow.sandbox.identity import derive_sandbox_scope_token
from deerflow.sandbox.sandbox import Sandbox, _validate_extra_env
from deerflow.sandbox.sandbox_provider import SandboxProvider
from deerflow.skills.projection import SkillProjectionPaths, _projection_lock
from deerflow.skills.types import SkillCategory

from ..warm_pool_lifecycle import WarmPoolLifecycleMixin
from .sandbox import _MAX_DOWNLOAD_SIZE, OpenSandboxSandbox, execution_stdout, format_execution

if TYPE_CHECKING:
    from opensandbox.config.connection_sync import ConnectionConfigSync
    from opensandbox.models.execd import RunCommandOpts
    from opensandbox.sync import SandboxSync

logger = logging.getLogger(__name__)

DEFAULT_IMAGE = "python:3.11"
DEFAULT_READY_TIMEOUT = 30.0
DEFAULT_REQUEST_TIMEOUT = 30.0
DEFAULT_SANDBOX_TIMEOUT = 4 * 60 * 60
DEFAULT_COMMAND_TIMEOUT = 10 * 60
_BOOTSTRAP_TIMEOUT = 30.0
_BOOTSTRAP_COMMAND = "mkdir -p /mnt/user-data/workspace /mnt/user-data/uploads /mnt/user-data/outputs"
_WINDOWS_RESERVED_NAMES = frozenset({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {f"{prefix}{digit}" for prefix in ("COM", "LPT") for digit in "123456789¹²³"})
_SKILL_CATEGORIES = (SkillCategory.PUBLIC, SkillCategory.CUSTOM, SkillCategory.LEGACY, SkillCategory.INTEGRATION)
_PROTECTED_SKILLS_ROOTS = tuple(PurePosixPath(path) for path in ("/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/libx32", "/proc", "/run", "/sbin", "/sys", "/usr", "/var", "/mnt/user-data", "/mnt/acp-workspace"))


class _SkillUploadError(RuntimeError):
    """The upload failed before the published skill view was changed."""


def _skills_root(path: str) -> PurePosixPath:
    root = PurePosixPath(path)
    if (
        len(root.parts) < 2
        or not root.is_absolute()
        or path.startswith("//")
        or root.as_posix() != path
        or ".." in root.parts
        or "\\" in path
        or "\0" in path
        or path in {"/home", "/root"}
        or any(root.is_relative_to(protected) or protected.is_relative_to(root) for protected in _PROTECTED_SKILLS_ROOTS)
    ):
        raise ValueError("skills.container_path must be a dedicated absolute OpenSandbox skills directory")
    return root


def _portable_skill_name(name: str) -> bool:
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return not ("\\" in name or ":" in name or name.endswith((" ", ".")) or name.partition(".")[0].rstrip(" ").upper() in _WINDOWS_RESERVED_NAMES)


def _skill_link_target(path: Path, package: Path) -> Path | None:
    raw_target = Path(os.readlink(path))
    if raw_target.is_absolute() or any(part != ".." and not _portable_skill_name(part) for part in raw_target.parts):
        return None
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not resolved.is_relative_to(package) or not all(_portable_skill_name(part) for part in resolved.relative_to(package).parts):
        return None
    return resolved


def _uses_insecure_remote_http(domain: Any, protocol: str) -> bool:
    if not domain:
        return False
    value = str(domain)
    try:
        parsed = urlsplit(value if "://" in value else f"{protocol}://{value}")
    except ValueError:
        return False
    if parsed.scheme.lower() != "http" or not parsed.hostname:
        return False
    if parsed.hostname.lower() == "localhost":
        return False
    try:
        return not ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        return True


def _import_sdk() -> tuple[type[SandboxSync], type[ConnectionConfigSync], type[RunCommandOpts]]:
    """Import the optional OpenSandbox sync SDK only when this provider is used."""
    try:
        from opensandbox.config.connection_sync import ConnectionConfigSync
        from opensandbox.models.execd import RunCommandOpts
        from opensandbox.sync import SandboxSync
    except ImportError as exc:  # pragma: no cover - depends on optional install state
        raise ImportError("OpenSandboxProvider requires the optional 'opensandbox' dependency. Install it with: pip install 'deerflow-harness[opensandbox]' or pip install 'opensandbox>=1.1.0,<2.0.0'.") from exc
    return SandboxSync, ConnectionConfigSync, RunCommandOpts


class OpenSandboxProvider(WarmPoolLifecycleMixin[OpenSandboxSandbox], SandboxProvider):
    """Create one OpenSandbox environment per effective user/thread scope."""

    uses_thread_data_mounts = False
    needs_upload_permission_adjustment = True
    supports_agent_skill_isolation = True
    _idle_checker_thread_name = "opensandbox-idle-reaper"
    _MAX_SYNC_FILES = 2000
    _MAX_SYNC_TOTAL_BYTES = 512 * 1024 * 1024
    _MAX_SYNC_LISTING_BYTES = 512 * 1024
    _SYNC_DEADLINE_SECONDS = 120.0
    _MAX_SKILL_FILES = 2000
    _MAX_SKILL_FILE_BYTES = 100 * 1024 * 1024
    _MAX_SKILL_TOTAL_BYTES = 512 * 1024 * 1024

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sandboxes: dict[str, OpenSandboxSandbox] = {}
        self._thread_sandboxes: dict[tuple[str, str], str] = {}
        self._warm_pool: dict[str, tuple[OpenSandboxSandbox, float]] = {}
        self._acquire_serializer: AcquireSerializer[str] = AcquireSerializer(thread_name_prefix="opensandbox-acquire-wait")
        self._idle_checker_stop = threading.Event()
        self._idle_checker_thread: threading.Thread | None = None
        self._shutdown_called = False
        self._sdk: tuple[type[SandboxSync], type[ConnectionConfigSync], type[RunCommandOpts]] | None = None
        self._config = self._load_config()
        atexit.register(self.shutdown)
        self._start_idle_checker()

    @staticmethod
    def _positive_float(name: str, value: Any, default: float) -> float:
        try:
            resolved = float(default if value is None else value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"sandbox.{name} must be positive") from exc
        if not math.isfinite(resolved) or resolved <= 0:
            raise ValueError(f"sandbox.{name} must be positive")
        return resolved

    def _load_config(self) -> dict[str, Any]:
        app_config = get_app_config()
        sandbox_config = app_config.sandbox

        def option(name: str) -> Any:
            return getattr(sandbox_config, name, None)

        def bool_option(name: str) -> bool:
            value = option(name)
            if value is None:
                return False
            if not isinstance(value, bool):
                raise ValueError(f"sandbox.{name} must be true or false")
            return value

        def resource_quantity(value: Any) -> str | None:
            if isinstance(value, str):
                return value.strip() or None
            if isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
                return str(value)
            return None

        def resource_option(name: str) -> dict[str, str] | None:
            value = option(name)
            if value is None:
                return None
            invalid = ValueError(f"sandbox.{name} must map resource names to positive quantities, e.g. {{cpu: '2', memory: 4Gi}}")
            if not isinstance(value, Mapping):
                raise invalid
            resources: dict[str, str] = {}
            for key, raw in value.items():
                quantity = resource_quantity(raw)
                if not isinstance(key, str) or not key.strip() or quantity is None:
                    raise invalid
                resources[key.strip()] = quantity
            return resources or None

        api_key = option("api_key")
        domain = option("domain")
        protocol = option("protocol") or "http"
        effective_domain = domain or os.environ.get("OPEN_SANDBOX_DOMAIN")
        if not (api_key or os.environ.get("OPEN_SANDBOX_API_KEY")) and not effective_domain:
            logger.warning("OpenSandboxProvider: no api_key or domain configured (set sandbox.api_key/sandbox.domain in config.yaml or OPEN_SANDBOX_API_KEY/OPEN_SANDBOX_DOMAIN). The SDK will default to unauthenticated localhost:8080.")
        if _uses_insecure_remote_http(effective_domain, protocol):
            logger.warning("OpenSandboxProvider: remote OpenSandbox domain uses HTTP; use HTTPS to protect credentials and sandbox traffic.")
        # $VARS in config.yaml are already resolved by AppConfig.resolve_env_variables;
        # resolving again would rewrite a secret that itself starts with $.
        environment = dict(option("environment") or {})
        _validate_extra_env(environment)
        replicas = option("replicas")
        idle_timeout = option("idle_timeout")
        raw_sandbox_timeout = option("sandbox_timeout")
        try:
            sandbox_timeout = float(DEFAULT_SANDBOX_TIMEOUT if raw_sandbox_timeout is None else raw_sandbox_timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("sandbox.sandbox_timeout must be non-negative") from exc
        if not math.isfinite(sandbox_timeout) or sandbox_timeout < 0:
            raise ValueError("sandbox.sandbox_timeout must be non-negative")
        return {
            "api_key": api_key,
            "domain": domain,
            "protocol": protocol,
            "request_timeout": self._positive_float("request_timeout", option("request_timeout"), DEFAULT_REQUEST_TIMEOUT),
            "use_server_proxy": bool_option("use_server_proxy"),
            "secure_access": bool_option("secure_access"),
            "image": option("image") or DEFAULT_IMAGE,
            "ready_timeout": self._positive_float("ready_timeout", option("ready_timeout"), DEFAULT_READY_TIMEOUT),
            "sandbox_timeout": None if sandbox_timeout == 0 else sandbox_timeout,
            "command_timeout": self._positive_float("bash_command_timeout", option("bash_command_timeout"), DEFAULT_COMMAND_TIMEOUT),
            "environment": environment,
            "replicas": replicas if replicas is not None else self.DEFAULT_REPLICAS,
            "idle_timeout": idle_timeout if idle_timeout is not None else self.DEFAULT_IDLE_TIMEOUT,
            "resource": resource_option("resource"),
            "resource_requests": resource_option("resource_requests"),
            "skills_root": _skills_root(app_config.skills.container_path),
        }

    def _get_sdk(self) -> tuple[type[SandboxSync], type[ConnectionConfigSync], type[RunCommandOpts]]:
        with self._lock:
            sdk = self._sdk
        if sdk is not None:
            return sdk
        imported = _import_sdk()
        with self._lock:
            if self._sdk is None:
                self._sdk = imported
                return imported
            return self._sdk

    def _new_connection_config(self, connection_config_cls: type[ConnectionConfigSync]) -> ConnectionConfigSync:
        # SandboxSync.create() derives an SDK-owned transport on a config copy,
        # and destroy() closes that transport. A fresh base config per remote
        # ensures no live sandbox can inherit another sandbox's transport.
        return connection_config_cls(
            api_key=self._config["api_key"],
            domain=self._config["domain"],
            protocol=self._config["protocol"],
            request_timeout=timedelta(seconds=self._config["request_timeout"]),
            use_server_proxy=self._config["use_server_proxy"],
        )

    @staticmethod
    def _sandbox_id(thread_id: str, user_id: str) -> str:
        return derive_sandbox_scope_token(user_id=user_id, thread_id=thread_id)

    @staticmethod
    def _thread_key(thread_id: str, user_id: str | None) -> tuple[str, str]:
        return (user_id or "", thread_id)

    def _start_idle_checker(self) -> None:
        if self._config["idle_timeout"] <= 0:
            return
        super()._start_idle_checker()

    def _active_count_locked(self) -> int:
        return len(self._sandboxes)

    def _destroy_warm_entry(self, sandbox_id: str, entry: OpenSandboxSandbox, *, reason: str) -> None:
        self._destroy_quietly(entry, context=f"warm pool, reason={reason}")

    @staticmethod
    def _destroy_quietly(sandbox: OpenSandboxSandbox, *, context: str) -> None:
        try:
            sandbox.destroy()
        except Exception as exc:
            logger.warning("Error destroying OpenSandbox %s (%s): %s", sandbox.id, context, exc)

    def _invalidate_sandbox(self, sandbox: OpenSandboxSandbox, reason: str) -> None:
        sandbox_id = sandbox.id
        with self._lock:
            active = self._sandboxes.get(sandbox_id)
            warm_entry = self._warm_pool.get(sandbox_id)
            if active is sandbox:
                self._sandboxes.pop(sandbox_id)
            elif warm_entry is not None and warm_entry[0] is sandbox:
                self._warm_pool.pop(sandbox_id)
            else:
                return
            for key in [key for key, value in self._thread_sandboxes.items() if value == sandbox_id]:
                self._thread_sandboxes.pop(key, None)
        logger.warning("Invalidating OpenSandbox %s after terminal failure: %s", sandbox_id, reason)
        self._destroy_quietly(sandbox, context="terminal failure")

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        with self._lock:
            if self._shutdown_called:
                raise RuntimeError("OpenSandboxProvider has been shut down")
        if thread_id is None:
            sandbox_id = str(uuid.uuid4())[:8]
            sandbox = self._create_sandbox(sandbox_id, thread_id=None, user_id=user_id)
            try:
                self._prepare_new_skill_view(sandbox, thread_id=None, user_id=user_id)
            except BaseException:
                self._destroy_quietly(sandbox, context="skill projection setup failed")
                raise
            with self._lock:
                if self._shutdown_called:
                    destroy_after_unlock = True
                else:
                    self._sandboxes[sandbox_id] = sandbox
                    destroy_after_unlock = False
            if destroy_after_unlock:
                self._destroy_quietly(sandbox, context="created during shutdown")
                raise RuntimeError("OpenSandboxProvider shut down during acquire")
            return sandbox_id

        key = self._thread_key(thread_id, user_id)
        sandbox_id = self._sandbox_id(thread_id, user_id or "")
        with self._acquire_serializer.hold(sandbox_id):
            return self._acquire_scope_locked(key, sandbox_id, thread_id=thread_id, user_id=user_id)

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        """Acquire without blocking the event loop.

        The entire synchronous acquire (serializer wait + body) runs on the
        serializer's dedicated executor — never the default executor. A
        cancelled awaiter abandons the worker thread, which runs to
        completion and releases the hold itself, so a retry serializes
        behind it instead of overlapping the abandoned body.
        """
        acquire = partial(self.acquire, thread_id, user_id=user_id)
        return await self._acquire_serializer.run_on_executor(acquire)

    def _acquire_scope_locked(self, key: tuple[str, str], sandbox_id: str, *, thread_id: str, user_id: str | None) -> str:
        with self._lock:
            existing = self._thread_sandboxes.get(key)
            active = self._sandboxes.get(existing) if existing is not None else None
        if existing is not None and active is not None:
            try:
                active.renew()
                return existing
            except Exception:
                # A terminal renewal failure invokes _invalidate_sandbox,
                # which removes and closes this exact client. Rebuild in the
                # same acquire; transient errors leave the registry intact
                # and must remain visible to the caller.
                with self._lock:
                    invalidated = self._sandboxes.get(existing) is not active and existing not in self._warm_pool
                    shutting_down = self._shutdown_called
                if not invalidated or not active.is_closed or shutting_down:
                    raise
                logger.info("Rebuilding terminal OpenSandbox %s during acquire", existing)
        sandbox = self._reclaim_warm_pool(sandbox_id)
        reclaimed = sandbox is not None
        if sandbox is None:
            sandbox = self._create_sandbox(sandbox_id, thread_id=thread_id, user_id=user_id)
        try:
            self._prepare_new_skill_view(sandbox, thread_id=thread_id, user_id=user_id)
        except BaseException as exc:
            if reclaimed and isinstance(exc, _SkillUploadError):
                self._park_failed_skill_upload(sandbox, was_active=False)
            else:
                self._destroy_quietly(sandbox, context="skill projection setup failed")
            raise
        with self._lock:
            if self._shutdown_called:
                destroy_after_unlock = True
            else:
                self._sandboxes[sandbox_id] = sandbox
                self._thread_sandboxes[key] = sandbox_id
                destroy_after_unlock = False
        if destroy_after_unlock:
            self._destroy_quietly(sandbox, context="created during shutdown")
            raise RuntimeError("OpenSandboxProvider shut down during acquire")
        return sandbox_id

    def _create_sandbox(self, sandbox_id: str, *, thread_id: str | None, user_id: str | None) -> OpenSandboxSandbox:
        replicas, total = self._replica_count()
        if total >= replicas:
            evicted = self._evict_oldest_warm()
            self._log_replicas_soft_cap(replicas, sandbox_id, evicted)

        sandbox_cls, connection_config_cls, run_command_opts_cls = self._get_sdk()
        connection_config = self._new_connection_config(connection_config_cls)
        metadata = {"deer_flow_provider": "opensandbox"}
        if thread_id is not None:
            metadata["deer_flow_thread"] = thread_id
        if user_id is not None:
            metadata["deer_flow_user"] = user_id
        remote = sandbox_cls.create(
            self._config["image"],
            timeout=None if self._config["sandbox_timeout"] is None else timedelta(seconds=self._config["sandbox_timeout"]),
            ready_timeout=timedelta(seconds=self._config["ready_timeout"]),
            env=self._config["environment"] or None,
            metadata=metadata,
            resource=self._config["resource"],
            resource_requests=self._config["resource_requests"],
            connection_config=connection_config,
            secure_access=self._config["secure_access"],
        )
        try:
            bootstrap = remote.commands.run(
                _BOOTSTRAP_COMMAND,
                opts=run_command_opts_cls(
                    timeout=timedelta(seconds=_BOOTSTRAP_TIMEOUT),
                    envs=self._config["environment"] or None,
                ),
            )
            exit_code = getattr(bootstrap, "exit_code", None)
            if exit_code != 0:
                detail = format_execution(bootstrap).strip() or ("no exit code" if exit_code is None else f"exit code {exit_code}")
                raise RuntimeError(f"OpenSandbox bootstrap failed: {detail}")
        except Exception:
            try:
                remote.destroy()
            except Exception:
                logger.warning("Failed to destroy OpenSandbox %s after bootstrap failure", remote.id, exc_info=True)
            raise

        sandbox = OpenSandboxSandbox(
            sandbox_id,
            remote,
            run_command_opts_cls=run_command_opts_cls,
            default_env=self._config["environment"],
            sandbox_timeout=None if self._config["sandbox_timeout"] is None else timedelta(seconds=self._config["sandbox_timeout"]),
            default_command_timeout=self._config["command_timeout"],
            on_terminal_failure=lambda _sandbox_id, reason: self._invalidate_sandbox(sandbox, reason),
        )
        return sandbox

    def _reclaim_warm_pool(self, sandbox_id: str) -> OpenSandboxSandbox | None:
        with self._lock:
            warm_entry = self._warm_pool.get(sandbox_id)
        if warm_entry is None:
            return None
        sandbox = warm_entry[0]
        if not sandbox.ping():
            with self._lock:
                removed = self._warm_pool.pop(sandbox_id, None)
            if removed is not None:
                self._destroy_warm_entry(sandbox_id, removed[0], reason="health_check_failed")
            return None
        with self._lock:
            removed = self._warm_pool.pop(sandbox_id, None)
            if removed is None:
                return None
        logger.info("Reclaimed warm OpenSandbox %s (remote=%s)", sandbox_id, sandbox.remote_id)
        return removed[0]

    def get(self, sandbox_id: str) -> Sandbox | None:
        with self._lock:
            return self._sandboxes.get(sandbox_id)

    def _prepare_new_skill_view(self, sandbox: OpenSandboxSandbox, *, thread_id: str | None, user_id: str | None) -> None:
        if not user_id:
            return
        from deerflow.skills.projection import ensure_skill_projections, thread_skill_projection_exists
        from deerflow.skills.storage import get_or_new_user_skill_storage

        storage = get_or_new_user_skill_storage(user_id, app_config=get_app_config())
        # Eager middleware installs the scoped view. Until then do not expose
        # either the shared view or the previous agent's files on a warm remote.
        projection = None if thread_id is not None and thread_skill_projection_exists(storage, thread_id) else ensure_skill_projections(storage)
        self._replace_skill_projection(sandbox, projection)

    def _park_failed_skill_upload(self, sandbox: OpenSandboxSandbox, *, was_active: bool) -> None:
        sandbox_id = sandbox.id
        with self._lock:
            if was_active:
                if self._sandboxes.get(sandbox_id) is not sandbox:
                    return
                self._sandboxes.pop(sandbox_id)
                for key in [key for key, value in self._thread_sandboxes.items() if value == sandbox_id]:
                    self._thread_sandboxes.pop(key)
            if not self._shutdown_called:
                self._warm_pool[sandbox_id] = (sandbox, time.monotonic())
                return
        self._destroy_quietly(sandbox, context="skill upload failed during shutdown")

    def sync_agent_skills(self, sandbox_id: str, *, thread_id: str, user_id: str, projection: SkillProjectionPaths) -> None:
        from deerflow.skills.projection import get_thread_skill_projection_paths
        from deerflow.skills.storage import get_or_new_user_skill_storage

        with self._acquire_serializer.hold(sandbox_id):
            with self._lock:
                sandbox = self._sandboxes.get(sandbox_id)
                owner_matches = self._thread_sandboxes.get(self._thread_key(thread_id, user_id)) == sandbox_id
            if sandbox is None or not owner_matches:
                raise RuntimeError("OpenSandbox is not active for this skill projection scope")
            storage = get_or_new_user_skill_storage(user_id, app_config=get_app_config())
            if projection != get_thread_skill_projection_paths(storage, thread_id):
                raise RuntimeError("OpenSandbox skill projection does not belong to this scope")
            try:
                self._replace_skill_projection(sandbox, projection)
            except _SkillUploadError:
                self._park_failed_skill_upload(sandbox, was_active=True)
                raise
            except BaseException:
                self._invalidate_sandbox(sandbox, "skill projection setup failed")
                raise

    def _replace_skill_projection(self, sandbox: OpenSandboxSandbox, projection: SkillProjectionPaths | None) -> None:
        root = self._config["skills_root"]
        stage = root / ".deerflow-skills-stage"
        deadline = time.monotonic() + self._SYNC_DEADLINE_SECONDS
        ancestors = [*reversed(root.parents[:-1]), root]
        no_links = "; ".join(f"test ! -L {shlex.quote(str(path))}" for path in ancestors)
        destinations = " ".join(shlex.quote(str(root / category)) for category in _SKILL_CATEGORIES)
        staged = " ".join(shlex.quote(str(stage / category)) for category in _SKILL_CATEGORIES)
        qroot = shlex.quote(str(root))
        qstage = shlex.quote(str(stage))

        def run(script: str) -> None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("OpenSandbox skill projection deadline exceeded")
            result = sandbox._run(f"set -e; {script}", timeout=min(remaining, _BOOTSTRAP_TIMEOUT))
            if getattr(result, "exit_code", None) != 0:
                raise RuntimeError("OpenSandbox skill projection command failed")

        try:
            run(f"{no_links}; mkdir -p -- {qroot}; rm -rf -- {qstage}; mkdir -m 700 -- {qstage}; mkdir -- {staged}")
        except Exception as exc:
            raise RuntimeError("Failed to synchronize OpenSandbox skill projection") from exc
        if projection is not None:
            try:
                self._upload_skill_projection(sandbox, projection, stage=stage, run=run, deadline=deadline)
            except Exception as exc:
                raise _SkillUploadError("Failed to synchronize OpenSandbox skill projection") from exc
        try:
            run(f"{no_links}; test ! -L {qstage}; rm -rf -- {destinations}; mv -- {staged} {qroot}; rmdir -- {qstage}")
        except Exception as exc:
            raise RuntimeError("Failed to synchronize OpenSandbox skill projection") from exc

    def _upload_skill_projection(
        self,
        sandbox: OpenSandboxSandbox,
        projection: SkillProjectionPaths,
        *,
        stage: PurePosixPath,
        run: Callable[[str], None],
        deadline: float,
    ) -> None:
        sources = (projection.public, projection.custom, projection.legacy, projection.integrations)
        entries: list[tuple[PurePosixPath, int, bool]] = []
        links: list[tuple[PurePosixPath, PurePosixPath, bool]] = []
        total = 0

        def fail_scan(error: OSError) -> None:
            raise error

        def check_deadline() -> None:
            if time.monotonic() >= deadline:
                raise TimeoutError("OpenSandbox skill projection deadline exceeded")

        def portable(name: str) -> bool:
            if _portable_skill_name(name):
                return True
            logger.warning("Skipping non-portable OpenSandbox skill path component %r", name)
            return False

        # Capture under the publication locks, but do not hold the global
        # public projection lock across SDK calls for one user's sandbox.
        with tempfile.TemporaryFile() as payload:
            with ExitStack() as locks:
                for lock_root in dict.fromkeys(source.parent for source in sources):
                    locks.enter_context(_projection_lock(lock_root, timeout=5.0))
                for category, source in zip(_SKILL_CATEGORIES, sources, strict=True):
                    if source.is_symlink() or any(parent.is_symlink() for parent in source.parents):
                        raise ValueError("Symlink in OpenSandbox skill projection root")
                    packages: set[Path] = set()
                    category_root = stage / category
                    for directory, dirnames, filenames in os.walk(source, followlinks=False, onerror=fail_scan):
                        check_deadline()
                        parent = Path(directory)
                        package = next((root for root in (parent, *parent.parents) if root in packages), None)
                        if package is None and "SKILL.md" in filenames and stat.S_ISREG((parent / "SKILL.md").lstat().st_mode):
                            packages.add(parent)
                            package = parent
                        target_dir = category_root / parent.relative_to(source).as_posix()
                        dirnames[:] = [name for name in dirnames if portable(name)]
                        dir_links = {name for name in dirnames if (parent / name).is_symlink()}
                        dirnames[:] = [name for name in dirnames if name not in dir_links]
                        for name in (*dir_links, *(name for name in filenames if portable(name))):
                            check_deadline()
                            path = parent / name
                            info = path.lstat()
                            if stat.S_ISLNK(info.st_mode):
                                resolved = _skill_link_target(path, package) if package is not None else None
                                if resolved is None or not (resolved.is_dir() or resolved.is_file()):
                                    logger.warning("Skipping unsafe OpenSandbox skill link %r", path.relative_to(source).as_posix())
                                    continue
                                if len(entries) + len(links) >= self._MAX_SKILL_FILES:
                                    raise ValueError("OpenSandbox skill projection exceeds upload limits")
                                links.append((target_dir / name, category_root / resolved.relative_to(source).as_posix(), resolved.is_dir()))
                                continue
                            if not stat.S_ISREG(info.st_mode):
                                continue
                            if len(entries) + len(links) >= self._MAX_SKILL_FILES or info.st_size > min(self._MAX_SKILL_FILE_BYTES, self._MAX_SKILL_TOTAL_BYTES - total):
                                raise ValueError("OpenSandbox skill projection exceeds upload limits")
                            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
                            with os.fdopen(os.open(path, flags), "rb") as file:
                                opened = os.fstat(file.fileno())
                                if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(info, opened):
                                    raise ValueError("OpenSandbox skill projection changed during upload")
                                data = file.read(info.st_size + 1)
                            if len(data) != info.st_size:
                                raise ValueError("OpenSandbox skill projection changed during upload")
                            payload.write(data)
                            entries.append((target_dir / name, len(data), bool(info.st_mode & stat.S_IXUSR)))
                            total += len(data)
            payload.seek(0)
            created = {stage / category for category in _SKILL_CATEGORIES}

            def ensure_dir(path: PurePosixPath) -> None:
                if path not in created:
                    run(f"mkdir -p -- {shlex.quote(str(path))}")
                    created.add(path)

            for target, size, executable in entries:
                ensure_dir(target.parent)
                check_deadline()
                sandbox._upload_skill_file(str(target), payload.read(size), executable=executable)
            files = {target for target, _, _ in entries}
            for link, target, is_dir in links:
                if is_dir:
                    ensure_dir(target)
                elif target not in files:
                    continue
                ensure_dir(link.parent)
                relative = posixpath.relpath(target, start=link.parent)
                run(f"ln -sT -- {shlex.quote(relative)} {shlex.quote(str(link))}")

    def release(self, sandbox_id: str) -> None:
        # Same scope lock as acquire: no next turn may reuse a client while its
        # previous outputs are still being mirrored. Keep it active until sync
        # finishes so the warm-pool reaper cannot destroy it during transfer.
        with self._lock:
            if sandbox_id not in self._sandboxes:
                return
        try:
            with self._acquire_serializer.hold(sandbox_id):
                self._release_scope_locked(sandbox_id)
        except AcquireSerializerClosed:
            # reset/shutdown can close the serializer between the existence
            # check and checkout. Preserve release's no-op after termination.
            with self._lock:
                untracked = sandbox_id not in self._sandboxes
            if not untracked:
                raise

    def _release_scope_locked(self, sandbox_id: str) -> None:
        with self._lock:
            sandbox = self._sandboxes.get(sandbox_id)
            scope = next((key for key, value in self._thread_sandboxes.items() if value == sandbox_id), None)
        if sandbox is None:
            return
        if scope is not None and scope[0]:
            try:
                self._sync_outputs_to_host(sandbox, user_id=scope[0], thread_id=scope[1])
            except Exception:
                logger.warning("Failed to synchronize OpenSandbox outputs for %s", sandbox_id, exc_info=True)
        with self._lock:
            # Terminal transfer failures or shutdown may already untrack
            # this client. Never resurrect it in the warm pool.
            if self._sandboxes.get(sandbox_id) is not sandbox:
                return
            self._sandboxes.pop(sandbox_id)
            for key in [key for key, value in self._thread_sandboxes.items() if value == sandbox_id]:
                self._thread_sandboxes.pop(key, None)
            destroy_after_unlock = self._shutdown_called
            if not destroy_after_unlock:
                self._warm_pool[sandbox_id] = (sandbox, time.monotonic())
        if destroy_after_unlock:
            self._destroy_quietly(sandbox, context="released during shutdown")

    @staticmethod
    def _output_parts(remote_path: str) -> tuple[str, ...]:
        prefix = "/mnt/user-data/outputs/"
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
        # Component IDs keep this preflight linear in the bounded listing size,
        # even for deeply nested names. A directory alias rejects all children.
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
        # Reject links/junctions in existing parents, including the owner/thread
        # bucket. Resolving the root first would trust an escaped linked root.
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

    def _sync_outputs_to_host(self, sandbox: OpenSandboxSandbox, *, thread_id: str, user_id: str) -> None:
        """Best-effort bounded mirror before parking a remote sandbox."""
        from deerflow.config.paths import get_paths

        root = get_paths().sandbox_outputs_dir(thread_id, user_id=user_id)
        deadline = time.monotonic() + self._SYNC_DEADLINE_SECONDS
        remote_root = shlex.quote("/mnt/user-data/outputs")
        command = (
            # POSIX sh lacks pipefail: preserve each stage's own exit status.
            'set +e; ( for _tool in find head base64 mktemp; do command -v "$_tool" >/dev/null || exit 127; done; '
            f"[ -d {remote_root} ] && [ ! -L {remote_root} ] || exit 1; "
            "_st=$(mktemp -d) || exit 1; "
            f'{{ find {remote_root} -type f -print0; echo $? > "$_st/find"; }} | '
            f'{{ head -c {self._MAX_SYNC_LISTING_BYTES + 1}; echo $? > "$_st/head"; }} | base64; _enc=$?; '
            '_find=$(cat "$_st/find" 2>/dev/null); _head=$(cat "$_st/head" 2>/dev/null); '
            'rm -f "$_st/find" "$_st/head"; rmdir "$_st"; '
            'printf "\\n__DF_OUTPUT_SYNC__:%s:%s:%s\\n" "$_find" "$_head" "$_enc"; exit 0 )'
        )
        execution = sandbox._run(command, timeout=self._SYNC_DEADLINE_SECONDS)
        if getattr(execution, "exit_code", None) != 0 or getattr(execution, "error", None) is not None:
            raise OSError("OpenSandbox output listing failed")
        # SSE stdout is line-oriented. Base64 keeps event boundaries from
        # inserting newlines into filenames (NUL frames alone cannot do that).
        payload, marker = execution_stdout(execution).rsplit("\n", 1)
        if marker not in {"__DF_OUTPUT_SYNC__:0:0:0", "__DF_OUTPUT_SYNC__:1:0:0", "__DF_OUTPUT_SYNC__:141:0:0"}:
            raise OSError(f"OpenSandbox output listing failed: {marker}")
        raw_listing = base64.b64decode("".join(payload.split()), validate=True)
        if marker == "__DF_OUTPUT_SYNC__:141:0:0" and len(raw_listing) <= self._MAX_SYNC_LISTING_BYTES:
            raise OSError("OpenSandbox output listing failed: unexpected SIGPIPE")
        if len(raw_listing) > self._MAX_SYNC_LISTING_BYTES:
            logger.warning("OpenSandbox output listing exceeded %d bytes; skipping synchronization", self._MAX_SYNC_LISTING_BYTES)
            return
        if raw_listing and not raw_listing.endswith(b"\0"):
            raise OSError("OpenSandbox output listing was incomplete")
        if marker == "__DF_OUTPUT_SYNC__:1:0:0":
            logger.warning("OpenSandbox output listing had traversal errors; synchronizing complete records")
        remote_paths: list[str | None] = []
        for remote_record in filter(None, raw_listing.split(b"\0")):
            try:
                remote_paths.append(remote_record.decode("utf-8"))
            except UnicodeDecodeError:
                logger.warning("Skipping non-UTF-8 OpenSandbox output %r", remote_record)
                remote_paths.append(None)
        # Include records beyond the transfer cap: publishing the first of two
        # aliases would otherwise expose its bytes through both artifact URLs.
        ambiguous_paths = self._ambiguous_output_paths(remote_paths)
        total = 0
        for index, remote_path in enumerate(remote_paths):
            if index >= self._MAX_SYNC_FILES or total >= self._MAX_SYNC_TOTAL_BYTES or time.monotonic() >= deadline:
                logger.warning("OpenSandbox output synchronization stopped at its file, byte or time limit")
                break
            if remote_path is None:
                continue
            if remote_path in ambiguous_paths:
                logger.warning("Skipping ambiguous OpenSandbox output %r", remote_path)
                continue
            staged: Path | None = None
            transferring = False
            try:
                target = self._output_destination(root, remote_path)
                transferring = True
                data = sandbox._download_file_bounded(remote_path, max_bytes=min(_MAX_DOWNLOAD_SIZE, self._MAX_SYNC_TOTAL_BYTES - total), deadline=deadline)
                transferring = False
                total += len(data)
                with tempfile.NamedTemporaryFile(prefix=".opensandbox-sync-", dir=target.parent, delete=False) as output:
                    staged = Path(output.name)
                    output.write(data)
                # Recheck confinement after the network operation before
                # publishing, preserving any previous complete version on error.
                self._output_destination(root, remote_path)
                staged.replace(target)
            except (OSError, ValueError):
                logger.warning("Could not synchronize OpenSandbox output %r", remote_path, exc_info=True)
                # A failed stream may already have consumed bytes that the
                # caller cannot account for. Stop rather than reset its budget.
                if transferring:
                    break
            finally:
                if staged is not None:
                    staged.unlink(missing_ok=True)

    def reset(self) -> None:
        """Park active clients so the detached provider still owns their cleanup."""
        with self._lock:
            now = time.monotonic()
            for sandbox_id, sandbox in self._sandboxes.items():
                self._warm_pool.setdefault(sandbox_id, (sandbox, now))
            self._sandboxes.clear()
            self._thread_sandboxes.clear()
            self._acquire_serializer.close()

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown_called:
                return
            self._shutdown_called = True
        try:
            self._stop_idle_checker()
        except Exception:
            with self._lock:
                self._shutdown_called = False
            raise
        with self._lock:
            sandboxes = list(self._sandboxes.values()) + [entry for entry, _ in self._warm_pool.values()]
            self._sandboxes.clear()
            self._warm_pool.clear()
            self._thread_sandboxes.clear()
            self._acquire_serializer.close()
        for sandbox in sandboxes:
            self._destroy_quietly(sandbox, context="shutdown")


__all__ = ["OpenSandboxProvider"]
