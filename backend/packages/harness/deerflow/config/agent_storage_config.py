"""Custom-agent and managed-subagent definition storage configuration.

Controls where custom agent *definitions* (``config.yaml`` + ``SOUL.md``) are
persisted, together with deployment-level managed subagent definitions. This
is orthogonal to :class:`DatabaseConfig` (which governs the
run/thread/event persistence layer) and to the deermem memory store.

Backends:
- file: Per-user files under ``{base_dir}/users/{user_id}/agents/{name}/``
  for Custom Agents and one JSON file per managed subagent under
  ``{base_dir}/managed-subagents/``. Node-local without a shared mount. This
  remains the default so zero-config development is unaffected.
- db: Rows in the ``agents`` and ``managed_subagents`` tables of the existing
  SQL persistence layer, shared by every node. Requires ``database.backend``
  to be ``sqlite`` or ``postgres`` (validated at startup).

Agent *memory* (``memory.json``) is a separate concern handled by the deermem
storage layer and is not affected by this switch.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AgentStorageConfig(BaseModel):
    backend: Literal["file", "db"] = Field(
        default="file",
        description=(
            "Storage backend for custom-agent and managed-subagent definitions. "
            "'file' (default) keeps their on-disk layouts and is node-local without a shared mount. "
            "'db' stores both definition types in the shared SQL persistence layer so a "
            "multi-instance deployment sees the same catalog on every node; it requires "
            "database.backend to be 'sqlite' or 'postgres'."
        ),
    )
