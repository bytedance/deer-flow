"""``VeFaaSSandboxProvider`` — DeerFlow :class:`SandboxProvider` for BytePlus veFaaS Cloud Sandbox.

Runs each DeerFlow thread sandbox as a managed BytePlus Function Service
(veFaaS) Cloud Sandbox instance running the All-in-One Sandbox image. The
control plane calls the BytePlus veFaaS OpenAPI (``Version=2024-06-06``) with
SigV4 authentication, while the data plane reuses :class:`AioSandbox` over the
sandbox application's unified access domain (routing to each instance via
``X-Faas-Instance-Name``) or an instance URL template.
"""

from __future__ import annotations

import atexit
import datetime
import io
import logging
import math
import os
import posixpath
import shlex
import signal
import stat
import tarfile
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal

from deerflow.community.provider_credentials import redact_secret, resolve_api_key
from deerflow.config import get_app_config
from deerflow.sandbox.acquire_serialization import AcquireSerializer, AcquireSerializerClosed
from deerflow.sandbox.download import DEFAULT_DOWNLOAD_LIMIT
from deerflow.sandbox.identity import derive_sandbox_scope_token
from deerflow.sandbox.sandbox import Sandbox, _validate_extra_env
from deerflow.sandbox.sandbox_provider import SandboxProvider, host_owns_sandbox_shutdown

from ..aio_sandbox.aio_sandbox import AioSandbox
from ..aio_sandbox.backend import wait_for_sandbox_ready
from ..aio_sandbox.ownership import (
    OwnershipBackendError,
    RenewOutcome,
    SandboxOwnershipStore,
    generate_owner_id,
    make_sandbox_ownership_store,
    resolve_ownership_config,
)
from ..warm_pool_lifecycle import WarmPoolLifecycleMixin
from .client import (
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_VEFAAS_REGION,
    VeFaaSApiError,
    VeFaaSClient,
    VeFaaSPrecacheTicket,
    VeFaaSSandboxNotFoundError,
    VeFaaSSandboxRecord,
    VeFaaSSnapshotNotFoundError,
    VeFaaSSnapshotRecord,
    validate_endpoint_url,
)

if TYPE_CHECKING:
    from deerflow.skills.projection import SkillProjectionPaths

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MINUTES = 60
MIN_TIMEOUT_MINUTES = 3
MAX_TIMEOUT_MINUTES = 1440
MIN_CPU_MILLI = 250
MAX_CPU_MILLI = 16000
MIN_MEMORY_MB = 512
MAX_MEMORY_MB = 131072
DEFAULT_READY_TIMEOUT = 60.0
DEFAULT_COMMAND_TIMEOUT = 600.0
DEFAULT_SNAPSHOT_TYPE = "disk"
VALID_SNAPSHOT_TYPES = frozenset({"disk", "full"})
MIN_SNAPSHOT_RETENTION_DAYS = 1
MAX_SNAPSHOT_RETENTION_DAYS = 365
DEFAULT_SNAPSHOT_TIMEOUT = 120.0
DEFAULT_MAX_SNAPSHOTS_PER_SANDBOX = 3
MAX_SNAPSHOTS_PER_SANDBOX_LIMIT = 100
DEFAULT_PRECACHE_TIMEOUT = 300.0
DEFAULT_SANDBOX_ACCESS_HEADER = "Authorization"
INSTANCE_ROUTING_HEADER = "X-Faas-Instance-Name"
USER_DATA_ROOT = "/mnt/user-data"
OUTPUTS_ROOT = f"{USER_DATA_ROOT}/outputs"
SKILL_CATEGORIES = ("public", "custom", "legacy", "integrations")
META_KEY_PROVIDER = "deer_flow_provider"
META_KEY_SANDBOX_ID = "deer_flow_sandbox_id"
META_VAL_PROVIDER = "vefaas_sandbox"

_PROTECTED_ROOTS = (
    "/bin",
    "/boot",
    "/dev",
    "/etc",
    "/lib",
    "/lib32",
    "/lib64",
    "/libx32",
    "/proc",
    "/root",
    "/run",
    "/sbin",
    "/sys",
    "/usr",
    "/var",
)
_WINDOWS_RESERVED_NAMES = frozenset({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {f"{prefix}{digit}" for prefix in ("COM", "LPT") for digit in "123456789¹²³"})
_BOOTSTRAP_OK_MARKER = "DEERFLOW_VEFAAS_BOOTSTRAP_OK"
# Use a split printf format so PTY echo of the command string cannot satisfy the marker check,
# and run in a subshell with ``set +e`` outside so persistent shell state is never poisoned.
_BOOTSTRAP_COMMAND = "set +e; ( mkdir -p -- /mnt/user-data/workspace /mnt/user-data/uploads /mnt/user-data/outputs && printf 'DEERFLOW_VEFAAS_%s\\n' 'BOOTSTRAP_OK' )"
_INIT_MARKER_PATH = "/tmp/.deerflow-vefaas-initialized"
_ADOPT_INIT_WAIT_SECONDS = 10.0
_ADOPT_INIT_POLL_INTERVAL_SECONDS = 0.2
_REMOTE_INIT_LOCKS_GUARD = threading.Lock()
_REMOTE_INIT_LOCKS: dict[tuple[str, str, str], tuple[threading.RLock, int]] = {}
_MAX_UPLOAD_FILES = 5000
_MAX_UPLOAD_BYTES = 64 * 1024 * 1024
_MAX_SYNC_FILES = 2000
_MAX_SYNC_TOTAL_BYTES = 512 * 1024 * 1024
_MAX_SYNC_LISTING_BYTES = 512 * 1024
_SYNC_DEADLINE_SECONDS = 120.0
_POLL_STATUS_INTERVAL_SECONDS = 1.0

VEFAAS_EXTRA_CONFIG_KEYS = frozenset(
    {
        "vefaas",
        "region",
        "endpoint",
        "function_id",
        "sandbox_base_url",
        "access_key",
        "secret_key",
        "session_token",
        "access_key_env",
        "secret_key_env",
        "session_token_env",
        "sandbox_access_token",
        "sandbox_access_header",
        "cpu_milli",
        "memory_mb",
        "timeout_minutes",
        "ready_timeout",
        "request_timeout",
        "allow_insecure_http",
        "tos_mount",
        "metadata",
        "snapshot_id",
        "pause_on_idle",
        "auto_pause",
        "snapshot_on_idle",
        "snapshot_type",
        "snapshot_retention_days",
        "snapshot_timeout",
        "max_snapshots_per_sandbox",
        "precache_images",
        "precache_on_startup",
    }
)
_TOS_MOUNT_KEYS = frozenset({"enabled", "bucket", "prefix", "local_mount_path", "read_only", "endpoint"})
_DISCOVER_TRANSITION_STATUSES = frozenset({"pausing", "resuming", "snapshotting"})


class _VeFaaSShutdownIncompleteError(RuntimeError):
    """Raised when shutdown leaves unconfirmed teardowns or running workers."""


class _VeFaaSSnapshotSettledFailureError(RuntimeError):
    """Raised when the control plane confirms a snapshot failed or disappeared."""


class _PeerTeardownError(RuntimeError):
    """Raised when a peer holds a destructive teardown lease for a sandbox."""


@dataclass
class _TrackedVeFaaSSandbox:
    """In-memory handle pairing a DeerFlow logical ID with its remote veFaaS instance."""

    sandbox_id: str
    remote_sandbox_id: str
    sandbox: AioSandbox
    thread_id: str | None
    user_id: str | None


@dataclass(frozen=True)
class _PendingRollback:
    """Failed provisioning generation retained for retryable teardown and shutdown."""

    sandbox_id: str
    remote_sandbox_id: str
    release_ownership: bool


@dataclass
class _UploadBudget:
    """Aggregate file-count and byte ceiling for one tar upload pass."""

    max_files: int
    max_bytes: int
    files: int = 0
    bytes: int = 0

    def admit(self, size: int) -> bool:
        if self.files + 1 > self.max_files or self.bytes + size > self.max_bytes:
            return False
        self.files += 1
        self.bytes += size
        return True


def _validate_skills_root(container_path: str) -> str:
    """Validate that the managed skills root is an isolated, non-system absolute path."""
    raw = (container_path or "").rstrip("/")
    normalized = posixpath.normpath(raw) if raw else ""
    if not normalized.startswith("/") or normalized == "/" or normalized != raw:
        raise ValueError(f"skills.container_path {container_path!r} is not a safe veFaaS skills root: use a normalized absolute path such as /mnt/skills")
    if normalized in {"/home", "/mnt", "/tmp"} or any(normalized == root or normalized.startswith(f"{root}/") for root in _PROTECTED_ROOTS):
        raise ValueError(f"skills.container_path {container_path!r} is not a safe veFaaS skills root: it is a system directory")
    if normalized == USER_DATA_ROOT or normalized.startswith(f"{USER_DATA_ROOT}/") or USER_DATA_ROOT.startswith(f"{normalized}/"):
        raise ValueError(f"skills.container_path {container_path!r} must not overlap {USER_DATA_ROOT}")
    return normalized


def _validate_sandbox_url_template(raw_url: str, *, allow_insecure_http: bool) -> str:
    """Validate a unified sandbox URL or a ``{sandbox_id}`` URL template."""
    trimmed = raw_url.strip().rstrip("/")
    if not trimmed:
        raise ValueError("sandbox.sandbox_base_url must not be empty")
    probe = trimmed.replace("{sandbox_id}", "sandbox-placeholder")
    validate_endpoint_url(probe, allow_insecure_http=allow_insecure_http)
    return trimmed


def _sanitize_tos_prefix(raw_prefix: str) -> str:
    """Normalize a TOS bucket prefix while rejecting path traversal."""
    cleaned = raw_prefix.strip().strip("/")
    if not cleaned:
        return ""
    parts = cleaned.split("/")
    if any(part in {"", ".", ".."} or "\\" in part for part in parts):
        raise ValueError(f"sandbox.tos_mount.prefix {raw_prefix!r} contains invalid path segments")
    return "/".join(parts)


def _snapshot_sort_key(record: VeFaaSSnapshotRecord) -> tuple[int, float, str, str]:
    """Order snapshots newest-first by UTC creation timestamp with deterministic ID tie-break."""
    raw = record.created_at.strip()
    if raw:
        try:
            parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.UTC)
            return (1, parsed.timestamp(), raw, record.id)
        except ValueError:
            return (0, 0.0, raw, record.id)
    return (0, 0.0, "", record.id)


