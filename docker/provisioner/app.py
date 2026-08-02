"""DeerFlow Sandbox Provisioner Service.

Dynamically creates and manages per-sandbox Pods in Kubernetes.
Each ``sandbox_id`` gets its own Pod + Service.  The backend accesses sandboxes
through NodePort or Kubernetes service DNS, depending on configuration.

The provisioner connects to the host machine's Kubernetes cluster via a
mounted kubeconfig (``~/.kube/config``) or in-cluster config.  Sandbox Pods
run in K8s and are accessed by the backend via the configured Service mode.

Endpoints:
    POST   /api/sandboxes              — Create a sandbox Pod + Service
    DELETE /api/sandboxes/{sandbox_id} — Destroy a sandbox Pod + Service
    GET    /api/sandboxes/{sandbox_id} — Get sandbox status & URL
    GET    /api/sandboxes              — List all sandboxes
    GET    /health                     — Provisioner health check

Architecture (docker-compose-dev):
    ┌────────────┐  HTTP  ┌─────────────┐  K8s API  ┌──────────────┐
    │ remote     │ ─────▸ │ provisioner │ ────────▸ │  host K8s    │
    │ _backend   │        │ :8002       │           │  API server  │
    └────────────┘        └─────────────┘           └──────┬───────┘
                                                           │ creates
                          ┌─────────────┐           ┌──────▼───────┐
                          │   backend   │ ────────▸ │   sandbox    │
                          │             │ direct/DNS│   Pod(s)     │
                          └─────────────┘           └──────────────┘
"""

from __future__ import annotations

import logging
import os
import posixpath
import re
import secrets
import time
from contextlib import asynccontextmanager

import urllib3
from fastapi import FastAPI, HTTPException, Request, Response
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException
from pydantic import BaseModel, Field

# Suppress only the InsecureRequestWarning from urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ── Configuration (all tuneable via environment variables) ───────────────

K8S_NAMESPACE = os.environ.get("K8S_NAMESPACE", "deer-flow")
SANDBOX_IMAGE = os.environ.get(
    "SANDBOX_IMAGE",
    "enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest",
)
# Optional "lark-cli init" image (Pattern A). When set, sandbox Pods get an init
# container + shared emptyDir that provisions the lark-cli runtime binary, instead
# of a hostPath/PVC runtime mount fed by a Gateway-side GitHub download. Empty ⇒
# feature off (legacy behavior).
LARK_CLI_INIT_IMAGE = os.environ.get("LARK_CLI_INIT_IMAGE", "")
LARK_CLI_RUNTIME_CONTAINER_PATH = "/mnt/integrations/lark-cli/runtime"
LARK_CLI_RUNTIME_VOLUME_NAME = "lark-cli-runtime"
# Optional "lark-cli broker" image (Pattern B, issue #4338). When set, sandbox
# Pods requesting the broker get an init container that stages a shim + a
# long-running broker sidecar that holds the credentials, instead of mounting the
# plaintext config/data credential dirs into the sandbox container. Empty ⇒ broker
# off (Pattern A / legacy behavior). Broker supersedes Pattern A when both are set.
LARK_CLI_BROKER_IMAGE = os.environ.get("LARK_CLI_BROKER_IMAGE", "")
# Optional comma-separated lark-cli subcommand denylist forwarded to the broker
# sidecar (issue #4338 hardening). Empty ⇒ no subcommand is blocked. See the
# broker README's "subcommand denylist" section.
LARK_CLI_BROKER_DENY_SUBCOMMANDS = os.environ.get("DEERFLOW_LARK_BROKER_DENY_SUBCOMMANDS", "")
LARK_CLI_CONFIG_CONTAINER_PATH = "/mnt/integrations/lark-cli/config"
LARK_CLI_DATA_CONTAINER_PATH = "/mnt/integrations/lark-cli/data"
# Where the broker sidecar reads the per-user credentials (sidecar-only paths).
LARK_BROKER_SIDECAR_CONFIG_PATH = "/var/lark/config"
LARK_BROKER_SIDECAR_DATA_PATH = "/var/lark/data"
LARK_BROKER_CONFIG_VOLUME_NAME = "lark-cli-config"
LARK_BROKER_DATA_VOLUME_NAME = "lark-cli-data"
LARK_BROKER_URL = "http://127.0.0.1:8788"
THREADS_HOST_PATH = os.environ.get("THREADS_HOST_PATH", "/.deer-flow/threads")
DEER_FLOW_HOST_BASE_DIR = os.environ.get("DEER_FLOW_HOST_BASE_DIR", "/.deer-flow")
SKILLS_PVC_NAME = os.environ.get("SKILLS_PVC_NAME", "")
USERDATA_PVC_NAME = os.environ.get("USERDATA_PVC_NAME", "")
SKILLS_PVC_SUBPATH_TEMPLATE = os.environ.get("SKILLS_PVC_SUBPATH_TEMPLATE", "")
SANDBOX_CONTAINER_PORT_RAW = os.environ.get("SANDBOX_CONTAINER_PORT", "8080")
SANDBOX_SERVICE_TYPE = os.environ.get("SANDBOX_SERVICE_TYPE", "NodePort")
try:
    SANDBOX_CONTAINER_PORT = int(SANDBOX_CONTAINER_PORT_RAW)
except ValueError as exc:
    raise RuntimeError(f"Invalid SANDBOX_CONTAINER_PORT={SANDBOX_CONTAINER_PORT_RAW!r}; expected an integer TCP port") from exc
if not (1 <= SANDBOX_CONTAINER_PORT <= 65535):
    raise RuntimeError(f"Invalid SANDBOX_CONTAINER_PORT={SANDBOX_CONTAINER_PORT}; expected a value in [1, 65535]")
