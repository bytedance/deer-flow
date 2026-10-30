"""Private runtime context keys shared across DeerFlow runtime components."""

from collections.abc import Mapping
from typing import Final

from deerflow.runtime.tracing_snapshot import TRACING_CHECKPOINT_KEYS, TRACING_MANAGED_KEY, TRACING_REFERENCE_KEYS

CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: Final[str] = "__deerflow_pre_run_message_ids"

# Server-authored checkpoint metadata that binds materialized state to the
# agent policy which produced it. The sentinel is intentionally not a valid
# custom-agent name, so a missing/invalid legacy value cannot be confused with
# the default agent and accidentally authorize a memory write.
CHECKPOINT_AGENT_NAME_METADATA_KEY: Final[str] = "deerflow_agent_name"
DEFAULT_AGENT_NAME_METADATA_VALUE: Final[str] = "__default__"

# Server-owned pinned project snapshot for a run, resolved once at admission
# (spec §7.1). Holds ``{project_id, name, instructions, shelf, shelf_hash}``.
# Clients can never supply it: it is popped from both run-config sections at
# Gateway admission and refused by the run worker's runtime-context merge.
PROJECT_CONTEXT_KEY: Final[str] = "__deerflow_project_context"


def checkpoint_agent_binding_metadata(metadata: object) -> dict[str, str | bool]:
    """Preserve server-authored agent and tracing bindings during a state rewrite.

    Callers must pass persisted checkpoint metadata, never request metadata.
    Missing or malformed values remain unbound so memory writes fail closed.
    """
    if not isinstance(metadata, Mapping):
        return {}
    result: dict[str, str | bool] = {}
    value = metadata.get(CHECKPOINT_AGENT_NAME_METADATA_KEY)
    if isinstance(value, str) and value:
        result[CHECKPOINT_AGENT_NAME_METADATA_KEY] = value
    present = TRACING_REFERENCE_KEYS.intersection(metadata)
    if present and (present != TRACING_REFERENCE_KEYS or any(not isinstance(metadata[key], str) or not metadata[key] for key in present)):
        raise ValueError("Invalid checkpoint tracing snapshot references")
    for key in TRACING_CHECKPOINT_KEYS:
        if key in metadata:
            if key == TRACING_MANAGED_KEY:
                result[key] = metadata[key] is True
            else:
                result[key] = metadata[key]
    return result
