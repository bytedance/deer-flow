"""WorkspaceBackend — abstract interface for agent persistent workspace storage."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deerflow.identity.agent_identity import AgentIdentity


class WorkspaceBackend(ABC):
    """Abstract persistent workspace backend.

    Implementations must be safe to call from multiple threads concurrently
    when different identities are in play.  Implementations that operate on
    the same identity path MUST serialize sync_down / sync_up calls.
    """

    @abstractmethod
    async def sync_down(self, identity: "AgentIdentity", local_dir: Path) -> None:
        """Pull remote workspace contents into *local_dir*.

        Called during sandbox Acquire.  *local_dir* is created by the caller.
        """

    @abstractmethod
    async def sync_up(self, identity: "AgentIdentity", local_dir: Path) -> None:
        """Push *local_dir* contents to the remote workspace.

        Called after sandbox Release.
        """