if SANDBOX_SERVICE_TYPE not in {"NodePort", "ClusterIP"}:
    raise RuntimeError(f"Invalid SANDBOX_SERVICE_TYPE={SANDBOX_SERVICE_TYPE!r}; expected 'NodePort' or 'ClusterIP'")
SAFE_THREAD_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
SAFE_USER_ID_PATTERN = r"^[A-Za-z0-9_\-]+$"
DEFAULT_USER_ID = "default"
MAX_EXTRA_MOUNTS = 9
ALLOWED_EXTRA_MOUNT_PATHS = {
    "/mnt/acp-workspace",
    "/mnt/skills/custom",
    "/mnt/skills/integrations",
    "/mnt/integrations/lark-cli/config",
    "/mnt/integrations/lark-cli/data",
    "/mnt/integrations/lark-cli/runtime",
}

# Path to the kubeconfig *inside* the provisioner container.
# Typically the host's ~/.kube/config is mounted here.
KUBECONFIG_PATH = os.environ.get("KUBECONFIG_PATH", "/root/.kube/config")
PROVISIONER_API_KEY = os.environ.get("PROVISIONER_API_KEY", "")

# The hostname / IP that the backend uses to reach NodePort services. On Docker
# Desktop for macOS this is ``host.docker.internal``; on Linux it may be the
# host's LAN IP. Ignored when SANDBOX_SERVICE_TYPE=ClusterIP.
NODE_HOST = os.environ.get("NODE_HOST", "host.docker.internal")


def join_host_path(base: str, *parts: str) -> str:
    """Join host filesystem path segments while preserving native style."""
    if not parts:
        return base

    if re.match(r"^[A-Za-z]:[\\/]", base) or base.startswith("\\\\") or "\\" in base:
        from pathlib import PureWindowsPath

        result = PureWindowsPath(base)
        for part in parts:
            result /= part
        return str(result)

    from pathlib import Path

    result = Path(base)
    for part in parts:
        result /= part
    return str(result)


def _host_base_dir_for_extra_mounts() -> str:
    """Return the host-visible DeerFlow state root used for controlled mounts."""
    if DEER_FLOW_HOST_BASE_DIR:
        return os.path.normpath(DEER_FLOW_HOST_BASE_DIR)

    normalized_threads = os.path.normpath(THREADS_HOST_PATH)
    if os.path.basename(normalized_threads) == "threads":
        return os.path.dirname(normalized_threads)
    return ""


def _is_path_under_base(path: str, base: str) -> bool:
    """Return whether *path* is inside *base* after normalization."""
    if not base:
        return False
    try:
        return os.path.commonpath([os.path.normpath(path), os.path.normpath(base)]) == os.path.normpath(base)
    except ValueError:
        return False


def _normalize_extra_mount_container_path(container_path: str) -> str:
    normalized = posixpath.normpath(container_path)
    if not normalized.startswith("/"):
        raise HTTPException(status_code=400, detail=f"Extra mount path must be absolute: {container_path}")
    if normalized not in ALLOWED_EXTRA_MOUNT_PATHS:
        raise HTTPException(status_code=400, detail=f"Unsupported extra mount path: {container_path}")
    return normalized


def _validated_extra_mounts(extra_mounts: list["ExtraMount"] | None) -> list["ExtraMount"]:
    """Validate extra mounts before converting them into K8s hostPath/PVC mounts."""
    if not extra_mounts:
        return []
    if len(extra_mounts) > MAX_EXTRA_MOUNTS:
        raise HTTPException(status_code=400, detail=f"Too many extra mounts; max is {MAX_EXTRA_MOUNTS}")

    host_base_dir = _host_base_dir_for_extra_mounts()
    seen_container_paths: set[str] = set()
    validated: list[ExtraMount] = []
    for mount in extra_mounts:
        host_path = os.path.normpath(mount.host_path)
        if not os.path.isabs(host_path):
            raise HTTPException(status_code=400, detail=f"Extra mount host path must be absolute: {mount.host_path}")
        if not _is_path_under_base(host_path, host_base_dir):
            raise HTTPException(status_code=400, detail=f"Extra mount host path is outside DeerFlow state: {mount.host_path}")

        container_path = _normalize_extra_mount_container_path(mount.container_path)
        if container_path in seen_container_paths:
            raise HTTPException(status_code=400, detail=f"Duplicate extra mount path: {container_path}")
        seen_container_paths.add(container_path)

        validated.append(
            ExtraMount(
                host_path=host_path,
                container_path=container_path,
                read_only=mount.read_only,
            )
        )
    return validated


def _extra_mount_volume_name(index: int) -> str:
    return f"extra-{index}"


def _lark_cli_runtime_enabled(provision_lark_cli_runtime: bool) -> bool:
    """Whether to provision the lark-cli runtime via init container + emptyDir."""
    return bool(LARK_CLI_INIT_IMAGE) and provision_lark_cli_runtime


def _lark_cli_broker_enabled(provision_lark_cli_broker: bool) -> bool:
    """Whether to provision the lark-cli broker sidecar (Pattern B)."""
    return bool(LARK_CLI_BROKER_IMAGE) and provision_lark_cli_broker


def _runtime_provided_extra_mounts(
    extra_mounts: list["ExtraMount"] | None,
    *,
    provision_lark_cli_runtime: bool,
    provision_lark_cli_broker: bool = False,
) -> list["ExtraMount"]:
    """Drop lark-cli extra mounts the init container / broker sidecar supersede.

    Pattern A (init container + emptyDir) provides
    ``/mnt/integrations/lark-cli/runtime``, so a hostPath/PVC mount at the same
    path would collide — it is dropped, leaving the per-user ``config`` / ``data``
    credential mounts intact.

    Pattern B (broker sidecar) additionally moves the ``config`` / ``data``
    credential mounts off the *sandbox* container and into the sidecar, so those
    are dropped here too — the sandbox never sees plaintext credentials.
    """
    dropped: set[str] = set()
    if _lark_cli_broker_enabled(provision_lark_cli_broker):
        dropped = {
            LARK_CLI_RUNTIME_CONTAINER_PATH,
            LARK_CLI_CONFIG_CONTAINER_PATH,
            LARK_CLI_DATA_CONTAINER_PATH,
        }
    elif _lark_cli_runtime_enabled(provision_lark_cli_runtime):
        dropped = {LARK_CLI_RUNTIME_CONTAINER_PATH}
    if not extra_mounts or not dropped:
        return list(extra_mounts or [])
    return [mount for mount in extra_mounts if posixpath.normpath(mount.container_path) not in dropped]


