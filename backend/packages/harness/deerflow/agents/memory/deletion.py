"""Shared helper for clearing deleted-agent tombstone markers.

Recreating a same-named agent after a delete must clear the marker written by
the deletion path, or every later memory write bails in the storage commit
guard and the agent is permanently muted (issue #3364). The REST create route,
``setup_agent`` and ``update_agent`` all upsert a (possibly deleted) agent, so
the clear lives here to stop the three surfaces from drifting.
"""

from __future__ import annotations

import logging

from deerflow.agents.memory.manager import get_memory_manager
from deerflow.config.memory_config import get_memory_config
from deerflow.runtime.user_context import resolve_runtime_user_id

logger = logging.getLogger(__name__)


def clear_deleted_agent_marker(
    agent_name: str,
    user_id: str,
    *,
    include_runtime_id: bool = True,
) -> None:
    """Clear the deleted-agent tombstone for a (re)created agent, best-effort.

    No-op when memory is disabled or the resolved backend has no marker concept.
    Never raises: a stale marker only suppresses memory writes, so a failure here
    must not fail agent (re)creation.
    """
    if not get_memory_config().enabled:
        return
    manager = get_memory_manager()
    clear = getattr(manager, "clear_agent_deleted", None)
    if clear is None:
        return

    # Mirror the delete path's candidate set (raw effective id plus any
    # runtime-resolved id) so we clear whichever bucket the deletion marked.
    candidate_ids: set[str] = {user_id}
    if include_runtime_id:
        try:
            candidate_ids.add(resolve_runtime_user_id(None))
        except Exception:
            pass

    for candidate_id in candidate_ids:
        try:
            clear(user_id=candidate_id, agent_name=agent_name)
        except Exception as e:
            logger.warning(
                "Failed to clear deleted marker for agent '%s' (user=%s): %s",
                agent_name,
                candidate_id,
                e,
            )
