"""Custom-agent definition storage configuration.

Controls where custom agent *definitions* (``config.yaml`` + ``SOUL.md``) are
persisted. This is orthogonal to :class:`DatabaseConfig` (which governs the
run/thread/event persistence layer) and to the deermem memory store.

Backends:
- file: Per-user files under ``{base_dir}/users/{user_id}/agents/{name}/``
  (today's layout, unchanged). Single-node by construction — an agent created
  on one node is invisible to other nodes without a shared mount. This is the
  default so single-node and zero-config development are unaffected.
- db: A row in the ``agents`` table of the existing SQL persistence layer,
  shared by every node. Requires ``database.backend`` to be ``sqlite`` or
  ``postgres`` (validated at startup; see the gateway ``deps`` module).

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
            "Storage backend for custom agent definitions (config.yaml + SOUL.md). "
            "'file' (default) keeps today's per-user on-disk layout — single-node only. "
            "'db' stores each agent as a row in the shared SQL persistence layer so a "
            "multi-instance deployment sees the same agents on every node; it requires "
            "database.backend to be 'sqlite' or 'postgres'."
        ),
    )