def _lark_broker_credential_mounts(extra_mounts: list["ExtraMount"] | None) -> dict[str, "ExtraMount"]:
    """Extract the config/data credential mounts the broker sidecar needs.

    Keyed by container path so the caller can wire each into the sidecar's fixed
    ``/var/lark/{config,data}`` paths.
    """
    result: dict[str, ExtraMount] = {}
    for mount in _validated_extra_mounts(extra_mounts):
        normalized = posixpath.normpath(mount.container_path)
        if normalized in (LARK_CLI_CONFIG_CONTAINER_PATH, LARK_CLI_DATA_CONTAINER_PATH):
            result[normalized] = mount
    return result


def _extra_mount_pvc_sub_path(host_path: str) -> str:
    host_base_dir = _host_base_dir_for_extra_mounts()
    if not _is_path_under_base(host_path, host_base_dir):
        raise HTTPException(status_code=400, detail=f"Extra mount host path is outside DeerFlow state: {host_path}")

    rel_path = os.path.relpath(os.path.normpath(host_path), host_base_dir)
    rel_parts = [part for part in rel_path.replace(os.sep, "/").split("/") if part and part != "."]
    if not rel_parts or any(part == ".." for part in rel_parts):
        raise HTTPException(status_code=400, detail=f"Invalid extra mount host path: {host_path}")
    return posixpath.join("deer-flow", *rel_parts)


# ── K8s client setup ────────────────────────────────────────────────────

core_v1: k8s_client.CoreV1Api | None = None


def _init_k8s_client() -> k8s_client.CoreV1Api:
    """Load kubeconfig from the mounted host config and return a CoreV1Api.

    Tries the mounted kubeconfig first, then falls back to in-cluster
    config (useful if the provisioner itself runs inside K8s).
    """
    if os.path.exists(KUBECONFIG_PATH):
        if os.path.isdir(KUBECONFIG_PATH):
            raise RuntimeError(f"KUBECONFIG_PATH points to a directory, expected a file: {KUBECONFIG_PATH}")
        try:
            k8s_config.load_kube_config(config_file=KUBECONFIG_PATH)
            logger.info(f"Loaded kubeconfig from {KUBECONFIG_PATH}")
        except Exception as exc:
            raise RuntimeError(f"Failed to load kubeconfig from {KUBECONFIG_PATH}: {exc}") from exc
    else:
        logger.warning(f"Kubeconfig not found at {KUBECONFIG_PATH}; trying in-cluster config")
        try:
            k8s_config.load_incluster_config()
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize Kubernetes client. No kubeconfig at {KUBECONFIG_PATH}, and in-cluster config is unavailable: {exc}") from exc

    # When connecting from inside Docker to the host's K8s API, the
    # kubeconfig may reference ``localhost`` or ``127.0.0.1``.  We
    # optionally rewrite the server address so it reaches the host.
    k8s_api_server = os.environ.get("K8S_API_SERVER")
    if k8s_api_server:
        configuration = k8s_client.Configuration.get_default_copy()
        configuration.host = k8s_api_server
        # Self-signed certs are common for local clusters
        configuration.verify_ssl = False
        api_client = k8s_client.ApiClient(configuration)
        return k8s_client.CoreV1Api(api_client)

    return k8s_client.CoreV1Api()


