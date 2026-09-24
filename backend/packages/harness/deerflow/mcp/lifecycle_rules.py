"""Pure rules that advance the persisted MCP lifecycle counters.

Callers pass the *enabled* server mappings of the effective configuration
before and after a mutation, keyed by server name and valued by the normalized
base stdio connection fingerprint. These rules are I/O- and lock-free so the
same computation can run inside any writer's config critical section.
"""

from __future__ import annotations

from collections.abc import Mapping

from deerflow.config.mcp_lifecycle import McpLifecycle

#: Serialized lifecycle schema version; the rules never advance it.
LIFECYCLE_SCHEMA_VERSION = 1


def _lifecycle_event(name: str, old_servers: Mapping[str, str], new_servers: Mapping[str, str]) -> bool:
    """Whether *name* experienced a resource lifecycle event.

    An event is a deletion, a disable (both = present → absent), an add or a
    re-enable (absent → present), or a change of the base connection
    fingerprint while present in both. Metadata-only edits and declaration
    order do not change a fingerprint, so they never count.
    """
    in_old = name in old_servers
    in_new = name in new_servers
    if in_old != in_new:
        return True
    if in_old and in_new:
        return old_servers[name] != new_servers[name]
    return False


def compute_next_lifecycle(
    previous: McpLifecycle | None,
    old_servers: Mapping[str, str],
    new_servers: Mapping[str, str],
    *,
    interceptors_changed: bool,
) -> McpLifecycle:
    """Return the lifecycle counters for one committed configuration change.

    ``configRevision`` advances on every call. ``globalGeneration`` advances
    only when ``interceptors_changed`` (a whole-pool lifecycle event). Each
    server generation advances only on a real per-server lifecycle event; names
    that are only present in the previous history are carried over unchanged and
    are never pruned.
    """
    previous_generations = dict(previous.server_generations) if previous is not None else {}
    generations: dict[str, int] = {}
    for name in sorted(set(old_servers) | set(new_servers) | set(previous_generations)):
        current = previous_generations.get(name, 0)
        generations[name] = current + (1 if _lifecycle_event(name, old_servers, new_servers) else 0)

    return McpLifecycle(
        schema_version=LIFECYCLE_SCHEMA_VERSION,
        config_revision=(previous.config_revision if previous is not None else 0) + 1,
        global_generation=(previous.global_generation if previous is not None else 0) + (1 if interceptors_changed else 0),
        server_generations=generations,
    )
