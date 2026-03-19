"""Abstract base 类 for sandbox provisioning backends."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

import requests

from .sandbox_info import SandboxInfo

logger = logging.getLogger(__name__)


def wait_for_sandbox_ready(sandbox_url: str, timeout: int = 30) -> bool:
    """Poll sandbox health endpoint until ready or timeout.

    Args:
        sandbox_url: URL of the sandbox (e.g. http://k3s:30001).
        timeout: Maximum time to wait in seconds.

    Returns:
        True if sandbox is ready, False otherwise.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = requests.get(f"{sandbox_url}/v1/sandbox", timeout=5)
            if response.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)
    return False


class SandboxBackend(ABC):
    """Abstract base for sandbox provisioning backends.

    Two implementations:
    - LocalContainerBackend: starts Docker/Apple Container locally, manages ports
    - RemoteSandboxBackend: connects to a pre-existing URL (K8s 服务, external)
    """

    @abstractmethod
    def create(self, thread_id: str, sandbox_id: str, extra_mounts: list[tuple[str, str, bool]] | None = None) -> SandboxInfo:
        """Create/provision a 新建 sandbox.

        Args:
            thread_id: 线程 ID for which the sandbox is being created. Useful for backends that want to organize sandboxes by 线程.
            sandbox_id: Deterministic sandbox identifier.
            extra_mounts: Additional volume mounts as (host_path, container_path, read_only) tuples.
                Ignored by backends that don't manage containers (e.g., remote).

        Returns:
            SandboxInfo with connection details.
        """
        ...

    @abstractmethod
    def destroy(self, info: SandboxInfo) -> None:
        """Destroy/cleanup a sandbox and release its resources.

        Args:
            信息: The sandbox metadata to destroy.
        """
        ...

    @abstractmethod
    def is_alive(self, info: SandboxInfo) -> bool:
        """Quick 检查 whether a sandbox is still alive.

        This should be a lightweight 检查 (e.g., container inspect)
        rather than a full health 检查.

        Args:
            信息: The sandbox metadata to 检查.

        Returns:
            True if the sandbox appears to be alive.
        """
        ...

    @abstractmethod
    def discover(self, sandbox_id: str) -> SandboxInfo | None:
        """Try to discover an existing sandbox by its deterministic ID.

        Used for cross-处理 recovery: when another 处理 started a sandbox,
        this 处理 can discover it by the deterministic container 名称 or URL.

        Args:
            sandbox_id: The deterministic sandbox ID to look for.

        Returns:
            SandboxInfo if found and healthy, None otherwise.
        """
        ...
