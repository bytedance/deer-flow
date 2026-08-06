"""Remote sandbox backend — delegates Pod lifecycle to the provisioner service.

The provisioner dynamically creates per-sandbox-id Pods + NodePort Services
in k3s.  The backend accesses sandbox pods directly via ``k3s:{NodePort}``.

Architecture:
    ┌────────────┐  HTTP   ┌─────────────┐  K8s API  ┌──────────┐
    │ this file  │ ──────▸ │ provisioner │ ────────▸ │   k3s    │
    │ (backend)  │         │ :8002       │           │ :6443    │
    └────────────┘         └─────────────┘           └─────┬────┘
                                                           │ creates
                           ┌─────────────┐           ┌─────▼──────┐
                           │   backend   │ ────────▸ │  sandbox   │
                           │             │  direct   │  Pod(s)    │
                           └─────────────┘ k3s:NPort └────────────┘
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path, PureWindowsPath

import requests

from deerflow.runtime.user_context import DEFAULT_USER_ID, get_effective_user_id
from deerflow.skills.storage import user_should_see_legacy_skills

from .backend import SandboxBackend
from .sandbox_info import SandboxInfo

logger = logging.getLogger(__name__)

_PROVISIONER_EXTRA_MOUNT_PATHS = {
    "/mnt/user-data/.upload-conversions",
    "/mnt/acp-workspace",
    "/mnt/skills/custom",
    "/mnt/skills/integrations",
    "/mnt/integrations/lark-cli/config",
    "/mnt/integrations/lark-cli/data",
    "/mnt/integrations/lark-cli/runtime",
}

_UPLOADS_CONTAINER_PATH = "/mnt/user-data/uploads"
_UPLOAD_CONVERSIONS_CONTAINER_PATH = "/mnt/user-data/.upload-conversions"
_UPLOAD_MOUNT_CONTRACT_VERSION = 2
_CAPABILITY_LEGACY_REFRESH_SECONDS = 30.0
_CAPABILITY_CURRENT_REFRESH_SECONDS = 300.0
_CAPABILITY_RETRY_MAX_SECONDS = 30.0

_LARK_CLI_RUNTIME_CONTAINER_PATH = "/mnt/integrations/lark-cli/runtime"
_LARK_CLI_CONFIG_CONTAINER_PATH = "/mnt/integrations/lark-cli/config"
_LARK_CLI_DATA_CONTAINER_PATH = "/mnt/integrations/lark-cli/data"


def _provisioner_extra_mounts_payload(
    extra_mounts: list[tuple[str, str, bool]] | None,
    *,
    provision_lark_cli_runtime: bool = False,
    provision_lark_cli_broker: bool = False,
) -> list[dict[str, object]]:
    """Return only extra mounts the provisioner knows how to recreate safely.

    When ``provision_lark_cli_runtime`` is set, the provisioner supplies the
    lark-cli runtime via an init container + emptyDir, so the runtime extra mount
    is dropped here to avoid a colliding hostPath/PVC mount at the same path. The
    per-user config/data credential mounts are still forwarded (they are mounted
    into the sandbox in Pattern A).

    When ``provision_lark_cli_broker`` is set (Pattern B, issue #4338), the
    provisioner runs a broker sidecar that holds the credentials, so the
    config/data mounts are **forwarded** (the provisioner wires them into the
    sidecar, not the sandbox) while the runtime mount is dropped. Nothing changes
    in this payload beyond keeping config/data available for the provisioner to
    place; the runtime entry is dropped in both modes.
    """
    if not extra_mounts:
        return []

    drop_runtime = provision_lark_cli_runtime or provision_lark_cli_broker

    uploads_host_path = next(
        (host_path for host_path, container_path, _read_only in extra_mounts if container_path == _UPLOADS_CONTAINER_PATH),
        None,
    )

    def expected_conversion_host_path() -> str | None:
        if uploads_host_path is None:
            return None
        if re.match(r"^[A-Za-z]:[\\/]", uploads_host_path) or uploads_host_path.startswith("\\\\") or "\\" in uploads_host_path:
            return str(PureWindowsPath(uploads_host_path).parent / ".upload-conversions")
        return str(Path(uploads_host_path).parent / ".upload-conversions")

    expected_conversion_path = expected_conversion_host_path()

    payload: list[dict[str, object]] = []
    for host_path, container_path, read_only in extra_mounts:
        if container_path not in _PROVISIONER_EXTRA_MOUNT_PATHS:
            continue
        if container_path == _UPLOAD_CONVERSIONS_CONTAINER_PATH:
            if not read_only:
                raise ValueError("Upload conversion mount must be read-only")
            if expected_conversion_path is None:
                raise ValueError("Upload conversion mount requires the matching uploads mount")
            if re.match(r"^[A-Za-z]:[\\/]", expected_conversion_path) or expected_conversion_path.startswith("\\\\"):
                matches_expected = PureWindowsPath(host_path) == PureWindowsPath(expected_conversion_path)
            else:
                matches_expected = os.path.normpath(host_path) == os.path.normpath(expected_conversion_path)
            if not matches_expected:
                raise ValueError("Upload conversion mount must belong to the same thread data directory")
        if drop_runtime and container_path == _LARK_CLI_RUNTIME_CONTAINER_PATH:
            continue
        payload.append(
            {
                "host_path": host_path,
                "container_path": container_path,
                "read_only": read_only,
            }
        )
    return payload


class RemoteSandboxBackend(SandboxBackend):
    """Backend that delegates sandbox lifecycle to the provisioner service.

    All Pod creation, destruction, and discovery are handled by the
    provisioner.  This backend is a thin HTTP client.

    Typical config.yaml::

        sandbox:
          use: deerflow.community.aio_sandbox:AioSandboxProvider
          provisioner_url: http://provisioner:8002
          provisioner_api_key: $PROVISIONER_API_KEY
    """

    def __init__(self, provisioner_url: str, api_key: str = ""):
        """Initialize with the provisioner service URL and optional API key.

        Args:
            provisioner_url: URL of the provisioner service
                             (e.g., ``http://provisioner:8002``).
            api_key: Value sent as ``X-API-Key`` header on every request.
                     Leave empty to send no authentication header.
        """
        self._provisioner_url = provisioner_url.rstrip("/")
        self._api_key = api_key
        self._mount_contract_version = 0
        self._mount_contract_capability_known = False
        self._capability_probe_failures = 0
        self._capability_next_probe_at = time.monotonic() + 1.0
        self._capability_probe_lock = threading.Lock()

    @property
    def provisioner_url(self) -> str:
        return self._provisioner_url

    def _auth_headers(self) -> dict[str, str]:
        return {"X-API-Key": self._api_key} if self._api_key else {}

    @property
    def mount_contract_version(self) -> int:
        """Provisioner mount contract negotiated during provider startup."""
        return self._mount_contract_version

    @property
    def mount_contract_capability_known(self) -> bool:
        """Whether the peer definitively answered capability negotiation."""
        return self._mount_contract_capability_known

    @property
    def requires_create_validation(self) -> bool:
        """Require idempotent POST so the Provisioner checks requested mounts."""
        return True

    def probe_capabilities(self) -> None:
        """Negotiate optional Provisioner capabilities without breaking old peers."""
        with self._capability_probe_lock:
            self._probe_capabilities_locked()

    def refresh_capabilities_if_stale(self) -> bool:
        """Refresh a legacy/unavailable capability result after its retry window.

        Returns ``True`` when this call performed the probe.  The non-blocking
        lock prevents a burst of concurrent acquires from serially repeating the
        same network request after one cached result expires.
        """
        now = time.monotonic()
        if now < self._capability_next_probe_at:
            return False
        if not self._capability_probe_lock.acquire(blocking=False):
            return False
        try:
            if time.monotonic() < self._capability_next_probe_at:
                return False
            self._probe_capabilities_locked()
            return True
        finally:
            self._capability_probe_lock.release()

    def _probe_capabilities_locked(self) -> None:
        """Probe while ``_capability_probe_lock`` is held."""
        try:
            response = requests.get(
                f"{self._provisioner_url}/api/capabilities",
                headers=self._auth_headers(),
                timeout=5,
            )
            if getattr(response, "status_code", None) == 404:
                self._mount_contract_version = 0
                self._mount_contract_capability_known = True
                self._capability_probe_failures = 0
                self._capability_next_probe_at = time.monotonic() + _CAPABILITY_LEGACY_REFRESH_SECONDS
                return
            response.raise_for_status()
            payload = response.json()
            version = payload.get("mount_contract_version", 0) if isinstance(payload, dict) else 0
            self._mount_contract_version = version if isinstance(version, int) and version >= 0 else 0
            self._mount_contract_capability_known = True
            self._capability_probe_failures = 0
            refresh_seconds = _CAPABILITY_CURRENT_REFRESH_SECONDS if self._mount_contract_version >= _UPLOAD_MOUNT_CONTRACT_VERSION else _CAPABILITY_LEGACY_REFRESH_SECONDS
            self._capability_next_probe_at = time.monotonic() + refresh_seconds
        except (requests.RequestException, ValueError, TypeError):
            self._mount_contract_version = 0
            self._mount_contract_capability_known = False
            self._capability_probe_failures += 1
            retry_seconds = min(
                _CAPABILITY_RETRY_MAX_SECONDS,
                float(2 ** (self._capability_probe_failures - 1)),
            )
            self._capability_next_probe_at = time.monotonic() + retry_seconds
            logger.warning("Provisioner mount capabilities are unavailable; mounted thread data will fail closed until compatibility can be verified")

    # ── SandboxBackend interface ──────────────────────────────────────────

    def create(
        self,
        thread_id: str | None,
        sandbox_id: str,
        extra_mounts: list[tuple[str, str, bool]] | None = None,
        *,
        user_id: str | None = None,
        provision_lark_cli_runtime: bool = False,
        provision_lark_cli_broker: bool = False,
    ) -> SandboxInfo:
        """Create a sandbox Pod + Service via the provisioner.

        Calls ``POST /api/sandboxes`` which creates a dedicated Pod +
        NodePort Service in k3s.
        """
        if self._mount_contract_version < _UPLOAD_MOUNT_CONTRACT_VERSION:
            self.refresh_capabilities_if_stale()
        effective_user_id = user_id or get_effective_user_id()
        if self._mount_contract_version < _UPLOAD_MOUNT_CONTRACT_VERSION and thread_id is not None and effective_user_id != DEFAULT_USER_ID:
            raise RuntimeError(f"Provisioner mount contract v{self._mount_contract_version} cannot isolate user {effective_user_id!r}; upgrade the Provisioner before creating authenticated-user sandboxes")
        return self._provisioner_create(
            thread_id,
            sandbox_id,
            extra_mounts,
            user_id=user_id,
            provision_lark_cli_runtime=provision_lark_cli_runtime,
            provision_lark_cli_broker=provision_lark_cli_broker,
        )

    def destroy(self, info: SandboxInfo) -> None:
        """Destroy a sandbox Pod + Service via the provisioner."""
        self._provisioner_destroy(info.sandbox_id)

    def is_alive(self, info: SandboxInfo) -> bool:
        """Check whether the sandbox Pod is running."""
        return self._provisioner_is_alive(info.sandbox_id)

    def discover(self, sandbox_id: str) -> SandboxInfo | None:
        """Discover an existing sandbox via the provisioner.

        Calls ``GET /api/sandboxes/{sandbox_id}`` and returns info if
        the Pod exists.
        """
        return self._provisioner_discover(sandbox_id)

    def list_running(self) -> list[SandboxInfo]:
        """Return all sandboxes currently managed by the provisioner.

        Calls ``GET /api/sandboxes`` so that ``AioSandboxProvider._reconcile_orphans()``
        can adopt pods that were created by a previous process and were never
        explicitly destroyed.
        Without this, a process restart silently orphans all existing k8s Pods —
        they stay running forever because the idle checker only
        tracks in-process state.
        """
        return self._provisioner_list()

    # ── Provisioner API calls ─────────────────────────────────────────────

    def _provisioner_list(self) -> list[SandboxInfo]:
        """GET /api/sandboxes → list all running sandboxes."""
        try:
            resp = requests.get(f"{self._provisioner_url}/api/sandboxes", headers=self._auth_headers(), timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                logger.warning("Provisioner list_running returned non-dict payload: %r", type(data))
                return []

            sandboxes = data.get("sandboxes", [])
            if not isinstance(sandboxes, list):
                logger.warning("Provisioner list_running returned non-list sandboxes: %r", type(sandboxes))
                return []

            infos: list[SandboxInfo] = []
            for sandbox in sandboxes:
                if not isinstance(sandbox, dict):
                    logger.warning("Provisioner list_running entry is not a dict: %r", type(sandbox))
                    continue

                sandbox_id = sandbox.get("sandbox_id")
                sandbox_url = sandbox.get("sandbox_url")
                if isinstance(sandbox_id, str) and sandbox_id and isinstance(sandbox_url, str) and sandbox_url:
                    infos.append(SandboxInfo(sandbox_id=sandbox_id, sandbox_url=sandbox_url))

            logger.info("Provisioner list_running: %d sandbox(es) found", len(infos))
            return infos
        except requests.RequestException as exc:
            logger.warning("Provisioner list_running failed: %s", exc)
            return []

    def _provisioner_create(
        self,
        thread_id: str | None,
        sandbox_id: str,
        extra_mounts: list[tuple[str, str, bool]] | None = None,
        *,
        user_id: str | None = None,
        provision_lark_cli_runtime: bool = False,
        provision_lark_cli_broker: bool = False,
    ) -> SandboxInfo:
        """POST /api/sandboxes → create Pod + Service."""
        effective_user_id = user_id or get_effective_user_id()
        include_legacy_skills = user_should_see_legacy_skills(effective_user_id)
        payload = {
            "sandbox_id": sandbox_id,
            "thread_id": thread_id,
            "user_id": effective_user_id,
            "include_legacy_skills": include_legacy_skills,
            "provision_lark_cli_runtime": provision_lark_cli_runtime,
            "provision_lark_cli_broker": provision_lark_cli_broker,
        }
        provisioner_extra_mounts = _provisioner_extra_mounts_payload(
            extra_mounts,
            provision_lark_cli_runtime=provision_lark_cli_runtime,
            provision_lark_cli_broker=provision_lark_cli_broker,
        )
        if provisioner_extra_mounts:
            payload["extra_mounts"] = provisioner_extra_mounts
        try:
            resp = requests.post(
                f"{self._provisioner_url}/api/sandboxes",
                json=payload,
                headers=self._auth_headers(),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise RuntimeError("Provisioner mount contract response is not an object")
            effective_thread_id = thread_id or sandbox_id
            if self._mount_contract_version >= _UPLOAD_MOUNT_CONTRACT_VERSION:
                response_contract = (
                    data.get("sandbox_id"),
                    data.get("user_id"),
                    data.get("thread_id"),
                    data.get("mount_contract_version"),
                )
                expected_contract = (
                    sandbox_id,
                    effective_user_id,
                    effective_thread_id,
                    _UPLOAD_MOUNT_CONTRACT_VERSION,
                )
                if response_contract != expected_contract:
                    raise RuntimeError(f"Provisioner mount contract response does not match the requested sandbox identity: expected={expected_contract!r}, received={response_contract!r}")
            logger.info(f"Provisioner created sandbox {sandbox_id}: sandbox_url={data['sandbox_url']}")
            return SandboxInfo(
                sandbox_id=sandbox_id,
                sandbox_url=data["sandbox_url"],
                user_id=data.get("user_id"),
                thread_id=data.get("thread_id"),
                mount_contract_version=data.get("mount_contract_version"),
            )
        except requests.RequestException as exc:
            logger.error(f"Provisioner create failed for {sandbox_id}: {exc}")
            raise RuntimeError(f"Provisioner create failed: {exc}") from exc

    def _provisioner_destroy(self, sandbox_id: str) -> None:
        """DELETE /api/sandboxes/{sandbox_id} → destroy Pod + Service."""
        try:
            resp = requests.delete(
                f"{self._provisioner_url}/api/sandboxes/{sandbox_id}",
                headers=self._auth_headers(),
                timeout=15,
            )
            if resp.ok:
                logger.info(f"Provisioner destroyed sandbox {sandbox_id}")
            else:
                logger.warning(f"Provisioner destroy returned {resp.status_code}: {resp.text}")
        except requests.RequestException as exc:
            logger.warning(f"Provisioner destroy failed for {sandbox_id}: {exc}")

    def _provisioner_is_alive(self, sandbox_id: str) -> bool:
        """GET /api/sandboxes/{sandbox_id} → check Pod phase."""
        try:
            resp = requests.get(
                f"{self._provisioner_url}/api/sandboxes/{sandbox_id}",
                headers=self._auth_headers(),
                timeout=10,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Provisioner health check failed for {sandbox_id}: {exc}") from exc

        if resp.status_code == 404:
            return False
        if not resp.ok:
            raise RuntimeError(f"Provisioner health check failed for {sandbox_id}: HTTP {resp.status_code} {resp.text}")

        data = resp.json()
        return data.get("status") == "Running"

    def _provisioner_discover(self, sandbox_id: str) -> SandboxInfo | None:
        """GET /api/sandboxes/{sandbox_id} → discover existing sandbox."""
        try:
            resp = requests.get(
                f"{self._provisioner_url}/api/sandboxes/{sandbox_id}",
                headers=self._auth_headers(),
                timeout=10,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            if data.get("mount_contract_version") != _UPLOAD_MOUNT_CONTRACT_VERSION:
                logger.info(
                    "Provisioner discovery ignored sandbox %s with mount contract %r",
                    sandbox_id,
                    data.get("mount_contract_version"),
                )
                return None
            return SandboxInfo(
                sandbox_id=sandbox_id,
                sandbox_url=data["sandbox_url"],
                user_id=data.get("user_id"),
                thread_id=data.get("thread_id"),
                mount_contract_version=data.get("mount_contract_version"),
            )
        except requests.RequestException as exc:
            logger.debug(f"Provisioner discover failed for {sandbox_id}: {exc}")
            return None