def _wait_for_kubeconfig(timeout: int = 30) -> None:
    """Wait for kubeconfig file if configured, then continue with fallback support."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(KUBECONFIG_PATH):
            if os.path.isfile(KUBECONFIG_PATH):
                logger.info(f"Found kubeconfig file at {KUBECONFIG_PATH}")
                return
            if os.path.isdir(KUBECONFIG_PATH):
                raise RuntimeError(f"Kubeconfig path is a directory. Please mount a kubeconfig file at {KUBECONFIG_PATH}.")
            raise RuntimeError(f"Kubeconfig path exists but is not a regular file: {KUBECONFIG_PATH}")
        logger.info(f"Waiting for kubeconfig at {KUBECONFIG_PATH} …")
        time.sleep(2)
    logger.warning(f"Kubeconfig not found at {KUBECONFIG_PATH} after {timeout}s; will attempt in-cluster Kubernetes config")


def _ensure_namespace() -> None:
    """Create the K8s namespace if it does not yet exist."""
    try:
        core_v1.read_namespace(K8S_NAMESPACE)
        logger.info(f"Namespace '{K8S_NAMESPACE}' already exists")
    except ApiException as exc:
        if exc.status == 404:
            ns = k8s_client.V1Namespace(
                metadata=k8s_client.V1ObjectMeta(
                    name=K8S_NAMESPACE,
                    labels={
                        "app.kubernetes.io/name": "deer-flow",
                        "app.kubernetes.io/component": "sandbox",
                    },
                )
            )
            core_v1.create_namespace(ns)
            logger.info(f"Created namespace '{K8S_NAMESPACE}'")
        else:
            raise


# ── FastAPI lifespan ─────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global core_v1
    _wait_for_kubeconfig()
    core_v1 = _init_k8s_client()
    _ensure_namespace()
    logger.info("Provisioner is ready (using host Kubernetes)")
    yield


app = FastAPI(title="DeerFlow Sandbox Provisioner", lifespan=lifespan)


@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        key = request.headers.get("X-API-Key", "")
        if not PROVISIONER_API_KEY or not secrets.compare_digest(key, PROVISIONER_API_KEY):
            logger.warning("provisioner auth rejected: %s %s", request.method, request.url.path)
            return Response(status_code=401, content="Unauthorized")
    return await call_next(request)


# ── Request / Response models ───────────────────────────────────────────


class ExtraMount(BaseModel):
    host_path: str
    container_path: str
    read_only: bool = False


class CreateSandboxRequest(BaseModel):
    sandbox_id: str
    thread_id: str | None = Field(default=None, pattern=SAFE_THREAD_ID_PATTERN)
    user_id: str = Field(default=DEFAULT_USER_ID, pattern=SAFE_USER_ID_PATTERN)
    extra_mounts: list[ExtraMount] = Field(default_factory=list)
    include_legacy_skills: bool = False
    # When true (and LARK_CLI_INIT_IMAGE is configured), provision the sandbox
    # lark-cli runtime via an init container + emptyDir instead of a runtime
    # hostPath/PVC extra mount.
    provision_lark_cli_runtime: bool = False
    # When true (and LARK_CLI_BROKER_IMAGE is configured), provision a lark-cli
    # broker sidecar (Pattern B, issue #4338): a shim in the sandbox forwards to
    # the sidecar, which holds the credentials — so the plaintext config/data are
    # mounted into the sidecar only, never the sandbox. Supersedes the runtime
    # binary + credential mounts when enabled.
    provision_lark_cli_broker: bool = False


class SandboxResponse(BaseModel):
    sandbox_id: str
    sandbox_url: str
    status: str


# ── K8s resource helpers ─────────────────────────────────────────────────


def _pod_name(sandbox_id: str) -> str:
    return f"sandbox-{sandbox_id}"


def _svc_name(sandbox_id: str) -> str:
    return f"sandbox-{sandbox_id}-svc"


def _sandbox_url(sandbox_id: str, node_port: int | None = None) -> str:
    """Build the sandbox access URL for the configured Service mode."""
    if SANDBOX_SERVICE_TYPE == "ClusterIP":
        return f"http://{_svc_name(sandbox_id)}.{K8S_NAMESPACE}.svc.cluster.local:{SANDBOX_CONTAINER_PORT}"
    if node_port is None:
        raise RuntimeError("node_port is required when SANDBOX_SERVICE_TYPE=NodePort")
    return f"http://{NODE_HOST}:{node_port}"


def _build_extra_volumes(extra_mounts: list[ExtraMount] | None = None) -> list[k8s_client.V1Volume]:
    volumes: list[k8s_client.V1Volume] = []
    for index, mount in enumerate(_validated_extra_mounts(extra_mounts)):
        if USERDATA_PVC_NAME:
            volumes.append(
                k8s_client.V1Volume(
                    name=_extra_mount_volume_name(index),
                    persistent_volume_claim=k8s_client.V1PersistentVolumeClaimVolumeSource(
                        claim_name=USERDATA_PVC_NAME,
                    ),
                )
            )
            continue

        volumes.append(
            k8s_client.V1Volume(
                name=_extra_mount_volume_name(index),
                host_path=k8s_client.V1HostPathVolumeSource(
                    path=mount.host_path,
                    type="Directory" if mount.read_only else "DirectoryOrCreate",
                ),
            )
        )
    return volumes


def _build_extra_volume_mounts(extra_mounts: list[ExtraMount] | None = None) -> list[k8s_client.V1VolumeMount]:
    mounts: list[k8s_client.V1VolumeMount] = []
    for index, mount in enumerate(_validated_extra_mounts(extra_mounts)):
        volume_mount = k8s_client.V1VolumeMount(
            name=_extra_mount_volume_name(index),
            mount_path=mount.container_path,
            read_only=mount.read_only,
        )
        if USERDATA_PVC_NAME:
            volume_mount.sub_path = _extra_mount_pvc_sub_path(mount.host_path)
        mounts.append(volume_mount)
    return mounts


def _build_volumes(
    thread_id: str,
    user_id: str = DEFAULT_USER_ID,
    *,
    include_legacy_skills: bool = False,
    extra_mounts: list[ExtraMount] | None = None,
    provision_lark_cli_runtime: bool = False,
    provision_lark_cli_broker: bool = False,
) -> list[k8s_client.V1Volume]:
    """Build volume list: PVC when configured, otherwise hostPath.

    Skills are split into public, per-user custom, and legacy (global-custom)
    volumes so that ``/mnt/skills/{public,custom,legacy}/`` paths resolve
    correctly inside the sandbox — matching the hostPath layout produced by
    ``LocalSandboxProvider`` and ``AioSandboxProvider``.
    """
    volumes: list[k8s_client.V1Volume] = []
    del include_legacy_skills  # retained for request compatibility

    # ── Skills volumes ────────────────────────────────────────────────

    if SKILLS_PVC_NAME:
        # PVC mode: three-way subPath not yet supported; fall back to
        # single-volume mount for backward compatibility.
        logger.warning("SKILLS_PVC_NAME is set — three-way skills layout is not supported in PVC mode yet; falling back to single /mnt/skills mount")
        volumes.append(
            k8s_client.V1Volume(
                name="skills",
                persistent_volume_claim=k8s_client.V1PersistentVolumeClaimVolumeSource(
                    claim_name=SKILLS_PVC_NAME,
                    read_only=True,
                ),
            )
        )
    else:
        # hostPath mode: three-way layout
        public_path = join_host_path(DEER_FLOW_HOST_BASE_DIR, "skills_view", "public")
        volumes.append(
            k8s_client.V1Volume(
                name="skills-public",
                host_path=k8s_client.V1HostPathVolumeSource(
                    path=public_path,
                    type="Directory",
                ),
            )
        )

        user_custom_path = join_host_path(
            DEER_FLOW_HOST_BASE_DIR,
            "users",
            user_id,
            "skills_view",
            "custom",
        )
        volumes.append(
            k8s_client.V1Volume(
                name="skills-custom",
                host_path=k8s_client.V1HostPathVolumeSource(
                    path=user_custom_path,
                    type="Directory",
                ),
            )
        )

        legacy_path = join_host_path(
            DEER_FLOW_HOST_BASE_DIR, "users", user_id, "skills_view", "legacy"
        )
        volumes.append(
            k8s_client.V1Volume(
                name="skills-legacy",
                host_path=k8s_client.V1HostPathVolumeSource(
                    path=legacy_path,
                    type="Directory",
                ),
            )
        )

    # ── User-data volume ──────────────────────────────────────────────

    if USERDATA_PVC_NAME:
        userdata_vol = k8s_client.V1Volume(
            name="user-data",
            persistent_volume_claim=k8s_client.V1PersistentVolumeClaimVolumeSource(
                claim_name=USERDATA_PVC_NAME,
            ),
        )
    else:
        userdata_vol = k8s_client.V1Volume(
            name="user-data",
            host_path=k8s_client.V1HostPathVolumeSource(
                path=join_host_path(THREADS_HOST_PATH, thread_id, "user-data"),
                type="DirectoryOrCreate",
            ),
        )

    volumes.append(userdata_vol)
    volumes.extend(
        _build_extra_volumes(
            _runtime_provided_extra_mounts(
                extra_mounts,
                provision_lark_cli_runtime=provision_lark_cli_runtime,
                provision_lark_cli_broker=provision_lark_cli_broker,
            )
        )
    )
    # The runtime emptyDir is shared by the init container (writer) and the
    # sandbox container (reader) in both Pattern A and Pattern B (shim).
    if _lark_cli_runtime_enabled(provision_lark_cli_runtime) or _lark_cli_broker_enabled(provision_lark_cli_broker):
        volumes.append(
            k8s_client.V1Volume(
                name=LARK_CLI_RUNTIME_VOLUME_NAME,
                empty_dir=k8s_client.V1EmptyDirVolumeSource(),
            )
        )
    # Pattern B: the config/data credential volumes go to the broker sidecar only.
    if _lark_cli_broker_enabled(provision_lark_cli_broker):
        credential_mounts = _lark_broker_credential_mounts(extra_mounts)
        for container_path, volume_name in (
            (LARK_CLI_CONFIG_CONTAINER_PATH, LARK_BROKER_CONFIG_VOLUME_NAME),
            (LARK_CLI_DATA_CONTAINER_PATH, LARK_BROKER_DATA_VOLUME_NAME),
        ):
            mount = credential_mounts.get(container_path)
            if mount is None:
                continue
            if USERDATA_PVC_NAME:
                volumes.append(
                    k8s_client.V1Volume(
                        name=volume_name,
                        persistent_volume_claim=k8s_client.V1PersistentVolumeClaimVolumeSource(
                            claim_name=USERDATA_PVC_NAME,
                        ),
                    )
                )
            else:
                volumes.append(
                    k8s_client.V1Volume(
                        name=volume_name,
                        host_path=k8s_client.V1HostPathVolumeSource(
                            path=mount.host_path,
                            type="Directory" if mount.read_only else "DirectoryOrCreate",
                        ),
                    )
                )
    return volumes


def _build_volume_mounts(
    thread_id: str,
    user_id: str = DEFAULT_USER_ID,
    *,
    include_legacy_skills: bool = False,
    extra_mounts: list[ExtraMount] | None = None,
    provision_lark_cli_runtime: bool = False,
    provision_lark_cli_broker: bool = False,
) -> list[k8s_client.V1VolumeMount]:
    """Build volume mount list, mirroring three-way skills layout.

    Skills are mounted to ``/mnt/skills/{public,custom,legacy}/`` so that
    category-aware ``Skill.get_container_path()`` paths resolve correctly.
    PVC mode falls back to a single ``/mnt/skills`` mount and can optionally
    scope that mount with ``SKILLS_PVC_SUBPATH_TEMPLATE``.
    """
    mounts: list[k8s_client.V1VolumeMount] = []
    del include_legacy_skills  # retained for request compatibility

    if SKILLS_PVC_NAME:
        skills_mount = k8s_client.V1VolumeMount(
            name="skills",
            mount_path="/mnt/skills",
            read_only=True,
        )
        if SKILLS_PVC_SUBPATH_TEMPLATE:
            skills_mount.sub_path = SKILLS_PVC_SUBPATH_TEMPLATE.format(
                user_id=user_id,
                thread_id=thread_id,
            )
        mounts.append(skills_mount)
    else:
        mounts.extend(
            [
                k8s_client.V1VolumeMount(
                    name="skills-public",
                    mount_path="/mnt/skills/public",
                    read_only=True,
                ),
                k8s_client.V1VolumeMount(
                    name="skills-custom",
                    mount_path="/mnt/skills/custom",
                    read_only=True,
                ),
                k8s_client.V1VolumeMount(
                    name="skills-legacy",
                    mount_path="/mnt/skills/legacy",
                    read_only=True,
                ),
            ]
        )

    userdata_mount = k8s_client.V1VolumeMount(
        name="user-data",
        mount_path="/mnt/user-data",
        read_only=False,
    )
    if USERDATA_PVC_NAME:
        userdata_mount.sub_path = f"deer-flow/users/{user_id}/threads/{thread_id}/user-data"
    mounts.append(userdata_mount)
    mounts.extend(
        _build_extra_volume_mounts(
            _runtime_provided_extra_mounts(
                extra_mounts,
                provision_lark_cli_runtime=provision_lark_cli_runtime,
                provision_lark_cli_broker=provision_lark_cli_broker,
            )
        )
    )
    # Sandbox reads the runtime dir (real binary in Pattern A, shim in Pattern B).
    if _lark_cli_runtime_enabled(provision_lark_cli_runtime) or _lark_cli_broker_enabled(provision_lark_cli_broker):
        mounts.append(
            k8s_client.V1VolumeMount(
                name=LARK_CLI_RUNTIME_VOLUME_NAME,
                mount_path=LARK_CLI_RUNTIME_CONTAINER_PATH,
                read_only=True,
            )
        )

    return mounts


def _build_lark_cli_init_containers(
    provision_lark_cli_runtime: bool,
    provision_lark_cli_broker: bool = False,
) -> list[k8s_client.V1Container]:
    """Init container that stages the lark-cli runtime into the shared emptyDir.

    Pattern B (broker) supersedes Pattern A: the broker image's ``install-shim``
    mode writes the forwarding shim; Pattern A's init image copies the real
    binary layout.
    """
    runtime_mount = k8s_client.V1VolumeMount(
        name=LARK_CLI_RUNTIME_VOLUME_NAME,
        mount_path=LARK_CLI_RUNTIME_CONTAINER_PATH,
        read_only=False,
    )
    secure = k8s_client.V1SecurityContext(privileged=False, allow_privilege_escalation=False)
    if _lark_cli_broker_enabled(provision_lark_cli_broker):
        return [
            k8s_client.V1Container(
                name="lark-cli-shim-init",
                image=LARK_CLI_BROKER_IMAGE,
                image_pull_policy="IfNotPresent",
                args=["install-shim", LARK_CLI_RUNTIME_CONTAINER_PATH],
                env=[k8s_client.V1EnvVar(name="LARK_CLI_RUNTIME_DEST", value=LARK_CLI_RUNTIME_CONTAINER_PATH)],
                volume_mounts=[runtime_mount],
                security_context=secure,
            )
        ]
    if not _lark_cli_runtime_enabled(provision_lark_cli_runtime):
        return []
    return [
        k8s_client.V1Container(
            name="lark-cli-init",
            image=LARK_CLI_INIT_IMAGE,
            image_pull_policy="IfNotPresent",
            env=[
                k8s_client.V1EnvVar(
                    name="LARK_CLI_RUNTIME_DEST",
                    value=LARK_CLI_RUNTIME_CONTAINER_PATH,
                )
            ],
            volume_mounts=[runtime_mount],
            security_context=secure,
        )
    ]


def _build_lark_cli_broker_sidecars(
    provision_lark_cli_broker: bool,
    extra_mounts: list[ExtraMount] | None,
) -> list[k8s_client.V1Container]:
    """Broker sidecar that holds lark-cli + the per-user credentials (Pattern B).

    The config/data credential dirs are mounted **only** here (never on the
    sandbox container), so the plaintext app secret / OAuth tokens stay out of
    the sandbox filesystem. The broker serves the command surface on loopback.
    """
    if not _lark_cli_broker_enabled(provision_lark_cli_broker):
        return []
    credential_mounts = _lark_broker_credential_mounts(extra_mounts)
    volume_mounts: list[k8s_client.V1VolumeMount] = []
    for container_path, volume_name, sidecar_path in (
        (LARK_CLI_CONFIG_CONTAINER_PATH, LARK_BROKER_CONFIG_VOLUME_NAME, LARK_BROKER_SIDECAR_CONFIG_PATH),
        (LARK_CLI_DATA_CONTAINER_PATH, LARK_BROKER_DATA_VOLUME_NAME, LARK_BROKER_SIDECAR_DATA_PATH),
    ):
        mount = credential_mounts.get(container_path)
        if mount is None:
            continue
        sidecar_mount = k8s_client.V1VolumeMount(
            name=volume_name,
            mount_path=sidecar_path,
            read_only=mount.read_only,
        )
        if USERDATA_PVC_NAME:
            sidecar_mount.sub_path = _extra_mount_pvc_sub_path(mount.host_path)
        volume_mounts.append(sidecar_mount)
    broker_env = [
        k8s_client.V1EnvVar(name="LARKSUITE_CLI_CONFIG_DIR", value=LARK_BROKER_SIDECAR_CONFIG_PATH),
        k8s_client.V1EnvVar(name="LARKSUITE_CLI_DATA_DIR", value=LARK_BROKER_SIDECAR_DATA_PATH),
    ]
    # Forward the optional subcommand denylist so the broker refuses secret-dump
    # subcommands (issue #4338 hardening); omitted when unset ⇒ nothing blocked.
    if LARK_CLI_BROKER_DENY_SUBCOMMANDS:
        broker_env.append(
            k8s_client.V1EnvVar(
                name="DEERFLOW_LARK_BROKER_DENY_SUBCOMMANDS",
                value=LARK_CLI_BROKER_DENY_SUBCOMMANDS,
            )
        )
    return [
        k8s_client.V1Container(
            name="lark-cli-broker",
            image=LARK_CLI_BROKER_IMAGE,
            image_pull_policy="IfNotPresent",
            args=["serve"],
            env=broker_env,
            volume_mounts=volume_mounts,
            security_context=k8s_client.V1SecurityContext(
                privileged=False,
                allow_privilege_escalation=False,
            ),
        )
    ]


def _build_pod(
    sandbox_id: str,
    thread_id: str,
    user_id: str = DEFAULT_USER_ID,
    *,
    include_legacy_skills: bool = False,
    extra_mounts: list[ExtraMount] | None = None,
    provision_lark_cli_runtime: bool = False,
    provision_lark_cli_broker: bool = False,
) -> k8s_client.V1Pod:
    """Construct a Pod manifest for a single sandbox."""
    init_containers = (
        _build_lark_cli_init_containers(provision_lark_cli_runtime, provision_lark_cli_broker) or None
    )
    return k8s_client.V1Pod(
        metadata=k8s_client.V1ObjectMeta(
            name=_pod_name(sandbox_id),
            namespace=K8S_NAMESPACE,
            labels={
                "app": "deer-flow-sandbox",
                "sandbox-id": sandbox_id,
                "app.kubernetes.io/name": "deer-flow",
                "app.kubernetes.io/component": "sandbox",
            },
        ),
        spec=k8s_client.V1PodSpec(
            containers=[
                k8s_client.V1Container(
                    name="sandbox",
                    image=SANDBOX_IMAGE,
                    image_pull_policy="IfNotPresent",
                    env=(
                        [k8s_client.V1EnvVar(name="DEERFLOW_LARK_BROKER_URL", value=LARK_BROKER_URL)]
                        if _lark_cli_broker_enabled(provision_lark_cli_broker)
                        else None
                    ),
                    ports=[
                        k8s_client.V1ContainerPort(
                            name="http",
                            container_port=SANDBOX_CONTAINER_PORT,
                            protocol="TCP",
                        )
                    ],
                    readiness_probe=k8s_client.V1Probe(
                        http_get=k8s_client.V1HTTPGetAction(
                            path="/v1/sandbox",
                            port=SANDBOX_CONTAINER_PORT,
                        ),
                        initial_delay_seconds=5,
                        period_seconds=5,
                        timeout_seconds=3,
                        failure_threshold=3,
                    ),
                    liveness_probe=k8s_client.V1Probe(
                        http_get=k8s_client.V1HTTPGetAction(
                            path="/v1/sandbox",
                            port=SANDBOX_CONTAINER_PORT,
                        ),
                        initial_delay_seconds=10,
                        period_seconds=10,
                        timeout_seconds=3,
                        failure_threshold=3,
                    ),
                    resources=k8s_client.V1ResourceRequirements(
                        requests={
                            "cpu": "100m",
                            "memory": "256Mi",
                            "ephemeral-storage": "500Mi",
                        },
                        limits={
                            "cpu": "1000m",
                            "memory": "1Gi",
                            "ephemeral-storage": "500Mi",
                        },
                    ),
                    volume_mounts=_build_volume_mounts(
                        thread_id,
                        user_id=user_id,
                        include_legacy_skills=include_legacy_skills,
                        extra_mounts=extra_mounts,
                        provision_lark_cli_runtime=provision_lark_cli_runtime,
                        provision_lark_cli_broker=provision_lark_cli_broker,
                    ),
                    security_context=k8s_client.V1SecurityContext(
                        privileged=False,
                        allow_privilege_escalation=True,
                    ),
                ),
                *_build_lark_cli_broker_sidecars(provision_lark_cli_broker, extra_mounts),
            ],
            init_containers=init_containers,
            volumes=_build_volumes(
                thread_id,
                user_id=user_id,
                include_legacy_skills=include_legacy_skills,
                extra_mounts=extra_mounts,
                provision_lark_cli_runtime=provision_lark_cli_runtime,
                provision_lark_cli_broker=provision_lark_cli_broker,
            ),
            restart_policy="Always",
        ),
    )


def _build_service(sandbox_id: str) -> k8s_client.V1Service:
    """Construct a Service manifest for the configured access mode."""
    return k8s_client.V1Service(
        metadata=k8s_client.V1ObjectMeta(
            name=_svc_name(sandbox_id),
            namespace=K8S_NAMESPACE,
            labels={
                "app": "deer-flow-sandbox",
                "sandbox-id": sandbox_id,
                "app.kubernetes.io/name": "deer-flow",
                "app.kubernetes.io/component": "sandbox",
            },
        ),
        spec=k8s_client.V1ServiceSpec(
            type=SANDBOX_SERVICE_TYPE,
            ports=[
                k8s_client.V1ServicePort(
                    name="http",
                    port=SANDBOX_CONTAINER_PORT,
                    target_port=SANDBOX_CONTAINER_PORT,
                    protocol="TCP",
                )
            ],
            selector={
                "sandbox-id": sandbox_id,
            },
        ),
    )


def _url_from_service(svc, sandbox_id: str) -> str | None:
    """Build the backend-facing sandbox URL from an already-fetched Service."""
    if SANDBOX_SERVICE_TYPE == "ClusterIP":
        return _sandbox_url(sandbox_id)

    for port in svc.spec.ports or []:
        if port.name == "http" and port.node_port:
            return _sandbox_url(sandbox_id, node_port=port.node_port)
    return None


def _sandbox_access_url(sandbox_id: str, *, tolerate_read_errors: bool = False) -> str | None:
    """Read the sandbox Service and return its backend-facing URL when ready."""
    try:
        svc = core_v1.read_namespaced_service(_svc_name(sandbox_id), K8S_NAMESPACE)
    except ApiException as exc:
        if exc.status == 404:
            return None
        if tolerate_read_errors and exc.status not in {401, 403}:
            logger.warning(
                "Transient error reading Service %s: status=%s reason=%s",
                _svc_name(sandbox_id),
                exc.status,
                exc.reason,
            )
            return None
        raise

    return _url_from_service(svc, sandbox_id)


def _get_pod_phase(sandbox_id: str) -> str:
    """Return the Pod phase (Pending / Running / Succeeded / Failed / Unknown)."""
    try:
        pod = core_v1.read_namespaced_pod(_pod_name(sandbox_id), K8S_NAMESPACE)
        return pod.status.phase or "Unknown"
    except ApiException:
        return "NotFound"


# ── API endpoints ────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    """Provisioner health check."""
    return {"status": "ok"}


@app.get("/api/capabilities")
async def capabilities():
    """Report provisioner-side capabilities the Gateway cannot infer statically.

    ``lark_cli_init_image`` / ``lark_cli_broker_image`` reflect whether a lark-cli
    init image (Pattern A) / broker image (Pattern B) is configured, which the
    Gateway surfaces as the Lark integration sandbox-runtime readiness signal so a
    green UI can't hide a chat-time ``command not found``.
    """
    return {
        "lark_cli_init_image": bool(LARK_CLI_INIT_IMAGE),
        "lark_cli_broker_image": bool(LARK_CLI_BROKER_IMAGE),
    }


@app.post("/api/sandboxes", response_model=SandboxResponse)
def create_sandbox(req: CreateSandboxRequest):
    """Create a sandbox Pod + Service for *sandbox_id*.

    If the sandbox already exists, returns the existing information
    (idempotent).
    """
    sandbox_id = req.sandbox_id
    thread_id = req.thread_id or sandbox_id
    user_id = req.user_id
    include_legacy_skills = req.include_legacy_skills
    provision_lark_cli_runtime = req.provision_lark_cli_runtime
    provision_lark_cli_broker = req.provision_lark_cli_broker

    logger.info(
        "Received request to create sandbox '%s' for thread '%s' user '%s' include_legacy_skills=%s provision_lark_cli_runtime=%s provision_lark_cli_broker=%s",
        sandbox_id,
        thread_id,
        user_id,
        include_legacy_skills,
        _lark_cli_runtime_enabled(provision_lark_cli_runtime),
        _lark_cli_broker_enabled(provision_lark_cli_broker),
    )

    # ── Fast path: sandbox already exists ────────────────────────────
    existing_url = _sandbox_access_url(sandbox_id, tolerate_read_errors=True)
    if existing_url:
        return SandboxResponse(
            sandbox_id=sandbox_id,
            sandbox_url=existing_url,
            status=_get_pod_phase(sandbox_id),
        )

    # ── Create Pod ───────────────────────────────────────────────────
    try:
        core_v1.create_namespaced_pod(
            K8S_NAMESPACE,
            _build_pod(
                sandbox_id,
                thread_id,
                user_id=user_id,
                include_legacy_skills=include_legacy_skills,
                extra_mounts=req.extra_mounts,
                provision_lark_cli_runtime=provision_lark_cli_runtime,
                provision_lark_cli_broker=provision_lark_cli_broker,
            ),
        )
        logger.info(f"Created Pod {_pod_name(sandbox_id)}")
    except ApiException as exc:
        if exc.status != 409:  # 409 = AlreadyExists
            raise HTTPException(status_code=500, detail=f"Pod creation failed: {exc.reason}")

    # ── Create Service ───────────────────────────────────────────────
    try:
        core_v1.create_namespaced_service(K8S_NAMESPACE, _build_service(sandbox_id))
        logger.info(f"Created Service {_svc_name(sandbox_id)}")
    except ApiException as exc:
        if exc.status != 409:
            # Roll back the Pod on failure
            try:
                core_v1.delete_namespaced_pod(_pod_name(sandbox_id), K8S_NAMESPACE)
            except ApiException:
                pass
            raise HTTPException(status_code=500, detail=f"Service creation failed: {exc.reason}")

    # ── Wait until the Service has a usable access URL ───────────────
    sandbox_url: str | None = None
    for _ in range(20):
        sandbox_url = _sandbox_access_url(sandbox_id, tolerate_read_errors=True)
        if sandbox_url:
            break
        time.sleep(0.5)

    if not sandbox_url:
        raise HTTPException(status_code=500, detail="Service access URL was not available in time")

    return SandboxResponse(
        sandbox_id=sandbox_id,
        sandbox_url=sandbox_url,
        status=_get_pod_phase(sandbox_id),
    )


@app.delete("/api/sandboxes/{sandbox_id}")
def destroy_sandbox(sandbox_id: str):
    """Destroy a sandbox Pod + Service."""
    errors: list[str] = []

    # Delete Service
    try:
        core_v1.delete_namespaced_service(_svc_name(sandbox_id), K8S_NAMESPACE)
        logger.info(f"Deleted Service {_svc_name(sandbox_id)}")
    except ApiException as exc:
        if exc.status != 404:
            errors.append(f"service: {exc.reason}")

    # Delete Pod
    try:
        core_v1.delete_namespaced_pod(_pod_name(sandbox_id), K8S_NAMESPACE)
        logger.info(f"Deleted Pod {_pod_name(sandbox_id)}")
    except ApiException as exc:
        if exc.status != 404:
            errors.append(f"pod: {exc.reason}")

    if errors:
        raise HTTPException(status_code=500, detail=f"Partial cleanup: {', '.join(errors)}")

    return {"ok": True, "sandbox_id": sandbox_id}


@app.get("/api/sandboxes/{sandbox_id}", response_model=SandboxResponse)
def get_sandbox(sandbox_id: str):
    """Return current status and URL for a sandbox."""
    sandbox_url = _sandbox_access_url(sandbox_id)
    if not sandbox_url:
        raise HTTPException(status_code=404, detail=f"Sandbox '{sandbox_id}' not found")

    return SandboxResponse(
        sandbox_id=sandbox_id,
        sandbox_url=sandbox_url,
        status=_get_pod_phase(sandbox_id),
    )


@app.get("/api/sandboxes")
def list_sandboxes():
    """List every sandbox currently managed in the namespace."""
    try:
        services = core_v1.list_namespaced_service(
            K8S_NAMESPACE,
            label_selector="app=deer-flow-sandbox",
        )
    except ApiException as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list services: {exc.reason}")

    sandboxes: list[SandboxResponse] = []
    for svc in services.items:
        sid = (svc.metadata.labels or {}).get("sandbox-id")
        if not sid:
            continue
        sandbox_url = _url_from_service(svc, sid)
        if not sandbox_url:
            continue
        sandboxes.append(
            SandboxResponse(
                sandbox_id=sid,
                sandbox_url=sandbox_url,
                status=_get_pod_phase(sid),
            )
        )

    return {"sandboxes": sandboxes, "count": len(sandboxes)}
