"""Deployment-level managed subagent persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from deerflow.persistence.managed_subagents.base import (
    ManagedSubagentDefinition,
    ManagedSubagentExistsError,
    ManagedSubagentStore,
)
from deerflow.persistence.managed_subagents.model import ManagedSubagentRow

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig

__all__ = [
    "ManagedSubagentDefinition",
    "ManagedSubagentExistsError",
    "ManagedSubagentRow",
    "ManagedSubagentStore",
    "get_managed_subagent_store",
    "make_managed_subagent_store",
]

_file_store_singleton: ManagedSubagentStore | None = None


def make_managed_subagent_store(config: AppConfig) -> ManagedSubagentStore:
    """Select the same persistence backend used by custom agent definitions."""
    if config.agent_storage.backend == "db":
        if config.database.backend not in ("sqlite", "postgres"):
            raise ValueError("Managed subagent database storage requires database.backend to be 'sqlite' or 'postgres'.")
        from deerflow.persistence.managed_subagents.sql import SqlManagedSubagentStore

        return SqlManagedSubagentStore(config.database.app_sync_sqlalchemy_url)
    return _file_store()


def get_managed_subagent_store(config: AppConfig | None = None) -> ManagedSubagentStore:
    if config is not None:
        return make_managed_subagent_store(config)
    from deerflow.config.app_config import get_app_config

    try:
        resolved = get_app_config()
    except Exception:  # noqa: BLE001 — lightweight/test contexts keep file fallback
        return _file_store()
    return make_managed_subagent_store(resolved)


def _file_store() -> ManagedSubagentStore:
    global _file_store_singleton
    if _file_store_singleton is None:
        from deerflow.persistence.managed_subagents.file import FileManagedSubagentStore

        _file_store_singleton = FileManagedSubagentStore()
    return _file_store_singleton
