"""Embedded session wiring for the TUI.

Owns construction of the ``DeerFlowClient`` (with a persistent checkpointer),
thread resolution for ``--continue`` / ``--resume``, and the shared-persistence
writer that makes terminal sessions visible in the Web UI (see
``deerflow.tui.persistence``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid importing the heavy client during pure planning
    from deerflow.client import DeerFlowClient

    from .cli import LaunchPlan
    from .persistence import ThreadMetaWriter


@dataclass
class Session:
    client: DeerFlowClient
    writer: ThreadMetaWriter | None = None

    def resolve_thread(self, plan: LaunchPlan) -> str | None:
        """Resolve the thread id to run against, honoring --resume / --continue."""
        if plan.thread_id:
            return plan.thread_id
        if plan.continue_recent:
            threads = self.client.list_threads(limit=1).get("thread_list", [])
            if threads:
                return threads[0].get("thread_id")
        return None

    def recent_threads(self, limit: int = 20) -> list[dict]:
        return self.client.list_threads(limit=limit).get("thread_list", [])


def open_session() -> Session:
    """Build an embedded session backed by the configured checkpointer + thread store."""
    from deerflow.client import DeerFlowClient
    from deerflow.runtime.checkpointer.provider import get_checkpointer

    from .persistence import build_persistence

    checkpointer = get_checkpointer()
    client = DeerFlowClient(checkpointer=checkpointer)
    _loop, writer = build_persistence()
    return Session(client=client, writer=writer)
