"""Abstract base class for sandbox provisioning backends."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from abc import ABC, abstractmethod
from urllib.parse import urlparse

import httpx
import requests

from .sandbox_info import SandboxInfo

logger = logging.getLogger(__name__)


def sandbox_http_trust_env(sandbox_url: str) -> bool:
    """Whether HTTP clients for *sandbox_url* should inherit proxy settings.

    Local Docker, DooD, and Kubernetes sandbox endpoints are control-plane
    connections, not internet traffic. Sending them through ``HTTP_PROXY`` can
    produce a misleading proxy-generated 502 even though the sandbox container
    is healthy (#3441). External fully-qualified hosts retain normal environment
    proxy behavior.
    """
    try:
        hostname = (urlparse(sandbox_url).hostname or "").rstrip(".").lower()
    except ValueError:
        return True
    if not hostname:
        return True
    if hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".docker.internal") or hostname.endswith(".containers.internal"):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return "." in hostname
    return not (address.is_loopback or address.is_private or address.is_link_local)


# The readiness deadline the local-container provider paths (sync and async)
# enforce before destroying a sandbox that never became ready. Tests that
# validate the shipped image must use this same budget: a longer one can
# pass while every real acquisition still fails.
SANDBOX_LOCAL_PROVIDER_READY_TIMEOUT = 60


def wait_for_sandbox_ready(sandbox_url: str, timeout: int = 30) -> bool:
    """Poll sandbox health endpoint until ready or timeout.

    Args:
        sandbox_url: URL of the sandbox (e.g. http://k3s:30001).
        timeout: Maximum time to wait in seconds.

    Returns:
        True if sandbox is ready, False otherwise.
    """
    start_time = time.time()
    with requests.Session() as session:
        session.trust_env = sandbox_http_trust_env(sandbox_url)
        while time.time() - start_time < timeout:
            try:
                response = session.get(f"{sandbox_url}/v1/sandbox", timeout=5)
                if response.status_code == 200:
                    return True
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)
    return False


async def wait_for_sandbox_ready_async(sandbox_url: str, timeout: int = 30, poll_interval: float = 1.0) -> bool:
    """Async variant of sandbox readiness polling.

    Use this from async runtime paths so sandbox startup waits do not block the
    event loop. The synchronous ``wait_for_sandbox_ready`` function remains for
    existing synchronous backend/provider call sites.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    async with httpx.AsyncClient(timeout=5, trust_env=sandbox_http_trust_env(sandbox_url)) as client:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                response = await client.get(f"{sandbox_url}/v1/sandbox", timeout=min(5.0, remaining))
                if response.status_code == 200:
                    return True
            except httpx.RequestError:
                pass
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(poll_interval, remaining))
    return False


class SandboxBackend(ABC):
    """Abstract base for sandbox provisioning backends.

    Two implementations:
    - LocalContainerBackend: starts Docker/Apple Container locally, manages ports
    - RemoteSandboxBackend: connects to a pre-existing URL (K8s service, external)
    """

    @abstractmethod
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
        """Create/provision a new sandbox.

        Args:
            thread_id: Thread ID for which the sandbox is being created. Useful for backends that want to organize sandboxes by thread.
            sandbox_id: Deterministic sandbox identifier.
            extra_mounts: Additional volume mounts as (host_path, container_path, read_only) tuples.
                Ignored by backends that don't manage containers (e.g., remote).
            user_id: User bucket that the sandbox should mount or provision for.
            provision_lark_cli_runtime: Ask the backend to provision the sandbox
                lark-cli runtime via its native mechanism (e.g. the provisioner's
                init container + emptyDir). Backends that can't do this ignore it.
            provision_lark_cli_broker: Ask the backend to provision a lark-cli
                broker sidecar (Pattern B, issue #4338) so credentials stay out of
                the sandbox. Supersedes ``provision_lark_cli_runtime`` when the
                backend supports it; backends that can't do this ignore it.

        Returns:
            SandboxInfo with connection details.
        """
        ...

    @abstractmethod
    def destroy(self, info: SandboxInfo) -> None:
        """Destroy/cleanup a sandbox and release its resources.

        Args:
            info: The sandbox metadata to destroy.
        """
        ...

    @abstractmethod
    def is_alive(self, info: SandboxInfo) -> bool:
        """Quick check whether a sandbox is still alive.

        This should be a lightweight check (e.g., container inspect)
        rather than a full health check.

        Args:
            info: The sandbox metadata to check.

        Returns:
            True if the sandbox appears to be alive.
        """
        ...

    @abstractmethod
    def discover(self, sandbox_id: str) -> SandboxInfo | None:
        """Try to discover an existing sandbox by its deterministic ID.

        Used for cross-process recovery: when another process started a sandbox,
        this process can discover it by the deterministic container name or URL.

        Args:
            sandbox_id: The deterministic sandbox ID to look for.

        Returns:
            SandboxInfo if found and healthy, None otherwise.
        """
        ...

    def list_running(self) -> list[SandboxInfo]:
        """Enumerate all running sandboxes managed by this backend.

        Used for startup reconciliation: when the process restarts, it needs
        to discover containers started by previous processes so they can be
        adopted into the warm pool or destroyed if idle too long.

        The default implementation returns an empty list, which is correct
        for backends that don't manage local containers (e.g., RemoteSandboxBackend
        delegates lifecycle to the provisioner which handles its own cleanup).

        Returns:
            A list of SandboxInfo for all currently running sandboxes.
        """
        return []
