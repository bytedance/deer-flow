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

import requests

from deerflow.runtime.user_context import get_effective_user_id

from .backend import SandboxBackend
from .sandbox_info import SandboxInfo

logger = logging.getLogger(__name__)


class RemoteSandboxBackend(SandboxBackend):
    """Backend that delegates sandbox lifecycle to the provisioner service.

    All Pod creation, destruction, and discovery are handled by the
    provisioner.  This backend is a thin HTTP client.

    Typical config.yaml::

        sandbox:
          use: deerflow.community.aio_sandbox:AioSandboxProvider
          provisioner_url: http://provisioner:8002
    """

    def __init__(self, provisioner_url: str, config_mounts: list | None = None):
        """Initialize with the provisioner service URL.

        Args:
            provisioner_url: URL of the provisioner service
                             (e.g., ``http://provisioner:8002``).
            config_mounts: Configured sandbox mounts to pass to the provisioner.
        """
        self._provisioner_url = provisioner_url.rstrip("/")
        self._config_mounts = config_mounts or []

    @property
    def provisioner_url(self) -> str:
        return self._provisioner_url

    # ── SandboxBackend interface ──────────────────────────────────────────

    def create(
        self,
        thread_id: str | None,
        sandbox_id: str,
        extra_mounts: list[tuple[str, str, bool]] | None = None,
    ) -> SandboxInfo:
        """Create a sandbox Pod + Service via the provisioner.

        Calls ``POST /api/sandboxes`` which creates a dedicated Pod +
        NodePort Service in k3s.
        """
        return self._provisioner_create(thread_id, sandbox_id, extra_mounts)

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
            resp = requests.get(f"{self._provisioner_url}/api/sandboxes", timeout=10)
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

    def _provisioner_create(self, thread_id: str | None, sandbox_id: str, extra_mounts: list[tuple[str, str, bool]] | None = None) -> SandboxInfo:
        """POST /api/sandboxes → create Pod + Service."""
        payload = {
            "sandbox_id": sandbox_id,
            "thread_id": thread_id,
            "user_id": get_effective_user_id(),
        }
        serialized_mounts = self._serialize_extra_mounts(extra_mounts)
        if serialized_mounts:
            payload["extra_mounts"] = serialized_mounts

        try:
            resp = requests.post(
                f"{self._provisioner_url}/api/sandboxes",
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"Provisioner created sandbox {sandbox_id}: sandbox_url={data['sandbox_url']}")
            return SandboxInfo(
                sandbox_id=sandbox_id,
                sandbox_url=data["sandbox_url"],
            )
        except requests.RequestException as exc:
            logger.error(f"Provisioner create failed for {sandbox_id}: {exc}")
            raise RuntimeError(f"Provisioner create failed: {exc}") from exc

    def _serialize_extra_mounts(self, extra_mounts: list[tuple[str, str, bool]] | None = None) -> list[dict[str, object]]:
        """Serialize configured and runtime mounts for the provisioner API."""
        mounts: list[dict[str, object]] = []
        seen_container_paths: set[str] = set()

        for mount in self._config_mounts:
            normalized_container_path = mount.container_path.rstrip("/") or "/"
            if self._is_provisioner_builtin_mount(normalized_container_path):
                logger.warning("Skipping provisioner built-in config mount target: %s", mount.container_path)
                continue
            if normalized_container_path in seen_container_paths:
                logger.warning("Skipping duplicate provisioner config mount target: %s", mount.container_path)
                continue
            seen_container_paths.add(normalized_container_path)
            mounts.append(
                {
                    "host_path": mount.host_path,
                    "container_path": normalized_container_path,
                    "read_only": mount.read_only,
                }
            )

        for host_path, container_path, read_only in extra_mounts or []:
            normalized_container_path = container_path.rstrip("/") or "/"
            if self._is_provisioner_builtin_mount(normalized_container_path):
                continue
            if normalized_container_path in seen_container_paths:
                logger.warning("Skipping duplicate provisioner extra mount target: %s", container_path)
                continue
            seen_container_paths.add(normalized_container_path)
            mounts.append(
                {
                    "host_path": host_path,
                    "container_path": normalized_container_path,
                    "read_only": read_only,
                }
            )

        return mounts

    @staticmethod
    def _is_provisioner_builtin_mount(container_path: str) -> bool:
        """Return true for mount paths the provisioner already creates itself."""
        return (
            container_path == "/mnt/skills"
            or container_path.startswith("/mnt/skills/")
            or container_path == "/mnt/user-data"
            or container_path.startswith("/mnt/user-data/")
        )

    def _provisioner_destroy(self, sandbox_id: str) -> None:
        """DELETE /api/sandboxes/{sandbox_id} → destroy Pod + Service."""
        try:
            resp = requests.delete(
                f"{self._provisioner_url}/api/sandboxes/{sandbox_id}",
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
                timeout=10,
            )
            if resp.ok:
                data = resp.json()
                return data.get("status") == "Running"
            return False
        except requests.RequestException:
            return False

    def _provisioner_discover(self, sandbox_id: str) -> SandboxInfo | None:
        """GET /api/sandboxes/{sandbox_id} → discover existing sandbox."""
        try:
            resp = requests.get(
                f"{self._provisioner_url}/api/sandboxes/{sandbox_id}",
                timeout=10,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            return SandboxInfo(
                sandbox_id=sandbox_id,
                sandbox_url=data["sandbox_url"],
            )
        except requests.RequestException as exc:
            logger.debug(f"Provisioner discover failed for {sandbox_id}: {exc}")
            return None
