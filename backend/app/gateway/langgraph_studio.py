"""Pre-runtime persistence repair for standalone LangGraph Studio.

``langgraph dev`` imports this custom application before entering the locked
in-memory runtime lifespan. That ordering is intentional: runtime 0.30.0 loads
and purges persisted ``created_by=system`` assistants before graph registration
and before a user application lifespan can run. Keep annotations eager in this
module: LangGraph's file loader executes it without first registering the module
in ``sys.modules``, which breaks dataclasses with postponed annotations.
"""

import json
import logging
import os
from collections.abc import Collection, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from fastapi import FastAPI

logger = logging.getLogger(__name__)

_OPS_PATH = Path(".langgraph_api/.langgraph_ops.pckl")


@dataclass(frozen=True)
class ProvenanceRepair:
    """Summary of one atomic pre-runtime persistence repair."""

    removed_registered_assistants: int = 0
    removed_registered_versions: int = 0
    demoted_assistants: int = 0
    demoted_versions: int = 0

    @property
    def changed(self) -> bool:
        return any(
            (
                self.removed_registered_assistants,
                self.removed_registered_versions,
                self.demoted_assistants,
                self.demoted_versions,
            )
        )


def configured_system_assistant_ids(
    graphs_json: str | None,
    *,
    namespace: UUID | None = None,
) -> set[str]:
    """Derive registered assistant IDs from the CLI-provided graph registry."""
    if not graphs_json:
        return set()

    graphs = json.loads(graphs_json)
    if not isinstance(graphs, dict):
        raise ValueError("LANGSERVE_GRAPHS must contain a JSON object")
    if not graphs:
        return set()

    if namespace is None:
        from langgraph_api.graph import NAMESPACE_GRAPH

        namespace = NAMESPACE_GRAPH

    return {str(uuid5(namespace, str(graph_id))) for graph_id in graphs}


def _demote_system_marker(row: MutableMapping[str, Any]) -> tuple[MutableMapping[str, Any], bool]:
    metadata = row.get("metadata") or {}
    if metadata.get("created_by") != "system":
        return row, False

    repaired = dict(row)
    repaired_metadata = dict(metadata)
    repaired_metadata["created_by"] = "user"
    repaired["metadata"] = repaired_metadata
    return repaired, True


def repair_persisted_assistant_provenance(
    store: MutableMapping[str, Any],
    *,
    registered_system_ids: Collection[str],
) -> ProvenanceRepair:
    """Repair legacy assistant rows before the in-memory runtime loads them.

    Configured graph assistant IDs are removed so graph registration recreates
    them with server-owned provenance. Every other legacy system marker is
    demoted in both the active row and its version history. The replacement
    lists are built before either store key is assigned, so a malformed row
    cannot leave a partially repaired store.
    """
    registered_ids = {str(assistant_id) for assistant_id in registered_system_ids}
    if not registered_ids:
        return ProvenanceRepair()

    assistants: list[MutableMapping[str, Any]] = []
    removed_registered_assistants = 0
    demoted_assistants = 0
    for row in store.get("assistants") or []:
        if str(row.get("assistant_id")) in registered_ids:
            removed_registered_assistants += 1
            continue
        repaired, demoted = _demote_system_marker(row)
        assistants.append(repaired)
        demoted_assistants += int(demoted)

    versions: list[MutableMapping[str, Any]] = []
    removed_registered_versions = 0
    demoted_versions = 0
    for row in store.get("assistant_versions") or []:
        if str(row.get("assistant_id")) in registered_ids:
            removed_registered_versions += 1
            continue
        repaired, demoted = _demote_system_marker(row)
        versions.append(repaired)
        demoted_versions += int(demoted)

    result = ProvenanceRepair(
        removed_registered_assistants=removed_registered_assistants,
        removed_registered_versions=removed_registered_versions,
        demoted_assistants=demoted_assistants,
        demoted_versions=demoted_versions,
    )
    store["assistants"] = assistants
    store["assistant_versions"] = versions
    return result


def repair_local_dev_persistence_before_runtime(
    *,
    persistence_path: Path = _OPS_PATH,
    graphs_json: str | None = None,
) -> ProvenanceRepair:
    """Load, repair, and atomically rewrite a locked local-dev store."""
    if graphs_json is None:
        graphs_json = os.getenv("LANGSERVE_GRAPHS")
    registered_ids = configured_system_assistant_ids(graphs_json)
    if not registered_ids or not persistence_path.is_file():
        return ProvenanceRepair()

    from langgraph.checkpoint.memory import PersistentDict

    store = PersistentDict(dict, filename=str(persistence_path))
    store.load()
    result = repair_persisted_assistant_provenance(
        store,
        registered_system_ids=registered_ids,
    )
    if not (result.removed_registered_assistants or result.removed_registered_versions):
        logger.warning(
            "Standalone Studio persistence repair matched no persisted registered assistant rows; verify the LangGraph runtime persistence contract before trusting provenance repair",
        )
    if result.changed:
        store.sync()
    return result


def _prepare_locked_local_dev_runtime() -> None:
    if os.getenv("LANGSMITH_LANGGRAPH_API_VARIANT") != "local_dev":
        return
    if "__inmem" not in os.getenv("MIGRATIONS_PATH", ""):
        return

    result = repair_local_dev_persistence_before_runtime()
    if result.changed:
        logger.warning(
            "Repaired standalone Studio persistence before runtime startup: %d registered assistant(s) and %d registered version(s) reset; %d legacy assistant marker(s) and %d version marker(s) demoted",
            result.removed_registered_assistants,
            result.removed_registered_versions,
            result.demoted_assistants,
            result.demoted_versions,
        )


_prepare_locked_local_dev_runtime()

langgraph_app = FastAPI(
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
