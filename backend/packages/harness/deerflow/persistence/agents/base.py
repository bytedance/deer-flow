"""Abstract interface for custom agent definition storage.

Two implementations:
- :class:`FileAgentStore` — the historical per-user on-disk layout
  (``config.yaml`` + ``SOUL.md``), still the default and behaviourally
  unchanged.
- :class:`SqlAgentStore` — a row per agent in the shared SQL persistence
  layer, so every node in a multi-instance deployment sees the same agents.

The store is deliberately **synchronous**. Its consumers — the LangGraph graph
factory (``make_lead_agent``), the ``setup_agent`` / ``update_agent`` tools, and
the GitHub agent registry — are synchronous and may run on the event loop or in
a separate process from the gateway, where an async engine cannot be driven.
Async HTTP routes call the store via ``asyncio.to_thread`` (the same pattern the
agents router already uses for filesystem work).

``user_id`` semantics (kept identical to the pre-refactor free functions in
:mod:`deerflow.config.agents_config`, which is what makes the file backend a
behaviour-neutral move): ``None`` resolves to the effective user from the
request context — ``"default"`` in no-auth mode — via
:func:`deerflow.runtime.user_context.get_effective_user_id`. This is filesystem
bucket semantics, distinct from the AUTO/None sentinel used by the async
``thread_meta`` repositories.
"""

from __future__ import annotations

import abc
from collections.abc import Hashable
from typing import Any, Literal

from deerflow.config.agents_config import AgentConfig


def parse_agent_config(data: dict[str, Any], name: str) -> AgentConfig:
    """Build an :class:`AgentConfig` from a raw config *document*, shared by both backends.

    Sets ``name`` from the natural key when the document omits it and strips
    unknown keys (e.g. a legacy ``prompt_file``) before validation — identical
    to the pre-refactor ``load_agent_config``.
    """
    data = dict(data)
    if "name" not in data:
        data["name"] = name
    known_fields = set(AgentConfig.model_fields.keys())
    data = {k: v for k, v in data.items() if k in known_fields}
    return AgentConfig(**data)


# Delete outcome, mirroring the agents router's result:
# a row/dir was removed ("deleted"); only a legacy shared-layout entry exists,
# which the current write path never removes ("legacy"); nothing was there
# ("missing"); or a per-user directory exists holding memory/facts data but is
# not a custom agent (no config.yaml), so it is preserved rather than deleting a
# user's memory ("not-custom-agent", #4279).
AgentDeleteOutcome = Literal["deleted", "legacy", "missing", "not-custom-agent"]


class AgentExistsError(Exception):
    """Raised by :meth:`AgentStore.create` when ``(user_id, name)`` already exists."""


class AgentStore(abc.ABC):
    @abc.abstractmethod
    def get(self, name: str, *, user_id: str | None = None) -> AgentConfig:
        """Return the agent's config.

        Raises :class:`FileNotFoundError` if the agent does not exist — the
        historical contract that ``routers/agents.py`` and ``update_agent`` rely
        on to surface a 404 / "does not exist" error.
        """

    @abc.abstractmethod
    def exists(self, name: str, *, user_id: str | None = None) -> bool:
        """Return whether ``name`` is already taken for ``user_id``.

        Consistent with :meth:`create`'s conflict rule (so an "available" name
        never then 409s): the file backend treats any per-user or legacy
        directory as taken; the db backend checks for a row.
        """

    @abc.abstractmethod
    def get_soul(self, name: str, *, user_id: str | None = None) -> str | None:
        """Return the agent's ``SOUL.md`` content, or ``None`` if unset/empty."""

    @abc.abstractmethod
    def list(self, *, user_id: str | None = None) -> list[AgentConfig]:
        """Return every custom agent owned by ``user_id``, sorted by name."""

    @abc.abstractmethod
    def list_all(self) -> list[tuple[str, AgentConfig]]:
        """Return ``(user_id, config)`` for every agent across all owners.

        Used by the GitHub registry, which scans all users' agents for repo
        bindings. Ordering is deterministic (by ``user_id`` then name).
        """

    @abc.abstractmethod
    def create(self, name: str, config: dict, soul: str, *, user_id: str | None = None) -> None:
        """Persist a new agent from the config *document* each write surface builds.

        ``config`` is the raw dict the caller assembled (the same one previously
        written to ``config.yaml``); passing the document rather than a
        re-serialized :class:`AgentConfig` keeps the on-disk bytes and the
        "only present keys are written" behaviour identical to the pre-refactor
        writers. Raises :class:`AgentExistsError` on an existing ``(user_id, name)``.
        """

    @abc.abstractmethod
    def update(self, name: str, config: dict | None, soul: str | None, *, user_id: str | None = None) -> None:
        """Write an agent's config and/or soul (upsert).

        ``config`` / ``soul`` are each independently optional: ``None`` means
        "leave that part unchanged" — the agents router updates config only when
        a config field changed, and soul only when one was supplied. Creates the
        record if it does not exist (the ``setup_agent`` / first-write path).
        """

    @abc.abstractmethod
    def delete(self, name: str, *, user_id: str | None = None) -> AgentDeleteOutcome:
        """Delete an agent and its co-located memory, returning the outcome."""

    @abc.abstractmethod
    def signature(self) -> Hashable:
        """Return an opaque change token for cache invalidation.

        Equal tokens mean "nothing changed since last read". The GitHub registry
        keys its cache off this instead of ``stat()`` so it works for both
        backends (mtime triples for ``file``; ``max(updated_at)`` + row count for
        ``db``).
        """
