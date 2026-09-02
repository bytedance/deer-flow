"""Custom agent definition persistence — abstract store + file/db backends.

The public entry point is :func:`get_agent_store`, which the free functions in
:mod:`deerflow.config.agents_config` dispatch to. ``file`` (default) preserves
today's on-disk layout; ``db`` shares definitions across nodes via the SQL
persistence layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deerflow.persistence.agents.base import (
    AgentDeleteOutcome,
    AgentExistsError,
    AgentStore,
    parse_agent_config,
)
from deerflow.persistence.agents.model import AgentRow

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig

__all__ = [
    "AgentDeleteOutcome",
    "AgentExistsError",
    "AgentRow",
    "AgentStore",
    "get_agent_store",
    "make_agent_store",
    "parse_agent_config",
    "should_discard_on_delete",
]

_file_store_singleton: AgentStore | None = None


def should_discard_on_delete(store: AgentStore, user_id: str, name: str) -> bool:
    """Whether deleting ``name`` should first discard its pending memory updates.

    The file backend scopes the discard to genuine custom agents (the agent dir
    contains a ``config.yaml``), mirroring ``FileAgentStore.delete``, so a no-op
    delete doesn't drop queued updates for an agent that is preserved. That
    filesystem guard is meaningless for db-backed stores: ``SqlAgentStore``
    keeps ``config.yaml``/SOUL in the DB row, never on disk, so the guard is
    always False there and the discard would silently no-op. Db-backed
    deletions therefore always discard. Pinned by
    ``test_should_discard_on_delete_backend_split``.
    """
    from deerflow.persistence.agents.file import FileAgentStore

    if not isinstance(store, FileAgentStore):
        return True
    from deerflow.config.paths import get_paths

    agent_dir = get_paths().user_agent_dir(user_id, name)
    return agent_dir.exists() and (agent_dir / "config.yaml").is_file()


def make_agent_store(config: AppConfig) -> AgentStore:
    """Build (or reuse) the store selected by ``config.agent_storage.backend``.

    ``db`` requires ``database.backend`` to be ``sqlite`` or ``postgres``; a
    ``memory`` database has no durable URL and is rejected here (the gateway
    also fails fast at startup, but this guard covers the graph-process path).
    """
    if config.agent_storage.backend == "db":
        db_backend = config.database.backend
        if db_backend not in ("sqlite", "postgres"):
            raise ValueError(
                f"agent_storage.backend='db' requires database.backend to be 'sqlite' or 'postgres', "
                f"but database.backend is '{db_backend}'. A 'memory' database is per-process and cannot "
                "share agent definitions across nodes; set database.backend accordingly or use "
                "agent_storage.backend='file'."
            )
        from deerflow.persistence.agents.sql import SqlAgentStore

        return SqlAgentStore(config.database.app_sync_sqlalchemy_url)

    return _file_store()


def get_agent_store() -> AgentStore:
    """Return the store for the current process's configuration.

    Defaults to the file backend when no app config can be resolved — the free
    functions in ``agents_config`` must keep working in lightweight contexts
    (CLI, tests, tools) that never load a full ``config.yaml``. Only an
    explicit ``agent_storage.backend: db`` diverges from the file default.

    Cross-process invariant (the ``db`` backend's whole point): the per-run
    agent build runs in the **graph subprocess**, a different process from the
    gateway. Its cross-node guarantee holds only because ``get_app_config()``
    resolves ``config.yaml`` there too and returns ``backend: db`` — so the read
    path in the graph process sees the same shared table the gateway wrote. The
    ``except`` below is a genuine *no resolvable config* fallback (CLI/tests),
    **not** a mask for a misconfigured graph process: if ``config.yaml`` is
    reachable there (it is, same working tree), ``db`` is honoured, not silently
    downgraded to node-local ``file``. Pinned by
    ``test_get_agent_store_resolves_db_backend_from_on_disk_config``.
    """
    from deerflow.config.app_config import get_app_config

    try:
        config = get_app_config()
    except Exception:  # noqa: BLE001 — no resolvable config → file default
        return _file_store()
    return make_agent_store(config)


def _file_store() -> AgentStore:
    global _file_store_singleton
    if _file_store_singleton is None:
        from deerflow.persistence.agents.file import FileAgentStore

        _file_store_singleton = FileAgentStore()
    return _file_store_singleton
