"""Build the GitHub webhook → agent registry.

Indexes every custom agent that declares a ``github:`` block by the
``(repo, event)`` pairs it is interested in, across all owners. Agent discovery
and change detection go through the configured agent store
(:mod:`deerflow.persistence.agents`), so both the ``file`` backend (per-user
directories + the legacy shared layout) and the ``db`` backend (the shared
``agents`` table) are covered by the same code.

The dispatcher calls :func:`build_github_agent_registry` once per webhook
delivery. We avoid re-loading every agent on each call via a small cache keyed
on the store's :meth:`~deerflow.persistence.agents.base.AgentStore.signature`
change token: the file backend derives it from ``config.yaml`` mtimes (any
edit, addition, or deletion invalidates the cache transparently); the db backend
derives it from ``max(updated_at)`` + the row count. Operators who hand-edit a
``config.yaml`` see the change on the next webhook.

Cache invalidation caveat (file backend): mtime granularity on macOS HFS+ /
APFS is ~1 µs but on some filesystems (FAT, network shares with caching) it's
1 s. Two edits inside the same coarse-tick would look identical. For the
dispatch path that's fine — webhooks are rare relative to operator edits, and
the next non-coincident write reconciles.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Hashable
from dataclasses import dataclass

from app.gateway.github.triggers import _resolved_trigger
from deerflow.config.agents_config import AgentConfig, GitHubTriggerConfig
from deerflow.persistence.agents import get_agent_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GitHubAgentMatch:
    """One ``(user, agent, _resolved_trigger)`` row in the ``(repo, event)`` index.

    The trigger is the binding override merged with per-event field defaults
    (see :func:`app.gateway.github.triggers._resolved_trigger`), so the
    dispatcher does not have to re-resolve it at fan-out time. Pre-resolving
    here also folds the per-binding lookup out of the hot path: the registry
    already chose the right binding for this ``(repo, event)``, so the
    dispatcher's old "find the binding whose ``.repo`` matches" loop —
    which silently dropped events when an agent had multiple bindings on
    one repo (PR feedback R3) — disappears entirely. Single-binding-per-repo
    is enforced upstream by :class:`GitHubAgentConfig`'s validator, so
    each ``(repo, event)`` resolves to exactly one trigger per agent.

    The ``github:`` block is read off ``agent.github`` (always non-None
    here — the rebuild filters agents without one before constructing a
    match), so we don't carry a separate ``github`` field.
    """

    user_id: str
    agent: AgentConfig
    trigger: GitHubTriggerConfig


# Cache: (signature, registry). ``signature`` is the store's opaque change
# token — identical token → registry is still valid, skip the reload.
_Registry = dict[tuple[str, str], list[GitHubAgentMatch]]
_cache: tuple[Hashable, _Registry] | None = None
# Threading lock (not asyncio): build_github_agent_registry is invoked
# from asyncio.to_thread in the dispatcher, so the lock is acquired on
# the worker thread. A plain Lock is the right primitive here.
_cache_lock = threading.Lock()


def _build_index(agents: list[tuple[str, AgentConfig]]) -> _Registry:
    """Build the ``(repo, event)`` index from the store's agents.

    Each ``(repo, event)`` slot stores :class:`GitHubAgentMatch` rows — the
    user_id + AgentConfig + the trigger already resolved (binding override
    merged with per-event field defaults). The dispatcher then only needs
    to apply the trigger; it never re-walks ``bindings`` to find the right
    one. Single-binding-per-repo is enforced by :class:`GitHubAgentConfig`'s
    validator (an agent that fails to load is already dropped by the store).
    """
    index: _Registry = {}
    for user_id, cfg in agents:
        if cfg.github is None:
            continue
        for binding in cfg.github.bindings:
            for event, override in binding.triggers.items():
                resolved = _resolved_trigger(event, {event: override})
                if resolved is None:
                    # ``_resolved_trigger`` only returns None when the
                    # event is not in the dict we passed — by construction
                    # it is here, so this branch is unreachable. Keep the
                    # guard for type-checker happiness.
                    continue
                index.setdefault((binding.repo, event), []).append(GitHubAgentMatch(user_id=user_id, agent=cfg, trigger=resolved))
    return index


def build_github_agent_registry() -> _Registry:
    """Return ``{(repo, event): [GitHubAgentMatch, ...]}`` across all users.

    Each agent appears in the index once per ``(repo, declared_event)`` pair,
    with the per-event trigger pre-resolved by merging the binding override
    with :data:`app.gateway.github.triggers.DEFAULT_TRIGGERS`. Events are
    opt-in per binding: an agent only registers for the events it explicitly
    lists under ``github.bindings[].triggers``. An agent that declares an
    empty ``triggers:`` map (or omits it) registers for nothing and the
    dispatcher will never fan a webhook out to it.

    Warm path (no agents added/removed/edited since the last call) costs
    only the store's ``signature()`` — cheap on both backends. Cold path
    reloads every agent and refreshes the cache. The result is shared across
    callers (returned by reference) since :class:`GitHubAgentMatch` is frozen
    and the registry is intended as read-only.
    """
    global _cache
    store = get_agent_store()
    with _cache_lock:
        signature = store.signature()
        if _cache is not None and _cache[0] == signature:
            return _cache[1]
        registry = _build_index(store.list_all())
        _cache = (signature, registry)
        return registry


def _invalidate_cache() -> None:
    """Drop the cached registry. Test-only helper."""
    global _cache
    with _cache_lock:
        _cache = None


def lookup_agents(
    registry: _Registry,
    repo: str,
    event: str,
) -> list[GitHubAgentMatch]:
    """Convenience: return the list of agent matches for ``(repo, event)``.

    Each match carries the user, AgentConfig (with ``.github`` attached),
    and the pre-resolved trigger config for this specific event, so the
    caller does not need to walk the agent's ``bindings`` again.
    """
    return registry.get((repo, event), [])