class VeFaaSSandboxProvider(WarmPoolLifecycleMixin[_TrackedVeFaaSSandbox], SandboxProvider):
    """Manage BytePlus veFaaS Cloud Sandbox instances reusing :class:`AioSandbox`."""

    uses_thread_data_mounts = False
    needs_upload_permission_adjustment = True
    supports_agent_skill_isolation = True
    supports_lazy_agent_skill_isolation = False
    _idle_checker_thread_name = "vefaas-sandbox-idle-reaper"
    _snapshot_watch_interval = _POLL_STATUS_INTERVAL_SECONDS

    def __init__(self, *, client: VeFaaSClient | None = None) -> None:
        self._lock = threading.Lock()
        self._shutdown_lock = threading.Lock()
        self._sandboxes: dict[str, _TrackedVeFaaSSandbox] = {}
        self._thread_sandboxes: dict[tuple[str, str], str] = {}
        self._warm_pool: dict[str, tuple[_TrackedVeFaaSSandbox, float]] = {}
        self._quarantined_remote_ids: dict[str, set[str]] = {}
        self._pending_destroys: dict[str, _TrackedVeFaaSSandbox] = {}
        self._pending_rollbacks: dict[str, _PendingRollback] = {}
        self._destroying_remote_ids: set[str] = set()
        self._mirroring_output_ids: set[str] = set()
        self._snapshotting_remote_ids: dict[str, int] = {}
        self._remote_snapshot_fences: dict[str, int] = {}
        self._snapshot_fence_locks: dict[str, tuple[threading.Lock, int]] = {}
        self._snapshot_watchers: set[threading.Thread] = set()
        self._snapshot_metadata_filter_supported = True
        self._snapshot_status_filter_supported = True
        # Same-process exclusion against warm-pool reaping and stale lease renewals:
        # - _local_teardown: refcount of teardowns currently active in this process
        # - _acquire_inflight: refcount of acquires currently publishing ownership
        # - _acquire_epoch: monotonic generation bumped whenever this process publishes an acquire
        # - _acquires: total in-flight acquire() calls gated by shutdown()
        self._local_teardown: dict[str, int] = {}
        self._acquire_inflight: dict[str, int] = {}
        self._acquire_epoch: dict[str, int] = {}
        self._acquire_epoch_counter = 0
        self._acquires = 0
        self._acquire_serializer: AcquireSerializer[str] = AcquireSerializer(thread_name_prefix="vefaas-sandbox-acquire-wait")
        self._idle_checker_stop = threading.Event()
        self._idle_checker_thread: threading.Thread | None = None
        self._renewal_stop = threading.Event()
        self._renewal_thread: threading.Thread | None = None
        self._precache_stop = threading.Event()
        self._precache_thread: threading.Thread | None = None
        self._shutdown_called = False
        self._shutdown_complete = False
        self._accepting = True
        self._owner_id = generate_owner_id()
        self._client_override = client
        self._client: VeFaaSClient | None = client
        self._config = self._load_config()

        self._ownership_config = resolve_ownership_config(
            self._config.get("ownership"),
            stream_bridge=self._config.get("stream_bridge"),
        )
        self._ownership: SandboxOwnershipStore = make_sandbox_ownership_store(
            self._ownership_config,
            owner_id=self._owner_id,
        )

        atexit.register(self._shutdown_at_exit)
        self._register_signal_handlers()
        self._start_idle_checker()
        self._start_renewal_thread()
        self._start_precache_thread()

    # ── Config ───────────────────────────────────────────────────────────

    @staticmethod
    def _bounded_int(name: str, value: Any, *, minimum: int, maximum: int, default: int | None = None) -> int | None:
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"sandbox.{name} must be an integer")
        if value < minimum or value > maximum:
            raise ValueError(f"sandbox.{name} must be between {minimum} and {maximum}")
        return value

    @staticmethod
    def _positive_float(name: str, value: Any, default: float) -> float:
        if value is not None and isinstance(value, bool):
            raise ValueError(f"sandbox.{name} must be a positive number")
        try:
            resolved = float(default if value is None else value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"sandbox.{name} must be a positive number") from exc
        if not math.isfinite(resolved) or resolved <= 0:
            raise ValueError(f"sandbox.{name} must be a positive number")
        return resolved

    @staticmethod
    def _bool_option(name: str, value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if not isinstance(value, bool):
            raise ValueError(f"sandbox.{name} must be true or false")
        return value

    @staticmethod
    def _validate_snapshot_type(value: Any, *, default: str = DEFAULT_SNAPSHOT_TYPE) -> str:
        if value is None:
            return default
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"sandbox.snapshot_type must be one of: {', '.join(sorted(VALID_SNAPSHOT_TYPES))}")
        normalized = value.strip().lower()
        if normalized not in VALID_SNAPSHOT_TYPES:
            raise ValueError(f"sandbox.snapshot_type must be one of: {', '.join(sorted(VALID_SNAPSHOT_TYPES))}")
        return normalized

    @staticmethod
    def _validate_precache_images(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise ValueError("sandbox.precache_images must be a list of non-empty image URLs")
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("sandbox.precache_images must contain only non-empty strings")
            url = item.strip()
            if url not in seen:
                seen.add(url)
                cleaned.append(url)
        return cleaned

    def _load_config(self) -> dict[str, Any]:
        app_config = get_app_config()
        sandbox_config = app_config.sandbox
        model_extra = dict(getattr(sandbox_config, "model_extra", None) or {})
        unknown_top = sorted(set(model_extra) - VEFAAS_EXTRA_CONFIG_KEYS)
        if unknown_top:
            logger.warning("VeFaaSSandboxProvider: unknown sandbox config fields: %s", ", ".join(unknown_top))

        nested = model_extra.get("vefaas")
        if nested is not None and not isinstance(nested, Mapping):
            raise ValueError("sandbox.vefaas must be a mapping")
        nested_map = dict(nested or {})
        unknown_nested = sorted(set(nested_map) - (VEFAAS_EXTRA_CONFIG_KEYS - {"vefaas"}))
        if unknown_nested:
            logger.warning("VeFaaSSandboxProvider: unknown sandbox.vefaas config fields: %s", ", ".join(unknown_nested))

        def opt(name: str, default: Any = None) -> Any:
            if name in nested_map and nested_map[name] is not None:
                return nested_map[name]
            val = getattr(sandbox_config, name, None)
            return default if val is None else val

        allow_insecure_http = self._bool_option("allow_insecure_http", opt("allow_insecure_http"), default=False)
        region = str(opt("region") or os.environ.get("BYTEPLUS_REGION") or DEFAULT_VEFAAS_REGION).strip()
        if not region:
            raise ValueError("sandbox.region must not be empty")

        raw_endpoint = str(opt("endpoint") or os.environ.get("BYTEPLUS_VEFAAS_ENDPOINT") or f"https://vefaas.{region}.byteplusapi.com").strip()
        endpoint = validate_endpoint_url(raw_endpoint, allow_insecure_http=allow_insecure_http)

        function_id = str(opt("function_id") or os.environ.get("BYTEPLUS_VEFAAS_SANDBOX_APP_ID") or os.environ.get("VEFAAS_FUNCTION_ID") or "").strip()
        raw_sandbox_base_url = str(opt("sandbox_base_url") or os.environ.get("BYTEPLUS_VEFAAS_SANDBOX_BASE_URL") or os.environ.get("VEFAAS_SANDBOX_BASE_URL") or "").strip()
        sandbox_base_url = _validate_sandbox_url_template(raw_sandbox_base_url, allow_insecure_http=allow_insecure_http) if raw_sandbox_base_url else ""

        ak_env = str(opt("access_key_env") or "BYTEPLUS_ACCESS_KEY_ID").strip()
        sk_env = str(opt("secret_key_env") or "BYTEPLUS_SECRET_ACCESS_KEY").strip()
        st_env = str(opt("session_token_env") or "BYTEPLUS_SESSION_TOKEN").strip()

        access_key = resolve_api_key(opt("access_key")) or resolve_api_key(os.environ.get(ak_env))
        secret_key = resolve_api_key(opt("secret_key")) or resolve_api_key(os.environ.get(sk_env))
        session_token = resolve_api_key(opt("session_token")) or resolve_api_key(os.environ.get(st_env))
        sandbox_access_token = resolve_api_key(opt("sandbox_access_token")) or resolve_api_key(os.environ.get("BYTEPLUS_VEFAAS_SANDBOX_ACCESS_TOKEN"))
        sandbox_access_header = str(opt("sandbox_access_header") or DEFAULT_SANDBOX_ACCESS_HEADER).strip()
        if not sandbox_access_header:
            raise ValueError("sandbox.sandbox_access_header must not be empty")

        cpu_milli = self._bounded_int("cpu_milli", opt("cpu_milli"), minimum=MIN_CPU_MILLI, maximum=MAX_CPU_MILLI)
        memory_mb = self._bounded_int("memory_mb", opt("memory_mb"), minimum=MIN_MEMORY_MB, maximum=MAX_MEMORY_MB)
        timeout_minutes = self._bounded_int(
            "timeout_minutes",
            opt("timeout_minutes"),
            minimum=MIN_TIMEOUT_MINUTES,
            maximum=MAX_TIMEOUT_MINUTES,
            default=DEFAULT_TIMEOUT_MINUTES,
        )
        assert timeout_minutes is not None

        raw_metadata = opt("metadata") or {}
        if not isinstance(raw_metadata, Mapping) or not all(isinstance(k, str) and isinstance(v, str) for k, v in raw_metadata.items()):
            raise ValueError("sandbox.metadata must map strings to strings")

        tos_mount_cfg = self._parse_tos_mount(opt("tos_mount"), allow_insecure_http=allow_insecure_http)

        raw_snapshot_id = opt("snapshot_id")
        if raw_snapshot_id is None:
            snapshot_id = None
        elif isinstance(raw_snapshot_id, str) and raw_snapshot_id.strip():
            snapshot_id = raw_snapshot_id.strip()
        else:
            raise ValueError("sandbox.snapshot_id must be a non-empty string")

        pause_on_idle = self._bool_option("pause_on_idle", opt("pause_on_idle"), default=False)
        auto_pause = self._bool_option("auto_pause", opt("auto_pause"), default=False)
        snapshot_on_idle = self._bool_option("snapshot_on_idle", opt("snapshot_on_idle"), default=False)
        snapshot_type = self._validate_snapshot_type(opt("snapshot_type"))
        snapshot_retention_days = self._bounded_int(
            "snapshot_retention_days",
            opt("snapshot_retention_days"),
            minimum=MIN_SNAPSHOT_RETENTION_DAYS,
            maximum=MAX_SNAPSHOT_RETENTION_DAYS,
        )
        snapshot_timeout = self._positive_float("snapshot_timeout", opt("snapshot_timeout"), DEFAULT_SNAPSHOT_TIMEOUT)
        max_snapshots_per_sandbox = self._bounded_int(
            "max_snapshots_per_sandbox",
            opt("max_snapshots_per_sandbox"),
            minimum=1,
            maximum=MAX_SNAPSHOTS_PER_SANDBOX_LIMIT,
            default=DEFAULT_MAX_SNAPSHOTS_PER_SANDBOX,
        )
        assert max_snapshots_per_sandbox is not None
        precache_images = self._validate_precache_images(opt("precache_images"))
        precache_on_startup = self._bool_option("precache_on_startup", opt("precache_on_startup"), default=False)

        environment = dict(getattr(sandbox_config, "environment", None) or {})
        _validate_extra_env(environment)

        replicas = getattr(sandbox_config, "replicas", None)
        idle_timeout = getattr(sandbox_config, "idle_timeout", None)
        command_timeout = self._positive_float(
            "bash_command_timeout",
            getattr(sandbox_config, "bash_command_timeout", None),
            DEFAULT_COMMAND_TIMEOUT,
        )

        return {
            "region": region,
            "endpoint": endpoint,
            "function_id": function_id,
            "sandbox_base_url": sandbox_base_url,
            "access_key": access_key,
            "secret_key": secret_key,
            "session_token": session_token,
            "sandbox_access_token": sandbox_access_token,
            "sandbox_access_header": sandbox_access_header,
            "cpu_milli": cpu_milli,
            "memory_mb": memory_mb,
            "timeout_minutes": timeout_minutes,
            "ready_timeout": self._positive_float("ready_timeout", opt("ready_timeout"), DEFAULT_READY_TIMEOUT),
            "request_timeout": self._positive_float("request_timeout", opt("request_timeout"), DEFAULT_REQUEST_TIMEOUT),
            "allow_insecure_http": allow_insecure_http,
            "image": getattr(sandbox_config, "image", None),
            "port": getattr(sandbox_config, "port", None),
            "tos_mount": tos_mount_cfg,
            "metadata": dict(raw_metadata),
            "snapshot_id": snapshot_id,
            "pause_on_idle": pause_on_idle,
            "auto_pause": auto_pause,
            "snapshot_on_idle": snapshot_on_idle,
            "snapshot_type": snapshot_type,
            "snapshot_retention_days": snapshot_retention_days,
            "snapshot_timeout": snapshot_timeout,
            "max_snapshots_per_sandbox": max_snapshots_per_sandbox,
            "precache_images": precache_images,
            "precache_on_startup": precache_on_startup,
            "environment": environment,
            "skills_container_path": _validate_skills_root(app_config.skills.container_path),
            "replicas": replicas if replicas is not None else self.DEFAULT_REPLICAS,
            "idle_timeout": idle_timeout if idle_timeout is not None else self.DEFAULT_IDLE_TIMEOUT,
            "command_timeout": command_timeout,
            "ownership": getattr(sandbox_config, "ownership", None),
            "stream_bridge": getattr(app_config, "stream_bridge", None),
        }

    def _parse_tos_mount(self, raw: Any, *, allow_insecure_http: bool) -> dict[str, Any] | None:
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise ValueError("sandbox.tos_mount must be a mapping")
        unknown = sorted(set(raw) - _TOS_MOUNT_KEYS)
        if unknown:
            logger.warning("VeFaaSSandboxProvider: unknown sandbox.tos_mount fields: %s", ", ".join(unknown))
        enabled = self._bool_option("tos_mount.enabled", raw.get("enabled"), default=False)
        if not enabled:
            return None
        bucket = str(raw.get("bucket") or "").strip()
        if not bucket:
            raise ValueError("sandbox.tos_mount.bucket is required when tos_mount.enabled is true")
        prefix = _sanitize_tos_prefix(str(raw.get("prefix") or ""))
        local_mount_path = posixpath.normpath(str(raw.get("local_mount_path") or USER_DATA_ROOT).strip())
        if not local_mount_path.startswith("/") or local_mount_path == "/":
            raise ValueError("sandbox.tos_mount.local_mount_path must be a non-root absolute path")
        read_only = self._bool_option("tos_mount.read_only", raw.get("read_only"), default=False)
        tos_endpoint = raw.get("endpoint")
        validated_endpoint = validate_endpoint_url(str(tos_endpoint), allow_insecure_http=allow_insecure_http) if tos_endpoint else None
        return {
            "enabled": True,
            "bucket": bucket,
            "prefix": prefix,
            "local_mount_path": local_mount_path,
            "read_only": read_only,
            "endpoint": validated_endpoint,
        }

    def _get_client(self) -> VeFaaSClient:
        with self._lock:
            if self._client is not None:
                return self._client
        access_key = self._config["access_key"]
        secret_key = self._config["secret_key"]
        if not access_key or not secret_key:
            raise ValueError("VeFaaSSandboxProvider requires BytePlus credentials: set sandbox.access_key / sandbox.secret_key or BYTEPLUS_ACCESS_KEY_ID / BYTEPLUS_SECRET_ACCESS_KEY")
        client = VeFaaSClient(
            endpoint=self._config["endpoint"],
            region=self._config["region"],
            access_key=access_key,
            secret_key=secret_key,
            session_token=self._config["session_token"],
            timeout=self._config["request_timeout"],
            allow_insecure_http=self._config["allow_insecure_http"],
        )
        with self._lock:
            if self._client is None:
                self._client = client
                return client
            existing = self._client
        client.close()
        return existing

    def _require_provisioning_settings(self) -> tuple[str, str]:
        function_id = self._config["function_id"]
        sandbox_base_url = self._config["sandbox_base_url"]
        if not function_id:
            raise ValueError("VeFaaSSandboxProvider requires sandbox.function_id (or BYTEPLUS_VEFAAS_SANDBOX_APP_ID)")
        if not sandbox_base_url:
            raise ValueError("VeFaaSSandboxProvider requires sandbox.sandbox_base_url (or BYTEPLUS_VEFAAS_SANDBOX_BASE_URL)")
        return function_id, sandbox_base_url

    # ── Identity & data-plane construction ───────────────────────────────

    @staticmethod
    def _sandbox_id(thread_id: str, user_id: str | None) -> str:
        return derive_sandbox_scope_token(user_id=user_id or "", thread_id=thread_id)

    @staticmethod
    def _thread_key(thread_id: str, user_id: str | None) -> tuple[str, str]:
        return (user_id or "", thread_id)

    def _resolve_data_plane(self, remote_sandbox_id: str) -> tuple[str, dict[str, str]]:
        """Build the data-plane URL and ephemeral headers for one veFaaS instance."""
        _, template = self._require_provisioning_settings()
        headers: dict[str, str] = {}
        if "{sandbox_id}" in template:
            url = template.replace("{sandbox_id}", remote_sandbox_id)
        else:
            url = template
            headers[INSTANCE_ROUTING_HEADER] = remote_sandbox_id

        token = self._config["sandbox_access_token"]
        if token:
            header_name = self._config["sandbox_access_header"]
            if header_name.lower() == "authorization" and " " not in token:
                headers[header_name] = f"Bearer {token}"
            else:
                headers[header_name] = token
        return url, headers

    def _build_aio_sandbox(self, sandbox_id: str, remote_sandbox_id: str) -> AioSandbox:
        url, headers = self._resolve_data_plane(remote_sandbox_id)
        return AioSandbox(
            id=sandbox_id,
            base_url=url,
            request_headers=headers or None,
            default_command_timeout=self._config["command_timeout"],
            lark_cli_broker=False,
        )

    def _build_tos_mount_config(self, sandbox_id: str) -> dict[str, Any] | None:
        tos_cfg = self._config["tos_mount"]
        if not tos_cfg:
            return None
        prefix = tos_cfg["prefix"]
        bucket_path = f"/{prefix}/{sandbox_id}" if prefix else f"/{sandbox_id}"
        mount_point: dict[str, Any] = {
            "BucketName": tos_cfg["bucket"],
            "BucketPath": bucket_path,
            "LocalMountPath": tos_cfg["local_mount_path"],
            "ReadOnly": tos_cfg["read_only"],
        }
        if tos_cfg.get("endpoint"):
            mount_point["Endpoint"] = tos_cfg["endpoint"]
        return {
            "Enable": True,
            "TosMountPoints": [mount_point],
        }

    def _uses_tos_for_user_data(self) -> bool:
        tos_cfg = self._config["tos_mount"]
        return bool(tos_cfg and tos_cfg["local_mount_path"] == USER_DATA_ROOT)

    # ── Non-blocking lookups (event-loop hot path) ───────────────────────

    def get(self, sandbox_id: str) -> Sandbox | None:
        """Return an active sandbox purely from process memory (never blocks)."""
        with self._lock:
            tracked = self._sandboxes.get(sandbox_id)
            return tracked.sandbox if tracked is not None else None

    def get_scoped(
        self,
        sandbox_id: str,
        *,
        thread_id: str,
        user_id: str,
    ) -> Sandbox | None:
        """Return an active sandbox only when it matches ``(user_id, thread_id)``."""
        expected_id = self._sandbox_id(thread_id, user_id)
        if sandbox_id != expected_id:
            return None
        with self._lock:
            tracked = self._sandboxes.get(sandbox_id)
            if tracked is None:
                return None
            if (tracked.user_id or "") != (user_id or "") or tracked.thread_id != thread_id:
                return None
            return tracked.sandbox

    # ── Warm pool & ownership maintenance ────────────────────────────────

    def _start_idle_checker(self) -> None:
        if self._config["idle_timeout"] <= 0:
            return
        super()._start_idle_checker()

    def _active_count_locked(self) -> int:
        return len(self._sandboxes) + len(self._pending_destroys)

    def _bump_acquire_epoch_locked(self, sandbox_id: str) -> int:
        self._acquire_epoch_counter += 1
        self._acquire_epoch[sandbox_id] = self._acquire_epoch_counter
        return self._acquire_epoch_counter

    @contextmanager
    def _acquiring(self) -> Iterator[None]:
        with self._lock:
            if not self._accepting or self._shutdown_called:
                raise RuntimeError("VeFaaSSandboxProvider has been shut down")
            self._acquires += 1
        try:
            yield
        finally:
            with self._lock:
                self._acquires -= 1

    @staticmethod
    def _is_sandbox_dirty(sandbox: AioSandbox) -> bool:
        # Read pending session creates before requires_container_recycle so a
        # pending -> ambiguous transition cannot slip into warm reuse, pause, or snapshot.
        return getattr(sandbox, "has_pending_session_creates", False) is True or getattr(sandbox, "requires_container_recycle", False) is True

    def _cleanup_idle_resources(self, idle_timeout: float) -> None:
        self._retry_pending_destroys()
        self._reap_expired_warm(idle_timeout)

    def _destroy_warm_entry(self, sandbox_id: str, entry: _TrackedVeFaaSSandbox, *, reason: str) -> bool:
        def still_reapable(sid: str = sandbox_id, expected: _TrackedVeFaaSSandbox = entry) -> bool:
            return self._warm_pool.get(sid, (None, 0.0))[0] is expected and sid not in self._sandboxes and sid not in self._acquire_inflight and expected.remote_sandbox_id not in self._snapshotting_remote_ids

        is_dirty = self._is_sandbox_dirty(entry.sandbox)
        want_pause = bool(self._config["pause_on_idle"]) and not is_dirty
        want_snapshot = bool(self._config["snapshot_on_idle"]) and not is_dirty
        if not want_pause and not want_snapshot:
            return self._destroy_tracked(
                entry,
                reason=f"warm_pool:{reason}",
                still_reapable=still_reapable,
                pop_warm=True,
            )
        return self._retire_warm_entry(
            entry,
            reason=f"warm_pool:{reason}",
            still_reapable=still_reapable,
            pause=want_pause,
            snapshot=want_snapshot,
        )

    def _evict_oldest_warm(self) -> str | None:
        """Evict the oldest eligible warm entry while keeping it fenced until teardown reserves it."""
        attempted: set[str] = set()
        while True:
            with self._lock:
                candidates = [
                    (sid, entry, ts)
                    for sid, (entry, ts) in self._warm_pool.items()
                    if sid not in attempted and sid not in self._local_teardown and sid not in self._acquire_inflight and sid not in self._sandboxes and entry.remote_sandbox_id not in self._snapshotting_remote_ids
                ]
                if not candidates:
                    return None
                sandbox_id, entry, _ = min(candidates, key=lambda item: item[2])
            attempted.add(sandbox_id)
            if self._destroy_warm_entry(sandbox_id, entry, reason="replica_enforcement"):
                return sandbox_id

    def _reap_expired_warm(self, idle_timeout: float | None = None) -> None:
        """Reap expired warm entries using per-sandbox local teardown reservations."""
        timeout = float(self._config.get("idle_timeout", self.DEFAULT_IDLE_TIMEOUT) if idle_timeout is None else idle_timeout)
        if timeout <= 0:
            return
        now = time.monotonic()
        with self._lock:
            expired = [
                (sandbox_id, entry)
                for sandbox_id, (entry, timestamp) in self._warm_pool.items()
                if now - timestamp > timeout and sandbox_id not in self._local_teardown and sandbox_id not in self._acquire_inflight and entry.remote_sandbox_id not in self._snapshotting_remote_ids
            ]
        for sandbox_id, entry in expired:
            self._destroy_warm_entry(sandbox_id, entry, reason="idle_timeout")

    def _start_renewal_thread(self) -> None:
        if not self._ownership.supports_cross_process:
            return
        if self._renewal_thread is not None and self._renewal_thread.is_alive():
            return
        self._renewal_stop.clear()
        self._renewal_thread = threading.Thread(
            target=self._renewal_loop,
            name="vefaas-sandbox-lease-renewer",
            daemon=True,
        )
        self._renewal_thread.start()

    def _stop_renewal_thread(self) -> None:
        self._renewal_stop.set()
        thread = self._renewal_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)
            if thread.is_alive():
                raise RuntimeError("veFaaS ownership renewal thread is still running after stop timeout")

    def _resolve_precache_urls(self, image_urls: Sequence[str] | None = None) -> list[str]:
        if image_urls is not None:
            return self._validate_precache_images(image_urls)
        configured = list(self._config["precache_images"])
        if configured:
            return configured
        image = self._config.get("image")
        if isinstance(image, str) and image.strip():
            return [image.strip()]
        return []

    def _start_precache_thread(self) -> None:
        if not self._config["precache_on_startup"]:
            return
        urls = self._resolve_precache_urls()
        if not urls:
            logger.debug("Skipping veFaaS startup image precache: no precache_images or image configured")
            return
        self._precache_stop.clear()
        self._precache_thread = threading.Thread(
            target=self._run_startup_precache,
            args=(urls,),
            name="vefaas-sandbox-image-precache",
            daemon=True,
        )
        self._precache_thread.start()

    def _stop_precache_thread(self) -> None:
        self._precache_stop.set()
        thread = self._precache_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)
            if thread.is_alive():
                raise RuntimeError("veFaaS image precache thread is still running after stop timeout")

    def _run_startup_precache(self, image_urls: list[str]) -> None:
        with self._lock:
            if self._precache_stop.is_set() or self._shutdown_called:
                return
        try:
            ticket_id = self._get_client().precache_sandbox_images(image_urls)
            logger.info("Submitted veFaaS startup image precache ticket %s for %d image(s)", ticket_id, len(image_urls))
        except Exception as exc:
            logger.warning("veFaaS startup image precache failed: %s", self._redact(exc))

    def _renewal_loop(self) -> None:
        interval = self._ownership_config.renewal_interval_seconds
        while not self._renewal_stop.wait(interval):
            try:
                self._renew_leases_once()
            except Exception:
                logger.exception("Error in veFaaS sandbox ownership renewal loop")

    def _renew_leases_once(self) -> None:
        with self._lock:
            tracked_ids = sorted(set(self._sandboxes) | set(self._warm_pool) | {entry.sandbox_id for rid, entry in self._pending_destroys.items() if rid in self._snapshotting_remote_ids})
            fenced_remotes = sorted(self._remote_snapshot_fences)
        for remote_id in fenced_remotes:
            self._refresh_snapshot_fence(remote_id)
        for sandbox_id in tracked_ids:
            with self._lock:
                if sandbox_id in self._local_teardown or sandbox_id in self._acquire_inflight:
                    continue
                epoch = self._acquire_epoch.get(sandbox_id, 0)
            try:
                outcome = self._ownership.renew(sandbox_id)
            except OwnershipBackendError as exc:
                logger.warning("Failed to renew ownership lease for veFaaS sandbox %s: %s", sandbox_id, exc)
                continue
            if outcome is RenewOutcome.RENEWED:
                continue
            if outcome is RenewOutcome.LAPSED:
                try:
                    reclaimed = self._ownership.claim(sandbox_id)
                except OwnershipBackendError as exc:
                    logger.warning("Failed to re-claim lapsed lease for veFaaS sandbox %s: %s", sandbox_id, exc)
                    continue
                if not reclaimed:
                    self._forget_lost_sandbox(sandbox_id, expected_epoch=epoch)
            elif outcome is RenewOutcome.LOST:
                self._forget_lost_sandbox(sandbox_id, expected_epoch=epoch)

    def _forget_lost_sandbox(self, sandbox_id: str, *, expected_epoch: int | None = None) -> None:
        """Stop tracking a sandbox whose ownership moved to a peer (never kill it)."""
        with self._lock:
            if sandbox_id in self._local_teardown:
                logger.debug("Not dropping veFaaS sandbox %s: this instance is tearing it down", sandbox_id)
                return
            if sandbox_id in self._acquire_inflight:
                logger.info("Not dropping veFaaS sandbox %s: an acquire is publishing ownership for it", sandbox_id)
                return
            if expected_epoch is not None and self._acquire_epoch.get(sandbox_id, 0) != expected_epoch:
                logger.info("Not dropping veFaaS sandbox %s: this instance re-acquired it after the lease check", sandbox_id)
                return
            active = self._sandboxes.pop(sandbox_id, None)
            warm = self._warm_pool.pop(sandbox_id, None)
            self._acquire_epoch.pop(sandbox_id, None)
            for key in [k for k, v in self._thread_sandboxes.items() if v == sandbox_id]:
                self._thread_sandboxes.pop(key, None)
        tracked = active or (warm[0] if warm is not None else None)
        if tracked is not None:
            logger.info("Forgetting veFaaS sandbox %s after ownership moved to a peer", sandbox_id)
            tracked.sandbox.close()

    def _register_signal_handlers(self) -> None:
        if host_owns_sandbox_shutdown():
            return
        if threading.current_thread() is not threading.main_thread():
            return
        for sig_name in ("SIGTERM", "SIGINT"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            prev = signal.getsignal(sig)

            def _handler(signum: int, frame: Any, _prev: Any = prev) -> None:
                try:
                    self.shutdown()
                except Exception:
                    logger.exception("veFaaS sandbox shutdown failed while handling signal %s; forwarding signal", signum)
                if callable(_prev):
                    _prev(signum, frame)
                elif _prev == signal.SIG_DFL:
                    signal.signal(signum, signal.SIG_DFL)
                    signal.raise_signal(signum)

            try:
                signal.signal(sig, _handler)
            except (OSError, ValueError):
                # Signal registration is unsupported outside the main thread or in restricted runtimes.
                logger.debug("Skipping %s handler registration for VeFaaSSandboxProvider", sig_name)

    # ── Acquisition ──────────────────────────────────────────────────────

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        with self._acquiring():
            if thread_id is None:
                sandbox_id = str(uuid.uuid4())[:8]
                with self._lock:
                    self._acquire_inflight[sandbox_id] = self._acquire_inflight.get(sandbox_id, 0) + 1
                try:
                    tracked = self._create_new_sandbox(sandbox_id, thread_id=None, user_id=user_id)
                    with self._lock:
                        if not self._accepting or self._shutdown_called or sandbox_id in self._local_teardown:
                            self._pending_destroys[tracked.remote_sandbox_id] = tracked
                            rollback = True
                        else:
                            self._sandboxes[sandbox_id] = tracked
                            self._bump_acquire_epoch_locked(sandbox_id)
                            rollback = False
                finally:
                    with self._lock:
                        remaining = self._acquire_inflight.get(sandbox_id, 1) - 1
                        if remaining <= 0:
                            self._acquire_inflight.pop(sandbox_id, None)
                        else:
                            self._acquire_inflight[sandbox_id] = remaining
                if rollback:
                    self._destroy_tracked(tracked, reason="created_during_shutdown", require_pending=True)
                    raise RuntimeError("VeFaaSSandboxProvider shut down during acquire")
                return sandbox_id

            key = self._thread_key(thread_id, user_id)
            sandbox_id = self._sandbox_id(thread_id, user_id)
            with self._acquire_serializer.hold(sandbox_id):
                return self._acquire_scope_locked(key, sandbox_id, thread_id=thread_id, user_id=user_id)

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        """Acquire a veFaaS sandbox off the event loop via the serializer's dedicated executor."""
        fn = partial(self.acquire, thread_id, user_id=user_id)
        return await self._acquire_serializer.run_on_executor(fn)

    def _acquire_scope_locked(
        self,
        key: tuple[str, str],
        sandbox_id: str,
        *,
        thread_id: str,
        user_id: str | None,
    ) -> str:
        with self._lock:
            if not self._accepting or self._shutdown_called:
                raise RuntimeError("VeFaaSSandboxProvider has been shut down")
            if sandbox_id in self._local_teardown:
                raise RuntimeError(f"veFaaS sandbox {sandbox_id} is currently being torn down")
            existing_id = self._thread_sandboxes.get(key)
            active = self._sandboxes.get(existing_id) if existing_id is not None else None
            if active is not None:
                return active.sandbox_id
            self._acquire_inflight[sandbox_id] = self._acquire_inflight.get(sandbox_id, 0) + 1

        try:
            reclaimed = self._reclaim_warm_pool(sandbox_id, key=key, thread_id=thread_id, user_id=user_id)
            if reclaimed is not None:
                return reclaimed

            with self._lock:
                if not self._accepting or self._shutdown_called or sandbox_id in self._local_teardown:
                    raise RuntimeError("VeFaaSSandboxProvider shut down during acquire")

            # Fence any quarantined remote generations before creating or adopting a replacement.
            self._drain_quarantine_for_scope(sandbox_id)

            discovered = self._discover_existing_sandbox(sandbox_id, thread_id=thread_id, user_id=user_id)
            if discovered is not None:
                with self._lock:
                    if not self._accepting or self._shutdown_called or sandbox_id in self._local_teardown:
                        rollback = True
                    else:
                        self._sandboxes[sandbox_id] = discovered
                        self._thread_sandboxes[key] = sandbox_id
                        self._bump_acquire_epoch_locked(sandbox_id)
                        rollback = False
                if rollback:
                    discovered.sandbox.close()
                    raise RuntimeError("VeFaaSSandboxProvider shut down during acquire")
                return sandbox_id

            tracked = self._create_new_sandbox(sandbox_id, thread_id=thread_id, user_id=user_id)
            with self._lock:
                if not self._accepting or self._shutdown_called or sandbox_id in self._local_teardown:
                    self._pending_destroys[tracked.remote_sandbox_id] = tracked
                    rollback = True
                else:
                    self._sandboxes[sandbox_id] = tracked
                    self._thread_sandboxes[key] = sandbox_id
                    self._bump_acquire_epoch_locked(sandbox_id)
                    rollback = False
            if rollback:
                self._destroy_tracked(tracked, reason="created_during_shutdown", require_pending=True)
                raise RuntimeError("VeFaaSSandboxProvider shut down during acquire")
            return sandbox_id
        finally:
            with self._lock:
                remaining = self._acquire_inflight.get(sandbox_id, 1) - 1
                if remaining <= 0:
                    self._acquire_inflight.pop(sandbox_id, None)
                else:
                    self._acquire_inflight[sandbox_id] = remaining

    @staticmethod
    def _needs_warm_resume(record: VeFaaSSandboxRecord) -> bool:
        return record.is_paused or record.is_transitioning

    def _discard_absent_warm_entry(self, sandbox_id: str, tracked: _TrackedVeFaaSSandbox) -> None:
        """Drop a warm entry whose remote instance is authoritatively absent or terminal."""
        with self._lock:
            removed = self._warm_pool.pop(sandbox_id, None) if self._warm_pool.get(sandbox_id, (None, 0.0))[0] is tracked else None
        if removed is not None:
            removed[0].sandbox.close()
            self._release_ownership_best_effort(sandbox_id, context="absent warm sandbox")

    def _destroy_warm_on_reclaim(self, sandbox_id: str, tracked: _TrackedVeFaaSSandbox, *, reason: str) -> None:
        """Atomically move an unhealthy or unadoptable warm entry to pending destroys and tear it down."""
        with self._lock:
            removed = self._warm_pool.pop(sandbox_id, None) if self._warm_pool.get(sandbox_id, (None, 0.0))[0] is tracked else None
            if removed is not None:
                self._pending_destroys[removed[0].remote_sandbox_id] = removed[0]
        if removed is not None:
            self._destroy_tracked(removed[0], reason=reason, require_pending=True)

    def _reclaim_paused_warm_entry(
        self,
        sandbox_id: str,
        tracked: _TrackedVeFaaSSandbox,
        *,
        record: VeFaaSSandboxRecord,
        key: tuple[str, str],
        function_id: str,
        thread_id: str,
        user_id: str | None,
    ) -> str | None:
        """Resume and adopt a paused/transitioning warm entry while keeping it tracked.

        Keeps ``tracked`` in ``_warm_pool`` across all transient control-plane and
        readiness errors so a failed acquire never drops the cleanup record for an
        owned remote instance. Only removes ``tracked`` from ``_warm_pool`` once the
        remote instance is adopted, confirmed absent/terminal, confirmed under peer
        teardown, or moved atomically into ``_pending_destroys``.
        """
        remote_id = tracked.remote_sandbox_id
        logger.info(
            "Warm veFaaS sandbox %s (remote=%s) is %s; resuming tracked instance in place",
            sandbox_id,
            remote_id,
            record.status,
        )
        candidate: VeFaaSSandboxRecord | None = record
        if not candidate.is_paused and not candidate.is_running:
            candidate = self._wait_for_transition_settled(
                function_id,
                remote_id,
                deadline=time.monotonic() + self._config["ready_timeout"],
            )
            if candidate is None:
                self._discard_absent_warm_entry(sandbox_id, tracked)
                return None

        try:
            outcome, adopted = self._resume_and_adopt_paused_sandbox_outcome(
                sandbox_id,
                remote_id,
                function_id=function_id,
                thread_id=thread_id,
                user_id=user_id,
            )
        except _PeerTeardownError:
            with self._lock:
                removed = self._warm_pool.pop(sandbox_id, None) if self._warm_pool.get(sandbox_id, (None, 0.0))[0] is tracked else None
            if removed is not None:
                removed[0].sandbox.close()
            raise
        except Exception:
            # If initialization rollback already quarantined this generation under _pending_rollbacks,
            # drop the stale warm entry so a retry drains quarantine instead of reclaiming it.
            with self._lock:
                quarantined = remote_id in self._pending_rollbacks or remote_id in self._quarantined_remote_ids.get(sandbox_id, set())
                removed = self._warm_pool.pop(sandbox_id, None) if quarantined and self._warm_pool.get(sandbox_id, (None, 0.0))[0] is tracked else None
            if removed is not None:
                removed[0].sandbox.close()
            raise

        if outcome == "absent":
            self._discard_absent_warm_entry(sandbox_id, tracked)
            return None
        if outcome != "adopted" or adopted is None:
            self._destroy_warm_on_reclaim(sandbox_id, tracked, reason="warm_resume_unadoptable")
            return None

        with self._lock:
            removed = self._warm_pool.pop(sandbox_id, None) if self._warm_pool.get(sandbox_id, (None, 0.0))[0] is tracked else None
            if not self._accepting or self._shutdown_called or sandbox_id in self._local_teardown:
                self._pending_destroys.setdefault(adopted.remote_sandbox_id, adopted)
                rollback = True
            else:
                self._sandboxes[sandbox_id] = adopted
                self._thread_sandboxes[key] = sandbox_id
                self._bump_acquire_epoch_locked(sandbox_id)
                rollback = False
        if removed is not None:
            removed[0].sandbox.close()
        if rollback:
            self._destroy_tracked(adopted, reason="reclaimed_during_shutdown", require_pending=True)
            adopted.sandbox.close()
            raise RuntimeError("VeFaaSSandboxProvider shut down during acquire")
        logger.info("Reclaimed paused warm veFaaS sandbox %s (remote=%s)", sandbox_id, remote_id)
        return sandbox_id

    def _reclaim_warm_pool(
        self,
        sandbox_id: str,
        *,
        key: tuple[str, str],
        thread_id: str,
        user_id: str | None,
    ) -> str | None:
        with self._lock:
            if sandbox_id in self._local_teardown:
                raise RuntimeError(f"veFaaS sandbox {sandbox_id} is currently being torn down")
            warm_entry = self._warm_pool.get(sandbox_id)
            quarantined_tracked: _TrackedVeFaaSSandbox | None = None
            if warm_entry is not None:
                remote_id = warm_entry[0].remote_sandbox_id
                if remote_id in self._pending_rollbacks or remote_id in self._quarantined_remote_ids.get(sandbox_id, set()):
                    self._warm_pool.pop(sandbox_id, None)
                    quarantined_tracked = warm_entry[0]
                    warm_entry = None
        if quarantined_tracked is not None:
            quarantined_tracked.sandbox.close()
        if warm_entry is None:
            return None
        tracked = warm_entry[0]
        function_id, _ = self._require_provisioning_settings()
        if self._config["auto_pause"]:
            record = self._get_client().describe_sandbox(function_id, tracked.remote_sandbox_id)
            if record is None or record.is_terminal_failure:
                self._discard_absent_warm_entry(sandbox_id, tracked)
                return None
            if self._needs_warm_resume(record):
                return self._reclaim_paused_warm_entry(
                    sandbox_id,
                    tracked,
                    record=record,
                    key=key,
                    function_id=function_id,
                    thread_id=thread_id,
                    user_id=user_id,
                )
        url, headers = self._resolve_data_plane(tracked.remote_sandbox_id)
        healthy = wait_for_sandbox_ready(url, timeout=5, headers=headers)
        if not healthy:
            record = self._get_client().describe_sandbox(function_id, tracked.remote_sandbox_id)
            if record is None or record.is_terminal_failure:
                self._discard_absent_warm_entry(sandbox_id, tracked)
                return None
            if self._needs_warm_resume(record):
                return self._reclaim_paused_warm_entry(
                    sandbox_id,
                    tracked,
                    record=record,
                    key=key,
                    function_id=function_id,
                    thread_id=thread_id,
                    user_id=user_id,
                )
            self._destroy_warm_on_reclaim(sandbox_id, tracked, reason="warm_health_check_failed")
            return None

        if not self._ownership.take(sandbox_id):
            with self._lock:
                removed = self._warm_pool.pop(sandbox_id, None) if self._warm_pool.get(sandbox_id, (None, 0.0))[0] is tracked else None
            if removed is not None:
                removed[0].sandbox.close()
            raise _PeerTeardownError(f"veFaaS sandbox {sandbox_id} is currently being destroyed by a peer")

        try:
            self._get_client().set_sandbox_timeout(
                function_id,
                tracked.remote_sandbox_id,
                timeout_minutes=self._config["timeout_minutes"],
            )
        except Exception as exc:
            logger.warning("Failed to extend veFaaS timeout for %s on reclaim: %s", tracked.remote_sandbox_id, exc)

        with self._lock:
            removed = self._warm_pool.pop(sandbox_id, None) if self._warm_pool.get(sandbox_id, (None, 0.0))[0] is tracked else None
            if removed is None:
                if not self._accepting or self._shutdown_called or sandbox_id in self._local_teardown:
                    raise RuntimeError("VeFaaSSandboxProvider shut down during acquire")
                return None
            if not self._accepting or self._shutdown_called or sandbox_id in self._local_teardown:
                self._pending_destroys[removed[0].remote_sandbox_id] = removed[0]
                rollback = True
            else:
                self._sandboxes[sandbox_id] = removed[0]
                self._thread_sandboxes[key] = sandbox_id
                self._bump_acquire_epoch_locked(sandbox_id)
                rollback = False
        if rollback:
            self._destroy_tracked(removed[0], reason="reclaimed_during_shutdown", require_pending=True)
            raise RuntimeError("VeFaaSSandboxProvider shut down during acquire")
        logger.info("Reclaimed warm veFaaS sandbox %s (remote=%s)", sandbox_id, tracked.remote_sandbox_id)
        return sandbox_id

    @contextmanager
    def _remote_init_lock(self, remote_sandbox_id: str) -> Iterator[None]:
        """Serialize marker checks and initialization for the same remote instance in-process."""
        key = (str(self._config.get("endpoint") or ""), str(self._config.get("function_id") or ""), remote_sandbox_id)
        with _REMOTE_INIT_LOCKS_GUARD:
            lock, refs = _REMOTE_INIT_LOCKS.get(key, (threading.RLock(), 0))
            _REMOTE_INIT_LOCKS[key] = (lock, refs + 1)
        try:
            with lock:
                yield
        finally:
            with _REMOTE_INIT_LOCKS_GUARD:
                entry = _REMOTE_INIT_LOCKS.get(key)
                if entry is not None:
                    cur_lock, cur_refs = entry
                    if cur_refs <= 1:
                        _REMOTE_INIT_LOCKS.pop(key, None)
                    else:
                        _REMOTE_INIT_LOCKS[key] = (cur_lock, cur_refs - 1)

    @staticmethod
    def _write_init_marker(sandbox: AioSandbox, sandbox_id: str) -> None:
        """Persist an ephemeral marker proving DeerFlow finished sandbox initialization."""
        sandbox.update_file(_INIT_MARKER_PATH, f"{sandbox_id}\n".encode())

    @staticmethod
    def _probe_init_marker(sandbox: AioSandbox, sandbox_id: str) -> Literal["initialized", "missing", "invalid"]:
        """Check whether an existing remote instance completed DeerFlow initialization."""
        quoted_marker = shlex.quote(_INIT_MARKER_PATH)
        output = sandbox.execute_command(f"set +e; ( if [ -f {quoted_marker} ] && [ ! -L {quoted_marker} ]; then printf 'INIT_MARKER:%s\\n' \"$(cat {quoted_marker})\"; else echo 'INIT_MARKER:MISSING'; fi )")
        for line in output.splitlines():
            stripped = line.strip()
            if stripped == f"INIT_MARKER:{sandbox_id}":
                return "initialized"
            if stripped == "INIT_MARKER:MISSING":
                return "missing"
        return "invalid"

    def _initialize_remote_sandbox(
        self,
        sandbox: AioSandbox,
        *,
        sandbox_id: str,
        thread_id: str | None,
        user_id: str | None,
    ) -> None:
        """Create workspace directories, restore host thread files/skills, and write init marker."""
        bootstrap_output = sandbox.execute_command(_BOOTSTRAP_COMMAND)
        if not any(line.strip() == _BOOTSTRAP_OK_MARKER for line in bootstrap_output.splitlines()):
            raise RuntimeError(f"veFaaS sandbox bootstrap failed for {sandbox_id}: {bootstrap_output[:200]}")

        if thread_id is not None and user_id:
            if not self._uses_tos_for_user_data():
                self._restore_thread_files(sandbox, thread_id=thread_id, user_id=user_id)
            self._upload_shared_skills(sandbox, thread_id=thread_id, user_id=user_id)

        self._write_init_marker(sandbox, sandbox_id)

    def _release_ownership_best_effort(self, sandbox_id: str, *, context: str) -> None:
        try:
            self._ownership.release(sandbox_id)
        except OwnershipBackendError as rel_exc:
            logger.warning("Failed to release ownership (%s) for veFaaS sandbox %s: %s", context, sandbox_id, rel_exc)

    def _adopt_running_sandbox(
        self,
        sandbox_id: str,
        remote_id: str,
        *,
        function_id: str,
        thread_id: str,
        user_id: str | None,
        ownership_claimed: bool = False,
        refresh_timeout: bool = True,
    ) -> _TrackedVeFaaSSandbox | None:
        """Verify initialization state, claim/take ownership, and adopt a running instance."""
        sandbox = self._build_aio_sandbox(sandbox_id, remote_id)
        adopt_deadline = time.monotonic() + min(self._config["ready_timeout"], _ADOPT_INIT_WAIT_SECONDS)
        adopted = False
        while True:
            with self._remote_init_lock(remote_id):
                try:
                    init_state = self._probe_init_marker(sandbox, sandbox_id)
                except Exception as exc:
                    logger.warning("Failed to verify initialization state for veFaaS sandbox %s (remote=%s): %s", sandbox_id, remote_id, self._redact(exc))
                    if ownership_claimed:
                        self._release_ownership_best_effort(sandbox_id, context="failed probe")
                    break
                if init_state == "invalid":
                    logger.warning("Refusing to adopt veFaaS sandbox %s (remote=%s): invalid or mismatched initialization marker", sandbox_id, remote_id)
                    if ownership_claimed:
                        self._release_ownership_best_effort(sandbox_id, context="invalid marker")
                    break
                if init_state == "initialized":
                    if not ownership_claimed:
                        try:
                            taken = self._ownership.take(sandbox_id)
                        except OwnershipBackendError:
                            sandbox.close()
                            raise
                        if not taken:
                            sandbox.close()
                            raise _PeerTeardownError(f"veFaaS sandbox {sandbox_id} is being destroyed by a peer")
                    adopted = True
                    break

                # Marker is missing: only an exclusive claim (never a takeover from a live
                # peer) may initialize this remote instance, preventing a second worker from
                # restoring older host files over a peer's live workspace.
                if ownership_claimed:
                    claimed = True
                else:
                    try:
                        claimed = self._ownership.claim(sandbox_id)
                    except OwnershipBackendError:
                        sandbox.close()
                        raise
                if claimed:
                    if not ownership_claimed:
                        try:
                            init_state = self._probe_init_marker(sandbox, sandbox_id)
                        except Exception as exc:
                            logger.warning("Failed to re-verify initialization state for veFaaS sandbox %s (remote=%s): %s", sandbox_id, remote_id, self._redact(exc))
                            self._release_ownership_best_effort(sandbox_id, context="failed re-probe")
                            break
                        if init_state == "invalid":
                            logger.warning("Refusing to adopt veFaaS sandbox %s (remote=%s): invalid or mismatched initialization marker", sandbox_id, remote_id)
                            self._release_ownership_best_effort(sandbox_id, context="invalid marker after claim")
                            break
                    if init_state == "missing":
                        logger.info("Completing DeerFlow initialization before adopting veFaaS sandbox %s (remote=%s)", sandbox_id, remote_id)
                        try:
                            self._initialize_remote_sandbox(
                                sandbox,
                                sandbox_id=sandbox_id,
                                thread_id=thread_id,
                                user_id=user_id,
                            )
                        except Exception:
                            sandbox.close()
                            self._rollback_remote_sandbox(sandbox_id, remote_id, release_ownership=True)
                            raise
                    adopted = True
                    break

            # Outside _remote_init_lock: another live worker holds ownership while this
            # sandbox is still uninitialized. Wait briefly for it to publish the marker
            # or drop ownership instead of stealing and restoring over live files.
            remaining = adopt_deadline - time.monotonic()
            if remaining <= 0:
                sandbox.close()
                raise RuntimeError(f"Timed out waiting for peer to initialize veFaaS sandbox {sandbox_id} (remote={remote_id})")
            time.sleep(min(_ADOPT_INIT_POLL_INTERVAL_SECONDS, remaining))

        if not adopted:
            sandbox.close()
            return None
        if refresh_timeout:
            try:
                self._get_client().set_sandbox_timeout(
                    function_id,
                    remote_id,
                    timeout_minutes=self._config["timeout_minutes"],
                )
            except Exception as exc:
                logger.warning("Failed to refresh timeout on discovered veFaaS sandbox %s: %s", remote_id, exc)
        logger.info("Adopted existing veFaaS sandbox %s (remote=%s)", sandbox_id, remote_id)
        return _TrackedVeFaaSSandbox(
            sandbox_id=sandbox_id,
            remote_sandbox_id=remote_id,
            sandbox=sandbox,
            thread_id=thread_id,
            user_id=user_id,
        )

    def _wait_for_transition_settled(self, function_id: str, remote_sandbox_id: str, *, deadline: float) -> VeFaaSSandboxRecord | None:
        """Wait for a Pausing/Resuming/Snapshotting sandbox to reach Running, Paused, or absent."""
        client = self._get_client()
        while True:
            record = client.describe_sandbox(function_id, remote_sandbox_id)
            if record is None or record.is_terminal_failure:
                return None
            if record.is_running or record.is_paused:
                return record
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for veFaaS sandbox {remote_sandbox_id} to leave {record.status!r} state")
            time.sleep(min(_POLL_STATUS_INTERVAL_SECONDS, remaining))

    def _resume_and_adopt_paused_sandbox(
        self,
        sandbox_id: str,
        remote_id: str,
        *,
        function_id: str,
        thread_id: str,
        user_id: str | None,
    ) -> _TrackedVeFaaSSandbox | None:
        """Resume a paused veFaaS sandbox under exclusive ownership and adopt it."""
        _, tracked = self._resume_and_adopt_paused_sandbox_outcome(
            sandbox_id,
            remote_id,
            function_id=function_id,
            thread_id=thread_id,
            user_id=user_id,
        )
        return tracked

    def _resume_and_adopt_paused_sandbox_outcome(
        self,
        sandbox_id: str,
        remote_id: str,
        *,
        function_id: str,
        thread_id: str,
        user_id: str | None,
    ) -> tuple[Literal["adopted", "absent", "unadoptable"], _TrackedVeFaaSSandbox | None]:
        """Resume a paused veFaaS sandbox and classify absence vs. refusal to adopt."""
        client = self._get_client()
        resume_deadline = time.monotonic() + self._config["ready_timeout"]

        while True:
            already_running = False
            with self._remote_init_lock(remote_id):
                current = client.describe_sandbox(function_id, remote_id)
                if current is None or current.is_terminal_failure:
                    return "absent", None
                if current.is_running:
                    already_running = True
                elif current.is_paused:
                    taken = self._ownership.take(sandbox_id)
                    if not taken:
                        raise _PeerTeardownError(f"veFaaS sandbox {sandbox_id} is being destroyed by a peer")
                    lease_held = True
                    try:
                        lease_lost = False
                        resumed_by_us = False
                        with self._ownership_lease_heartbeat(sandbox_id) as heartbeat:

                            def _refresh_resume_lease() -> bool:
                                if heartbeat["lost"]:
                                    return False
                                if not self._refresh_owned_lease(sandbox_id):
                                    heartbeat["lost"] = True
                                    return False
                                return True

                            refreshed = client.describe_sandbox(function_id, remote_id)
                            if refreshed is None or refreshed.is_terminal_failure:
                                return "absent", None
                            if refreshed.is_paused:
                                try:
                                    client.resume_sandbox(
                                        function_id,
                                        remote_id,
                                        timeout_minutes=self._config["timeout_minutes"],
                                    )
                                    resumed_by_us = True
                                except VeFaaSSandboxNotFoundError:
                                    return "absent", None
                            running = self._wait_for_remote_running(
                                function_id,
                                remote_id,
                                deadline=resume_deadline,
                                refresh_lease=_refresh_resume_lease,
                            )
                            if running is None:
                                lease_lost = True
                            else:
                                url, headers = self._resolve_data_plane(remote_id)
                                remaining = max(1, int(math.ceil(resume_deadline - time.monotonic())))
                                if not wait_for_sandbox_ready(url, timeout=remaining, headers=headers):
                                    if heartbeat["lost"]:
                                        lease_lost = True
                                    else:
                                        raise TimeoutError(f"Resumed veFaaS sandbox {remote_id} did not become HTTP-ready within {self._config['ready_timeout']}s")

                        if lease_lost or heartbeat["lost"] or not self._verify_owned_lease_strict(sandbox_id):
                            lease_held = False
                            post = client.describe_sandbox(function_id, remote_id)
                            if post is None or post.is_terminal_failure:
                                return "absent", None
                            if post.is_running:
                                already_running = True
                            else:
                                raise _PeerTeardownError(f"Lost ownership lease while resuming veFaaS sandbox {sandbox_id} (remote={remote_id})")
                        else:
                            # Hand ownership lifecycle to _adopt_running_sandbox from this point on.
                            lease_held = False
                            tracked = self._adopt_running_sandbox(
                                sandbox_id,
                                remote_id,
                                function_id=function_id,
                                thread_id=thread_id,
                                user_id=user_id,
                                ownership_claimed=True,
                                refresh_timeout=not resumed_by_us,
                            )
                            if tracked is not None:
                                logger.info("Resumed paused veFaaS sandbox %s (remote=%s)", sandbox_id, remote_id)
                                return "adopted", tracked
                            return "unadoptable", None
                    finally:
                        if lease_held:
                            self._release_ownership_best_effort(sandbox_id, context="failed resume")

            if already_running:
                url, headers = self._resolve_data_plane(remote_id)
                remaining = max(1, int(math.ceil(resume_deadline - time.monotonic())))
                if not wait_for_sandbox_ready(url, timeout=remaining, headers=headers):
                    raise TimeoutError(f"veFaaS sandbox {remote_id} did not become HTTP-ready within {self._config['ready_timeout']}s")
                adopted = self._adopt_running_sandbox(
                    sandbox_id,
                    remote_id,
                    function_id=function_id,
                    thread_id=thread_id,
                    user_id=user_id,
                    ownership_claimed=False,
                    refresh_timeout=True,
                )
                if adopted is not None:
                    return "adopted", adopted
                return "unadoptable", None

            remaining = resume_deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting to resume veFaaS sandbox {sandbox_id} (remote={remote_id})")
            time.sleep(min(_ADOPT_INIT_POLL_INTERVAL_SECONDS, remaining))

    def _discover_existing_sandbox(
        self,
        sandbox_id: str,
        *,
        thread_id: str,
        user_id: str | None,
    ) -> _TrackedVeFaaSSandbox | None:
        function_id, _ = self._require_provisioning_settings()
        client = self._get_client()
        expected_metadata = {
            META_KEY_PROVIDER: META_VAL_PROVIDER,
            META_KEY_SANDBOX_ID: sandbox_id,
        }
        records = client.list_sandboxes(function_id, metadata=expected_metadata)
        with self._lock:
            quarantined = set(self._quarantined_remote_ids.get(sandbox_id, set()))

        running: list[VeFaaSSandboxRecord] = []
        paused: list[VeFaaSSandboxRecord] = []
        transitioning: list[VeFaaSSandboxRecord] = []
        for record in records:
            if record.id in quarantined or record.is_terminal_failure:
                continue
            if any(record.metadata.get(k) != v for k, v in expected_metadata.items()):
                continue
            if record.is_running:
                running.append(record)
            elif record.is_paused:
                paused.append(record)
            elif record.status.strip().lower() in _DISCOVER_TRANSITION_STATUSES:
                transitioning.append(record)

        for record in running + paused + transitioning:
            candidate = record
            if candidate.status.strip().lower() in _DISCOVER_TRANSITION_STATUSES:
                settled = self._wait_for_transition_settled(
                    function_id,
                    candidate.id,
                    deadline=time.monotonic() + self._config["ready_timeout"],
                )
                if settled is None:
                    continue
                candidate = settled

            if candidate.is_paused:
                resumed = self._resume_and_adopt_paused_sandbox(
                    sandbox_id,
                    candidate.id,
                    function_id=function_id,
                    thread_id=thread_id,
                    user_id=user_id,
                )
                if resumed is not None:
                    return resumed
                continue

            if not candidate.is_running:
                continue
            url, headers = self._resolve_data_plane(candidate.id)
            if not wait_for_sandbox_ready(url, timeout=5, headers=headers):
                continue
            adopted = self._adopt_running_sandbox(
                sandbox_id,
                candidate.id,
                function_id=function_id,
                thread_id=thread_id,
                user_id=user_id,
                ownership_claimed=False,
                refresh_timeout=True,
            )
            if adopted is not None:
                return adopted
        return None

    def _wait_for_remote_running(
        self,
        function_id: str,
        remote_sandbox_id: str,
        *,
        deadline: float,
        refresh_lease: Callable[[], bool] | None = None,
    ) -> VeFaaSSandboxRecord | None:
        client = self._get_client()
        while True:
            if refresh_lease is not None and not refresh_lease():
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for veFaaS sandbox {remote_sandbox_id} to reach Running state")
            record = client.describe_sandbox(function_id, remote_sandbox_id)
            if record is None:
                raise RuntimeError(f"veFaaS sandbox {remote_sandbox_id} disappeared before becoming ready")
            if record.is_running:
                return record
            if record.is_terminal_failure:
                detail = record.error_message or record.error_code or record.status
                raise RuntimeError(f"veFaaS sandbox {remote_sandbox_id} entered terminal state {record.status!r}: {detail}")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for veFaaS sandbox {remote_sandbox_id} to reach Running state")
            time.sleep(min(_POLL_STATUS_INTERVAL_SECONDS, remaining))

    def _scoped_metadata(self, sandbox_id: str) -> dict[str, str]:
        metadata = dict(self._config["metadata"])
        metadata[META_KEY_PROVIDER] = META_VAL_PROVIDER
        metadata[META_KEY_SANDBOX_ID] = sandbox_id
        return metadata

    def _list_scoped_snapshots(
        self,
        function_id: str,
        sandbox_id: str | None = None,
        *,
        status: str | None = None,
    ) -> list[VeFaaSSnapshotRecord]:
        """List snapshots for ``function_id`` using server-side filters with strict client verification."""
        client = self._get_client()
        use_meta_filters = self._snapshot_metadata_filter_supported
        use_status_filter = status is not None and self._snapshot_status_filter_supported

        def _build_filters(*, include_meta: bool, include_status: bool) -> list[dict[str, Any]] | None:
            items: list[dict[str, Any]] = []
            if include_meta:
                items.append({"Name": f"Metadata.{META_KEY_PROVIDER}", "Values": [META_VAL_PROVIDER]})
                if sandbox_id is not None:
                    items.append({"Name": f"Metadata.{META_KEY_SANDBOX_ID}", "Values": [sandbox_id]})
            if include_status and status is not None:
                items.append({"Name": "Status", "Values": [status]})
            return items or None

        filters = _build_filters(include_meta=use_meta_filters, include_status=use_status_filter)
        try:
            snapshots = client.list_sandbox_snapshots(function_id, filters=filters)
        except VeFaaSApiError as exc:
            if exc.status_code != 400 or not filters:
                raise
            if use_meta_filters:
                logger.warning(
                    "veFaaS ListSandboxSnapshots rejected Metadata filters for %s; falling back without metadata filters: %s",
                    function_id,
                    self._redact(exc),
                )
                self._snapshot_metadata_filter_supported = False
                fallback_filters = _build_filters(include_meta=False, include_status=use_status_filter)
                try:
                    snapshots = client.list_sandbox_snapshots(function_id, filters=fallback_filters)
                except VeFaaSApiError as status_exc:
                    if status_exc.status_code != 400 or not fallback_filters:
                        raise
                    logger.warning(
                        "veFaaS ListSandboxSnapshots rejected Status filter for %s; falling back to unfiltered listing: %s",
                        function_id,
                        self._redact(status_exc),
                    )
                    self._snapshot_status_filter_supported = False
                    snapshots = client.list_sandbox_snapshots(function_id)
            else:
                logger.warning(
                    "veFaaS ListSandboxSnapshots rejected Status filter for %s; falling back to unfiltered listing: %s",
                    function_id,
                    self._redact(exc),
                )
                self._snapshot_status_filter_supported = False
                snapshots = client.list_sandbox_snapshots(function_id)

        wanted_status = status.strip().lower() if status is not None else None
        return [
            snap
            for snap in snapshots
            if snap.metadata.get(META_KEY_PROVIDER) == META_VAL_PROVIDER
            and (sandbox_id is None or snap.metadata.get(META_KEY_SANDBOX_ID) == sandbox_id)
            and (wanted_status is None or (snap.is_ready if wanted_status == "ready" else snap.status.strip().lower() == wanted_status))
        ]

    def _find_latest_ready_snapshot(self, function_id: str, sandbox_id: str) -> str | None:
        """Return the newest Ready snapshot strictly matching ``sandbox_id``'s scope metadata."""
        matching = self._list_scoped_snapshots(function_id, sandbox_id, status="Ready")
        if not matching:
            return None
        matching.sort(key=_snapshot_sort_key, reverse=True)
        return matching[0].id

    def _create_new_sandbox(
        self,
        sandbox_id: str,
        *,
        thread_id: str | None,
        user_id: str | None,
    ) -> _TrackedVeFaaSSandbox:
        function_id, _ = self._require_provisioning_settings()
        replicas, total = self._replica_count()
        if total >= replicas:
            evicted = self._evict_oldest_warm()
            self._log_replicas_soft_cap(replicas, sandbox_id, evicted)

        client = self._get_client()
        metadata = self._scoped_metadata(sandbox_id)

        image_info: dict[str, Any] | None = None
        if self._config["image"] or self._config["port"]:
            image_info = {}
            if self._config["image"]:
                image_info["Image"] = self._config["image"]
            if self._config["port"]:
                image_info["Port"] = self._config["port"]

        tos_mount_config = self._build_tos_mount_config(sandbox_id)
        auto_pause_config: dict[str, Any] | None = None
        if self._config["auto_pause"]:
            auto_pause_config = {
                "Enable": True,
                "SnapshotType": self._config["snapshot_type"],
            }

        resolved_snapshot_id: str | None = None
        using_thread_snapshot = False
        if thread_id is not None and self._config["snapshot_on_idle"]:
            resolved_snapshot_id = self._find_latest_ready_snapshot(function_id, sandbox_id)
            using_thread_snapshot = resolved_snapshot_id is not None
        if resolved_snapshot_id is None:
            resolved_snapshot_id = self._config["snapshot_id"]

        create_kwargs: dict[str, Any] = {
            "cpu_milli": self._config["cpu_milli"],
            "memory_mb": self._config["memory_mb"],
            "timeout_minutes": self._config["timeout_minutes"],
            "metadata": metadata,
            "envs": self._config["environment"] or None,
            "instance_image_info": image_info,
            "instance_tos_mount_config": tos_mount_config,
            "session_id": sandbox_id,
            "auto_pause_config": auto_pause_config,
        }
        booted_from_snapshot = resolved_snapshot_id is not None
        try:
            remote_sandbox_id = client.create_sandbox(
                function_id,
                snapshot_id=resolved_snapshot_id,
                **create_kwargs,
            )
        except VeFaaSSnapshotNotFoundError:
            if not using_thread_snapshot:
                raise
            logger.warning(
                "Auto-discovered veFaaS snapshot %s for %s disappeared before CreateSandbox; falling back to base snapshot/image",
                resolved_snapshot_id,
                sandbox_id,
            )
            fallback_snapshot_id = self._config["snapshot_id"]
            booted_from_snapshot = fallback_snapshot_id is not None
            remote_sandbox_id = client.create_sandbox(
                function_id,
                snapshot_id=fallback_snapshot_id,
                **create_kwargs,
            )

        sandbox: AioSandbox | None = None
        ownership_taken = False
        try:
            # Publish ownership immediately after CreateSandbox (while the instance is
            # still starting up) so a concurrent peer cannot claim and initialize it
            # before this worker finishes bootstrapping.
            if not self._ownership.take(sandbox_id):
                raise RuntimeError(f"Refused to hand out veFaaS sandbox {sandbox_id}: peer holds teardown lease")
            ownership_taken = True

            deadline = time.monotonic() + self._config["ready_timeout"]
            self._wait_for_remote_running(function_id, remote_sandbox_id, deadline=deadline)

            url, headers = self._resolve_data_plane(remote_sandbox_id)
            remaining = max(1, int(math.ceil(deadline - time.monotonic())))
            if not wait_for_sandbox_ready(url, timeout=remaining, headers=headers):
                raise TimeoutError(f"veFaaS sandbox {remote_sandbox_id} did not become HTTP-ready within {self._config['ready_timeout']}s")

            with self._remote_init_lock(remote_sandbox_id):
                sandbox = self._build_aio_sandbox(sandbox_id, remote_sandbox_id)
                init_state = self._probe_init_marker(sandbox, sandbox_id)
                if init_state == "invalid":
                    raise RuntimeError(f"Refused to hand out veFaaS sandbox {sandbox_id}: invalid initialization marker")
                if init_state == "missing":
                    self._initialize_remote_sandbox(
                        sandbox,
                        sandbox_id=sandbox_id,
                        thread_id=thread_id,
                        user_id=user_id,
                    )
                elif booted_from_snapshot and thread_id is not None and user_id:
                    # A restored disk/full snapshot may preserve /tmp/.deerflow-vefaas-initialized.
                    # Keep the snapshot's workspace/outputs intact while syncing newer host uploads
                    # and refreshing shared skills so post-snapshot host changes take effect.
                    if not self._uses_tos_for_user_data():
                        self._restore_thread_uploads(sandbox, thread_id=thread_id, user_id=user_id)
                    self._upload_shared_skills(sandbox, thread_id=thread_id, user_id=user_id)

            return _TrackedVeFaaSSandbox(
                sandbox_id=sandbox_id,
                remote_sandbox_id=remote_sandbox_id,
                sandbox=sandbox,
                thread_id=thread_id,
                user_id=user_id,
            )
        except Exception:
            if sandbox is not None:
                sandbox.close()
            self._rollback_remote_sandbox(sandbox_id, remote_sandbox_id, release_ownership=ownership_taken)
            raise

    def _rollback_remote_sandbox(self, sandbox_id: str, remote_sandbox_id: str, *, release_ownership: bool) -> None:
        entry = _PendingRollback(
            sandbox_id=sandbox_id,
            remote_sandbox_id=remote_sandbox_id,
            release_ownership=release_ownership,
        )
        self._cleanup_rollback(entry, reason="rollback")

    def _cleanup_rollback(self, entry: _PendingRollback, *, reason: str, require_pending: bool = False) -> bool:
        """Kill and confirm absence of a failed provisioning generation.

        Returns ``True`` only once the remote instance is authoritatively absent
        (and any owned lease released). Failed rollbacks remain queued in
        ``_pending_rollbacks`` and ``_quarantined_remote_ids`` so background
        retries and ``shutdown()`` keep retrying until deletion is confirmed.
        """
        sandbox_id = entry.sandbox_id
        remote_id = entry.remote_sandbox_id
        with self._lock:
            if require_pending and self._pending_rollbacks.get(remote_id) is not entry:
                return False
            self._pending_rollbacks[remote_id] = entry
            if remote_id in self._destroying_remote_ids:
                return False
            self._destroying_remote_ids.add(remote_id)

        confirmed = False
        try:
            function_id = self._config["function_id"]
            self._get_client().kill_sandbox(function_id, remote_id)
            if self._confirm_remote_absent(function_id, remote_id):
                confirmed = True
            else:
                logger.warning(
                    "veFaaS rollback sandbox %s (remote=%s) still present after KillSandbox (%s); keeping quarantine fence",
                    sandbox_id,
                    remote_id,
                    reason,
                )
        except Exception as exc:
            logger.warning(
                "Failed to roll back veFaaS sandbox %s (remote=%s, %s): %s",
                sandbox_id,
                remote_id,
                reason,
                self._redact(exc),
            )
        finally:
            if confirmed and entry.release_ownership:
                try:
                    self._ownership.release(sandbox_id)
                except OwnershipBackendError as exc:
                    logger.warning("Failed to release ownership after veFaaS rollback for %s: %s", sandbox_id, exc)
                    confirmed = False
            with self._lock:
                self._destroying_remote_ids.discard(remote_id)
                if confirmed:
                    self._pending_rollbacks.pop(remote_id, None)
                    bucket = self._quarantined_remote_ids.get(sandbox_id)
                    if bucket is not None:
                        bucket.discard(remote_id)
                        if not bucket:
                            self._quarantined_remote_ids.pop(sandbox_id, None)
                else:
                    self._quarantined_remote_ids.setdefault(sandbox_id, set()).add(remote_id)
        return confirmed

    def _redact(self, value: object) -> str:
        text = redact_secret(value, self._config.get("secret_key"))
        text = redact_secret(text, self._config.get("access_key"))
        text = redact_secret(text, self._config.get("session_token"))
        text = redact_secret(text, self._config.get("sandbox_access_token"))
        return text

    # ── Quarantine & authoritative teardown ──────────────────────────────

    def _confirm_remote_absent(self, function_id: str, remote_sandbox_id: str) -> bool:
        """Confirm absence authoritatively via ``DescribeSandbox`` (API errors raise)."""
        record = self._get_client().describe_sandbox(function_id, remote_sandbox_id)
        if record is None:
            return True
        return record.is_terminal_failure

    @staticmethod
    def _snapshot_fence_key(remote_id: str) -> str:
        """Cross-worker ownership store key fencing teardowns while manual snapshots settle."""
        return f"snapshot-fence:{remote_id}"

    @staticmethod
    def _is_uncertain_snapshot_submit_error(exc: Exception) -> bool:
        """Return True when ``CreateSandboxSnapshot`` may have been accepted despite raising."""
        if isinstance(exc, VeFaaSApiError):
            # Definitive 4xx API errors (including SandboxNotFound) prove rejection.
            # Transport/timeout errors (status_code=None), malformed 2xx replies, and 5xx
            # responses leave submission state uncertain.
            return exc.status_code is None or exc.status_code >= 500 or exc.status_code < 400
        return isinstance(exc, (TimeoutError, ConnectionError, OSError))

    @contextmanager
    def _snapshot_fence_lock(self, remote_id: str) -> Iterator[None]:
        """Serialize cross-worker snapshot fence reservation with last-key deletion per remote."""
        with self._lock:
            lock, refs = self._snapshot_fence_locks.get(remote_id, (threading.Lock(), 0))
            self._snapshot_fence_locks[remote_id] = (lock, refs + 1)
        try:
            with lock:
                yield
        finally:
            with self._lock:
                current = self._snapshot_fence_locks.get(remote_id)
                if current is not None:
                    cur_lock, cur_refs = current
                    if cur_refs <= 1:
                        self._snapshot_fence_locks.pop(remote_id, None)
                    else:
                        self._snapshot_fence_locks[remote_id] = (cur_lock, cur_refs - 1)

    def _refresh_snapshot_fence(self, remote_id: str) -> bool:
        """Best-effort refresh of our cross-worker snapshot fence for ``remote_id``."""
        try:
            return self._ownership.claim(self._snapshot_fence_key(remote_id), for_destroy=True)
        except OwnershipBackendError as exc:
            logger.warning("Failed to refresh cross-worker snapshot fence for veFaaS remote %s: %s", remote_id, exc)
            return True

    def _is_remote_snapshot_fenced(self, remote_id: str) -> bool:
        """Return True if any worker holds a snapshot reservation for ``remote_id`` (fail closed)."""
        with self._lock:
            if remote_id in self._snapshotting_remote_ids:
                return True
        try:
            owner = self._ownership.owner(self._snapshot_fence_key(remote_id))
            return isinstance(owner, str) and bool(owner)
        except OwnershipBackendError as exc:
            logger.warning(
                "Failed to check cross-worker snapshot fence for veFaaS remote %s; deferring teardown: %s",
                remote_id,
                exc,
            )
            return True

    def _may_own_for_teardown(self, sandbox_id: str) -> bool:
        """Return True if this worker might still be responsible for tearing down ``sandbox_id``."""
        try:
            current_owner = self._ownership.owner(sandbox_id)
        except OwnershipBackendError:
            return True
        return current_owner is None or current_owner == self._ownership.owner_id

    def _restore_deferred_teardown_lease(self, sandbox_id: str, *, context: str) -> None:
        """Unwind our destructive ``del:`` claim and best-effort restore ``own:`` when teardown defers."""
        self._release_ownership_best_effort(sandbox_id, context=context)
        try:
            self._ownership.claim(sandbox_id)
        except OwnershipBackendError as exc:
            logger.warning("Failed to restore ownership lease (%s) for veFaaS sandbox %s: %s", context, sandbox_id, exc)

    def _refresh_owned_lease(self, sandbox_id: str) -> bool:
        """Refresh our normal ``own:`` lease; return False if a peer took or started destroying it."""
        try:
            outcome = self._ownership.renew(sandbox_id)
        except OwnershipBackendError as exc:
            logger.warning("Failed to refresh ownership lease for veFaaS sandbox %s: %s", sandbox_id, exc)
            return True
        if outcome is RenewOutcome.RENEWED:
            return True
        if outcome is RenewOutcome.LAPSED:
            try:
                return self._ownership.claim(sandbox_id)
            except OwnershipBackendError as exc:
                logger.warning("Failed to re-claim lapsed ownership lease for veFaaS sandbox %s: %s", sandbox_id, exc)
                return True
        return False

    def _verify_owned_lease_strict(self, sandbox_id: str) -> bool:
        """Authoritatively confirm we still hold ``own:`` for ``sandbox_id`` (fail closed on backend errors)."""
        outcome = self._ownership.renew(sandbox_id)
        if outcome is RenewOutcome.RENEWED:
            return True
        if outcome is RenewOutcome.LAPSED:
            return self._ownership.claim(sandbox_id)
        return False

    @contextmanager
    def _ownership_lease_heartbeat(self, sandbox_id: str) -> Iterator[dict[str, bool]]:
        """Keep ``sandbox_id``'s normal ownership lease alive across long resume/readiness waits."""
        state = {"lost": False}
        stop = threading.Event()
        interval = self._ownership_config.renewal_interval_seconds

        def _beat() -> None:
            while not stop.wait(interval):
                try:
                    if not self._refresh_owned_lease(sandbox_id):
                        state["lost"] = True
                        logger.warning("Lost ownership lease for veFaaS sandbox %s during resume", sandbox_id)
                        return
                except Exception as exc:
                    logger.warning("Failed to refresh ownership lease for veFaaS sandbox %s: %s", sandbox_id, self._redact(exc))

        thread: threading.Thread | None = None
        if interval > 0:
            thread = threading.Thread(
                target=_beat,
                name="vefaas-sandbox-resume-lease",
                daemon=True,
            )
            thread.start()
        try:
            yield state
        finally:
            stop.set()
            if thread is not None and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=5)
                if thread.is_alive():
                    logger.warning("veFaaS resume lease heartbeat for %s did not exit within 5s", sandbox_id)

    @contextmanager
    def _teardown_lease_heartbeat(self, sandbox_id: str) -> Iterator[dict[str, bool]]:
        """Keep ``sandbox_id``'s destructive teardown lease alive across long retirements."""
        state = {"lost": False, "exited": True}
        stop = threading.Event()
        interval = self._ownership_config.renewal_interval_seconds

        def _beat() -> None:
            while not stop.wait(interval):
                try:
                    if not self._ownership.claim(sandbox_id, for_destroy=True):
                        state["lost"] = True
                        logger.warning("Lost destructive teardown lease for veFaaS sandbox %s during retirement", sandbox_id)
                        return
                except Exception as exc:
                    logger.warning("Failed to refresh destructive teardown lease for veFaaS sandbox %s: %s", sandbox_id, self._redact(exc))

        thread: threading.Thread | None = None
        if interval > 0:
            thread = threading.Thread(
                target=_beat,
                name="vefaas-sandbox-teardown-lease",
                daemon=True,
            )
            thread.start()
        try:
            yield state
        finally:
            stop.set()
            if thread is not None and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=5)
                if thread.is_alive():
                    state["exited"] = False
                    logger.warning("veFaaS teardown lease heartbeat for %s did not exit within 5s", sandbox_id)

    def _confirm_remote_paused(
        self,
        function_id: str,
        remote_sandbox_id: str,
        *,
        deadline: float,
        refresh_lease: Callable[[], bool] | None = None,
    ) -> Literal["paused", "absent", "failed", "lost"]:
        """Poll ``DescribeSandbox`` until the instance confirms Paused, absent, failed, or lost."""
        client = self._get_client()
        while True:
            if refresh_lease is not None and not refresh_lease():
                return "lost"
            record = client.describe_sandbox(function_id, remote_sandbox_id)
            if record is None or record.is_terminal_failure:
                return "absent"
            if record.is_paused:
                return "paused"
            status_lower = record.status.strip().lower()
            if status_lower != "pausing" and not record.pending:
                return "failed"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "failed"
            time.sleep(min(_POLL_STATUS_INTERVAL_SECONDS, remaining))

    def _wait_for_snapshot_ready(
        self,
        function_id: str,
        snapshot_id: str,
        *,
        deadline: float,
        refresh_lease: Callable[[], bool] | None = None,
    ) -> VeFaaSSnapshotRecord:
        """Poll ``DescribeSandboxSnapshot`` until the snapshot is Ready or terminates."""
        client = self._get_client()
        while True:
            if refresh_lease is not None and not refresh_lease():
                raise RuntimeError(f"Lost teardown lease while waiting for veFaaS snapshot {snapshot_id}")
            record = client.describe_sandbox_snapshot(function_id, snapshot_id)
            if record is None:
                raise _VeFaaSSnapshotSettledFailureError(f"veFaaS snapshot {snapshot_id} disappeared before becoming ready")
            if record.is_ready:
                return record
            if record.is_terminal_failure:
                raise _VeFaaSSnapshotSettledFailureError(f"veFaaS snapshot {snapshot_id} entered terminal state {record.status!r}")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for veFaaS snapshot {snapshot_id} to become Ready")
            time.sleep(min(_POLL_STATUS_INTERVAL_SECONDS, remaining))

    def _prune_old_snapshots(
        self,
        function_id: str,
        sandbox_id: str,
        *,
        keep: int,
        refresh_lease: Callable[[], bool] | None = None,
    ) -> None:
        """Best-effort pruning of older ready snapshots belonging strictly to ``sandbox_id``."""
        if keep <= 0:
            return
        client = self._get_client()
        try:
            matching = self._list_scoped_snapshots(function_id, sandbox_id, status="Ready")
        except Exception as exc:
            logger.warning("Failed to list veFaaS snapshots for pruning %s: %s", sandbox_id, self._redact(exc))
            return
        if len(matching) <= keep:
            return
        matching.sort(key=_snapshot_sort_key, reverse=True)
        for stale in matching[keep:]:
            if refresh_lease is not None and not refresh_lease():
                return
            try:
                client.delete_sandbox_snapshot(function_id, stale.id)
            except Exception as exc:
                logger.warning("Failed to prune old veFaaS snapshot %s for %s: %s", stale.id, sandbox_id, self._redact(exc))

    def _snapshot_before_destroy(
        self,
        function_id: str,
        *,
        sandbox_id: str,
        remote_id: str,
        reason: str,
        refresh_lease: Callable[[], bool] | None = None,
    ) -> None:
        """Best-effort scoped snapshot before destroying an idle sandbox."""
        client = self._get_client()
        try:
            snapshot_id = client.create_sandbox_snapshot(
                function_id,
                remote_id,
                snapshot_type=self._config["snapshot_type"],
                retention_days=self._config["snapshot_retention_days"],
                metadata=self._scoped_metadata(sandbox_id),
            )
            self._wait_for_snapshot_ready(
                function_id,
                snapshot_id,
                deadline=time.monotonic() + self._config["snapshot_timeout"],
                refresh_lease=refresh_lease,
            )
            logger.info("Captured idle snapshot %s for veFaaS sandbox %s (remote=%s, %s)", snapshot_id, sandbox_id, remote_id, reason)
            self._prune_old_snapshots(
                function_id,
                sandbox_id,
                keep=self._config["max_snapshots_per_sandbox"],
                refresh_lease=refresh_lease,
            )
        except Exception as exc:
            logger.warning(
                "Failed to capture idle snapshot for veFaaS sandbox %s (remote=%s, %s); continuing teardown: %s",
                sandbox_id,
                remote_id,
                reason,
                self._redact(exc),
            )

    def _retire_warm_entry(
        self,
        tracked: _TrackedVeFaaSSandbox,
        *,
        reason: str,
        still_reapable: Callable[[], bool],
        pause: bool,
        snapshot: bool,
    ) -> bool:
        """Pause or snapshot-then-destroy an idle warm sandbox under full teardown fencing."""
        remote_id = tracked.remote_sandbox_id
        sandbox_id = tracked.sandbox_id
        if self._is_remote_snapshot_fenced(remote_id):
            return False
        with self._lock:
            if self._shutdown_called or not self._accepting:
                shutdown_active = True
            else:
                shutdown_active = False
                if sandbox_id in self._local_teardown or not still_reapable():
                    return False
                if remote_id in self._destroying_remote_ids or remote_id in self._mirroring_output_ids or remote_id in self._snapshotting_remote_ids:
                    return False
                self._local_teardown[sandbox_id] = self._local_teardown.get(sandbox_id, 0) + 1
                self._destroying_remote_ids.add(remote_id)
                self._pending_destroys[remote_id] = tracked
        if shutdown_active:
            return self._destroy_tracked(tracked, reason=reason, still_reapable=still_reapable, pop_warm=True)

        confirmed = False
        release_lease = False
        deferred_by_snapshot = False
        handle_closed = False
        try:
            claimed = self._ownership.claim(sandbox_id, for_destroy=True)
            if not claimed:
                logger.info("Skipping remote retirement for veFaaS sandbox %s (%s): owned by a peer", sandbox_id, reason)
                confirmed = True
            elif self._is_remote_snapshot_fenced(remote_id):
                logger.info("Deferring remote retirement for veFaaS sandbox %s (remote=%s, %s): snapshot fence active", sandbox_id, remote_id, reason)
                deferred_by_snapshot = True
                self._restore_deferred_teardown_lease(sandbox_id, context="deferred warm retirement")
            else:
                tracked.sandbox.close()
                handle_closed = True
                release_lease = True
                needs_kill = True
                function_id = self._config["function_id"]
                client = self._get_client()
                with self._teardown_lease_heartbeat(sandbox_id) as heartbeat:

                    def _refresh_teardown_lease() -> bool:
                        if heartbeat["lost"]:
                            return False
                        try:
                            if not self._ownership.claim(sandbox_id, for_destroy=True):
                                heartbeat["lost"] = True
                                return False
                            return True
                        except OwnershipBackendError as exc:
                            logger.warning("Failed to refresh destructive teardown lease for veFaaS sandbox %s: %s", sandbox_id, exc)
                            return True

                    if pause:
                        try:
                            client.pause_sandbox(function_id, remote_id)
                            pause_state = self._confirm_remote_paused(
                                function_id,
                                remote_id,
                                deadline=time.monotonic() + self._config["ready_timeout"],
                                refresh_lease=_refresh_teardown_lease,
                            )
                            if pause_state == "lost":
                                logger.warning("Skipping remote kill for veFaaS sandbox %s (remote=%s, %s): teardown lease lost during pause", sandbox_id, remote_id, reason)
                                confirmed = True
                                needs_kill = False
                                release_lease = False
                            elif pause_state in {"paused", "absent"}:
                                confirmed = True
                                needs_kill = False
                                if pause_state == "paused":
                                    logger.info("Paused idle veFaaS sandbox %s (remote=%s, %s)", sandbox_id, remote_id, reason)
                            else:
                                logger.warning(
                                    "veFaaS sandbox %s (remote=%s) did not reach Paused state (%s); falling back to KillSandbox",
                                    sandbox_id,
                                    remote_id,
                                    reason,
                                )
                        except VeFaaSSandboxNotFoundError:
                            confirmed = True
                            needs_kill = False
                        except Exception as exc:
                            logger.warning(
                                "Failed to pause idle veFaaS sandbox %s (remote=%s, %s); falling back to KillSandbox: %s",
                                sandbox_id,
                                remote_id,
                                reason,
                                self._redact(exc),
                            )

                    if needs_kill and snapshot:
                        self._snapshot_before_destroy(
                            function_id,
                            sandbox_id=sandbox_id,
                            remote_id=remote_id,
                            reason=reason,
                            refresh_lease=_refresh_teardown_lease,
                        )

                    if needs_kill:
                        if heartbeat["lost"] or not self._ownership.claim(sandbox_id, for_destroy=True):
                            logger.warning(
                                "Skipping remote kill for veFaaS sandbox %s (remote=%s, %s): teardown lease lost to a peer during retirement",
                                sandbox_id,
                                remote_id,
                                reason,
                            )
                            confirmed = True
                            release_lease = False
                        else:
                            client.kill_sandbox(function_id, remote_id)
                            if self._confirm_remote_absent(function_id, remote_id):
                                confirmed = True
                            else:
                                logger.warning(
                                    "veFaaS sandbox %s (remote=%s) still present after KillSandbox (%s); keeping quarantine fence",
                                    sandbox_id,
                                    remote_id,
                                    reason,
                                )
                if not heartbeat["exited"]:
                    release_lease = False
                    confirmed = False
        except Exception as exc:
            logger.warning("Failed to retire veFaaS sandbox %s (remote=%s, %s): %s", sandbox_id, remote_id, reason, self._redact(exc))
        finally:
            if confirmed and release_lease:
                try:
                    self._ownership.release(sandbox_id)
                except OwnershipBackendError as exc:
                    logger.warning("Failed to release ownership lease for retired veFaaS sandbox %s: %s", sandbox_id, exc)
                    confirmed = False
            with self._lock:
                remaining_teardowns = self._local_teardown.get(sandbox_id, 1) - 1
                if remaining_teardowns <= 0:
                    self._local_teardown.pop(sandbox_id, None)
                else:
                    self._local_teardown[sandbox_id] = remaining_teardowns
                if not deferred_by_snapshot and self._warm_pool.get(sandbox_id, (None, 0.0))[0] is tracked:
                    self._warm_pool.pop(sandbox_id, None)
                self._destroying_remote_ids.discard(remote_id)
                if deferred_by_snapshot:
                    self._pending_destroys.pop(remote_id, None)
                elif confirmed:
                    self._pending_destroys.pop(remote_id, None)
                    bucket = self._quarantined_remote_ids.get(sandbox_id)
                    if bucket is not None:
                        bucket.discard(remote_id)
                        if not bucket:
                            self._quarantined_remote_ids.pop(sandbox_id, None)
                else:
                    self._quarantined_remote_ids.setdefault(sandbox_id, set()).add(remote_id)
            if not handle_closed and not deferred_by_snapshot:
                tracked.sandbox.close()
        return not deferred_by_snapshot

    def _drain_quarantine_for_scope(self, sandbox_id: str) -> None:
        with self._lock:
            quarantined = sorted(self._quarantined_remote_ids.get(sandbox_id, set()))
        if not quarantined:
            return
        function_id, _ = self._require_provisioning_settings()
        client = self._get_client()
        still_present: list[str] = []
        for remote_id in quarantined:
            with self._lock:
                pending_rollback = self._pending_rollbacks.get(remote_id)
                pending_destroy = self._pending_destroys.get(remote_id)
            if pending_rollback is not None:
                if not self._cleanup_rollback(pending_rollback, reason="drain_quarantine", require_pending=True):
                    with self._lock:
                        if remote_id in self._quarantined_remote_ids.get(sandbox_id, set()):
                            still_present.append(remote_id)
                continue
            if pending_destroy is not None:
                self._destroy_tracked(pending_destroy, reason="drain_quarantine", require_pending=True)
                with self._lock:
                    if remote_id in self._quarantined_remote_ids.get(sandbox_id, set()):
                        still_present.append(remote_id)
                continue
            try:
                client.kill_sandbox(function_id, remote_id)
                if self._confirm_remote_absent(function_id, remote_id):
                    with self._lock:
                        bucket = self._quarantined_remote_ids.get(sandbox_id)
                        if bucket is not None:
                            bucket.discard(remote_id)
                            if not bucket:
                                self._quarantined_remote_ids.pop(sandbox_id, None)
                else:
                    still_present.append(remote_id)
            except Exception as exc:
                raise RuntimeError(f"Cannot replace quarantined veFaaS sandbox {sandbox_id} (remote={remote_id}): {self._redact(exc)}") from exc
        if still_present:
            raise RuntimeError(f"Quarantined veFaaS sandbox generation(s) still active for {sandbox_id}: {', '.join(still_present)}")

    def _destroy_tracked(
        self,
        tracked: _TrackedVeFaaSSandbox,
        *,
        reason: str,
        still_reapable: Callable[[], bool] | None = None,
        pop_warm: bool = False,
        require_pending: bool = False,
    ) -> bool:
        remote_id = tracked.remote_sandbox_id
        sandbox_id = tracked.sandbox_id
        if pop_warm and self._is_remote_snapshot_fenced(remote_id):
            return False
        with self._lock:
            if require_pending and self._pending_destroys.get(remote_id) is not tracked:
                return False
            if still_reapable is not None and (sandbox_id in self._local_teardown or not still_reapable()):
                return False
            if remote_id in self._destroying_remote_ids or remote_id in self._mirroring_output_ids or remote_id in self._snapshotting_remote_ids:
                return False
            self._local_teardown[sandbox_id] = self._local_teardown.get(sandbox_id, 0) + 1
            self._destroying_remote_ids.add(remote_id)
            self._pending_destroys[remote_id] = tracked

        confirmed = False
        release_lease = False
        deferred_by_snapshot = False
        handle_closed = False
        try:
            claimed = self._ownership.claim(sandbox_id, for_destroy=True)
            if not claimed:
                # Owned by a live peer: never destroy remotely; drop local pending state.
                logger.info("Skipping remote kill for veFaaS sandbox %s (%s): owned by a peer", sandbox_id, reason)
                confirmed = True
            elif self._is_remote_snapshot_fenced(remote_id):
                logger.info("Deferring remote kill for veFaaS sandbox %s (remote=%s, %s): snapshot fence active", sandbox_id, remote_id, reason)
                deferred_by_snapshot = True
                self._restore_deferred_teardown_lease(sandbox_id, context="deferred teardown")
            else:
                tracked.sandbox.close()
                handle_closed = True
                release_lease = True
                function_id = self._config["function_id"]
                self._get_client().kill_sandbox(function_id, remote_id)
                if self._confirm_remote_absent(function_id, remote_id):
                    confirmed = True
                else:
                    logger.warning("veFaaS sandbox %s (remote=%s) still present after KillSandbox (%s); keeping quarantine fence", sandbox_id, remote_id, reason)
        except Exception as exc:
            logger.warning("Failed to destroy veFaaS sandbox %s (remote=%s, %s): %s", sandbox_id, remote_id, reason, self._redact(exc))
        finally:
            if confirmed and release_lease:
                try:
                    self._ownership.release(sandbox_id)
                except OwnershipBackendError as exc:
                    logger.warning("Failed to release ownership lease for destroyed veFaaS sandbox %s: %s", sandbox_id, exc)
                    confirmed = False
            with self._lock:
                remaining_teardowns = self._local_teardown.get(sandbox_id, 1) - 1
                if remaining_teardowns <= 0:
                    self._local_teardown.pop(sandbox_id, None)
                else:
                    self._local_teardown[sandbox_id] = remaining_teardowns
                if pop_warm and not deferred_by_snapshot and self._warm_pool.get(sandbox_id, (None, 0.0))[0] is tracked:
                    self._warm_pool.pop(sandbox_id, None)
                self._destroying_remote_ids.discard(remote_id)
                if deferred_by_snapshot:
                    if pop_warm:
                        self._pending_destroys.pop(remote_id, None)
                elif confirmed:
                    self._pending_destroys.pop(remote_id, None)
                    bucket = self._quarantined_remote_ids.get(sandbox_id)
                    if bucket is not None:
                        bucket.discard(remote_id)
                        if not bucket:
                            self._quarantined_remote_ids.pop(sandbox_id, None)
                else:
                    self._quarantined_remote_ids.setdefault(sandbox_id, set()).add(remote_id)
            if not handle_closed and not deferred_by_snapshot:
                tracked.sandbox.close()
        return not deferred_by_snapshot

    def _retry_pending_destroys(self) -> None:
        with self._lock:
            pending = list(self._pending_destroys.values())
            pending_rollbacks = list(self._pending_rollbacks.values())
        for tracked in pending:
            self._destroy_tracked(tracked, reason="retry_destroy", require_pending=True)
        for rollback in pending_rollbacks:
            self._cleanup_rollback(rollback, reason="retry_rollback", require_pending=True)

    # ── Upload-based file restoration & per-agent skills isolation ───────

    @staticmethod
    def _add_tree_to_tar(archive: tarfile.TarFile, source: Path, arc_prefix: str, budget: _UploadBudget) -> bool:
        for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
            dirnames.sort()
            filenames.sort()
            current_dir = Path(dirpath)
            rel_dir = current_dir.relative_to(source)
            # Prune symlinked directories so a local link cannot smuggle host files.
            kept_dirs: list[str] = []
            for dname in dirnames:
                candidate = current_dir / dname
                if candidate.is_symlink():
                    continue
                kept_dirs.append(dname)
            dirnames[:] = kept_dirs

            for fname in filenames:
                file_path = current_dir / fname
                if file_path.is_symlink():
                    continue
                try:
                    st = file_path.stat()
                except OSError:
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue
                if not budget.admit(st.st_size):
                    return False
                rel_file = (rel_dir / fname).as_posix() if rel_dir != Path(".") else fname
                arcname = f"{arc_prefix}/{rel_file}"
                archive.add(file_path, arcname=arcname, recursive=False)
        return True

    def _upload_trees(
        self,
        sandbox: AioSandbox,
        sources: list[tuple[Path, str]],
        *,
        dest_root: str,
        replace: tuple[str, ...] = (),
    ) -> bool:
        budget = _UploadBudget(max_files=_MAX_UPLOAD_FILES, max_bytes=_MAX_UPLOAD_BYTES)
        complete = True
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for source, arc_prefix in sources:
                for part in (source, *source.parents):
                    if part.is_symlink():
                        raise ValueError(f"Refusing symlinked upload root for {arc_prefix}")
                if not source.is_dir():
                    continue
                if not self._add_tree_to_tar(archive, source, arc_prefix, budget):
                    complete = False
                    break

        if not complete and replace:
            return False
        if budget.files == 0 and not replace:
            return complete

        token = uuid.uuid4().hex
        remote_tar = f"/tmp/deerflow-vefaas-{token}.tar.gz"
        sandbox.update_file(remote_tar, buffer.getvalue())

        quoted_root = shlex.quote(dest_root)
        quoted_tar = shlex.quote(remote_tar)
        # Always run in a subshell with ``set +e`` outside so ``set -e``, ``trap EXIT``,
        # and ``exit`` never poison AioSandbox's persistent PTY shell session.
        if replace:
            staging_dir = f"{dest_root}/.vefaas-stage-{token}"
            quoted_stage = shlex.quote(staging_dir)
            stage_dirs = " ".join(shlex.quote(f"{staging_dir}/{name}") for name in replace)
            swap_steps = " ".join(f"rm -rf -- {shlex.quote(f'{dest_root}/{name}')}; mv -- {shlex.quote(f'{staging_dir}/{name}')} {shlex.quote(f'{dest_root}/{name}')};" for name in replace)
            script = (
                f"set +e; ( set -e; trap 'rm -rf -- {quoted_tar} {quoted_stage}' EXIT; "
                f"if [ -L {quoted_root} ]; then echo 'Refusing symlinked destination' >&2; exit 2; fi; "
                f"mkdir -p -- {quoted_root} {quoted_stage} {stage_dirs}; "
                f"tar -xzf {quoted_tar} -C {quoted_stage} --no-same-owner; "
                f"{swap_steps} echo UPLOAD_OK )"
            )
        else:
            script = (
                f"set +e; ( set -e; trap 'rm -f -- {quoted_tar}' EXIT; "
                f"if [ -L {quoted_root} ]; then echo 'Refusing symlinked destination' >&2; exit 2; fi; "
                f"mkdir -p -- {quoted_root}; "
                f"tar -xzf {quoted_tar} -C {quoted_root} --no-same-owner; "
                f"echo UPLOAD_OK )"
            )
        output = sandbox.execute_command(script)
        if "UPLOAD_OK" not in output:
            raise RuntimeError(f"veFaaS upload into {dest_root} failed: {output[:200]}")
        return complete

    def _restore_thread_files(self, sandbox: AioSandbox, *, thread_id: str, user_id: str) -> None:
        from deerflow.config.paths import get_paths

        paths = get_paths()
        sources = [
            (paths.sandbox_uploads_dir(thread_id, user_id=user_id), "uploads"),
            (paths.sandbox_work_dir(thread_id, user_id=user_id), "workspace"),
            (paths.sandbox_outputs_dir(thread_id, user_id=user_id), "outputs"),
        ]
        if not self._upload_trees(sandbox, sources, dest_root=USER_DATA_ROOT):
            logger.warning(
                "Thread files for veFaaS sandbox %s exceed %d files or %d bytes; remaining files were skipped",
                sandbox.id,
                _MAX_UPLOAD_FILES,
                _MAX_UPLOAD_BYTES,
            )

    def _restore_thread_uploads(self, sandbox: AioSandbox, *, thread_id: str, user_id: str) -> None:
        """Sync host uploads into a snapshot-restored sandbox without overwriting snapshot workspace."""
        from deerflow.config.paths import get_paths

        paths = get_paths()
        sources = [(paths.sandbox_uploads_dir(thread_id, user_id=user_id), "uploads")]
        if not self._upload_trees(sandbox, sources, dest_root=USER_DATA_ROOT):
            logger.warning(
                "Thread uploads for veFaaS sandbox %s exceed %d files or %d bytes; remaining files were skipped",
                sandbox.id,
                _MAX_UPLOAD_FILES,
                _MAX_UPLOAD_BYTES,
            )

    def _upload_shared_skills(self, sandbox: AioSandbox, *, thread_id: str, user_id: str) -> None:
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
            logger.warning("Could not upload shared skills projection for veFaaS sandbox %s: %s", sandbox.id, exc)

    def _upload_skills(self, sandbox: AioSandbox, projection: SkillProjectionPaths) -> None:
        sources = [(Path(getattr(projection, category)), category) for category in SKILL_CATEGORIES]
        if not self._upload_trees(
            sandbox,
            sources,
            dest_root=self._config["skills_container_path"],
            replace=SKILL_CATEGORIES,
        ):
            raise RuntimeError("Skills projection exceeds the veFaaS upload limit")

    def sync_agent_skills(
        self,
        sandbox_id: str,
        *,
        thread_id: str,
        user_id: str,
        projection: SkillProjectionPaths,
    ) -> None:
        """Atomically replace the managed skills tree inside the veFaaS sandbox."""
        with self._acquire_serializer.hold(sandbox_id):
            with self._lock:
                tracked = self._sandboxes.get(sandbox_id)
            if tracked is None:
                raise RuntimeError(f"veFaaS sandbox {sandbox_id} is not available for skill synchronization")
            if (tracked.user_id or "") != (user_id or "") or tracked.thread_id != thread_id:
                raise RuntimeError(f"veFaaS sandbox {sandbox_id} does not match target identity ({user_id}, {thread_id})")
            self._upload_skills(tracked.sandbox, projection)

    # ── Snapshots & image precaching ─────────────────────────────────────

    def create_snapshot(
        self,
        sandbox_id: str,
        *,
        snapshot_type: str | None = None,
        retention_days: int | None = None,
        wait: bool = True,
        timeout: float | None = None,
    ) -> VeFaaSSnapshotRecord:
        """Create a scoped snapshot of a tracked (active or warm) veFaaS sandbox."""
        resolved_type = self._validate_snapshot_type(snapshot_type, default=self._config["snapshot_type"])
        resolved_retention = (
            self._config["snapshot_retention_days"]
            if retention_days is None
            else self._bounded_int(
                "snapshot_retention_days",
                retention_days,
                minimum=MIN_SNAPSHOT_RETENTION_DAYS,
                maximum=MAX_SNAPSHOT_RETENTION_DAYS,
            )
        )
        resolved_timeout = self._positive_float("snapshot_timeout", timeout, self._config["snapshot_timeout"])
        function_id, _ = self._require_provisioning_settings()

        with self._acquiring():
            with self._acquire_serializer.hold(sandbox_id):
                with self._lock:
                    if not self._accepting or self._shutdown_called:
                        raise RuntimeError("VeFaaSSandboxProvider has been shut down")
                    if sandbox_id in self._local_teardown:
                        raise RuntimeError(f"veFaaS sandbox {sandbox_id} is currently being torn down")
                    tracked = self._sandboxes.get(sandbox_id)
                    if tracked is None:
                        warm = self._warm_pool.get(sandbox_id)
                        tracked = warm[0] if warm is not None else None
                    if tracked is None:
                        raise RuntimeError(f"veFaaS sandbox {sandbox_id} is not tracked by this provider")
                    remote_id = tracked.remote_sandbox_id
                    self._snapshotting_remote_ids[remote_id] = self._snapshotting_remote_ids.get(remote_id, 0) + 1
                snapshot_id: str | None = None
                settled = True
                handed_off = False
                remote_fence_reserved = False
                submission_uncertain = False
                try:
                    if self._is_sandbox_dirty(tracked.sandbox):
                        raise RuntimeError(f"Refusing to snapshot corrupted veFaaS sandbox {sandbox_id}")
                    fence_key = self._snapshot_fence_key(remote_id)
                    with self._snapshot_fence_lock(remote_id):
                        if not self._ownership.claim(sandbox_id):
                            raise RuntimeError(f"Refusing to snapshot veFaaS sandbox {sandbox_id}: owned by a peer or tearing down")
                        if not self._ownership.claim(fence_key, for_destroy=True):
                            raise RuntimeError(f"Refusing to snapshot veFaaS sandbox {sandbox_id} (remote={remote_id}): another worker holds a snapshot reservation")
                        with self._lock:
                            self._remote_snapshot_fences[remote_id] = self._remote_snapshot_fences.get(remote_id, 0) + 1
                        remote_fence_reserved = True
                        # Dekker re-check: verify no peer claimed destructive teardown on sandbox_id
                        # before fence_key became visible.
                        if not self._ownership.claim(sandbox_id):
                            raise RuntimeError(f"Refusing to snapshot veFaaS sandbox {sandbox_id}: ownership moved to a peer before snapshot started")

                    metadata = self._scoped_metadata(sandbox_id)
                    with self._teardown_lease_heartbeat(fence_key):
                        try:
                            snapshot_id = self._get_client().create_sandbox_snapshot(
                                function_id,
                                remote_id,
                                snapshot_type=resolved_type,
                                retention_days=resolved_retention,
                                metadata=metadata,
                            )
                        except Exception as submit_exc:
                            if self._is_uncertain_snapshot_submit_error(submit_exc):
                                submission_uncertain = True
                                settled = False
                            raise
                        settled = False
                        if not wait:
                            return VeFaaSSnapshotRecord(
                                id=snapshot_id,
                                sandbox_id=remote_id,
                                function_id=function_id,
                                status="Creating",
                                snapshot_type=resolved_type,
                                retention_days=resolved_retention,
                                metadata=metadata,
                            )
                        try:
                            record = self._wait_for_snapshot_ready(
                                function_id,
                                snapshot_id,
                                deadline=time.monotonic() + resolved_timeout,
                                refresh_lease=lambda: self._refresh_snapshot_fence(remote_id) or True,
                            )
                            settled = True
                            return record
                        except _VeFaaSSnapshotSettledFailureError:
                            settled = True
                            raise
                finally:
                    if not settled:
                        if snapshot_id is not None:
                            try:
                                self._start_snapshot_watcher(
                                    function_id=function_id,
                                    remote_id=remote_id,
                                    snapshot_id=snapshot_id,
                                )
                                handed_off = True
                            except Exception as watch_exc:
                                logger.warning(
                                    "Failed to start completion watcher for veFaaS snapshot %s (remote=%s): %s",
                                    snapshot_id,
                                    remote_id,
                                    self._redact(watch_exc),
                                )
                        elif submission_uncertain:
                            try:
                                self._start_uncertain_snapshot_watcher(
                                    function_id=function_id,
                                    remote_id=remote_id,
                                )
                                handed_off = True
                            except Exception as watch_exc:
                                logger.warning(
                                    "Failed to start reconciliation watcher for uncertain veFaaS snapshot submission (remote=%s): %s",
                                    remote_id,
                                    self._redact(watch_exc),
                                )
                    if not handed_off:
                        self._release_snapshot_fence(remote_id, release_remote=remote_fence_reserved)

    def _release_snapshot_fence(self, remote_id: str, *, release_remote: bool) -> None:
        if release_remote:
            with self._snapshot_fence_lock(remote_id):
                drop_remote_key = False
                with self._lock:
                    remote_remaining = self._remote_snapshot_fences.get(remote_id, 1) - 1
                    if remote_remaining <= 0:
                        self._remote_snapshot_fences.pop(remote_id, None)
                        drop_remote_key = True
                    else:
                        self._remote_snapshot_fences[remote_id] = remote_remaining
                if drop_remote_key:
                    self._release_ownership_best_effort(self._snapshot_fence_key(remote_id), context="snapshot fence")
        with self._lock:
            snap_remaining = self._snapshotting_remote_ids.get(remote_id, 1) - 1
            if snap_remaining <= 0:
                self._snapshotting_remote_ids.pop(remote_id, None)
            else:
                self._snapshotting_remote_ids[remote_id] = snap_remaining

    def _start_snapshot_watcher(self, *, function_id: str, remote_id: str, snapshot_id: str) -> None:
        thread = threading.Thread(
            target=self._watch_snapshot_completion,
            kwargs={
                "function_id": function_id,
                "remote_id": remote_id,
                "snapshot_id": snapshot_id,
            },
            name=f"vefaas-snapshot-watch-{snapshot_id[:12]}",
            daemon=True,
        )
        with self._lock:
            self._snapshot_watchers.add(thread)
        try:
            thread.start()
        except Exception:
            with self._lock:
                self._snapshot_watchers.discard(thread)
            raise

    def _start_uncertain_snapshot_watcher(self, *, function_id: str, remote_id: str) -> None:
        thread = threading.Thread(
            target=self._watch_uncertain_snapshot_submission,
            kwargs={
                "function_id": function_id,
                "remote_id": remote_id,
            },
            name=f"vefaas-snapshot-reconcile-{remote_id[:12]}",
            daemon=True,
        )
        with self._lock:
            self._snapshot_watchers.add(thread)
        try:
            thread.start()
        except Exception:
            with self._lock:
                self._snapshot_watchers.discard(thread)
            raise

    def _watch_snapshot_completion(self, *, function_id: str, remote_id: str, snapshot_id: str) -> None:
        """Keep ``remote_id`` fenced until the control plane confirms ``snapshot_id`` settled."""
        waiter = threading.Event()
        try:
            client = self._get_client()
            while True:
                self._refresh_snapshot_fence(remote_id)
                try:
                    record = client.describe_sandbox_snapshot(function_id, snapshot_id)
                except Exception as exc:
                    logger.warning(
                        "Transient error polling veFaaS snapshot %s (remote=%s): %s",
                        snapshot_id,
                        remote_id,
                        self._redact(exc),
                    )
                else:
                    if record is None:
                        logger.info("veFaaS snapshot %s (remote=%s) disappeared; releasing teardown fence", snapshot_id, remote_id)
                        return
                    if record.is_ready:
                        logger.info("veFaaS snapshot %s (remote=%s) is Ready; releasing teardown fence", snapshot_id, remote_id)
                        return
                    if record.is_terminal_failure:
                        logger.warning(
                            "veFaaS snapshot %s (remote=%s) entered terminal state %r; releasing teardown fence",
                            snapshot_id,
                            remote_id,
                            record.status,
                        )
                        return
                waiter.wait(self._snapshot_watch_interval)
        finally:
            self._release_snapshot_fence(remote_id, release_remote=True)
            with self._lock:
                self._snapshot_watchers.discard(threading.current_thread())

    def _watch_uncertain_snapshot_submission(self, *, function_id: str, remote_id: str) -> None:
        """Keep ``remote_id`` fenced after an uncertain submit until no snapshot is in progress."""
        waiter = threading.Event()
        try:
            client = self._get_client()
            while True:
                self._refresh_snapshot_fence(remote_id)
                try:
                    snapshots = client.list_sandbox_snapshots(function_id, sandbox_id=remote_id)
                    in_progress = [snap for snap in snapshots if snap.sandbox_id == remote_id and not snap.is_ready and not snap.is_terminal_failure]
                    if not in_progress:
                        sandbox = client.describe_sandbox(function_id, remote_id)
                        if sandbox is None or sandbox.status.strip().lower() != "snapshotting":
                            logger.info("Uncertain veFaaS snapshot submission on remote=%s reconciled (no in-progress snapshot); releasing teardown fence", remote_id)
                            return
                except Exception as exc:
                    logger.warning(
                        "Transient error reconciling uncertain veFaaS snapshot submission (remote=%s): %s",
                        remote_id,
                        self._redact(exc),
                    )
                waiter.wait(self._snapshot_watch_interval)
        finally:
            self._release_snapshot_fence(remote_id, release_remote=True)
            with self._lock:
                self._snapshot_watchers.discard(threading.current_thread())

    def _join_snapshot_watchers(self) -> None:
        current = threading.current_thread()
        with self._lock:
            watchers = [thread for thread in self._snapshot_watchers if thread is not current]
        for thread in watchers:
            if thread.is_alive():
                thread.join(timeout=5)
                if thread.is_alive():
                    raise RuntimeError("veFaaS snapshot completion watcher is still running after join timeout")

    def list_snapshots(self, sandbox_id: str | None = None) -> list[VeFaaSSnapshotRecord]:
        """List DeerFlow-scoped snapshots for this veFaaS function, newest first."""
        function_id, _ = self._require_provisioning_settings()
        with self._acquiring():
            matching = self._list_scoped_snapshots(function_id, sandbox_id)
        matching.sort(key=_snapshot_sort_key, reverse=True)
        return matching

    def delete_snapshot(self, snapshot_id: str) -> None:
        """Delete a veFaaS sandbox snapshot (idempotent when already absent)."""
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            raise ValueError("snapshot_id must be a non-empty string")
        function_id, _ = self._require_provisioning_settings()
        with self._acquiring():
            self._get_client().delete_sandbox_snapshot(function_id, snapshot_id.strip())

    def precache_images(
        self,
        image_urls: Sequence[str] | None = None,
        *,
        wait: bool = False,
        timeout: float | None = None,
    ) -> VeFaaSPrecacheTicket:
        """Trigger veFaaS sandbox image precaching and optionally wait for completion."""
        urls = self._resolve_precache_urls(image_urls)
        if not urls:
            raise ValueError("precache_images requires image_urls or configured sandbox.precache_images / sandbox.image")
        resolved_timeout = self._positive_float("precache_timeout", timeout, DEFAULT_PRECACHE_TIMEOUT)
        with self._acquiring():
            client = self._get_client()
            ticket_id = client.precache_sandbox_images(urls)
            if not wait:
                return VeFaaSPrecacheTicket(ticket_id=ticket_id, status="Pending")
            deadline = time.monotonic() + resolved_timeout
            while True:
                ticket = client.get_sandbox_image_precache_ticket(ticket_id)
                if ticket.is_succeeded:
                    return ticket
                if ticket.is_terminal_failure:
                    raise RuntimeError(f"veFaaS image precache ticket {ticket_id} failed with status {ticket.status!r}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Timed out waiting for veFaaS image precache ticket {ticket_id} to complete")
                time.sleep(min(_POLL_STATUS_INTERVAL_SECONDS, remaining))

    # ── Release & bounded output mirroring ───────────────────────────────

    def release(self, sandbox_id: str) -> None:
        """Mirror outputs (when not TOS-mounted) and park the sandbox in the warm pool."""
        with self._lock:
            if sandbox_id not in self._sandboxes:
                return
        try:
            with self._acquire_serializer.hold(sandbox_id):
                self._release_scope_locked(sandbox_id)
        except AcquireSerializerClosed:
            with self._lock:
                untracked = sandbox_id not in self._sandboxes
            if not untracked:
                raise

    def _release_scope_locked(self, sandbox_id: str) -> None:
        with self._lock:
            tracked = self._sandboxes.get(sandbox_id)
        if tracked is None:
            return
        needs_recycle = self._is_sandbox_dirty(tracked.sandbox)
        if not needs_recycle and not self._uses_tos_for_user_data() and tracked.thread_id and tracked.user_id:
            remote_id = tracked.remote_sandbox_id
            with self._lock:
                if self._shutdown_called or self._sandboxes.get(sandbox_id) is not tracked:
                    return
                self._mirroring_output_ids.add(remote_id)
            try:
                self._sync_outputs_to_host(tracked.sandbox, thread_id=tracked.thread_id, user_id=tracked.user_id)
            except Exception:
                logger.warning("Failed to synchronize veFaaS outputs for %s", sandbox_id, exc_info=True)
            finally:
                with self._lock:
                    self._mirroring_output_ids.remove(remote_id)
            needs_recycle = self._is_sandbox_dirty(tracked.sandbox)

        with self._lock:
            if self._sandboxes.get(sandbox_id) is not tracked:
                return
            self._sandboxes.pop(sandbox_id)
            for key in [k for k, v in self._thread_sandboxes.items() if v == sandbox_id]:
                self._thread_sandboxes.pop(key, None)
            destroy_now = needs_recycle or self._shutdown_called or not self._accepting
            if destroy_now:
                # Register pending teardown in the same critical section as removing the active
                # entry so a concurrent shutdown() cannot miss this sandbox or close the client early.
                self._pending_destroys[tracked.remote_sandbox_id] = tracked
            else:
                self._warm_pool[sandbox_id] = (tracked, time.monotonic())
        if destroy_now:
            reason = "recycle_corrupted" if needs_recycle else "released_during_shutdown"
            if needs_recycle:
                logger.warning("Recycling veFaaS sandbox %s instead of returning it to the warm pool", sandbox_id)
            self._destroy_tracked(tracked, reason=reason, require_pending=True)
        else:
            logger.info("Released veFaaS sandbox %s to the warm pool", sandbox_id)

    @staticmethod
    def _output_parts(remote_path: str) -> tuple[str, ...]:
        prefix = f"{OUTPUTS_ROOT}/"
        if not remote_path.startswith(prefix) or "\\" in remote_path:
            raise ValueError("Output path is outside the outputs directory")
        parts = remote_path[len(prefix) :].split("/")
        if any(part in {"", ".", ".."} or ":" in part or part.partition(".")[0].rstrip(" ").upper() in _WINDOWS_RESERVED_NAMES or part.endswith((" ", ".")) for part in parts):
            raise ValueError("Unsafe output path")
        return tuple(parts)

    @classmethod
    def _output_destination(cls, root: Path, remote_path: str) -> Path:
        parts = cls._output_parts(remote_path)
        target = root.joinpath(*PurePosixPath(*parts).parts)
        for component in reversed((target, *target.parents)):
            if component.is_symlink() or component.is_junction():
                raise ValueError("Symlinked output destination")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not stat.S_ISREG(target.stat().st_mode):
            raise ValueError("Output destination is not a regular file")
        return target

    def _sync_outputs_to_host(self, sandbox: AioSandbox, *, thread_id: str, user_id: str) -> None:
        from deerflow.config.paths import get_paths

        root = get_paths().sandbox_outputs_dir(thread_id, user_id=user_id)
        quoted_out = shlex.quote(OUTPUTS_ROOT)
        listing = sandbox.execute_command(f"[ -d {quoted_out} ] && [ ! -L {quoted_out} ] && find {quoted_out} -type f 2>/dev/null | head -c {_MAX_SYNC_LISTING_BYTES + 1} || true")
        if not listing or len(listing.encode("utf-8", errors="ignore")) > _MAX_SYNC_LISTING_BYTES:
            return
        remote_paths = [line.strip() for line in listing.splitlines() if line.strip().startswith(f"{OUTPUTS_ROOT}/")]
        deadline = time.monotonic() + _SYNC_DEADLINE_SECONDS
        total = 0
        for index, remote_path in enumerate(remote_paths):
            if index >= _MAX_SYNC_FILES or total >= _MAX_SYNC_TOTAL_BYTES or time.monotonic() >= deadline:
                break
            staged: Path | None = None
            try:
                target = self._output_destination(root, remote_path)
                data = sandbox.download_file(remote_path, max_bytes=min(DEFAULT_DOWNLOAD_LIMIT, _MAX_SYNC_TOTAL_BYTES - total))
                total += len(data)
                with tempfile.NamedTemporaryFile(prefix=".vefaas-sync-", dir=target.parent, delete=False) as tmp:
                    staged = Path(tmp.name)
                    tmp.write(data)
                self._output_destination(root, remote_path)
                staged.replace(target)
            except (OSError, ValueError):
                logger.warning("Could not synchronize veFaaS output %r", remote_path, exc_info=True)
            finally:
                if staged is not None:
                    staged.unlink(missing_ok=True)

    # ── Reset & Shutdown ─────────────────────────────────────────────────

    def reset(self) -> None:
        """Retire admission and park tracked sandboxes in this instance's warm pool."""
        with self._lock:
            self._accepting = False
            now = time.monotonic()
            for sandbox_id, tracked in self._sandboxes.items():
                self._warm_pool.setdefault(sandbox_id, (tracked, now))
            self._sandboxes.clear()
            self._thread_sandboxes.clear()
        self._acquire_serializer.close()

    def _shutdown_at_exit(self) -> None:
        try:
            self.shutdown()
        except _VeFaaSShutdownIncompleteError as exc:
            logger.warning("%s", exc)

    def shutdown(self) -> None:
        """Close admission, stop maintenance threads, and tear down owned remote sandboxes."""
        with self._shutdown_lock:
            with self._lock:
                if self._shutdown_complete:
                    return
                self._shutdown_called = True
                self._accepting = False
                if self._mirroring_output_ids or self._snapshotting_remote_ids:
                    # Keep clients, snapshot sources, and lease renewal alive until in-flight
                    # output mirrors and manual snapshots settle.
                    raise _VeFaaSShutdownIncompleteError(f"veFaaS shutdown incomplete: {len(self._mirroring_output_ids)} output mirror(s) and {len(self._snapshotting_remote_ids)} snapshot(s) active; retry shutdown")
                tracked_remote_scopes = {entry.remote_sandbox_id: entry.sandbox_id for entry in (list(self._sandboxes.values()) + [entry for entry, _ in self._warm_pool.values()] + list(self._pending_destroys.values()))}
            fenced_owned_remotes = [rid for rid, sid in sorted(tracked_remote_scopes.items()) if self._is_remote_snapshot_fenced(rid) and self._may_own_for_teardown(sid)]
            if fenced_owned_remotes:
                raise _VeFaaSShutdownIncompleteError(f"veFaaS shutdown incomplete: {len(fenced_owned_remotes)} peer snapshot fence(s) active; retry shutdown")

            self._acquire_serializer.close()

            threads_stopped = True
            try:
                self._stop_idle_checker()
            except RuntimeError:
                threads_stopped = False
            try:
                self._stop_renewal_thread()
            except RuntimeError:
                threads_stopped = False
            try:
                self._stop_precache_thread()
            except RuntimeError:
                threads_stopped = False
            try:
                self._join_snapshot_watchers()
            except RuntimeError:
                threads_stopped = False

            with self._lock:
                active = list(self._sandboxes.values())
                warm = [entry for entry, _ in self._warm_pool.values()]
                pending = list(self._pending_destroys.values())
                pending_rollbacks = list(self._pending_rollbacks.values())
                self._sandboxes.clear()
                self._warm_pool.clear()
                self._thread_sandboxes.clear()

            unique = {entry.remote_sandbox_id: entry for entry in active + warm + pending}
            for tracked in unique.values():
                self._destroy_tracked(tracked, reason="shutdown")
            for rollback in pending_rollbacks:
                self._cleanup_rollback(rollback, reason="shutdown", require_pending=True)

            with self._lock:
                still_pending = len(self._pending_destroys) + len(self._pending_rollbacks)
                in_flight_acquires = self._acquires
                if in_flight_acquires or still_pending or not threads_stopped or self._snapshotting_remote_ids:
                    raise _VeFaaSShutdownIncompleteError(f"veFaaS shutdown incomplete: {in_flight_acquires} acquire(s) active, {still_pending} teardown(s) pending, threads_stopped={threads_stopped}; retry shutdown")
                self._shutdown_complete = True

            if self._client is not None and self._client_override is None:
                self._client.close()
            self._ownership.close()


__all__ = ["VeFaaSSandboxProvider"]
