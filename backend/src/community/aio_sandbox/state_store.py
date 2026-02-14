"""Abstract base class for sandbox state persistence.

The state store handles cross-process persistence of thread_id → sandbox mappings,
enabling different processes (gateway, langgraph, multiple workers) to find the same
sandbox for a given thread.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Generator
from contextlib import contextmanager

from .sandbox_info import SandboxInfo


class SandboxStateStore(ABC):
    """Abstract base for persisting thread_id → sandbox mappings across processes.

    Implementations:
    - FileSandboxStateStore: JSON files + fcntl file locking (single-host)
    - TODO: RedisSandboxStateStore: Redis-based for distributed multi-host deployments
    """

    @abstractmethod
    def save(self, thread_id: str, info: SandboxInfo) -> None:
        """Save sandbox state for a thread.

        Args:
            thread_id: The thread ID.
            info: Sandbox metadata to persist.
        """
        ...

    @abstractmethod
    def load(self, thread_id: str) -> SandboxInfo | None:
        """Load sandbox state for a thread.

        Args:
            thread_id: The thread ID.

        Returns:
            SandboxInfo if found, None otherwise.
        """
        ...

    @abstractmethod
    def remove(self, thread_id: str) -> None:
        """Remove sandbox state for a thread.

        Args:
            thread_id: The thread ID.
        """
        ...

    @abstractmethod
    @contextmanager
    def lock(self, thread_id: str) -> Generator[None, None, None]:
        """Acquire a cross-process lock for a thread's sandbox operations.

        Ensures only one process can create/modify a sandbox for a given
        thread_id at a time, preventing duplicate sandbox creation.

        Args:
            thread_id: The thread ID to lock.

        Yields:
            None — use as a context manager.
        """
        ...
