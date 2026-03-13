"""Sandbox state store abstract interface for multi-user sandbox state persistence."""

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Optional


@dataclass
class SandboxInfo:
    """Information about a sandbox instance."""

    thread_id: str
    user_id: Optional[str] = None
    sandbox_id: str = "local"
    created_at: float = 0.0


class SandboxStateStore(ABC):
    """Sandbox state persistence with user isolation.

    This abstract interface defines the contract for sandbox state persistence
    with support for multi-user isolation. Implementations can use different
    backends (file, Redis, etc.) to store sandbox state.
    """

    @abstractmethod
    def lock(self, thread_id: str, user_id: Optional[str] = None) -> AbstractContextManager:
        """Acquire a cross-process lock for the given thread and user.

        The lock key is composed of user_id:thread_id for user isolation,
        or just thread_id for single-tenant mode.

        Args:
            thread_id: The thread ID.
            user_id: Optional user ID for multi-tenant mode.

        Returns:
            A context manager that acquires and releases the lock.
        """
        pass

    @abstractmethod
    def save(self, thread_id: str, info: SandboxInfo, user_id: Optional[str] = None) -> None:
        """Persist sandbox information.

        Args:
            thread_id: The thread ID.
            info: The sandbox information to persist.
            user_id: Optional user ID for multi-tenant mode.
        """
        pass

    @abstractmethod
    def load(self, thread_id: str, user_id: Optional[str] = None) -> Optional[SandboxInfo]:
        """Load sandbox information.

        Args:
            thread_id: The thread ID.
            user_id: Optional user ID for multi-tenant mode.

        Returns:
            The sandbox information if found, None otherwise.
        """
        pass

    @abstractmethod
    def remove(self, thread_id: str, user_id: Optional[str] = None) -> None:
        """Remove sandbox information.

        Args:
            thread_id: The thread ID.
            user_id: Optional user ID for multi-tenant mode.
        """
        pass

    def _get_key(self, thread_id: str, user_id: Optional[str] = None) -> str:
        """Generate a composite key for user isolation.

        Args:
            thread_id: The thread ID.
            user_id: Optional user ID for multi-tenant mode.

        Returns:
            A composite key string.
        """
        if user_id:
            return f"{user_id}:{thread_id}"
        return thread_id
